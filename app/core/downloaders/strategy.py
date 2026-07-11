"""Explicit download strategy chain for media transfer decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.config import cfg
from app.debug_logger import debug_logger
from app.exceptions import DownloaderStoppedError, StreamDownloadError
from app.models import VideoItem
from app.models.download_context import DownloadContext

@dataclass(slots=True)
class DownloadRequest:
    """下载策略链共享的请求上下文，避免每个策略重复解析 VideoItem/meta。"""

    video_item: VideoItem
    save_path: str
    headers: dict[str, str]
    progress_callback: Callable[..., None]
    check_stop_func: Callable[[], bool]
    max_retries: int
    timeout: int
    chunk_size: int
    support_resume: bool = False
    error_message: str = "下载失败"

    @property
    def context(self) -> DownloadContext:
        return self.video_item.build_download_context()

    @property
    def explicit_strategy(self) -> str:
        return self.context.explicit_strategy

class StrategyCapableDownloader(Protocol):
    """策略链只依赖 BaseDownloader 的最小接口，便于平台下载器复用。"""

    def _apply_runtime_headers(self, video_item: VideoItem, headers: dict[str, str]) -> None:
        ...

    def _domain_policy_for_item(self, video_item: VideoItem):
        ...

    def _download_http_file(
        self,
        *,
        url: str,
        save_path: str,
        headers: dict[str, str],
        check_stop_func,
        progress_callback=None,
        max_retries: int = 3,
        timeout: int = 60,
        chunk_size: int = 8192,
        support_resume: bool = False,
        error_message: str = "下载失败",
        proxy: str | None = None,
        trace_id: str | None = None,
        domain_policy=None,
    ) -> None:
        ...

class DownloadStrategy(Protocol):
    """单个下载策略；返回 False 表示当前策略不适用或允许后续策略接管。"""

    name: str

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> bool:
        ...

class M3U8DownloadStrategy:
    name = "m3u8"

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> bool:
        from .m3u8 import N_m3u8DL_RE_Downloader

        if request.explicit_strategy != self.name and not N_m3u8DL_RE_Downloader.is_m3u8_url(request.video_item.url):
            return False
        if not N_m3u8DL_RE_Downloader.is_available():
            return False
        N_m3u8DL_RE_Downloader().download(
            request.video_item,
            request.save_path,
            request.progress_callback,
            request.check_stop_func,
        )
        return True

class ChunkedDownloadStrategy:
    name = "chunked"

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> bool:
        from .chunked import ChunkedDownloader

        if request.explicit_strategy != self.name and not ChunkedDownloader.should_use(request.video_item):
            return False
        try:
            ChunkedDownloader().download(
                request.video_item,
                request.save_path,
                request.progress_callback,
                request.check_stop_func,
            )
            return True
        except StreamDownloadError as exc:
            debug_logger.log(
                component=type(downloader).__name__,
                action="chunked_fallback",
                level="WARN",
                message="分块下载不可用，回退到后续下载策略",
                status_code="DL_CHUNKED_FALLBACK",
                details={
                    "title": request.video_item.title,
                    "reason": str(exc),
                    "url": request.video_item.url,
                    "requested_strategy": request.explicit_strategy or "auto",
                },
                trace_id=request.context.trace_id,
            )
            return False

class FFmpegDownloadStrategy:
    name = "ffmpeg"

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> bool:
        from .ffmpeg import FFmpegDownloader

        try:
            if int(cfg.get("download", "speed_limit_kb", 0) or 0) > 0:
                return False
        except (TypeError, ValueError):
            pass
        if request.explicit_strategy != self.name and not FFmpegDownloader.should_use(request.video_item):
            return False
        if not FFmpegDownloader.is_available():
            return False
        FFmpegDownloader().download(
            request.video_item,
            request.save_path,
            request.progress_callback,
            request.check_stop_func,
        )
        return True

class HttpDownloadStrategy:
    name = "http"

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> bool:
        downloader._download_http_file(
            url=request.video_item.url,
            save_path=request.save_path,
            headers=request.headers,
            check_stop_func=request.check_stop_func,
            progress_callback=request.progress_callback,
            max_retries=request.max_retries,
            timeout=request.timeout,
            chunk_size=request.chunk_size,
            support_resume=request.support_resume,
            error_message=request.error_message,
            proxy=request.context.proxy,
            trace_id=request.context.trace_id,
            domain_policy=downloader._domain_policy_for_item(request.video_item),
        )
        return True

class DownloadStrategyChain:
    """按固定顺序尝试下载策略，并支持任务级显式策略优先。"""

    def __init__(self, strategies: list[DownloadStrategy]) -> None:
        self._strategies = list(strategies)

    def execute(self, downloader: StrategyCapableDownloader, request: DownloadRequest) -> None:
        downloader._apply_runtime_headers(request.video_item, request.headers)
        last_error: Exception | None = None
        for strategy in self._ordered_strategies(request.explicit_strategy):
            try:
                if strategy.execute(downloader, request):
                    return
            except DownloaderStoppedError:
                # 用户停止不能被当成策略失败回退，否则会出现“取消后又被下一个策略继续下载”。
                raise
            except Exception as exc:
                last_error = exc
                debug_logger.log(
                    component=type(downloader).__name__,
                    action="strategy_fallback",
                    level="WARN",
                    message="下载策略执行失败，回退到后续策略",
                    status_code="DL_STRATEGY_FALLBACK",
                    details={
                        "strategy": strategy.name,
                        "reason": str(exc),
                        "requested_strategy": request.explicit_strategy or "auto",
                        "url": request.video_item.url,
                    },
                    trace_id=request.context.trace_id,
                )
        if last_error is not None:
            raise StreamDownloadError(f"{request.error_message}: {last_error}") from last_error
        raise StreamDownloadError(request.error_message)

    def _ordered_strategies(self, explicit_strategy: str) -> list[DownloadStrategy]:
        if not explicit_strategy:
            return list(self._strategies)
        # 显式策略只调整优先级，不关闭兜底；外部工具不可用时仍可回退到 HTTP。
        preferred = [strategy for strategy in self._strategies if strategy.name == explicit_strategy]
        if not preferred:
            available = [strategy.name for strategy in self._strategies]
            raise ValueError(f"未知下载策略: '{explicit_strategy}'，可用策略: {available}")
        fallback = [strategy for strategy in self._strategies if strategy.name != explicit_strategy]
        return preferred + fallback

DEFAULT_DOWNLOAD_STRATEGY_CHAIN = DownloadStrategyChain(
    [
        M3U8DownloadStrategy(),
        ChunkedDownloadStrategy(),
        FFmpegDownloadStrategy(),
        HttpDownloadStrategy(),
    ]
)
