"""Tests for m3u8 downloader lifecycle and callback safety."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from app.core.downloaders.m3u8 import N_m3u8DL_RE_Downloader
from app.exceptions import ExternalToolError
from app.models import VideoItem


class M3u8DownloaderLifecycleTests(unittest.TestCase):
    @staticmethod
    def _fake_m3u8_module():
        """构造最小 m3u8 模块，隔离真实依赖，只让 fallback 流程走到分片写入阶段。"""
        fake_m3u8 = types.ModuleType("m3u8")

        class FakeSegment:
            absolute_uri = "https://example.com/segment.ts"
            key = None

        class FakePlaylist:
            is_variant = False
            playlists: list[object] = []
            segments = [FakeSegment()]

        fake_m3u8.loads = MagicMock(return_value=FakePlaylist())
        return fake_m3u8

    @staticmethod
    def _fake_curl_cffi_module():
        """构造 curl_cffi 替身，验证临时目录清理而不发起真实网络请求。"""
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_requests = types.ModuleType("curl_cffi.requests")

        class FakeResponse:
            status_code = 200
            text = "#EXTM3U\n"
            content = b"segment"

        class FakeSession:
            def get(self, *_args, **_kwargs):
                return FakeResponse()

            def close(self):
                return None

        fake_requests.Session = MagicMock(return_value=FakeSession())
        fake_curl_cffi.requests = fake_requests
        return fake_curl_cffi, fake_requests

    @staticmethod
    def _fake_playwright_modules():
        """构造 Playwright 上下文替身，覆盖浏览器 fallback 的异常清理路径。"""
        fake_playwright = types.ModuleType("playwright")
        fake_sync_api = types.ModuleType("playwright.sync_api")

        class FakePlaywrightError(Exception):
            pass

        class FakePage:
            pass

        class FakeContext:
            def new_page(self):
                return FakePage()

        class FakeBrowser:
            def new_context(self, **_kwargs):
                return FakeContext()

            def close(self):
                return None

        class FakeChromium:
            def launch(self, **_kwargs):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_sync_api.Error = FakePlaywrightError
        fake_sync_api.sync_playwright = MagicMock(return_value=FakePlaywright())
        return fake_playwright, fake_sync_api

    def test_success_with_failing_final_callback_does_not_delete_output(self):
        """最终 100% 回调失败只是 UI 问题，已经成功的输出文件不能被当失败缓存删除。"""
        save_dir = tempfile.mkdtemp()
        save_path = os.path.join(save_dir, "clip.mp4")
        with open(save_path, "wb") as fp:
            fp.write(b"ok")

        video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="test")
        process = MagicMock()
        process.poll.return_value = 0
        process.returncode = 0

        def progress_callback(_value: int) -> None:
            if _value == 100:
                raise RuntimeError("ui callback failed")

        with patch.object(N_m3u8DL_RE_Downloader, "is_available", return_value=True), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable",
            return_value="tool",
        ), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.build_download_command",
            return_value=["tool"],
        ), patch("app.core.downloaders.m3u8.subprocess.Popen", return_value=process), patch(
            "app.core.downloaders.m3u8.ExternalToolRunner.wait_process",
        ):
            downloader = N_m3u8DL_RE_Downloader()
            downloader.download(video, save_path, progress_callback, lambda: False)

        self.assertTrue(os.path.exists(save_path))

    def test_wait_process_callback_error_does_not_delete_successful_output(self):
        """wait 阶段的进度回调异常不应覆盖外部工具已成功退出的事实。"""
        save_dir = tempfile.mkdtemp()
        save_path = os.path.join(save_dir, "clip.mp4")
        with open(save_path, "wb") as fp:
            fp.write(b"ok")

        video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="test")
        process = subprocess.Popen(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", "exit", "0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=5)

        def progress_callback(value: int) -> None:
            if value == 50:
                raise TypeError("progress ui failed")

        with patch.object(N_m3u8DL_RE_Downloader, "is_available", return_value=True), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.resolve_executable",
            return_value="tool",
        ), patch(
            "app.core.downloaders.m3u8.NM3U8DLREExternalTool.build_download_command",
            return_value=["tool"],
        ), patch("app.core.downloaders.m3u8.subprocess.Popen", return_value=process):
            downloader = N_m3u8DL_RE_Downloader()
            downloader.download(video, save_path, progress_callback, lambda: False)

        self.assertTrue(os.path.exists(save_path))

    def test_curl_cffi_fallback_cleans_temp_dir_on_failure(self):
        fake_m3u8 = self._fake_m3u8_module()
        fake_curl_cffi, fake_requests = self._fake_curl_cffi_module()

        with tempfile.TemporaryDirectory() as save_dir:
            save_path = os.path.join(save_dir, "clip.mp4")
            temp_dir = os.path.join(save_dir, "clip_curl_cffi_hls")
            video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="missav")

            with patch.dict(
                sys.modules,
                {"m3u8": fake_m3u8, "curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_requests},
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_write_hls_segments",
                side_effect=ExternalToolError("segment write failed"),
            ):
                downloader = N_m3u8DL_RE_Downloader()
                with self.assertRaises(ExternalToolError):
                    downloader._download_with_curl_cffi_hls(
                        video,
                        save_path,
                        {"User-Agent": "test"},
                        None,
                        lambda *_args, **_kwargs: None,
                        lambda: False,
                    )

            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(os.path.exists(save_path))

    def test_playwright_fallback_cleans_temp_dir_on_failure(self):
        fake_m3u8 = self._fake_m3u8_module()
        fake_playwright, fake_sync_api = self._fake_playwright_modules()

        with tempfile.TemporaryDirectory() as save_dir:
            save_path = os.path.join(save_dir, "clip.mp4")
            temp_dir = os.path.join(save_dir, "clip_playwright_hls")
            video = VideoItem(url="https://example.com/stream.m3u8", title="clip", source="missav")

            with patch.dict(
                sys.modules,
                {"m3u8": fake_m3u8, "playwright": fake_playwright, "playwright.sync_api": fake_sync_api},
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_playwright_fetch_or_goto_bytes",
                return_value=b"#EXTM3U\n",
            ), patch.object(
                N_m3u8DL_RE_Downloader,
                "_write_hls_segments",
                side_effect=ExternalToolError("segment write failed"),
            ):
                downloader = N_m3u8DL_RE_Downloader()
                with self.assertRaises(ExternalToolError):
                    downloader._download_with_playwright_hls(
                        video,
                        save_path,
                        {"User-Agent": "test"},
                        None,
                        lambda *_args, **_kwargs: None,
                        lambda: False,
                    )

            self.assertFalse(os.path.exists(temp_dir))
            self.assertFalse(os.path.exists(save_path))

    def test_sweep_orphaned_workspaces_removes_stale_dirs(self):
        """启动清扫同时覆盖新版统一工作目录和旧版 fallback 目录。"""
        with tempfile.TemporaryDirectory() as save_dir:
            nm3u8_workspace = os.path.join(save_dir, N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME, "ucp-foo")
            curl_workspace = os.path.join(save_dir, "xxx_curl_cffi_hls")
            playwright_workspace = os.path.join(save_dir, "yyy_playwright_hls")
            for path in (nm3u8_workspace, curl_workspace, playwright_workspace):
                os.makedirs(path, exist_ok=True)

            cleaned = N_m3u8DL_RE_Downloader.sweep_orphaned_workspaces([save_dir])

            self.assertEqual(cleaned, 3)
            self.assertFalse(os.path.exists(os.path.join(save_dir, N_m3u8DL_RE_Downloader.NM3U8_TEMP_ROOT_NAME)))
            self.assertFalse(os.path.exists(curl_workspace))
            self.assertFalse(os.path.exists(playwright_workspace))


if __name__ == "__main__":
    unittest.main()
