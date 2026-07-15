"""MissAV HLS 下载入口，负责代理、请求头和外部工具回退。"""

from __future__ import annotations

from app.debug_logger import debug_logger
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck
from .m3u8 import N_m3u8DL_RE_Downloader

class MissAVDownloader(BaseDownloader):
    """为 MissAV HLS 任务补齐代理与 Referer，并委托外部下载器。"""
    source_id = "missav"

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        trace_id = video_item.meta.get("trace_id")
        video_item.meta.setdefault("referer", video_item.meta.get("referer", "https://missav.ai/"))
        debug_logger.log(
            component="MissAVDownloader",
            action="prepare_download",
            message="准备下载 MissAV HLS 流",
            status_code="MISSAV_DL_PREPARE",
            details=debug_logger.pick_used(
                {
                    "title": video_item.title,
                    "source_url": video_item.url,
                    "save_path": save_path,
                    "referer": video_item.meta.get("referer"),
                    "proxy": video_item.meta.get("proxy"),
                },
                "title",
                "source_url",
                "save_path",
                "referer",
                "proxy",
            ),
            trace_id=trace_id,
        )
        return N_m3u8DL_RE_Downloader().download(video_item, save_path, progress_callback, check_stop_func)
