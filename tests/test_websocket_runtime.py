from __future__ import annotations

import unittest
from types import SimpleNamespace

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

class WebSocketRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_message_closes_and_disconnects_connection(self):
        manager = _FakeConnectionManager()
        runtime = WebSocketRuntime(connection_manager=manager, dispatcher=_FakeDispatcher())
        ws = _OversizedWebSocket()
        context = SimpleNamespace(session_id="session-a")

        await runtime.run(ws, context)

        self.assertEqual(ws.closed, (1009, "message too large"))
        self.assertEqual(manager.disconnected, [ws])

if __name__ == "__main__":
    unittest.main()
