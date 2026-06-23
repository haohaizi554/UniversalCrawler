"""Unified frontend state adapter for GUI and WebUI.

This service is intentionally transport-agnostic.  GUI widgets and the Web
static app should consume the same snapshot shape instead of reading spiders,
downloaders, parsers, or task builders directly.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from copy import deepcopy
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import cfg
from app.debug_logger import debug_logger
from app.core.plugin_registry import registry
from app.core.state import VideoStatus, parse_video_status
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.cache_service import CacheService
from app.services.frontend_event_aggregator import (
    ALL_FRONTEND_SECTIONS,
    VIDEO_SECTIONS,
    FrontendEventAggregator,
    sections_for_topic,
)
from app.services.icon_registry import icon_manifest, tool_icon_file
from app.services.media_metadata_service import MediaMetadata, MediaMetadataService
from app.utils.runtime_paths import user_data_root

QUEUE_STATUSES = ("待解析", "解析中", "已解析", "排队中", "已存在", "待下载")

PAGE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"id": "queue", "title": "下载队列"},
    {"id": "active", "title": "正在下载"},
    {"id": "completed", "title": "已完成"},
    {"id": "failed", "title": "失败列表"},
    {"id": "logs", "title": "日志中心"},
    {"id": "settings", "title": "配置中心"},
    {"id": "toolbox", "title": "工具箱"},
)

TOOLBOX_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "link_parser",
        "title": "链接解析",
        "summary": "解析网页或文本中的链接，提取视频、图片等资源地址",
        "input_example": "https://www.douyin.com/user/MS4wLjABAAAA...",
        "output_example": "解析出视频、图片、作者主页等可下载资源地址",
        "icon": "link",
    },
    {
        "id": "batch_rename",
        "title": "批量重命名",
        "summary": "按规则、序号和预览结果批量重命名本地文件",
        "input_example": "D:\\Videos\\*.mp4 + {platform}_{title}_{index}",
        "output_example": "生成可预览、可回滚的批量重命名方案",
        "icon": "rename",
    },
    {
        "id": "cover_extract",
        "title": "封面提取",
        "summary": "从视频文件中提取封面图片，支持单个或批量提取",
        "input_example": "选择本地视频文件或下载完成列表",
        "output_example": "导出 JPG/PNG 封面图并写入文件信息",
        "icon": "image",
    },
    {
        "id": "video_to_audio",
        "title": "视频转音频",
        "summary": "将视频文件转换为音频，支持多种格式和质量设置",
        "input_example": "MP4/MKV/WebM 视频文件",
        "output_example": "输出 MP3/AAC/WAV 音频文件",
        "icon": "music",
    },
    {
        "id": "dedupe_scan",
        "title": "本地去重扫描",
        "summary": "扫描并查找重复文件，支持按内容或文件名去重",
        "input_example": "选择下载目录或任意本地目录",
        "output_example": "生成重复文件分组和可清理建议",
        "icon": "search",
    },
    {
        "id": "metadata_viewer",
        "title": "元数据查看",
        "summary": "查看视频、音频和图片文件的详细元数据",
        "input_example": "本地视频、音频、图片文件",
        "output_example": "展示编码、分辨率、时长、码率和容器信息",
        "icon": "metadata",
    },
    {
        "id": "format_convert",
        "title": "格式转换",
        "summary": "转换视频、音频和图片文件格式",
        "input_example": "选择源文件和目标格式",
        "output_example": "输出转换后的媒体文件并保留来源记录",
        "icon": "convert",
    },
    {
        "id": "file_verify",
        "title": "文件校验",
        "summary": "计算并校验文件哈希值，支持 MD5、SHA1、SHA256",
        "input_example": "选择一个或多个本地文件",
        "output_example": "输出 MD5、SHA1、SHA256 校验值",
        "icon": "shield",
    },
)

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

    LOG_ENTRY_RE = re.compile(
        r"^\[(?P<time>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+(?P<source>[^/]+?)\s*/\s*(?P<action>.+)$"
    )
    METADATA_PROBES_PER_SNAPSHOT = 64

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
        self.app_state = app_state or AppState()
        self.cache_service = cache_service or self.app_state.cache_service
        self._directory_opener = directory_opener or self._open_directory_with_system
        self._association_service_factory = association_service_factory
        self._executable_path_provider = executable_path_provider or self._current_executable_path
        self.media_metadata_service = media_metadata_service or MediaMetadataService()
        self._frontend_event_emitter = frontend_event_emitter
        self._file_log_cache: list[dict[str, Any]] = []
        self._file_log_cache_at = 0.0
        self._file_log_cache_ttl_seconds = 1.0
        self._file_log_cache_lock = threading.RLock()
        self._running_state = "空闲中"
        self._static_snapshot_cache: dict[str, Any] | None = None
        self._delta_lock = threading.RLock()
        self._event_aggregator = FrontendEventAggregator()
        self._active_event_time_cache: dict[str, str] = {}
        self._metadata_retry_lock = threading.RLock()
        self._metadata_retry_timers: dict[str, threading.Timer] = {}
        self._metadata_probe_budget_remaining: int | None = None
        self._app_state_event_handler = self.app_state.event_bus.subscribe(
            "app_state.changed",
            self._record_app_state_change,
        )

    def bind_controller(self, controller: Any) -> None:
        self.controller = controller
        snapshot = getattr(controller, "_video_items_snapshot", None)
        if callable(snapshot):
            self.app_state.replace_videos(snapshot())
            return
        snapshot_videos = getattr(self.app_state, "snapshot_videos", None)
        if callable(snapshot_videos):
            self.app_state.replace_videos(snapshot_videos())

    def set_frontend_event_emitter(self, emitter: Callable[[str, dict[str, Any]], None] | None) -> None:
        self._frontend_event_emitter = emitter

    def set_running(self, is_running: bool) -> None:
        self._running_state = "运行中" if is_running else "空闲中"
        self.app_state.set_running_state(self._running_state)

    def record_log(self, message: str, *, level: str = "INFO", source: str = "GUI", trace_id: str = "") -> None:
        self.app_state.record_log(message, level=level, source=source, trace_id=trace_id)

    def upsert_video(self, item: VideoItem) -> None:
        self.app_state.upsert_video(item)

    def remove_video(self, video_id: str) -> None:
        self._active_event_time_cache.pop(str(video_id), None)
        self._cancel_metadata_retry(str(video_id))
        self.app_state.remove_video(video_id)

    def clear_videos(self) -> None:
        self.app_state.clear_videos()

    def invalidate_refresh_caches(self) -> None:
        with self._file_log_cache_lock:
            self._file_log_cache_at = 0.0
        self.cache_service.delete("frontend.file_log_cache")
        self._static_snapshot_cache = None
        self._active_event_time_cache.clear()
        self._cancel_all_metadata_retries()
        self._event_aggregator.reset()

    @property
    def frontend_version(self) -> int:
        return self._event_aggregator.version

    def frontend_metrics(self) -> dict[str, Any]:
        return self._event_aggregator.metrics()

    def record_event(self, topic: str, payload: Mapping[str, Any] | None = None) -> None:
        normalized = str(topic or "")
        payload_dict = dict(payload or {})
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
        if not isinstance(payload, dict):
            self._event_aggregator.record("app_state.changed", {})
            return
        topic = str(payload.get("topic") or "app_state.changed")
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
        return None

    def _static_snapshot_parts(self) -> dict[str, Any]:
        if self._static_snapshot_cache is None:
            self._static_snapshot_cache = {
                "pages": list(PAGE_DEFINITIONS),
                "settings_snapshot": self.settings_snapshot(),
                "toolbox_items": self.toolbox_items(),
                "toolbox_recent_items": self.toolbox_recent_items(),
                "icon_manifest": icon_manifest(),
            }
        parts = dict(self._static_snapshot_cache)
        parts["download_options"] = self.download_options_snapshot()
        return parts

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
        log_excerpt_index: dict[str, list[dict[str, Any]]] | None = None

        want_failed = only is None or "failed_items" in only
        want_completed = only is None or "completed_items" in only
        if want_failed:
            log_excerpt_index = self._log_excerpt_index()

        previous_probe_budget = self._metadata_probe_budget_remaining
        if want_completed:
            self._metadata_probe_budget_remaining = self.METADATA_PROBES_PER_SNAPSHOT
        try:
            for item in videos.values():
                bucket = self._bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids)
                if bucket == "active":
                    if only is None or "active_downloads" in only:
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
            count_completed = only is None or "completed_items" in only
            count_failed = only is None or "failed_items" in only
            include_active = only is None or "active_downloads" in only
            sections["app_status"] = self.app_status(
                completed_count=len(completed_items) if count_completed else None,
                failed_count=len(failed_items) if count_failed else None,
                active_downloads=active_downloads if include_active else None,
            )
        return sections

    def get_snapshot(self, *, mock: bool = False, sections: frozenset[str] | None = None) -> dict[str, Any]:
        if mock:
            snapshot = self.mock_snapshot()
            snapshot["version"] = self.frontend_version
            return snapshot

        static_keys = frozenset({"pages", "icon_manifest", "toolbox_items", "toolbox_recent_items", "settings_snapshot", "download_options"})
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
            requested_sections = frozenset(sections) if sections is not None else dirty.changed_sections
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
                "deleted_ids": list(dirty.deleted_ids),
                "events": list(dirty.pending_events)[-200:],
                "priority": dirty.priority.name.lower(),
                "metrics": self.frontend_metrics(),
            }

    def handle_action(self, action: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        handler = {
            "delete_item": self._action_delete_item,
            "pause_download": self._action_pause_download,
            "retry_failed": self._action_retry_failed,
            "copy_diagnostics": self._action_copy_diagnostics,
            "change_directory": self._action_change_directory,
            "open_directory": self._action_open_directory,
            "run_tool": self._action_run_tool,
            "register_file_associations": self._action_register_file_associations,
            "update_download_options": self._action_update_download_options,
            "update_completed_metadata": self._action_update_completed_metadata,
            "log_operation": self._action_log_operation,
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
            return getattr(controller, "_dl_manager", None)
        return getattr(controller, "dl_manager", None)

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
        parsed = parse_video_status(item.status)
        if parsed in {VideoStatus.COMPLETED, VideoStatus.LOCAL}:
            return "completed"
        if parsed in {VideoStatus.FAILED, VideoStatus.TIMED_OUT}:
            return "failed"
        if item.id in active_ids or parsed == VideoStatus.DOWNLOADING:
            return "active"
        if item.progress >= 100 and item.local_path:
            return "completed"
        if item.id in queued_ids or parsed == VideoStatus.PENDING:
            return "queue"
        return "queue"

    def _platform_label(self, item: VideoItem) -> str:
        plugin = registry.get_plugin(item.source)
        return plugin.name if plugin else (item.source or "本地")

    @staticmethod
    def _trace_id(item: VideoItem) -> str:
        return str((item.meta or {}).get("trace_id") or "")

    def _queue_status(self, item: VideoItem, queued_ids: set[str]) -> str:
        meta = item.meta or {}
        parsed = parse_video_status(item.status)
        if parsed == VideoStatus.LOCAL:
            return "本地"
        if meta.get("frontend_status") in QUEUE_STATUSES:
            return str(meta["frontend_status"])
        if meta.get("already_exists"):
            return "已存在"
        if item.id in queued_ids:
            return "排队中"
        raw = str(item.status or "")
        if "解析" in raw:
            return "已解析"
        if "等待" in raw:
            return "待下载"
        return "待解析" if not item.url else "待下载"

    def _queue_item(self, item: VideoItem, *, queued_ids: set[str]) -> dict[str, Any]:
        meta = item.meta or {}
        return {
            "id": item.id,
            "title": item.title,
            "subtitle": self._queue_subtitle(meta),
            "platform": self._platform_label(item),
            "platform_id": item.source,
            "status": self._queue_status(item, queued_ids),
            "source_url": item.url,
            "trace_id": self._trace_id(item),
            "created_at": str(meta.get("created_at") or meta.get("discovered_at") or meta.get("added_at") or ""),
            "actions": ["delete"],
        }

    @staticmethod
    def _queue_subtitle(meta: dict) -> str:
        raw = str(meta.get("created_at") or meta.get("discovered_at") or meta.get("added_at") or "").strip()
        if not raw:
            return ""
        return raw.replace("T", " ")[:19]

    def _active_item(self, item: VideoItem) -> dict[str, Any]:
        meta = item.meta or {}
        progress = int(item.progress or 0)
        chunks_done = int(meta.get("chunks_done", 0) or 0)
        chunks_total = int(meta.get("chunks_total", 0) or 0)
        if chunks_total <= 0:
            chunks_total = 100
            chunks_done = progress
        path = Path(item.local_path) if item.local_path else None
        save_dir = str(meta.get("save_dir") or meta.get("download_dir") or (path.parent if path is not None else self._current_save_dir()))
        output_filename = str(meta.get("output_filename") or meta.get("filename") or (path.name if path is not None else item.title))
        speed = str(meta.get("speed") or "0 B/s")
        remaining_time = str(meta.get("remaining_time") or meta.get("eta") or "--")
        trace_id = self._trace_id(item)
        write_status = str(meta.get("write_status") or "\u7b49\u5f85\u5199\u5165")
        merge_status = str(meta.get("merge_status") or "\u7b49\u5f85\u5408\u5e76")
        return {
            "id": item.id,
            "title": item.title,
            "platform": self._platform_label(item),
            "platform_id": item.source,
            "progress": progress,
            "save_dir": save_dir,
            "output_filename": output_filename,
            "speed": speed,
            "speed_bps": int(meta.get("speed_bps") or 0),
            "bytes_downloaded": int(meta.get("bytes_downloaded", 0) or 0),
            "bytes_total": int(meta.get("bytes_total", 0) or 0),
            "eta_seconds": meta.get("eta_seconds"),
            "eta": str(meta.get("eta") or "--"),
            "remaining_time": remaining_time,
            "trace_id": trace_id,
            "thread_count": int(meta.get("thread_count", meta.get("threads", 1)) or 1),
            "retry_count": int(meta.get("retry_count", 0) or 0),
            "write_status": write_status,
            "merge_status": merge_status,
            "source_url": item.url,
            "chunk_progress": {
                "completed": chunks_done,
                "total": chunks_total,
                "percent": progress,
            },
            "speed_trend": list(meta.get("speed_trend") or self._default_speed_trend(progress)),
            "events": self._active_events(
                item,
                progress=progress,
                chunks_done=chunks_done,
                chunks_total=chunks_total,
                speed=speed,
                remaining_time=remaining_time,
                write_status=write_status,
                merge_status=merge_status,
                trace_id=trace_id,
            ),
            "actions": ["delete"],
        }

    def _completed_item(self, item: VideoItem) -> dict[str, Any]:
        path = Path(item.local_path) if item.local_path else None
        meta = item.meta or {}
        size_bytes = int(meta.get("size_bytes", 0) or 0)
        stat = self._safe_stat(path) if path is not None else None
        if size_bytes <= 0 and path is not None:
            size_bytes = stat.st_size if stat else 0
        completed_at = str(meta.get("completed_at") or meta.get("mtime") or self._format_mtime(stat))
        metadata, metadata_pending = self._completed_media_metadata(item, path)
        duration = self._display_duration(meta.get("duration") or metadata.duration)
        resolution = self._display_resolution(meta.get("resolution"), meta.get("quality"), metadata.resolution)
        pending_label = "\u68c0\u6d4b\u4e2d"
        format_label = str(meta.get("format") or metadata.format or self._format_from_path(path))
        content_type = str(meta.get("content_type") or metadata.content_type or self._content_type_from_path(path))
        filename = str(meta.get("filename") or (path.name if path else "") or item.title)
        save_dir = str(meta.get("save_dir") or (path.parent if path else ""))
        return {
            "id": item.id,
            "title": item.title,
            "thumbnail": str(meta.get("thumbnail") or ""),
            "completed_at": completed_at,
            "completed_at_table": self._format_completed_at_table(completed_at),
            "duration": duration or (pending_label if metadata_pending else "--"),
            "resolution": resolution if resolution != "--" else (pending_label if metadata_pending else "--"),
            "size": self._format_size(size_bytes),
            "size_bytes": size_bytes,
            "format": format_label,
            "filename": filename,
            "save_dir": save_dir,
            "download_speed": str(meta.get("speed") or "--"),
            "download_speed_bps": int(meta.get("speed_bps") or 0),
            "local_path": item.local_path or "",
            "content_type": content_type,
            "metadata_pending": metadata_pending,
            "platform": self._platform_label(item),
            "actions": ["play", "open_directory", "delete"],
        }

    def _completed_media_metadata(self, item: VideoItem, path: Path | None) -> tuple[MediaMetadata, bool]:
        meta = item.meta or {}
        if self._has_media_metadata(meta, path):
            return MediaMetadata(), False
        if path is None or not path.exists():
            return MediaMetadata(), False
        cached = self.media_metadata_service.cached(path)
        if cached is not None:
            return cached, False
        deferred = getattr(self.media_metadata_service, "is_probe_deferred", None)
        if callable(deferred) and deferred(path):
            return MediaMetadata(), True
        if not self._consume_metadata_probe_budget():
            return MediaMetadata(), True

        def on_metadata_ready(metadata: MediaMetadata, *, video_id: str = item.id, source_path: str = str(path)) -> None:
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
                self._cancel_metadata_retry(video_id)
            else:
                self._schedule_metadata_retry(video_id)
            if not has_useful_metadata:
                debug_logger.log(
                    component="FrontendStateService",
                    action="metadata_probe_empty",
                    level="WARN",
                    message="Completed media metadata probe finished without usable duration or resolution",
                    details={"video_id": video_id, "source_path": source_path},
                )
            self._emit_frontend_event(
                "videos.metadata",
                {"video_id": video_id, "metadata": has_useful_metadata},
            )

        pending = self.media_metadata_service.ensure_probe(path, on_metadata_ready)
        if not pending:
            pending = bool(deferred(path)) if callable(deferred) else False
        return MediaMetadata(), pending

    def _consume_metadata_probe_budget(self) -> bool:
        budget = self._metadata_probe_budget_remaining
        if budget is None:
            return True
        if budget <= 0:
            return False
        self._metadata_probe_budget_remaining = budget - 1
        return True

    def update_completed_metadata(
        self,
        video_id: str,
        metadata: Mapping[str, Any] | None,
        *,
        source: str = "",
    ) -> dict[str, Any]:
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
        try:
            Path(debug_logger.latest_file).write_text("", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _export_latest_debug_log() -> Path:
        source = Path(debug_logger.latest_file)
        export_dir = user_data_root() / "Exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"latest_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        if source.exists():
            shutil.copyfile(source, target)
        else:
            target.write_text("", encoding="utf-8")
        return target

    @staticmethod
    def _open_file_path(path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(str(path))
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        import subprocess

        subprocess.Popen(["xdg-open", str(path)])

    def _normalize_completed_metadata_payload(self, metadata: Mapping[str, Any]) -> dict[str, str]:
        duration = self._display_duration(metadata.get("duration"))
        if not duration:
            try:
                duration_ms = float(metadata.get("duration_ms") or 0)
            except (TypeError, ValueError):
                duration_ms = 0
            if duration_ms > 0:
                duration = MediaMetadataService.format_duration(duration_ms / 1000)
        if not duration:
            duration = self._display_duration(metadata.get("duration_seconds"))
        resolution = str(metadata.get("resolution") or "").strip()
        if not self._is_real_resolution(resolution):
            try:
                width = int(float(metadata.get("width") or 0))
                height = int(float(metadata.get("height") or 0))
            except (TypeError, ValueError):
                width = height = 0
            resolution = f"{width} x {height}" if width > 0 and height > 0 else ""
        return {
            "duration": duration,
            "resolution": resolution if self._is_real_resolution(resolution) else "",
            "format": str(metadata.get("format") or "").strip(),
            "content_type": str(metadata.get("content_type") or "").strip(),
        }

    def _apply_completed_metadata(self, item: VideoItem, metadata: Mapping[str, Any]) -> bool:
        changed = False
        if item.meta is None:
            item.meta = {}
        for key, value in metadata.items():
            value_text = str(value or "").strip()
            if not value_text:
                continue
            current = str(item.meta.get(key) or "").strip()
            if key == "resolution":
                should_update = self._is_real_resolution(value_text) and not self._is_real_resolution(current)
            elif key == "duration":
                should_update = self._has_display_duration(value_text) and not self._has_display_duration(current)
            else:
                should_update = current in {"", "--"}
            if should_update:
                item.meta[key] = value_text
                changed = True
        return changed

    def _emit_frontend_event(self, topic: str, payload: dict[str, Any]) -> None:
        emitter = self._frontend_event_emitter
        if callable(emitter):
            emitter(topic, payload)
            return
        publisher = getattr(self.app_state, "_publish_change", None)
        if callable(publisher):
            publisher(topic, payload)
            return
        self.record_event(topic, payload)

    def _schedule_metadata_retry(self, video_id: str) -> None:
        key = str(video_id or "")
        if not key:
            return
        delay = float(getattr(self.media_metadata_service, "EMPTY_RETRY_SECONDS", 30.0) or 30.0)
        delay = max(1.0, min(delay, 60.0)) + 0.25
        with self._metadata_retry_lock:
            if key in self._metadata_retry_timers:
                return

            def fire() -> None:
                with self._metadata_retry_lock:
                    self._metadata_retry_timers.pop(key, None)
                self._emit_frontend_event("videos.metadata", {"video_id": key, "metadata": False, "retry": True})

            timer = threading.Timer(delay, fire)
            timer.daemon = True
            self._metadata_retry_timers[key] = timer
            timer.start()

    def _cancel_metadata_retry(self, video_id: str) -> None:
        key = str(video_id or "")
        if not key:
            return
        with self._metadata_retry_lock:
            timer = self._metadata_retry_timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    def _cancel_all_metadata_retries(self) -> None:
        with self._metadata_retry_lock:
            timers = list(self._metadata_retry_timers.values())
            self._metadata_retry_timers.clear()
        for timer in timers:
            timer.cancel()

    @classmethod
    def _has_media_metadata(cls, meta: Mapping[str, Any], path: Path | None = None) -> bool:
        resolution = str(meta.get("resolution") or meta.get("quality") or "").strip()
        content_type = str(meta.get("content_type") or "").strip().lower()
        is_image = content_type == "image" or (
            path is not None and path.suffix.lower() in MediaMetadataService.IMAGE_EXTENSIONS
        )
        if is_image:
            return cls._is_real_resolution(resolution)
        return cls._has_display_duration(meta.get("duration")) and cls._is_real_resolution(resolution)

    @staticmethod
    def _has_display_duration(value: Any) -> bool:
        text = str(value or "").strip()
        if text in {"", "--", "00:00:00"}:
            return False
        return True

    @classmethod
    def _display_resolution(cls, *values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if cls._is_real_resolution(text):
                return text
        return "--"

    @staticmethod
    def _is_real_resolution(value: Any) -> bool:
        return bool(re.match(r"^\d{2,5}\s*x\s*\d{2,5}$", str(value or "").strip(), flags=re.IGNORECASE))

    @classmethod
    def _same_local_path(cls, left: str, right: str) -> bool:
        normalized_left = cls._normalize_local_path(left)
        normalized_right = cls._normalize_local_path(right)
        return bool(normalized_left and normalized_right and normalized_left == normalized_right)

    @staticmethod
    def _normalize_local_path(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            resolved = Path(text).expanduser().resolve(strict=False)
            normalized = str(resolved)
        except (OSError, RuntimeError, ValueError):
            normalized = os.path.abspath(os.path.normpath(text))
        return os.path.normcase(os.path.normpath(normalized)).replace("\\", "/")

    @staticmethod
    def _display_duration(value: Any) -> str:
        if isinstance(value, (int, float)):
            return MediaMetadataService.format_duration(value)
        text = str(value or "").strip()
        if not text or text == "--":
            return ""
        if text.isdigit():
            return MediaMetadataService.format_duration(text)
        return text

    @staticmethod
    def _format_completed_at_table(value: str) -> str:
        text = str(value or "").strip().replace("T", " ")
        if not text or text == "--":
            return text or "--"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt).strftime("%m-%d %H:%M")
            except ValueError:
                pass
        if len(text) >= 16 and text[4:5] in {"-", "/"}:
            return text[5:16]
        return text

    def _failed_item(
        self,
        item: VideoItem,
        *,
        log_excerpt_index: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        meta = item.meta or {}
        reason = str(meta.get("download_error") or meta.get("error") or item.status or "未知错误")
        trace_id = self._trace_id(item)
        category = self._failure_category(reason)
        log_excerpt_items = self._failed_log_excerpt_items(item, trace_id, log_excerpt_index)
        failed_at = str(meta.get("failed_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return {
            "id": item.id,
            "title": item.title,
            "failed_at": failed_at,
            "failed_at_table": self._format_failed_at_table(failed_at),
            "reason": reason,
            "reason_detail": reason,
            "reason_label": category["label"],
            "reason_category": category["key"],
            "reason_icon_file": category["icon_file"],
            "status": "失败",
            "status_label": "失败",
            "status_icon_file": "status_failed.png",
            "trace_id": trace_id,
            "platform": self._platform_label(item),
            "platform_id": item.source,
            "source_url": item.url,
            "log_excerpt": [entry["message"] for entry in log_excerpt_items],
            "log_excerpt_items": log_excerpt_items,
            "solutions": self._solutions_for_reason(reason),
            "actions": ["copy_diagnostics", "delete"],
        }

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
        size = float(max(size_bytes, 0))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return "0 B"

    @staticmethod
    def _format_from_path(path: Path | None) -> str:
        if not path or not path.suffix:
            return "--"
        return path.suffix.lstrip(".").upper()

    @staticmethod
    def _content_type_from_path(path: Path | None) -> str:
        if not path:
            return ""
        return "image" if path.suffix.lower() in MediaMetadataService.IMAGE_EXTENSIONS else "video"

    @staticmethod
    def _default_speed_trend(progress: int) -> list[float]:
        seed = max(0, min(100, progress)) / 100
        return [round((0.7 + ((index % 5) * 0.12)) * seed, 2) for index in range(12)]

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
        existing: list[dict[str, str]] = []
        for event in list((item.meta or {}).get("events") or [])[-6:]:
            if not isinstance(event, Mapping):
                continue
            message = str(event.get("message") or "").strip()
            if not message:
                continue
            existing.append({"time": str(event.get("time") or ""), "message": message})
        event_time = self._stable_active_event_time(item, existing)
        for event in existing:
            if not event["time"]:
                event["time"] = event_time
        if len(existing) >= 6:
            return existing[-6:]

        chunk_text = f"{progress}%"
        if chunks_total:
            chunk_text = f"{progress}% ({chunks_done}/{chunks_total})"
        derived = [
            f"\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668\uff1a{item.title}",
            f"\u8fdb\u5ea6\uff1a{chunk_text}",
            f"\u5f53\u524d\u901f\u5ea6\uff1a{speed}\uff0c\u5269\u4f59\uff1a{remaining_time}",
        ]
        if trace_id:
            derived.append(f"Trace ID\uff1a{trace_id}")
        elif item.url:
            derived.append("\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55")
        derived.extend(
            [
                f"\u5199\u5165\u72b6\u6001\uff1a{write_status}",
                f"\u5408\u5e76\u72b6\u6001\uff1a{merge_status}",
            ]
        )

        seen = {event["message"] for event in existing}
        result = list(existing)
        for message in derived:
            if message in seen:
                continue
            result.append({"time": event_time, "message": message})
            seen.add(message)
            if len(result) >= 6:
                break
        return result[:6]

    def _stable_active_event_time(self, item: VideoItem, existing: list[dict[str, str]]) -> str:
        for event in existing:
            value = str(event.get("time") or "").strip()
            if value:
                return value
        meta = item.meta or {}
        for key in ("event_time", "download_started_at", "started_at", "created_at", "discovered_at", "added_at"):
            formatted = self._format_event_clock(meta.get(key))
            if formatted:
                self._active_event_time_cache[item.id] = formatted
                return formatted
        cached = self._active_event_time_cache.get(item.id)
        if cached:
            return cached
        generated = datetime.now().strftime("%H:%M:%S")
        self._active_event_time_cache[item.id] = generated
        return generated

    @staticmethod
    def _format_event_clock(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%H:%M:%S")
        raw = str(value).strip()
        if not raw:
            return ""
        if len(raw) >= 8 and raw[-8:].count(":") == 2:
            return raw[-8:]
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M:%S")
        except ValueError:
            return raw

    @staticmethod
    def _default_active_events(item: VideoItem) -> list[dict[str, str]]:
        now = datetime.now().strftime("%H:%M:%S")
        return [
            {"time": now, "message": f"\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668\uff1a{item.title}"},
            {"time": now, "message": "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6"},
            {"time": now, "message": "\u8fdb\u5ea6\uff1a0%"},
            {"time": now, "message": "\u5f53\u524d\u901f\u5ea6\uff1a0 B/s"},
        ]

    def _solutions_for_reason(self, reason: str) -> list[dict[str, str]]:
        lowered = reason.lower()
        if "login" in lowered or "登录" in reason:
            return [
                {"title": "确认登录态", "description": "部分内容需要登录后才能访问，请检查平台认证状态。", "icon_file": "action_user.png"},
                {"title": "重新获取链接", "description": "登录后重新复制分享链接并重试任务。", "icon_file": "action_trace_link.png"},
            ]
        if "timeout" in lowered or "超时" in reason:
            return [
                {"title": "检查网络", "description": "确认网络连接正常，或尝试切换网络环境后重试。", "icon_file": "status_network_warning.png"},
                {"title": "增加超时时间", "description": "在配置中心提高请求超时和重试次数。", "icon_file": "status_timeout.png"},
            ]
        if any(token in lowered for token in ("connection", "network", "403", "404", "forbidden")) or any(token in reason for token in ("连接", "网络", "拒绝", "失效")):
            return [
                {"title": "重新获取链接", "description": "请重新复制最新的分享链接并重试任务。", "icon_file": "action_trace_link.png"},
                {"title": "检查网络", "description": "确认代理、DNS 和网络环境正常，必要时切换网络后重试。", "icon_file": "status_network_warning.png"},
            ]
        if any(token in lowered for token in ("permission", "occupied", "file")) or any(token in reason for token in ("占用", "权限", "文件")):
            return [
                {"title": "释放文件占用", "description": "关闭正在播放或占用目标文件的程序后重试。", "icon_file": "status_locked.png"},
                {"title": "更改目录", "description": "尝试切换到有写入权限的保存目录。", "icon_file": "action_open_directory.png"},
            ]
        return [
            {"title": "重新获取链接", "description": "请重新复制最新的分享链接并重试任务。", "icon_file": "action_trace_link.png"},
            {"title": "查看 Trace ID", "description": "在日志中心按 Trace ID 过滤，定位同一任务的上下游日志。", "icon_file": "action_search.png"},
        ]

    @staticmethod
    def _failure_category(reason: str) -> dict[str, str]:
        lowered = str(reason or "").lower()
        if "login" in lowered or "登录" in reason:
            return {"key": "login", "label": "需要登录", "icon_file": "action_user.png"}
        if "timeout" in lowered or "超时" in reason:
            return {"key": "timeout", "label": "网络超时", "icon_file": "status_timeout.png"}
        if any(token in lowered for token in ("connection", "network", "403", "404", "forbidden", "ssl", "proxy")) or any(
            token in reason for token in ("连接", "网络", "拒绝", "失效", "链接")
        ):
            return {"key": "link", "label": "链接失败", "icon_file": "action_trace_link.png"}
        if any(token in lowered for token in ("permission", "occupied", "file")) or any(token in reason for token in ("占用", "权限", "文件")):
            return {"key": "file", "label": "文件占用", "icon_file": "status_locked.png"}
        if any(token in lowered for token in ("parse", "parser", "extract", "decode")) or any(token in reason for token in ("解析", "提取")):
            return {"key": "parse", "label": "解析失败", "icon_file": "action_code.png"}
        if any(token in lowered for token in ("ffmpeg", "m3u8", "external", "tool")) or any(token in reason for token in ("外部工具", "合并")):
            return {"key": "tool", "label": "工具异常", "icon_file": "action_repair.png"}
        return {"key": "unknown", "label": "任务失败", "icon_file": "status_error_warning.png"}

    @classmethod
    def _format_failed_at_table(cls, value: str) -> str:
        return cls._format_completed_at_table(value)

    def log_items(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        needs_refresh = False
        with self._file_log_cache_lock:
            needs_refresh = now - self._file_log_cache_at >= self._file_log_cache_ttl_seconds
        if needs_refresh:
            cached = self.cache_service.get("frontend.file_log_cache")
            if cached is None:
                cached = self._read_log_items(limit=300)
                self.cache_service.set(
                    "frontend.file_log_cache",
                    cached,
                    ttl_seconds=self._file_log_cache_ttl_seconds,
                    persist=False,
                )
            with self._file_log_cache_lock:
                self._file_log_cache = deepcopy(cached)
                self._file_log_cache_at = time.monotonic()
        buffer = self.app_state.get_log_buffer()
        with self._file_log_cache_lock:
            file_log_cache = deepcopy(self._file_log_cache)
        merged = [*file_log_cache, *buffer][-300:]
        return [self._enrich_log_item(item) for item in merged]

    def _read_log_items(self, *, limit: int) -> list[dict[str, Any]]:
        try:
            from app.debug_logger import debug_logger

            latest_file = Path(debug_logger.latest_file)
        except Exception:
            return []
        if not latest_file.exists():
            return []
        try:
            lines = latest_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        detail_lines: list[str] = []
        for line in lines:
            match = self.LOG_ENTRY_RE.match(line.strip())
            if match:
                if current is not None:
                    current["detail"] = "\n".join(detail_lines).strip()
                    items.append(current)
                current = {
                    "time": match.group("time"),
                    "level": self._normalize_log_level(match.group("level")),
                    "source": match.group("source").strip(),
                    "thread": "",
                    "trace_id": "",
                    "message_summary": match.group("action").strip(),
                    "message": "",
                    "detail": "",
                    "stack": "",
                }
                detail_lines = []
                continue
            if current is None:
                continue
            stripped = line.strip()
            if stripped.startswith("说明:"):
                current["message"] = stripped.replace("说明:", "", 1).strip()
                current["message_summary"] = current["message"][:120]
            elif self._looks_like_trace_line(stripped):
                current["trace_id"] = self._parse_trace_line(stripped)
            detail_lines.append(line)

        if current is not None:
            current["detail"] = "\n".join(detail_lines).strip()
            items.append(current)
        return items[-limit:]

    def _enrich_log_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        enriched = dict(item or {})
        enriched["level"] = self._normalize_log_level(str(enriched.get("level") or "INFO"))
        enriched["trace_id"] = str(enriched.get("trace_id") or self._trace_from_log_detail(enriched) or "")
        enriched["platform"] = str(enriched.get("platform") or self._platform_from_log(enriched) or "系统")
        enriched["category"] = self._log_category(enriched)
        enriched["timestamp_ms"] = self._log_timestamp_ms(str(enriched.get("time") or ""))
        if not enriched.get("message_summary"):
            enriched["message_summary"] = str(enriched.get("message") or "")[:120]
        return enriched

    @staticmethod
    def _trace_from_log_detail(item: Mapping[str, Any]) -> str:
        text = "\n".join(
            str(item.get(key) or "")
            for key in ("detail", "message", "message_summary")
        )
        for pattern in (
            r"(?:trace_id|Trace ID|追踪ID)\s*[:：]\s*([A-Za-z0-9_.:-]+)",
            r"-\s*trace_id\s*[:：]\s*([A-Za-z0-9_.:-]+)",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(",;")
        return ""

    @staticmethod
    def _platform_from_log(item: Mapping[str, Any]) -> str:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("trace_id", "source", "message", "message_summary", "detail")
        ).lower()
        mapping = (
            ("bilibili", "Bilibili"),
            ("bili", "Bilibili"),
            ("douyin", "抖音"),
            ("dy_", "抖音"),
            ("kuaishou", "快手"),
            ("ks_", "快手"),
            ("missav", "MissAV"),
            ("xhs", "小红书"),
            ("xiaohongshu", "小红书"),
        )
        for token, label in mapping:
            if token in text:
                return label
        return ""

    @classmethod
    def _log_category(cls, item: Mapping[str, Any]) -> str:
        level = str(item.get("level") or "").upper()
        if level == "ERROR":
            return "error"
        source = str(item.get("source") or "")
        platform = str(item.get("platform") or "")
        message = str(item.get("message") or item.get("message_summary") or "")
        text = f"{source} {platform} {message}".lower()
        if any(token in text for token in ("download", "下载", "bilibili", "douyin", "kuaishou", "missav", "小红书", "抖音", "快手")):
            return "download"
        return "system"

    @staticmethod
    def _log_timestamp_ms(value: str) -> int:
        text = str(value or "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return int(datetime.strptime(text, fmt).timestamp() * 1000)
            except ValueError:
                continue
        return 0

    @staticmethod
    def _normalize_log_level(level: str) -> str:
        normalized = level.upper()
        if normalized == "COMMAND":
            return "INFO"
        return normalized

    @staticmethod
    def _looks_like_trace_line(line: str) -> bool:
        lowered = str(line or "").strip().lower()
        return lowered.startswith((
            "追踪id:",
            "追踪id：",
            "trace id:",
            "trace id：",
            "trace_id:",
            "trace_id：",
            "- trace_id:",
            "- trace_id：",
            "- trace id:",
            "- trace id：",
        ))

    @staticmethod
    def _parse_trace_line(line: str) -> str:
        text = str(line or "").strip()
        if text.startswith("-"):
            text = text[1:].strip()
        for delimiter in (":", "："):
            if delimiter in text:
                return text.split(delimiter, 1)[1].strip()
        return ""

    def _log_excerpt_index(self) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}
        fallback_key = "__recent_errors__"
        for item in self.log_items():
            trace_id = str(item.get("trace_id") or "")
            message = str(item.get("message_summary") or item.get("message") or "")
            if not message:
                continue
            entry = {
                "time": str(item.get("time") or "")[-8:],
                "level": self._normalize_log_level(str(item.get("level") or "INFO")),
                "source": str(item.get("source") or ""),
                "trace_id": trace_id,
                "message": message,
                "icon_file": self._log_level_icon_file(str(item.get("level") or "INFO")),
            }
            if trace_id:
                index.setdefault(trace_id, []).append(entry)
            if entry["level"] in {"ERROR", "WARN", "WARNING"}:
                index.setdefault(fallback_key, []).append(entry)
        return index

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
        entries = list(index.get(trace_id, [])) if trace_id else []
        if not entries:
            entries = self._fallback_failed_log_entries(item, index)
        return entries[-8:]

    def _fallback_failed_log_entries(
        self,
        item: VideoItem,
        index: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        meta = item.meta or {}
        title = str(item.title or "").strip()
        reason = str(meta.get("download_error") or meta.get("error") or item.status or "").strip()
        needles = [part for part in (title[:24], reason[:32], item.source or "") if part]
        matched: list[dict[str, Any]] = []
        for entries in index.values():
            for entry in entries:
                message = str(entry.get("message") or "")
                if any(needle and needle in message for needle in needles):
                    matched.append(entry)
        if matched:
            return matched[-8:]
        fallback = list(index.get("__recent_errors__", []))
        if fallback:
            return fallback[-8:]
        reason_text = reason or "任务失败，暂无可匹配日志片段"
        return [
            {
                "time": str(meta.get("failed_at") or "")[-8:],
                "level": "ERROR",
                "source": self._platform_label(item),
                "trace_id": self._trace_id(item),
                "message": reason_text,
                "icon_file": "log_level_error.png",
            }
        ]

    @staticmethod
    def _log_level_icon_file(level: str) -> str:
        normalized = str(level or "").upper()
        if normalized in {"WARN", "WARNING"}:
            return "log_level_warn.png"
        if normalized == "ERROR":
            return "log_level_error.png"
        return "log_level_info.png"

    def settings_snapshot(self) -> dict[str, Any]:
        data = self.config.data
        download_options = self.download_options_snapshot()
        platforms = []
        for plugin in registry.get_all_plugins():
            section = data.get(plugin.id, {})
            platforms.append(
                {
                    "id": plugin.id,
                    "name": plugin.name,
                    "auth_status": "已认证" if plugin.id in {"douyin", "bilibili"} else "未认证",
                    "default_count": section.get("max_items") or section.get("max_pages") or 20,
                    "proxy": section.get("proxy_app") or section.get("proxy_url") or "系统代理",
                }
            )
        return {
            "基础设置": {
                "download_directory": data.get("common", {}).get("save_directory", ""),
                "filename_template": "{platform}_{title}_{date}_{index}",
                "open_after_download": True,
                "default_open_mode": "系统默认播放器",
            },
            "下载设置": {
                "max_concurrent": download_options["max_concurrent"],
                "request_timeout": data.get("download", {}).get("request_timeout", 60),
                "max_retries": download_options["max_retries"],
                "resume_enabled": True,
                "speed_limit_kb": 0,
                "video_only": False,
            },
            "平台设置": platforms,
            "播放设置": {
                "default_player": "内置播放器",
                "remember_position": True,
                "hardware_acceleration": True,
                "autoplay_next": True,
                "manual_image_switch": True,
            },
            "日志设置": {
                "retention_days": 30,
                "level": "信息",
                "auto_copy_trace_on_error": True,
                "cleanup_old_logs_on_start": False,
            },
            "外观设置": {
                "follow_system": False,
                "theme": data.get("common", {}).get("theme", "light"),
                "accent": "#0078d4",
                "scale": "100%",
                "font_size": "中",
            },
        }

    @staticmethod
    def toolbox_items() -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for item in TOOLBOX_DEFINITIONS:
            entry = dict(item)
            entry["icon_file"] = tool_icon_file(entry.get("icon", ""))
            items.append(entry)
        return items

    @staticmethod
    def toolbox_recent_items() -> list[dict[str, str]]:
        return [
            {"id": "link_parser", "title": "链接解析", "last_used": "今天 18:24"},
            {"id": "video_to_audio", "title": "视频转音频", "last_used": "今天 17:35"},
            {"id": "metadata_viewer", "title": "元数据查看", "last_used": "今天 14:10"},
        ]

    def download_options_snapshot(self) -> dict[str, Any]:
        try:
            configured_concurrent = int(self.config.get("download", "max_concurrent", 3))
        except (TypeError, ValueError):
            configured_concurrent = 3
        manager = self._dl_manager()
        try:
            effective_concurrent = int(getattr(manager, "max_concurrent", configured_concurrent) or configured_concurrent)
        except (TypeError, ValueError):
            effective_concurrent = configured_concurrent
        try:
            max_retries = int(self.config.get("download", "max_retries", 3))
        except (TypeError, ValueError):
            max_retries = 3
        auto_retry = bool(self.cache_service.get("download.auto_retry", True))
        return {
            "auto_retry": auto_retry,
            "max_retries": max(1, min(max_retries, 10)),
            "max_concurrent": max(1, min(effective_concurrent, 8)),
        }

    def app_status(
        self,
        *,
        completed_count: int | None = None,
        failed_count: int | None = None,
        active_downloads: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            from cli import __version__
        except Exception:
            __version__ = "1.0.0"

        videos = self._videos()
        if completed_count is None:
            completed_count = sum(1 for item in videos.values() if self._bucket_for_item(item, queued_ids=set(), active_ids=set()) == "completed")
        if failed_count is None:
            failed_count = sum(1 for item in videos.values() if self._bucket_for_item(item, queued_ids=set(), active_ids=set()) == "failed")
        running = self._is_running()
        if active_downloads is None:
            if running:
                partial = self._build_video_sections(shallow=True, only=frozenset({"active_downloads"}))
                active_downloads = list(partial.get("active_downloads") or [])
            else:
                active_downloads = []
        speed_bps = sum(int(item.get("speed_bps") or 0) for item in active_downloads)
        if speed_bps <= 0 and active_downloads:
            speed_bps = sum(self._parse_speed_string(str(item.get("speed") or "")) for item in active_downloads)
        indicator = "running" if running else ("error" if (failed_count or 0) > 0 else "idle")
        return {
            "running_state": "运行中" if running else self._running_state,
            "status_indicator": indicator,
            "download_speed": self._format_transfer_speed(speed_bps),
            "download_speed_bps": speed_bps,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "version": f"v{__version__}",
        }

    @staticmethod
    def _format_transfer_speed(bps: int) -> str:
        if bps <= 0:
            return "0 B/s"
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = float(bps)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        if index == 0:
            return f"{int(value)} {units[index]}"
        return f"{value:.1f} {units[index]}"

    @staticmethod
    def _parse_speed_string(value: str | None) -> int:
        text = str(value or "").strip().upper()
        if not text or text.startswith("0"):
            return 0
        parts = text.split()
        if len(parts) < 2:
            return 0
        try:
            amount = float(parts[0])
        except ValueError:
            return 0
        unit = parts[1].replace("/S", "/s")
        multipliers = {
            "B/s": 1,
            "KB/s": 1024,
            "MB/s": 1024**2,
            "GB/s": 1024**3,
        }
        return int(amount * multipliers.get(unit, 1))

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
            except Exception:
                pass
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
        if not active_downloads:
            return "0 B/s"
        total_bps = 0
        for item in active_downloads:
            speed_bps = item.get("speed_bps")
            if speed_bps:
                total_bps += int(speed_bps)
                continue
            total_bps += FrontendStateService._parse_speed_string(str(item.get("speed") or ""))
        return FrontendStateService._format_transfer_speed(total_bps)

    def _action_delete_item(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        video_id = str(payload.get("id") or payload.get("video_id") or "")
        if not video_id:
            return FrontendActionResult("error", "missing video id")
        controller = self.controller
        if controller is not None and hasattr(controller, "delete_video"):
            controller.delete_video(video_id)
        elif controller is not None and hasattr(controller, "_delete_video_sync"):
            controller._delete_video_sync(video_id)
        else:
            self.remove_video(video_id)
        return FrontendActionResult("ok", "deleted", {"video_id": video_id})

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
        data = dict(payload or {})
        try:
            max_concurrent = int(data.get("max_concurrent") or self.config.get("download", "max_concurrent", 3))
        except (TypeError, ValueError):
            max_concurrent = 3
        max_concurrent = max(1, min(max_concurrent, 8))
        try:
            max_retries = int(data.get("max_retries") or self.config.get("download", "max_retries", 3))
        except (TypeError, ValueError):
            max_retries = 3
        max_retries = max(1, min(max_retries, 10))
        auto_retry = bool(data.get("auto_retry", self.cache_service.get("download.auto_retry", True)))
        self.cache_service.set("download.auto_retry", auto_retry, persist=False)
        manager = self._dl_manager()
        setter = getattr(manager, "set_max_concurrent", None)
        if callable(setter):
            try:
                max_concurrent = int(setter(max_concurrent))
            except (TypeError, ValueError):
                max_concurrent = max(1, min(max_concurrent, 8))
        self.config.set("download", "max_concurrent", max_concurrent)
        self.config.set("download", "max_retries", max_retries)
        self._static_snapshot_cache = None
        self.record_event("settings.update", {"section": "download", "max_concurrent": max_concurrent, "download_options": True})
        return FrontendActionResult(
            "ok",
            "download options updated",
            {"auto_retry": auto_retry, "max_retries": max_retries, "max_concurrent": max_concurrent},
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

    def _action_change_directory(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        directory = str(payload.get("directory") or "")
        if not directory:
            return FrontendActionResult("error", "directory is required")
        self.config.set("common", "save_directory", directory)
        controller = self.controller
        if controller is not None and hasattr(controller, "current_save_dir"):
            controller.current_save_dir = directory
        return FrontendActionResult("ok", "directory changed", {"directory": directory})

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

    def _action_run_tool(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "")
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        valid_ids = {item["id"] for item in TOOLBOX_DEFINITIONS}
        if tool_id not in valid_ids:
            return FrontendActionResult("error", "unknown tool", {"tool_id": tool_id})
        return FrontendActionResult("ok", "tool queued", {"tool_id": tool_id})

    def _action_register_file_associations(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        include_video = bool(payload.get("include_video", True))
        include_image = bool(payload.get("include_image", False))
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
        if os.name == "nt":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise OSError("os.startfile is unavailable")
            startfile(directory)
            return
        import subprocess

        subprocess.Popen(["xdg-open", directory])

    @staticmethod
    def _current_executable_path() -> str:
        if getattr(sys, "frozen", False):
            return sys.executable
        return sys.argv[0]

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
        now_date = "2026-04-12"
        active_specs = [
            ("a1", "\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929", 65, "4.2 MB/s", 4_404_019, "00:01:42", 39),
            ("a2", "\u96e8\u540e\u5c71\u95f4\u7684\u6e29\u67d4\u65f6\u523b", 38, "2.7 MB/s", 2_831_155, "00:03:18", 23),
            ("a3", "\u81ea\u9a7e\u65b0\u7586 | \u661f\u7a7a\u4e0b\u7684\u665a\u9910", 22, "1.6 MB/s", 1_677_721, "00:06:45", 13),
            ("a4", "\u57ce\u5e02\u591c\u666f\u5ef6\u65f6\u6444\u5f71", 11, "1.1 MB/s", 1_153_434, "00:13:27", 7),
            ("a5", "\u5f92\u6b65\u7a7f\u8d8a\u5ce1\u8c37\u7684\u4e00\u5929", 8, "0.8 MB/s", 838_861, "00:18:56", 5),
        ]
        active_items = []
        for item_id, title, progress, speed, speed_bps, eta, chunks_done in active_specs:
            active_items.append({
                "id": item_id,
                "title": title,
                "platform": "\u6296\u97f3",
                "platform_id": "douyin",
                "progress": progress,
                "speed": speed,
                "speed_bps": speed_bps,
                "eta": eta,
                "remaining_time": eta,
                "trace_id": f"dy_20260412_182452_{item_id}",
                "save_dir": "D:\\Downloads\\\u6296\u97f3\\\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5",
                "output_filename": "\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_\u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929_20260412.mp4",
                "thread_count": 8,
                "retry_count": 0,
                "write_status": "\u6b63\u5728\u5199\u5165\uff0839 \u4e2a\u5206\u7247\uff09",
                "merge_status": "\u7b49\u5f85\u5168\u90e8\u5206\u7247\u5b8c\u6210\u540e\u81ea\u52a8\u5408\u5e76",
                "source_url": "https://v.douyin.com/abc123",
                "chunk_progress": {"completed": chunks_done, "total": 60, "percent": progress},
                "speed_trend": [3.2, 3.6, 3.1, 4.2, 3.8, 4.9, 3.5, 4.1, 3.9, 4.5, 3.7, 4.2],
                "events": [
                    {"time": "20:12:03", "message": "\u5f00\u59cb\u4e0b\u8f7d\uff1a" + title},
                    {"time": "20:12:03", "message": "\u5df2\u89e3\u6790\u89c6\u9891\u4fe1\u606f\uff0c\u5206\u8fa8\u7387\uff1a1920x1080"},
                    {"time": "20:12:04", "message": "\u5df2\u89e3\u6790\u5206\u7247\u7d22\u5f15\uff0c\u5171 60 \u4e2a\u5206\u7247"},
                    {"time": "20:12:05", "message": "\u5199\u5165\u5206\u7247\uff1a#37\uff0848.5 MB / 96\uff09"},
                    {"time": "20:12:06", "message": "\u5199\u5165\u5206\u7247\uff1a#38\uff0849.8 MB / 96\uff09"},
                ],
                "actions": ["delete"],
            })
        return {
            "pages": list(PAGE_DEFINITIONS),
            "queue_items": [
                {"id": "q1", "title": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929', "subtitle": f"{now_date} 18:24", "platform": '\u6296\u97f3', "platform_id": "douyin", "status": '\u5df2\u89e3\u6790', "source_url": "https://v.douyin.com/mock1", "trace_id": "dy_mock_001", "actions": ["delete"]},
                {"id": "q2", "title": '\u96e8\u540e\u5c71\u95f4\u7684\u6e05\u6668', "subtitle": f"{now_date} 18:22", "platform": '\u6296\u97f3', "platform_id": "douyin", "status": '\u5f85\u4e0b\u8f7d', "source_url": "https://v.douyin.com/mock2", "trace_id": "dy_mock_002", "actions": ["delete"]},
                {"id": "q3", "title": '\u57ce\u5e02\u591c\u666f\u5ef6\u65f6\u6444\u5f71', "subtitle": f"{now_date} 18:20", "platform": "Bilibili", "platform_id": "bilibili", "status": '\u6392\u961f\u4e2d', "source_url": "https://www.bilibili.com/video/BVmock", "trace_id": "bilibili_mock_003", "actions": ["delete"]},
            ] + [
                {
                    "id": f"q{index}",
                    "title": f"\u5f85\u4e0b\u8f7d\u793a\u4f8b\u4efb\u52a1 {index}",
                    "subtitle": f"{now_date} 18:{20 - index:02d}",
                    "platform": '\u6296\u97f3' if index % 2 else '\u5feb\u624b',
                    "platform_id": "douyin" if index % 2 else "kuaishou",
                    "status": ['\u5f85\u89e3\u6790', '\u89e3\u6790\u4e2d', '\u5df2\u89e3\u6790', '\u6392\u961f\u4e2d', '\u5df2\u5b58\u5728', '\u5f85\u4e0b\u8f7d'][index % 6],
                    "source_url": f"https://example.com/mock/{index}",
                    "trace_id": f"dy_mock_q_{index:03d}",
                    "actions": ["delete"],
                }
                for index in range(4, 10)
            ],
            "active_downloads": active_items,
            "completed_items": [
                {
                    "id": "c1",
                    "title": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5 | \u4e91\u6d77\u7ffb\u6d8c\u7684\u4e00\u5929',
                    "thumbnail": "",
                    "completed_at": f"{now_date} 18:24:35",
                    "completed_at_table": "04-12 18:24",
                    "duration": "00:00:24",
                    "resolution": "1920 x 1080",
                    "size": "24.6 MB",
                    "size_bytes": 24_600_000,
                    "format": "MP4",
                    "download_speed": "4.2 MB/s",
                    "download_speed_bps": 4_404_019,
                    "local_path": 'D:\\desktop\\\u89c6\u9891\\\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_20260412.mp4',
                    "filename": '\u5ddd\u897f\u96ea\u5c71\u4e4b\u65c5_20260412.mp4',
                    "save_dir": 'D:\\desktop\\\u89c6\u9891',
                    "content_type": "video",
                    "metadata_pending": False,
                    "platform": '\u6296\u97f3',
                    "actions": ["play", "open_directory", "delete"],
                }
            ] + [
                {
                    "id": f"c{index}",
                    "title": f"\u5df2\u5b8c\u6210\u793a\u4f8b\u89c6\u9891 {index:03d}",
                    "thumbnail": "",
                    "completed_at": f"{now_date} 17:{index % 60:02d}:10",
                    "completed_at_table": f"04-12 17:{index % 60:02d}",
                    "duration": "00:01:36",
                    "resolution": "1920 x 1080",
                    "size": f"{18 + index % 23}.4 MB",
                    "size_bytes": (18 + index % 23) * 1_048_576,
                    "format": "MP4",
                    "download_speed": f"{1 + index % 5}.2 MB/s",
                    "download_speed_bps": (1 + index % 5) * 1_258_291,
                    "local_path": f"D:\\desktop\\\u89c6\u9891\\completed_{index:03d}.mp4",
                    "filename": f"completed_{index:03d}.mp4",
                    "save_dir": "D:\\desktop\\\u89c6\u9891",
                    "content_type": "video",
                    "metadata_pending": False,
                    "platform": '\u6296\u97f3' if index % 2 else "Bilibili",
                    "actions": ["play", "open_directory", "delete"],
                }
                for index in range(2, 129)
            ],
            "failed_items": [
                {
                    "id": "f1",
                    "title": '\u5357\u5cb3\u5c71\u95f4\u7684\u6e05\u6668',
                    "failed_at": f"{now_date} 07:31:12",
                    "failed_at_table": "04-12 07:31",
                    "reason": '\u9700\u8981\u767b\u5f55',
                    "reason_detail": '\u9700\u8981\u767b\u5f55',
                    "reason_label": '\u9700\u8981\u767b\u5f55',
                    "reason_icon_file": "action_user.png",
                    "status": '\u5931\u8d25',
                    "status_label": '\u5931\u8d25',
                    "status_icon_file": "status_failed.png",
                    "trace_id": "dy_failed_001",
                    "platform": '\u6296\u97f3',
                    "platform_id": "douyin",
                    "source_url": "https://v.douyin.com/fail",
                    "log_excerpt": ['\u8bf7\u6c42\u89c6\u9891\u94fe\u63a5', '\u63a5\u53e3\u8fd4\u56de\u9700\u8981\u767b\u5f55', '\u4efb\u52a1\u6807\u8bb0\u4e3a\u5931\u8d25'],
                    "log_excerpt_items": [
                        {"time": f"{now_date} 07:31:02", "level": "INFO", "message": '\u8bf7\u6c42\u89c6\u9891\u94fe\u63a5', "icon_file": "log_level_info.png"},
                        {"time": f"{now_date} 07:31:09", "level": "WARN", "message": '\u63a5\u53e3\u8fd4\u56de\u9700\u8981\u767b\u5f55', "icon_file": "log_level_warn.png"},
                        {"time": f"{now_date} 07:31:12", "level": "ERROR", "message": '\u4efb\u52a1\u6807\u8bb0\u4e3a\u5931\u8d25', "icon_file": "log_level_error.png"},
                    ],
                    "solutions": [
                        {"title": '\u786e\u8ba4\u767b\u5f55\u6001', "description": '\u90e8\u5206\u5185\u5bb9\u9700\u8981\u767b\u5f55\u540e\u624d\u80fd\u8bbf\u95ee\uff0c\u8bf7\u68c0\u67e5\u767b\u5f55\u72b6\u6001\u3002', "icon_file": "action_user.png"},
                        {"title": '\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5', "description": '\u767b\u5f55\u540e\u91cd\u65b0\u590d\u5236\u5206\u4eab\u94fe\u63a5\u5e76\u91cd\u8bd5\u3002', "icon_file": "action_trace_link.png"},
                    ],
                    "actions": ["retry", "copy_diagnostics", "delete"],
                }
            ] + [
                {
                    "id": f"f{index}",
                    "title": f"\u5931\u8d25\u793a\u4f8b\u4efb\u52a1 {index}",
                    "failed_at": f"{now_date} 07:{30 + index:02d}:12",
                    "failed_at_table": f"04-12 07:{30 + index:02d}",
                    "reason": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5df2\u5931\u6548', '\u5e73\u53f0\u9700\u8981\u767b\u5f55'][index % 3],
                    "reason_detail": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5df2\u5931\u6548', '\u5e73\u53f0\u9700\u8981\u767b\u5f55'][index % 3],
                    "reason_label": ['\u7f51\u7edc\u8d85\u65f6', '\u94fe\u63a5\u5931\u8d25', '\u9700\u8981\u767b\u5f55'][index % 3],
                    "reason_icon_file": ["status_timeout.png", "action_trace_link.png", "action_user.png"][index % 3],
                    "status": '\u5931\u8d25',
                    "status_label": '\u5931\u8d25',
                    "status_icon_file": "status_failed.png",
                    "trace_id": f"dy_failed_{index:03d}",
                    "platform": '\u6296\u97f3' if index % 2 else '\u5feb\u624b',
                    "platform_id": "douyin" if index % 2 else "kuaishou",
                    "source_url": f"https://example.com/fail/{index}",
                    "log_excerpt": ['\u5f00\u59cb\u89e3\u6790\u94fe\u63a5', '\u4e0b\u8f7d\u5668\u8fd4\u56de\u9519\u8bef', '\u4efb\u52a1\u8fdb\u5165\u5931\u8d25\u5217\u8868'],
                    "log_excerpt_items": [
                        {"time": f"{now_date} 07:{30 + index:02d}:04", "level": "INFO", "message": '\u5f00\u59cb\u89e3\u6790\u94fe\u63a5', "icon_file": "log_level_info.png"},
                        {"time": f"{now_date} 07:{30 + index:02d}:09", "level": "ERROR", "message": '\u4e0b\u8f7d\u5668\u8fd4\u56de\u9519\u8bef', "icon_file": "log_level_error.png"},
                        {"time": f"{now_date} 07:{30 + index:02d}:12", "level": "WARN", "message": '\u4efb\u52a1\u8fdb\u5165\u5931\u8d25\u5217\u8868', "icon_file": "log_level_warn.png"},
                    ],
                    "solutions": [
                        {"title": '\u91cd\u8bd5\u4efb\u52a1', "description": '\u7f51\u7edc\u6296\u52a8\u65f6\u53ef\u7a0d\u540e\u91cd\u8bd5\u3002', "icon_file": "action_refresh.png"},
                        {"title": '\u68c0\u67e5\u94fe\u63a5', "description": '\u786e\u8ba4\u5206\u4eab\u94fe\u63a5\u4ecd\u53ef\u8bbf\u95ee\u3002', "icon_file": "action_trace_link.png"},
                    ],
                    "actions": ["retry", "copy_diagnostics", "delete"],
                }
                for index in range(2, 8)
            ],
            "log_items": [
                {"time": f"{now_date} 18:24:35", "level": "INFO", "source": "下载器", "thread": "download-worker-1", "trace_id": "7f8c9b0d3e1a4b2c", "message_summary": "开始下载视频", "message": "开始下载视频", "detail": "{}", "stack": ""},
                {"time": f"{now_date} 18:25:03", "level": "ERROR", "source": "下载器", "thread": "download-worker-1", "trace_id": "b7c5d8e9f0a1b2c3", "message_summary": "下载失败：无法解析视频播放地址", "message": "下载失败：无法解析视频播放地址", "detail": "code: 1001", "stack": ""},
            ],
            "settings_snapshot": FrontendStateService().settings_snapshot(),
            "download_options": {"auto_retry": True, "max_retries": 3, "max_concurrent": 3},
            "toolbox_items": FrontendStateService.toolbox_items(),
            "toolbox_recent_items": FrontendStateService.toolbox_recent_items(),
            "icon_manifest": icon_manifest(),
            "app_status": {
                "running_state": "\u8fd0\u884c\u4e2d",
                "status_indicator": "running",
                "download_speed": "10.4 MB/s",
                "download_speed_bps": 10_905_190,
                "completed_count": 128,
                "failed_count": 7,
                "version": "v2.3.0",
            },
        }
