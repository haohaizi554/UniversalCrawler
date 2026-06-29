import asyncio
import threading
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

class _DeferredLoop(_FakeLoop):
    def call_later(self, delay, callback, *args):
        self.call_later_calls.append((delay, callback, args))

    def run_later_callbacks(self):
        callbacks = list(self.call_later_calls)
        self.call_later_calls.clear()
        for _delay, callback, args in callbacks:
            callback(*args)

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

    def test_progress_event_uses_frontend_delta_without_legacy_echo(self):
        loop = _FakeLoop()
        sent = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(_base_version):
            return {
                "version": 1,
                "changed_sections": ["active_downloads", "app_status"],
                "sections": {"active_downloads": [{"id": "v1", "progress": 50}]},
            }

        bridge = WebSocketBridge(
            loop,
            send_func,
            event_recorder=lambda _topic, _payload: None,
            delta_provider=delta_provider,
        )

        bridge.emit("video_state_changed", {"video_id": "v1", "progress": 50})

        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta"])

    def test_log_event_uses_frontend_delta_without_legacy_echo(self):
        loop = _FakeLoop()
        sent = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(_base_version):
            return {
                "version": 1,
                "changed_sections": ["log_items", "app_status"],
                "sections": {"log_items": [{"message": "tick"}]},
            }

        bridge = WebSocketBridge(
            loop,
            send_func,
            event_recorder=lambda _topic, _payload: None,
            delta_provider=delta_provider,
        )

        bridge.emit("log", {"message": "tick"})

        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta"])

    def test_log_event_keeps_legacy_message_without_delta_provider(self):
        loop = _FakeLoop()
        sent = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        bridge = WebSocketBridge(loop, send_func)

        bridge.emit("log", {"message": "tick"})

        self.assertEqual(sent, [("log", {"message": "tick"})])

    def test_noisy_events_share_single_delayed_frontend_delta(self):
        loop = _DeferredLoop()
        sent = []
        delta_bases = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(base_version):
            delta_bases.append(base_version)
            return {
                "version": 1,
                "changed_sections": ["active_downloads", "log_items", "app_status"],
                "sections": {},
            }

        bridge = WebSocketBridge(loop, send_func, delta_provider=delta_provider)

        for index in range(100):
            bridge.emit("video_state_changed", {"video_id": "v1", "progress": index})
            bridge.emit("log", {"trace_id": "trace-1", "message": f"line-{index}"})

        self.assertEqual(len(loop.call_later_calls), 1)
        self.assertEqual(sent, [])
        self.assertEqual(delta_bases, [])

        loop.run_later_callbacks()

        self.assertEqual(delta_bases, [0])
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta"])

    def test_concurrent_noisy_events_share_single_delayed_frontend_delta(self):
        loop = _DeferredLoop()
        sent = []
        delta_bases = []
        errors: list[BaseException] = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(base_version):
            delta_bases.append(base_version)
            return {
                "version": 1,
                "changed_sections": ["active_downloads", "log_items", "app_status"],
                "sections": {},
            }

        bridge = WebSocketBridge(loop, send_func, delta_provider=delta_provider)

        def emit_many(thread_index: int) -> None:
            try:
                for index in range(100):
                    bridge.emit(
                        "video_state_changed",
                        {"video_id": f"v{thread_index}", "progress": index},
                    )
                    bridge.emit("log", {"trace_id": f"trace-{thread_index}", "message": f"line-{index}"})
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=emit_many, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(loop.call_later_calls), 1)
        self.assertEqual(sent, [])
        self.assertEqual(delta_bases, [])

        loop.run_later_callbacks()

        self.assertEqual(delta_bases, [0])
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta"])

    def test_stale_delayed_delta_flush_is_skipped_after_critical_flush(self):
        loop = _DeferredLoop()
        sent = []
        delta_bases = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(base_version):
            delta_bases.append(base_version)
            return {
                "version": len(delta_bases),
                "changed_sections": ["active_downloads", "app_status"],
                "sections": {},
            }

        bridge = WebSocketBridge(loop, send_func, delta_provider=delta_provider)

        bridge.emit("video_state_changed", {"video_id": "v1", "progress": 10})
        self.assertEqual(len(loop.call_later_calls), 1)

        bridge.emit("task_error", {"video_id": "v1", "error": "boom"})

        self.assertEqual(delta_bases, [0])
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta", "task_error"])

        loop.run_later_callbacks()

        self.assertEqual(delta_bases, [0])
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta", "task_error"])

    def test_critical_event_keeps_legacy_message_when_delta_enabled(self):
        loop = _FakeLoop()
        sent = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(_base_version):
            return {
                "version": 1,
                "changed_sections": ["queue_items", "active_downloads", "completed_items", "failed_items", "app_status"],
                "sections": {},
            }

        bridge = WebSocketBridge(loop, send_func, delta_provider=delta_provider)

        bridge.emit("task_finished", {"video_id": "v1"})

        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta", "task_finished"])

    def test_dropped_delta_does_not_advance_acknowledged_version(self):
        sent = []
        delta_bases = []

        def send_func(event_type, data):
            sent.append((event_type, data))

        def delta_provider(base_version):
            delta_bases.append(base_version)
            return {
                "version": len(delta_bases),
                "changed_sections": ["queue_items", "app_status"],
                "sections": {},
            }

        bridge = WebSocketBridge(None, send_func, delta_provider=delta_provider)

        bridge.emit("task_finished", {"video_id": "v1"})

        self.assertEqual(delta_bases, [0])
        self.assertEqual(sent, [])
        self.assertEqual(bridge._last_delta_version, 0)

        bridge.set_loop(_FakeLoop())
        bridge.emit("task_finished", {"video_id": "v2"})

        self.assertEqual(delta_bases, [0, 0])
        self.assertEqual([event_type for event_type, _data in sent], ["frontend_delta", "task_finished"])
        self.assertEqual(bridge._last_delta_version, 2)

    def test_async_send_rejection_does_not_acknowledge_delta_version(self):
        async def scenario():
            sent = []

            async def send_func(event_type, data):
                sent.append((event_type, data))
                if event_type == "frontend_delta":
                    return False
                return True

            def delta_provider(base_version):
                return {
                    "version": base_version + 1,
                    "changed_sections": ["active_downloads", "app_status"],
                    "sections": {},
                }

            bridge = WebSocketBridge(
                asyncio.get_running_loop(),
                send_func,
                delta_provider=delta_provider,
            )

            bridge.emit("task_finished", {"video_id": "v1"})
            for _ in range(5):
                await asyncio.sleep(0)

            event_types = [event_type for event_type, _data in sent]
            self.assertEqual(len(event_types), 2)
            self.assertIn("frontend_delta", event_types)
            self.assertIn("task_finished", event_types)
            self.assertEqual(bridge._last_delta_version, 0)

        asyncio.run(scenario())

    def test_async_send_acceptance_acknowledges_delta_version(self):
        async def scenario():
            async def send_func(event_type, data):
                return True

            def delta_provider(base_version):
                return {
                    "version": base_version + 3,
                    "changed_sections": ["active_downloads", "app_status"],
                    "sections": {},
                }

            bridge = WebSocketBridge(
                asyncio.get_running_loop(),
                send_func,
                delta_provider=delta_provider,
            )

            bridge.emit("task_finished", {"video_id": "v1"})
            for _ in range(5):
                await asyncio.sleep(0)

            self.assertEqual(bridge._last_delta_version, 3)

        asyncio.run(scenario())

if __name__ == "__main__":
    unittest.main()
