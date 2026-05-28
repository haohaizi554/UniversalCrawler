"""下载器模块，负责 `app/core/downloaders/bilibili.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import os
import subprocess
import threading

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import (
    DownloaderStoppedError,
    ExternalToolError,
    ExternalToolNotFoundError,
    MergeError,
    StreamDownloadError,
)
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck
from .external import FFmpegExternalTool, build_hidden_startupinfo


class BilibiliDownloader(BaseDownloader):
    """实现 `BilibiliDownloader` 对应的资源下载与落盘流程。"""
    source_id = "bilibili"

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        """执行 `download` 对应的业务逻辑，供 `BilibiliDownloader` 使用。"""
        trace_id = video_item.meta.get("trace_id")
        ffmpeg_path = FFmpegExternalTool.resolve_executable()
        if not ffmpeg_path:
            raise ExternalToolNotFoundError("未找到 ffmpeg.exe，无法合并音视频")

        video_url = video_item.url
        audio_url = video_item.meta.get("audio_url")
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("bilibili", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.bilibili.com"),
        }
        save_dir = os.path.dirname(save_path)
        base_name = os.path.splitext(os.path.basename(save_path))[0]
        temp_v = os.path.join(save_dir, f"{base_name}_video.m4s")
        temp_a = os.path.join(save_dir, f"{base_name}_audio.m4s")
        chunk_size = max(cfg.get("download", "chunk_size", 65536), 256 * 1024)
        debug_logger.log(
            component="BilibiliDownloader",
            action="prepare_download",
            message="准备下载 Bilibili 音视频流",
            status_code="BILI_DL_PREPARE",
            details=debug_logger.pick_used(
                {
                    "title": video_item.title,
                    "video_url": video_url,
                    "audio_url": audio_url,
                    "save_path": save_path,
                    "chunk_size": chunk_size,
                    "bvid": video_item.meta.get("bvid"),
                    "cid": video_item.meta.get("cid"),
                },
                "title",
                "video_url",
                "audio_url",
                "save_path",
                "chunk_size",
                "bvid",
                "cid",
            ),
            trace_id=trace_id,
        )

        def cleanup_temp_files() -> None:
            """执行 `cleanup_temp_files` 对应的业务逻辑。"""
            for temp_path in (temp_v, temp_a):
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        stream_stats = {
            "video": {"downloaded": 0, "total": 0},
            "audio": {"downloaded": 0, "total": 0},
        }
        progress_lock = threading.Lock()
        last_progress = [9]
        stop_event = threading.Event()
        error_holder: list[Exception] = []

        def emit_combined_progress() -> None:
            """执行 `emit_combined_progress` 对应的业务逻辑。"""
            total = sum(item["total"] for item in stream_stats.values() if item["total"] > 0)
            downloaded = sum(item["downloaded"] for item in stream_stats.values())
            if total <= 0:
                return
            percent = 10 + int((downloaded / total) * 80)
            percent = min(90, max(10, percent))
            if percent > last_progress[0]:
                last_progress[0] = percent
                progress_callback(percent)

        def download_stream(name: str, url: str | None, path: str) -> None:
            """执行 `download_stream` 对应的业务逻辑。"""
            if not url:
                return
            try:
                with requests.get(url, headers=headers, stream=True, timeout=(15, 120)) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    debug_logger.log_api(
                        component="BilibiliDownloader",
                        api_name=f"stream_{name}",
                        request={"url": url, "save_path": path},
                        response_summary={"content_length": total, "content_type": response.headers.get("content-type")},
                        message="Bilibili 流请求建立成功",
                        status_code=response.status_code,
                        trace_id=trace_id,
                    )
                    with progress_lock:
                        stream_stats[name]["total"] = total
                        emit_combined_progress()
                    with open(path, "wb") as fp:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if stop_event.is_set():
                                return
                            if check_stop_func():
                                stop_event.set()
                                raise DownloaderStoppedError("用户停止下载")
                            if chunk:
                                fp.write(chunk)
                                with progress_lock:
                                    stream_stats[name]["downloaded"] += len(chunk)
                                    emit_combined_progress()
            except (requests.RequestException, OSError, ValueError, RuntimeError, StreamDownloadError) as exc:
                stop_event.set()
                error_holder.append(exc)
                if os.path.exists(path):
                    os.remove(path)

        progress_callback(10)
        try:
            threads = [threading.Thread(target=download_stream, args=("video", video_url, temp_v), daemon=True)]
            if audio_url:
                threads.append(threading.Thread(target=download_stream, args=("audio", audio_url, temp_a), daemon=True))

            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if error_holder:
                first_error = error_holder[0]
                if isinstance(first_error, DownloaderStoppedError):
                    raise first_error
                raise StreamDownloadError(f"B站流下载失败: {first_error}") from first_error
            if stop_event.is_set() and check_stop_func():
                raise DownloaderStoppedError("用户停止下载")

            progress_callback(90)
            cmd_merge = FFmpegExternalTool.build_merge_command(ffmpeg_path, temp_v, temp_a if audio_url else None, save_path)
            debug_logger.log_command(
                component="BilibiliDownloader",
                tool_name="ffmpeg",
                command_args=cmd_merge,
                message="准备合并 Bilibili 音视频流",
                context={"title": video_item.title, "save_path": save_path},
                trace_id=trace_id,
            )
            startupinfo = build_hidden_startupinfo()
            subprocess.run(
                cmd_merge,
                check=True,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cleanup_temp_files()
            progress_callback(100)
            debug_logger.log(
                component="BilibiliDownloader",
                action="merge_finished",
                message="Bilibili 音视频合并完成",
                status_code="BILI_MERGE_OK",
                details={"title": video_item.title, "save_path": save_path},
                trace_id=trace_id,
            )
        except DownloaderStoppedError:
            cleanup_temp_files()
            raise
        except subprocess.CalledProcessError as exc:
            cleanup_temp_files()
            debug_logger.log_exception(
                "BilibiliDownloader",
                "merge_error",
                exc,
                context={"title": video_item.title, "save_path": save_path},
                trace_id=trace_id,
            )
            raise MergeError(f"B站音视频合并失败: {exc}") from exc
        except (requests.RequestException, OSError, ValueError, RuntimeError, ExternalToolError, StreamDownloadError) as exc:
            cleanup_temp_files()
            debug_logger.log_exception(
                "BilibiliDownloader",
                "download_error",
                exc,
                context={"title": video_item.title, "save_path": save_path},
                trace_id=trace_id,
            )
            if isinstance(exc, MergeError):
                raise
            raise StreamDownloadError(f"B站下载失败: {exc}") from exc
