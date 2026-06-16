import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.controllers.media_host_controller_mixin import MediaHostControllerMixin
from app.exceptions import MediaScanError
from app.models import VideoItem
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


if __name__ == "__main__":
    unittest.main()
