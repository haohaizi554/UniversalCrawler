import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from app.controllers.application_controller import ApplicationController
from app.core.event_bus import EventBus
from app.services.media_library_runtime import MediaLibraryMixin
from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.file_service import ScanResult

class _DummyMediaController(MediaLibraryMixin):
    def __init__(self):
        self.file_service = Mock()
        self.dl_manager = Mock()
        self.videos = {}

    @staticmethod
    def _prepare_local_item(item: VideoItem) -> VideoItem:
        item.status = "✅ 本地"
        item.progress = 100
        return item

class MediaLibraryMixinTests(unittest.TestCase):
    def test_complete_delete_publishes_after_key_state_and_meta_locks_are_released(self):
        cache_service = Mock()
        cache_service.get.return_value = "queue"
        event_bus = EventBus()
        state = AppState(event_bus=event_bus, cache_service=cache_service)
        controller = ApplicationController.__new__(ApplicationController)
        controller.app_state = state
        controller.videos = state.videos
        item = VideoItem(url="", title="old", source="local")
        state.videos[item.id] = item
        context = controller._prepare_delete_video(item.id)
        self.assertIsNotNone(context)

        lock_observations: dict[str, bool] = {}
        probe_threads: list[threading.Thread] = []

        def observe_lock(name, guard_factory):
            acquired = threading.Event()

            def probe():
                with guard_factory():
                    acquired.set()

            thread = threading.Thread(target=probe)
            probe_threads.append(thread)
            thread.start()
            lock_observations[name] = acquired.wait(timeout=0.05)

        def on_state_change(payload):
            if payload.get("topic") != "videos.remove":
                return
            observe_lock("key", lambda: state._media_item_locks.hold(item.id))
            observe_lock("state", lambda: state._lock)
            observe_lock("meta", item.meta_guard)

        event_bus.subscribe("app_state.changed", on_state_change)

        outcome = controller._complete_delete_video(context, deleted=True)
        for thread in probe_threads:
            thread.join(timeout=1)

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(
            lock_observations,
            {"key": True, "state": True, "meta": True},
        )
        self.assertTrue(all(not thread.is_alive() for thread in probe_threads))

    def test_build_scan_summary_message_handles_all_states(self):
        truncated = ScanResult(items=[], total_count=3, video_count=2, image_count=1, truncated=True, original_count=9)
        empty = ScanResult(items=[], total_count=0, video_count=0, image_count=0)
        filled = ScanResult(items=[], total_count=2, video_count=1, image_count=1)

        self.assertIn("仅加载最新的 3 个", _DummyMediaController._build_scan_summary_message(truncated))
        self.assertIn("没有找到视频或图片", _DummyMediaController._build_scan_summary_message(empty))
        self.assertIn("已加载 2 个本地文件", _DummyMediaController._build_scan_summary_message(filled))

    def test_cache_scanned_items_updates_store_and_local_state(self):
        controller = _DummyMediaController()
        item = VideoItem(url="", title="demo", source="local")
        result = ScanResult(items=[item], total_count=1, video_count=1, image_count=0)

        cached = controller._cache_scanned_items(result)

        self.assertEqual(cached, [item])
        self.assertIs(controller.videos[item.id], item)
        self.assertEqual((item.status, item.progress), ("✅ 本地", 100))

    def test_delete_video_sync_returns_messages_and_removes_item(self):
        controller = _DummyMediaController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = r"C:\temp\demo.mp4"
        controller.videos[item.id] = item
        controller.dl_manager.cancel_task.return_value = "running"
        controller.file_service.delete_media.return_value = True

        outcome = controller._delete_video_sync(item.id)

        self.assertEqual(outcome.status, "ok")
        self.assertTrue(outcome.deleted)
        self.assertNotIn(item.id, controller.videos)
        self.assertTrue(any("已删除" in msg for msg in controller._delete_outcome_messages(outcome)))
        self.assertTrue(any("已请求停止下载" in msg for msg in controller._delete_outcome_messages(outcome)))

    def test_delete_video_sync_preserves_store_on_error(self):
        controller = _DummyMediaController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = r"C:\temp\demo.mp4"
        controller.videos[item.id] = item
        controller.dl_manager.cancel_task.return_value = "queued"
        controller.file_service.delete_media.side_effect = FileOperationError("权限不足")

        outcome = controller._delete_video_sync(item.id)

        self.assertEqual(outcome.status, "error")
        self.assertIn(item.id, controller.videos)
        self.assertEqual(outcome.error, "权限不足")

    def test_delete_video_sync_stops_when_same_id_is_replaced_during_cancel(self):
        controller = _DummyMediaController()
        old = VideoItem(url="", title="old", source="local")
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = old.id
        controller.videos[old.id] = old

        class RaceManager:
            def __init__(self):
                self.cancelled_video = None
                self.cancelled_by_id = False

            def cancel_video_and_wait(self, video):
                self.cancelled_video = video
                controller.videos[video.id] = replacement
                return "queued"

            def cancel_task(self, video_id):
                self.cancelled_by_id = True
                controller.videos[video_id] = replacement
                return "queued"

        manager = RaceManager()
        controller.dl_manager = manager

        outcome = controller._delete_video_sync(old.id)

        self.assertEqual(outcome.status, "superseded")
        self.assertIs(controller.videos[old.id], replacement)
        self.assertIs(manager.cancelled_video, old)
        self.assertFalse(manager.cancelled_by_id)
        controller.file_service.delete_media.assert_not_called()

    def test_delete_video_sync_does_not_remove_replacement_inserted_during_file_delete(self):
        controller = _DummyMediaController()
        old = VideoItem(url="", title="old", source="local")
        replacement = VideoItem(url="", title="replacement", source="local")
        replacement.id = old.id
        controller.videos[old.id] = old
        controller.dl_manager.cancel_task.return_value = None

        def replace_during_delete(_video):
            controller.videos[old.id] = replacement
            return True

        controller.file_service.delete_media.side_effect = replace_during_delete

        outcome = controller._delete_video_sync(old.id)

        self.assertEqual(outcome.status, "superseded")
        self.assertIs(controller.videos[old.id], replacement)
        controller.file_service.delete_media.assert_called_once_with(old)

    def test_delete_video_sync_serializes_same_id_replacement_file_publish(self):
        controller = _DummyMediaController()
        delete_started = threading.Event()
        allow_delete = threading.Event()
        replacement_published = threading.Event()
        outcomes = []

        with TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "same-id.mp4"
            media_path.write_bytes(b"old")
            old = VideoItem(url="", title="old", source="local")
            old.local_path = str(media_path)
            replacement = VideoItem(url="", title="replacement", source="local")
            replacement.id = old.id
            replacement.local_path = str(media_path)
            controller.videos[old.id] = old
            controller.dl_manager.cancel_task.return_value = None

            def delete_media(video):
                delete_started.set()
                self.assertTrue(allow_delete.wait(timeout=1))
                Path(video.local_path).unlink()
                return True

            def publish_replacement():
                controller._store_video_item(replacement)
                media_path.write_bytes(b"new")
                replacement_published.set()

            controller.file_service.delete_media.side_effect = delete_media
            delete_thread = threading.Thread(
                target=lambda: outcomes.append(controller._delete_video_sync(old.id))
            )
            delete_thread.start()
            self.assertTrue(delete_started.wait(timeout=1))

            publish_thread = threading.Thread(target=publish_replacement)
            publish_thread.start()
            replacement_blocked_during_delete = not replacement_published.wait(timeout=0.05)
            allow_delete.set()
            delete_thread.join(timeout=1)
            publish_thread.join(timeout=1)

            self.assertTrue(replacement_blocked_during_delete)
            self.assertFalse(delete_thread.is_alive())
            self.assertFalse(publish_thread.is_alive())
            self.assertTrue(replacement_published.is_set())
            self.assertEqual(media_path.read_bytes(), b"new")
            self.assertIs(controller.videos[old.id], replacement)
            self.assertEqual([outcome.status for outcome in outcomes], ["ok"])

    def test_concurrent_delete_contexts_only_delete_the_captured_instance_once(self):
        controller = _DummyMediaController()
        item = VideoItem(url="", title="old", source="local")
        controller.videos[item.id] = item
        controller.dl_manager.cancel_task.return_value = None
        prepared = threading.Barrier(2)
        original_prepare = controller._prepare_delete_video
        delete_lock = threading.Lock()
        second_delete_entered = threading.Event()
        delete_calls = 0
        outcomes = []

        def prepare_together(video_id):
            context = original_prepare(video_id)
            prepared.wait(timeout=1)
            return context

        def delete_media(_video):
            nonlocal delete_calls
            with delete_lock:
                delete_calls += 1
                call_number = delete_calls
            if call_number == 1:
                second_delete_entered.wait(timeout=0.1)
            else:
                second_delete_entered.set()
            return True

        controller._prepare_delete_video = prepare_together
        controller.file_service.delete_media.side_effect = delete_media
        threads = [
            threading.Thread(target=lambda: outcomes.append(controller._delete_video_sync(item.id)))
            for _index in range(2)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(delete_calls, 1)
        self.assertEqual({outcome.status for outcome in outcomes}, {"ok", "superseded"})

    def test_rename_video_sync_updates_path_and_title(self):
        controller = _DummyMediaController()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        controller.file_service.rename_media.return_value = ("old.mp4", "D:/downloads/new.mp4")

        outcome = controller._rename_video_sync(item.id, "新标题", "D:/downloads")

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(item.title, "新标题")
        self.assertEqual(item.local_path, "D:/downloads/new.mp4")
        self.assertIn("重命名", controller._rename_outcome_message(outcome))
