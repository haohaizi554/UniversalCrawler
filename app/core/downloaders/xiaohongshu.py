"""Downloader for XiaoHongShu media items."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import DEFAULT_USER_AGENT, cfg
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem
from app.utils.filenames import sanitize_filename

from .base import BaseDownloader, ProgressCallback, StopCheck

class XiaohongshuDownloader(BaseDownloader):
    """Handle XHS videos and gallery downloads."""

    source_id = "xiaohongshu"
    GALLERY_IMAGE_WORKER_CAP = 10

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        user_agent = self._resolve_runtime_user_agent(
            video_item,
            source="xiaohongshu",
            configured_user_agent=cfg.get("xiaohongshu", "user_agent", DEFAULT_USER_AGENT),
        )
        headers = {
            "User-Agent": user_agent,
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
        self._download_gallery_parallel(
            video_item=video_item,
            images_data=images_data,
            save_dir=save_dir,
            base_name=base_name,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            headers=headers,
        )

    def _download_gallery_parallel(
        self,
        *,
        video_item: VideoItem,
        images_data: list[dict[str, str]],
        save_dir: str,
        base_name: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
        headers: dict[str, str],
    ) -> None:
        image_jobs = [
            (idx, image)
            for idx, image in enumerate(images_data, start=1)
            if image.get("image_url")
        ]
        total = max(1, len(image_jobs))
        if not image_jobs:
            self._emit_progress(progress_callback, 100)
            return

        completed = 0
        downloaded_by_image: dict[int, int] = {}
        total_by_image: dict[int, int] = {}
        progress_by_image: dict[int, int] = {}
        first_index = total + 1
        progress_lock = threading.RLock()

        def emit_gallery_progress(
            idx: int,
            image_progress: int,
            *,
            image_bytes_downloaded: int | None = None,
            image_bytes_total: int | None = None,
        ) -> None:
            with progress_lock:
                if image_bytes_downloaded is not None:
                    downloaded_by_image[idx] = max(0, int(image_bytes_downloaded or 0))
                if image_bytes_total is not None:
                    total_by_image[idx] = max(0, int(image_bytes_total or 0))
                progress_by_image[idx] = max(0, min(100, int(image_progress or 0)))
                aggregate_downloaded = sum(downloaded_by_image.values())
                aggregate_total = sum(total_by_image.values())
                aggregate_progress = int((completed + sum(progress_by_image.values()) / 100) / total * 100)
            self._emit_progress(
                progress_callback,
                aggregate_progress,
                bytes_downloaded=aggregate_downloaded if aggregate_downloaded > 0 else None,
                bytes_total=aggregate_total if aggregate_total > 0 else None,
            )

        def download_one(idx: int, image: dict[str, str]) -> tuple[int, str]:
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            image_url = image.get("image_url", "")
            ext = ".jpeg"
            lowered = image_url.lower()
            if ".png" in lowered:
                ext = ".png"
            elif ".webp" in lowered:
                ext = ".webp"
            elif ".gif" in lowered:
                ext = ".gif"
            target_path = os.path.join(save_dir, f"{base_name}_{idx}{ext}")

            def image_progress_callback(
                progress: int,
                *,
                bytes_downloaded: int | None = None,
                bytes_total: int | None = None,
            ) -> None:
                emit_gallery_progress(
                    idx,
                    progress,
                    image_bytes_downloaded=bytes_downloaded,
                    image_bytes_total=bytes_total,
                )

            self._download_http_file(
                url=image_url,
                save_path=target_path,
                headers=headers,
                check_stop_func=check_stop_func,
                progress_callback=image_progress_callback,
                max_retries=cfg.get("download", "max_retries", 3),
                timeout=cfg.get("download", "request_timeout", 60),
                chunk_size=cfg.get("download", "chunk_size", 65536),
                error_message=f"小红书图片下载失败: {base_name}_{idx}",
                proxy=video_item.meta.get("proxy"),
            )
            return idx, target_path

        worker_count = self._gallery_image_worker_count(total)
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="xhs-gallery") as executor:
            futures = [executor.submit(download_one, idx, image) for idx, image in image_jobs]
            for future in as_completed(futures):
                idx, target_path = future.result()
                with progress_lock:
                    if idx < first_index:
                        first_index = idx
                        video_item.local_path = target_path
                    progress_by_image.pop(idx, None)
                    completed += 1
                    progress = int(completed / total * 100)
                    aggregate_downloaded = sum(downloaded_by_image.values())
                    aggregate_total = sum(total_by_image.values())
                self._emit_progress(
                    progress_callback,
                    progress,
                    bytes_downloaded=aggregate_downloaded if aggregate_downloaded > 0 else None,
                    bytes_total=aggregate_total if aggregate_total > 0 else None,
                )
        with progress_lock:
            aggregate_downloaded = sum(downloaded_by_image.values())
            aggregate_total = sum(total_by_image.values())
        self._emit_progress(
            progress_callback,
            100,
            bytes_downloaded=aggregate_downloaded if aggregate_downloaded > 0 else None,
            bytes_total=aggregate_total if aggregate_total > 0 else None,
        )

    @classmethod
    def _gallery_image_worker_count(cls, total: int) -> int:
        try:
            configured = int(cfg.get("download", "max_concurrent", 3) or 3)
        except (TypeError, ValueError):
            configured = 3
        configured = max(1, min(configured, cls.GALLERY_IMAGE_WORKER_CAP))
        if bool(cfg.get("download", "image_respects_concurrency", False)):
            target = configured
        else:
            target = cls.GALLERY_IMAGE_WORKER_CAP
        return max(1, min(int(total or 1), cls.GALLERY_IMAGE_WORKER_CAP, target))
