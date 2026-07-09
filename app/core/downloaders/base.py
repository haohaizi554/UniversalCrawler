"""下载器模块，负责 `app/core/downloaders/base.py` 对应资源的落盘或外部工具调用流程。"""

from __future__ import annotations

import os
import time
from typing import Callable

import requests

from app.config import DEFAULT_USER_AGENT
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, StreamDownloadError
from app.models import VideoItem
from app.utils.user_agents import resolve_user_agent

ProgressCallback = Callable[..., None]
StopCheck = Callable[[], bool]

class BaseDownloader:
    """实现 `BaseDownloader` 对应的资源下载与落盘流程。"""

    source_id: str | None = None

    @classmethod
    def can_handle(cls, video_item: VideoItem) -> bool:
        """判断当前对象是否满足 `can_handle` 所需的处理条件，供 `BaseDownloader` 使用。"""
        return bool(cls.source_id and video_item.source == cls.source_id)

    @staticmethod
    def _emit_progress(
        progress_callback: ProgressCallback | None,
        progress: int,
        *,
        bytes_downloaded: int | None = None,
        bytes_total: int | None = None,
        phase: str | None = None,
        phase_message: str | None = None,
        write_status: str | None = None,
        merge_status: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        kwargs = {
            "bytes_downloaded": bytes_downloaded,
            "bytes_total": bytes_total,
            "phase": phase,
            "phase_message": phase_message,
            "write_status": write_status,
            "merge_status": merge_status,
        }
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        try:
            if not kwargs:
                progress_callback(progress)
                return
            progress_callback(progress, **kwargs)
        except TypeError as exc:
            # 旧调用方只接受百分比；这里降级调用，避免新增 telemetry 字段破坏兼容适配器。
            if not kwargs:
                debug_logger.log_exception(
                    "BaseDownloader",
                    "progress_callback_error",
                    exc,
                    details={"progress": progress},
                )
                return
            try:
                progress_callback(progress)
            except Exception as fallback_exc:
                debug_logger.log_exception(
                    "BaseDownloader",
                    "progress_callback_fallback_error",
                    fallback_exc,
                    details={"progress": progress},
                )
        except Exception as exc:
            debug_logger.log_exception(
                "BaseDownloader",
                "progress_callback_error",
                exc,
                details={"progress": progress},
            )

    def _apply_runtime_headers(self, video_item: VideoItem, headers: dict[str, str]) -> None:
        """让策略下载器复用上层已经确定好的认证头信息。"""
        if headers.get("User-Agent"):
            video_item.meta["ua"] = headers["User-Agent"]
        if headers.get("Referer"):
            video_item.meta["referer"] = headers["Referer"]

    def _resolve_runtime_user_agent(
        self,
        video_item: VideoItem,
        *,
        source: str,
        configured_user_agent: str,
        default_user_agent: str = DEFAULT_USER_AGENT,
    ) -> str:
        user_agent = resolve_user_agent(
            source,
            video_item.meta,
            configured_user_agent=configured_user_agent,
            default_user_agent=default_user_agent,
        )
        if not video_item.meta.get("ua"):
            video_item.meta["ua"] = user_agent
        return user_agent

    # 智能下载调度器：把选择策略交给 strategy.py，便于平台下载器复用同一套回退顺序。
    def _download_with_strategy_fallback(
        self,
        *,
        video_item: VideoItem,
        save_path: str,
        headers: dict[str, str],
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
        max_retries: int,
        timeout: int,
        chunk_size: int,
        support_resume: bool = False,
        error_message: str = "下载失败",
    ) -> None:
        """按流类型/体积选择外部工具、分块下载或普通 HTTP 下载。"""
        from .strategy import DEFAULT_DOWNLOAD_STRATEGY_CHAIN, DownloadRequest

        request = DownloadRequest(
            video_item=video_item,
            save_path=save_path,
            headers=headers,
            progress_callback=progress_callback,
            check_stop_func=check_stop_func,
            max_retries=max_retries,
            timeout=timeout,
            chunk_size=chunk_size,
            support_resume=support_resume,
            error_message=error_message,
        )
        DEFAULT_DOWNLOAD_STRATEGY_CHAIN.execute(self, request)
        return

        # 历史内联实现保留在下方作为迁移参照；当前实际路径已经交给策略链管理。
        from .chunked import ChunkedDownloader
        from .ffmpeg import FFmpegDownloader
        from .m3u8 import N_m3u8DL_RE_Downloader

        self._apply_runtime_headers(video_item, headers)

        if N_m3u8DL_RE_Downloader.is_m3u8_url(video_item.url) and N_m3u8DL_RE_Downloader.is_available():
            N_m3u8DL_RE_Downloader().download(video_item, save_path, progress_callback, check_stop_func)
            return

        size_mb = float(video_item.meta.get("size_mb", 0) or 0)
        if size_mb > ChunkedDownloader.SIZE_THRESHOLD_MB:
            try:
                ChunkedDownloader().download(video_item, save_path, progress_callback, check_stop_func)
                return
            except StreamDownloadError as exc:
                debug_logger.log(
                    component=self.__class__.__name__,
                    action="chunked_fallback",
                    level="WARN",
                    message="分块下载不可用，回退到后续下载策略",
                    status_code="DL_CHUNKED_FALLBACK",
                    details={"title": video_item.title, "reason": str(exc), "url": video_item.url},
                    trace_id=video_item.meta.get("trace_id"),
                )

        if FFmpegDownloader.should_use(video_item) and FFmpegDownloader.is_available():
            FFmpegDownloader().download(video_item, save_path, progress_callback, check_stop_func)
            return

        self._download_http_file(
            url=video_item.url,
            save_path=save_path,
            headers=headers,
            check_stop_func=check_stop_func,
            progress_callback=progress_callback,
            max_retries=max_retries,
            timeout=timeout,
            chunk_size=chunk_size,
            support_resume=support_resume,
            error_message=error_message,
            proxy=video_item.meta.get("proxy"),
        )

    def _should_resume_download(self, temp_path: str) -> bool:
        """提供 `_should_resume_download` 对应的内部辅助逻辑，供 `BaseDownloader` 使用。"""
        return os.path.exists(temp_path)

    def _get_existing_size(self, temp_path: str) -> int:
        """提供 `_get_existing_size` 对应的内部辅助逻辑，供 `BaseDownloader` 使用。"""
        try:
            return os.path.getsize(temp_path)
        except OSError:
            return 0

    def _cleanup_temp_file(self, temp_path: str) -> None:
        """提供 `_cleanup_temp_file` 对应的内部辅助逻辑，供 `BaseDownloader` 使用。"""
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _finalize_download(self, temp_path: str, save_path: str) -> None:
        """提供 `_finalize_download` 对应的内部辅助逻辑，供 `BaseDownloader` 使用。"""
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except OSError:
                pass
        os.rename(temp_path, save_path)

    @staticmethod
    def _coerce_retry_count(value: object, default: int = 3) -> int:
        try:
            retry_count = int(value)
        except (TypeError, ValueError):
            retry_count = default
        return max(0, min(retry_count, 10))

    @staticmethod
    def _coerce_bool_setting(value: object, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    # 单线程 HTTP 下载实现，作为所有专用策略不可用时的最终兜底。
    def _download_http_file(
        self,
        *,
        url: str,
        save_path: str,
        headers: dict[str, str],
        check_stop_func: StopCheck,
        progress_callback: ProgressCallback | None = None,
        max_retries: int = 3,
        timeout: int = 60,
        chunk_size: int = 8192,
        support_resume: bool = False,
        error_message: str = "下载失败",
        proxy: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """按配置执行普通 HTTP 下载，支持基于 `.downloading` 临时文件的续传重试。"""
        # 只在最后 rename 到 save_path，避免失败或中断时把半成品暴露成可播放文件。
        temp_path = save_path + ".downloading"
        success = False
        proxies = {"http": proxy, "https": proxy} if proxy else None
        retry_count = self._coerce_retry_count(max_retries)

        # retry_count 表示失败后的重试次数，因此总尝试次数是 retry_count + 1。
        for attempt in range(retry_count + 1):
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            existing_size = 0
            try:
                # 续传依赖上次失败保留下来的临时文件；主动停止会清理它，避免用户取消后误续传。
                existing_size = self._get_existing_size(temp_path) if support_resume and self._should_resume_download(temp_path) else 0
                request_headers = headers.copy()
                if support_resume and existing_size > 0:
                    request_headers["Range"] = f"bytes={existing_size}-"
                    debug_logger.log(
                        component=self.__class__.__name__,
                        action="http_resume",
                        message="HTTP 断点续传请求已建立",
                        status_code="DL_HTTP_RESUME",
                        details={
                            "url": url,
                            "save_path": save_path,
                            "attempt": attempt + 1,
                            "resume_offset": existing_size,
                        },
                        trace_id=trace_id,
                    )

                with requests.get(url, headers=request_headers, stream=True, timeout=timeout, proxies=proxies) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    if support_resume and existing_size > 0 and response.status_code == 206:
                        total_size += existing_size
                    elif support_resume and existing_size > 0 and response.status_code == 200:
                        # 服务端忽略 Range 时必须从头覆盖写入，不能继续 append 已有半截文件。
                        existing_size = 0

                    mode = "ab" if support_resume and existing_size > 0 and response.status_code == 206 else "wb"
                    downloaded = existing_size
                    with open(temp_path, mode) as fp:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if check_stop_func():
                                raise DownloaderStoppedError("用户停止下载")
                            if chunk:
                                fp.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and total_size > 0:
                                    self._emit_progress(progress_callback, int(downloaded / total_size * 100), bytes_downloaded=downloaded, bytes_total=total_size)
                success = True
                break
            except DownloaderStoppedError:
                # 用户主动停止语义是“放弃本次未完成文件”，不同于网络失败后的可续传缓存。
                self._cleanup_temp_file(temp_path)
                raise
            except requests.RequestException:
                if attempt == retry_count:
                    break
                debug_logger.log(
                    component=self.__class__.__name__,
                    action="http_retry",
                    level="WARN",
                    message=f"HTTP 下载失败，准备重试 ({attempt + 1}/{retry_count})",
                    status_code="DL_HTTP_RETRY",
                    details={
                        "url": url,
                        "save_path": save_path,
                        "attempt": attempt + 1,
                        "max_retries": retry_count,
                        "resume_enabled": support_resume,
                        "resume_offset": existing_size,
                    },
                    trace_id=trace_id,
                )
                time.sleep(1 if retry_count <= 3 else 3)
            except OSError as exc:
                self._cleanup_temp_file(temp_path)
                raise StreamDownloadError(f"{error_message}: {exc}") from exc
            except (ValueError, TypeError, RuntimeError) as exc:
                if attempt == retry_count:
                    raise StreamDownloadError(f"{error_message}: {exc}") from exc
                debug_logger.log(
                    component=self.__class__.__name__,
                    action="http_retry",
                    level="WARN",
                    message=f"HTTP 下载异常，准备重试 ({attempt + 1}/{retry_count})",
                    status_code="DL_HTTP_RETRY",
                    details={
                        "url": url,
                        "save_path": save_path,
                        "attempt": attempt + 1,
                        "max_retries": retry_count,
                        "resume_enabled": support_resume,
                        "resume_offset": existing_size,
                        "error": str(exc),
                    },
                    trace_id=trace_id,
                )
                time.sleep(1 if retry_count <= 3 else 3)

        if not success:
            # 网络失败且重试耗尽后清理兜底临时文件，避免失败列表删除时再遗留 `.downloading`。
            self._cleanup_temp_file(temp_path)
            raise StreamDownloadError(error_message)

        self._finalize_download(temp_path, save_path)
        if progress_callback:
            self._emit_progress(progress_callback, 100, bytes_downloaded=total_size or downloaded, bytes_total=total_size or downloaded)

    def download(
        self,
        video_item: VideoItem,
        save_path: str,
        progress_callback: ProgressCallback,
        check_stop_func: StopCheck,
    ) -> None:
        
        raise NotImplementedError
