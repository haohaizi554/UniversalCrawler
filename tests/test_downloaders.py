import asyncio
import queue
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from app.core.download_manager import DownloadManager, DownloadWorker
from app.core.lib.douyin.tools.session import create_client, request_params
from app.core.downloaders import (
    BilibiliDownloader,
    ChunkedDownloader,
    DouyinDownloader,
    FFmpegDownloader,
    KuaishouDownloader,
    MissAVDownloader,
    N_m3u8DL_RE_Downloader,
)
from app.models import VideoItem


class DownloaderStrategyTests(unittest.TestCase):
    def test_source_downloaders_can_handle_matching_items(self):
        self.assertTrue(DouyinDownloader.can_handle(VideoItem(url="https://example.com/1", title="a", source="douyin")))
        self.assertTrue(KuaishouDownloader.can_handle(VideoItem(url="https://example.com/2", title="b", source="kuaishou")))
        self.assertTrue(MissAVDownloader.can_handle(VideoItem(url="https://example.com/3", title="c", source="missav")))
        self.assertTrue(BilibiliDownloader.can_handle(VideoItem(url="https://example.com/4", title="d", source="bilibili")))

    def test_m3u8_url_detection(self):
        self.assertTrue(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/master.m3u8"))
        self.assertFalse(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/video.mp4"))

    def test_chunked_downloader_threshold(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["size_mb"] = 250
        self.assertTrue(ChunkedDownloader.should_use(item))

    def test_ffmpeg_downloader_threshold(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["duration"] = 601
        self.assertTrue(FFmpegDownloader.should_use(item))

    def test_download_worker_uses_registered_downloader(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        self.assertIsInstance(worker._select_downloader(), DouyinDownloader)

    @patch("app.core.downloaders.missav.N_m3u8DL_RE_Downloader.download")
    def test_missav_downloader_delegates_to_m3u8(self, mocked_download):
        item = VideoItem(url="https://example.com/master.m3u8", title="demo", source="missav")
        downloader = MissAVDownloader()

        downloader.download(item, "demo.mp4", lambda _: None, lambda: False)

        mocked_download.assert_called_once()
        self.assertEqual(item.meta.get("referer"), "https://missav.ai/")

    @patch("app.core.downloaders.m3u8.N_m3u8DL_RE_Downloader.is_available", return_value=True)
    @patch("app.core.downloaders.m3u8.N_m3u8DL_RE_Downloader.download")
    def test_douyin_downloader_routes_m3u8_to_m3u8_tool(self, mocked_download, _mocked_available):
        item = VideoItem(url="https://example.com/live/index.m3u8", title="demo", source="douyin")
        downloader = DouyinDownloader()

        downloader.download(item, "demo.mp4", lambda _: None, lambda: False)

        mocked_download.assert_called_once()

    @patch("app.core.lib.douyin.tools.session.AsyncClient")
    def test_create_client_enables_ssl_verification_by_default(self, mocked_async_client):
        create_client()

        self.assertTrue(mocked_async_client.call_args.kwargs["verify"])

    @patch("app.core.lib.douyin.tools.session.request", new_callable=AsyncMock, return_value={})
    @patch("app.core.lib.douyin.tools.session.Client")
    def test_request_params_enables_ssl_verification_by_default(self, mocked_client, _mocked_request):
        client = Mock()
        mocked_client.return_value.__enter__.return_value = client
        mocked_client.return_value.__exit__.return_value = False

        asyncio.run(request_params(Mock(), "https://example.com/api", method="GET"))

        self.assertTrue(mocked_client.call_args.kwargs["verify"])

    def test_download_manager_stop_all_waits_with_timeout(self):
        manager = DownloadManager.__new__(DownloadManager)
        manager.is_running = True
        manager.queue = queue.Queue()
        manager.dispatcher_thread = Mock()
        manager._workers_lock = threading.Lock()
        worker = Mock()
        worker.video = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        worker.wait.return_value = False
        manager.workers = [worker]

        manager.stop_all()

        worker.stop.assert_called_once()
        worker.wait.assert_called_once_with(DownloadManager.WORKER_STOP_TIMEOUT_MS)
        manager.dispatcher_thread.join.assert_called_once_with(timeout=2)

    def test_video_item_update_from_dict_uses_field_whitelist(self):
        item = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")

        item.update_from_dict(
            {
                "status": "done",
                "meta": {"trace_id": "abc"},
                "get_safe_filename": "hijacked",
                "unknown_field": "ignored",
            }
        )

        self.assertEqual(item.status, "done")
        self.assertEqual(item.meta["trace_id"], "abc")
        self.assertTrue(callable(item.get_safe_filename))
        self.assertFalse(hasattr(item, "unknown_field"))

    @patch("app.core.downloaders.kuaishou.requests.get", side_effect=requests.RequestException("skip probe"))
    @patch.object(KuaishouDownloader, "_download_with_strategy_fallback")
    @patch("app.core.downloaders.kuaishou.cfg.get")
    def test_kuaishou_downloader_prefers_kuaishou_user_agent_config(
        self,
        mocked_cfg_get,
        mocked_download,
        _mocked_requests_get,
    ):
        def fake_get(section, key, default=None):
            if (section, key) == ("kuaishou", "user_agent"):
                return "kuaishou-ua"
            return default

        mocked_cfg_get.side_effect = fake_get
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="kuaishou")

        KuaishouDownloader().download(item, "demo.mp4", lambda _: None, lambda: False)

        self.assertEqual(mocked_download.call_args.kwargs["headers"]["User-Agent"], "kuaishou-ua")

    @patch("app.core.downloaders.kuaishou.requests.get", side_effect=requests.RequestException("skip probe"))
    @patch.object(KuaishouDownloader, "_download_with_strategy_fallback")
    @patch("app.core.downloaders.kuaishou.cfg.get", return_value="config-ua")
    def test_kuaishou_downloader_allows_task_level_user_agent_override(
        self,
        _mocked_cfg_get,
        mocked_download,
        _mocked_requests_get,
    ):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="kuaishou")
        item.meta["ua"] = "meta-ua"

        KuaishouDownloader().download(item, "demo.mp4", lambda _: None, lambda: False)

        self.assertEqual(mocked_download.call_args.kwargs["headers"]["User-Agent"], "meta-ua")


if __name__ == "__main__":
    unittest.main()
