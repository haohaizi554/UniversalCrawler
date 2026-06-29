"""Shared domain event models used by different hosts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.state import CrawlStatus, VideoStatus, parse_video_status
from app.models import VideoItem

class DomainEventType(str, Enum):
    """Canonical domain event categories."""

    VIDEO_STATE_CHANGED = "video_state_changed"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_ERROR = "task_error"
    ITEM_FOUND = "item_found"
    SELECTION_REQUIRED = "selection_required"
    CRAWL_STATE_CHANGED = "crawl_state_changed"
    LOG = "log"

@dataclass(slots=True)
class DomainEvent:
    """Transport-agnostic domain event payload."""

    event_type: DomainEventType
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    entity_id: str | None = None
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_payload(self) -> dict[str, Any]:
        data = dict(self.payload)
        data.setdefault("event_type", self.event_type.value)
        data.setdefault("timestamp_ms", self.timestamp_ms)
        if self.trace_id:
            data.setdefault("trace_id", self.trace_id)
        if self.entity_id:
            data.setdefault("entity_id", self.entity_id)
        return data

def build_video_state_event(
    video_id: str,
    item: VideoItem,
    *,
    requested_progress: int | None,
) -> DomainEvent:
    """Build a canonical video state event from a VideoItem."""
    parsed_status = parse_video_status(item.status) or VideoStatus.PENDING
    payload: dict[str, Any] = {
        "video_id": video_id,
        "status": item.status,
        "status_code": parsed_status.value,
        "progress": requested_progress if requested_progress is not None else item.progress,
    }
    if parsed_status in {VideoStatus.COMPLETED, VideoStatus.FAILED, VideoStatus.TIMED_OUT, VideoStatus.LOCAL}:
        payload["local_path"] = item.local_path or ""
        payload["content_type"] = item.meta.get("content_type", "") if item.meta else ""
    return DomainEvent(
        event_type=DomainEventType.VIDEO_STATE_CHANGED,
        payload=payload,
        trace_id=item.meta.get("trace_id") if item.meta else None,
        entity_id=video_id,
    )

def build_crawl_state_event(status: CrawlStatus, **payload: Any) -> DomainEvent:
    """Build a canonical crawl lifecycle event."""
    data = {"status": status.value, **payload}
    return DomainEvent(
        event_type=DomainEventType.CRAWL_STATE_CHANGED,
        payload=data,
    )

def build_log_event(message: str, **payload: Any) -> DomainEvent:
    """Build a canonical log event."""
    return DomainEvent(
        event_type=DomainEventType.LOG,
        payload={"message": message, **payload},
    )

def build_item_found_event(item: VideoItem) -> DomainEvent:
    """Build a canonical item-found event."""
    return DomainEvent(
        event_type=DomainEventType.ITEM_FOUND,
        payload={"item": item},
        trace_id=item.meta.get("trace_id") if item.meta else None,
        entity_id=item.id,
    )

def build_selection_required_event(items: list[Any]) -> DomainEvent:
    """Build a canonical selection-required event."""
    return DomainEvent(
        event_type=DomainEventType.SELECTION_REQUIRED,
        payload={"items": items},
    )

def _build_task_event_payload(video_id: str, item: VideoItem | None, *, error: str | None = None) -> tuple[dict[str, Any], str | None]:
    payload: dict[str, Any] = {
        "video_id": video_id,
        "local_path": (item.local_path or "") if item else "",
        "title": item.title if item else "",
        "content_type": (item.meta.get("content_type", "") if item and item.meta else ""),
    }
    if error is not None:
        payload["error"] = error
    trace_id = item.meta.get("trace_id") if item and item.meta else None
    return payload, trace_id

def build_task_started_event(video_id: str, item: VideoItem | None) -> DomainEvent:
    """Build a task-started event while keeping legacy Web payload shape."""
    payload, trace_id = _build_task_event_payload(video_id, item)
    return DomainEvent(
        event_type=DomainEventType.TASK_STARTED,
        payload=payload,
        trace_id=trace_id,
        entity_id=video_id,
    )

def build_task_finished_event(video_id: str, item: VideoItem | None) -> DomainEvent:
    """Build a task-finished event while keeping legacy Web payload shape."""
    payload, trace_id = _build_task_event_payload(video_id, item)
    return DomainEvent(
        event_type=DomainEventType.TASK_FINISHED,
        payload=payload,
        trace_id=trace_id,
        entity_id=video_id,
    )

def build_task_error_event(video_id: str, item: VideoItem | None, error: str) -> DomainEvent:
    """Build a task-error event while keeping legacy Web payload shape."""
    payload, trace_id = _build_task_event_payload(video_id, item, error=error)
    return DomainEvent(
        event_type=DomainEventType.TASK_ERROR,
        payload=payload,
        trace_id=trace_id,
        entity_id=video_id,
    )
