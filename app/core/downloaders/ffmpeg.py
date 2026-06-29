"""下载器模块，负责 `app/core/downloaders/ffmpeg.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections import deque

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck
from .external import FFmpegExternalTool, build_hidden_startupinfo

#基于external.py实现
class FFmpegDownloader(BaseDownloader):
    """实现 `FFmpegDownloader` 对应的资源下载与落盘流程。"""
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600
    PROGRESS_TIMEOUT_SEC = 30
    STDERR_POLL_INTERVAL_SEC = 0.2

    @staticmethod
    def _parse_clock_to_seconds(raw: str) -> float | None:
        match = re.match(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\.(?P<ms>\d+))?", raw.strip())
        if not match:
            return None
        seconds = int(match.group("h")) * 3600 + int(match.group("m")) * 60 + int(match.group("s"))
        fraction = match.group("ms")
        if fraction:
            seconds += float(f"0.{fraction}")
        return seconds

    @classmethod
    def _extract_expected_duration(cls, line_str: str, fallback_duration: float | None) -> float | None:
        if fallback_duration and fallback_duration > 0:
            return fallback_duration
        duration_info = re.search(r"Duration:\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
        if not duration_info:
            return fallback_duration
        return cls._parse_clock_to_seconds(duration_info.group(1)) or fallback_duration

    @classmethod
    def _estimate_progress(
        cls,
        *,
        out_time_seconds: float | None,
        total_size_bytes: int | None,
        expected_duration: float | None,
        expected_size_bytes: int | None,
    ) -> int | None:
        if expected_duration and expected_duration > 0 and out_time_seconds is not None:
            return min(99, max(1, int((out_time_seconds / expected_duration) * 100)))
        if expected_size_bytes and expected_size_bytes > 0 and total_size_bytes is not None:
            return min(99, max(1, int((total_size_bytes / expected_size_bytes) * 100)))
        return None

    @classmethod
    def _parse_progress_line(
        cls,
        line_str: str,
        *,
        expected_duration: float | None,
        expected_size_bytes: int | None,
    ) -> tuple[float | None, int | None, int | None]:
        next_duration = cls._extract_expected_duration(line_str, expected_duration)
        total_size_bytes: int | None = None
        out_time_seconds: float | None = None
        progress_value: int | None = None

        if "=" in line_str:
            key, value = line_str.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in {"out_time", "out_time_ms", "out_time_us"}:
                if key == "out_time":
                    out_time_seconds = cls._parse_clock_to_seconds(value)
                else:
                    try:
                        raw_out_time = int(value)
                        # Newer FFmpeg progress output may emit microseconds for both
                        # out_time_us and out_time_ms keys. Prefer the microsecond scale,
                        # and fall back to millisecond scale only for small legacy values.
                        if key == "out_time_ms" and raw_out_time < 1_000_000:
                            out_time_seconds = raw_out_time / 1000
                        else:
                            out_time_seconds = raw_out_time / 1_000_000
                    except ValueError:
                        out_time_seconds = None
            elif key == "total_size":
                try:
                    total_size_bytes = int(value)
                except ValueError:
                    total_size_bytes = None
        else:
            current_time = re.search(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
            if current_time:
                out_time_seconds = cls._parse_clock_to_seconds(current_time.group(1))

        progress_value = cls._estimate_progress(
            out_time_seconds=out_time_seconds,
            total_size_bytes=total_size_bytes,
            expected_duration=next_duration,
            expected_size_bytes=expected_size_bytes,
        )
        return next_duration, total_size_bytes, progress_value

    @classmethod
    def is_available(cls) -> bool:
        
        return FFmpegExternalTool.is_available()

    @classmethod
    def should_use(cls, video_item: VideoItem) -> bool:
        
        duration_sec = video_item.meta.get("duration", 0)
        size_mb = video_item.meta.get("size_mb", 0)
        return bool(size_mb > cls.SIZE_THRESHOLD_MB or duration_sec > cls.DURATION_THRESHOLD_SEC)

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        original_url = video_item.url
        url = original_url
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        trace_id = video_item.meta.get("trace_id")
        ffmpeg = FFmpegExternalTool.resolve_executable()
        if not ffmpeg:
            raise ExternalToolNotFoundError("未找到 ffmpeg.exe")
        proxy = video_item.meta.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        expected_duration = None
        raw_duration = video_item.meta.get("duration")
        if isinstance(raw_duration, (int, float)) and raw_duration > 0:
            expected_duration = float(raw_duration)
        expected_size_bytes = None
        def _resolve_stream_url(source_url: str) -> tuple[str, int | None]:
            resolved_url = source_url
            resolved_size = expected_size_bytes
            try:
                resp = requests.head(
                    source_url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                    proxies=proxies,
                )
                real_url = resp.url
                content_length = resp.headers.get("content-length")
                if content_length:
                    try:
                        resolved_size = int(content_length)
                    except ValueError:
                        resolved_size = None
                debug_logger.log_api(
                    component="FFmpegDownloader",
                    api_name="head_redirect",
                    request={"url": source_url},
                    response_summary={"real_url": real_url, "content_length": resp.headers.get("content-length")},
                    message="ffmpeg 下载前检查真实地址",
                    status_code=resp.status_code,
                    trace_id=trace_id,
                )
                if real_url != source_url:
                    resolved_url = real_url
            except requests.RequestException as exc:
                debug_logger.log_exception(
                    "FFmpegDownloader",
                    "head_redirect",
                    exc,
                    context={"url": source_url},
                    trace_id=trace_id,
                )
            return resolved_url, resolved_size

        startupinfo = build_hidden_startupinfo()

        max_retries = cfg.get("download", "max_retries", 3)
        for attempt in range(max_retries):
            attempt_completed = False
            stderr_tail: deque[str] = deque(maxlen=12)
            current_url, current_expected_size = _resolve_stream_url(original_url)
            url = current_url
            if current_expected_size:
                expected_size_bytes = current_expected_size
            cmd = FFmpegExternalTool.build_download_command(ffmpeg, url, save_path, headers, proxy=proxy)
            debug_logger.log_command(
                component="FFmpegDownloader",
                tool_name="ffmpeg",
                command_args=cmd,
                message="准备调用 ffmpeg 执行下载",
                context={"save_path": save_path, "source_url": url, "title": video_item.title, "attempt": attempt + 1},
                trace_id=trace_id,
            )
            process = None
            stderr_thread = None
            try:
                process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                )
                last_progress_time = time.time()
                last_progress = 0
                stderr_queue: queue.Queue[bytes | None] = queue.Queue()
                stderr_closed = False

                def _pump_stderr() -> None:
                    stderr = process.stderr
                    if stderr is None:
                        stderr_queue.put(None)
                        return
                    try:
                        while True:
                            line = stderr.readline()
                            if not line:
                                break
                            stderr_queue.put(line)
                    except (OSError, RuntimeError, ValueError) as exc:
                        debug_logger.log_exception("FFmpegDownloader", "stderr_pump", exc)
                    finally:
                        stderr_queue.put(None)

                stderr_thread = threading.Thread(
                    target=_pump_stderr,
                    name="ffmpeg-stderr-pump",
                    daemon=True,
                )
                stderr_thread.start()

                while True:
                    if check_stop_func():
                        process.kill()
                        raise DownloaderStoppedError("用户停止下载")

                    try:
                        line = stderr_queue.get(timeout=self.STDERR_POLL_INTERVAL_SEC)
                    except queue.Empty:
                        line = b""
                    if line is None:
                        stderr_closed = True
                        line = b""
                    if not line:
                        if time.time() - last_progress_time > self.PROGRESS_TIMEOUT_SEC:
                            process.kill()
                            break
                        if process.poll() is not None and stderr_closed:
                            break
                        continue

                    last_progress_time = time.time()
                    line_str = line.decode("utf-8", errors="ignore").strip()
                    if line_str:
                        stderr_tail.append(line_str)
                    expected_duration, _observed_size_bytes, parsed_progress = self._parse_progress_line(
                        line_str,
                        expected_duration=expected_duration,
                        expected_size_bytes=expected_size_bytes,
                    )
                    if parsed_progress is not None and parsed_progress > last_progress:
                        last_progress = parsed_progress
                        self._emit_progress(progress_callback, parsed_progress)

                process.wait()
                if process.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    attempt_completed = True
                    self._emit_progress(progress_callback, 100)
                    debug_logger.log(
                        component="FFmpegDownloader",
                        action="download_finished",
                        message="ffmpeg 下载完成",
                        status_code="FFMPEG_OK",
                        details={"save_path": save_path, "source_url": url, "title": video_item.title},
                        trace_id=trace_id,
                    )
                    return
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise ExternalToolError(f"ffmpeg 下载失败 (Code: {process.returncode})")
            except DownloaderStoppedError:
                raise
            except (OSError, RuntimeError, ValueError, ExternalToolError) as exc:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    debug_logger.log_exception(
                        "FFmpegDownloader",
                        "download_error",
                        exc,
                        context={"save_path": save_path, "source_url": url, "title": video_item.title, "stderr_tail": list(stderr_tail)},
                        trace_id=trace_id,
                    )
                    raise ExternalToolError(f"ffmpeg 下载失败: {exc}") from exc
            finally:
                if process is not None:
                    returncode = getattr(process, "returncode", None)
                    if returncode is None:
                        try:
                            returncode = process.poll()
                        except Exception:
                            returncode = None
                    if returncode is None:
                        try:
                            process.kill()
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "kill_process", exc)
                    stderr = getattr(process, "stderr", None)
                    close_stderr = getattr(stderr, "close", None)
                    if callable(close_stderr):
                        try:
                            close_stderr()
                        except (OSError, RuntimeError, ValueError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "close_stderr", exc)
                    if returncode is None:
                        try:
                            process.wait(timeout=2)
                        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                            debug_logger.log_exception("FFmpegDownloader", "wait_process_after_kill", exc)
                if stderr_thread is not None:
                    try:
                        stderr_thread.join(timeout=1)
                    except RuntimeError as exc:
                        debug_logger.log_exception("FFmpegDownloader", "join_stderr_thread", exc)
                if not attempt_completed:
                    try:
                        if os.path.exists(save_path):
                            os.remove(save_path)
                    except OSError:
                        pass
