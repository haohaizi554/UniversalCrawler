"""Coalesce high-volume frontend events into versioned dirty sections."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

class FrontendEventPriority(IntEnum):
    """Frontend event delivery priority."""

    NOISY = 0
    NORMAL = 1
    CRITICAL = 2

VIDEO_SECTIONS = frozenset({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"})
STATIC_SECTIONS = frozenset(
    {
        "pages",
        "icon_manifest",
        "toolbox_items",
        "toolbox_recent_items",
        "settings_snapshot",
        "settings_contract",
        "download_options",
    }
)
ALL_FRONTEND_SECTIONS = VIDEO_SECTIONS | STATIC_SECTIONS | frozenset({"log_items"})

NOISY_TOPICS = frozenset(
    {
        "videos.update",
        "video_state_changed",
        "task_progress",
        "logs.append",
        "log",
    }
)

CRITICAL_TOPICS = frozenset(
    {
        "task_finished",
        "task_error",
        "video_removed",
        "clear_videos",
        "crawl_state",
        "crawl_state_changed",
        "select_tasks",
        "selection_required",
        "frontend_action_result",
        "videos.remove",
        "videos.remove_many",
        "videos.clear",
    }
)

NORMAL_TOPICS = frozenset(
    {
        "videos.upsert",
        "videos.replace",
        "item_found",
        "task_started",
        "scan_result",
        "video_renamed",
        "app.running_state",
        "page.visibility",
        "media.current_playing",
        "videos.metadata",
        "settings.update",
        "config",
        "platforms",
    }
)

def priority_for_topic(topic: str) -> FrontendEventPriority:
    normalized = str(topic or "")
    if normalized in CRITICAL_TOPICS:
        return FrontendEventPriority.CRITICAL
    if normalized in NOISY_TOPICS:
        return FrontendEventPriority.NOISY
    return FrontendEventPriority.NORMAL

def sections_for_topic(topic: str) -> frozenset[str] | None:
    """Map transport/domain topics to frontend snapshot sections."""

    normalized = str(topic or "")
    if normalized in {"videos.update", "video_state_changed", "task_progress"}:
        return frozenset({"active_downloads", "app_status"})
    if normalized == "videos.metadata":
        return frozenset({"completed_items", "app_status"})
    if normalized in {
        "videos.upsert",
        "videos.remove",
        "videos.remove_many",
        "videos.clear",
        "videos.replace",
        "item_found",
        "task_started",
        "task_finished",
        "task_error",
        "video_removed",
        "clear_videos",
        "video_renamed",
        "scan_result",
    }:
        # `scan_result` is usually a local directory scan refresh, so keep section
        # fan-out tight to avoid rebuilding unrelated video sections.
        if normalized == "scan_result":
            return frozenset({"queue_items", "app_status"})
        return VIDEO_SECTIONS
    if normalized in {"logs.append", "log"}:
        return frozenset({"log_items", "app_status"})
    if normalized in {"app.running_state", "crawl_state", "crawl_state_changed", "page.visibility"}:
        return frozenset({"app_status"})
    if normalized in {"settings.update", "config"}:
        return frozenset({"settings_snapshot", "settings_contract", "download_options", "app_status"})
    if normalized == "settings.platform_auth":
        return frozenset({"settings_snapshot", "settings_contract"})
    if normalized == "platforms":
        return frozenset({"settings_snapshot"})
    return None

def event_coalesce_key(topic: str, payload: Any = None) -> tuple[str, str]:
    """Return the latest-state-wins key for a frontend event."""

    payload = payload if isinstance(payload, dict) else {}
    entity_id = (
        payload.get("video_id")
        or payload.get("id")
        or payload.get("entity_id")
        or payload.get("trace_id")
        or ""
    )
    if priority_for_topic(topic) == FrontendEventPriority.NOISY and entity_id:
        return (str(topic), str(entity_id))
    return (str(topic), "")

@dataclass(slots=True)
class FrontendDirtyState:
    version: int
    changed_sections: frozenset[str]
    priority: FrontendEventPriority
    pending_events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    deleted_ids: tuple[str, ...] = field(default_factory=tuple)
    coalesced_count: int = 0
    dropped_count: int = 0

class FrontendEventAggregator:
    """Thread-safe dirty-section tracker for GUI and WebUI refreshes."""

    def __init__(self, *, max_pending_events: int = 2048, monotonic=time.monotonic) -> None:
        self._lock = threading.RLock()
        self._version = 0
        self._dirty_sections: set[str] = set()
        self._priority = FrontendEventPriority.NOISY
        self._pending_events: dict[tuple[str, str], dict[str, Any]] = {}
        self._deleted_ids: set[str] = set()
        self._max_pending_events = max(1, int(max_pending_events))
        self._section_history: deque[tuple[int, frozenset[str]]] = deque(maxlen=max(256, self._max_pending_events))
        self._deleted_history: deque[tuple[int, str]] = deque(maxlen=max(256, self._max_pending_events))
        self._coalesced_count = 0
        self._dropped_count = 0
        self._recorded_count = 0
        self._last_recorded_at = 0.0
        self._monotonic = monotonic

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def record(self, topic: str, payload: Any = None, *, sections: frozenset[str] | set[str] | None = None) -> FrontendDirtyState:
        priority = priority_for_topic(topic)
        dirty_sections = frozenset(sections) if sections is not None else sections_for_topic(topic)
        with self._lock:
            self._version += 1
            self._recorded_count += 1
            self._last_recorded_at = self._monotonic()
            if dirty_sections is None:
                event_sections = ALL_FRONTEND_SECTIONS
            else:
                event_sections = dirty_sections
            self._dirty_sections.update(event_sections)
            self._section_history.append((self._version, frozenset(event_sections)))
            self._priority = max(self._priority, priority)
            self._remember_event(topic, payload, priority)
            self._remember_deleted_id(topic, payload, self._version)
            return self.peek()

    def reset(self) -> None:
        with self._lock:
            self._version += 1
            self._dirty_sections.update(ALL_FRONTEND_SECTIONS)
            self._priority = FrontendEventPriority.CRITICAL
            self._pending_events.clear()
            self._deleted_ids.clear()
            self._section_history.clear()
            self._deleted_history.clear()
            self._section_history.append((self._version, ALL_FRONTEND_SECTIONS))

    def peek(self) -> FrontendDirtyState:
        with self._lock:
            return FrontendDirtyState(
                version=self._version,
                changed_sections=frozenset(self._dirty_sections),
                priority=self._priority,
                pending_events=tuple(self._pending_events.values()),
                deleted_ids=tuple(sorted(self._deleted_ids)),
                coalesced_count=self._coalesced_count,
                dropped_count=self._dropped_count,
            )

    def consume(self) -> FrontendDirtyState:
        with self._lock:
            state = self.peek()
            self._dirty_sections.clear()
            self._priority = FrontendEventPriority.NOISY
            self._pending_events.clear()
            self._deleted_ids.clear()
            return state

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self._version,
                "pending_event_count": len(self._pending_events),
                "dirty_sections": sorted(self._dirty_sections),
                "priority": self._priority.name.lower(),
                "recorded_count": self._recorded_count,
                "coalesced_count": self._coalesced_count,
                "dropped_count": self._dropped_count,
                "last_recorded_at": self._last_recorded_at,
                "history_depth": len(self._section_history),
            }

    def sections_since(self, base_version: int) -> frozenset[str]:
        """Return the exact dirty section union after ``base_version`` when retained."""
        with self._lock:
            try:
                base = int(base_version or 0)
            except (TypeError, ValueError):
                base = 0
            if base >= self._version:
                return frozenset()
            if not self._section_history:
                return frozenset(self._dirty_sections or ALL_FRONTEND_SECTIONS)
            oldest_version = self._section_history[0][0]
            if base < oldest_version - 1:
                return ALL_FRONTEND_SECTIONS
            sections: set[str] = set()
            for version, dirty_sections in self._section_history:
                if version > base:
                    sections.update(dirty_sections)
            return frozenset(sections)

    def deleted_ids_since(self, base_version: int) -> tuple[str, ...]:
        with self._lock:
            try:
                base = int(base_version or 0)
            except (TypeError, ValueError):
                base = 0
            if base >= self._version:
                return ()
            deleted = {
                video_id
                for version, video_id in self._deleted_history
                if version > base
            }
            return tuple(sorted(deleted))

    def _remember_event(self, topic: str, payload: Any, priority: FrontendEventPriority) -> None:
        key = event_coalesce_key(topic, payload)
        if key in self._pending_events:
            self._coalesced_count += 1
        elif len(self._pending_events) >= self._max_pending_events:
            if priority == FrontendEventPriority.NOISY:
                self._dropped_count += 1
                return
            if not self._drop_queued_below_priority(priority):
                if priority != FrontendEventPriority.CRITICAL:
                    self._dropped_count += 1
                    return
                self._drop_oldest_event()
        self._pending_events[key] = {
            "topic": str(topic),
            "priority": priority.name.lower(),
            "payload": payload if isinstance(payload, dict) else {},
            "recorded_at": self._monotonic(),
        }

    def _drop_queued_below_priority(self, priority: FrontendEventPriority) -> bool:
        for candidate_priority in (FrontendEventPriority.NOISY, FrontendEventPriority.NORMAL):
            if candidate_priority >= priority:
                continue
            if self._drop_first_event_with_priority(candidate_priority):
                return True
        return False

    def _drop_first_event_with_priority(self, priority: FrontendEventPriority) -> bool:
        priority_name = priority.name.lower()
        for key, event in list(self._pending_events.items()):
            if event.get("priority") == priority_name:
                self._pending_events.pop(key, None)
                self._dropped_count += 1
                return True
        return False

    def _drop_oldest_event(self) -> None:
        first_key = next(iter(self._pending_events), None)
        if first_key is not None:
            self._pending_events.pop(first_key, None)
            self._dropped_count += 1

    def _remember_deleted_id(self, topic: str, payload: Any, version: int) -> None:
        if topic not in {"videos.remove", "videos.remove_many", "video_removed"}:
            return
        if not isinstance(payload, dict):
            return
        video_ids = payload.get("video_ids")
        if isinstance(video_ids, (list, tuple, set)):
            for video_id in video_ids:
                if video_id:
                    self._remember_deleted_value(str(video_id), version)
            return
        video_id = payload.get("video_id") or payload.get("id")
        if video_id:
            self._remember_deleted_value(str(video_id), version)

    def _remember_deleted_value(self, video_id: str, version: int) -> None:
        self._deleted_ids.add(str(video_id))
        self._deleted_history.append((version, str(video_id)))

