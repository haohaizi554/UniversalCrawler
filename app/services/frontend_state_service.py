"""Unified frontend state adapter for GUI and WebUI.

This service is intentionally transport-agnostic.  GUI widgets and the Web
static app should consume the same snapshot shape instead of reading spiders,
downloaders, parsers, or task builders directly.
"""

from __future__ import annotations

import os
import threading
import time
from copy import deepcopy
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal

from app.config import cfg
from app.config.settings import (
    CURRENT_FILENAME_TEMPLATE,
    DEFAULT_OPEN_MODE,
    open_mode_label,
    playback_player_label,
)
from app.core.plugins.run_options import build_missav_proxy_url
from app.exceptions import ConfigValidationError
from app.debug_logger import debug_logger
from app.core.plugin_registry import registry
from app.core.state import VideoStatus, parse_video_status
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.cache_service import CacheService
from app.services import frontend_settings_adapter as settings_adapter
from app.services.frontend_event_aggregator import (
    ALL_FRONTEND_SECTIONS,
    VIDEO_SECTIONS,
    FrontendEventAggregator,
    sections_for_topic,
)
from app.services import completed_metadata_rules as metadata_rules
from app.services import frontend_file_actions as file_actions
from app.services import frontend_log_adapter as log_adapter
from app.services import frontend_status_adapter as status_adapter
from app.services import frontend_toolbox_adapter as toolbox_adapter
from app.services import frontend_video_adapter as video_adapter
from app.services.icon_registry import icon_manifest
from app.services.frontend_page_definitions import PAGE_DEFINITIONS
from app.services.frontend_log_cache import FrontendLogCache
from app.services.media_metadata_service import MediaMetadata, MediaMetadataService
from app.services.metadata_probe_queue import MetadataProbeQueue
from app.services.metadata_retry_tracker import MetadataRetryTracker
from app.utils.filenames import sanitize_filename
from app.utils.safe_slot import safe_slot

QUEUE_STATUSES = video_adapter.QUEUE_STATUSES
UI_TITLE_STAGE_META_KEY = "ui_title_stage"
UI_TITLE_TEMPLATE_META_KEY = "ui_title_template"


class _GuiRuntimeInvoker(QObject):
    call_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call_requested.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def invoke(self, callback: Callable[[], None]) -> None:
        self.call_requested.emit(callback)

    def _run(self, callback: Callable[[], None]) -> None:
        callback()

TOOLBOX_DEFINITIONS = toolbox_adapter.TOOLBOX_DEFINITIONS

@dataclass(slots=True)
class FrontendActionResult:
    status: str
    message: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"status": self.status}
        if self.message:
            result["message"] = self.message
        if self.data:
            result["data"] = self.data
        return result

