import unittest
from unittest.mock import patch

from app.web.controller import WebSocketBridge

class _FakeLoop:
    def __init__(self):
        self.soon_calls = []
        self.created_coroutines = []
        self.call_soon_calls = []
        self.call_later_calls = []

    def is_closed(self):
        return False

    def is_running(self):
        return True

    def call_soon_threadsafe(self, callback, *args):
        self.soon_calls.append((callback, args))
        callback(*args)

    def call_soon(self, callback, *args):
        self.call_soon_calls.append((callback, args))
        callback(*args)

    def call_later(self, delay, callback, *args):
        self.call_later_calls.append((delay, callback, args))
        callback(*args)

    def create_task(self, coro):
        self.created_coroutines.append(coro)
        coro.close()
        return object()

class WebSocketBridgeTests(unittest.TestCase):
    def test_emit_schedules_broadcast_on_target_loop_thread_safely(self):
        loop = _FakeLoop()

        async def send_func(event_type, data):
            return {"event_type": event_type, "data": data}

        bridge = WebSocketBridge(loop, send_func)
        bridge.emit("select_tasks", {"items": [1, 2, 3]})

        self.assertEqual(len(loop.soon_calls), 1)
        self.assertEqual(len(loop.created_coroutines), 1)

    def test_emit_ignores_foreign_running_loop_and_uses_bound_loop(self):
        target_loop = _FakeLoop()
        foreign_loop = _FakeLoop()

        async def send_func(event_type, data):
            return {"event_type": event_type, "data": data}

        bridge = WebSocketBridge(target_loop, send_func)
        with patch("app.web.controller.asyncio.get_running_loop", return_value=foreign_loop):
            bridge.emit("select_tasks", {"items": [4, 5, 6]})

        self.assertEqual(len(foreign_loop.call_soon_calls), 0)
        self.assertEqual(len(target_loop.soon_calls), 1)
        self.assertEqual(len(target_loop.created_coroutines), 1)

    def test_metadata_event_schedules_frontend_delta(self):
        loop = _FakeLoop()
        recorded = []
        delta_bases = []

        async def send_func(event_type, data):
            return {"event_type": event_type, "data": data}

        def delta_provider(base_version):
            delta_bases.append(base_version)
            return {
                "version": 1,
                "changed_sections": ["completed_items", "app_status"],
                "sections": {"completed_items": []},
            }

        bridge = WebSocketBridge(
            loop,
            send_func,
            event_recorder=lambda topic, payload: recorded.append((topic, payload)),
            delta_provider=delta_provider,
        )

        bridge.emit("videos.metadata", {"video_id": "done", "metadata": True})

        self.assertEqual(recorded, [("videos.metadata", {"video_id": "done", "metadata": True})])
        self.assertEqual(delta_bases, [0])
        self.assertEqual(len(loop.call_later_calls), 1)
        self.assertEqual(len(loop.created_coroutines), 2)

if __name__ == "__main__":
    unittest.main()
