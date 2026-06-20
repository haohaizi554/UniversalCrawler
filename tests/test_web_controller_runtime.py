import unittest
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.models import VideoItem

def _signal():
    return SimpleNamespace(connect=Mock())

class WebControllerRuntimeTests(unittest.TestCase):
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

    def test_shutdown_does_not_create_download_manager_for_idle_session(self):
        from app.web.controller import WebController

        with patch("app.web.controller.DownloadManager") as mocked_manager:
            controller = WebController(None, lambda *_args, **_kwargs: None)
            controller.shutdown()

        mocked_manager.assert_not_called()

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

    def test_video_store_snapshot_and_clear_are_lock_guarded(self):
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        item = VideoItem(url="https://example.com/a.mp4", title="a", source="douyin")

        controller._store_video_item(item)
        snapshot = controller._video_items_snapshot()
        snapshot[item.id].title = "mutated"
        controller._clear_video_items()

        self.assertIsNot(snapshot[item.id], item)
        self.assertEqual(item.title, "a")
        self.assertEqual(controller._video_count(), 0)

    def test_async_frontend_delete_action_uses_async_delete_video(self):
        import asyncio
        from app.web.controller import WebController

        controller = WebController(None, lambda *_args, **_kwargs: None)
        controller.async_delete_video = AsyncMock()

        result = asyncio.run(controller.async_handle_frontend_action("delete_item", {"id": "video-1"}))

        self.assertEqual(result["status"], "ok")
        controller.async_delete_video.assert_awaited_once_with("video-1")

if __name__ == "__main__":
    unittest.main()
