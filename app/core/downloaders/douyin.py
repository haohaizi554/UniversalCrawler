"""抖音视频、图集与实况资源下载流程。"""

from __future__ import annotations

import os

import requests  # noqa: F401 - 保留供外部补丁和兼容测试替换。

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem

from .base import BaseDownloader, ProgressCallback, StopCheck


class DouyinDownloader(BaseDownloader):
    """抖音下载器。"""
    source_id = "douyin"
    DOUYIN_VIEWPORT_COOKIES = ("dy_swidth=1536", "dy_sheight=864")

    @classmethod
    def _ensure_viewport_cookies(cls, headers: dict[str, str]) -> None:
        cookie_header = (headers.get("Cookie") or "").strip()
        cookie_parts = [part.strip() for part in cookie_header.split(";") if part.strip()]
        cookie_names = {part.split("=", 1)[0].strip() for part in cookie_parts}

        for cookie in cls.DOUYIN_VIEWPORT_COOKIES:
            name = cookie.split("=", 1)[0]
            if name not in cookie_names:
                cookie_parts.append(cookie)
                cookie_names.add(name)

        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

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
            source="douyin",
            configured_user_agent=cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT),
        )
        headers = {
            "User-Agent": user_agent,
            "Referer": video_item.meta.get("referer", "https://www.douyin.com/"),
        }
        # 与快手下载器对齐：支持 CLI/SDK 传入的 cookie（字符串）和 GUI spider 传入的 cookies（字典）
        cookie_dict = video_item.meta.get("cookies")
        if isinstance(cookie_dict, dict):
            headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        elif isinstance(video_item.meta.get("cookie"), str):
            headers["Cookie"] = video_item.meta["cookie"]
        self._ensure_viewport_cookies(headers)
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
            download_cfg.resume_enabled,
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
        support_resume: bool,
    ) -> None:
        """沿统一策略链下载单个视频，并保留 HTTP 续传能力。"""
        self._download_with_strategy_fallback(
            video_item=video_item,
            save_path=save_path,
            headers=headers,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            max_retries=max_retries,
            timeout=request_timeout,
            chunk_size=chunk_size,
            support_resume=self._coerce_bool_setting(support_resume),
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
        """顺序落盘图集/实况条目，并把单文件进度汇总为任务进度。"""
        save_dir = os.path.dirname(save_path)
        total_files = len(images_data)
        completed = 0
        domain_policy = self._domain_policy_for_item(video_item)
        downloaded_by_file: dict[int, int] = {}
        total_by_file: dict[int, int] = {}
        progress_by_file: dict[int, int] = {}

        def emit_gallery_progress(
            seq: int,
            file_progress: int,
            *,
            file_bytes_downloaded: int | None = None,
            file_bytes_total: int | None = None,
        ) -> None:
            if file_bytes_downloaded is not None:
                downloaded_by_file[seq] = max(0, int(file_bytes_downloaded or 0))
            if file_bytes_total is not None:
                total_by_file[seq] = max(0, int(file_bytes_total or 0))
            progress_by_file[seq] = max(0, min(100, int(file_progress or 0)))
            aggregate_downloaded = sum(downloaded_by_file.values())
            aggregate_total = sum(total_by_file.values())
            aggregate_progress = int((completed + sum(progress_by_file.values()) / 100) / total_files * 100)
            self._emit_progress(
                progress_callback,
                aggregate_progress,
                bytes_downloaded=aggregate_downloaded if aggregate_downloaded > 0 else None,
                bytes_total=aggregate_total if aggregate_total > 0 else None,
            )

        for idx, image_info in enumerate(images_data):
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            img_url = image_info.get("image_url", "")
            live_url = image_info.get("live_video_url", "")
            seq = idx + 1

            def file_progress_callback(
                progress: int,
                *,
                bytes_downloaded: int | None = None,
                bytes_total: int | None = None,
                _seq: int = seq,
            ) -> None:
                emit_gallery_progress(
                    _seq,
                    progress,
                    file_bytes_downloaded=bytes_downloaded,
                    file_bytes_total=bytes_total,
                )

            if live_url:
                self._download_file(
                    live_url,
                    os.path.join(save_dir, f"{video_item.title}_{seq}.mp4"),
                    headers,
                    check_stop_func,
                    progress_callback=file_progress_callback,
                    domain_policy=domain_policy,
                )
                progress_by_file.pop(seq, None)
                completed += 1
                self._emit_progress(
                    progress_callback,
                    int(completed / total_files * 100),
                    bytes_downloaded=sum(downloaded_by_file.values()) or None,
                    bytes_total=sum(total_by_file.values()) or None,
                )
            elif img_url:
                img_ext = ".jpeg"
                lowered = img_url.lower()
                if ".png" in lowered:
                    img_ext = ".png"
                elif ".webp" in lowered:
                    img_ext = ".webp"
                self._download_file(
                    img_url,
                    os.path.join(save_dir, f"{video_item.title}_{seq}{img_ext}"),
                    headers,
                    check_stop_func,
                    progress_callback=file_progress_callback,
                    domain_policy=domain_policy,
                )
                progress_by_file.pop(seq, None)
                completed += 1
                self._emit_progress(
                    progress_callback,
                    int(completed / total_files * 100),
                    bytes_downloaded=sum(downloaded_by_file.values()) or None,
                    bytes_total=sum(total_by_file.values()) or None,
                )

        self._emit_progress(
            progress_callback,
            100,
            bytes_downloaded=sum(downloaded_by_file.values()) or None,
            bytes_total=sum(total_by_file.values()) or None,
        )

    def _download_file(
        self,
        url: str,
        save_path: str,
        headers: dict[str, str],
        check_stop_func: StopCheck,
        progress_callback: ProgressCallback | None = None,
        domain_policy=None,
    ) -> None:
        """按平台安全策略下载图集中的单个文件。"""
        self._download_http_file(
            url=url,
            save_path=save_path,
            headers=headers,
            check_stop_func=check_stop_func,
            progress_callback=progress_callback,
            max_retries=cfg.get("download", "max_retries", 3),
            timeout=cfg.get("download", "request_timeout", 60),
            chunk_size=8192,
            support_resume=self._coerce_bool_setting(cfg.get("download", "resume_enabled", True)),
            error_message=f"文件下载失败: {os.path.basename(save_path)}",
            domain_policy=domain_policy,
        )
