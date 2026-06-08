"""测试模块，覆盖 `tests/test_downloaders.py` 对应功能的行为与回归场景。"""

import asyncio
import os
import queue
import subprocess
import tempfile
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
    FFmpegExternalTool,
    KuaishouDownloader,
    MissAVDownloader,
    NM3U8DLREExternalTool,
    N_m3u8DL_RE_Downloader,
)
from app.core.downloaders.external import ExternalToolRunner
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError, MergeError, StreamDownloadError
from app.models import VideoItem


class DownloaderStrategyTests(unittest.TestCase):
    """封装 `DownloaderStrategyTests` 在 `tests/test_downloaders.py` 中承担的核心逻辑。"""
    def _make_stream_response(self, chunks, headers=None, status_code=200):
        """提供 `_make_stream_response` 对应的内部辅助逻辑，供 `DownloaderStrategyTests` 使用。"""
        response = Mock()
        response.headers = headers or {}
        response.status_code = status_code
        response.iter_content.return_value = iter(chunks)
        response.raise_for_status.return_value = None
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_source_downloaders_can_handle_matching_items(self):
        """验证 `test_source_downloaders_can_handle_matching_items` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        self.assertTrue(DouyinDownloader.can_handle(VideoItem(url="https://example.com/1", title="a", source="douyin")))
        self.assertTrue(KuaishouDownloader.can_handle(VideoItem(url="https://example.com/2", title="b", source="kuaishou")))
        self.assertTrue(MissAVDownloader.can_handle(VideoItem(url="https://example.com/3", title="c", source="missav")))
        self.assertTrue(BilibiliDownloader.can_handle(VideoItem(url="https://example.com/4", title="d", source="bilibili")))

    def test_m3u8_url_detection(self):
        """验证 `test_m3u8_url_detection` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        self.assertTrue(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/master.m3u8"))
        self.assertFalse(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/video.mp4"))

    def test_chunked_downloader_threshold(self):
        """验证 `test_chunked_downloader_threshold` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["size_mb"] = 250
        self.assertTrue(ChunkedDownloader.should_use(item))

    def test_ffmpeg_downloader_threshold(self):
        """验证 `test_ffmpeg_downloader_threshold` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["duration"] = 601
        self.assertTrue(FFmpegDownloader.should_use(item))

    @patch("app.core.downloaders.external.resolve_tool_file")
    def test_external_tool_runner_resolve_executable_prefers_local_tool_file(self, mocked_resolve_tool_file):
        """验证 `test_external_tool_runner_resolve_executable_prefers_local_tool_file` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        local_path = Mock()
        local_path.exists.return_value = True
        mocked_resolve_tool_file.return_value = local_path

        result = ExternalToolRunner.resolve_executable("ffmpeg.exe", "ffmpeg")

        self.assertEqual(result, str(local_path))

    @patch("app.core.downloaders.external.subprocess.run")
    @patch("app.core.downloaders.external.resolve_tool_file")
    def test_external_tool_runner_resolve_executable_falls_back_to_cli(self, mocked_resolve_tool_file, mocked_run):
        """验证 `test_external_tool_runner_resolve_executable_falls_back_to_cli` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        local_path = Mock()
        local_path.exists.return_value = False
        mocked_resolve_tool_file.return_value = local_path

        result = ExternalToolRunner.resolve_executable("ffmpeg.exe", "ffmpeg", ["-version"])

        self.assertEqual(result, "ffmpeg")
        mocked_run.assert_called_once()

    @patch("app.core.downloaders.external.subprocess.run", side_effect=OSError("missing"))
    @patch("app.core.downloaders.external.resolve_tool_file")
    def test_external_tool_runner_resolve_executable_returns_none_when_all_missing(self, mocked_resolve_tool_file, _mocked_run):
        """验证 `test_external_tool_runner_resolve_executable_returns_none_when_all_missing` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        local_path = Mock()
        local_path.exists.return_value = False
        mocked_resolve_tool_file.return_value = local_path

        self.assertIsNone(ExternalToolRunner.resolve_executable("ffmpeg.exe", "ffmpeg"))

    @patch("app.core.downloaders.external.time.sleep", return_value=None)
    def test_external_tool_runner_wait_process_reports_progress_until_exit(self, _mocked_sleep):
        """验证 `test_external_tool_runner_wait_process_reports_progress_until_exit` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        process = Mock()
        process.poll.side_effect = [None, None, 0]
        progress = []

        ExternalToolRunner.wait_process(process, lambda: False, progress.append, 50, poll_interval=0)

        self.assertEqual(progress, [50, 50])
        self.assertEqual(process.poll.call_count, 3)
        process.kill.assert_not_called()

    @patch("app.core.downloaders.external.time.sleep", return_value=None)
    def test_external_tool_runner_wait_process_kills_process_when_stopped(self, _mocked_sleep):
        """验证 `test_external_tool_runner_wait_process_kills_process_when_stopped` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        process = Mock()
        process.poll.return_value = None

        with self.assertRaises(DownloaderStoppedError):
            ExternalToolRunner.wait_process(process, lambda: True, poll_interval=0)

        process.kill.assert_called_once()

    def test_ffmpeg_external_tool_build_merge_command_skips_audio_when_none(self):
        """验证 `test_ffmpeg_external_tool_build_merge_command_skips_audio_when_none` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        command = FFmpegExternalTool.build_merge_command("ffmpeg.exe", "video.m4s", None, "output.mp4")

        self.assertEqual(command, ["ffmpeg.exe", "-y", "-i", "video.m4s", "-c", "copy", "output.mp4"])

    def test_ffmpeg_external_tool_build_download_command_contains_headers_and_target(self):
        """验证 `test_ffmpeg_external_tool_build_download_command_contains_headers_and_target` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        command = FFmpegExternalTool.build_download_command(
            "ffmpeg.exe",
            "https://cdn.example.com/master.m3u8",
            "video.mp4",
            {"User-Agent": "ua-demo", "Referer": "https://www.douyin.com/"},
        )

        self.assertIn("-user_agent", command)
        self.assertIn("ua-demo", command)
        self.assertIn("-progress", command)
        self.assertIn("pipe:2", command)
        self.assertIn("-nostats", command)
        self.assertIn("Referer: https://www.douyin.com/\r\n", command)
        self.assertEqual(command[-1], "video.mp4")

    @patch("app.core.downloaders.ffmpeg.requests.head")
    @patch("app.core.downloaders.ffmpeg.subprocess.Popen")
    @patch("app.core.downloaders.ffmpeg.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    def test_ffmpeg_downloader_reports_structured_progress(
        self,
        _mocked_resolve,
        mocked_popen,
        mocked_head,
    ):
        """ffmpeg 结构化 progress 输出应能持续映射为百分比，而不是只显示起止状态。"""
        head_response = Mock()
        head_response.url = "https://cdn.example.com/video.mp4"
        head_response.status_code = 200
        head_response.headers = {"content-length": "4096"}
        mocked_head.return_value = head_response

        process = Mock()
        process.stderr.readline.side_effect = [
            b"out_time_ms=1000\n",
            b"progress=continue\n",
            b"out_time_ms=5000\n",
            b"progress=end\n",
            b"",
        ]
        process.poll.return_value = 0
        process.returncode = 0
        mocked_popen.return_value = process

        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["duration"] = 10
        progress = []

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            with open(save_path, "wb") as fp:
                fp.write(b"done")
            FFmpegDownloader().download(item, save_path, progress.append, lambda: False)

        self.assertEqual(progress, [10, 50, 100])

    def test_ffmpeg_progress_parser_treats_large_out_time_ms_as_microseconds(self):
        """较新的 FFmpeg 会把 out_time_ms 输出为微秒值，不能按毫秒直接换算。"""
        next_duration, _, progress_value = FFmpegDownloader._parse_progress_line(
            "out_time_ms=11066667",
            expected_duration=820.0,
            expected_size_bytes=None,
        )

        self.assertEqual(next_duration, 820.0)
        self.assertEqual(progress_value, 1)

    @patch("app.core.downloaders.ffmpeg.time.sleep", return_value=None)
    @patch("app.core.downloaders.ffmpeg.requests.head")
    @patch("app.core.downloaders.ffmpeg.subprocess.Popen")
    @patch("app.core.downloaders.ffmpeg.os.path.getsize", return_value=1024)
    @patch("app.core.downloaders.ffmpeg.os.path.exists", return_value=True)
    @patch("app.core.downloaders.ffmpeg.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    def test_ffmpeg_downloader_refreshes_douyin_stream_url_between_retries(
        self,
        _mocked_resolve,
        _mocked_exists,
        _mocked_getsize,
        mocked_popen,
        mocked_head,
        _mocked_sleep,
    ):
        """抖音 play_url 失败重试时应重新解析可用 CDN，而不是死用同一条失效地址。"""
        head_first = Mock()
        head_first.url = "https://cdn1.example.com/video.mp4"
        head_first.status_code = 200
        head_first.headers = {"content-length": "4096"}
        head_second = Mock()
        head_second.url = "https://cdn2.example.com/video.mp4"
        head_second.status_code = 200
        head_second.headers = {"content-length": "8192"}
        mocked_head.side_effect = [head_first, head_second]

        failed_process = Mock()
        failed_process.stderr.readline.side_effect = [b"", b""]
        failed_process.poll.side_effect = [1]
        failed_process.returncode = 1

        success_process = Mock()
        success_process.stderr.readline.side_effect = [b"progress=end\n", b""]
        success_process.poll.side_effect = [0]
        success_process.returncode = 0

        mocked_popen.side_effect = [failed_process, success_process]

        item = VideoItem(
            url="https://www.douyin.com/aweme/v1/play/?video_id=demo",
            title="demo",
            source="douyin",
        )
        item.meta["duration"] = 12

        progress = []
        FFmpegDownloader().download(item, "demo.mp4", progress.append, lambda: False)

        self.assertEqual(mocked_head.call_count, 2)
        first_cmd = mocked_popen.call_args_list[0].args[0]
        second_cmd = mocked_popen.call_args_list[1].args[0]
        self.assertEqual(first_cmd[first_cmd.index("-i") + 1], "https://cdn1.example.com/video.mp4")
        self.assertEqual(second_cmd[second_cmd.index("-i") + 1], "https://cdn2.example.com/video.mp4")
        self.assertEqual(progress, [100])

    def test_nm3u8_external_tool_build_download_command_uses_headers_and_save_name(self):
        """验证 `test_nm3u8_external_tool_build_download_command_uses_headers_and_save_name` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        command = NM3U8DLREExternalTool.build_download_command(
            "N_m3u8DL-RE.exe",
            "https://cdn.example.com/live/index.m3u8",
            os.path.join("downloads", "demo.mp4"),
            "ua-demo",
            "https://www.douyin.com/",
        )

        self.assertIn("--save-dir", command)
        self.assertIn("--save-name", command)
        self.assertIn("User-Agent: ua-demo", command)
        self.assertIn("Referer: https://www.douyin.com/", command)

    def test_download_worker_uses_registered_downloader(self):
        """验证 `test_download_worker_uses_registered_downloader` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        self.assertIsInstance(worker._select_downloader(), DouyinDownloader)

    @patch("app.core.downloaders.missav.N_m3u8DL_RE_Downloader.download")
    def test_missav_downloader_delegates_to_m3u8(self, mocked_download):
        """验证 `test_missav_downloader_delegates_to_m3u8` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/master.m3u8", title="demo", source="missav")
        downloader = MissAVDownloader()

        downloader.download(item, "demo.mp4", lambda _: None, lambda: False)

        mocked_download.assert_called_once()
        self.assertEqual(item.meta.get("referer"), "https://missav.ai/")

    @patch("app.core.downloaders.m3u8.N_m3u8DL_RE_Downloader.is_available", return_value=True)
    @patch("app.core.downloaders.m3u8.N_m3u8DL_RE_Downloader.download")
    def test_douyin_downloader_routes_m3u8_to_m3u8_tool(self, mocked_download, _mocked_available):
        """验证 `test_douyin_downloader_routes_m3u8_to_m3u8_tool` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/live/index.m3u8", title="demo", source="douyin")
        downloader = DouyinDownloader()

        downloader.download(item, "demo.mp4", lambda _: None, lambda: False)

        mocked_download.assert_called_once()

    @patch.object(DouyinDownloader, "_download_with_strategy_fallback")
    @patch("app.core.downloaders.douyin.requests.head", side_effect=requests.RequestException("skip head"))
    def test_douyin_downloader_prefers_task_runtime_headers(self, _mocked_head, mocked_download):
        """验证 `test_douyin_downloader_prefers_task_runtime_headers` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta.update({"ua": "task-ua", "referer": "https://www.douyin.com/user/demo"})

        DouyinDownloader().download(item, "demo.mp4", lambda _: None, lambda: False)

        self.assertEqual(mocked_download.call_args.kwargs["headers"]["User-Agent"], "task-ua")
        self.assertEqual(mocked_download.call_args.kwargs["headers"]["Referer"], "https://www.douyin.com/user/demo")

    @patch.object(DouyinDownloader, "_download_file")
    def test_douyin_gallery_download_uses_live_and_image_extensions(self, mocked_download_file):
        """验证 `test_douyin_gallery_download_uses_live_and_image_extensions` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/cover.jpg", title="图集", source="douyin")
        downloader = DouyinDownloader()

        downloader._download_gallery(
            item,
            [
                {"live_video_url": "https://cdn.example.com/live.mp4", "image_url": ""},
                {"live_video_url": "", "image_url": "https://cdn.example.com/cover.webp"},
            ],
            os.path.join("downloads", "demo.mp4"),
            lambda _value: None,
            lambda: False,
            {"User-Agent": "ua", "Referer": "https://www.douyin.com/"},
        )

        self.assertEqual(mocked_download_file.call_args_list[0].args[1], os.path.join("downloads", "图集_1.mp4"))
        self.assertEqual(mocked_download_file.call_args_list[1].args[1], os.path.join("downloads", "图集_2.webp"))

    @patch("app.core.lib.douyin.tools.session.AsyncClient")
    def test_create_client_enables_ssl_verification_by_default(self, mocked_async_client):
        """验证 `test_create_client_enables_ssl_verification_by_default` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        create_client()

        self.assertTrue(mocked_async_client.call_args.kwargs["verify"])
        self.assertFalse(mocked_async_client.call_args.kwargs["trust_env"])
        self.assertNotIn("mounts", mocked_async_client.call_args.kwargs)

    @patch("app.core.lib.douyin.tools.session.AsyncClient")
    def test_create_client_only_builds_proxy_mounts_when_proxy_configured(self, mocked_async_client):
        """验证 `create_client` 仅在配置代理时才创建 transport mounts。"""
        create_client(proxy="http://127.0.0.1:7890")

        self.assertIn("mounts", mocked_async_client.call_args.kwargs)
        self.assertEqual(
            sorted(mocked_async_client.call_args.kwargs["mounts"].keys()),
            ["http://", "https://"],
        )

    @patch("app.core.lib.douyin.tools.session.request", new_callable=AsyncMock, return_value={})
    @patch("app.core.lib.douyin.tools.session.Client")
    def test_request_params_enables_ssl_verification_by_default(self, mocked_client, _mocked_request):
        """验证 `test_request_params_enables_ssl_verification_by_default` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        client = Mock()
        mocked_client.return_value.__enter__.return_value = client
        mocked_client.return_value.__exit__.return_value = False

        asyncio.run(request_params(Mock(), "https://example.com/api", method="GET"))

        self.assertTrue(mocked_client.call_args.kwargs["verify"])
        self.assertFalse(mocked_client.call_args.kwargs["trust_env"])
        self.assertNotIn("mounts", mocked_client.call_args.kwargs)

    @patch("app.core.lib.douyin.tools.session.request", new_callable=AsyncMock, return_value={})
    @patch("app.core.lib.douyin.tools.session.Client")
    def test_request_params_only_builds_proxy_mounts_when_proxy_configured(self, mocked_client, _mocked_request):
        """验证 `request_params` 仅在配置代理时才创建 transport mounts。"""
        client = Mock()
        mocked_client.return_value.__enter__.return_value = client
        mocked_client.return_value.__exit__.return_value = False

        asyncio.run(
            request_params(
                Mock(),
                "https://example.com/api",
                method="GET",
                proxy="http://127.0.0.1:7890",
            )
        )

        self.assertIn("mounts", mocked_client.call_args.kwargs)

    @patch("app.core.downloaders.chunked.requests.head", side_effect=requests.RequestException("boom"))
    def test_chunked_downloader_raises_when_head_request_fails(self, _mocked_head):
        """验证 `test_chunked_downloader_raises_when_head_request_fails` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with self.assertRaises(StreamDownloadError):
            ChunkedDownloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    @patch("app.core.downloaders.chunked.requests.head")
    def test_chunked_downloader_rejects_missing_content_length(self, mocked_head):
        """验证 `test_chunked_downloader_rejects_missing_content_length` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        head_response = Mock()
        head_response.headers = {"content-length": "0", "accept-ranges": "bytes"}
        head_response.raise_for_status.return_value = None
        mocked_head.return_value = head_response
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with self.assertRaises(StreamDownloadError):
            ChunkedDownloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    @patch("app.core.downloaders.chunked.requests.head")
    def test_chunked_downloader_rejects_servers_without_range_support(self, mocked_head):
        """验证 `test_chunked_downloader_rejects_servers_without_range_support` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        head_response = Mock()
        head_response.headers = {"content-length": str(ChunkedDownloader.CHUNK_SIZE * 2), "accept-ranges": "none"}
        head_response.raise_for_status.return_value = None
        mocked_head.return_value = head_response
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with self.assertRaises(StreamDownloadError):
            ChunkedDownloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    @patch("app.core.downloaders.bilibili.subprocess.run")
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.build_merge_command", return_value=["ffmpeg", "-i", "video", "output"])
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_downloader_downloads_video_only_streams_when_audio_missing(
        self,
        mocked_get,
        _mocked_resolve,
        mocked_build_merge,
        mocked_subprocess_run,
    ):
        """验证 `test_bilibili_downloader_downloads_video_only_streams_when_audio_missing` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        mocked_get.return_value = self._make_stream_response(
            [b"video-bytes"],
            headers={"content-length": "11", "content-type": "video/mp4"},
        )
        progress = []
        item = VideoItem(url="https://cdn.example.com/video.m4s", title="B站视频", source="bilibili")
        item.meta["audio_url"] = None

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            BilibiliDownloader().download(item, save_path, progress.append, lambda: False)

        self.assertEqual(progress, [10, 10, 90, 90, 100])
        self.assertEqual(mocked_get.call_count, 1)
        mocked_build_merge.assert_called_once()
        self.assertIsNone(mocked_build_merge.call_args.args[2])
        mocked_subprocess_run.assert_called_once()

    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_play_url_refresh_forwards_proxy_settings(self, mocked_get):
        """B站刷新 play_url 时必须沿用代理配置，否则 Web/CLI 网络路径会出现分叉。"""
        response = Mock()
        response.json.return_value = {
            "code": 0,
            "data": {
                "dash": {
                    "video": [{"baseUrl": "https://cdn.example.com/video.m4s"}],
                    "audio": [{"baseUrl": "https://cdn.example.com/audio.m4s"}],
                }
            },
        }
        mocked_get.return_value = response
        proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

        video_url, audio_url = BilibiliDownloader._fetch_bilibili_play_url(
            "BV1xx",
            "123",
            {"User-Agent": "ua"},
            proxies=proxies,
        )

        self.assertEqual(video_url, "https://cdn.example.com/video.m4s")
        self.assertEqual(audio_url, "https://cdn.example.com/audio.m4s")
        self.assertEqual(mocked_get.call_args.kwargs["proxies"], proxies)

    @patch("app.core.downloaders.bilibili.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]))
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.build_merge_command", return_value=["ffmpeg", "-i", "video", "output"])
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_downloader_raises_merge_error_when_ffmpeg_fails(
        self,
        mocked_get,
        _mocked_resolve,
        _mocked_build_merge,
        _mocked_subprocess_run,
    ):
        """验证 `test_bilibili_downloader_raises_merge_error_when_ffmpeg_fails` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        mocked_get.return_value = self._make_stream_response(
            [b"video-bytes"],
            headers={"content-length": "11", "content-type": "video/mp4"},
        )
        item = VideoItem(url="https://cdn.example.com/video.m4s", title="B站视频", source="bilibili")

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            with self.assertRaises(MergeError):
                BilibiliDownloader().download(item, save_path, lambda _value: None, lambda: False)

    @patch("app.core.downloaders.m3u8.ExternalToolRunner.wait_process")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_reports_external_tool_exit_failure(self, _mocked_resolve, mocked_popen, mocked_wait_process):
        """验证 `test_m3u8_downloader_reports_external_tool_exit_failure` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        process = Mock()
        process.returncode = 3
        mocked_popen.return_value = process
        mocked_wait_process.return_value = None
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="直播", source="douyin")

        with self.assertRaises(ExternalToolError):
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value=None)
    def test_m3u8_downloader_raises_when_executable_missing(self, _mocked_resolve):
        """验证 `test_m3u8_downloader_raises_when_executable_missing` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="直播", source="douyin")

        with self.assertRaises(ExternalToolNotFoundError):
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    def test_download_manager_stop_all_waits_with_timeout(self):
        """验证 `test_download_manager_stop_all_waits_with_timeout` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
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

    def test_download_manager_release_slot_is_idempotent(self):
        """验证 `test_download_manager_release_slot_is_idempotent` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.slot_semaphore = Mock()
        manager._workers_lock = threading.Lock()
        worker = Mock()
        worker.video = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        worker.video.meta["trace_id"] = "trace-1"
        worker._slot_released = False
        manager.workers = [worker]

        manager._release_worker_slot(worker, "task_finished")
        manager._release_worker_slot(worker, "thread_finished")

        manager.slot_semaphore.release.assert_called_once()
        self.assertTrue(worker._slot_released)

    def test_download_manager_handle_worker_completion_removes_worker_and_releases_slot(self):
        """验证 `test_download_manager_handle_worker_completion_removes_worker_and_releases_slot` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.slot_semaphore = Mock()
        manager._workers_lock = threading.Lock()
        worker = Mock()
        worker.video = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        worker.video.meta["trace_id"] = "trace-2"
        worker._slot_released = False
        manager.workers = [worker]

        manager._handle_worker_completion(worker, "task_finished")

        self.assertEqual(manager.workers, [])
        manager.slot_semaphore.release.assert_called_once()

    def test_download_manager_cancel_task_removes_queued_item_without_touching_slots(self):
        """验证 `test_download_manager_cancel_task_removes_queued_item_without_touching_slots` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.queue = queue.Queue()
        manager._workers_lock = threading.Lock()
        manager.workers = []
        manager.slot_semaphore = Mock()
        keep_item = VideoItem(url="https://example.com/1.mp4", title="keep", source="douyin")
        cancel_item = VideoItem(url="https://example.com/2.mp4", title="cancel", source="douyin")
        manager.queue.put((keep_item, "downloads"))
        manager.queue.put((cancel_item, "downloads"))

        result = manager.cancel_task(cancel_item.id)

        self.assertEqual(result, "queued")
        remaining_video, remaining_dir = manager.queue.get_nowait()
        self.assertEqual(remaining_video.id, keep_item.id)
        self.assertEqual(remaining_dir, "downloads")
        manager.slot_semaphore.release.assert_not_called()

    def test_download_manager_cancel_task_stops_running_worker(self):
        """验证 `test_download_manager_cancel_task_stops_running_worker` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.queue = queue.Queue()
        manager._workers_lock = threading.Lock()
        manager.slot_semaphore = Mock()
        worker = Mock()
        worker.video = VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin")
        manager.workers = [worker]

        result = manager.cancel_task(worker.video.id)

        self.assertEqual(result, "running")
        worker.stop.assert_called_once()

    def test_download_manager_cancel_task_returns_none_when_missing(self):
        """验证 `test_download_manager_cancel_task_returns_none_when_missing` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.queue = queue.Queue()
        manager._workers_lock = threading.Lock()
        manager.slot_semaphore = Mock()
        manager.workers = []

        self.assertIsNone(manager.cancel_task("missing"))

    def test_download_worker_generate_filename_prefers_meta_filename(self):
        """验证 `test_download_worker_generate_filename_prefers_meta_filename` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="显示标题", source="bilibili")
        item.meta["preferred_filename"] = "P01_真实文件名.mp4"
        worker = DownloadWorker(item, "downloads")

        filename = worker._generate_filename(".mp4")

        self.assertEqual(filename, "P01_真实文件名.mp4")

    def test_download_worker_resolve_save_dir_uses_subfolder_for_gallery_like_tasks(self):
        """验证 `test_download_worker_resolve_save_dir_uses_subfolder_for_gallery_like_tasks` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/cover.jpg", title="图集", source="douyin")
        item.meta.update(
            {
                "content_type": "gallery",
                "folder_name": "合集目录",
                "is_gallery": True,
            }
        )
        worker = DownloadWorker(item, "downloads")

        self.assertEqual(worker._resolve_save_dir(), os.path.join("downloads", "合集目录"))

    def test_download_worker_infer_extension_uses_content_type_and_url_hint(self):
        """验证 `test_download_worker_infer_extension_uses_content_type_and_url_hint` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        gallery_item = VideoItem(url="https://example.com/cover.bin", title="图集", source="douyin")
        gallery_item.meta["content_type"] = "gallery"
        gallery_worker = DownloadWorker(gallery_item, "downloads")

        image_item = VideoItem(url="https://example.com/cover.webp?size=1080", title="封面", source="douyin")
        image_worker = DownloadWorker(image_item, "downloads")

        self.assertEqual(gallery_worker._infer_extension(), ".jpeg")
        self.assertEqual(image_worker._infer_extension(), ".webp")

    def test_download_worker_ensure_unique_path_appends_incrementing_suffix(self):
        """验证 `test_download_worker_ensure_unique_path_appends_incrementing_suffix` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = os.path.join(temp_dir, "demo.mp4")
            open(base_path, "wb").close()
            open(os.path.join(temp_dir, "demo_1.mp4"), "wb").close()

            unique_path = worker._ensure_unique_path(base_path)

        self.assertTrue(unique_path.endswith("demo_2.mp4"))

    def test_download_worker_detect_actual_file_type_recognizes_mp4_signature(self):
        """验证 `test_download_worker_detect_actual_file_type_recognizes_mp4_signature` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.bin", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "video.bin")
            with open(file_path, "wb") as fp:
                fp.write(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 16)

            detected_ext = worker._detect_actual_file_type(file_path)

        self.assertEqual(detected_ext, ".mp4")

    def test_download_worker_detect_actual_file_type_returns_none_for_missing_file(self):
        """验证 `test_download_worker_detect_actual_file_type_returns_none_for_missing_file` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.bin", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")

        self.assertIsNone(worker._detect_actual_file_type("missing-file.bin"))

    def test_video_item_update_from_dict_uses_field_whitelist(self):
        """验证 `test_video_item_update_from_dict_uses_field_whitelist` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
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

    @patch.object(KuaishouDownloader, "_download_with_strategy_fallback")
    @patch("app.core.downloaders.kuaishou.cfg.get")
    def test_kuaishou_downloader_prefers_kuaishou_user_agent_config(
        self,
        mocked_cfg_get,
        mocked_download,
    ):
        """验证 `test_kuaishou_downloader_prefers_kuaishou_user_agent_config` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        def fake_get(section, key, default=None):
            """执行 `fake_get` 对应的业务逻辑。"""
            if (section, key) == ("kuaishou", "user_agent"):
                return "kuaishou-ua"
            return default

        mocked_cfg_get.side_effect = fake_get
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="kuaishou")

        KuaishouDownloader().download(item, "demo.mp4", lambda _: None, lambda: False)

        self.assertEqual(mocked_download.call_args.kwargs["headers"]["User-Agent"], "kuaishou-ua")

    @patch.object(KuaishouDownloader, "_download_with_strategy_fallback")
    @patch("app.core.downloaders.kuaishou.cfg.get", return_value="config-ua")
    def test_kuaishou_downloader_allows_task_level_user_agent_override(
        self,
        _mocked_cfg_get,
        mocked_download,
    ):
        """验证 `test_kuaishou_downloader_allows_task_level_user_agent_override` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="kuaishou")
        item.meta["ua"] = "meta-ua"

        KuaishouDownloader().download(item, "demo.mp4", lambda _: None, lambda: False)

        self.assertEqual(mocked_download.call_args.kwargs["headers"]["User-Agent"], "meta-ua")


if __name__ == "__main__":
    unittest.main()
