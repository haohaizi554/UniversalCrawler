import os
import tempfile
import unittest
from unittest.mock import Mock

from app.controllers.application_controller import ApplicationController
from app.models import VideoItem


class ApplicationControllerTests(unittest.TestCase):
    def _make_controller(self) -> ApplicationController:
        controller = ApplicationController.__new__(ApplicationController)
        controller.window = Mock()
        controller.file_service = Mock()
        controller.videos = {}
        controller.current_playing_id = None
        return controller

    def test_clear_local_items_uses_window_api(self):
        controller = self._make_controller()
        controller.videos = {"v1": VideoItem(url="https://example.com", title="demo", source="local")}

        controller._clear_local_items()

        controller.window.clear_video_rows.assert_called_once()
        self.assertEqual(controller.videos, {})

    def test_on_delete_video_stops_preview_and_removes_row(self):
        controller = self._make_controller()
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="local")
        item.local_path = r"C:\temp\demo.mp4"
        controller.videos[item.id] = item
        controller.current_playing_id = item.id
        controller.file_service.delete_media.return_value = True

        controller.on_delete_video(2, item.id)

        controller.window.stop_media_playback.assert_called_once()
        controller.window.remove_video_row.assert_called_once_with(2)
        controller.window.refresh_table_bindings.assert_called_once()
        self.assertNotIn(item.id, controller.videos)
        self.assertIsNone(controller.current_playing_id)

    def test_play_video_routes_images_to_image_preview(self):
        controller = self._make_controller()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "demo.jpg")
            with open(image_path, "wb") as fp:
                fp.write(b"image")
            item = VideoItem(url="", title="image", source="local")
            item.local_path = image_path
            controller.videos[item.id] = item

            controller.play_video(item.id)

            controller.window.show_image.assert_called_once_with(image_path)
            controller.window.play_video.assert_not_called()

    def test_play_video_routes_videos_to_media_panel(self):
        controller = self._make_controller()
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "demo.mp4")
            with open(video_path, "wb") as fp:
                fp.write(b"video")
            item = VideoItem(url="", title="video", source="local")
            item.local_path = video_path
            controller.videos[item.id] = item

            controller.play_video(item.id)

            controller.window.play_video.assert_called_once_with(video_path)
            controller.window.show_image.assert_not_called()

    def test_on_start_crawl_rejects_duplicate_running_spider(self):
        controller = self._make_controller()
        controller.current_spider = Mock()
        controller.current_spider.isRunning.return_value = True
        controller._create_spider = Mock()

        controller.on_start_crawl("关键词", "douyin", {})

        controller.window.append_log.assert_called_once()
        controller._create_spider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
