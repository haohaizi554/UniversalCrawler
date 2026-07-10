from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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
    async def test_frontend_action_delta_is_built_off_event_loop_thread(self):
        dispatcher = WebSocketMessageDispatcher()
        main_thread = threading.get_ident()
        worker_threads: list[int] = []
        sent = []

        async def send(event_type, data):
            sent.append((event_type, data))

        class Controller:
            async def async_handle_frontend_action(self, action, payload):
                return {"status": "ok", "action": action, "payload": payload}

            def get_frontend_delta(self, frontend_version):
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

if __name__ == "__main__":
    unittest.main()
