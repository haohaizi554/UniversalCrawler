from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.web.session_runtime import WebSessionRegistry
from app.web.ws_session_binding import WebSocketSessionBinder

class _FakeWebSocket:
    def __init__(self, *, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.url = SimpleNamespace(scheme="ws", netloc="testserver")
        self.closed = None

    async def close(self, *, code: int, reason: str):
        self.closed = (code, reason)

class WebSocketSessionBinderTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self):
        return WebSessionRegistry(
            send_factory=lambda _session_id: lambda _event_type, _data=None: None,
            controller_factory=lambda _loop, _send: SimpleNamespace(current_save_dir="downloads"),
            workflow_factory=lambda _controller, _send: object(),
            pinned_session_ids={"default"},
        )

    async def test_bind_accepts_legacy_local_clients_without_origin(self):
        registry = self._registry()
        binder = WebSocketSessionBinder(registry, default_session_id="default")
        ws = _FakeWebSocket()

        binding = await binder.bind(ws)

        self.assertIsNotNone(binding)
        self.assertEqual(binding.session_id, "default")
        self.assertIsNone(ws.closed)

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

    async def test_bind_rejects_bad_token_when_origin_is_present(self):
        registry = self._registry()
        registry.get_or_create("session-a")
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

if __name__ == "__main__":
    unittest.main()
