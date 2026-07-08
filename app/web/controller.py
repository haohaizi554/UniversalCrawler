"""WebController：桥接后台事件到 WebSocket，复用现有 Spider/DownloadManager 逻辑。"""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
import time
from copy import deepcopy
from functools import partial
from typing import Any, Callable

from app.config import cfg
from app.controllers.media_library_mixin import MediaLibraryMixin, MediaRenameOutcome
from app.controllers.session_mixin import ControllerSessionMixin
from app.core.download_manager import DownloadManager
from app.core.media_filter import should_skip_for_video_only
from app.core.plugin_registry import registry
from app.debug_logger import debug_logger
from app.exceptions import ConfigValidationError, FileOperationError, MediaScanError
from app.models import VideoItem
from app.services.file_service import MediaLibraryService
from app.services.frontend_event_aggregator import FrontendEventPriority, priority_for_topic, sections_for_topic
from app.services.frontend_state_service import FrontendStateService
from app.services.icon_registry import icon_manifest
from app.web.controller_config_service import ConfigWriteError, WebControllerConfigService

DELTA_ONLY_LEGACY_TOPICS = frozenset(
    {
        "video_state_changed",
        "task_progress",
        "videos.update",
        "log",
        "logs.append",
    }
)

class WebSocketBridge:
    """Thread-safe Python bridge from controller events to WebSocket transport."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None,
        send_func: Callable,
        *,
        event_recorder: Callable[[str, dict[str, Any]], None] | None = None,
        delta_provider: Callable[[int], dict[str, Any]] | None = None,
        delta_interval_seconds: float = 0.12,
    ):
        self._loop = loop
        self._send_func = send_func
        self._event_recorder = event_recorder
        self._delta_provider = delta_provider
        self._delta_interval_seconds = max(0.02, float(delta_interval_seconds))
        self._pending_tasks: set[asyncio.Task] = set()
        self._delta_lock = threading.RLock()
        self._delta_pending = False
        self._delta_schedule_generation = 0
        self._last_delta_version = 0

    def _get_loop(self) -> asyncio.AbstractEventLoop | None:
        """Resolve the uvicorn loop lazily so worker threads can emit safely."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                return None
        return self._loop

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Explicitly bind the running WebSocket event loop."""
        self._loop = loop

    def mark_frontend_version_sent(self, version: int) -> None:
        try:
            normalized = int(version or 0)
        except (TypeError, ValueError):
            normalized = 0
        with self._delta_lock:
            self._last_delta_version = max(self._last_delta_version, normalized)

    def emit(self, event_type: str, data: Any = None):
        """Safely broadcast an event from any thread and schedule frontend deltas."""
        event_type = str(event_type or "")
        payload = data if isinstance(data, dict) else {}
        self._record_frontend_event(event_type, payload)
        self._schedule_frontend_delta(event_type)
        if self._should_send_legacy_event(event_type):
            self._schedule_send(event_type, data)

    def _should_send_legacy_event(self, event_type: str) -> bool:
        if self._delta_provider is None:
            return True
        return str(event_type or "") not in DELTA_ONLY_LEGACY_TOPICS

    def _record_frontend_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type in {"frontend_state", "frontend_delta", "init_state", "platforms", "config"}:
            return
        if self._event_recorder is None:
            return
        try:
            self._event_recorder(event_type, payload)
        except Exception as exc:
            debug_logger.log_exception("WebSocketBridge", "record_frontend_event", exc)

    def _schedule_frontend_delta(self, event_type: str) -> None:
        if self._delta_provider is None or event_type in {"frontend_state", "frontend_delta"}:
            return
        if sections_for_topic(event_type) is None:
            return
        priority = priority_for_topic(event_type)
        delay = 0.0 if priority == FrontendEventPriority.CRITICAL else self._delta_interval_seconds
        with self._delta_lock:
            if self._delta_pending and priority != FrontendEventPriority.CRITICAL:
                return
            self._delta_pending = True
            self._delta_schedule_generation += 1
            generation = self._delta_schedule_generation
        loop = self._get_loop()

        def _schedule() -> None:
            if delay <= 0:
                loop.call_soon(self._flush_frontend_delta, generation)
            else:
                loop.call_later(delay, self._flush_frontend_delta, generation)

        if loop and loop.is_running():
            loop.call_soon_threadsafe(_schedule)
        else:
            with self._delta_lock:
                if generation == self._delta_schedule_generation:
                    self._delta_pending = False
            debug_logger.log(
                "WebSocketBridge",
                "frontend_delta_deferred",
                level="DEBUG",
                message="Web event loop is unavailable; deferred frontend delta until a later async flush.",
                status_code="WEB_DELTA_DEFERRED",
                details={"event_type": event_type, "generation": generation},
            )

    def _flush_frontend_delta(self, generation: int | None = None) -> None:
        with self._delta_lock:
            if generation is not None and generation != self._delta_schedule_generation:
                return
            self._delta_pending = False
            base_version = self._last_delta_version
        if self._delta_provider is None:
            return
        loop = self._get_loop()
        if loop and loop.is_running() and callable(getattr(loop, "run_in_executor", None)):
            try:
                task = loop.create_task(self._build_and_send_frontend_delta(base_version, generation))
            except RuntimeError:
                pass
            else:
                self._track_task(task)
                return
        debug_logger.log(
            "WebSocketBridge",
            "frontend_delta_skipped",
            level="DEBUG",
            message="Skipped frontend delta flush because no running event loop is available.",
            status_code="WEB_DELTA_NO_LOOP",
            details={"generation": generation},
        )

    async def _build_and_send_frontend_delta(self, base_version: int, generation: int | None = None) -> None:
        if self._delta_provider is None:
            return
        try:
            loop = asyncio.get_running_loop()
            delta = await loop.run_in_executor(None, self._delta_provider, base_version)
        except Exception as exc:
            debug_logger.log_exception("WebSocketBridge", "frontend_delta", exc)
            return
        self._emit_frontend_delta(delta, base_version, generation)

    def _emit_frontend_delta(self, delta: dict[str, Any], base_version: int, generation: int | None = None) -> None:
        if not isinstance(delta, dict):
            return
        with self._delta_lock:
            if generation is not None and generation != self._delta_schedule_generation:
                return
        version = int(delta.get("version") or base_version or 0)
        if version == base_version and not delta.get("changed_sections"):
            return

        def _mark_delivered() -> None:
            with self._delta_lock:
                self._last_delta_version = max(self._last_delta_version, version)

        self._schedule_send("frontend_delta", delta, on_accepted=_mark_delivered)

    def _schedule_send(
        self,
        event_type: str,
        data: Any = None,
        *,
        on_accepted: Callable[[], None] | None = None,
    ) -> bool:
        target_loop = self._get_loop()
        try:
            current_loop = asyncio.get_running_loop()
            if current_loop is target_loop:
                def _schedule():
                    result = self._send_func(event_type, data)
                    self._handle_send_result(result, current_loop, on_accepted=on_accepted)

                current_loop.call_soon(_schedule)
                return True
        except RuntimeError:
            pass

        if target_loop and target_loop.is_running():
            def _schedule():
                result = self._send_func(event_type, data)
                self._handle_send_result(result, target_loop, on_accepted=on_accepted)

            target_loop.call_soon_threadsafe(_schedule)
            return True
        else:
            import logging
            logging.warning(f"WebSocketBridge: event loop is not running; dropped event {event_type}")
            return False

    def _handle_send_result(
        self,
        result: Any,
        loop: asyncio.AbstractEventLoop,
        *,
        on_accepted: Callable[[], None] | None = None,
    ) -> None:
        if asyncio.iscoroutine(result):
            self._track_task(loop.create_task(result), on_accepted=on_accepted)
            return
        if result is not False and on_accepted is not None:
            on_accepted()

    def _track_task(self, task: asyncio.Task, *, on_accepted: Callable[[], None] | None = None) -> None:
        add_done_callback = getattr(task, "add_done_callback", None)
        if not callable(add_done_callback):
            return
        self._pending_tasks.add(task)

        def _discard(done_task: asyncio.Task) -> None:
            self._pending_tasks.discard(done_task)
            try:
                result = done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                debug_logger.log_exception("WebSocketBridge", "send_task", exc)
            else:
                if result is not False and on_accepted is not None:
                    on_accepted()

        add_done_callback(_discard)

    def call_later(self, delay_seconds: float, callback: Callable[[], None]) -> None:
        """Schedule a callback on the Web event loop when available."""
        loop = self._get_loop()
        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: loop.call_later(delay_seconds, callback))
            return
        callback()

class WebController(ControllerSessionMixin, MediaLibraryMixin):
    """Web 端核心控制器，逻辑与 ApplicationController 对称，但输出到 WebSocket。"""

    MAX_CONCURRENT_API_OPS = 16
    VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    DOWNLOAD_LOG_COMPONENT = "WebController"
    DOWNLOAD_FINISHED_STATUS_CODE = "WEB_DL_FINISH"
    DOWNLOAD_ERROR_STATUS_CODE = "WEB_DL_ERROR"
    DOWNLOAD_FINISHED_MESSAGE = "Web 端下载任务完成"
    DOWNLOAD_ERROR_MESSAGE = "Web 端下载任务失败"
    DOWNLOAD_ERROR_PROGRESS = 0
    PROGRESS_EVENT_MIN_INTERVAL_SECONDS = 0.25

    def __init__(self, loop: asyncio.AbstractEventLoop, send_func: Callable):
        self._loop = loop
        self._send_func = send_func
        self.frontend_state_service = FrontendStateService(self)
        self.bridge = WebSocketBridge(
            loop,
            send_func,
            event_recorder=self.frontend_state_service.record_event,
            delta_provider=self.get_frontend_delta,
        )
        self.frontend_state_service.set_frontend_event_emitter(self.bridge.emit)

        self.file_service = MediaLibraryService(self.VIDEO_EXTENSIONS, self.IMAGE_EXTENSIONS)
        self._dl_manager: DownloadManager | None = None
        self._dl_manager_lock = threading.RLock()

        self.videos: dict[str, VideoItem] = {}
        self._videos_lock = threading.RLock()
        self._progress_emit_lock = threading.RLock()
        self._last_progress_emit_at: dict[str, float] = {}
        self._last_progress_emit_value: dict[str, int] = {}
        self.current_spider = None
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_condition = threading.Condition(self._lifecycle_lock)
        self._is_shutting_down = False
        self._save_dir_lock = threading.RLock()
        self._current_save_dir: str = cfg.get("common", "save_directory", "downloads")
        self._stop_wait_lock = threading.RLock()
        self._stop_wait_count = 0
        self._stop_wait_spider = None
        self._pending_selection_strategy = None  # 由 /api/crawl/start 设置，供 _bind_spider_signals 使用
        self.max_concurrent_api_ops = self.MAX_CONCURRENT_API_OPS
        self._api_operation_semaphore = asyncio.Semaphore(self.max_concurrent_api_ops)
    @property
    def dl_manager(self) -> DownloadManager:
        """延迟创建 DownloadManager，避免空闲会话也创建实例。"""
        with self._dl_manager_lock:
            if self._dl_manager is None:
                self._dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))
                self._connect_download_signals()
            return self._dl_manager

    @property
    def current_save_dir(self) -> str:
        with self._save_dir_lock:
            return self._current_save_dir

    @current_save_dir.setter
    def current_save_dir(self, value: str) -> None:
        with self._save_dir_lock:
            self._current_save_dir = str(value)

    def _connect_download_signals(self):
        manager = self._dl_manager
        if manager is None:
            return
        manager.task_started.connect(self._on_task_started)
        manager.task_progress.connect(self._on_task_progress)
        manager.task_finished.connect(self._on_task_finished)
        manager.task_error.connect(self._on_task_error)

    def _video_lookup(self, video_id: str) -> VideoItem | None:
        with self._videos_lock:
            return self.videos.get(video_id)

    def _video_state_guard(self):
        return self._videos_lock

    def _store_video_item(self, item: VideoItem) -> None:
        with self._videos_lock:
            self.videos[item.id] = item

    def _remove_video_item(self, video_id: str) -> VideoItem | None:
        self._forget_progress_emit_state(video_id)
        with self._videos_lock:
            return self.videos.pop(video_id, None)

    def _clear_video_items(self) -> None:
        self._clear_progress_emit_state()
        with self._videos_lock:
            self.videos.clear()

    def _video_items_snapshot(self) -> dict[str, VideoItem]:
        with self._videos_lock:
            return deepcopy(self.videos)

    def _video_count(self) -> int:
        with self._videos_lock:
            return len(self.videos)

    def _has_active_spider(self) -> bool:
        with self._lifecycle_lock:
            spider = self.current_spider
        return bool(spider and spider.isRunning())

    def _video_only_mode_enabled(self) -> bool:
        manager_value = getattr(getattr(self, "_dl_manager", None), "video_only", None)
        if isinstance(manager_value, bool):
            return manager_value
        return bool(cfg.get("download", "video_only", False))

    def _should_skip_for_video_only(self, item: VideoItem) -> bool:
        return self._video_only_mode_enabled() and should_skip_for_video_only(item)

    def _log_video_only_skip(self, item: VideoItem) -> None:
        debug_logger.log(
            component="WebController",
            action="skip_non_video_resource",
            message="Video-only mode skipped a non-video resource",
            status_code="WEB_SKIP_VIDEO_ONLY",
            context=debug_logger.pick_used(
                {"trace_id": item.meta.get("trace_id"), "video_id": item.id, "source": item.source},
                "trace_id",
                "video_id",
                "source",
            ),
            details=debug_logger.pick_used(
                {"title": item.title, "url": item.url, "content_type": item.meta.get("content_type")},
                "title",
                "url",
                "content_type",
            ),
            trace_id=item.meta.get("trace_id"),
        )

    # ---- 下载信号处理 ----

    def _after_task_started(self, video_id: str, item: VideoItem | None) -> None:
        local_path = (item.local_path or "") if item else ""
        title = item.title if item else ""
        content_type = (item.meta.get("content_type", "") if item.meta else "") if item else ""
        self.bridge.emit("task_started", {
            "video_id": video_id,
            "local_path": local_path,
            "title": title,
            "content_type": content_type,
        })

    def _after_task_progress(self, video_id: str, item: VideoItem | None, progress: int) -> None:
        # `video_state_changed` 已经覆盖进度变化；这里不再额外发送 `task_progress`，
        # 避免高频下载时把 WebSocket 和前端 DOM 更新放大成双倍事件风暴。
        return None

    def _after_task_finished(self, video_id: str, item: VideoItem | None) -> None:
        local_path = (item.local_path or "") if item else ""
        content_type = ""
        title = ""
        if item:
            content_type = item.meta.get("content_type", "") if item.meta else ""
            title = item.title
        self.bridge.emit("task_finished", {
            "video_id": video_id,
            "local_path": local_path,
            "content_type": content_type,
            "title": title,
        })
        self._forget_progress_emit_state(video_id)

    def _after_task_error(self, video_id: str, item: VideoItem | None, error: str) -> None:
        local_path = (item.local_path or "") if item else ""
        content_type = (item.meta.get("content_type", "") if item.meta else "") if item else ""
        title = item.title if item else ""
        self.bridge.emit("task_error", {
            "video_id": video_id,
            "error": error,
            "local_path": local_path,
            "content_type": content_type,
            "title": title,
        })
        self._forget_progress_emit_state(video_id)

    def _publish_video_state(self, vid: str, item: VideoItem, *, requested_progress: int | None) -> None:
        if requested_progress is not None and not self._should_emit_progress_update(vid, requested_progress):
            return
        event_data = {
            "video_id": vid,
            "status": item.status,
            "progress": item.progress if requested_progress is not None else None,
        }
        if item.status in ("✅ 完成", "❌ 失败", "❌ 超时"):
            event_data["local_path"] = item.local_path or ""
            event_data["content_type"] = (item.meta.get("content_type", "") if item.meta else "")
        self.bridge.emit("video_state_changed", event_data)

    def _should_emit_progress_update(self, video_id: str, progress: int) -> bool:
        try:
            normalized = max(0, min(100, int(progress)))
        except (TypeError, ValueError):
            return False
        if normalized in {0, 100}:
            return True
        now = time.monotonic()
        with self._progress_emit_lock:
            last_progress = self._last_progress_emit_value.get(video_id)
            last_at = self._last_progress_emit_at.get(video_id, 0.0)
            if last_progress == normalized:
                return False
            if now - last_at < self.PROGRESS_EVENT_MIN_INTERVAL_SECONDS:
                return False
            self._last_progress_emit_value[video_id] = normalized
            self._last_progress_emit_at[video_id] = now
            return True

    def _forget_progress_emit_state(self, video_id: str) -> None:
        with self._progress_emit_lock:
            self._last_progress_emit_at.pop(str(video_id), None)
            self._last_progress_emit_value.pop(str(video_id), None)

    def _clear_progress_emit_state(self) -> None:
        with self._progress_emit_lock:
            self._last_progress_emit_at.clear()
            self._last_progress_emit_value.clear()

    def _emit_controller_log(
        self,
        message: str,
        *,
        trace_id: str | None = None,
        source: str = "Downloader",
        level: str = "INFO",
    ) -> None:
        self.bridge.emit(
            "log",
            {
                "message": message,
                "trace_id": trace_id or "",
                "source": source or "Downloader",
                "level": level or "INFO",
            },
        )

    async def _send_recorded_frontend_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = data if isinstance(data, dict) else {}
        try:
            self.frontend_state_service.record_event(event_type, payload)
        except Exception as exc:
            debug_logger.log_exception("WebController", "record_direct_frontend_event", exc)
        result = self._send_func(event_type, data)
        if inspect.isawaitable(result):
            await result

    def _build_download_finished_log_details(self, item: VideoItem) -> dict[str, Any]:
        return {
            "video_id": item.id,
            "title": item.title,
            "local_path": item.local_path or "",
        }

    def _build_download_error_log_details(self, item: VideoItem, error: str) -> dict[str, Any]:
        return {
            "video_id": item.id,
            "title": item.title,
            "error": error,
        }

    # ---- 爬虫控制 ----

    def _cleanup_dead_spider(self):
        """清理已退出但未被 _on_spider_finished 处理的 spider。

        场景：spider 因 Playwright 崩溃等异常退出，sig_finished 未被 emit，
        导致 current_spider 残留、isRunning() 返回 False 但引用未清空。
        """
        if self.current_spider and not self.current_spider.isRunning():
            self.bridge.emit("log", {"message": "⚠️ 上次任务未正常结束，正在清理..."})
            self._disconnect_spider_signals(self.current_spider)
            self.current_spider = None
            self._pending_selection_strategy = None
            self.bridge.emit("crawl_state", {"is_running": False})

    def start_crawl(self, source_id: str, keyword: str, config: dict):
        with self._lifecycle_condition:
            shutdown_deadline = time.monotonic() + 10.0
            while self._is_shutting_down:
                remaining = shutdown_deadline - time.monotonic()
                if remaining <= 0:
                    self.bridge.emit("log", {"message": "上一个任务仍在停止中，请稍后再试"})
                    self.bridge.emit("crawl_state", {"is_running": False})
                    return
                self._lifecycle_condition.wait(timeout=min(0.5, remaining))
            self._start_crawl_unlocked(source_id, keyword, config)

    def _start_crawl_unlocked(self, source_id: str, keyword: str, config: dict):
        # 清理已退出但残留的 spider 引用
        self._cleanup_dead_spider()

        if self.current_spider and self.current_spider.isRunning():
            self.bridge.emit("log", {"message": "⚠️ 当前已有任务在运行，请先停止或等待结束"})
            # 与 GUI 一致：启动失败时恢复 UI 状态
            self.bridge.emit("crawl_state", {"is_running": False})
            # 清理预置的选择策略，避免跨请求污染
            self._pending_selection_strategy = None
            return

        plugin = registry.get_plugin(source_id)
        if not plugin:
            self.bridge.emit("log", {"message": "❌ 未知的爬虫源"})
            self.bridge.emit("crawl_state", {"is_running": False})
            # 清理预置的选择策略，避免跨请求污染
            self._pending_selection_strategy = None
            return

        # BaseSpider 已完成去 Qt 化，Web 侧可直接在当前线程创建和启动。
        self._do_start_crawl(plugin, source_id, keyword, config)

    def _do_start_crawl(self, plugin, source_id: str, keyword: str, config: dict):
        """在 Qt 主线程中创建和启动 spider（与 GUI on_start_crawl 对齐）。"""
        try:
            spider_cls = plugin.get_spider_class()
            spider = spider_cls(keyword=keyword, config=config)
        except Exception as exc:
            self.bridge.emit("log", {"message": f"❌ 创建爬虫失败: {exc}"})
            self.bridge.emit("crawl_state", {"is_running": False})
            self._pending_selection_strategy = None
            return

        self.bridge.emit("log", {"message": f"🟢 启动任务 | 模式: {plugin.name} | 关键词: {keyword}"})
        self.bridge.emit("crawl_state", {"is_running": True, "source": source_id})

        # 与 GUI _log_crawl_start 对齐：记录爬虫启动日志
        debug_logger.log(
            component="WebController",
            action="start_crawl",
            message="Web 端启动爬虫任务",
            status_code="WEB_CRAWL_START",
            details={
                "keyword": keyword,
                "source_id": source_id,
                "plugin_name": plugin.name,
                "active_config": {k: v for k, v in config.items() if v not in (None, "", [], {})},
            },
        )

        spider.ui_trace_id = debug_logger.new_trace_id(f"{source_id}-crawl")
        spider.source_id = source_id
        self.current_spider = spider
        self._bind_spider_signals(spider)
        spider.start()

    def _bind_spider_signals(self, spider):
        from types import MethodType

        # Web 端始终显式接管 ask_user_selection。
        # 这样可以避免 Spider 线程依赖通用回调链去“碰运气”唤醒 WebSocket，
        # 选择弹窗的展示/恢复统一收口到 WebController。
        if self._pending_selection_strategy is not None:
            strategy = self._pending_selection_strategy
            self._pending_selection_strategy = None  # 用完即清
            call_count = [0]

            def ask_user_selection_sync(spider_self, items):
                """同步版 ask_user_selection：直接调 selection_strategy，不走 Qt 信号。
                与 CLI CLIRunner._make_ask_user_selection 完全对齐。"""
                from cli.selection_base import build_selection_prompt

                call_count[0] += 1
                try:
                    indices = strategy.select(
                        items,
                        prompt=build_selection_prompt(call_count[0], len(items)),
                    )
                except Exception:
                    indices = list(range(len(items)))
                if indices is None:
                    indices = []
                return indices

            spider.ask_user_selection = MethodType(ask_user_selection_sync, spider)
        else:
            def ask_user_selection_web(spider_self, items):
                spider_self._resume_event.clear()
                spider_self._selection_result = None
                spider_self._selection_emit_perf_ms = time.perf_counter() * 1000
                spider_self._selection_emit_wall_ms = int(time.time() * 1000)
                self._on_spider_select_tasks(items)
                while spider_self.is_running:
                    if spider_self._resume_event.wait(timeout=1.0):
                        break
                if not spider_self.is_running and spider_self._selection_result is None:
                    return None
                result = spider_self._selection_result
                spider_self._selection_result = None
                return result

            spider.ask_user_selection = MethodType(ask_user_selection_web, spider)

        # BaseSpider 现在使用纯 Python 回调信号；WebSocketBridge 自身已负责跨线程投递到 asyncio。
        def on_log(msg):
            self.bridge.emit(
                "log",
                {
                    "message": msg,
                    "trace_id": getattr(spider, "ui_trace_id", "") or "",
                    "source": getattr(spider, "source_id", "") or "Spider",
                    "level": "INFO",
                },
            )

        spider.sig_log.connect(on_log)
        spider.sig_item_found.connect(self._on_spider_item_found)
        spider.sig_select_tasks.connect(self._on_spider_select_tasks)
        spider.sig_finished.connect(self._on_spider_finished)
        self._spider_signal_handlers = {
            "on_log": on_log,
            "on_item_found": self._on_spider_item_found,
            "on_select_tasks": self._on_spider_select_tasks,
            "on_finished": self._on_spider_finished,
        }

    def _disconnect_spider_signals(self, spider) -> None:
        handlers = getattr(self, "_spider_signal_handlers", None) or {}
        mapping = (
            ("sig_log", handlers.get("on_log")),
            ("sig_item_found", handlers.get("on_item_found")),
            ("sig_select_tasks", handlers.get("on_select_tasks")),
            ("sig_finished", handlers.get("on_finished")),
        )
        for signal_name, callback in mapping:
            if callback is None:
                continue
            signal = getattr(spider, signal_name, None)
            disconnect = getattr(signal, "disconnect", None)
            if callable(disconnect):
                try:
                    disconnect(callback)
                except (TypeError, ValueError):
                    pass
        self._spider_signal_handlers = {}

    def _on_spider_item_found(self, item: VideoItem):
        if self._should_skip_for_video_only(item):
            self._log_video_only_skip(item)
            return
        self._prepare_pending_item(item)
        self._store_video_item(item)
        self.bridge.emit("item_found", self._video_item_to_dict(item))
        self.dl_manager.add_task(item, self.current_save_dir)
        # 与 GUI _on_spider_item_found 对齐：记录 item 发现日志（含 context 和 trace_id）
        debug_logger.log(
            component="WebController",
            action="item_found",
            message="Web 端发现可下载资源",
            status_code="WEB_ITEM_FOUND",
            context=self._item_context(item),
            details={"video_id": item.id, "title": item.title, "source": item.source},
            trace_id=self._item_trace_id(item),
        )

    def _on_spider_select_tasks(self, items: list):
        """二次选择回调：将候选列表推送给前端。

        与 GUI SelectionDialog 对齐：序列化完整信息，不只是 title/index。
        VideoItem 对象使用 to_dict() 序列化，dict 对象提取关键字段。
        """
        serialized = []
        for i, it in enumerate(items):
            if isinstance(it, VideoItem):
                # 与 GUI 一致：使用 to_dict() 完整序列化
                serialized.append(it.to_dict())
            elif isinstance(it, dict):
                # 兼容 dict 格式：提取关键字段，补全 index
                entry = {"index": it.get("index", i)}
                for key in ("id", "title", "url", "source", "status", "progress",
                            "local_path", "content_type", "meta"):
                    if key in it:
                        entry[key] = it[key]
                if "title" not in entry:
                    entry["title"] = ""
                serialized.append(entry)
            elif hasattr(it, "title"):
                # 其他有 title 属性的对象
                serialized.append({
                    "index": i,
                    "title": getattr(it, "title", ""),
                    "url": getattr(it, "url", ""),
                    "source": getattr(it, "source", ""),
                })
            else:
                serialized.append({"title": str(it), "index": i})
        spider_trace = {}
        if self.current_spider and hasattr(self.current_spider, "get_selection_emit_trace"):
            spider_trace = self.current_spider.get_selection_emit_trace()
        controller_perf_ms = time.perf_counter() * 1000
        controller_wall_ms = int(time.time() * 1000)
        if spider_trace.get("spider_emit_perf_ms"):
            debug_logger.log(
                "WebController",
                (
                    "select_tasks relay lag="
                    f"{controller_perf_ms - float(spider_trace['spider_emit_perf_ms']):.1f}ms "
                    f"items={len(serialized)}"
                ),
            )
        self.bridge.emit(
            "select_tasks",
            {
                "items": serialized,
                "timing": {
                    **spider_trace,
                    "controller_relay_perf_ms": controller_perf_ms,
                    "controller_relay_wall_ms": controller_wall_ms,
                },
            },
        )

    def _on_spider_finished(self):
        with self._lifecycle_lock:
            self._on_spider_finished_unlocked()

    def _on_spider_finished_unlocked(self):
        import threading
        spider = self.current_spider
        debug_logger.log(
            component="WebController",
            action="_on_spider_finished_enter",
            message="_on_spider_finished 被调用",
            status_code="WEB_SPIDER_FINISH_ENTER",
            details={
                "thread": threading.current_thread().name,
                "has_spider": self.current_spider is not None,
                "spider_running": self.current_spider.isRunning() if self.current_spider else None,
            },
        )
        self.bridge.emit("log", {"message": "✅ 爬虫任务结束"})
        if spider is not None:
            self._disconnect_spider_signals(spider)
        self.bridge.emit("crawl_state", {"is_running": False})
        # 与 GUI _on_spider_finished 对齐：记录完成日志
        debug_logger.log(
            component="WebController",
            action="crawl_finished",
            message="Web 端爬虫任务结束",
            status_code="WEB_CRAWL_FINISH",
        )
        self.current_spider = None
        # 防御性清理：确保 _pending_selection_strategy 不残留
        # （正常流程中 _bind_spider_signals 已消费，但 spider 异常退出时可能未消费）
        self._pending_selection_strategy = None

    def stop_crawl(self):
        with self._lifecycle_lock:
            self._stop_crawl_unlocked()

    def _stop_crawl_unlocked(self):
        if not self.current_spider:
            return
        # 防抖：如果已经在停止等待中，忽略重复请求
        with self._stop_wait_lock:
            if getattr(self, '_stop_wait_spider', None) is not None:
                return
        self._do_stop_crawl()

    def _do_stop_crawl(self):
        """在 Qt 主线程中执行停止操作（与 GUI on_stop_crawl 对齐）。"""
        spider = self.current_spider
        if not spider:
            return
        spider.stop()
        self.bridge.emit("log", {"message": "🛑 正在停止任务..."})
        debug_logger.log(
            component="WebController",
            action="stop_crawl",
            level="WARN",
            message="Web 端用户请求停止爬虫任务",
            status_code="WEB_CRAWL_STOP",
        )
        # 异步等待 spider 退出（避免阻塞 Qt 事件循环）
        with self._stop_wait_lock:
            self._stop_wait_count = 0
            self._stop_wait_spider = spider
        self._schedule_stop_wait()

    def _schedule_stop_wait(self):
        """异步等待 spider 线程退出（避免阻塞 Qt 事件循环）。"""
        with self._stop_wait_lock:
            spider = getattr(self, '_stop_wait_spider', None)
            if spider is None:
                return
            self._stop_wait_count += 1
            stop_wait_count = self._stop_wait_count

        if not spider.isRunning():
            # spider 已退出
            self._finish_stop(spider, forced=False)
            return

        if stop_wait_count >= 300:  # 30 秒超时（300 * 100ms）
            if self._spider_in_selection_wait(spider) and stop_wait_count < 600:
                self.bridge.call_later(0.1, self._schedule_stop_wait)
                return
            # spider 仍在运行（Playwright 阻塞），强制清理
            self._finish_stop(spider, forced=True)
            return

        # 继续等待
        self.bridge.call_later(0.1, self._schedule_stop_wait)

    @staticmethod
    def _spider_in_selection_wait(spider) -> bool:
        if spider is None or not spider.is_alive():
            return False
        resume_event = getattr(spider, "_resume_event", None)
        if resume_event is None:
            return False
        return not resume_event.is_set() and bool(getattr(spider, "_selection_emit_perf_ms", 0))

    def _finish_stop(self, spider, forced: bool = False):
        with self._lifecycle_lock:
            self._finish_stop_unlocked(spider, forced=forced)

    def _finish_stop_unlocked(self, spider, forced: bool = False):
        """完成停止操作的清理。"""
        # 强制释放时断开 spider 信号，防止幽灵 spider 继续发消息到前端
        self._disconnect_spider_signals(spider)
        if forced:
            self.bridge.emit("log", {"message": "⚠️ 爬虫线程未能在 30 秒内退出，已强制释放"})
        else:
            self.bridge.emit("log", {"message": "✅ 任务已停止"})
        # 清理 spider 引用（与 GUI _on_spider_finished 对齐）
        if self.current_spider is spider:
            self.current_spider = None
        self._pending_selection_strategy = None
        with self._stop_wait_lock:
            self._stop_wait_spider = None
            self._stop_wait_count = 0
        self.bridge.emit("crawl_state", {"is_running": False})

    def resume_spider_selection(self, selected_indices: list[int] | None):
        with self._lifecycle_lock:
            spider = self.current_spider
            if (
                spider is not None
                and selected_indices is None
                and not getattr(spider, "interrupt_requested", False)
            ):
                self._stop_crawl_unlocked()
        if spider:
            spider.resume_from_ui(selected_indices)

    # ---- 目录扫描 ----

    def scan_local_dir(self, directory: str | None = None, scan_limit: int | None = None):
        """同步版目录扫描（向后兼容）。

        与 GUI 对齐：扫描不改变 current_save_dir（只有 change_dir 才改变）。

        Args:
            directory: 要扫描的目录（默认使用 current_save_dir）
            scan_limit: 最多扫描文件数（None=从配置读取，与 REST API /api/scan 对齐）
        """
        directory = directory or self.current_save_dir
        self.bridge.emit("log", {"message": f"📂 正在扫描目录: {directory}"})
        # 与 GUI scan_local_dir 对齐：记录扫描开始日志
        debug_logger.log(
            component="WebController",
            action="scan_local_dir",
            message="Web 端开始扫描本地媒体目录",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )

        self._clear_video_items()
        self.bridge.emit("clear_videos", {"directory": directory})

        try:
            result = self._scan_media_directory(directory, scan_limit)
            for item in self._cache_scanned_items(result):
                self.bridge.emit("item_found", self._video_item_to_dict(item))
            for message in self._build_scan_messages(result):
                self.bridge.emit("log", {"message": message})
            self.bridge.emit("scan_result", {
                "total_count": result.total_count,
                "video_count": result.video_count,
                "image_count": result.image_count,
                # 与 REST API /api/scan 和 /api/dir/change 对齐：包含 truncated 和 original_count
                "truncated": result.truncated,
                "original_count": result.original_count,
            })
        except MediaScanError as exc:
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "scan_local_dir", exc, context={"directory": directory})
        except Exception as exc:
            # BUG-180: 捕获所有异常，避免未处理异常导致 WebSocket 断连
            self.bridge.emit("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "scan_local_dir", exc, context={"directory": directory})

    async def async_scan_local_dir(self, directory: str | None = None, scan_limit: int | None = None):
        """异步版目录扫描：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。

        修复 BUG-180: change_dir 不再使用 run_in_executor 包裹整个方法，
        而是只将文件 I/O 部分放到线程池，WebSocket 消息直接 await 发送，
        避免 bridge.emit 的 call_soon + create_task 调度可能导致的静默失败。
        修复 BUG-182: 直接 await self._send_func 而不是通过 bridge.emit 间接调度，
        确保消息在当前协程中立即发送，不会因为调度时序问题丢失。

        Args:
            directory: 要扫描的目录（默认使用 current_save_dir）
            scan_limit: 最多扫描文件数（None=从配置读取，与 REST API /api/scan 对齐）
        """
        import asyncio
        directory = directory or self.current_save_dir
        # 与 GUI 对齐：扫描不改变 current_save_dir（只有 async_change_dir 才改变）

        # 1. 直接 await 发送初始事件（确保消息立即发送到浏览器）
        await self._send_recorded_frontend_event("log", {"message": f"📂 正在扫描目录: {directory}"})
        # 与 GUI scan_local_dir 对齐：记录扫描开始日志
        debug_logger.log(
            component="WebController",
            action="async_scan_local_dir",
            message="Web 端开始扫描本地媒体目录（异步）",
            status_code="WEB_SCAN_START",
            details={"directory": directory},
        )
        self._clear_video_items()
        await self._send_recorded_frontend_event("clear_videos", {"directory": directory})

        # 2. 文件 I/O 在线程池中执行（不阻塞事件循环）
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                self._scan_media_directory,
                directory,
                scan_limit,
            )
        except MediaScanError as exc:
            await self._send_recorded_frontend_event("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "async_scan_local_dir", exc, context={"directory": directory})
            return
        except Exception as exc:
            await self._send_recorded_frontend_event("log", {"message": f"❌ 扫描目录出错: {exc}"})
            # 与 GUI scan_local_dir 对齐：记录扫描错误日志
            debug_logger.log_exception("WebController", "async_scan_local_dir", exc, context={"directory": directory})
            return

        # 3. 直接 await 发送结果事件（确保消息立即发送到浏览器）
        for item in self._cache_scanned_items(result):
            await self._send_recorded_frontend_event("item_found", self._video_item_to_dict(item))

        for message in self._build_scan_messages(result):
            await self._send_recorded_frontend_event("log", {"message": message})
        await self._send_recorded_frontend_event("scan_result", {
            "total_count": result.total_count,
            "video_count": result.video_count,
            "image_count": result.image_count,
            # 与 REST API /api/scan 和 /api/dir/change 对齐：包含 truncated 和 original_count
            "truncated": result.truncated,
            "original_count": result.original_count,
        })

    def change_dir(self, directory: str):
        self.current_save_dir = directory
        cfg.set("common", "save_directory", directory)
        # 与 GUI on_dir_changed 对齐：记录目录变更日志
        debug_logger.log(
            component="WebController",
            action="change_save_dir",
            message="Web 端保存目录已变更",
            status_code="WEB_DIR_CHANGED",
            details={"save_dir": directory},
        )
        self.bridge.emit("log", {"message": f"📂 目录已变更: {directory}"})
        self.scan_local_dir(directory)

    async def async_change_dir(self, directory: str):
        """异步版更改目录：使用 async_scan_local_dir，WebSocket 消息直接 await 发送。

        与 REST API /api/dir/change 对齐：cfg.set 在线程池中执行，避免文件 I/O 阻塞事件循环。
        """
        self.current_save_dir = directory
        # 与 REST API /api/dir/change 对齐：cfg.set 在线程池中执行
        import asyncio
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, cfg.set, "common", "save_directory", directory
            )
        except (ConfigValidationError, ConfigWriteError, OSError, RuntimeError, TypeError, ValueError) as exc:
            debug_logger.log_exception("WebController", "async_change_dir_cfg_set", exc, details={"directory": directory})
        # 与 GUI on_dir_changed 对齐：记录目录变更日志
        debug_logger.log(
            component="WebController",
            action="change_save_dir",
            message="Web 端保存目录已变更",
            status_code="WEB_DIR_CHANGED",
            details={"save_dir": directory},
        )
        await self._send_recorded_frontend_event("log", {"message": f"📂 目录已变更: {directory}"})
        await self.async_scan_local_dir(directory)

    # ---- 文件操作 ----

    def delete_video(self, video_id: str):
        outcome = self._delete_video_sync(video_id)
        if outcome.status == "missing":
            return {"status": "ok", "message": "already deleted", "data": {"video_id": video_id, "missing": True}}
        if outcome.status == "error":
            self.bridge.emit("log", {"message": f"❌ 删除文件失败: {outcome.error}"})
            return {"status": "error", "message": outcome.error or "delete failed", "data": {"video_id": video_id}}
        for message in self._delete_outcome_messages(outcome):
            self.bridge.emit("log", {"message": message})
        self.bridge.emit("video_removed", {"video_id": video_id})
        return {
            "status": "ok",
            "message": "deleted",
            "data": {"video_id": video_id, "deleted": outcome.deleted},
        }

    async def async_delete_video(self, video_id: str, _approved_roots=None):
        """异步版删除视频：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。"""
        import asyncio
        context = self._begin_delete_video(video_id)
        if context is None:
            return {"status": "ok", "message": "already deleted", "data": {"video_id": video_id, "missing": True}}
        try:
            deleted = await asyncio.get_running_loop().run_in_executor(
                None, self.file_service.delete_media, context.video
            )
        except FileOperationError as exc:
            await self._send_recorded_frontend_event("log", {"message": f"❌ 删除文件失败: {exc}"})
            return {"status": "error", "message": str(exc), "data": {"video_id": video_id}}
        outcome = self._complete_delete_video(context, deleted=deleted)
        for message in self._delete_outcome_messages(outcome):
            await self._send_recorded_frontend_event("log", {"message": message})
        await self._send_recorded_frontend_event("video_removed", {"video_id": video_id})
        return {
            "status": "ok",
            "message": "deleted",
            "data": {"video_id": video_id, "deleted": deleted},
        }

    # ---- 重命名 ----

    def rename_video(self, video_id: str, new_title: str) -> dict:
        outcome = self._rename_video_sync(video_id, new_title, self.current_save_dir)
        if outcome.status != "ok":
            self.bridge.emit("log", {"message": f"❌ 重命名失败: {outcome.error}"})
            return {"status": "error", "message": outcome.error}
        message = self._rename_outcome_message(outcome)
        if message:
            self.bridge.emit("log", {"message": message})
        self.bridge.emit(
            "video_renamed",
            {"video_id": video_id, "new_title": outcome.video.title, "new_path": outcome.new_path},
        )
        return {"status": "ok"}

    async def async_rename_video(self, video_id: str, new_title: str, _approved_roots=None) -> dict:
        """异步版重命名：文件 I/O 在线程池中执行，WebSocket 消息直接 await 发送。"""
        import asyncio
        video = self._video_lookup(video_id)
        if not video:
            return {"status": "error", "message": "视频不存在"}
        normalized_title = new_title.strip()
        if not normalized_title:
            return {"status": "error", "message": "标题不能为空"}
        if not video.local_path or not os.path.exists(video.local_path):
            return {"status": "error", "message": "文件不存在，无法重命名"}
        try:
            old_path, new_path = await asyncio.get_running_loop().run_in_executor(
                None, self.file_service.rename_media, video, normalized_title, self.current_save_dir
            )
            video.title = normalized_title
            video.local_path = new_path
            message = self._rename_outcome_message(
                MediaRenameOutcome(
                    status="ok",
                    video_id=video_id,
                    video=video,
                    old_path=old_path,
                    new_path=new_path,
                )
            )
            if message:
                await self._send_recorded_frontend_event("log", {"message": message})
            await self._send_recorded_frontend_event("video_renamed", {"video_id": video_id, "new_title": video.title, "new_path": new_path})
            return {"status": "ok"}
        except FileOperationError as exc:
            await self._send_recorded_frontend_event("log", {"message": f"❌ 重命名失败: {exc}"})
            return {"status": "error", "message": str(exc)}

    # ---- 配置 ----

    def get_config(self) -> dict:
        return cfg.settings.to_dict()

    def update_config(self, updates: dict):
        errors: list[ConfigWriteError] = []
        for section, values in updates.items():
            if not isinstance(values, dict):
                continue
            section_name = str(section)
            for key, value in values.items():
                key_name = str(key)
                if not WebControllerConfigService.is_web_config_allowed(section_name, key_name):
                    errors.append(
                        ConfigWriteError(
                            section=section_name,
                            key=key_name,
                            value=value,
                            error="该配置项不允许通过 Web 修改",
                        )
                    )
                    continue
                result = self.handle_frontend_action(
                    "update_setting",
                    {"section": section_name, "key": key_name, "value": value},
                )
                if isinstance(result, dict) and result.get("status") == "ok":
                    continue
                errors.append(
                    ConfigWriteError(
                        section=section_name,
                        key=key_name,
                        value=value,
                        error=str((result or {}).get("message") or "配置更新失败"),
                    )
                )
        return errors

    async def _run_api_operation(self, operation: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        del operation
        async with self._api_operation_semaphore:
            if inspect.iscoroutinefunction(func):
                result = func(*args, **kwargs)
            else:
                result = await asyncio.get_running_loop().run_in_executor(None, partial(func, *args, **kwargs))
            if inspect.isawaitable(result):
                return await result
            return result

    async def async_update_config(self, updates: dict) -> list[ConfigWriteError]:
        return await self._run_api_operation("update_config", self.update_config, updates)

    # ---- 平台信息 ----

    def get_platforms(self) -> list[dict]:
        """返回平台列表（与 SDK list_platforms 字段对齐）。"""
        platforms = []
        for plugin in registry.get_all_plugins():
            info = {
                "id": plugin.id,
                "name": plugin.name,
                "search_placeholder": plugin.get_search_placeholder(),
            }
            # 与 SDK list_platforms 一致：包含 description 和 settings
            if hasattr(plugin, "description") and plugin.description:
                info["description"] = plugin.description
            if hasattr(plugin, "settings_builder") and plugin.settings_builder is not None:
                try:
                    info["settings"] = plugin.settings_builder.field_defs
                except (AttributeError, TypeError):
                    pass
            platforms.append(info)
        return platforms

    # ---- 状态快照 ----

    def get_state(self) -> dict:
        with self._lifecycle_lock:
            spider = self.current_spider
        return {
            "current_save_dir": self.current_save_dir,
            "is_crawling": bool(spider and spider.isRunning()),
            # 与 GUI 状态栏对齐：返回当前已加载的视频数量
            "video_count": self._video_count(),
        }

    def get_frontend_state(self) -> dict:
        return self.frontend_state_service.get_snapshot()

    def get_frontend_delta(self, since_version: int = 0, sections: frozenset[str] | set[str] | None = None) -> dict:
        return self.frontend_state_service.get_delta(since_version, sections=sections)

    def get_frontend_icons(self) -> dict:
        return icon_manifest()

    def handle_frontend_action(self, action: str, payload: dict | None = None) -> dict:
        return self.frontend_state_service.handle_action(action, payload or {})

    async def async_handle_frontend_action(self, action: str, payload: dict | None = None) -> dict:
        normalized_payload = payload or {}

        async def _delete() -> dict:
            video_id = str(normalized_payload.get("id") or normalized_payload.get("video_id") or "")
            if not video_id:
                return {"status": "error", "message": "missing video id"}
            result = await self.async_delete_video(video_id)
            if isinstance(result, dict):
                return result
            return {"status": "ok", "message": "deleted", "data": {"video_id": video_id}}

        if action == "delete_item":
            return await self._run_api_operation("frontend_action", _delete)
        return await self._run_api_operation("frontend_action", self.handle_frontend_action, action, normalized_payload)

    # ---- 媒体路径 ----

    def get_media_path(self, video_id: str) -> str | None:
        item = self._video_lookup(video_id)
        if item and item.local_path and os.path.exists(item.local_path):
            return item.local_path
        return None

    # ---- 辅助 ----

    @staticmethod
    def _video_item_to_dict(item: VideoItem) -> dict:
        """统一序列化：委托给 VideoItem.to_dict()，确保 CLI/SDK/Web/Skill 四层一致。"""
        return item.to_dict()

    def shutdown(self):
        frontend_state_service = getattr(self, "frontend_state_service", None)
        with self._lifecycle_condition:
            self._is_shutting_down = True
            spider = self.current_spider
            self.current_spider = None
            self._pending_selection_strategy = None
            manager = self._dl_manager

        try:
            if spider and spider.isRunning():
                spider.stop()
                spider.wait(2000)
            if manager is not None:
                manager.stop_all()
        finally:
            destroy_frontend_state = getattr(frontend_state_service, "destroy", None)
            if callable(destroy_frontend_state):
                try:
                    destroy_frontend_state()
                except Exception as exc:
                    debug_logger.log_exception(
                        "WebController",
                        "shutdown_frontend_state_service",
                        exc,
                    )
            app_state = getattr(frontend_state_service, "app_state", None)
            shutdown_app_state = getattr(app_state, "shutdown", None)
            if callable(shutdown_app_state):
                try:
                    shutdown_app_state()
                except Exception as exc:
                    debug_logger.log_exception(
                        "WebController",
                        "shutdown_app_state",
                        exc,
                    )
            cache_service = getattr(frontend_state_service, "cache_service", None)
            close_cache = getattr(cache_service, "close", None)
            if callable(close_cache):
                try:
                    close_cache()
                except Exception as exc:
                    debug_logger.log_exception(
                        "WebController",
                        "shutdown_cache_service",
                        exc,
                    )
            with self._lifecycle_condition:
                self._is_shutting_down = False
                self._lifecycle_condition.notify_all()

    def _shutdown_unlocked(self):
        self.shutdown()
