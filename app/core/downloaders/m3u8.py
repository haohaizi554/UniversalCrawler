"""下载器模块，负责 `app/core/downloaders/m3u8.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import os
import subprocess

from app.config import DEFAULT_USER_AGENT
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, ExternalToolError, ExternalToolNotFoundError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck
from .external import ExternalToolRunner, NM3U8DLREExternalTool, build_new_console_flags

#基于external.py实现
class N_m3u8DL_RE_Downloader(BaseDownloader):
    """调用 `N_m3u8DL-RE` 完成 HLS 资源下载与状态回传。"""

    @classmethod
    def is_available(cls) -> bool:
        """执行 `is_available` 对应的业务逻辑，供 `N_m3u8DL_RE_Downloader` 使用。"""
        return NM3U8DLREExternalTool.is_available()

    @classmethod
    def is_m3u8_url(cls, url: str) -> bool:
        """执行 `is_m3u8_url` 对应的业务逻辑，供 `N_m3u8DL_RE_Downloader` 使用。"""
        return NM3U8DLREExternalTool.is_m3u8_url(url)

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        """执行 `download` 对应的业务逻辑，供 `N_m3u8DL_RE_Downloader` 使用。"""
        executable = NM3U8DLREExternalTool.resolve_executable()
        if not executable:
            raise ExternalToolNotFoundError(f"未找到 {NM3U8DLREExternalTool.EXE_PATH}")

        url = video_item.url
        trace_id = video_item.meta.get("trace_id")
        ua = video_item.meta.get("ua", DEFAULT_USER_AGENT)
        referer = video_item.meta.get("referer", "https://www.douyin.com/")

        cmd = NM3U8DLREExternalTool.build_download_command(executable, url, save_path, ua, referer)
        debug_logger.log_command(
            component="N_m3u8DL_RE_Downloader",
            tool_name="N_m3u8DL-RE",
            command_args=cmd,
            message="准备调用 N_m3u8DL-RE 下载 HLS 流",
            context={"title": video_item.title, "save_path": save_path, "source_url": url},
            trace_id=trace_id,
        )

        creation_flags = build_new_console_flags()
        progress_callback(10)
        try:
            process = subprocess.Popen(cmd, creationflags=creation_flags)
            ExternalToolRunner.wait_process(process, check_stop_func, progress_callback, 50)

            if process.returncode != 0:
                raise ExternalToolError(f"N_m3u8DL-RE 异常退出 (Code: {process.returncode})")

            progress_callback(100)
            debug_logger.log(
                component="N_m3u8DL_RE_Downloader",
                action="download_finished",
                message="N_m3u8DL-RE 下载完成",
                status_code="M3U8_OK",
                details={"title": video_item.title, "save_path": save_path},
                trace_id=trace_id,
            )
        except DownloaderStoppedError:
            raise
        except (OSError, RuntimeError, ValueError, ExternalToolError) as exc:
            debug_logger.log_exception(
                "N_m3u8DL_RE_Downloader",
                "download_error",
                exc,
                context={"title": video_item.title, "save_path": save_path, "source_url": url},
                trace_id=trace_id,
            )
            raise ExternalToolError(f"N_m3u8DL-RE 下载失败: {exc}") from exc