class FrontendStateService:
    """Build the 7-page frontend snapshot shared by GUI and WebUI."""

    METADATA_PROBES_PER_SNAPSHOT = 64
    METADATA_EMPTY_MAX_RETRIES = 3
    FRONTEND_DELTA_EVENTS_LIMIT = 64
    FILE_LOG_BACKFILL_LIMIT = 500
    PLATFORM_AUTH_REFRESH_TTL_SECONDS = 60.0

    def __init__(
        self,
        controller: Any | None = None,
        config_manager=cfg,
        *,
        app_state: AppState | None = None,
        cache_service: CacheService | None = None,
        directory_opener: Callable[[str], None] | None = None,
        association_service_factory: Callable[[], Any] | None = None,
        executable_path_provider: Callable[[], str] | None = None,
        media_metadata_service: MediaMetadataService | None = None,
        frontend_event_emitter: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.controller = controller
        self.config = config_manager
        self._owns_app_state = app_state is None
        self.app_state = app_state if app_state is not None else AppState()
        self.cache_service = cache_service or self.app_state.cache_service
        self._directory_opener = directory_opener or self._open_directory_with_system
        self._association_service_factory = association_service_factory
        self._executable_path_provider = executable_path_provider or self._current_executable_path
        self.media_metadata_service = media_metadata_service or MediaMetadataService()
        self._frontend_event_emitter = frontend_event_emitter
        self._gui_runtime_invoker = self._create_gui_runtime_invoker()
        self._file_log_cache_store = FrontendLogCache(
            cache_service=self.cache_service,
            reader=self._read_log_items,
            limit_provider=self._ui_log_display_limit,
            ttl_seconds=1.0,
            backfill_limit=self.FILE_LOG_BACKFILL_LIMIT,
        )
        self._running_state = "空闲中"
        self._static_snapshot_cache: dict[str, Any] | None = None
        self._platform_auth_cache: dict[str, dict[str, Any]] = {}
        self._platform_auth_force_refresh_once = False
        self._delta_lock = threading.RLock()
        self._event_aggregator = FrontendEventAggregator()
        self._active_event_time_cache: dict[str, str] = {}
        self._metadata_retry_tracker = MetadataRetryTracker(
            retry_callback=lambda video_id, source_path: self._retry_completed_metadata_probe(video_id, source_path),
            event_callback=lambda topic, payload: self._emit_frontend_event(topic, payload),
            key_factory=self._metadata_failure_key,
            max_retries_provider=lambda: max(1, int(getattr(self, "METADATA_EMPTY_MAX_RETRIES", 3) or 3)),
            delay_provider=lambda: float(getattr(self.media_metadata_service, "EMPTY_RETRY_SECONDS", 30.0) or 30.0),
            timer_factory=threading.Timer,
        )
        self._metadata_probe_scheduler = MetadataProbeQueue(
            retry_callback=lambda video_id, source_path: self._retry_completed_metadata_probe(video_id, source_path),
            key_factory=self._metadata_failure_key,
            batch_size_provider=lambda: max(1, int(getattr(self, "METADATA_PROBES_PER_SNAPSHOT", 64) or 64)),
            closed_checker=lambda: self._destroyed,
            timer_factory=threading.Timer,
        )
        self._metadata_probe_budget_remaining: int | None = None
        self._destroyed = False
        self._app_state_event_handler = self.app_state.event_bus.subscribe(
            "app_state.changed",
            self._record_app_state_change,
        )
        subscribe = getattr(self.config, "subscribe", None)
        self._config_event_handler = (
            subscribe("config.changed", self._on_config_changed)
            if callable(subscribe)
            else None
        )
        self._apply_logging_runtime_settings(cleanup_old_logs=True)

    @staticmethod
    def _is_qt_gui_thread() -> bool:
        app = QCoreApplication.instance()
        if app is None:
            return threading.current_thread() is threading.main_thread()
        return QThread.currentThread() == app.thread()

    @staticmethod
    def _create_gui_runtime_invoker() -> _GuiRuntimeInvoker | None:
        app = QCoreApplication.instance()
        if app is None:
            return None
        invoker = _GuiRuntimeInvoker()
        if invoker.thread() != app.thread():
            invoker.moveToThread(app.thread())
        return invoker

    def bind_controller(self, controller: Any) -> None:
        if self._destroyed:
            return
        self.controller = controller
        snapshot = getattr(controller, "_video_items_snapshot", None)
        if callable(snapshot):
            self.app_state.replace_videos(snapshot())
            return
        snapshot_videos = getattr(self.app_state, "snapshot_videos", None)
        if callable(snapshot_videos):
            self.app_state.replace_videos(snapshot_videos())

    def set_frontend_event_emitter(self, emitter: Callable[[str, dict[str, Any]], None] | None) -> None:
        if self._destroyed:
            return
        self._frontend_event_emitter = emitter

    def set_running(self, is_running: bool) -> None:
        if self._destroyed:
            return
        self._running_state = "运行中" if is_running else "空闲中"
        self.app_state.set_running_state(self._running_state)

    def record_log(self, message: str, *, level: str = "INFO", source: str = "GUI", trace_id: str = "") -> None:
        if self._destroyed:
            return
        self.app_state.record_log(message, level=level, source=source, trace_id=trace_id)
        self._event_aggregator.record(
            "logs.append",
            {"message": message, "level": level, "source": source, "trace_id": trace_id},
            sections=sections_for_topic("logs.append"),
        )

    def upsert_video(self, item: VideoItem) -> None:
        if self._destroyed:
            return
        self.app_state.upsert_video(item)

    def remove_video(self, video_id: str) -> None:
        if self._destroyed:
            return
        self._active_event_time_cache.pop(str(video_id), None)
        self._cancel_metadata_retry(str(video_id))
        self._clear_metadata_empty_failures(str(video_id))
        self._drop_metadata_probe_queue_for(str(video_id))
        self.app_state.remove_video(video_id)

    def clear_videos(self) -> None:
        if self._destroyed:
            return
        self._cancel_metadata_probe_queue()
        self.app_state.clear_videos()

    def invalidate_refresh_caches(self) -> None:
        if self._destroyed:
            return
        self._invalidate_file_log_cache()
        self._static_snapshot_cache = None
        self._platform_auth_cache.clear()
        self._active_event_time_cache.clear()
        self._cancel_all_metadata_retries()
        self._cancel_metadata_probe_queue()
        self._clear_metadata_empty_failures()
        self._event_aggregator.reset()

    def destroy(self) -> None:
        """退订所有 EventBus 订阅，释放资源。应在 FSS 不再使用时调用。"""
        self._destroyed = True
        if self._app_state_event_handler is not None:
            try:
                self.app_state.event_bus.unsubscribe("app_state.changed", self._app_state_event_handler)
            except Exception as exc:
                debug_logger.log_exception(
                    "FrontendStateService",
                    "destroy.unsubscribe.app_state",
                    exc,
                )
            self._app_state_event_handler = None
        if self._config_event_handler is not None:
            unsubscribe = getattr(self.config, "unsubscribe", None)
            if callable(unsubscribe):
                try:
                    unsubscribe("config.changed", self._config_event_handler)
                except Exception as exc:
                    debug_logger.log_exception(
                        "FrontendStateService",
                        "destroy.unsubscribe.config",
                        exc,
                    )
            self._config_event_handler = None
        self._metadata_retry_tracker.cancel_all(clear_failures=True)
        self._cancel_metadata_probe_queue(close=True)
        if self._owns_app_state:
            shutdown = getattr(self.app_state, "shutdown", None)
            if callable(shutdown):
                shutdown()

    @property
    def frontend_version(self) -> int:
        return self._event_aggregator.version

    def frontend_metrics(self) -> dict[str, Any]:
        return self._event_aggregator.metrics()

    def record_event(self, topic: str, payload: Mapping[str, Any] | None = None) -> None:
        if self._destroyed:
            return
        normalized = str(topic or "")
        payload_dict = dict(payload or {})
        self._materialize_stage_title_for_event(normalized, payload_dict)
        if normalized == "log":
            message = str(payload_dict.get("message") or "")
            if message:
                self.record_log(
                    message,
                    level=str(payload_dict.get("level") or "INFO"),
                    source=str(payload_dict.get("source") or "Web"),
                    trace_id=str(payload_dict.get("trace_id") or ""),
                )
            return
        sections = self._sections_for_recorded_event(normalized, payload_dict)
        self._event_aggregator.record(normalized, payload_dict, sections=sections)

    def _record_app_state_change(self, payload: Any) -> None:
        if self._destroyed:
            return
        if not isinstance(payload, dict):
            self._event_aggregator.record("app_state.changed", {})
            return
        topic = str(payload.get("topic") or "app_state.changed")
        self._materialize_stage_title_for_event(topic, payload)
        sections = self._sections_for_recorded_event(topic, payload)
        self._event_aggregator.record(topic, payload, sections=sections)

    @staticmethod
    def _sections_for_recorded_event(topic: str, payload: Mapping[str, Any]) -> frozenset[str] | None:
        normalized = str(topic or "")
        if normalized not in {"videos.update", "video_state_changed", "task_progress"}:
            return sections_for_topic(normalized)
        status = str(payload.get("status") or "")
        parsed_status = parse_video_status(status)
        try:
            progress = int(payload.get("progress"))
        except (TypeError, ValueError):
            progress = None
        terminal_text = any(marker in status for marker in ("\u5b8c\u6210", "\u5931\u8d25", "\u8d85\u65f6", "\u672c\u5730"))
        if (
            parsed_status in {VideoStatus.COMPLETED, VideoStatus.LOCAL, VideoStatus.FAILED, VideoStatus.TIMED_OUT}
            or terminal_text
            or progress == 100
        ):
            return VIDEO_SECTIONS
        return sections_for_topic(normalized)

    def _static_snapshot_parts(self) -> dict[str, Any]:
        if self._static_snapshot_cache is not None and self._platform_auth_cache_has_expired():
            self._static_snapshot_cache = None
        if self._static_snapshot_cache is None:
            settings_snapshot = self.settings_snapshot()
            settings_contract = self._settings_contract_payload(settings_snapshot)
            self._static_snapshot_cache = {
                "pages": list(PAGE_DEFINITIONS),
                "settings_snapshot": settings_snapshot,
                "settings_contract": settings_contract,
                "toolbox_items": self.toolbox_items(),
                "toolbox_recent_items": self.toolbox_recent_items(),
                "icon_manifest": icon_manifest(),
            }
        parts = dict(self._static_snapshot_cache)
        parts["download_options"] = self.download_options_snapshot()
        return parts

    @staticmethod
    def _settings_contract_payload(settings_snapshot: Mapping[str, Any]) -> dict[str, Any]:
        order = [str(key) for key in settings_snapshot.keys()]
        descriptions = {
            "基础设置": "下载目录、文件命名和打开行为",
            "下载设置": "并发、超时、重试和下载策略",
            "平台设置": "认证状态、爬取数量和代理入口",
            "播放设置": "播放器、断点续播和预览行为",
            "日志设置": "保留策略、显示上限和错误追踪",
            "外观设置": "语言、主题、界面缩放和字体",
        }
        return {
            "group_order": order,
            "group_descriptions": {
                group: descriptions.get(group, "")
                for group in order
            },
        }

    def _build_video_sections(
        self,
        *,
        shallow: bool = False,
        only: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        videos = self._videos(shallow=shallow)
        queued_ids = self._queued_video_ids()
        active_ids = self._active_video_ids()
        queue_items: list[dict[str, Any]] = []
        active_downloads: list[dict[str, Any]] = []
        completed_items: list[dict[str, Any]] = []
        failed_items: list[dict[str, Any]] = []
        bucket_counts = {"queue": 0, "active": 0, "completed": 0, "failed": 0}
        log_excerpt_index: dict[str, list[dict[str, Any]]] | None = None

        want_failed = only is None or "failed_items" in only
        want_completed = only is None or "completed_items" in only
        want_active_items = only is None or "active_downloads" in only
        want_active_for_status = only is not None and "app_status" in only
        if want_failed:
            log_excerpt_index = self._log_excerpt_index()

        previous_probe_budget = self._metadata_probe_budget_remaining
        if want_completed:
            self._metadata_probe_budget_remaining = self.METADATA_PROBES_PER_SNAPSHOT
        try:
            for item in videos.values():
                bucket = self._bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids)
                item = self._ensure_stage_title_snapshot(item, bucket)
                if bucket in bucket_counts:
                    bucket_counts[bucket] += 1
                if bucket == "active":
                    if want_active_items or want_active_for_status:
                        active_downloads.append(self._active_item(item))
                elif bucket == "completed":
                    if want_completed:
                        completed_items.append(self._completed_item(item))
                elif bucket == "failed":
                    if want_failed:
                        failed_items.append(self._failed_item(item, log_excerpt_index=log_excerpt_index))
                else:
                    if only is None or "queue_items" in only:
                        queue_items.append(self._queue_item(item, queued_ids=queued_ids))
        finally:
            self._metadata_probe_budget_remaining = previous_probe_budget

        sections: dict[str, Any] = {}
        if only is None or "queue_items" in only:
            sections["queue_items"] = queue_items
        if only is None or "active_downloads" in only:
            sections["active_downloads"] = active_downloads
        if only is None or "completed_items" in only:
            sections["completed_items"] = completed_items
        if only is None or "failed_items" in only:
            sections["failed_items"] = failed_items
        if only is None or "app_status" in only:
            include_active = only is None or "active_downloads" in only
            sections["app_status"] = self.app_status(
                queue_count=bucket_counts["queue"],
                active_count=bucket_counts["active"],
                completed_count=bucket_counts["completed"],
                failed_count=bucket_counts["failed"],
                active_downloads=active_downloads if (include_active or want_active_for_status) else None,
            )
        return sections

    def get_snapshot(self, *, mock: bool = False, sections: frozenset[str] | None = None) -> dict[str, Any]:
        if mock:
            snapshot = self.mock_snapshot()
            snapshot["version"] = self.frontend_version
            return snapshot

        static_keys = frozenset({
            "pages",
            "icon_manifest",
            "toolbox_items",
            "toolbox_recent_items",
            "settings_snapshot",
            "settings_contract",
            "download_options",
        })
        video_keys = frozenset({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"})
        if sections is None:
            video_parts = self._build_video_sections(shallow=False)
            result = dict(self._static_snapshot_parts())
            result.update(video_parts)
            result["log_items"] = self.log_items()
            result["version"] = self.frontend_version
            return result

        result: dict[str, Any] = {}
        if sections & static_keys:
            result.update({key: value for key, value in self._static_snapshot_parts().items() if key in sections})
        if sections & video_keys:
            shallow = sections <= (video_keys | frozenset({"log_items"}))
            result.update(self._build_video_sections(shallow=shallow, only=sections & video_keys))
        if "log_items" in sections:
            result["log_items"] = self.log_items()
        result["version"] = self.frontend_version
        return result

    def get_delta(
        self,
        since_version: int = 0,
        *,
        sections: frozenset[str] | set[str] | None = None,
    ) -> dict[str, Any]:
        """Return a versioned frontend delta while keeping full snapshots compatible."""

        with self._delta_lock:
            try:
                base_version = int(since_version or 0)
            except (TypeError, ValueError):
                base_version = 0
            dirty = self._event_aggregator.peek()
            current_version = dirty.version
            history_sections = self._event_aggregator.sections_since(base_version)
            requested_sections = history_sections
            if sections is not None:
                requested_sections = history_sections | frozenset(sections)
            full = base_version < 0 or base_version > current_version
            if full:
                requested_sections = frozenset(ALL_FRONTEND_SECTIONS)
            elif base_version >= current_version:
                requested_sections = frozenset()

            snapshot_sections: dict[str, Any] = {}
            if requested_sections:
                partial = self.get_snapshot(sections=frozenset(requested_sections))
                snapshot_sections = {
                    key: value
                    for key, value in partial.items()
                    if key in requested_sections
                }

            return {
                "version": current_version,
                "base_version": base_version,
                "full": full,
                "changed_sections": sorted(requested_sections),
                "sections": snapshot_sections,
                "deleted_ids": [] if full else list(self._event_aggregator.deleted_ids_since(base_version)),
                "events": list(dirty.pending_events)[-self.FRONTEND_DELTA_EVENTS_LIMIT:],
                "priority": dirty.priority.name.lower(),
                "metrics": self.frontend_metrics(),
            }

    def handle_action(self, action: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self._destroyed:
            return FrontendActionResult("error", "frontend state service destroyed").to_dict()
        payload = payload or {}
        handler = {
            "delete_item": self._action_delete_item,
            "clear_queue": self._action_clear_queue,
            "pause_download": self._action_pause_download,
            "retry_failed": self._action_retry_failed,
            "copy_diagnostics": self._action_copy_diagnostics,
            "change_directory": self._action_change_directory,
            "update_basic_setting": self._action_update_basic_setting,
            "update_setting": self._action_update_setting,
            "open_directory": self._action_open_directory,
            "open_file": self._action_open_file,
            "run_tool": self._action_run_tool,
            "register_file_associations": self._action_register_file_associations,
            "update_download_options": self._action_update_download_options,
            "update_completed_metadata": self._action_update_completed_metadata,
            "log_operation": self._action_log_operation,
            "refresh_platform_auth_status": self._action_refresh_platform_auth_status,
        }.get(action)
        if handler is None:
            return FrontendActionResult("error", f"unknown frontend action: {action}").to_dict()
        return handler(payload).to_dict()

    def queue_item_ids(self) -> set[str]:
        queued_ids = self._queued_video_ids()
        active_ids = self._active_video_ids()
        with getattr(self.app_state, "_lock", threading.RLock()):
            videos = dict(getattr(self.app_state, "videos", {}) or {})
        if not videos:
            controller_videos = getattr(self.controller, "videos", None)
            if isinstance(controller_videos, dict):
                videos = dict(controller_videos)
        return {
            item.id
            for item in videos.values()
            if getattr(item, "id", None) and self._bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids) == "queue"
        }
    def _videos(self, *, shallow: bool = False) -> dict[str, VideoItem]:
        snapshot = getattr(self.controller, "_video_items_snapshot", None)
        if callable(snapshot):
            return snapshot()
        videos = getattr(self.controller, "videos", None)
        if isinstance(videos, dict):
            return videos if shallow else deepcopy(videos)
        snapshot_videos = getattr(self.app_state, "snapshot_videos", None)
        if callable(snapshot_videos):
            return snapshot_videos()
        source = self.app_state.videos
        return dict(source) if shallow else deepcopy(source)

    def _video_for_update(self, video_id: str) -> VideoItem | None:
        lookup = getattr(self.controller, "_video_lookup", None)
        if callable(lookup):
            return lookup(video_id)
        videos = getattr(self.controller, "videos", None)
        if isinstance(videos, dict):
            return videos.get(video_id)
        with getattr(self.app_state, "_lock", threading.RLock()):
            return self.app_state.videos.get(video_id)

    def _dl_manager(self) -> Any | None:
        controller = self.controller
        if controller is None:
            return None
        if hasattr(controller, "_dl_manager"):
            manager = getattr(controller, "_dl_manager", None)
            if manager is not None:
                return manager
            return None
        return getattr(controller, "dl_manager", None)

    def _config_section_values(self, section: str, defaults: Mapping[str, Any]) -> dict[str, Any]:
        raw_data = getattr(self.config, "data", None)
        section_data = raw_data.get(section, {}) if isinstance(raw_data, Mapping) else {}
        return {
            key: section_data.get(key, self.config.get(section, key, default))
            for key, default in defaults.items()
        }

    def _apply_download_runtime_settings(self) -> None:
        manager = self._dl_manager()
        if manager is None:
            return
        download_cfg = self._config_section_values(
            "download",
            {
                "max_concurrent": 3,
                "max_retries": 3,
                "request_timeout": 60,
                "resume_enabled": True,
                "speed_limit_kb": 0,
                "video_only": False,
                "image_respects_concurrency": False,
                "image_fast_lane_limit": 10,
            },
        )
        set_runtime_options = getattr(manager, "set_runtime_options", None)
        if callable(set_runtime_options):
            set_runtime_options(
                max_concurrent=download_cfg.get("max_concurrent", 3),
                max_retries=download_cfg.get("max_retries", 3),
                request_timeout=download_cfg.get("request_timeout", 60),
                resume_enabled=download_cfg.get("resume_enabled", True),
                speed_limit_kb=download_cfg.get("speed_limit_kb", 0),
                video_only=download_cfg.get("video_only", False),
                image_respects_concurrency=download_cfg.get("image_respects_concurrency", False),
                image_fast_lane_limit=download_cfg.get("image_fast_lane_limit", 10),
            )
            return

    def _apply_logging_runtime_settings(self, *, cleanup_old_logs: bool = False) -> None:
        logging_cfg = self._config_section_values(
            "logging",
            {
                "level": "info",
                "retention_days": 1,
                "cleanup_old_logs_on_start": False,
                "ui_log_max_display_count": 300,
                "auto_copy_trace_on_error": True,
            },
        )
        configure = getattr(debug_logger, "configure", None)
        if callable(configure):
            configure(
                level=logging_cfg.get("level", "info"),
                retention_days=logging_cfg.get("retention_days", 1),
                cleanup_old_logs=cleanup_old_logs,
            )
        configure_buffer = getattr(self.app_state, "configure_log_buffer", None)
        if callable(configure_buffer):
            configure_buffer(logging_cfg.get("ui_log_max_display_count", 300))
        if cleanup_old_logs:
            self._invalidate_file_log_cache(limit=logging_cfg.get("ui_log_max_display_count", 300))
        else:
            self._resize_file_log_cache_limit(logging_cfg.get("ui_log_max_display_count", 300))
        set_auto_copy = getattr(self.app_state, "set_auto_copy_trace_on_error", None)
        if callable(set_auto_copy):
            set_auto_copy(bool(logging_cfg.get("auto_copy_trace_on_error", True)))

    def _apply_runtime_setting(self, section: str, key: str, value: Any) -> None:
        if section == "download":
            self._apply_download_runtime_settings()
        elif section == "logging":
            self._apply_logging_runtime_settings(cleanup_old_logs=key == "retention_days")
        elif section == "common":
            self._dispatch_gui_runtime_setting("_apply_common_setting", key, value)
        elif section == "appearance":
            self._dispatch_gui_runtime_setting("_apply_appearance_runtime_settings", key)
        elif section == "playback":
            self._dispatch_gui_runtime_setting("_apply_playback_runtime_settings")

    @safe_slot
    def _on_config_changed(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            return
        section = str(payload.get("section") or "")
        key = str(payload.get("key") or "")
        value = payload.get("value")
        if not section or not key:
            return
        try:
            self._apply_runtime_setting(section, key, value)
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendStateService",
                "config_changed_runtime_apply",
                exc,
                details={"section": section, "key": key},
            )
        if self._platform_auth_config_affects_status(section, key):
            self._invalidate_platform_auth_cache()
        else:
            self._static_snapshot_cache = None
        self.record_event("settings.update", {"section": section, "key": key})

    def _dispatch_gui_runtime_setting(self, method_name: str, *args: Any) -> bool:
        controller = self.controller
        window = getattr(controller, "window", None)
        target = window or controller
        method = getattr(target, method_name, None)
        if not callable(method):
            return False

        def _call() -> None:
            try:
                method(*args)
            except Exception as exc:
                debug_logger.log_exception(
                    "FrontendStateService",
                    method_name,
                    exc,
                    details={"args": list(args)},
                )

        if self._is_qt_gui_thread():
            _call()
        elif callable(getattr(target, "invoke_on_ui_thread", None)):
            target.invoke_on_ui_thread(_call)
        elif self._gui_runtime_invoker is not None:
            self._gui_runtime_invoker.invoke(_call)
        else:
            _call()
        return True

    def _queued_video_ids(self) -> set[str]:
        manager = self._dl_manager()
        queued_video_ids = getattr(manager, "queued_video_ids", None)
        if callable(queued_video_ids):
            return queued_video_ids()
        queue_obj = getattr(manager, "queue", None)
        if queue_obj is None:
            return set()
        snapshot_video_ids = getattr(queue_obj, "snapshot_video_ids", None)
        if callable(snapshot_video_ids):
            return snapshot_video_ids()
        return set()

    def _active_video_ids(self) -> set[str]:
        manager = self._dl_manager()
        prune_finished = getattr(manager, "prune_finished_workers", None)
        if callable(prune_finished):
            prune_finished()
        lock = getattr(manager, "_workers_lock", None)
        if lock is not None:
            with lock:
                workers = list(getattr(manager, "workers", []) or [])
        else:
            workers = list(getattr(manager, "workers", []) or [])
        ids: set[str] = set()
        for worker in workers:
            video = getattr(worker, "video", None)
            video_id = getattr(video, "id", "")
            if video_id:
                ids.add(video_id)
        return ids

    def _bucket_for_item(self, item: VideoItem, *, queued_ids: set[str], active_ids: set[str]) -> str:
        return video_adapter.bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids)

    def _materialize_stage_title_for_event(self, topic: str, payload: Mapping[str, Any]) -> None:
        if str(topic or "") not in {
            "item_found",
            "scan_result",
            "task_started",
            "task_finished",
            "task_error",
            "videos.upsert",
            "videos.update",
            "video_state_changed",
            "task_progress",
        }:
            return
        video_ids = self._event_video_ids(payload)
        if not video_ids:
            return
        queued_ids = self._queued_video_ids()
        active_ids = self._active_video_ids()
        for video_id in video_ids:
            item = self._video_for_update(video_id)
            if item is None:
                continue
            bucket = self._bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids)
            self._ensure_stage_title_snapshot(item, bucket)

    @staticmethod
    def _event_video_ids(payload: Mapping[str, Any]) -> list[str]:
        ids: list[str] = []
        for key in ("video_id", "id", "entity_id"):
            value = payload.get(key)
            if value:
                ids.append(str(value))
        raw_ids = payload.get("video_ids")
        if isinstance(raw_ids, (list, tuple, set)):
            ids.extend(str(value) for value in raw_ids if value)
        elif raw_ids:
            ids.append(str(raw_ids))
        seen: set[str] = set()
        ordered: list[str] = []
        for video_id in ids:
            if video_id in seen:
                continue
            seen.add(video_id)
            ordered.append(video_id)
        return ordered

    def _ensure_stage_title_snapshot(self, item: VideoItem, bucket: str) -> VideoItem:
        stage_key = video_adapter.STAGE_TITLE_KEYS.get(bucket)
        if not stage_key:
            return item
        target = self._video_for_update(str(getattr(item, "id", "") or "")) or item
        if not isinstance(getattr(target, "meta", None), dict):
            target.meta = {}
        meta = target.meta
        previous_stage = str(meta.get(UI_TITLE_STAGE_META_KEY) or "")
        current_title = str(meta.get(stage_key) or "").strip()
        if previous_stage != bucket or not current_title:
            meta[stage_key] = self._build_stage_display_title(target)
            meta[UI_TITLE_STAGE_META_KEY] = bucket
            meta[UI_TITLE_TEMPLATE_META_KEY] = self._current_filename_template()
        if target is not item:
            if not isinstance(getattr(item, "meta", None), dict):
                item.meta = {}
            for key in (stage_key, UI_TITLE_STAGE_META_KEY, UI_TITLE_TEMPLATE_META_KEY):
                if key in meta:
                    item.meta[key] = meta[key]
        return item

    def _build_stage_display_title(self, item: VideoItem) -> str:
        filename = self._render_filename_for_current_template(item)
        return video_adapter.filename_stem(filename) or str(getattr(item, "title", "") or "")

    def _render_filename_for_current_template(self, item: VideoItem) -> str:
        meta = item.meta if isinstance(getattr(item, "meta", None), dict) else {}
        ext = self._stage_filename_extension(item)
        preferred_name = meta.get("preferred_filename") or meta.get("file_name")
        current_name = str(preferred_name or getattr(item, "title", "") or "").strip()
        template = self._current_filename_template()
        raw_name = current_name
        if template and template != CURRENT_FILENAME_TEMPLATE:
            now = datetime.now()
            context = {
                "title": current_name,
                "platform": str(getattr(item, "source", "") or ""),
                "source": str(getattr(item, "source", "") or ""),
                "id": str(getattr(item, "id", "") or ""),
                "date": now.strftime("%Y%m%d"),
                "datetime": now.strftime("%Y%m%d_%H%M%S"),
                "index": str(
                    meta.get("index")
                    or meta.get("sequence")
                    or meta.get("part_index")
                    or ""
                ),
            }

            class _Missing(dict):
                def __missing__(self, key):
                    return ""

            try:
                raw_name = template.format_map(_Missing(context)).strip() or current_name
            except (KeyError, ValueError, IndexError):
                raw_name = current_name
        desc = sanitize_filename(raw_name)
        base_name, current_ext = os.path.splitext(desc)
        safe_name = base_name if current_ext.lower() == ext.lower() else desc
        safe_name = safe_name[:200] or f"{getattr(item, 'source', '')}_{getattr(item, 'id', '')}"
        return f"{safe_name}{ext}"

    def _current_filename_template(self) -> str:
        try:
            template = self.config.get("common", "filename_template", CURRENT_FILENAME_TEMPLATE)
        except Exception:
            template = CURRENT_FILENAME_TEMPLATE
        return str(template or CURRENT_FILENAME_TEMPLATE).strip() or CURRENT_FILENAME_TEMPLATE

    @staticmethod
    def _stage_filename_extension(item: VideoItem) -> str:
        meta = item.meta if isinstance(getattr(item, "meta", None), dict) else {}
        for value in (
            getattr(item, "local_path", ""),
            meta.get("output_filename"),
            meta.get("filename"),
            meta.get("preferred_filename"),
            meta.get("file_name"),
        ):
            _base, ext = os.path.splitext(str(value or "").strip())
            if ext:
                return ext
        return ".mp4"

    def _platform_label(self, item: VideoItem) -> str:
        plugin = registry.get_plugin(item.source)
        return plugin.name if plugin else (item.source or "本地")

    @staticmethod
    def _trace_id(item: VideoItem) -> str:
        return video_adapter.trace_id(item)

    def _queue_status(self, item: VideoItem, queued_ids: set[str]) -> str:
        return video_adapter.queue_status(item, queued_ids)

    def _queue_item(self, item: VideoItem, *, queued_ids: set[str]) -> dict[str, Any]:
        return video_adapter.queue_item(item, queued_ids=queued_ids, platform_label=self._platform_label)

    @staticmethod
    def _queue_subtitle(meta: dict) -> str:
        return video_adapter.queue_subtitle(meta)

    def _active_item(self, item: VideoItem) -> dict[str, Any]:
        return video_adapter.active_item(
            item,
            platform_label=self._platform_label,
            current_save_dir=self._current_save_dir(),
            active_events=self._active_events,
        )

    def _completed_item(self, item: VideoItem) -> dict[str, Any]:
        path = Path(item.local_path) if item.local_path else None
        meta = item.meta or {}
        size_bytes = int(meta.get("size_bytes", 0) or 0)
        stat = self._safe_stat(path) if path is not None else None
        if size_bytes <= 0 and path is not None:
            size_bytes = stat.st_size if stat else 0
        completed_at = str(meta.get("completed_at") or meta.get("mtime") or self._format_mtime(stat))
        metadata, metadata_pending = self._completed_media_metadata(item, path)
        return video_adapter.completed_item(
            item,
            path=path,
            size_bytes=size_bytes,
            completed_at=completed_at,
            metadata=metadata,
            metadata_pending=metadata_pending,
            platform_label=self._platform_label,
        )

    def _completed_media_metadata(self, item: VideoItem, path: Path | None) -> tuple[MediaMetadata, bool]:
        if self._destroyed:
            return MediaMetadata(), False
        meta = item.meta or {}
        if self._has_media_metadata(meta, path):
            return MediaMetadata(), False
        if path is None or not path.exists():
            return MediaMetadata(), False
        failure_key = self._metadata_failure_key(item.id, str(path))
        if self._metadata_empty_retries_exhausted(failure_key):
            return MediaMetadata(), False
        cached = self.media_metadata_service.cached(path)
        if cached is not None:
            self._clear_metadata_empty_failures(item.id, str(path))
            return cached, False
        deferred = getattr(self.media_metadata_service, "is_probe_deferred", None)
        if callable(deferred) and deferred(path):
            return MediaMetadata(), True
        if not self._consume_metadata_probe_budget():
            self._queue_completed_metadata_probe(item.id, str(path))
            return MediaMetadata(), True

        def on_metadata_ready(metadata: MediaMetadata, *, video_id: str = item.id, source_path: str = str(path)) -> None:
            if self._destroyed:
                return
            target = self._video_for_update(video_id)
            if target is None:
                debug_logger.log(
                    component="FrontendStateService",
                    action="metadata_probe_discarded",
                    level="WARN",
                    message="Completed media metadata probe result was discarded because the item no longer exists",
                    details={"video_id": video_id, "source_path": source_path},
                )
                return
            if not self._same_local_path(str(getattr(target, "local_path", "") or ""), source_path):
                debug_logger.log(
                    component="FrontendStateService",
                    action="metadata_probe_discarded",
                    level="WARN",
                    message="Completed media metadata probe result was discarded because the local path changed",
                    details={
                        "video_id": video_id,
                        "source_path": source_path,
                        "current_path": str(getattr(target, "local_path", "") or ""),
                    },
                )
                return
            metadata_payload = {
                "duration": metadata.duration,
                "resolution": metadata.resolution,
                "format": metadata.format,
                "content_type": metadata.content_type,
            }
            has_useful_metadata = bool(metadata.duration or metadata.resolution)
            changed = self._apply_completed_metadata(target, metadata_payload)
            if has_useful_metadata:
                self._clear_metadata_empty_failures(video_id, source_path)
                self._cancel_metadata_retry(video_id)
            else:
                attempts = self._record_metadata_empty_failure(video_id, source_path)
                if not self._metadata_empty_retries_exhausted(self._metadata_failure_key(video_id, source_path)):
                    self._schedule_metadata_retry(video_id, source_path)
            if not has_useful_metadata:
                debug_logger.log(
                    component="FrontendStateService",
                    action="metadata_probe_empty",
                    level="WARN",
                    message="Completed media metadata probe finished without usable duration or resolution",
                    details={
                        "video_id": video_id,
                        "source_path": source_path,
                        "attempts": attempts,
                        "max_retries": self.METADATA_EMPTY_MAX_RETRIES,
                    },
                )
            self._emit_frontend_event(
                "videos.metadata",
                {
                    "video_id": video_id,
                    "metadata": has_useful_metadata,
                    **({"exhausted": True} if not has_useful_metadata and attempts >= self.METADATA_EMPTY_MAX_RETRIES else {}),
                },
            )

        pending = self.media_metadata_service.ensure_probe(path, on_metadata_ready)
        if not pending:
            pending = bool(deferred(path)) if callable(deferred) else False
        if self._metadata_empty_retries_exhausted(failure_key):
            pending = False
        return MediaMetadata(), pending

    def _consume_metadata_probe_budget(self) -> bool:
        budget = self._metadata_probe_budget_remaining
        if budget is None:
            return True
        if budget <= 0:
            return False
        self._metadata_probe_budget_remaining = budget - 1
        return True

    def _queue_completed_metadata_probe(self, video_id: str, source_path: str) -> None:
        if self._destroyed:
            return
        self._metadata_probe_scheduler.queue(video_id, source_path)

    def _drain_queued_metadata_probes(self, generation: int | None = None) -> None:
        self._metadata_probe_scheduler.drain(generation)

    def _drop_metadata_probe_queue_for(self, video_id: str) -> None:
        self._metadata_probe_scheduler.drop_for(video_id)

    def _cancel_metadata_probe_queue(self, *, close: bool = False) -> None:
        self._metadata_probe_scheduler.cancel(close=close)

    @property
    def _metadata_probe_queue(self) -> dict[str, tuple[str, str]]:
        return self._metadata_probe_scheduler.pending

    @property
    def _metadata_probe_queue_timer(self) -> Any | None:
        return self._metadata_probe_scheduler.timer

    @property
    def _metadata_probe_queue_closed(self) -> bool:
        return self._metadata_probe_scheduler.closed

    def update_completed_metadata(
        self,
        video_id: str,
        metadata: Mapping[str, Any] | None,
        *,
        source: str = "",
    ) -> dict[str, Any]:
        if self._destroyed:
            return FrontendActionResult("error", "frontend state service destroyed").to_dict()
        video_id = str(video_id or "")
        if not video_id:
            return FrontendActionResult("error", "missing video id").to_dict()
        item = self._video_for_update(video_id)
        if item is None:
            return FrontendActionResult("error", "completed item not found", {"video_id": video_id}).to_dict()
        normalized = self._normalize_completed_metadata_payload(metadata or {})
        if not any(normalized.values()):
            return FrontendActionResult("ok", "metadata ignored", {"video_id": video_id, "changed": False}).to_dict()
        changed = self._apply_completed_metadata(item, normalized)
        if changed:
            self._emit_frontend_event(
                "videos.metadata",
                {"video_id": video_id, "metadata": True, "source": source or "frontend"},
            )
        return FrontendActionResult(
            "ok",
            "metadata updated" if changed else "metadata unchanged",
            {"video_id": video_id, "changed": changed},
        ).to_dict()

    def _action_update_completed_metadata(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        metadata = dict(payload.get("metadata") or {})
        for key in ("duration", "resolution", "format", "content_type", "duration_ms", "width", "height"):
            if key in payload and key not in metadata:
                metadata[key] = payload[key]
        result = self.update_completed_metadata(video_id, metadata, source=str(payload.get("source") or "web_player"))
        return FrontendActionResult(
            str(result.get("status") or "error"),
            str(result.get("message") or ""),
            dict(result.get("data") or {}),
        )

    def refresh_platform_auth_status(self, *, force: bool = False) -> bool:
        if self._destroyed:
            return False
        should_refresh = bool(force) or self._static_snapshot_cache is None or self._platform_auth_cache_has_expired()
        if not should_refresh:
            return False
        self._platform_auth_force_refresh_once = bool(force)
        self._static_snapshot_cache = None
        self.record_event("settings.platform_auth", {"force": bool(force), "refreshed": True})
        return True

    def _action_refresh_platform_auth_status(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        refreshed = self.refresh_platform_auth_status(force=bool(payload.get("force", False)))
        return FrontendActionResult(
            "ok",
            "平台认证状态已刷新" if refreshed else "",
            {"refreshed": refreshed},
        )
    def _action_log_operation(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        operation = str(payload.get("operation") or payload.get("id") or "").strip()
        try:
            if operation == "refresh":
                self.invalidate_refresh_caches()
                self.record_event("logs.append", {"operation": operation})
                return FrontendActionResult("ok", "日志缓存已刷新")
            if operation == "clear":
                self.app_state.clear_logs()
                self._truncate_latest_debug_log()
                self.invalidate_refresh_caches()
                self.record_event("logs.append", {"operation": operation, "cleared": True})
                return FrontendActionResult("ok", "日志已清空")
            if operation == "export":
                export_path = self._export_latest_debug_log()
                return FrontendActionResult("ok", "日志已导出", {"path": str(export_path)})
            if operation == "open_latest":
                path = Path(debug_logger.latest_file)
                self._open_file_path(path)
                return FrontendActionResult("ok", "已打开 latest_debug.log", {"path": str(path)})
            if operation == "open_error_summary":
                path = Path(debug_logger.latest_error_summary_file)
                self._open_file_path(path)
                return FrontendActionResult("ok", "已打开 latest_error_summary.md", {"path": str(path)})
            return FrontendActionResult("error", f"unknown log operation: {operation}")
        except Exception as exc:
            return FrontendActionResult("error", f"日志操作失败: {exc}", {"operation": operation})

    @staticmethod
    def _truncate_latest_debug_log() -> None:
        file_actions.truncate_latest_debug_log()

    @staticmethod
    def _export_latest_debug_log() -> Path:
        return file_actions.export_latest_debug_log()

    @staticmethod
    def _open_file_path(path: Path) -> None:
        file_actions.open_file_path(path)

    def _normalize_completed_metadata_payload(self, metadata: Mapping[str, Any]) -> dict[str, str]:
        return metadata_rules.normalize_completed_metadata_payload(metadata)

    def _apply_completed_metadata(self, item: VideoItem, metadata: Mapping[str, Any]) -> bool:
        if item.meta is None:
            item.meta = {}
        return metadata_rules.apply_completed_metadata(item.meta, metadata)

    def _emit_frontend_event(self, topic: str, payload: dict[str, Any]) -> None:
        if self._destroyed:
            return
        emitter = self._frontend_event_emitter
        if callable(emitter):
            emitter(topic, payload)
            return
        publisher = getattr(self.app_state, "_publish_change", None)
        if callable(publisher):
            publisher(topic, payload)
            return
        self.record_event(topic, payload)

    def _schedule_metadata_retry(self, video_id: str, source_path: str) -> None:
        if self._destroyed:
            return
        self._metadata_retry_tracker.schedule(video_id, source_path)

    def _cancel_metadata_retry(self, video_id: str) -> None:
        self._metadata_retry_tracker.cancel(video_id)

    def _cancel_all_metadata_retries(self) -> None:
        self._metadata_retry_tracker.cancel_all()

    def _retry_completed_metadata_probe(self, video_id: str, source_path: str) -> bool:
        if self._destroyed:
            return False
        target = self._video_for_update(video_id)
        if target is None:
            return False
        current_path = str(getattr(target, "local_path", "") or "")
        if not self._same_local_path(current_path, source_path):
            return False
        path = Path(source_path)
        if not path.exists():
            return False
        _metadata, pending = self._completed_media_metadata(target, path)
        return bool(pending)

    def _metadata_failure_key(self, video_id: str, source_path: str) -> str:
        return metadata_rules.metadata_failure_key(video_id, source_path)

    def _record_metadata_empty_failure(self, video_id: str, source_path: str) -> int:
        return self._metadata_retry_tracker.record_empty_failure(video_id, source_path)

    def _metadata_empty_retries_exhausted(self, failure_key: str) -> bool:
        return self._metadata_retry_tracker.exhausted(failure_key)

    def _clear_metadata_empty_failures(self, video_id: str | None = None, source_path: str | None = None) -> None:
        self._metadata_retry_tracker.clear_failures(video_id, source_path)

    @classmethod
    def _has_media_metadata(cls, meta: Mapping[str, Any], path: Path | None = None) -> bool:
        return metadata_rules.has_media_metadata(meta, path)

    @staticmethod
    def _has_display_duration(value: Any) -> bool:
        return metadata_rules.has_display_duration(value)

    @classmethod
    def _display_resolution(cls, *values: Any) -> str:
        return video_adapter.display_resolution(*values)

    @staticmethod
    def _is_real_resolution(value: Any) -> bool:
        return video_adapter.is_real_resolution(value)

    @classmethod
    def _same_local_path(cls, left: str, right: str) -> bool:
        return metadata_rules.same_local_path(left, right)

    @staticmethod
    def _normalize_local_path(value: str) -> str:
        return metadata_rules.normalize_local_path(value)

    @staticmethod
    def _display_duration(value: Any) -> str:
        return video_adapter.display_duration(value)

    @staticmethod
    def _format_completed_at_table(value: str) -> str:
        return video_adapter.format_completed_at_table(value)

    def _failed_item(
        self,
        item: VideoItem,
        *,
        log_excerpt_index: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        item_trace_id = self._trace_id(item)
        log_excerpt_items = self._failed_log_excerpt_items(item, item_trace_id, log_excerpt_index)
        return video_adapter.failed_item(
            item,
            platform_label=self._platform_label,
            log_excerpt_items=log_excerpt_items,
            failed_at_fallback=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    @staticmethod
    def _safe_stat(path: Path | None):
        if not path:
            return None
        try:
            return path.stat()
        except OSError:
            return None

    @staticmethod
    def _format_mtime(stat) -> str:
        if not stat:
            return "--"
        return datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        return video_adapter.format_size(size_bytes)

    @staticmethod
    def _format_from_path(path: Path | None) -> str:
        return video_adapter.format_from_path(path)

    @staticmethod
    def _content_type_from_path(path: Path | None) -> str:
        return video_adapter.content_type_from_path(path)

    @staticmethod
    def _default_speed_trend(progress: int) -> list[float]:
        return video_adapter.default_speed_trend(progress)

    def _active_events(
        self,
        item: VideoItem,
        *,
        progress: int,
        chunks_done: int,
        chunks_total: int,
        speed: str,
        remaining_time: str,
        write_status: str,
        merge_status: str,
        trace_id: str,
    ) -> list[dict[str, str]]:
        return video_adapter.active_events(
            item,
            progress=progress,
            chunks_done=chunks_done,
            chunks_total=chunks_total,
            speed=speed,
            remaining_time=remaining_time,
            write_status=write_status,
            merge_status=merge_status,
            trace_id=trace_id,
            event_time_cache=self._active_event_time_cache,
        )

    def _stable_active_event_time(self, item: VideoItem, existing: list[dict[str, str]]) -> str:
        return video_adapter.stable_active_event_time(
            item,
            existing,
            event_time_cache=self._active_event_time_cache,
        )

    @staticmethod
    def _format_event_clock(value: Any) -> str:
        return video_adapter.format_event_clock(value)

    @staticmethod
    def _default_active_events(item: VideoItem) -> list[dict[str, str]]:
        return video_adapter.default_active_events(item)

    def _solutions_for_reason(self, reason: str) -> list[dict[str, str]]:
        return video_adapter.solutions_for_reason(reason)

    @staticmethod
    def _failure_category(reason: str) -> dict[str, str]:
        return video_adapter.failure_category(reason)

    @classmethod
    def _format_failed_at_table(cls, value: str) -> str:
        return cls._format_completed_at_table(value)

    def log_items(self) -> list[dict[str, Any]]:
        buffer = self.app_state.get_log_buffer()
        merged = self._file_log_cache_store.merged_items(buffer)
        return [self._enrich_log_item(item) for item in merged]

    def _ui_log_display_limit(self) -> int:
        try:
            raw_value = self.config.get("logging", "ui_log_max_display_count", 300)
            limit = int(raw_value)
        except (TypeError, ValueError, AttributeError):
            limit = 300
        return max(100, min(limit, 5000))

    @staticmethod
    def _file_log_cache_key(limit: int) -> str:
        return FrontendLogCache.cache_key(limit)

    def _invalidate_file_log_cache(self, *, limit: Any | None = None) -> None:
        self._file_log_cache_store.invalidate(limit=limit)

    def _resize_file_log_cache_limit(self, limit: Any) -> None:
        self._file_log_cache_store.resize_limit(limit)

    def _read_log_items(self, *, limit: int) -> list[dict[str, Any]]:
        try:
            from app.debug_logger import debug_logger

            latest_file = Path(debug_logger.latest_file)
        except Exception:
            return []
        return log_adapter.parse_debug_log_file(latest_file, limit=limit)

    def _enrich_log_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        return log_adapter.enrich_log_item(item)

    def _log_excerpt_index(self) -> dict[str, list[dict[str, Any]]]:
        return log_adapter.build_log_excerpt_index(self.log_items())

    def _log_excerpt(self, trace_id: str) -> list[str]:
        if not trace_id:
            return []
        return [entry["message"] for entry in self._log_excerpt_index().get(trace_id, [])[-8:]]

    def _failed_log_excerpt_items(
        self,
        item: VideoItem,
        trace_id: str,
        log_excerpt_index: dict[str, list[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]]:
        index = log_excerpt_index if log_excerpt_index is not None else self._log_excerpt_index()
        return log_adapter.failed_log_excerpt_items(
            item,
            trace_id=trace_id,
            index=index,
            platform_label=self._platform_label,
            trace_id_for_item=self._trace_id,
        )

    def _fallback_failed_log_entries(
        self,
        item: VideoItem,
        index: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        return log_adapter.fallback_failed_log_entries(
            item,
            index,
            platform_label=self._platform_label,
            trace_id_for_item=self._trace_id,
        )

    def _platform_auth_snapshot(
        self,
        plugin_id: str,
        auth_cfg: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> dict[str, str]:
        plugin_key = str(plugin_id or "").strip().lower()
        signature = self._platform_auth_signature(plugin_key, auth_cfg)
        now = time.monotonic()
        cached = self._platform_auth_cache.get(plugin_key)
        if (
            not force
            and cached
            and cached.get("signature") == signature
            and now < float(cached.get("expires_at") or 0)
        ):
            return dict(cached.get("value") or {})
        value = settings_adapter.platform_auth_snapshot(plugin_key, auth_cfg)
        self._platform_auth_cache[plugin_key] = {
            "signature": signature,
            "expires_at": now + float(self.PLATFORM_AUTH_REFRESH_TTL_SECONDS),
            "value": dict(value),
        }
        return dict(value)

    def _platform_auth_signature(self, plugin_id: str, auth_cfg: Mapping[str, Any]) -> tuple[Any, ...]:
        requirement = settings_adapter.PLATFORM_AUTH_REQUIREMENTS.get(str(plugin_id or "").strip().lower())
        if not requirement:
            return (plugin_id, "no-rule")
        file_key, _cookie_names = requirement
        raw_path = str(auth_cfg.get(file_key) or "").strip()
        if not raw_path:
            return (plugin_id, file_key, "")
        path = Path(raw_path).expanduser()
        try:
            normalized_path = str(path.resolve(strict=False)).casefold()
        except OSError:
            normalized_path = str(path).replace("\\", "/").casefold()
        try:
            stat = path.stat()
        except OSError:
            return (plugin_id, file_key, normalized_path, False, 0, 0)
        return (plugin_id, file_key, normalized_path, True, int(stat.st_mtime_ns), int(stat.st_size))

    def _platform_auth_cache_has_expired(self) -> bool:
        if not self._platform_auth_cache:
            return False
        now = time.monotonic()
        return any(now >= float(entry.get("expires_at") or 0) for entry in self._platform_auth_cache.values())

    @staticmethod
    def _platform_auth_config_affects_status(section: str, key: str) -> bool:
        normalized_section = str(section or "").strip().lower()
        normalized_key = str(key or "").strip().lower()
        return normalized_section == "auth" or "cookie" in normalized_key

    def _invalidate_platform_auth_cache(self) -> None:
        self._platform_auth_cache.clear()
        self._static_snapshot_cache = None

    @staticmethod
    def _count_label(value: Any, unit: str) -> str:
        return settings_adapter.count_label(value, unit)

    @classmethod
    def _platform_count_contract(cls, plugin_id: str, section: Mapping[str, Any]) -> dict[str, Any]:
        return settings_adapter.platform_count_contract(plugin_id, section)

    @staticmethod
    def _platform_proxy_contract(plugin_id: str, section: Mapping[str, Any]) -> dict[str, Any]:
        return settings_adapter.platform_proxy_contract(plugin_id, section)

    @classmethod
    def _platform_timeout_contract(cls, section: Mapping[str, Any]) -> dict[str, Any]:
        return settings_adapter.platform_timeout_contract(section)

    def settings_snapshot(self) -> dict[str, Any]:
        force_auth = bool(self._platform_auth_force_refresh_once)
        try:
            return settings_adapter.build_settings_snapshot(
                self.config.data,
                self.download_options_snapshot(),
                auth_status_provider=lambda plugin_id, auth_cfg: self._platform_auth_snapshot(
                    plugin_id,
                    auth_cfg,
                    force=force_auth,
                ),
            )
        finally:
            self._platform_auth_force_refresh_once = False

    @staticmethod
    def toolbox_items() -> list[dict[str, str]]:
        return toolbox_adapter.toolbox_items()

    @staticmethod
    def toolbox_recent_items() -> list[dict[str, str]]:
        return toolbox_adapter.toolbox_recent_items()

    def download_options_snapshot(self) -> dict[str, Any]:
        return settings_adapter.build_download_options_snapshot(
            self.config.get,
            self.cache_service.get,
            self._dl_manager(),
        )

    def app_status(
        self,
        *,
        queue_count: int | None = None,
        active_count: int | None = None,
        completed_count: int | None = None,
        failed_count: int | None = None,
        active_downloads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            from cli import __version__
        except Exception:
            __version__ = "3.6.14"

        if any(value is None for value in (queue_count, active_count, completed_count, failed_count)):
            counts = self._video_bucket_counts()
            if queue_count is None:
                queue_count = counts["queue"]
            if active_count is None:
                active_count = counts["active"]
            if completed_count is None:
                completed_count = counts["completed"]
            if failed_count is None:
                failed_count = counts["failed"]
        running = self._is_running()
        if active_downloads is None:
            if running:
                partial = self._build_video_sections(shallow=True, only=frozenset({"active_downloads"}))
                active_downloads = list(partial.get("active_downloads") or [])
            else:
                active_downloads = []
        return status_adapter.build_app_status(
            running=running,
            running_state=self._running_state,
            queue_count=int(queue_count or 0),
            active_count=int(active_count or 0),
            completed_count=int(completed_count or 0),
            failed_count=int(failed_count or 0),
            active_downloads=active_downloads,
            version=__version__,
        )

    def _video_bucket_counts(self) -> dict[str, int]:
        queued_ids = self._queued_video_ids()
        active_ids = self._active_video_ids()
        counts = {"queue": 0, "active": 0, "completed": 0, "failed": 0}
        for item in self._videos(shallow=True).values():
            bucket = self._bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids)
            if bucket in counts:
                counts[bucket] += 1
        return counts

    @staticmethod
    def _format_transfer_speed(bps: int) -> str:
        return status_adapter.format_transfer_speed(bps)

    @staticmethod
    def _parse_speed_string(value: str | None) -> int:
        return status_adapter.parse_speed_string(value)

    def _is_running(self) -> bool:
        controller = self.controller
        lock = getattr(controller, "_lifecycle_lock", None)
        if lock is not None:
            with lock:
                spider = getattr(controller, "current_spider", None)
        else:
            spider = getattr(controller, "current_spider", None)
        if spider is not None:
            try:
                if spider.isRunning():
                    return True
            except (RuntimeError, AttributeError) as exc:
                debug_logger.log_exception(
                    "FrontendStateService",
                    "spider_running_state_check",
                    exc,
                    details={"spider_type": type(spider).__name__},
                )
        manager = self._dl_manager()
        if manager is None:
            return False
        lock = getattr(manager, "_workers_lock", None)
        if lock is not None:
            with lock:
                workers = list(getattr(manager, "workers", []) or [])
        else:
            workers = list(getattr(manager, "workers", []) or [])
        return len(workers) > 0

    @staticmethod
    def _aggregate_speed(active_downloads: list[dict[str, Any]]) -> str:
        return status_adapter.aggregate_speed(active_downloads)

    def _action_delete_item(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        if not video_id:
            return FrontendActionResult("error", "missing video id")
        controller = self.controller
        outcome = None
        if controller is not None and hasattr(controller, "delete_video"):
            outcome = controller.delete_video(video_id)
        elif controller is not None and hasattr(controller, "_delete_video_sync"):
            outcome = controller._delete_video_sync(video_id)
        else:
            self.remove_video(video_id)
        result = self._delete_action_result_from_outcome(video_id, outcome)
        if result is not None:
            return result
        return FrontendActionResult("ok", "deleted", {"video_id": video_id})

    @staticmethod
    def _delete_action_result_from_outcome(
        video_id: str,
        outcome: Any,
    ) -> FrontendActionResult | None:
        if outcome is None:
            return None
        if isinstance(outcome, Mapping):
            status = str(outcome.get("status") or "")
            message = str(outcome.get("message") or "")
            data = dict(outcome.get("data") or {})
        else:
            status = str(getattr(outcome, "status", "") or "")
            message = str(getattr(outcome, "error", None) or "")
            data = {"video_id": video_id}
            if hasattr(outcome, "deleted"):
                data["deleted"] = bool(getattr(outcome, "deleted", False))
            if status == "missing":
                data["missing"] = True
        if not status:
            return None
        if status == "error":
            return FrontendActionResult("error", message or "delete failed", data or {"video_id": video_id})
        if status == "missing":
            return FrontendActionResult(
                "ok",
                message or "already deleted",
                data or {"video_id": video_id, "missing": True},
            )
        if status == "ok":
            return FrontendActionResult("ok", message or "deleted", data or {"video_id": video_id})
        return FrontendActionResult("error", message or f"delete failed: {status}", data or {"video_id": video_id})

    def _action_clear_queue(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        del payload
        queue_ids = sorted(self.queue_item_ids())
        clear_queue = getattr(self.controller, "on_clear_queue", None)
        if callable(clear_queue):
            clear_queue()
        else:
            controller_videos = getattr(self.controller, "videos", None)
            if isinstance(controller_videos, dict):
                for video_id in queue_ids:
                    controller_videos.pop(video_id, None)
            for video_id in queue_ids:
                self.remove_video(video_id)
        if queue_ids:
            self._emit_frontend_event(
                "videos.clear_queue",
                {"video_ids": queue_ids, "count": len(queue_ids)},
            )
        return FrontendActionResult("ok", "queue cleared", {"count": len(queue_ids), "video_ids": queue_ids})

    def _action_pause_download(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        if not video_id:
            return FrontendActionResult("error", "missing video id")
        manager = self._dl_manager()
        cancel_task = getattr(manager, "cancel_task", None)
        if not callable(cancel_task):
            return FrontendActionResult("error", "download manager is unavailable")
        result = cancel_task(video_id)
        if result is None:
            return FrontendActionResult("error", "download task not found", {"video_id": video_id})
        item = self._video_for_update(video_id)
        if item is not None:
            item.status = VideoStatus.PENDING.label
            item.meta["frontend_status"] = "待下载"
            item.meta["user_cancel_requested"] = True
            app_state = getattr(self, "app_state", None)
            if app_state is not None:
                app_state._publish_change(
                    "videos.update",
                    {"video_id": video_id, "scope": result},
                )
        return FrontendActionResult("ok", "download paused", {"video_id": video_id, "scope": result})

    def _action_update_download_options(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        options = settings_adapter.normalize_download_options_payload(
            payload,
            self.config.get,
            self.cache_service.get,
        )
        manager = self._dl_manager()
        options["max_concurrent"] = settings_adapter.apply_manager_concurrency(
            manager,
            options["max_concurrent"],
        )
        settings_adapter.persist_download_options(
            self.config.set,
            self.cache_service.set,
            options,
        )
        if callable(getattr(manager, "set_runtime_options", None)):
            try:
                self._apply_runtime_setting("download", "download_options", None)
            except Exception as exc:
                debug_logger.log_exception(
                    "FrontendStateService",
                    "apply_download_options",
                    exc,
                    details={
                        "max_concurrent": options["max_concurrent"],
                        "max_retries": options["max_retries"],
                        "video_only": options["video_only"],
                        "image_respects_concurrency": options["image_respects_concurrency"],
                    },
                )
                return FrontendActionResult("error", f"download options persisted but runtime apply failed: {exc}")
        self._static_snapshot_cache = None
        self.record_event(
            "settings.update",
            {
                "section": "download",
                "max_concurrent": options["max_concurrent"],
                "video_only": options["video_only"],
                "image_respects_concurrency": options["image_respects_concurrency"],
                "download_options": True,
            },
        )
        return FrontendActionResult("ok", "download options updated", options)

    def _action_update_setting(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        section = str(payload.get("section") or payload.get("group") or "").strip()
        key = str(payload.get("key") or payload.get("name") or "").strip()
        value = payload.get("value")
        if section == "basic":
            section = "common"
        if section == "appearance" and key == "theme":
            section = "common"
        if not section or not key:
            return FrontendActionResult("error", "setting section and key are required")
        if section == "common":
            return self._action_update_basic_setting({"key": key, "value": value})
        if section == "download" and key in {"max_concurrent", "max_retries", "video_only", "image_respects_concurrency"}:
            options = self.download_options_snapshot()
            options[key] = value
            return self._action_update_download_options(options)
        section_models = getattr(self.config, "SECTION_MODELS", {})
        if section not in section_models:
            return FrontendActionResult("error", f"unknown setting section: {section}")
        try:
            if section == "missav" and key in {"proxy_app", "proxy_url"}:
                proxy_text = str(value or "").strip()
                proxy_url = (
                    str(self.config.get("missav", "proxy_url", "") or "").strip()
                    if key == "proxy_app" and proxy_text == "自定义"
                    else build_missav_proxy_url(proxy_text)
                )
                proxy_app = proxy_text if key == "proxy_app" else "自定义"
                updater = getattr(self.config, "update_missav_proxy", None)
                if callable(updater):
                    updater(proxy_app or "自定义", proxy_url)
                else:
                    self.config.set("missav", key, value)
                    if key == "proxy_app":
                        self.config.set("missav", "proxy_url", proxy_url)
                    elif key == "proxy_url":
                        self.config.set("missav", "proxy_app", "自定义")
                current_value = self.config.get("missav", key)
                self._static_snapshot_cache = None
                self.record_event("settings.update", {"section": section, "key": key})
                return FrontendActionResult(
                    "ok",
                    "setting updated",
                    {"section": section, "key": key, "value": current_value, "proxy_url": proxy_url},
                )
            self.config.set(section, key, value)
            current_value = self.config.get(section, key)
            self._apply_runtime_setting(section, key, current_value)
        except ConfigValidationError as exc:
            return FrontendActionResult("error", str(exc), {"section": section, "key": key})
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendStateService",
                "apply_runtime_setting",
                exc,
                details={"section": section, "key": key},
            )
            return FrontendActionResult(
                "error",
                f"setting persisted but runtime apply failed: {exc}",
                {"section": section, "key": key},
            )
        if self._platform_auth_config_affects_status(section, key):
            self._invalidate_platform_auth_cache()
        else:
            self._static_snapshot_cache = None
        self.record_event("settings.update", {"section": section, "key": key})
        return FrontendActionResult(
            "ok",
            "setting updated",
            {"section": section, "key": key, "value": current_value},
        )

    def _action_retry_failed(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        item = self._video_for_update(video_id)
        manager = self._dl_manager()
        if not item or manager is None:
            return FrontendActionResult("error", "task cannot be retried")
        item.status = VideoStatus.PENDING.label
        item.progress = 0
        manager.add_task(item, self._current_save_dir())
        return FrontendActionResult("ok", "retry queued", {"video_id": video_id})

    def _action_copy_diagnostics(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        item = self._videos().get(video_id)
        if not item:
            return FrontendActionResult("error", "task not found")
        trace_id = self._trace_id(item)
        if not trace_id:
            return FrontendActionResult("error", "trace id not found", {"video_id": video_id})
        return FrontendActionResult("ok", "trace id ready", {"text": trace_id, "trace_id": trace_id})

    def _action_update_basic_setting(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        key = str(payload.get("key") or payload.get("name") or "").strip()
        value = payload.get("value")
        aliases = {"download_directory": "save_directory", "save_directory": "save_directory"}
        config_key = aliases.get(key, key)
        allowed = {"save_directory", "filename_template", "open_after_download", "default_open_mode", "theme"}
        if config_key not in allowed:
            return FrontendActionResult("error", f"unknown basic setting: {key}")
        if config_key == "save_directory" and value is None:
            value = payload.get("directory")
        try:
            self.config.set("common", config_key, value)
            current_value = self.config.get("common", config_key)
            self._apply_runtime_setting("common", config_key, current_value)
        except ConfigValidationError as exc:
            return FrontendActionResult("error", str(exc), {"key": key or config_key})
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendStateService",
                "apply_basic_runtime_setting",
                exc,
                details={"key": config_key},
            )
            return FrontendActionResult(
                "error",
                f"setting persisted but runtime apply failed: {exc}",
                {"key": key or config_key},
            )
        controller = self.controller
        if config_key == "save_directory" and controller is not None and hasattr(controller, "current_save_dir"):
            controller.current_save_dir = str(current_value)
        self._static_snapshot_cache = None
        self.record_event("settings.update", {"section": "common", "key": config_key})
        data = {"section": "common", "key": key or config_key, "config_key": config_key, "value": current_value}
        if config_key == "save_directory":
            data["directory"] = current_value
        return FrontendActionResult("ok", "basic setting updated", data)

    def _action_change_directory(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        return self._action_update_basic_setting({
            "key": "download_directory",
            "value": payload.get("directory"),
        })

    def _action_open_directory(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        item = self._videos().get(video_id)
        file_path = getattr(item, "local_path", "") if item else ""
        if not file_path:
            return FrontendActionResult("error", "file path is unavailable")
        directory_path = Path(file_path).expanduser().parent
        if not directory_path.exists():
            return FrontendActionResult("error", "directory does not exist", {"directory": str(directory_path)})
        directory = str(directory_path)
        try:
            self._directory_opener(directory)
        except Exception as exc:
            return FrontendActionResult("error", str(exc), {"directory": directory})
        return FrontendActionResult("ok", "directory opened", {"directory": directory})

    def _action_open_file(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        item = self._videos().get(video_id)
        file_path = getattr(item, "local_path", "") if item else ""
        if not file_path:
            return FrontendActionResult("error", "file path is unavailable")
        path = Path(file_path).expanduser()
        if not path.exists():
            return FrontendActionResult("error", "file does not exist", {"path": str(path)})
        try:
            self._open_file_path(path)
        except Exception as exc:
            return FrontendActionResult("error", str(exc), {"path": str(path)})
        return FrontendActionResult("ok", "file opened", {"path": str(path)})

    def _action_run_tool(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "")
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        if tool_id not in toolbox_adapter.valid_tool_ids():
            return FrontendActionResult("error", "unknown tool", {"tool_id": tool_id})
        return FrontendActionResult("ok", "tool queued", {"tool_id": tool_id})

    def _action_register_file_associations(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        include_video = bool(payload.get("include_video", True))
        include_image = bool(payload.get("include_image", True))
        if not include_video and not include_image:
            return FrontendActionResult("error", "no file type selected")
        try:
            service = self._make_association_service()
            result = service.register_current_user(
                self._executable_path_provider(),
                include_video=include_video,
                include_image=include_image,
            )
            if not getattr(result, "registered", False):
                return FrontendActionResult("error", getattr(result, "message", "") or "file association registration failed")

            default_result = service.set_current_user_defaults(include_video=include_video, include_image=include_image)
            diagnostics = service.diagnose_current_user(include_video=include_video, include_image=include_image)
            pending = tuple(getattr(diagnostics, "pending_extensions", ()) or ())
            opened_settings = False
            if getattr(diagnostics, "available", False) and pending:
                opened_settings = bool(service.open_default_apps_settings())

            failed = tuple(getattr(default_result, "failed_extensions", ()) or ())
            defaulted = tuple(getattr(default_result, "defaulted_extensions", ()) or ())
            if pending:
                message = "default apps settings opened" if opened_settings else "manual default app confirmation required"
            elif failed:
                message = "some defaults failed"
            elif defaulted:
                message = "default file associations applied"
            else:
                message = getattr(default_result, "message", "") or "file association action completed"
            return FrontendActionResult(
                "ok",
                message,
                {
                    "defaulted_extensions": list(defaulted),
                    "failed_extensions": list(failed),
                    "pending_extensions": list(pending),
                    "opened_settings": opened_settings,
                },
            )
        except Exception as exc:
            return FrontendActionResult("error", str(exc))

    def _make_association_service(self) -> Any:
        if self._association_service_factory is not None:
            return self._association_service_factory()
        from app.services.windows_file_association_service import WindowsFileAssociationService

        return WindowsFileAssociationService()

    @staticmethod
    def _open_directory_with_system(directory: str) -> None:
        file_actions.open_directory_with_system(directory)

    @staticmethod
    def _current_executable_path() -> str:
        return file_actions.current_executable_path()

    def _current_save_dir(self) -> str:
        controller_dir = getattr(self.controller, "current_save_dir", "")
        if controller_dir:
            return str(controller_dir)
        host = getattr(self.controller, "host", None)
        host_dir = getattr(host, "current_save_dir", "")
        if host_dir:
            return str(host_dir)
        return str(self.config.get("common", "save_directory", "downloads"))

    @classmethod
    def mock_snapshot(cls) -> dict[str, Any]:
        from app.services.frontend_mock_snapshot import build_mock_snapshot

        temp_service = cls()
        try:
            return build_mock_snapshot(
                temp_service.settings_snapshot,
                cls._settings_contract_payload,
            )
        finally:
            temp_service.destroy()
