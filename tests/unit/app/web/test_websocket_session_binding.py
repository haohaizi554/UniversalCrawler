from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.web.session_runtime import WebSessionCapacityError, WebSessionRegistry
from app.web.ws_session_binding import WebSocketSessionBinder

class _FakeWebSocket:
    def __init__(self, *, cookies=None, headers=None, client_host="127.0.0.1"):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.url = SimpleNamespace(scheme="ws", netloc="testserver")
        self.client = SimpleNamespace(host=client_host)
        self.closed = None

    async def close(self, *, code: int, reason: str):
        self.closed = (code, reason)

class WebSocketSessionBinderTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self, **kwargs):
        return WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: SimpleNamespace(current_save_dir="downloads"),
            workflow_factory=lambda _controller, _send: object(),
            pinned_session_ids={"default"},
            **kwargs,
        )

    async def test_bind_rejects_local_clients_without_session_token(self):
        registry = self._registry()
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket()

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "invalid session token"))

    async def test_bind_uses_http_session_cookie_name(self):
        registry = self._registry()
        context = registry.get_or_create("session-a")
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_session": "session-a",
                "ucrawl_session_token": context.session_token,
            },
            headers={"origin": "http://testserver"},
        )

        binding = await binder.bind(ws)

        self.assertIsNotNone(binding)
        self.assertEqual(binding.session_id, "session-a")
        self.assertIs(binding.context, context)
        self.assertIsNone(ws.closed)
        self.assertTrue(context.has_active_websocket())
        binding.release()
        binding.release()
        self.assertFalse(context.has_active_websocket())

    async def test_bind_rejects_bad_token_when_origin_is_present(self):
        registry = self._registry()
        context = registry.get_or_create("session-a")
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_session": "session-a",
                "ucrawl_session_token": "bad",
            },
            headers={"origin": "http://testserver"},
        )

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "invalid session token"))
        self.assertEqual(registry._contexts, {"session-a": context})
        self.assertFalse(context.has_active_websocket())
        self.assertFalse(registry._contexts["session-a"].has_active_websocket())

    async def test_bind_rejects_remote_client_without_origin_or_token(self):
        registry = self._registry()
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket(client_host="192.0.2.10")

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "forbidden origin"))
        self.assertEqual(registry._contexts, {})

    async def test_bind_requires_configured_application_access_token_before_session_token(self):
        registry = self._registry()
        context = registry.get_or_create("session-a")
        binder = WebSocketSessionBinder(
            registry,
            default_session_id="default",
            access_token="application-access-token",
            access_cookie_name="ucrawl_access_token",
        )
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_session": "session-a",
                "ucrawl_session_token": context.session_token,
            },
            headers={"origin": "http://testserver"},
            client_host="192.0.2.10",
        )

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "invalid access token"))

    async def test_bind_rejects_remote_client_with_valid_tokens_but_missing_origin(self):
        registry = self._registry()
        context = registry.get_or_create("session-a")
        binder = WebSocketSessionBinder(
            registry,
            default_session_id="default",
            access_token="application-access-token",
            access_cookie_name="ucrawl_access_token",
        )
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_access_token": "application-access-token",
                "ucrawl_session": "session-a",
                "ucrawl_session_token": context.session_token,
            },
            client_host="192.0.2.10",
        )

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "forbidden origin"))

    async def test_bind_rejects_capacity_exhaustion_with_retry_later_code(self):
        registry = self._registry()
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket()
        original_acquire = registry.acquire_websocket_context

        def reject_session(_session_id, _session_token):
            raise WebSessionCapacityError("session capacity exhausted")

        registry.acquire_websocket_context = reject_session
        try:
            binding = await binder.bind(ws)
        finally:
            registry.acquire_websocket_context = original_acquire

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1013, "session capacity exhausted"))

    async def test_unknown_session_token_cannot_create_or_evict_a_context(self):
        shutdown = Mock()

        class _Controller:
            current_save_dir = "downloads"

            def shutdown(self):
                shutdown()

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: _Controller(),
            workflow_factory=lambda _controller, _send: object(),
            max_contexts=1,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        existing = registry.get_or_create("existing-session")
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_session": "unknown-session",
                "ucrawl_session_token": "attacker-token",
            },
            headers={"origin": "http://testserver"},
        )

        binding = await binder.bind(ws)

        self.assertIsNone(binding)
        self.assertEqual(ws.closed, (1008, "invalid session token"))
        self.assertEqual(registry._contexts, {"existing-session": existing})
        shutdown.assert_not_called()
        registry.shutdown_all(wait=True, timeout=1.0)

    async def test_binding_reserves_context_before_runtime_can_be_evicted(self):
        controllers = []

        class _Controller:
            current_save_dir = "downloads"

            def __init__(self):
                self.shutdown_calls = 0

            def shutdown(self):
                self.shutdown_calls += 1

        def controller_factory(_loop, _send):
            controller = _Controller()
            controllers.append(controller)
            return controller

        registry = WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=controller_factory,
            workflow_factory=lambda _controller, _send: object(),
            max_contexts=1,
            disposal_workers=1,
            disposal_queue_capacity=0,
        )
        context = registry.get_or_create("session-a")
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket(
            cookies={
                "ucrawl_session": "session-a",
                "ucrawl_session_token": context.session_token,
            },
            headers={"origin": "http://testserver"},
        )

        binding = await binder.bind(ws)

        self.assertIsNotNone(binding)
        with self.assertRaises(WebSessionCapacityError):
            registry.get_or_create("session-b")
        self.assertIs(registry._contexts["session-a"], context)
        self.assertEqual(controllers[0].shutdown_calls, 0)

        binding.release()
        registry.get_or_create("session-b")
        for _ in range(100):
            if controllers[0].shutdown_calls:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(controllers[0].shutdown_calls, 1)
        registry.shutdown_all(wait=True, timeout=1.0)
        self.assertEqual(controllers[0].shutdown_calls, 1)

if __name__ == "__main__":
    unittest.main()
