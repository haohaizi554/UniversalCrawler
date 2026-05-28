"""测试模块，覆盖 `tests/test_integration_flows.py` 对应功能的行为与回归场景。"""

import os
import tempfile
import unittest
from unittest.mock import Mock

from app.controllers.application_controller import ApplicationController
from app.core.download_manager import DownloadWorker
from app.models import VideoItem
from app.spiders.base import BaseSpider
from app.spiders.douyin.parser import DouyinItemParser


class DummySpider(BaseSpider):
    """封装 `DummySpider` 对应的平台采集、登录或任务编排逻辑。"""
    def run(self):
        """执行当前对象或脚本的主流程，供 `DummySpider` 使用。"""
        return None


class IntegrationFlowTests(unittest.TestCase):
    """封装 `IntegrationFlowTests` 在 `tests/test_integration_flows.py` 中承担的核心逻辑。"""
    def _make_controller(self) -> ApplicationController:
        """提供 `_make_controller` 对应的内部辅助逻辑，供 `IntegrationFlowTests` 使用。"""
        controller = ApplicationController.__new__(ApplicationController)
        controller.window = Mock()
        controller.window.current_save_dir = "downloads"
        controller.file_service = Mock()
        controller.dl_manager = Mock()
        controller.videos = {}
        controller.current_playing_id = None
        return controller

    def test_parser_to_controller_to_download_manager_preserves_video_item_data(self):
        """验证 `test_parser_to_controller_to_download_manager_preserves_video_item_data` 对应场景是否符合预期，供 `IntegrationFlowTests` 使用。"""
        parser = DouyinItemParser()
        controller = self._make_controller()
        item = parser.parse_aweme(
            {
                "aweme_id": "aweme-1",
                "desc": "集成测试视频",
                "author": {"nickname": "集成作者"},
                "video": {"duration": 8000, "play_addr": {"url_list": ["https://cdn.example.com/video.mp4"]}},
            }
        )

        controller._on_spider_item_found(item)

        cached = controller.videos[item.id]
        self.assertEqual(cached.id, item.id)
        self.assertEqual(cached.title, "集成测试视频")
        self.assertEqual(cached.meta["trace_id"], "dy-aweme-1")
        self.assertEqual(cached.status, "⏳ 等待中")
        controller.window.add_video_row.assert_called_once_with(item)
        controller.dl_manager.add_task.assert_called_once_with(item, "downloads")

    def test_spider_emit_video_reaches_controller_queue_handler(self):
        """验证 `test_spider_emit_video_reaches_controller_queue_handler` 对应场景是否符合预期，供 `IntegrationFlowTests` 使用。"""
        spider = DummySpider("关键字", {})
        controller = self._make_controller()
        spider.sig_item_found.connect(controller._on_spider_item_found)

        spider.emit_video(
            url="https://cdn.example.com/video.mp4",
            title="来自爬虫",
            source="douyin",
            meta={"trace_id": "trace-emit"},
        )

        self.assertEqual(len(controller.videos), 1)
        item = next(iter(controller.videos.values()))
        self.assertEqual(item.title, "来自爬虫")
        self.assertEqual(item.meta["trace_id"], "trace-emit")
        controller.dl_manager.add_task.assert_called_once_with(item, "downloads")

    def test_download_worker_run_emits_lifecycle_and_normalizes_extension(self):
        """验证 `test_download_worker_run_emits_lifecycle_and_normalizes_extension` 对应场景是否符合预期，供 `IntegrationFlowTests` 使用。"""
        item = VideoItem(url="https://cdn.example.com/file.bin", title="完成链路", source="douyin")
        worker = DownloadWorker(item, "")
        events = {"start": [], "progress": [], "finished": [], "errors": []}
        worker.sig_start.connect(events["start"].append)
        worker.sig_finished.connect(events["finished"].append)
        worker.sig_progress.connect(lambda _video_id, progress: events["progress"].append(progress))
        worker.sig_error.connect(lambda video_id, message: events["errors"].append((video_id, message)))

        class FakeDownloader:
            """实现 `FakeDownloader` 对应的资源下载与落盘流程。"""
            def download(self, video_item, save_path, progress_callback, check_stop_func):
                """执行 `download` 对应的业务逻辑，供 `FakeDownloader` 使用。"""
                progress_callback(55)
                with open(save_path, "wb") as fp:
                    fp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)

        with tempfile.TemporaryDirectory() as temp_dir:
            worker.save_dir = temp_dir
            worker._select_downloader = Mock(return_value=FakeDownloader())

            worker.run()

            self.assertTrue(os.path.exists(worker.video.local_path))
            self.assertTrue(worker.video.local_path.endswith(".png"))

        self.assertEqual(events["start"], [item.id])
        self.assertIn(55, events["progress"])
        self.assertEqual(events["finished"], [item.id])
        self.assertEqual(events["errors"], [])


if __name__ == "__main__":
    unittest.main()
