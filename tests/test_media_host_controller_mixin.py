import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.controllers.media_host_controller_mixin import MediaHostControllerMixin
from app.exceptions import MediaScanError
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.file_service import ScanResult

class _DummyMediaHostController(MediaHostControllerMixin):
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    def __init__(self):
        self.host = Mock()
        self.videos = {}
        self.current_playing_id = None

    def _host(self):
        return self.host

    def _cache_scanned_items(self, result):
        for item in result.items:
            self.videos[item.id] = item
        return list(result.items)

    @staticmethod
    def _build_scan_messages(result):
        return [f"loaded {result.total_count}"]

    def _scan_media_directory(self, directory):
        return self._scan_result

    def _rename_video_sync(self, vid, title, save_dir):
        return self._rename_outcome

    def _rename_outcome_message(self, outcome):
        return f"renamed:{outcome.new_title}" if getattr(outcome, "new_title", None) else ""

    def _delete_video_sync(self, vid):
        return self._delete_outcome

    @staticmethod
    def _delete_outcome_messages(outcome):
        return getattr(outcome, "messages", [])

class MediaHostControllerMixinTests(unittest.TestCase):
    def test_current_playing_id_prefers_app_state_over_stale_controller_mirror(self):
        controller = _DummyMediaHostController()
        controller.current_playing_id = "stale"
        controller.app_state = Mock()
        controller.app_state.current_playing_id = "fresh"
        controller.app_state.get_current_playing_id.side_effect = lambda: controller.app_state.current_playing_id

        def set_current_playing_id(video_id):
            controller.app_state.current_playing_id = video_id

        controller.app_state.set_current_playing_id.side_effect = set_current_playing_id

        self.assertEqual(controller._get_current_playing_id(), "fresh")
        self.assertEqual(controller.current_playing_id, "fresh")

        controller._set_current_playing_id("next")

        controller.app_state.set_current_playing_id.assert_called_once_with("next")
        self.assertEqual(controller.current_playing_id, "next")

    def test_scan_local_dir_announces_scan_and_populates_rows(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "downloads"
        item = VideoItem(url="", title="demo", source="local")
        controller._scan_result = ScanResult(items=[item], total_count=1, video_count=1, image_count=0)

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.scan_local_dir()

        controller.host.announce_scan_start.assert_called_once_with("downloads")
        controller.host.clear_video_rows.assert_called_once()
        controller.host.add_video_row.assert_called_once_with(item)
        controller.host.append_log.assert_called_once_with("loaded 1")

    def test_scan_local_dir_reports_media_scan_error(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "downloads"

        def _raise(_directory):
            raise MediaScanError("权限不足")

        controller._scan_media_directory = _raise

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.scan_local_dir()

        controller.host.report_scan_error.assert_called_once()

    def test_on_dir_changed_announces_and_rescans(self):
        controller = _DummyMediaHostController()
        controller.host.current_save_dir = "D:/downloads"
        controller.scan_local_dir = Mock()

        with patch("app.controllers.media_host_controller_mixin.debug_logger", Mock()):
            controller.on_dir_changed()

        controller.host.announce_directory_changed.assert_called_once_with("D:/downloads")
        controller.scan_local_dir.assert_called_once()

    def test_on_rename_video_reports_error_and_resets_text(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller._rename_outcome = type("Outcome", (), {"status": "error", "error": "权限不足", "new_title": None})()

        controller.on_rename_video(table_item)

        controller.host.report_rename_error.assert_called_once_with("权限不足")
        table_item.setText.assert_called_once_with("旧标题")

    def test_on_rename_video_reorders_row_after_success(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller._rename_outcome = type("Outcome", (), {"status": "ok", "error": None, "new_title": "新标题"})()

        controller.on_rename_video(table_item)

        controller.host.reorder_video_row.assert_called_once_with(item)

    def test_on_delete_video_missing_entry_removes_row_only(self):
        controller = _DummyMediaHostController()

        controller.on_delete_video(3, "missing")

        controller.host.remove_video_row.assert_called_once_with(3)
        controller.host.refresh_table_bindings.assert_not_called()

    def test_play_video_reports_missing_media(self):
        controller = _DummyMediaHostController()
        item = VideoItem(url="", title="demo", source="local")
        item.local_path = "Z:/missing.mp4"
        controller.videos[item.id] = item

        controller.play_video(item.id)

        controller.host.report_missing_media.assert_called_once()

    def test_play_video_routes_image_and_video_to_correct_host_action(self):
        controller = _DummyMediaHostController()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "demo.jpg")
            video_path = os.path.join(temp_dir, "demo.mp4")
            with open(image_path, "wb") as handle:
                handle.write(b"image")
            with open(video_path, "wb") as handle:
                handle.write(b"video")

            image_item = VideoItem(url="", title="image", source="local")
            image_item.local_path = image_path
            video_item = VideoItem(url="", title="video", source="local")
            video_item.local_path = video_path
            controller.videos[image_item.id] = image_item
            controller.videos[video_item.id] = video_item

            controller.play_video(image_item.id)
            controller.play_video(video_item.id)

        controller.host.show_image.assert_called_once_with(image_path)
        controller.host.play_video.assert_called_once_with(video_path)

    def test_switch_preview_selects_adjacent_video_in_host_order(self):
        controller = _DummyMediaHostController()
        first = VideoItem(url="", title="one", source="local")
        second = VideoItem(url="", title="two", source="local")
        controller.current_playing_id = first.id
        controller.host.get_adjacent_video_id.return_value = second.id
        controller.play_video = Mock()

        controller.switch_preview(1)

        controller.host.get_adjacent_video_id.assert_called_once_with(first.id, 1, wrap=True)
        controller.host.select_video_by_id.assert_called_once_with(second.id)
        controller.play_video.assert_called_once_with(second.id)

    def test_autoplay_next_preview_stops_at_end_without_wrap(self):
        controller = _DummyMediaHostController()
        current = VideoItem(url="", title="one", source="local")
        controller.current_playing_id = current.id
        controller.host.get_adjacent_video_id.return_value = None
        controller.play_video = Mock()

        controller.autoplay_next_preview()

        controller.host.get_adjacent_video_id.assert_called_once_with(current.id, 1, wrap=False)
        controller.host.append_log.assert_called_once_with("ℹ️ 已播放到最后一项")
        controller.play_video.assert_not_called()

    def test_on_clear_queue_removes_queue_items_and_keeps_completed(self):
        controller = _DummyMediaHostController()
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "\u23f3 \u7b49\u5f85\u4e2d"
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "\u2705 \u672c\u5730"
        completed.progress = 100
        completed.local_path = __file__
        controller.app_state = Mock()
        controller.app_state.videos = {queued.id: queued, completed.id: completed}
        controller.app_state.task_state = {queued.id: {"progress": 0}}
        controller.app_state._last_progress_emit_at = {queued.id: 1.0}
        controller.app_state._lock = threading.RLock()
        controller.app_state._publish_change = Mock()
        controller.videos = controller.app_state.videos
        controller.dl_manager = Mock()
        controller.dl_manager.cancel_task.return_value = "queued"
        controller.frontend_state_service = Mock()
        controller.frontend_state_service.queue_item_ids = Mock(return_value={queued.id})
        controller.frontend_state_service.get_snapshot.side_effect = AssertionError("full snapshot should not be used")

        controller.on_clear_queue()

        self.assertNotIn(queued.id, controller.app_state.videos)
        self.assertIn(completed.id, controller.app_state.videos)
        self.assertNotIn(queued.id, controller.app_state.task_state)
        self.assertNotIn(queued.id, controller.app_state._last_progress_emit_at)
        controller.dl_manager.cancel_task.assert_called_once_with(queued.id)
        controller.app_state._publish_change.assert_called_once_with(
            "videos.remove_many",
            {"video_ids": [queued.id], "count": 1},
        )
        controller.host.append_log.assert_called_once_with("\U0001f5d1\ufe0f \u5df2\u6e05\u7a7a\u4e0b\u8f7d\u961f\u5217 (1 \u9879)")
        controller.host.refresh_frontend_state.assert_called_once_with(force=False, topics={"videos.remove_many"})

    def test_on_clear_queue_batches_large_queue_without_snapshot(self):
        controller = _DummyMediaHostController()
        controller.app_state = AppState()
        items = [VideoItem(url=f"https://example.com/{index}.mp4", title=f"queued-{index}", source="douyin") for index in range(10000)]
        for item in items:
            item.status = "\u23f3 \u7b49\u5f85\u4e2d"
        ids = {item.id for item in items}
        with controller.app_state._lock:
            controller.app_state.videos = {item.id: item for item in items}
            controller.app_state.task_state = {item.id: {"progress": 0} for item in items}
        controller.videos = controller.app_state.videos
        controller.dl_manager = SimpleNamespace(cancel_tasks=Mock(return_value={video_id: "queued" for video_id in ids}))
        controller.frontend_state_service = SimpleNamespace(
            queue_item_ids=Mock(return_value=ids),
            get_snapshot=Mock(side_effect=AssertionError("full snapshot should not be used")),
        )

        controller.on_clear_queue()

        self.assertEqual(controller.app_state.videos, {})
        self.assertEqual(controller.app_state.task_state, {})
        controller.frontend_state_service.queue_item_ids.assert_called_once()
        controller.frontend_state_service.get_snapshot.assert_not_called()
        controller.dl_manager.cancel_tasks.assert_called_once()
        self.assertEqual(len(next(iter(controller.dl_manager.cancel_tasks.call_args.args))), 10000)
        controller.host.refresh_frontend_state.assert_called_once_with(force=False, topics={"videos.remove_many"})

if __name__ == "__main__":
    unittest.main()
