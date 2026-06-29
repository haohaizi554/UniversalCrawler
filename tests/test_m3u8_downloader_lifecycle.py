"""Tests for m3u8 downloader lifecycle and callback safety."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.core.downloaders.m3u8 import N_m3u8DL_RE_Downloader
from app.models import VideoItem

class M3u8DownloaderLifecycleTests(unittest.TestCase):
    def test_success_with_failing_final_callback_does_not_delete_output(self):
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

if __name__ == "__main__":
    unittest.main()
