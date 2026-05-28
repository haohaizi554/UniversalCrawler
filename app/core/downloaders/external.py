from __future__ import annotations

import os
import subprocess
import time

from app.config import DEFAULT_USER_AGENT
from app.exceptions import DownloaderStoppedError
from app.utils.runtime_paths import resolve_tool_file

from .base import ProgressCallback, StopCheck


def build_hidden_startupinfo():
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def build_new_console_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


class ExternalToolRunner:
    @staticmethod
    def resolve_executable(preferred_name: str, fallback_name: str | None = None, version_args: list[str] | None = None) -> str | None:
        preferred_path = resolve_tool_file(preferred_name)
        if preferred_path.exists():
            return str(preferred_path)
        if not fallback_name:
            return None
        try:
            subprocess.run(
                [fallback_name, *(version_args or ["-version"])],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return fallback_name
        except (OSError, subprocess.CalledProcessError):
            return None

    @staticmethod
    def wait_process(
        process: subprocess.Popen,
        check_stop_func: StopCheck,
        progress_callback: ProgressCallback | None = None,
        progress_value: int | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        while process.poll() is None:
            if check_stop_func():
                process.kill()
                raise DownloaderStoppedError("用户停止下载")
            time.sleep(poll_interval)
            if progress_callback is not None and progress_value is not None:
                progress_callback(progress_value)


class FFmpegExternalTool:
    EXE_PATH = "ffmpeg.exe"
    CLI_NAME = "ffmpeg"

    @classmethod
    def resolve_executable(cls) -> str | None:
        return ExternalToolRunner.resolve_executable(cls.EXE_PATH, cls.CLI_NAME, ["-version"])

    @classmethod
    def is_available(cls) -> bool:
        return cls.resolve_executable() is not None

    @classmethod
    def build_download_command(cls, executable: str, url: str, save_path: str, headers: dict[str, str]) -> list[str]:
        return [
            executable,
            "-y",
            "-user_agent",
            headers.get("User-Agent", DEFAULT_USER_AGENT),
            "-headers",
            f"Referer: {headers.get('Referer', '')}\r\n",
            "-reconnect",
            "1",
            "-reconnect_at_eof",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-timeout",
            "60000000",
            "-i",
            url,
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-bufsize",
            "10M",
            save_path,
        ]

    @classmethod
    def build_merge_command(
        cls,
        executable: str,
        video_path: str,
        audio_path: str | None,
        save_path: str,
    ) -> list[str]:
        command = [executable, "-y", "-i", video_path]
        if audio_path:
            command.extend(["-i", audio_path])
        command.extend(["-c", "copy", save_path])
        return command


class NM3U8DLREExternalTool:
    EXE_PATH = "N_m3u8DL-RE.exe"

    @classmethod
    def resolve_executable(cls) -> str | None:
        path = resolve_tool_file(cls.EXE_PATH)
        return str(path) if path.exists() else None

    @classmethod
    def is_available(cls) -> bool:
        return cls.resolve_executable() is not None

    @classmethod
    def is_m3u8_url(cls, url: str) -> bool:
        url_lower = url.lower()
        return ".m3u8" in url_lower or "m3u8" in url_lower

    @classmethod
    def build_download_command(
        cls,
        executable: str,
        source_url: str,
        save_path: str,
        user_agent: str,
        referer: str,
    ) -> list[str]:
        save_dir = os.path.dirname(save_path)
        save_name_no_ext = os.path.splitext(os.path.basename(save_path))[0]
        return [
            executable,
            source_url,
            "--save-dir",
            save_dir,
            "--save-name",
            save_name_no_ext,
            "--thread-count",
            "16",
            "--download-retry-count",
            "10",
            "--auto-select",
            "true",
            "--header",
            f"User-Agent: {user_agent}",
            "--header",
            f"Referer: {referer}",
            "--mux-after-done",
            "format=mp4",
        ]
