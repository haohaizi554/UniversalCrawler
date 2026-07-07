import unittest
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.exceptions import FileOperationError
from app.models import VideoItem

def _signal():
    return SimpleNamespace(connect=Mock())

class WebControllerRuntimeTests(unittest.TestCase):
    def _controller_with_video(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        item = VideoItem(url="https://example.com/a.mp4", title="a", source="douyin")
        controller._store_video_item(item)
        return controller, item

    @staticmethod
    def _video_state_events(controller):
        return [
            call.args[1]
            for call in controller.bridge.emit.call_args_list
            if call.args and call.args[0] == "video_state_changed"
        ]

    def test_init_does_not_create_download_manager_until_needed(self):
        from app.web.controller import WebController

        fake_manager = SimpleNamespace(
            task_started=_signal(),
            task_progress=_signal(),
            task_finished=_signal(),
            task_error=_signal(),
        )

        with patch("app.web.controller.DownloadManager", return_value=fake_manager) as mocked_manager:
            controller = WebController(None, lambda *_args, **_kwargs: None)

            self.assertIsNone(controller._dl_manager)
            mocked_manager.assert_not_called()

            manager = controller.dl_manager

        self.assertIs(manager, fake_manager)
        mocked_manager.assert_called_once()
        fake_manager.task_started.connect.assert_called_once_with(controller._on_task_started)
        fake_manager.task_progress.connect.assert_called_once_with(controller._on_task_progress)
        fake_manager.task_finished.connect.assert_called_once_with(controller._on_task_finished)
        fake_manager.task_error.connect.assert_called_once_with(controller._on_task_error)

    def test_on_spider_item_found_skips_image_when_video_only_enabled(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        controller._dl_manager = SimpleNamespace(video_only=True, add_task=Mock())
        item = VideoItem(url="https://example.com/cover.jpg", title="cover", source="xiaohongshu")
        item.meta["content_type"] = "image/jpeg"

        controller._on_spider_item_found(item)

        self.assertEqual(controller._video_count(), 0)
        controller.bridge.emit.assert_not_called()
        controller._dl_manager.add_task.assert_not_called()


    def test_shutdown_does_not_create_download_manager_for_idle_session(self):
        from app.web.controller import WebController

        with patch("app.web.controller.DownloadManager") as mocked_manager:
            controller = WebController(None, lambda *_args, **_kwargs: None)
            controller.shutdown()

        mocked_manager.assert_not_called()

    def test_shutdown_releases_frontend_state_and_cache_resources(self):
        from app.web.controller import WebController

        frontend_state = Mock()
        frontend_state.app_state = Mock()
        frontend_state.cache_service = Mock()

        with patch("app.web.controller.FrontendStateService", return_value=frontend_state):
            controller = WebController(None, lambda *_args, **_kwargs: None)

        controller.shutdown()

        frontend_state.destroy.assert_called_once()
        frontend_state.app_state.shutdown.assert_called_once()
        frontend_state.cache_service.close.assert_called_once()

    def test_start_crawl_waits_for_shutdown_lifecycle_lock(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        entered_shutdown_wait = threading.Event()
        release_shutdown = threading.Event()
        started: list[bool] = []

        class FakeSpider:
            def __init__(self):
                self.running = True
                self.stopped = False

            def isRunning(self):
                return self.running

            def stop(self):
                self.stopped = True

            def wait(self, _timeout_ms):
                entered_shutdown_wait.set()
                release_shutdown.wait(timeout=1)
                self.running = False
                return True

        def fake_start(*_args):
            started.append(True)

        controller.current_spider = FakeSpider()
        controller._start_crawl_unlocked = fake_start

        shutdown_thread = threading.Thread(target=controller.shutdown)
        shutdown_thread.start()
        self.assertTrue(entered_shutdown_wait.wait(timeout=1))

        start_thread = threading.Thread(target=lambda: controller.start_crawl("douyin", "demo", {}))
        start_thread.start()
        time.sleep(0.05)
        self.assertEqual(started, [])

        release_shutdown.set()
        shutdown_thread.join(timeout=1)
        start_thread.join(timeout=1)

        self.assertEqual(started, [True])

    def test_shutdown_wait_does_not_block_spider_finished_callback(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()
        entered_shutdown_wait = threading.Event()
        release_shutdown = threading.Event()

        class FakeSpider:
            def isRunning(self):
                return True

            def stop(self):
                pass

            def wait(self, _timeout_ms):
                entered_shutdown_wait.set()
                release_shutdown.wait(timeout=1)
                return True

        controller.current_spider = FakeSpider()
        shutdown_thread = threading.Thread(target=controller.shutdown)
        shutdown_thread.start()
        self.assertTrue(entered_shutdown_wait.wait(timeout=1))

        finished_thread = threading.Thread(target=controller._on_spider_finished)
        finished_thread.start()
        finished_thread.join(timeout=0.5)
        self.assertFalse(finished_thread.is_alive())

        release_shutdown.set()
        shutdown_thread.join(timeout=1)

    def test_resume_selection_none_requests_spider_stop(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.bridge.emit = Mock()

        class FakeSpider:
            def __init__(self):
                self.running = True
                self.interrupt_requested = False
                self.stopped = False
                self.resumed_with = object()

            def isRunning(self):
                return self.running

            def stop(self):
                self.stopped = True
                self.interrupt_requested = True
                self.running = False

            def resume_from_ui(self, value):
                self.resumed_with = value

        spider = FakeSpider()
        controller.current_spider = spider

        controller.resume_spider_selection(None)

        self.assertTrue(spider.stopped)
        self.assertIsNone(spider.resumed_with)
        self.assertIsNone(controller.current_spider)
        controller.bridge.emit.assert_any_call("crawl_state", {"is_running": False})

    def test_video_store_snapshot_and_clear_are_lock_guarded(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        item = VideoItem(url="https://example.com/a.mp4", title="a", source="douyin")

        controller._store_video_item(item)
        controller._on_task_progress(item.id, 55)
        self.assertIn(item.id, controller._last_progress_emit_at)
        snapshot = controller._video_items_snapshot()
        snapshot[item.id].title = "mutated"
        controller._clear_video_items()

        self.assertIsNot(snapshot[item.id], item)
        self.assertEqual(item.title, "a")
        self.assertEqual(controller._video_count(), 0)
        self.assertEqual(controller._last_progress_emit_at, {})
        self.assertEqual(controller._last_progress_emit_value, {})

    def test_async_frontend_delete_action_uses_async_delete_video(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock()

        result = asyncio.run(controller.async_handle_frontend_action("delete_item", {"id": "video-1"}))

        self.assertEqual(result["status"], "ok")
        controller.async_delete_video.assert_awaited_once_with("video-1")

    def test_async_frontend_delete_action_propagates_delete_failure(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock(
            return_value={"status": "error", "message": "permission denied", "data": {"video_id": "video-1"}}
        )

        result = asyncio.run(controller.async_handle_frontend_action("delete_item", {"id": "video-1"}))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        controller.async_delete_video.assert_awaited_once_with("video-1")

    def test_async_delete_video_preserves_item_on_file_delete_error(self):
        import asyncio

        controller, item = self._controller_with_video()
        controller._dl_manager = SimpleNamespace(cancel_task=Mock(return_value=None))
        controller.file_service.delete_media = Mock(side_effect=FileOperationError("permission denied"))

        result = asyncio.run(controller.async_delete_video(item.id))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "permission denied")
        self.assertIs(controller._video_lookup(item.id), item)
        controller.file_service.delete_media.assert_called_once_with(item)

    def test_progress_signal_is_throttled_inside_time_window(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 10)
        controller._on_task_progress(item.id, 11)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [10])

        controller._last_progress_emit_at[item.id] -= controller.PROGRESS_EVENT_MIN_INTERVAL_SECONDS
        controller._on_task_progress(item.id, 11)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [10, 11])

    def test_progress_signal_drops_duplicate_value_even_after_interval(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 42)
        controller._last_progress_emit_at[item.id] -= controller.PROGRESS_EVENT_MIN_INTERVAL_SECONDS
        controller._on_task_progress(item.id, 42)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [42])

    def test_terminal_progress_bypasses_throttle(self):
        controller, item = self._controller_with_video()

        controller._on_task_progress(item.id, 20)
        controller._on_task_progress(item.id, 100)

        events = self._video_state_events(controller)
        self.assertEqual([event["progress"] for event in events], [20, 100])

    def test_progress_emit_state_is_removed_when_task_finishes(self):
        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)
        self.assertIn(item.id, controller._last_progress_emit_at)

        controller._on_task_finished(item.id)

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

    def test_progress_emit_state_is_removed_when_task_fails_or_is_deleted(self):
        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)

        controller._on_task_error(item.id, "network timeout")

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

        controller, item = self._controller_with_video()
        controller._on_task_progress(item.id, 55)
        controller._remove_video_item(item.id)

        self.assertNotIn(item.id, controller._last_progress_emit_at)
        self.assertNotIn(item.id, controller._last_progress_emit_value)

if __name__ == "__main__":
    unittest.main()
