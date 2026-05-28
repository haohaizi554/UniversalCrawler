from __future__ import annotations

import os

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck


class DouyinDownloader(BaseDownloader):
    """抖音下载器。"""
    source_id = "douyin"

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        trace_id = video_item.meta.get("trace_id")
        download_cfg = cfg.settings.download
        headers = {
            "User-Agent": video_item.meta.get("ua", cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT)),
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        debug_logger.log(
            component="DouyinDownloader",
            action="prepare_download",
            message="准备下载抖音资源",
            status_code="DOUYIN_DL_PREPARE",
            details=debug_logger.pick_used(
                {
                    "title": video_item.title,
                    "source_url": video_item.url,
                    "save_path": save_path,
                    "content_type": video_item.meta.get("content_type"),
                    "is_gallery": video_item.meta.get("is_gallery", False),
                    "aweme_id": video_item.meta.get("aweme_id"),
                },
                "title",
                "source_url",
                "save_path",
                "content_type",
                "is_gallery",
                "aweme_id",
            ),
            trace_id=trace_id,
        )

        is_gallery = video_item.meta.get("is_gallery", False)
        images_data = video_item.meta.get("images_data", [])
        if is_gallery and images_data:
            return self._download_gallery(video_item, images_data, save_path, progress_callback, check_stop_func, headers)

        self._download_single(
            video_item,
            save_path,
            progress_callback,
            check_stop_func,
            headers,
            download_cfg.max_retries,
            download_cfg.request_timeout,
            download_cfg.chunk_size,
        )

    def _download_single(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
        headers: dict[str, str],
        max_retries: int,
        request_timeout: int,
        chunk_size: int,
    ) -> None:
        self._download_with_strategy_fallback(
            video_item=video_item,
            save_path=save_path,
            headers=headers,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            max_retries=max_retries,
            timeout=request_timeout,
            chunk_size=chunk_size,
            support_resume=True,
            error_message="下载失败，请检查网络或链接是否失效",
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
        total_files = len(images_data)
        completed = 0

        for idx, image_info in enumerate(images_data):
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            img_url = image_info.get("image_url", "")
            live_url = image_info.get("live_video_url", "")
            seq = idx + 1

            if live_url:
                self._download_file(live_url, os.path.join(save_dir, f"{video_item.title}_{seq}.mp4"), headers, check_stop_func)
                completed += 1
                progress_callback(int(completed / total_files * 100))
            elif img_url:
                img_ext = ".jpeg"
                lowered = img_url.lower()
                if ".png" in lowered:
                    img_ext = ".png"
                elif ".webp" in lowered:
                    img_ext = ".webp"
                self._download_file(img_url, os.path.join(save_dir, f"{video_item.title}_{seq}{img_ext}"), headers, check_stop_func)
                completed += 1
                progress_callback(int(completed / total_files * 100))

        progress_callback(100)

    def _download_file(
        self,
        url: str,
        save_path: str,
        headers: dict[str, str],
        check_stop_func: StopCheck,
    ) -> None:
        self._download_http_file(
            url=url,
            save_path=save_path,
            headers=headers,
            check_stop_func=check_stop_func,
            max_retries=cfg.get("download", "max_retries", 3),
            timeout=cfg.get("download", "request_timeout", 60),
            chunk_size=8192,
            error_message=f"文件下载失败: {os.path.basename(save_path)}",
        )
