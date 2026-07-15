"""下载器公共基类：统一校验、重试、断点续传与原子发布。"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Callable, cast

import requests

from app.config import DEFAULT_USER_AGENT, cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, StreamDownloadError
from app.models import VideoItem
from app.utils.user_agents import resolve_user_agent
from shared.runtime_options import (
    PUBLIC_DOMAIN_POLICY,
    DomainPolicyEngine,
    DomainPolicyViolation,
)
from shared.network_proxy import requests_proxy_mapping

ProgressCallback = Callable[..., None]
StopCheck = Callable[[], bool]


class TransferRateLimiter:
    """按所有调用线程的累计字节数限制单个下载任务的平均传输速度。"""

    def __init__(self, speed_limit_kb: object) -> None:
        try:
            normalized = max(0, int(cast(Any, speed_limit_kb or 0)))
        except (TypeError, ValueError):
            normalized = 0
        self.bytes_per_second = normalized * 1024
        self._started_at = time.monotonic()
        self._scheduled_bytes = 0
        self._lock = threading.Lock()

    def throttle(self, byte_count: int, check_stop_func: StopCheck | None = None) -> None:
        """等待到累计字节对应的时间点；共享实例可限制多分片的合计速度。"""
        if self.bytes_per_second <= 0 or byte_count <= 0:
            return
        with self._lock:
            self._scheduled_bytes += int(byte_count)
            deadline = self._started_at + (self._scheduled_bytes / self.bytes_per_second)

        while True:
            if check_stop_func is not None and check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))


class BaseDownloader:
    """为平台下载器提供公共校验、进度回调、重试与原子落盘能力。"""

    source_id: str | None = None

    @staticmethod
    def _domain_policy_for_item(video_item: VideoItem) -> DomainPolicyEngine | None:
        meta = video_item.meta if isinstance(getattr(video_item, "meta", None), dict) else {}
        return PUBLIC_DOMAIN_POLICY if meta.get("_network_policy") == "public" else None

    @staticmethod
    def _domain_policy_request_kwargs(
        domain_policy: DomainPolicyEngine | None,
        url: str,
    ) -> dict[str, object]:
        if domain_policy is None:
            return {}
        domain_policy.require_public_url(url)
        return {"hooks": {"response": domain_policy.validate_redirect_response}}

    @classmethod
    def can_handle(cls, video_item: VideoItem) -> bool:
        """仅接收来源与当前下载器 `source_id` 匹配的任务。"""
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

    def _should_resume_download(self, temp_path: str) -> bool:
        """仅在临时文件仍存在时尝试断点续传。"""
        return os.path.exists(temp_path)

    def _get_existing_size(self, temp_path: str) -> int:
        """读取续传偏移；文件在检查后消失时按零字节重新下载。"""
        try:
            return os.path.getsize(temp_path)
        except OSError:
            return 0

    def _cleanup_temp_file(self, temp_path: str) -> None:
        """尽力清理失败下载的临时文件，不覆盖原始异常。"""
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _finalize_download(self, temp_path: str, save_path: str) -> None:
        """下载完整后原子替换目标文件，失败时保留旧文件。"""
        os.replace(temp_path, save_path)

    @staticmethod
    def _coerce_retry_count(value: object, default: int = 3) -> int:
        try:
            retry_count = int(cast(Any, value))
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
        domain_policy: DomainPolicyEngine | None = None,
    ) -> None:
        """按配置执行普通 HTTP 下载，支持基于 `.downloading` 临时文件的续传重试。"""
        # 只在最后 rename 到 save_path，避免失败或中断时把半成品暴露成可播放文件。
        temp_path = save_path + ".downloading"
        success = False
        proxies = requests_proxy_mapping(proxy)
        retry_count = self._coerce_retry_count(max_retries)
        rate_limiter = TransferRateLimiter(cfg.get("download", "speed_limit_kb", 0))

        # retry_count 表示失败后的重试次数，因此总尝试次数是 retry_count + 1。
        for attempt in range(retry_count + 1):
            if check_stop_func():
                raise DownloaderStoppedError("用户停止下载")
            existing_size = 0
            downloaded = 0
            discard_partial_on_error = False
            try:
                request_kwargs = self._domain_policy_request_kwargs(domain_policy, url)
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

                with requests.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=timeout,
                    proxies=proxies,
                    **request_kwargs,
                ) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    if response.status_code == 206:
                        content_range = response.headers.get("content-range") or response.headers.get("Content-Range")
                        parsed_range = self._parse_content_range_header(content_range)
                        if parsed_range is None or parsed_range[0] != existing_size:
                            discard_partial_on_error = True
                            raise StreamDownloadError(
                                f"断点续传响应范围不匹配: expected {existing_size}, got {content_range!r}"
                            )
                        total_size = parsed_range[2] or (total_size + existing_size)
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
                                # iter_content 下一轮读取前等待，才能对网络读取形成背压；
                                # 只限制本任务，不会让一个慢任务阻塞其他下载 worker。
                                rate_limiter.throttle(len(chunk), check_stop_func)
                                downloaded += len(chunk)
                                if progress_callback and total_size > 0:
                                    self._emit_progress(progress_callback, int(downloaded / total_size * 100), bytes_downloaded=downloaded, bytes_total=total_size)
                    if total_size > 0 and downloaded < total_size:
                        raise StreamDownloadError(
                            f"HTTP response ended early: received {downloaded} of {total_size} bytes"
                        )
                success = True
                break
            except DownloaderStoppedError:
                # 用户主动停止语义是“放弃本次未完成文件”，不同于网络失败后的可续传缓存。
                self._cleanup_temp_file(temp_path)
                raise
            except DomainPolicyViolation as exc:
                self._cleanup_temp_file(temp_path)
                raise StreamDownloadError(f"下载地址违反公网访问策略: {exc}") from exc
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
            except StreamDownloadError as exc:
                if discard_partial_on_error or not support_resume or attempt == retry_count:
                    self._cleanup_temp_file(temp_path)
                if attempt == retry_count:
                    raise
                debug_logger.log(
                    component=self.__class__.__name__,
                    action="http_retry",
                    level="WARN",
                    message=f"HTTP 下载内容不完整，准备重试 ({attempt + 1}/{retry_count})",
                    status_code="DL_HTTP_RETRY",
                    details={
                        "url": url,
                        "save_path": save_path,
                        "attempt": attempt + 1,
                        "max_retries": retry_count,
                        "resume_enabled": support_resume,
                        "resume_offset": 0 if discard_partial_on_error else downloaded,
                        "error": str(exc),
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
    @staticmethod
    def _parse_content_range_header(value: object) -> tuple[int, int, int | None] | None:
        match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip(), re.IGNORECASE)
        if match is None:
            return None
        start = int(match.group(1))
        end = int(match.group(2))
        total = None if match.group(3) == "*" else int(match.group(3))
        if end < start or (total is not None and end >= total):
            return None
        return start, end, total
