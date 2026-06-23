"""下载器模块，负责 `app/core/downloaders/external.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import os
import subprocess
import time

from app.config import DEFAULT_USER_AGENT, cfg
from app.exceptions import DownloaderStoppedError
from app.utils.runtime_paths import resolve_tool_file

from .base import ProgressCallback, StopCheck
#媒体资源下载的外部工具封装模块，提供接口

def build_hidden_startupinfo():
    """为 Windows 子进程构造隐藏控制台窗口的启动参数。"""
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo

def build_new_console_flags() -> int:
    """返回 Windows 下用于创建独立控制台的进程标志。"""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

class ExternalToolRunner:
    """封装外部工具查找、等待和停止控制的公共逻辑。"""

    @staticmethod
    def resolve_executable(preferred_name: str, fallback_name: str | None = None, version_args: list[str] | None = None) -> str | None:
        """优先查找项目内工具文件，找不到时再回退到系统环境变量。"""
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
        """轮询等待外部进程结束，并在中途响应停止请求与进度回调。"""
        while process.poll() is None:
            if check_stop_func():
                process.kill()
                try:
                    process.wait(timeout=2)
                except Exception:
                    pass
                raise DownloaderStoppedError("用户停止下载")
            time.sleep(poll_interval)
            if progress_callback is not None and progress_value is not None:
                try:
                    progress_callback(progress_value)
                except Exception:
                    pass

class FFmpegExternalTool:
    """封装 ffmpeg 的可执行文件查找与命令构造逻辑。"""
    EXE_PATH = "ffmpeg.exe"
    CLI_NAME = "ffmpeg"

    @classmethod
    def resolve_executable(cls) -> str | None:
        """定位可用的 ffmpeg 可执行文件。"""
        return ExternalToolRunner.resolve_executable(cls.EXE_PATH, cls.CLI_NAME, ["-version"])

    @classmethod
    def is_available(cls) -> bool:
        """判断当前环境是否能直接调用 ffmpeg。"""
        return cls.resolve_executable() is not None

    @classmethod
    def build_download_command(cls, executable: str, url: str, save_path: str, headers: dict[str, str], proxy: str | None = None) -> list[str]:
        """构造 ffmpeg 直连下载媒体流的命令行参数。"""
        cmd = [
            executable,
            "-y",
            "-nostats",
            "-progress",
            "pipe:2",
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
        ]
        if proxy:
            cmd.extend(["-http_proxy", proxy])
        cmd.extend([
            "-i",
            url,
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-bufsize",
            "10M",
            save_path,
        ])
        return cmd

    @classmethod
    def build_merge_command(
        cls,
        executable: str,
        video_path: str,
        audio_path: str | None,
        save_path: str,
    ) -> list[str]:
        """构造音视频合并命令，纯视频场景下不会追加音频输入。"""
        command = [executable, "-y", "-i", video_path]
        if audio_path:
            command.extend(["-i", audio_path])
        command.extend(["-c", "copy", save_path])
        return command

class NM3U8DLREExternalTool:
    """封装 `N_m3u8DL-RE` 的定位、识别和命令构造逻辑。"""
    EXE_PATH = "N_m3u8DL-RE.exe"
    DISPLAY_NAME = "N_m3u8DL-RE"
    WINDOWS_CANDIDATES = ("N_m3u8DL-RE.exe", "N_m3u8DL-RE", "n-m3u8dl-re")
    POSIX_CANDIDATES = ("N_m3u8DL-RE", "n-m3u8dl-re")

    @classmethod
    def executable_candidates(cls) -> tuple[str, ...]:
        """返回当前平台优先级排序后的可执行文件候选名。"""
        if os.name == "nt":
            return cls.WINDOWS_CANDIDATES
        return cls.POSIX_CANDIDATES

    @classmethod
    def cli_candidates(cls) -> tuple[str, ...]:
        """返回适合直接走系统 PATH 探测的命令名。"""
        if os.name == "nt":
            return ("N_m3u8DL-RE.exe", "N_m3u8DL-RE")
        return ("N_m3u8DL-RE", "n-m3u8dl-re")

    @classmethod
    def resolve_executable(cls) -> str | None:
        """定位当前平台可用的 `N_m3u8DL-RE` 可执行文件。"""
        for executable_name in cls.executable_candidates():
            path = resolve_tool_file(executable_name)
            if path.exists():
                return str(path)

        for executable_name in cls.cli_candidates():
            try:
                subprocess.run(
                    [executable_name, "--version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                return executable_name
            except (OSError, subprocess.CalledProcessError):
                continue
        return None

    @classmethod
    def is_available(cls) -> bool:
        """判断当前环境是否具备 HLS 外部下载能力。"""
        return cls.resolve_executable() is not None

    @classmethod
    def is_m3u8_url(cls, url: str) -> bool:
        """粗略判断一个 URL 是否指向 m3u8 播放列表。"""
        url_lower = url.lower()
        return ".m3u8" in url_lower or "m3u8" in url_lower

    @classmethod
    def _m3u8_thread_count(cls) -> str:
        max_concurrent = max(1, int(cfg.get("download", "max_concurrent", 3)))
        return str(max(1, 16 // max_concurrent))

    @classmethod
    def build_download_command(
        cls,
        executable: str,
        source_url: str,
        save_path: str,
        user_agent: str,
        referer: str,
        proxy: str | None = None,
        extra_headers: dict[str, str] | None = None,
        thread_count: str | int | None = None,
    ) -> list[str]:
        """构造 `N_m3u8DL-RE` 的下载命令，并指定输出目录与文件名。"""
        save_dir = os.path.dirname(save_path)
        save_name_no_ext = os.path.splitext(os.path.basename(save_path))[0]
        headers = cls._normalized_headers(user_agent, referer, extra_headers)
        thread_count_text = str(thread_count or cls._m3u8_thread_count())
        cmd = [
            executable,
            source_url,
            "--save-dir",
            save_dir,
            "--save-name",
            save_name_no_ext,
            "--thread-count",
            thread_count_text,
            "--download-retry-count",
            "10",
            "--auto-select",
            "true",
            "--mux-after-done",
            "format=mp4",
        ]
        for key, value in headers.items():
            cmd.extend(["--header", f"{key}: {value}"])
        if proxy:
            cmd.extend(["--custom-proxy", proxy])
        return cmd

    @staticmethod
    def _normalized_headers(
        user_agent: str,
        referer: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        blocked_headers = {
            "host",
            "content-length",
            "connection",
            "transfer-encoding",
        }
        for key, value in (extra_headers or {}).items():
            key_text = str(key or "").strip()
            value_text = str(value or "").strip()
            if not key_text or not value_text:
                continue
            lowered = key_text.lower()
            if lowered.startswith(":") or lowered in blocked_headers:
                continue
            canonical = "-".join(part[:1].upper() + part[1:].lower() for part in lowered.split("-"))
            headers[canonical] = value_text
        headers["User-Agent"] = headers.get("User-Agent") or str(user_agent or DEFAULT_USER_AGENT)
        if referer:
            headers["Referer"] = headers.get("Referer") or str(referer)
        return headers
