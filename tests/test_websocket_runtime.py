from __future__ import annotations

import threading
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import WebSocketDisconnect

from app.web.ws_dispatcher import WebSocketMessageDispatcher
from app.web.ws_runtime import WebSocketRuntime

class _FakeConnectionManager:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, ws):
        self.disconnected.append(ws)

class _FakeDispatcher:
    async def handle(self, msg, context):
        del msg, context

class _OversizedWebSocket:
    def __init__(self):
        self.closed = None

    async def receive_text(self):
        return "x" * (WebSocketRuntime.MAX_MESSAGE_CHARS + 1)

    async def close(self, *, code: int, reason: str):
        self.closed = (code, reason)

class _OneMessageWebSocket:
    def __init__(self):
        self.messages = ['{"type": "noop", "data": {}}']

    async def receive_text(self):
        if self.messages:
            return self.messages.pop(0)
        raise WebSocketDisconnect()

class WebSocketRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_connection_refreshes_and_releases_session_lease(self):
        manager = _FakeConnectionManager()
        runtime = WebSocketRuntime(connection_manager=manager, dispatcher=_FakeDispatcher())
        ws = _OneMessageWebSocket()
        context = SimpleNamespace(
            session_id="session-a",
            mark_websocket_connected=Mock(),
            mark_websocket_disconnected=Mock(),
            touch=Mock(),
        )

        await runtime.run(ws, context)

        context.mark_websocket_connected.assert_called_once()
        context.touch.assert_called_once()
        context.mark_websocket_disconnected.assert_called_once()

    async def test_oversized_message_closes_and_disconnects_connection(self):
        manager = _FakeConnectionManager()
        runtime = WebSocketRuntime(connection_manager=manager, dispatcher=_FakeDispatcher())
        ws = _OversizedWebSocket()
        context = SimpleNamespace(session_id="session-a")

        await runtime.run(ws, context)

        self.assertEqual(ws.closed, (1009, "message too large"))
        self.assertEqual(manager.disconnected, [ws])


class WebSocketMessageDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_without_directory_authorizes_current_save_directory(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(
            current_save_dir="C:/outside",
            async_scan_local_dir=AsyncMock(),
        )
        context = SimpleNamespace(
            controller=controller,
            require_directory=Mock(side_effect=PermissionError("目录未被当前会话授权访问")),
            send=send,
        )

        await dispatcher._handle_scan_dir({}, context)

        context.require_directory.assert_called_once_with("C:/outside")
        controller.async_scan_local_dir.assert_not_awaited()
        self.assertEqual(sent[0][0], "log")
        self.assertIn("授权", sent[0][1]["message"])

    async def test_frontend_action_passes_session_roots_to_controller(self):
        dispatcher = WebSocketMessageDispatcher()
        observed = {}
        sent = []

        class Controller:
            async def async_handle_frontend_action(self, action, payload, approved_roots=None):
                observed["action"] = action
                observed["payload"] = payload
                observed["approved_roots"] = approved_roots
                return {"status": "error", "message": "目录未被当前会话授权访问"}

            def get_frontend_delta(self, frontend_version):
                return {"version": frontend_version, "base_version": frontend_version, "sections": {}}

        async def send(event_type, data):
            sent.append((event_type, data))

        context = SimpleNamespace(
            controller=Controller(),
            approved_roots_snapshot=Mock(return_value=("C:/allowed",)),
            send=send,
        )

        await dispatcher._handle_frontend_action(
            {
                "action": "update_basic_setting",
                "payload": {"key": "download_directory", "value": "C:/allowed/subdir"},
                "frontend_version": 3,
            },
            context,
        )

        self.assertEqual(observed["approved_roots"], ("C:/allowed",))
        self.assertEqual(sent[0][0], "frontend_action_result")
        self.assertEqual(sent[0][1]["status"], "error")

    async def test_sync_frontend_action_passes_session_roots_to_controller(self):
        dispatcher = WebSocketMessageDispatcher()
        observed = {}
        sent = []

        def handle_frontend_action(action, payload, approved_roots=None):
            observed["action"] = action
            observed["payload"] = payload
            observed["approved_roots"] = approved_roots
            return {"status": "ok"}

        async def send(event_type, data):
            sent.append((event_type, data))

        context = SimpleNamespace(
            controller=SimpleNamespace(handle_frontend_action=handle_frontend_action),
            approved_roots_snapshot=Mock(return_value=("C:/allowed",)),
            send=send,
        )

        await dispatcher._handle_frontend_action(
            {
                "action": "update_basic_setting",
                "payload": {"key": "download_directory", "value": "C:/allowed/subdir"},
                "frontend_version": 0,
            },
            context,
        )

        self.assertEqual(observed["approved_roots"], ("C:/allowed",))
        self.assertEqual(sent[0][0], "frontend_action_result")

    async def test_frontend_action_delta_is_built_off_event_loop_thread(self):
        dispatcher = WebSocketMessageDispatcher()
        main_thread = threading.get_ident()
        worker_threads: list[int] = []
        sent = []
        timeline = []

        async def send(event_type, data):
            timeline.append(f"send:{event_type}")
            sent.append((event_type, data))

        class Controller:
            async def async_handle_frontend_action(self, action, payload):
                timeline.append("handler")
                return {"status": "ok", "action": action, "payload": payload}

            def get_frontend_delta(self, frontend_version):
                timeline.append("get_delta")
                worker_threads.append(threading.get_ident())
                return {
                    "version": frontend_version + 1,
                    "changed_sections": ["app_status"],
                    "sections": {},
                }

        context = SimpleNamespace(controller=Controller(), send=send)

        await dispatcher.handle(
            {
                "type": "frontend_action",
                "data": {"action": "refresh_logs", "payload": {"force": True}, "frontend_version": 7},
            },
            context,
        )

        self.assertTrue(worker_threads)
        self.assertNotEqual(worker_threads[0], main_thread)
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_action_result", "frontend_delta"])
        self.assertEqual(
            timeline,
            ["handler", "get_delta", "send:frontend_action_result", "send:frontend_delta"],
        )
        self.assertEqual(sent[0][1]["frontend_delta"], sent[1][1])

    async def test_frontend_action_result_keeps_delta_when_compatibility_delta_is_dropped(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))
            return event_type != "frontend_delta"

        delta = {"version": 4, "base_version": 3, "changed_sections": ["app_status"], "sections": {}}
        controller = SimpleNamespace(
            async_handle_frontend_action=AsyncMock(return_value={"status": "ok"}),
            get_frontend_delta=Mock(return_value=delta),
        )
        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_frontend_action(
            {
                "action": "refresh_platform_auth_status",
                "payload": {"force": False},
                "frontend_version": 3,
                "request_id": "ws-pressure-1",
            },
            context,
        )

        self.assertEqual(sent[0][0], "frontend_action_result")
        self.assertEqual(sent[0][1]["frontend_delta"], delta)

    async def test_frontend_action_still_returns_result_when_delta_build_fails(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(
            async_handle_frontend_action=AsyncMock(return_value={"status": "ok", "message": "saved"}),
            get_frontend_delta=Mock(side_effect=RuntimeError("delta unavailable")),
        )
        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_frontend_action(
            {
                "action": "refresh_platform_auth_status",
                "payload": {"force": False},
                "frontend_version": 3,
                "request_id": "ws-delta-error-1",
            },
            context,
        )

        self.assertEqual([event_type for event_type, _data in sent], ["frontend_action_result"])
        self.assertEqual(sent[0][1]["status"], "ok")
        self.assertEqual(sent[0][1]["request_id"], "ws-delta-error-1")
        self.assertNotIn("frontend_delta", sent[0][1])

    async def test_save_config_enforces_web_allowlist_before_frontend_action(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(async_handle_frontend_action=AsyncMock())
        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_save_config(
            {"section": "common", "key": "user_agent", "value": "unsafe"},
            context,
        )

        controller.async_handle_frontend_action.assert_not_awaited()
        self.assertEqual(sent[0][0], "log")
        self.assertIn("不允许通过 Web 修改", sent[0][1]["message"])

    async def test_save_config_rejects_save_directory_outside_session_roots(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(async_handle_frontend_action=AsyncMock())
        with TemporaryDirectory(ignore_cleanup_errors=True) as allowed_root, TemporaryDirectory(
            ignore_cleanup_errors=True
        ) as outside_root:
            context = SimpleNamespace(
                controller=controller,
                approved_roots_snapshot=Mock(return_value=(allowed_root,)),
                send=send,
            )

            await dispatcher._handle_save_config(
                {"section": "common", "key": "save_directory", "value": outside_root},
                context,
            )

        controller.async_handle_frontend_action.assert_not_awaited()
        self.assertEqual(sent[0][0], "log")
        self.assertIn("授权", sent[0][1]["message"])

    async def test_frontend_action_rejects_hidden_setting_before_controller(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(
            async_handle_frontend_action=AsyncMock(),
        )
        context = SimpleNamespace(
            controller=controller,
            approved_roots_snapshot=Mock(return_value=("C:/allowed",)),
            send=send,
        )

        await dispatcher._handle_frontend_action(
            {
                "action": "update_setting",
                "payload": {"section": "douyin", "key": "user_agent", "value": "unsafe"},
                "frontend_version": 1,
            },
            context,
        )

        controller.async_handle_frontend_action.assert_not_awaited()
        self.assertEqual(sent[0][0], "frontend_action_result")
        self.assertEqual(sent[0][1]["status"], "error")
        self.assertIn("不允许通过 Web 修改", sent[0][1]["message"])

    async def test_frontend_action_rejects_string_boolean_and_echoes_request_id(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(async_handle_frontend_action=AsyncMock())
        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_frontend_action(
            {
                "action": "update_download_options",
                "payload": {"video_only": "false"},
                "frontend_version": 1,
                "request_id": "ws-bool-1",
            },
            context,
        )

        controller.async_handle_frontend_action.assert_not_awaited()
        self.assertEqual(sent[0][0], "frontend_action_result")
        self.assertEqual(sent[0][1]["status"], "error")
        self.assertEqual(sent[0][1]["data"]["code"], "invalid_config_value")
        self.assertEqual(sent[0][1]["request_id"], "ws-bool-1")

    async def test_frontend_action_rejects_explicit_invalid_request_ids(self):
        dispatcher = WebSocketMessageDispatcher()

        for invalid_request_id in (0, False, None, [], "x" * 81):
            with self.subTest(request_id=invalid_request_id):
                sent = []

                async def send(event_type, data):
                    sent.append((event_type, data))

                controller = SimpleNamespace(async_handle_frontend_action=AsyncMock())
                context = SimpleNamespace(controller=controller, send=send)

                await dispatcher._handle_frontend_action(
                    {
                        "action": "refresh_platform_auth_status",
                        "payload": {"force": False},
                        "request_id": invalid_request_id,
                    },
                    context,
                )

                controller.async_handle_frontend_action.assert_not_awaited()
                self.assertEqual(sent[0][0], "frontend_action_result")
                self.assertEqual(sent[0][1]["data"]["code"], "invalid_request_id")

    async def test_frontend_action_echoes_request_id_before_delta(self):
        dispatcher = WebSocketMessageDispatcher()
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        controller = SimpleNamespace(
            async_handle_frontend_action=AsyncMock(return_value={"status": "ok"}),
            get_frontend_delta=Mock(
                return_value={"version": 2, "base_version": 1, "changed_sections": [], "sections": {}}
            ),
        )
        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_frontend_action(
            {
                "action": "refresh_platform_auth_status",
                "payload": {"force": False},
                "frontend_version": 1,
                "request_id": "ws-action-2",
            },
            context,
        )

        self.assertEqual([event_type for event_type, _data in sent], ["frontend_action_result", "frontend_delta"])
        self.assertEqual(sent[0][1]["request_id"], "ws-action-2")

    async def test_save_config_invokes_sync_handler_without_approved_roots_parameter(self):
        dispatcher = WebSocketMessageDispatcher()
        observed = []

        def handle_frontend_action(action, payload):
            observed.append((action, payload))
            return {"status": "ok"}

        async def send(_event_type, _data):
            return None

        context = SimpleNamespace(
            controller=SimpleNamespace(handle_frontend_action=handle_frontend_action),
            send=send,
        )

        await dispatcher._handle_save_config(
            {"section": "appearance", "key": "language", "value": "en-US"},
            context,
        )

        self.assertEqual(
            observed,
            [("update_setting", {"section": "appearance", "key": "language", "value": "en-US"})],
        )

    async def test_save_config_uses_authorizer_alias_for_appearance_theme(self):
        dispatcher = WebSocketMessageDispatcher()
        controller = SimpleNamespace(async_handle_frontend_action=AsyncMock(return_value={"status": "ok"}))

        async def send(_event_type, _data):
            return None

        context = SimpleNamespace(controller=controller, send=send)

        await dispatcher._handle_save_config(
            {"section": "appearance", "key": "theme", "value": "dark"},
            context,
        )

        controller.async_handle_frontend_action.assert_awaited_once_with(
            "update_setting",
            {"section": "appearance", "key": "theme", "value": "dark"},
            approved_roots=None,
        )

if __name__ == "__main__":
    unittest.main()
