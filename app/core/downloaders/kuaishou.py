"""下载器模块，负责 `app/core/downloaders/kuaishou.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck

class KuaishouDownloader(BaseDownloader):
    """实现 `KuaishouDownloader` 对应的资源下载与落盘流程。"""
    source_id = "kuaishou"

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        trace_id = video_item.meta.get("trace_id")
        download_cfg = cfg.settings.download
        user_agent = self._resolve_runtime_user_agent(
            video_item,
            source="kuaishou",
            configured_user_agent=cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
        )
        headers = {
            "User-Agent": user_agent,
            "Referer": video_item.meta.get("referer", "https://www.kuaishou.com/"),
        }
        cookie_dict = video_item.meta.get("cookies")
        if isinstance(cookie_dict, dict):
            headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        elif isinstance(video_item.meta.get("cookie"), str):
            # CLI/SDK 传入的 cookie 是字符串格式（GUI spider 传入的是 dict 格式的 cookies）
            headers["Cookie"] = video_item.meta["cookie"]

        debug_logger.log(
            component="KuaishouDownloader",
            action="prepare_download",
            message="准备下载快手视频流",
            status_code="KUAISHOU_DL_PREPARE",
            details=debug_logger.pick_used(
                {
                    "title": video_item.title,
                    "source_url": video_item.url,
                    "save_path": save_path,
                    "download_strategy": video_item.meta.get("download_strategy"),
                    "referer": headers.get("Referer"),
                },
                "title",
                "source_url",
                "save_path",
                "download_strategy",
                "referer",
            ),
            trace_id=trace_id,
        )

        self._download_with_strategy_fallback(
            video_item=video_item,
            save_path=save_path,
            headers=headers,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            max_retries=download_cfg.max_retries,
            timeout=download_cfg.request_timeout,
            chunk_size=download_cfg.chunk_size,
            support_resume=self._coerce_bool_setting(download_cfg.resume_enabled),
            error_message="下载失败",
        )
        debug_logger.log(
            component="KuaishouDownloader",
            action="download_finished",
            message="快手视频下载完成",
            status_code="KUAISHOU_DL_OK",
            details=debug_logger.pick_used({"title": video_item.title, "save_path": save_path}, "title", "save_path"),
            trace_id=trace_id,
        )
