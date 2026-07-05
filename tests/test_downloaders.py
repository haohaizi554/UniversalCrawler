"""Downloader lifecycle and strategy tests."""
from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from app.core.download_manager import DownloadManager, DownloadWorker
from app.core.download_manager_core import PendingDownloadQueue
from app.core.lib.douyin.tools.session import create_client, request_params
from app.core.downloaders import BaseDownloader, ChunkedDownloader, FFmpegDownloader, FFmpegExternalTool, NM3U8DLREExternalTool, N_m3u8DL_RE_Downloader
from app.core.downloaders.bilibili import BilibiliDownloader
from app.core.downloaders.douyin import DouyinDownloader
from app.core.downloaders.kuaishou import KuaishouDownloader
from app.core.downloaders.missav import MissAVDownloader
from app.core.downloaders.xiaohongshu import XiaohongshuDownloader
from app.core.downloaders.external import ExternalToolRunner
from app.core.downloaders.m3u8 import _LocalHlsProxy, _Nm3u8OutputProgress
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError, MergeError, StreamDownloadError
from app.models import VideoItem

class DownloaderStrategyTests(unittest.TestCase):
    
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
        self.assertTrue(XiaohongshuDownloader.can_handle(VideoItem(url="https://example.com/5", title="e", source="xiaohongshu")))

    def test_m3u8_url_detection(self):
        """验证 `test_m3u8_url_detection` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        self.assertTrue(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/master.m3u8"))
        self.assertFalse(N_m3u8DL_RE_Downloader.is_m3u8_url("https://example.com/video.mp4"))

    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.is_available", return_value=False)
    @patch("app.core.downloaders.m3u8.N_m3u8DL_RE_Downloader._python_hls_fallback_available", return_value=True)
    def test_m3u8_downloader_is_available_when_python_hls_fallback_exists(self, _mocked_python, _mocked_external):
        self.assertTrue(N_m3u8DL_RE_Downloader.is_available())

    def test_base_downloader_progress_callback_errors_are_isolated(self):
        calls = []

        def progress_callback(value, **_kwargs):
            calls.append(value)
            raise RuntimeError("ui callback failed")

        BaseDownloader._emit_progress(progress_callback, 42, bytes_downloaded=1024, bytes_total=2048)

        self.assertEqual(calls, [42])

    def test_m3u8_cleanup_removes_external_tool_temp_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            temp_file = os.path.join(temp_dir, "demo.part")
            temp_dir_path = os.path.join(temp_dir, "demo_tmp")
            open(save_path, "wb").close()
            open(temp_file, "wb").close()
            os.mkdir(temp_dir_path)

            N_m3u8DL_RE_Downloader._cleanup_external_temp_files(save_path)

            self.assertFalse(os.path.exists(save_path))
            self.assertFalse(os.path.exists(temp_file))
            self.assertFalse(os.path.exists(temp_dir_path))

    def test_m3u8_cleanup_skips_unowned_tmp_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            user_dir = Path(temp_dir) / "not-owned"
            user_dir.mkdir()
            marker = user_dir / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            N_m3u8DL_RE_Downloader._cleanup_nm3u8_temp_workspace(user_dir)

            self.assertTrue(marker.exists())

    def test_m3u8_cleanup_removes_owned_tmp_workspace_and_empty_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            workspace = N_m3u8DL_RE_Downloader._create_nm3u8_temp_workspace(save_path)
            (workspace / "segment.ts").write_bytes(b"data")
            root = workspace.parent

            N_m3u8DL_RE_Downloader._cleanup_nm3u8_temp_workspace(workspace)

            self.assertFalse(workspace.exists())
            self.assertFalse(root.exists())

    def test_bili_api_close_closes_requests_session(self):
        from app.spiders.bilibili.spider import BiliAPI

        api = BiliAPI.__new__(BiliAPI)
        api.sess = Mock()

        api.close()

        api.sess.close.assert_called_once()

    def test_douyin_async_main_closes_runtime_params(self):
        from app.spiders.douyin.spider import DouyinSpider

        class FakeParams:
            def __init__(self):
                self.closed = False

            async def close_client(self):
                self.closed = True

        fake_params = FakeParams()
        spider = DouyinSpider.__new__(DouyinSpider)

        async def fake_body(_cookie):
            spider._active_douyin_params = fake_params

        spider._async_main_body = fake_body

        asyncio.run(spider._async_main("cookie"))

        self.assertTrue(fake_params.closed)
        self.assertIsNone(spider._active_douyin_params)

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
    def test_external_tool_runner_progress_callback_errors_do_not_abort_wait(self, _mocked_sleep):
        process = Mock()
        process.poll.side_effect = [None, None, 0]

        def progress(_value):
            raise AttributeError("ui callback failed")

        ExternalToolRunner.wait_process(process, lambda: False, progress, 50, poll_interval=0)

        self.assertEqual(process.poll.call_count, 3)
        process.kill.assert_not_called()

    @patch("app.core.downloaders.external.time.sleep", return_value=None)
    def test_external_tool_runner_wait_process_terminates_process_when_stopped(self, _mocked_sleep):
        """验证 `test_external_tool_runner_wait_process_kills_process_when_stopped` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        process = Mock()
        process.poll.side_effect = [None, None, 0]

        with self.assertRaises(DownloaderStoppedError):
            ExternalToolRunner.wait_process(process, lambda: True, poll_interval=0)

        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5.0)
        process.kill.assert_not_called()

    def test_external_tool_runner_terminate_process_kills_after_timeout(self):
        process = Mock()
        process.poll.side_effect = [None, None, None]
        process.wait.side_effect = [subprocess.TimeoutExpired("tool", 5), None]

        ExternalToolRunner.terminate_process(process)

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_args_list[-1].kwargs["timeout"], 2)

    def test_ffmpeg_external_tool_build_merge_command_skips_audio_when_none(self):
        """验证 `test_ffmpeg_external_tool_build_merge_command_skips_audio_when_none` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        command = FFmpegExternalTool.build_merge_command("ffmpeg.exe", "video.m4s", None, "output.mp4")

        self.assertEqual(
            command,
            [
                "ffmpeg.exe",
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "video.m4s",
                "-map",
                "0:v:0?",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                "output.mp4",
            ],
        )

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
        process.stderr.close.assert_called()

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

    @patch.object(FFmpegDownloader, "PROGRESS_TIMEOUT_SEC", 0.01)
    @patch.object(FFmpegDownloader, "STDERR_POLL_INTERVAL_SEC", 0.005)
    @patch("app.core.downloaders.ffmpeg.time.sleep", return_value=None)
    @patch("app.core.downloaders.ffmpeg.requests.head")
    @patch("app.core.downloaders.ffmpeg.subprocess.Popen")
    @patch("app.core.downloaders.ffmpeg.cfg.get")
    @patch("app.core.downloaders.ffmpeg.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    def test_ffmpeg_downloader_kills_stalled_process_even_when_stderr_blocks(
        self,
        _mocked_resolve,
        mocked_cfg_get,
        mocked_popen,
        mocked_head,
        _mocked_sleep,
    ):
        """stderr 不再产出时，下载器仍应按无进度超时主动 kill 进程。"""
        head_response = Mock()
        head_response.url = "https://cdn.example.com/video.mp4"
        head_response.status_code = 200
        head_response.headers = {"content-length": "4096"}
        mocked_head.return_value = head_response

        def fake_cfg_get(section, key, default=None):
            if (section, key) == ("download", "max_retries"):
                return 1
            return default

        mocked_cfg_get.side_effect = fake_cfg_get

        class BlockingStderr:
            def readline(self):
                threading.Event().wait(0.05)
                return b""

        process = Mock()
        process.stderr = BlockingStderr()
        process.poll.return_value = None
        process.returncode = 1
        mocked_popen.return_value = process

        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with self.assertRaises(ExternalToolError):
            FFmpegDownloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        process.kill.assert_called()

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
        auto_select_index = command.index("--auto-select")
        self.assertEqual(command[auto_select_index + 1], "true")

    def test_nm3u8_external_tool_build_download_command_accepts_tmp_dir(self):
        tmp_dir = os.path.join("downloads", ".ucp-nm3u8-tmp", "ucp-demo")
        command = NM3U8DLREExternalTool.build_download_command(
            "N_m3u8DL-RE.exe",
            "https://cdn.example.com/live/index.m3u8",
            os.path.join("downloads", "demo.mp4"),
            "ua-demo",
            "https://www.douyin.com/",
            tmp_dir=tmp_dir,
        )

        self.assertEqual(command[command.index("--tmp-dir") + 1], tmp_dir)

    def test_nm3u8_external_tool_build_download_command_includes_extra_headers(self):
        command = NM3U8DLREExternalTool.build_download_command(
            "N_m3u8DL-RE.exe",
            "https://surrit.com/live/index.m3u8",
            os.path.join("downloads", "demo.mp4"),
            "ua-demo",
            "https://missav.ai/cn/abc-123",
            extra_headers={
                "Cookie": "session=abc",
                "Origin": "https://missav.ai",
                "Host": "surrit.com",
                "Accept-Encoding": "gzip, br",
                "Range": "bytes=0-",
                "Sec-Fetch-Dest": "video",
            },
        )

        self.assertIn("Cookie: session=abc", command)
        self.assertIn("Origin: https://missav.ai", command)
        self.assertNotIn("Host: surrit.com", command)
        self.assertIn("Accept-Encoding: gzip, br", command)
        self.assertIn("Range: bytes=0-", command)
        self.assertIn("Sec-Fetch-Dest: video", command)

    def test_nm3u8_external_tool_accepts_explicit_thread_count(self):
        command = NM3U8DLREExternalTool.build_download_command(
            "N_m3u8DL-RE.exe",
            "https://surrit.com/live/index.m3u8",
            os.path.join("downloads", "demo.mp4"),
            "ua-demo",
            "https://missav.ai/cn/abc-123",
            thread_count=16,
        )

        self.assertEqual(command[command.index("--thread-count") + 1], "16")

    def test_m3u8_downloader_headers_from_missav_meta_default_to_legacy_minimum(self):
        item = VideoItem(url="https://surrit.com/live/index.m3u8", title="demo", source="missav")
        item.meta.update(
            {
                "headers": {"Cookie": "session=abc"},
                "referer": "https://missav.ai/cn/abc-123",
            }
        )

        headers = N_m3u8DL_RE_Downloader._headers_from_meta(
            item,
            "ua-demo",
            "https://missav.ai/cn/abc-123",
        )

        self.assertEqual(headers, {"User-Agent": "ua-demo", "Referer": "https://missav.ai/cn/abc-123"})

    def test_m3u8_downloader_headers_from_missav_meta_can_preserve_cookie_when_enabled(self):
        item = VideoItem(url="https://surrit.com/live/index.m3u8", title="demo", source="missav")
        item.meta.update(
            {
                "headers": {"Cookie": "session=abc"},
                "referer": "https://missav.ai/cn/abc-123",
                "missav_include_cookies": True,
            }
        )

        headers = N_m3u8DL_RE_Downloader._headers_from_meta(
            item,
            "ua-demo",
            "https://missav.ai/cn/abc-123",
        )

        self.assertEqual(headers["Cookie"], "session=abc")
        self.assertNotIn("Origin", headers)
        self.assertEqual(headers["User-Agent"], "ua-demo")

    def test_m3u8_downloader_headers_from_missav_browser_meta_preserve_detailed_headers(self):
        item = VideoItem(url="https://surrit.com/live/index.m3u8", title="demo", source="missav")
        item.meta.update(
            {
                "headers": {
                    "Cookie": "session=abc",
                    "Sec-Fetch-Site": "cross-site",
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Origin": "https://missav.ai",
                    "Cache-Control": "no-cache",
                    "Sec-Ch-Ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
                },
                "referer": "https://missav.ai/cn/abc-123",
                "missav_use_browser_headers": True,
            }
        )

        headers = N_m3u8DL_RE_Downloader._headers_from_meta(
            item,
            "ua-demo",
            "https://missav.ai/cn/abc-123",
        )

        self.assertEqual(headers["Cookie"], "session=abc")
        self.assertEqual(headers["Sec-Fetch-Site"], "cross-site")
        self.assertEqual(headers["Accept"], "*/*")
        self.assertEqual(headers["Accept-Encoding"], "gzip, deflate, br, zstd")
        self.assertEqual(headers["Origin"], "https://missav.ai")
        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertEqual(headers["Sec-Ch-Ua"], '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"')
        self.assertEqual(headers["Referer"], "https://missav.ai/cn/abc-123")

    @patch("app.core.downloaders.external.os.name", "nt")
    @patch("app.core.downloaders.external.resolve_tool_file")
    def test_nm3u8_external_tool_prefers_windows_executable_name(self, mocked_resolve_tool_file):
        """Windows 应优先解析 `N_m3u8DL-RE.exe`。"""
        exe_path = Mock()
        exe_path.exists.return_value = True

        def fake_resolve(name):
            if name == "N_m3u8DL-RE.exe":
                return exe_path
            missing = Mock()
            missing.exists.return_value = False
            return missing

        mocked_resolve_tool_file.side_effect = fake_resolve

        self.assertEqual(NM3U8DLREExternalTool.resolve_executable(), str(exe_path))
        self.assertEqual(mocked_resolve_tool_file.call_args_list[0].args[0], "N_m3u8DL-RE.exe")

    @patch("app.core.downloaders.external.os.name", "posix")
    @patch("app.core.downloaders.external.subprocess.run")
    @patch("app.core.downloaders.external.resolve_tool_file")
    def test_nm3u8_external_tool_falls_back_to_linux_cli_name(self, mocked_resolve_tool_file, mocked_run):
        """Linux 容器应回退到无扩展名命令而不是只认 `.exe`。"""
        missing = Mock()
        missing.exists.return_value = False
        mocked_resolve_tool_file.return_value = missing

        def fake_run(cmd, stdout=None, stderr=None, check=None):
            if cmd[0] == "N_m3u8DL-RE":
                return Mock()
            raise OSError("missing")

        mocked_run.side_effect = fake_run

        self.assertEqual(NM3U8DLREExternalTool.resolve_executable(), "N_m3u8DL-RE")
        self.assertEqual(mocked_run.call_args_list[0].args[0][0], "N_m3u8DL-RE")

    def test_download_worker_uses_registered_downloader(self):
        """验证 `test_download_worker_uses_registered_downloader` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        self.assertIsInstance(worker._select_downloader(), DouyinDownloader)

    def test_download_worker_drops_duplicate_progress_percentages(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        emitted: list[tuple[str, int]] = []
        worker.sig_progress.connect(lambda video_id, progress: emitted.append((video_id, progress)))
        progress = worker._emit_progress_if_changed()

        for value in (0, 0, 1, 1, 1, 2, 2, 100, 100):
            progress(value)

        self.assertEqual(
            emitted,
            [(item.id, 0), (item.id, 1), (item.id, 2), (item.id, 100)],
        )

    def test_download_worker_ignores_progress_after_stop(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        emitted: list[tuple[str, int]] = []
        worker.sig_progress.connect(lambda video_id, progress: emitted.append((video_id, progress)))
        progress = worker._emit_progress_if_changed()

        worker.stop()
        progress(50, bytes_downloaded=512, bytes_total=1024)

        self.assertEqual(emitted, [])

    def test_download_worker_records_byte_progress_and_refreshes_speed(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        worker = DownloadWorker(item, "downloads")
        emitted: list[tuple[str, int]] = []
        worker.sig_progress.connect(lambda video_id, progress: emitted.append((video_id, progress)))
        progress = worker._emit_progress_if_changed()

        with patch("app.core.download_manager.time.monotonic", side_effect=[0.0, 0.0, 1.0, 1.0]):
            progress(10, bytes_downloaded=1_000, bytes_total=10_000)
            progress(10, bytes_downloaded=3_000, bytes_total=10_000)

        self.assertEqual(emitted, [(item.id, 10), (item.id, 10)])
        self.assertEqual(item.meta["bytes_downloaded"], 3_000)
        self.assertEqual(item.meta["bytes_total"], 10_000)
        self.assertGreater(item.meta["speed_bps"], 0)

    def test_download_worker_marks_stopped_before_success_callbacks(self):
        class SuccessfulDownloader:
            def download(self, video_item, save_path, progress_callback, check_stop_func):
                with open(save_path, "wb") as fp:
                    fp.write(b"\x00\x00\x00\x20ftypisom")
                progress_callback(100)

        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = DownloadWorker(item, temp_dir)
            observed = []
            worker._select_downloader = lambda: SuccessfulDownloader()
            worker.sig_finished.connect(
                lambda video_id: observed.append(("finished", video_id, worker.is_running))
            )
            worker._completion_callback = lambda _worker, reason: observed.append(
                ("completion", reason, worker.is_running)
            )

            worker.run()

        self.assertIn(("finished", item.id, False), observed)
        self.assertIn(("completion", "task_finished", False), observed)
        self.assertFalse(worker.is_running)

    def test_download_worker_marks_stopped_before_error_callbacks(self):
        class FailingDownloader:
            def download(self, video_item, save_path, progress_callback, check_stop_func):
                raise RuntimeError("boom")

        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = DownloadWorker(item, temp_dir)
            observed = []
            worker._select_downloader = lambda: FailingDownloader()
            worker.sig_error.connect(
                lambda video_id, error: observed.append(("error", video_id, error, worker.is_running))
            )
            worker._completion_callback = lambda _worker, reason: observed.append(
                ("completion", reason, worker.is_running)
            )

            worker.run()

        self.assertIn(("error", item.id, "boom", False), observed)
        self.assertIn(("completion", "task_error", False), observed)
        self.assertFalse(worker.is_running)

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

    @patch.object(DouyinDownloader, "_download_file")
    def test_douyin_gallery_reports_aggregate_byte_progress(self, mocked_download_file):
        def fake_download_file(*_args, **kwargs):
            callback = kwargs["progress_callback"]
            callback(50, bytes_downloaded=512, bytes_total=1024)
            callback(100, bytes_downloaded=1024, bytes_total=1024)

        mocked_download_file.side_effect = fake_download_file
        item = VideoItem(url="https://example.com/cover.jpg", title="gallery", source="douyin")
        events = []

        def progress_callback(value, **kwargs):
            events.append((value, kwargs))

        DouyinDownloader()._download_gallery(
            item,
            [
                {"live_video_url": "", "image_url": "https://cdn.example.com/one.jpg"},
                {"live_video_url": "", "image_url": "https://cdn.example.com/two.jpg"},
            ],
            os.path.join("downloads", "demo.mp4"),
            progress_callback,
            lambda: False,
            {"User-Agent": "ua", "Referer": "https://www.douyin.com/"},
        )

        byte_events = [kwargs for _value, kwargs in events if kwargs.get("bytes_downloaded")]
        self.assertTrue(byte_events)
        self.assertEqual(max(event["bytes_downloaded"] for event in byte_events), 2048)
        self.assertEqual(max(event["bytes_total"] for event in byte_events), 2048)
        self.assertEqual(events[-1][0], 100)

    @patch.object(DouyinDownloader, "_download_file")
    def test_douyin_gallery_progress_callback_failure_does_not_stop_downloads(self, mocked_download_file):
        item = VideoItem(url="https://example.com/cover.jpg", title="gallery", source="douyin")

        def progress_callback(_value):
            raise RuntimeError("ui callback failed")

        DouyinDownloader()._download_gallery(
            item,
            [
                {"live_video_url": "", "image_url": "https://cdn.example.com/one.jpg"},
                {"live_video_url": "", "image_url": "https://cdn.example.com/two.jpg"},
            ],
            os.path.join("downloads", "demo.mp4"),
            progress_callback,
            lambda: False,
            {"User-Agent": "ua", "Referer": "https://www.douyin.com/"},
        )

        self.assertEqual(mocked_download_file.call_count, 2)

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

    @patch.object(BilibiliDownloader, "_run_merge_process")
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.build_merge_command", return_value=["ffmpeg", "-i", "video", "output"])
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_downloader_downloads_video_only_streams_when_audio_missing(
        self,
        mocked_get,
        _mocked_resolve,
        mocked_build_merge,
        mocked_run_merge,
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
            mocked_run_merge.side_effect = lambda *args, **kwargs: Path(save_path).write_bytes(b"merged")
            BilibiliDownloader().download(item, save_path, progress.append, lambda: False)

        self.assertEqual(progress, [10, 10, 90, 90, 91, 100])
        self.assertEqual(mocked_get.call_count, 1)
        mocked_build_merge.assert_called_once()
        self.assertIsNone(mocked_build_merge.call_args.args[2])
        mocked_run_merge.assert_called_once()

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

    @patch("app.core.downloaders.bilibili.debug_logger.log_exception")
    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_play_url_refresh_logs_request_exceptions(self, mocked_get, mocked_log_exception):
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
        mocked_get.side_effect = [requests.RequestException("network boom"), response]

        video_url, audio_url = BilibiliDownloader._fetch_bilibili_play_url(
            "BV1xx",
            "123",
            {"User-Agent": "ua"},
            trace_id="trace-bili",
        )

        self.assertEqual(video_url, "https://cdn.example.com/video.m4s")
        self.assertEqual(audio_url, "https://cdn.example.com/audio.m4s")
        mocked_log_exception.assert_called_once()
        self.assertEqual(mocked_log_exception.call_args.args[:2], ("BilibiliDownloader", "play_url_refresh"))
        self.assertEqual(mocked_log_exception.call_args.kwargs["trace_id"], "trace-bili")
        self.assertEqual(
            mocked_log_exception.call_args.kwargs["details"],
            {"fnval": 4048, "bvid": "BV1xx", "cid": "123"},
        )

    @patch.object(BilibiliDownloader, "_run_merge_process", side_effect=MergeError("ffmpeg failed"))
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.build_merge_command", return_value=["ffmpeg", "-i", "video", "output"])
    @patch("app.core.downloaders.bilibili.FFmpegExternalTool.resolve_executable", return_value="ffmpeg.exe")
    @patch("app.core.downloaders.bilibili.requests.get")
    def test_bilibili_downloader_raises_merge_error_when_ffmpeg_fails(
        self,
        mocked_get,
        _mocked_resolve,
        _mocked_build_merge,
        _mocked_run_merge,
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

    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_reports_external_tool_exit_failure(self, _mocked_resolve, mocked_popen, mocked_wait_progress):
        """验证 `test_m3u8_downloader_reports_external_tool_exit_failure` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        process = Mock()
        process.returncode = 3
        mocked_popen.return_value = process
        mocked_wait_progress.return_value = None
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="直播", source="douyin")

        with self.assertRaises(ExternalToolError):
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_cleans_owned_tmp_workspace_on_external_failure(
        self,
        _mocked_resolve,
        mocked_popen,
        mocked_wait_progress,
    ):
        process = Mock()
        process.returncode = 3
        process.poll.return_value = 0
        created_tmp_dirs = []

        def fake_popen(cmd, *args, **kwargs):
            del args, kwargs
            tmp_dir = Path(cmd[cmd.index("--tmp-dir") + 1])
            created_tmp_dirs.append(tmp_dir)
            (tmp_dir / "segment.ts").write_bytes(b"data")
            return process

        mocked_popen.side_effect = fake_popen
        mocked_wait_progress.return_value = None
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="live", source="douyin")
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")

            with self.assertRaises(ExternalToolError):
                N_m3u8DL_RE_Downloader().download(item, save_path, lambda _value: None, lambda: False)

            self.assertEqual(len(created_tmp_dirs), 1)
            self.assertFalse(created_tmp_dirs[0].exists())
            self.assertFalse((Path(temp_dir) / N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME).exists())

    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_curl_cffi_hls")
    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_nm3u8_external")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_missav_surrit_downloader_prefers_external_tool_before_python_fallback(
        self, mocked_resolve, mocked_external, mocked_curl
    ):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta.update({"headers": {"Referer": "https://missav.ai/cn/demo"}, "missav_use_browser_headers": True})

        N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        mocked_resolve.assert_called_once()
        mocked_external.assert_called_once()
        self.assertEqual(mocked_external.call_args.args[7], 16)
        mocked_curl.assert_not_called()

    def test_missav_surrit_external_tool_uses_local_hls_proxy_url(self):
        downloader = N_m3u8DL_RE_Downloader()
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")

        class FakeProxy:
            url = "http://127.0.0.1:12345/hls?u=demo"

            def progress_snapshot(self):
                return 50, 0

            def stop(self):
                pass

        with patch.object(downloader, "_start_local_hls_proxy", return_value=FakeProxy()) as mocked_start, patch.object(
            downloader, "_run_nm3u8_external_command"
        ) as mocked_run:
            downloader._download_with_nm3u8_external(
                item,
                "demo.mp4",
                "N_m3u8DL-RE.exe",
                "ua-demo",
                "https://missav.ai/cn/demo",
                "http://127.0.0.1:7890",
                {"Referer": "https://missav.ai/cn/demo"},
                16,
                lambda _value: None,
                lambda: False,
            )

        mocked_start.assert_called_once()
        args = mocked_run.call_args.args
        self.assertEqual(args[3], "http://127.0.0.1:12345/hls?u=demo")
        self.assertIsNone(args[6])
        self.assertEqual(args[8], 16)
        self.assertTrue(mocked_run.call_args.kwargs["local_proxy"])
        self.assertTrue(callable(mocked_run.call_args.kwargs["progress_provider"]))

    def test_run_nm3u8_external_command_cleans_owned_tmp_workspace_on_failure(self):
        downloader = N_m3u8DL_RE_Downloader()
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        process = Mock()
        process.returncode = 7
        process.poll.return_value = 0
        created_tmp_dirs = []

        def fake_popen(cmd, _creation_flags):
            tmp_dir = Path(cmd[cmd.index("--tmp-dir") + 1])
            created_tmp_dirs.append(tmp_dir)
            (tmp_dir / "segment.ts").write_bytes(b"data")
            return process

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            downloader,
            "_popen_nm3u8_process",
            side_effect=fake_popen,
        ), patch.object(downloader, "_wait_external_process_with_file_progress", return_value=None):
            save_path = os.path.join(temp_dir, "demo.mp4")

            with self.assertRaises(ExternalToolError):
                downloader._run_nm3u8_external_command(
                    item,
                    save_path,
                    "N_m3u8DL-RE.exe",
                    item.url,
                    "ua-demo",
                    "https://missav.ai/cn/demo",
                    None,
                    {"Referer": "https://missav.ai/cn/demo"},
                    16,
                    lambda _value: None,
                    lambda: False,
                    local_proxy=False,
                )

            self.assertEqual(len(created_tmp_dirs), 1)
            self.assertFalse(created_tmp_dirs[0].exists())
            self.assertFalse((Path(temp_dir) / N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME).exists())

    def test_hls_proxy_rewrites_playlist_urls_to_local_proxy_urls(self):
        playlist = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:4,
seg1.ts
#EXT-X-MAP:URI='init.mp4'
https://cdn.example.com/seg2.ts
"""

        result = N_m3u8DL_RE_Downloader._rewrite_hls_playlist_for_proxy(
            playlist,
            "https://surrit.com/demo/playlist.m3u8",
            lambda url: f"local://{url}",
        )

        self.assertIn('URI="local://https://surrit.com/demo/key.bin"', result)
        self.assertIn("local://https://surrit.com/demo/seg1.ts", result)
        self.assertIn("URI='local://https://surrit.com/demo/init.mp4'", result)
        self.assertIn("local://https://cdn.example.com/seg2.ts", result)

    def test_hls_proxy_counts_media_segments_without_master_variants(self):
        playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000
variant/index.m3u8
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:4,
seg1.ts
#EXTINF:4,
https://cdn.example.com/seg2.m4s?token=1
"""

        self.assertEqual(N_m3u8DL_RE_Downloader._count_hls_media_entries(playlist), 2)

    def test_external_process_progress_uses_local_proxy_provider(self):
        downloader = N_m3u8DL_RE_Downloader()
        process = Mock()
        process.returncode = 0
        poll_calls = {"count": 0}

        def poll():
            poll_calls["count"] += 1
            return None if poll_calls["count"] == 1 else 0

        process.poll.side_effect = poll
        updates = []

        def progress(value, **kwargs):
            updates.append((value, kwargs))

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.core.downloaders.m3u8.time.sleep", return_value=None
        ):
            downloader._wait_external_process_with_file_progress(
                process,
                os.path.join(temp_dir, "demo.mp4"),
                lambda: False,
                progress,
                50,
                progress_provider=lambda: (71, 2048),
            )

        self.assertEqual(updates[-1][0], 71)
        self.assertEqual(updates[-1][1]["bytes_downloaded"], 2048)

    def test_nm3u8_output_progress_parses_tool_percent_and_speed(self):
        with patch("app.core.downloaders.nm3u8_progress.time.monotonic", side_effect=[0.0, 0.0, 1.0]):
            progress = _Nm3u8OutputProgress(default_progress=50)
            progress.feed("Vid 1280x720 ---------------- 25/100 25.00% - 2.00MBps(16) 00:10")
            percent, bytes_downloaded = progress.snapshot()

        self.assertEqual(percent, 25)
        self.assertEqual(bytes_downloaded, 2 * 1024 * 1024)

    def test_nm3u8_output_progress_accepts_slash_speed_units(self):
        with patch("app.core.downloaders.nm3u8_progress.time.monotonic", side_effect=[0.0, 0.0, 1.0]):
            progress = _Nm3u8OutputProgress(default_progress=50)
            progress.feed("Vid 1280x720 ---------------- 12/100 12.50% - 1.50 MiB/s 00:10")
            percent, bytes_downloaded = progress.snapshot()

        self.assertEqual(percent, 12)
        self.assertEqual(bytes_downloaded, int(1.5 * 1024 * 1024))

    def test_nm3u8_output_progress_combines_with_local_proxy_provider(self):
        combined = N_m3u8DL_RE_Downloader._combine_progress_providers(
            lambda: (71, 2048),
            lambda: (42, 4096),
        )

        self.assertIsNotNone(combined)
        self.assertEqual(combined(), (71, 4096))

    def test_nm3u8_combined_progress_provider_keeps_healthy_source_when_one_fails(self):
        def failing_provider():
            raise RuntimeError("provider failed")

        combined = N_m3u8DL_RE_Downloader._combine_progress_providers(
            failing_provider,
            lambda: (42, 4096),
        )

        self.assertIsNotNone(combined)
        self.assertEqual(combined(), (42, 4096))

    def test_nm3u8_combined_progress_provider_uses_startup_progress_when_unknown(self):
        combined = N_m3u8DL_RE_Downloader._combine_progress_providers(None, None)

        self.assertIsNone(combined)

    @patch("app.core.downloaders.m3u8.build_hidden_startupinfo", return_value="hidden-startupinfo")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    def test_nm3u8_process_captures_output_without_visible_console(self, mocked_popen, _mocked_startupinfo):
        N_m3u8DL_RE_Downloader._popen_nm3u8_process(["N_m3u8DL-RE.exe", "demo.m3u8"], 123)

        kwargs = mocked_popen.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], 123)
        self.assertEqual(kwargs["startupinfo"], "hidden-startupinfo")
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        self.assertTrue(kwargs["text"])

    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.build_no_window_flags", return_value=321)
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_uses_file_progress_for_external_tool(
        self,
        _mocked_resolve,
        _mocked_no_window_flags,
        mocked_popen,
        mocked_wait_progress,
    ):
        process = Mock()
        process.returncode = 0
        mocked_popen.return_value = process
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="live", source="douyin")

        N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value, **_kwargs: None, lambda: False)

        mocked_wait_progress.assert_called_once()
        self.assertIs(mocked_wait_progress.call_args.args[0], process)
        self.assertEqual(mocked_wait_progress.call_args.args[1], "demo.mp4")
        self.assertEqual(mocked_wait_progress.call_args.args[4], 0)
        self.assertEqual(mocked_popen.call_args.kwargs["creationflags"], 321)
        self.assertEqual(mocked_popen.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(mocked_popen.call_args.kwargs["stderr"], subprocess.STDOUT)
        self.assertIsNotNone(mocked_wait_progress.call_args.kwargs["progress_provider"])

    def test_local_hls_proxy_unknown_playlist_keeps_startup_progress(self):
        downloader = N_m3u8DL_RE_Downloader()
        proxy = _LocalHlsProxy(downloader, "https://surrit.com/demo/playlist.m3u8", {}, None)

        self.assertEqual(proxy.progress_snapshot(), (0, 0))

    def test_local_hls_proxy_streams_segment_bytes_for_live_speed(self):
        downloader = N_m3u8DL_RE_Downloader()
        proxy = _LocalHlsProxy(downloader, "https://surrit.com/demo/playlist.m3u8", {}, None)
        proxy._segment_total = 1

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "video/mp4", "Content-Length": "6"}

            def iter_content(self, chunk_size=0):
                yield b"abc"
                yield b"def"

            def close(self):
                pass

        class FakeHandler:
            def __init__(self):
                self.status = None
                self.headers = []
                self.wfile = io.BytesIO()

            def send_response(self, status):
                self.status = status

            def send_header(self, key, value):
                self.headers.append((key, value))

            def end_headers(self):
                pass

        handler = FakeHandler()
        with patch.object(downloader, "_hls_proxy_open_upstream", return_value=FakeResponse()):
            proxy.serve(handler, "https://surrit.com/demo/seg1.m4s")

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.wfile.getvalue(), b"abcdef")
        self.assertEqual(proxy.progress_snapshot(), (95, 6))

    def test_local_hls_proxy_forwards_range_response_headers(self):
        downloader = N_m3u8DL_RE_Downloader()
        proxy = _LocalHlsProxy(downloader, "https://surrit.com/demo/playlist.m3u8", {}, None)

        class FakeResponse:
            status_code = 206
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": "6",
                "Content-Range": "bytes 0-5/6",
                "Accept-Ranges": "bytes",
                "ETag": '"demo"',
            }
            content = b"abcdef"

            def close(self):
                pass

        class FakeHandler:
            def __init__(self):
                self.status = None
                self.headers = []
                self.wfile = io.BytesIO()

            def send_response(self, status):
                self.status = status

            def send_header(self, key, value):
                self.headers.append((key, value))

            def end_headers(self):
                pass

        handler = FakeHandler()
        with patch.object(downloader, "_hls_proxy_open_upstream", return_value=FakeResponse()):
            proxy.serve(handler, "https://surrit.com/demo/seg1.m4s")

        self.assertEqual(handler.status, 206)
        self.assertIn(("Content-Range", "bytes 0-5/6"), handler.headers)
        self.assertIn(("Accept-Ranges", "bytes"), handler.headers)
        self.assertIn(("ETag", '"demo"'), handler.headers)
        self.assertEqual(handler.wfile.getvalue(), b"abcdef")

    def test_hls_proxy_segment_headers_mimic_browser_media_request(self):
        headers = {
            "User-Agent": "ua-demo",
            "Referer": "https://missav.ai/cn/demo",
            "Origin": "https://missav.ai",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }

        media_headers = N_m3u8DL_RE_Downloader._headers_for_hls_proxy_upstream(
            "https://surrit.com/demo/seg-0001.ts",
            headers,
        )
        playlist_headers = N_m3u8DL_RE_Downloader._headers_for_hls_proxy_upstream(
            "https://surrit.com/demo/playlist.m3u8",
            headers,
        )

        self.assertNotIn("Origin", media_headers)
        self.assertEqual(media_headers["Accept-Encoding"], "identity;q=1, *;q=0")
        self.assertEqual(media_headers["Range"], "bytes=0-")
        self.assertEqual(media_headers["Sec-Fetch-Dest"], "video")
        self.assertEqual(media_headers["Sec-Fetch-Mode"], "no-cors")
        self.assertEqual(media_headers["Sec-Fetch-Site"], "same-origin")
        self.assertEqual(playlist_headers["Sec-Fetch-Dest"], "empty")

    def test_hls_proxy_open_upstream_avoids_curl_cffi_stream_mode(self):
        downloader = N_m3u8DL_RE_Downloader()
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "video/mp4"}
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_curl_cffi.requests = object()

        with patch.dict(sys.modules, {"curl_cffi": fake_curl_cffi}), patch.object(
            downloader,
            "_curl_cffi_get_response",
            return_value=response,
        ) as mocked_get:
            result = downloader._hls_proxy_open_upstream(
                "https://surrit.com/demo/seg1.m4s",
                {"Referer": "https://missav.ai/cn/demo"},
                None,
            )

        self.assertIs(result, response)
        self.assertNotIn("stream", mocked_get.call_args.kwargs)

    def test_response_iter_bytes_prefers_buffered_content_before_iter_content(self):
        class FakeResponse:
            content = b"abcdef"

            def iter_content(self, *args, **kwargs):
                raise AssertionError("buffered content should be used before iter_content")

        self.assertEqual(
            list(N_m3u8DL_RE_Downloader._response_iter_bytes(FakeResponse(), chunk_size=3)),
            [b"abc", b"def"],
        )

    def test_response_iter_bytes_prefers_no_arg_iter_content_without_buffered_content(self):
        class FakeResponse:
            content = b""

            def iter_content(self, *args, **kwargs):
                if args or kwargs:
                    raise AssertionError("chunk_size should not be passed first")
                return iter([b"abc"])

        self.assertEqual(list(N_m3u8DL_RE_Downloader._response_iter_bytes(FakeResponse())), [b"abc"])

    def test_downloaded_file_size_hint_includes_recent_external_temp_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            started_at = time.time()
            save_path = os.path.join(temp_dir, "demo.mp4")
            temp_segments = Path(temp_dir) / "N_m3u8DL-RE_Download"
            temp_segments.mkdir()
            (temp_segments / "0001.m4s").write_bytes(b"a" * 1024)
            (temp_segments / "0002.m4s").write_bytes(b"b" * 2048)

            size = N_m3u8DL_RE_Downloader._downloaded_file_size_hint(save_path, since=started_at)

        self.assertEqual(size, 3072)

    def test_missav_surrit_external_headers_are_clean_referer_headers(self):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta.update(
            {
                "headers": {
                    "Referer": "https://missav.ai/cn/demo",
                    "Origin": "https://missav.ai",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "cross-site",
                    "Range": "bytes=0-",
                    "Cookie": "__cf_bm=token",
                },
                "missav_use_browser_headers": True,
            }
        )
        headers = N_m3u8DL_RE_Downloader._headers_from_meta(item, "ua-demo", "https://missav.ai/cn/demo")

        clean = N_m3u8DL_RE_Downloader._headers_for_nm3u8_external(
            item, headers, "ua-demo", "https://missav.ai/cn/demo"
        )

        self.assertEqual(clean["User-Agent"], "ua-demo")
        self.assertEqual(clean["Referer"], "https://missav.ai/cn/demo")
        self.assertEqual(clean["Cookie"], "__cf_bm=token")
        self.assertNotIn("Origin", clean)
        self.assertNotIn("Sec-Fetch-Mode", clean)
        self.assertNotIn("Range", clean)

    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_playwright_hls")
    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_curl_cffi_hls", side_effect=ExternalToolError("curl blocked"))
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable")
    def test_missav_surrit_downloader_uses_playwright_after_curl_cffi_failure(
        self,
        mocked_resolve,
        _mocked_curl,
        mocked_playwright,
    ):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta.update(
            {
                "headers": {"Referer": "https://missav.ai/cn/demo", "Cookie": "__cf_bm=token"},
                "missav_use_browser_headers": True,
                "browser_storage_state": {"cookies": [], "origins": []},
                "force_python_hls": True,
            }
        )

        N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        mocked_playwright.assert_called_once()
        mocked_resolve.assert_not_called()

    def test_playlist_text_from_cache_ignores_fragment(self):
        cache = {"https://surrit.com/demo/playlist.m3u8?token=1": "#EXTM3U"}

        result = N_m3u8DL_RE_Downloader._playlist_text_from_cache(
            cache,
            "https://surrit.com/demo/playlist.m3u8?token=1#media",
        )

        self.assertEqual(result, "#EXTM3U")

    def test_playwright_launch_kwargs_use_visible_browser_for_missav_surrit(self):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")

        kwargs = N_m3u8DL_RE_Downloader._playwright_launch_kwargs(item, "http://127.0.0.1:7890")

        self.assertFalse(kwargs["headless"])
        self.assertEqual(kwargs["proxy"], {"server": "http://127.0.0.1:7890"})
        self.assertIn("--disable-blink-features=AutomationControlled", kwargs["args"])

    def test_playwright_capture_playlist_from_referer_reads_browser_response_body(self):
        class ExpectResponseContext:
            def __init__(self, response):
                self.value = response

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        page = Mock()
        response = Mock()
        response.url = "https://surrit.com/demo/playlist.m3u8"
        response.status = 200
        response.body.return_value = b"#EXTM3U\n#EXTINF:4,\nseg.ts\n"
        page.expect_response.return_value = ExpectResponseContext(response)

        result = N_m3u8DL_RE_Downloader._playwright_capture_playlist_from_referer(
            page,
            "https://missav.ai/cn/demo",
            "https://surrit.com/demo/playlist.m3u8",
        )

        self.assertEqual(result["https://surrit.com/demo/playlist.m3u8"], "#EXTM3U\n#EXTINF:4,\nseg.ts\n")
        page.goto.assert_called_once_with("https://missav.ai/cn/demo", wait_until="domcontentloaded", timeout=60000)
        page.expect_response.assert_called_once()

    def test_playwright_capture_playlist_from_referer_ignores_non_playlist_body(self):
        class ExpectResponseContext:
            def __init__(self, response):
                self.value = response

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        page = Mock()
        response = Mock()
        response.url = "https://surrit.com/demo/playlist.m3u8"
        response.status = 200
        response.body.return_value = b"Forbidden"
        page.expect_response.return_value = ExpectResponseContext(response)

        result = N_m3u8DL_RE_Downloader._playwright_capture_playlist_from_referer(
            page,
            "https://missav.ai/cn/demo",
            "https://surrit.com/demo/playlist.m3u8",
        )

        self.assertEqual(result, {})

    def test_playwright_fetch_bytes_decodes_page_result(self):
        page = Mock()
        page.evaluate.return_value = {"status": 200, "body": "YWFh"}

        result = N_m3u8DL_RE_Downloader._playwright_fetch_bytes(page, "https://surrit.com/seg.ts")

        self.assertEqual(result, b"aaa")
        page.evaluate.assert_called_once()

    def test_playwright_fetch_or_goto_tries_media_request_before_plain_same_origin_fetch(self):
        page = Mock()
        with patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_fetch_bytes",
            side_effect=ExternalToolError("CORS blocked"),
        ) as mocked_fetch, patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_media_request_bytes",
            return_value=b"media",
        ) as mocked_media, patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_fetch_bytes",
        ) as mocked_same_origin, patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_goto_bytes",
        ) as mocked_goto:
            result = N_m3u8DL_RE_Downloader._playwright_fetch_or_goto_bytes(
                page,
                "https://surrit.com/demo/seg.ts",
            )

        self.assertEqual(result, b"media")
        mocked_fetch.assert_called_once()
        mocked_media.assert_called_once()
        mocked_same_origin.assert_not_called()
        mocked_goto.assert_not_called()

    def test_playwright_fetch_or_goto_uses_plain_same_origin_fetch_when_media_fails(self):
        page = Mock()
        with patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_fetch_bytes",
            side_effect=ExternalToolError("CORS blocked"),
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_media_request_bytes",
            side_effect=ExternalToolError("video blocked"),
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_fetch_bytes",
            return_value=b"plain",
        ) as mocked_same_origin, patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_goto_bytes",
        ) as mocked_goto:
            result = N_m3u8DL_RE_Downloader._playwright_fetch_or_goto_bytes(
                page,
                "https://surrit.com/demo/seg.ts",
            )

        self.assertEqual(result, b"plain")
        mocked_same_origin.assert_called_once()
        mocked_goto.assert_not_called()

    def test_playwright_fetch_or_goto_uses_navigation_when_fetches_fail(self):
        page = Mock()
        with patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_fetch_bytes",
            side_effect=ExternalToolError("CORS blocked"),
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_media_request_bytes",
            side_effect=ExternalToolError("video blocked"),
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_same_origin_fetch_bytes",
            side_effect=ExternalToolError("plain blocked"),
        ), patch.object(
            N_m3u8DL_RE_Downloader,
            "_playwright_goto_bytes",
            return_value=b"segment",
        ) as mocked_goto:
            result = N_m3u8DL_RE_Downloader._playwright_fetch_or_goto_bytes(
                page,
                "https://surrit.com/seg.ts",
            )

        self.assertEqual(result, b"segment")
        mocked_goto.assert_called_once()

    def test_playwright_same_origin_media_request_reads_browser_response(self):
        class ExpectResponseContext:
            def __init__(self, response):
                self.value = response

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        page = Mock()
        response = Mock()
        response.url = "https://surrit.com/demo/playlist.m3u8"
        response.status = 206
        response.body.return_value = b"playlist"
        page.expect_response.return_value = ExpectResponseContext(response)

        result = N_m3u8DL_RE_Downloader._playwright_same_origin_media_request_bytes(
            page,
            "https://surrit.com/demo/playlist.m3u8",
        )

        self.assertEqual(result, b"playlist")
        page.goto.assert_called_once_with("https://surrit.com/demo/", wait_until="commit", timeout=60000)
        page.expect_response.assert_called_once()
        page.evaluate.assert_called_once()

    def test_playwright_same_origin_landing_url_uses_directory(self):
        result = N_m3u8DL_RE_Downloader._playwright_same_origin_landing_url(
            "https://surrit.com/a/b/playlist.m3u8?token=1"
        )

        self.assertEqual(result, "https://surrit.com/a/b/")

    def test_playwright_cookie_header_expands_to_stream_and_referer_hosts(self):
        cookies = N_m3u8DL_RE_Downloader._cookies_from_header(
            "__cf_bm=token; sid=abc",
            "https://surrit.com/demo/playlist.m3u8",
            "https://missav.ai/cn/demo",
        )

        pairs = {(cookie["domain"], cookie["name"], cookie["value"]) for cookie in cookies}
        self.assertIn(("surrit.com", "__cf_bm", "token"), pairs)
        self.assertIn(("missav.ai", "sid", "abc"), pairs)

    def test_hls_encryption_guard_allows_aes_128(self):
        import m3u8

        playlist = m3u8.loads(
            """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:4,
seg.ts
#EXT-X-ENDLIST
""",
            uri="https://surrit.com/demo/playlist.m3u8",
        )

        self.assertFalse(N_m3u8DL_RE_Downloader._has_unsupported_hls_encryption(playlist))

    def test_hls_encryption_guard_rejects_unknown_method(self):
        import m3u8

        playlist = m3u8.loads(
            """#EXTM3U
#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key.bin"
#EXTINF:4,
seg.ts
#EXT-X-ENDLIST
""",
            uri="https://surrit.com/demo/playlist.m3u8",
        )

        self.assertTrue(N_m3u8DL_RE_Downloader._has_unsupported_hls_encryption(playlist))

    def test_hls_segment_writer_reports_byte_progress_for_speed(self):
        import m3u8

        downloader = N_m3u8DL_RE_Downloader()
        playlist = m3u8.loads(
            """#EXTM3U
#EXTINF:4,
seg1.ts
#EXTINF:4,
seg2.ts
#EXT-X-ENDLIST
""",
            uri="https://surrit.com/demo/playlist.m3u8",
        )
        progress_calls = []

        def fetch(url):
            return b"aaa" if url.endswith("seg1.ts") else b"bbbbb"

        def progress(value, **kwargs):
            progress_calls.append((value, kwargs))

        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "out.ts"
            downloader._write_hls_segments(playlist, raw_path, fetch, progress, lambda: False)

        self.assertEqual(progress_calls[-1][1]["bytes_downloaded"], 8)
        self.assertGreater(progress_calls[-1][0], progress_calls[0][0])

    def test_hls_aes_128_segments_are_decrypted_with_media_sequence_iv(self):
        import m3u8
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad

        downloader = N_m3u8DL_RE_Downloader()
        key = b"0123456789abcdef"
        plain = b"hls-segment-data"
        iv = (42).to_bytes(16, byteorder="big")
        encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain, 16))
        playlist_text = """#EXTM3U
#EXT-X-MEDIA-SEQUENCE:42
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:4,
seg.ts
#EXT-X-ENDLIST
"""
        playlist = m3u8.loads(playlist_text, uri="https://surrit.com/demo/playlist.m3u8")

        def fetch(url):
            if url.endswith("key.bin"):
                return key
            if url.endswith("seg.ts"):
                return encrypted
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = os.path.join(temp_dir, "out.ts")
            downloader._write_hls_segments(playlist, Path(raw_path), fetch, lambda _value: None, lambda: False)
            with open(raw_path, "rb") as fp:
                self.assertEqual(fp.read(), plain)

    def test_hls_aes_128_iv_parser_accepts_hex_iv(self):
        iv = N_m3u8DL_RE_Downloader._hls_aes_iv("0x1", 99)
        self.assertEqual(iv, (1).to_bytes(16, byteorder="big"))

    def test_curl_cffi_hls_fallback_uses_cached_playlist_text(self):
        downloader = N_m3u8DL_RE_Downloader()
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta["playlist_cache"] = {
            "https://surrit.com/demo/playlist.m3u8": """#EXTM3U
#EXT-X-TARGETDURATION:8
#EXTINF:4,
seg1.ts
#EXT-X-ENDLIST
"""
        }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, headers=None, timeout=None):
                self.calls.append(url)
                response = Mock()
                response.status_code = 200
                response.text = ""
                response.content = b"aaa" if url.endswith("seg1.ts") else b""
                return response

            def close(self):
                pass

        fake_session = FakeSession()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.ts")
            with patch.object(downloader, "_make_curl_cffi_session", return_value=fake_session):
                downloader._download_with_curl_cffi_hls(
                    item,
                    save_path,
                    {"Referer": "https://missav.ai/cn/demo"},
                    None,
                    lambda _value: None,
                    lambda: False,
                )
            with open(save_path, "rb") as fp:
                self.assertEqual(fp.read(), b"aaa")

        self.assertEqual(fake_session.calls, ["https://surrit.com/demo/seg1.ts"])

    def test_curl_cffi_hls_fallback_downloads_media_segments(self):
        downloader = N_m3u8DL_RE_Downloader()
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        playlist = """#EXTM3U
#EXT-X-TARGETDURATION:8
#EXTINF:4,
seg1.ts
#EXTINF:4,
https://cdn.example.com/seg2.ts
#EXT-X-ENDLIST
"""

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, headers=None, timeout=None):
                self.calls.append((url, headers, timeout))
                response = Mock()
                response.status_code = 200
                if url.endswith("playlist.m3u8"):
                    response.text = playlist
                    response.content = playlist.encode("utf-8")
                elif url.endswith("seg1.ts"):
                    response.text = ""
                    response.content = b"aaa"
                elif url.endswith("seg2.ts"):
                    response.text = ""
                    response.content = b"bbb"
                else:
                    response.status_code = 404
                    response.text = ""
                    response.content = b""
                return response

            def close(self):
                pass

        fake_session = FakeSession()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.ts")
            with patch.object(downloader, "_make_curl_cffi_session", return_value=fake_session):
                downloader._download_with_curl_cffi_hls(
                    item,
                    save_path,
                    {"Referer": "https://missav.ai/cn/demo"},
                    None,
                    lambda _value: None,
                    lambda: False,
                )
            with open(save_path, "rb") as fp:
                self.assertEqual(fp.read(), b"aaabbb")

        self.assertEqual(fake_session.calls[0][0], "https://surrit.com/demo/playlist.m3u8")
        self.assertEqual(fake_session.calls[1][0], "https://surrit.com/demo/seg1.ts")
        self.assertEqual(fake_session.calls[2][0], "https://cdn.example.com/seg2.ts")

    @patch.object(N_m3u8DL_RE_Downloader, "_cleanup_external_temp_files")
    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_yt_dlp_fallback")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_missav_surrit_skips_external_tool_after_browser_fallback_failure(
        self,
        mocked_resolve,
        mocked_popen,
        mocked_fallback,
        mocked_cleanup,
    ):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta.update(
            {
                "headers": {"Referer": "https://missav.ai/cn/demo"},
                "missav_use_browser_headers": True,
                "force_python_hls": True,
            }
        )

        with patch.object(
            N_m3u8DL_RE_Downloader,
            "_download_with_curl_cffi_hls",
            side_effect=ExternalToolError("curl blocked"),
        ) as mocked_curl, patch.object(
            N_m3u8DL_RE_Downloader,
            "_download_with_playwright_hls",
            side_effect=ExternalToolError("browser blocked"),
        ) as mocked_playwright:
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        mocked_curl.assert_called_once()
        mocked_playwright.assert_called_once()
        mocked_fallback.assert_called_once()
        mocked_resolve.assert_not_called()
        mocked_popen.assert_not_called()
        mocked_cleanup.assert_not_called()

    @patch.object(N_m3u8DL_RE_Downloader, "_cleanup_external_temp_files")
    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_yt_dlp_fallback")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_missav_surrit_with_cached_playlist_skips_yt_dlp_network_playlist_retry(
        self,
        mocked_resolve,
        mocked_popen,
        mocked_fallback,
        mocked_cleanup,
    ):
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        item.meta.update(
            {
                "headers": {"Referer": "https://missav.ai/cn/demo"},
                "missav_use_browser_headers": True,
                "playlist_cache": {"https://surrit.com/demo/playlist.m3u8": "#EXTM3U"},
                "force_python_hls": True,
            }
        )

        with patch.object(
            N_m3u8DL_RE_Downloader,
            "_download_with_curl_cffi_hls",
            side_effect=ExternalToolError("segment blocked"),
        ) as mocked_curl, patch.object(
            N_m3u8DL_RE_Downloader,
            "_download_with_playwright_hls",
            side_effect=ExternalToolError("browser blocked"),
        ) as mocked_playwright:
            with self.assertRaises(ExternalToolError):
                N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        mocked_curl.assert_called_once()
        mocked_playwright.assert_called_once()
        mocked_fallback.assert_not_called()
        mocked_resolve.assert_not_called()
        mocked_popen.assert_not_called()
        mocked_cleanup.assert_not_called()

    @patch.object(N_m3u8DL_RE_Downloader, "_download_with_yt_dlp_fallback")
    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_does_not_use_yt_dlp_fallback_for_other_sources(
        self,
        _mocked_resolve,
        mocked_popen,
        mocked_wait_progress,
        mocked_fallback,
    ):
        process = Mock()
        process.returncode = 3
        process.poll.return_value = 0
        mocked_popen.return_value = process
        mocked_wait_progress.return_value = None
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="live", source="douyin")

        with self.assertRaises(ExternalToolError):
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        mocked_fallback.assert_not_called()

    def test_yt_dlp_fallback_params_enable_impersonation_and_proxy(self):
        params = N_m3u8DL_RE_Downloader._yt_dlp_params(
            "D:/downloads/demo.mp4",
            {"Referer": "https://missav.ai/cn/demo"},
            "http://127.0.0.1:7890",
            lambda _status: None,
        )

        self.assertEqual(params["impersonate"], "")
        self.assertEqual(params["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(params["http_headers"]["Referer"], "https://missav.ai/cn/demo")

    def test_yt_dlp_fallback_retries_without_impersonation_and_wraps_failure(self):
        from yt_dlp.utils import YoutubeDLError

        downloader = N_m3u8DL_RE_Downloader()
        item = VideoItem(url="https://surrit.com/demo/playlist.m3u8", title="miss", source="missav")
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "demo.mp4")
            with patch.object(downloader, "_run_yt_dlp") as mocked_run:
                mocked_run.side_effect = [YoutubeDLError("bad impersonation"), YoutubeDLError("still forbidden")]

                with self.assertRaises(ExternalToolError):
                    downloader._download_with_yt_dlp_fallback(
                        item,
                        save_path,
                        {"Referer": "https://missav.ai/cn/demo"},
                        None,
                        lambda _value: None,
                        lambda: False,
                    )

        self.assertEqual(mocked_run.call_count, 2)
        first_params = mocked_run.call_args_list[0].args[1]
        retry_params = mocked_run.call_args_list[1].args[1]
        self.assertIn("impersonate", first_params)
        self.assertNotIn("impersonate", retry_params)

    @patch.object(N_m3u8DL_RE_Downloader, "_cleanup_external_temp_files")
    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress")
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_keeps_successful_output_when_final_progress_callback_fails(
        self,
        _mocked_resolve,
        mocked_popen,
        mocked_wait_progress,
        mocked_cleanup,
    ):
        process = Mock()
        process.returncode = 0
        process.poll.return_value = 0
        mocked_popen.return_value = process
        mocked_wait_progress.return_value = None
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="直播", source="douyin")

        def progress(value):
            if value == 100:
                raise RuntimeError("ui callback failed")

        N_m3u8DL_RE_Downloader().download(item, "demo.mp4", progress, lambda: False)

        mocked_cleanup.assert_not_called()

    @patch.object(N_m3u8DL_RE_Downloader, "_wait_external_process_with_file_progress", side_effect=RuntimeError("callback failed"))
    @patch("app.core.downloaders.m3u8.subprocess.Popen")
    @patch("app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable", return_value="N_m3u8DL-RE.exe")
    def test_m3u8_downloader_terminates_process_when_wait_progress_raises(
        self,
        _mocked_resolve,
        mocked_popen,
        _mocked_wait_progress,
    ):
        alive = {"value": True}
        process = Mock()

        def poll():
            return None if alive["value"] else -9

        def terminate():
            alive["value"] = False
            process.returncode = -9

        process.returncode = None
        process.poll.side_effect = poll
        process.terminate.side_effect = terminate
        mocked_popen.return_value = process
        item = VideoItem(url="https://cdn.example.com/live/index.m3u8", title="直播", source="douyin")

        with self.assertRaises(ExternalToolError):
            N_m3u8DL_RE_Downloader().download(item, "demo.mp4", lambda _value: None, lambda: False)

        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        process.wait.assert_called_with(timeout=5.0)

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
        manager.queue = PendingDownloadQueue()
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
        manager.queue = PendingDownloadQueue()
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
        self.assertTrue(worker.video.meta["user_cancel_requested"])

    def test_download_manager_cancel_task_returns_none_when_missing(self):
        """验证 `test_download_manager_cancel_task_returns_none_when_missing` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.queue = queue.Queue()
        manager._workers_lock = threading.Lock()
        manager.slot_semaphore = Mock()
        manager.workers = []

        self.assertIsNone(manager.cancel_task("missing"))

    def test_worker_thread_finished_disconnects_worker_callbacks(self):
        manager = DownloadManager.__new__(DownloadManager)
        worker = DownloadWorker(VideoItem(url="https://example.com/1.mp4", title="demo", source="douyin"), "downloads")
        worker.sig_start.connect(lambda *_args: None)
        worker.sig_progress.connect(lambda *_args: None)
        worker.sig_finished.connect(lambda *_args: None)
        worker.sig_error.connect(lambda *_args: None)
        worker.finished.connect(lambda *_args: None)
        worker._completion_callback = Mock()

        manager._on_worker_thread_finished(worker)

        self.assertEqual(worker.sig_start._callbacks, [])
        self.assertEqual(worker.sig_progress._callbacks, [])
        self.assertEqual(worker.sig_finished._callbacks, [])
        self.assertEqual(worker.sig_error._callbacks, [])
        self.assertEqual(worker.finished._callbacks, [])
        self.assertIsNone(worker._completion_callback)

    def test_download_worker_generate_filename_prefers_meta_filename(self):
        """验证 `test_download_worker_generate_filename_prefers_meta_filename` 对应场景是否符合预期，供 `DownloaderStrategyTests` 使用。"""
        item = VideoItem(url="https://example.com/video.mp4", title="显示标题", source="bilibili")
        item.meta["preferred_filename"] = "P01_真实文件名.mp4"
        worker = DownloadWorker(item, "downloads")

        with patch("app.config.cfg.get", return_value="current"):
            filename = worker._generate_filename(".mp4")

        self.assertEqual(filename, "P01_真实文件名.mp4")

    def test_download_worker_generate_filename_uses_configured_template(self):
        item = VideoItem(url="https://example.com/video.mp4", title="Demo Title", source="bilibili")
        item.meta["index"] = 7
        worker = DownloadWorker(item, "downloads")

        with patch("app.config.cfg.get", return_value="{platform}_{title}_{index}"):
            filename = worker._generate_filename(".mp4")

        self.assertEqual(filename, "bilibili_Demo Title_7.mp4")

    def test_download_worker_remembers_output_path_for_frontend_stages(self):
        item = VideoItem(url="https://example.com/video.mp4", title="Demo Title", source="bilibili")
        worker = DownloadWorker(item, "downloads")

        worker._remember_output_path(os.path.join("downloads", "bilibili_Demo.mp4"))

        self.assertEqual(item.meta["output_filename"], "bilibili_Demo.mp4")
        self.assertEqual(item.meta["filename"], "bilibili_Demo.mp4")
        self.assertEqual(item.meta["save_dir"], "downloads")

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

    def test_download_worker_resolve_save_dir_keeps_xiaohongshu_video_flat(self):
        """验证小红书单视频在未标记子目录时保持直接落盘。"""
        item = VideoItem(url="https://example.com/video.mp4", title="单视频", source="xiaohongshu")
        item.meta.update(
            {
                "content_type": "video",
                "folder_name": "作者目录",
            }
        )
        worker = DownloadWorker(item, "downloads")

        self.assertEqual(worker._resolve_save_dir(), "downloads")

    def test_download_worker_resolve_save_dir_keeps_xiaohongshu_gallery_flat_without_folder_name(self):
        """小红书图文未显式提供目录名时，不应被空值清洗成 `untitled` 子目录。"""
        item = VideoItem(url="https://example.com/cover.jpg", title="图文", source="xiaohongshu")
        item.meta.update(
            {
                "content_type": "gallery",
                "is_gallery": True,
            }
        )
        worker = DownloadWorker(item, "downloads")

        self.assertEqual(worker._resolve_save_dir(), "downloads")

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
