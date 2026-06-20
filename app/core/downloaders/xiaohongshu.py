"""Downloader for XiaoHongShu media items."""

from __future__ import annotations

import os

from app.config import DEFAULT_USER_AGENT, cfg
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem
from app.utils.filenames import sanitize_filename

from .base import BaseDownloader, ProgressCallback, StopCheck

class XiaohongshuDownloader(BaseDownloader):
    """Handle XHS videos and gallery downloads."""

    source_id = "xiaohongshu"

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("xiaohongshu", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.xiaohongshu.com/"),
        }
        cookie = video_item.meta.get("cookie")
        if isinstance(cookie, str) and cookie:
            headers["Cookie"] = cookie

        if video_item.meta.get("is_gallery") and video_item.meta.get("images_data"):
            self._download_gallery(
                video_item,
                list(video_item.meta.get("images_data") or []),
                save_path,
                progress_callback,
                check_stop_func,
                headers,
            )
            return

        self._download_with_strategy_fallback(
            video_item=video_item,
            save_path=save_path,
            headers=headers,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            max_retries=cfg.get("download", "max_retries", 3),
            timeout=cfg.get("download", "request_timeout", 60),
            chunk_size=cfg.get("download", "chunk_size", 65536),
            support_resume=True,
            error_message="小红书视频下载失败",
        )

    def _download_gallery(
        self,
        video_item: VideoItem,
        images_data: list[dict[str, str]],
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
        headers: dict[str, str],
    ) -> None:
        save_dir = os.path.dirname(save_path)
        base_name = sanitize_filename(os.path.splitext(os.path.basename(save_path))[0])
        total = max(1, len(images_data))
        completed = 0
        for idx, image in enumerate(images_data, start=1):
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            image_url = image.get("image_url", "")
            if not image_url:
                continue
            ext = ".jpeg"
            lowered = image_url.lower()
            if ".png" in lowered:
                ext = ".png"
            elif ".webp" in lowered:
                ext = ".webp"
            elif ".gif" in lowered:
                ext = ".gif"
            target_path = os.path.join(save_dir, f"{base_name}_{idx}{ext}")
            self._download_http_file(
                url=image_url,
                save_path=target_path,
                headers=headers,
                check_stop_func=check_stop_func,
                max_retries=cfg.get("download", "max_retries", 3),
                timeout=cfg.get("download", "request_timeout", 60),
                chunk_size=cfg.get("download", "chunk_size", 65536),
                error_message=f"小红书图片下载失败: {base_name}_{idx}",
                proxy=video_item.meta.get("proxy"),
            )
            if completed == 0:
                video_item.local_path = target_path
            completed += 1
            progress_callback(int(completed / total * 100))
        progress_callback(100)
