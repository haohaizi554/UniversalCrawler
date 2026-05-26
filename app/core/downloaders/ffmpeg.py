from __future__ import annotations

import os
import re
import subprocess
import time

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck
from .external import FFmpegExternalTool, build_hidden_startupinfo


class FFmpegDownloader(BaseDownloader):
    SIZE_THRESHOLD_MB = 200
    DURATION_THRESHOLD_SEC = 600

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
        url = video_item.url
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        trace_id = video_item.meta.get("trace_id")
        ffmpeg = FFmpegExternalTool.resolve_executable()
        if not ffmpeg:
            raise ExternalToolNotFoundError("未找到 ffmpeg.exe")
        try:
            resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            real_url = resp.url
            debug_logger.log_api(
                component="FFmpegDownloader",
                api_name="head_redirect",
                request={"url": url},
                response_summary={"real_url": real_url, "content_length": resp.headers.get("content-length")},
                message="ffmpeg 下载前检查真实地址",
                status_code=resp.status_code,
                trace_id=trace_id,
            )
            if real_url != url:
                url = real_url
        except requests.RequestException as exc:
            debug_logger.log_exception(
                "FFmpegDownloader",
                "head_redirect",
                exc,
                context={"url": url},
                trace_id=trace_id,
            )

        cmd = FFmpegExternalTool.build_download_command(ffmpeg, url, save_path, headers)
        debug_logger.log_command(
            component="FFmpegDownloader",
            tool_name="ffmpeg",
            command_args=cmd,
            message="准备调用 ffmpeg 执行下载",
            context={"save_path": save_path, "source_url": url, "title": video_item.title},
            trace_id=trace_id,
        )

        startupinfo = build_hidden_startupinfo()

        progress_callback(5)
        max_retries = cfg.get("download", "max_retries", 3)
        for attempt in range(max_retries):
            try:
                process = subprocess.Popen(
                    cmd,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                )
                duration_match: int | None = None
                last_progress_time = time.time()

                while True:
                    if check_stop_func():
                        process.kill()
                        raise DownloaderStoppedError("用户停止下载")

                    line = process.stderr.readline() if process.stderr else b""
                    if not line:
                        if time.time() - last_progress_time > 30:
                            process.kill()
                            break
                        if process.poll() is not None:
                            break
                        continue

                    last_progress_time = time.time()
                    line_str = line.decode("utf-8", errors="ignore").strip()
                    if duration_match is None:
                        duration_info = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", line_str)
                        if duration_info:
                            duration_match = (
                                int(duration_info.group(1)) * 3600
                                + int(duration_info.group(2)) * 60
                                + int(duration_info.group(3))
                            )
                    if duration_match and duration_match > 0:
                        current_time = re.search(r"time=(\d{2}):(\d{2}):(\d{2})", line_str)
                        if current_time:
                            current = (
                                int(current_time.group(1)) * 3600
                                + int(current_time.group(2)) * 60
                                + int(current_time.group(3))
                            )
                            progress_callback(min(99, int(current / duration_match * 100)))

                process.wait()
                if process.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    progress_callback(100)
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
                        context={"save_path": save_path, "source_url": url, "title": video_item.title},
                        trace_id=trace_id,
                    )
                    raise ExternalToolError(f"ffmpeg 下载失败: {exc}") from exc
