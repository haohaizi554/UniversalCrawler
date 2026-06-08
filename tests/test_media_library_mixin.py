import unittest
from unittest.mock import Mock

from app.controllers.media_library_mixin import MediaLibraryMixin
from app.exceptions import FileOperationError
from app.models import VideoItem
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

