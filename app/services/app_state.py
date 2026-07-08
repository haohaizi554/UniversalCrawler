"""Central frontend state store for GUI pages, logs and task progress."""

from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from typing import Any

from app.core.event_bus import EventBus
from app.debug_logger import debug_logger
from app.models import VideoItem
from app.config.settings import normalize_ui_log_max_display_count
from app.services.cache_service import CacheService

class AppState:
    """Single source of truth for desktop frontend state."""

    LOG_BUFFER_LIMIT = 300
    LOG_PUBLISH_INTERVAL_SECONDS = 0.1
    PROGRESS_THROTTLE_SECONDS = 0.25
    MAX_PUBLISH_DEPTH = 8

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        cache_service: CacheService | None = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self._owns_cache_service = cache_service is None
        self.cache_service = cache_service or CacheService(namespace="app_state")
        self._lock = threading.RLock()
        self.videos: dict[str, Any] = {}
        self.current_playing_id: str | None = None
        self.running_state = "空闲中"
        self.page_state: dict[str, dict[str, Any]] = {}
        self.task_state: dict[str, dict[str, Any]] = {}
        self.log_buffer: deque[dict[str, Any]] = deque(maxlen=self.LOG_BUFFER_LIMIT)
        self.auto_copy_trace_on_error = True
        self._last_progress_emit_at: dict[str, float] = {}
        self._log_publish_lock = threading.RLock()
        self._log_publish_timer: threading.Timer | None = None
        self._log_publish_pending = False
        self._log_publish_count = 0
        self._publish_depth = threading.local()
        self._visible_page = str(self.cache_service.get("ui.visible_page", "queue") or "queue")
        self.page_state[self._visible_page] = {"visible": True}

    def set_visible_page(
        self,
        page_id: str,
        all_pages: list[str] | None = None,
        *,
        emit_change: bool = True,
    ) -> None:
        with self._lock:
            self._visible_page = str(page_id or "queue")
            if all_pages:
                for candidate in all_pages:
                    self.page_state.setdefault(candidate, {})["visible"] = candidate == self._visible_page
            else:
                self.page_state.setdefault(self._visible_page, {})["visible"] = True
            visible_page = self._visible_page
        self.cache_service.set("ui.visible_page", visible_page, persist=False)
        if emit_change:
            self._publish_change("page.visibility", {"page_id": visible_page})

    def get_visible_page(self) -> str:
        with self._lock:
            return self._visible_page

    def is_page_visible(self, page_id: str) -> bool:
        with self._lock:
            return bool(self.page_state.get(page_id, {}).get("visible", False))

    def set_running_state(self, label: str) -> None:
        with self._lock:
            self.running_state = str(label)
        self._publish_change("app.running_state", {"running_state": self.running_state})

    def upsert_video(self, item: Any) -> None:
        with self._lock:
            self.videos[item.id] = item
        self._publish_change("videos.upsert", {"video_id": item.id})

    def upsert_videos(self, items: Any) -> list[str]:
        video_items = [item for item in items if getattr(item, "id", None)]
        if not video_items:
            return []
        with self._lock:
            for item in video_items:
                self.videos[item.id] = item
            video_ids = [item.id for item in video_items]
        self._publish_change("videos.upsert_many", {"video_ids": video_ids, "count": len(video_ids)})
        return video_ids

    def remove_video(self, video_id: str) -> None:
        removed = self.remove_videos({video_id}, publish=False)
        if removed:
            self._publish_change("videos.remove", {"video_id": video_id})

    def remove_videos(self, video_ids, *, publish: bool = True) -> list[str]:
        ids = {str(video_id) for video_id in video_ids if video_id}
        if not ids:
            return []
        removed: list[str] = []
        with self._lock:
            for video_id in ids:
                if self.videos.pop(video_id, None) is None:
                    continue
                removed.append(video_id)
                self.task_state.pop(video_id, None)
                self._last_progress_emit_at.pop(video_id, None)
        if removed and publish:
            self._publish_change("videos.remove_many", {"video_ids": list(removed), "count": len(removed)})
        return removed

    def clear_videos(self) -> None:
        with self._lock:
            self.videos.clear()
            self.task_state.clear()
            self._last_progress_emit_at.clear()
        self._publish_change("videos.clear", {})

    def replace_videos(self, videos: dict[str, Any]) -> None:
        with self._lock:
            self.videos = deepcopy(videos)
            valid_ids = set(self.videos)
            for state in (self.task_state, self._last_progress_emit_at):
                for video_id in list(state):
                    if video_id not in valid_ids:
                        state.pop(video_id, None)
        self._publish_change("videos.replace", {"count": len(videos)})

    def update_video_state(self, video_id: str, *, status: str | None = None, progress: int | None = None) -> Any | None:
        with self._lock:
            item = self.videos.get(video_id)
            if item is None:
                return None
            if status is not None:
                item.status = status
            if progress is not None:
                item.progress = progress
                task_state = self.task_state.setdefault(video_id, {})
                task_state["progress"] = progress
                task_state["updated_at"] = time.monotonic()
        payload = {
            "video_id": video_id,
            "progress": progress,
            "status": str(getattr(item, "status", "") or ""),
            "local_path": str(getattr(item, "local_path", "") or ""),
            "content_type": str(getattr(item, "content_type", "") or ""),
        }
        self._publish_change("videos.update", payload)
        if item is None:
            return None
        if hasattr(item, "to_dict"):
            return self._video_item_from_snapshot(item.to_dict())
        return deepcopy(item)

    def snapshot_videos(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self.videos)

    def set_current_playing_id(self, video_id: str | None) -> None:
        with self._lock:
            self.current_playing_id = video_id
        self._publish_change("media.current_playing", {"video_id": video_id})

    def get_current_playing_id(self) -> str | None:
        with self._lock:
            return self.current_playing_id

    def should_emit_progress(self, video_id: str, progress: int) -> bool:
        now = time.monotonic()
        with self._lock:
            last_at = self._last_progress_emit_at.get(video_id, 0.0)
            last_progress = self.task_state.get(video_id, {}).get("progress")
            if progress not in {0, 100} and last_progress == progress and now - last_at < self.PROGRESS_THROTTLE_SECONDS:
                return False
            if progress not in {0, 100} and now - last_at < self.PROGRESS_THROTTLE_SECONDS:
                return False
            self._last_progress_emit_at[video_id] = now
            self.task_state.setdefault(video_id, {})["progress"] = progress
            self.task_state[video_id]["updated_at"] = now
            return True

    def record_log(
        self,
        message: str,
        *,
        level: str = "INFO",
        source: str = "GUI",
        trace_id: str = "",
        topic: str = "logs.append",
    ) -> dict[str, Any]:
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level.upper(),
            "source": source,
            "thread": "GUI",
            "trace_id": trace_id,
            "message_summary": str(message),
            "message": str(message),
            "detail": {},
            "stack": "",
        }
        with self._lock:
            self.log_buffer.append(entry)
            count = len(self.log_buffer)
        if topic == "logs.append":
            self._schedule_log_publish(count)
        else:
            self._publish_change(topic, {"count": count})
        return entry

    def configure_log_buffer(self, max_entries: int) -> int:
        """Resize the UI log ring buffer without losing recent entries."""
        normalized = normalize_ui_log_max_display_count(max_entries, default=self.LOG_BUFFER_LIMIT)
        with self._lock:
            if self.log_buffer.maxlen == normalized:
                return normalized
            recent_entries = list(self.log_buffer)[-normalized:]
            self.log_buffer = deque(recent_entries, maxlen=normalized)
            count = len(self.log_buffer)
        self._cancel_pending_log_publish()
        self._publish_change("logs.append", {"count": count, "limit": normalized})
        return normalized

    def set_auto_copy_trace_on_error(self, enabled: bool) -> bool:
        with self._lock:
            self.auto_copy_trace_on_error = bool(enabled)
            current = self.auto_copy_trace_on_error
        self._publish_change("logging.policy", {"auto_copy_trace_on_error": current})
        return current

    def should_auto_copy_trace_on_error(self) -> bool:
        with self._lock:
            return bool(self.auto_copy_trace_on_error)

    def get_log_buffer(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self.log_buffer))

    def clear_logs(self) -> None:
        with self._lock:
            self.log_buffer.clear()
        self._cancel_pending_log_publish()
        self._publish_change("logs.append", {"count": 0, "cleared": True})

    def shutdown(self) -> None:
        """Cancel pending asynchronous UI notifications owned by this state store."""
        self._cancel_pending_log_publish()
        if not self._owns_cache_service:
            return
        close_cache = getattr(self.cache_service, "close", None)
        if not callable(close_cache):
            return
        try:
            close_cache()
            self._owns_cache_service = False
        except Exception as exc:
            debug_logger.log_exception(
                "AppState",
                "shutdown_cache_service",
                exc,
            )

    def snapshot_meta(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current_playing_id": self.current_playing_id,
                "running_state": self.running_state,
                "visible_page": self._visible_page,
                "page_state": deepcopy(self.page_state),
                "task_state": deepcopy(self.task_state),
            }

    def _publish_change(self, topic: str, payload: dict[str, Any]) -> None:
        depth = int(getattr(self._publish_depth, "value", 0) or 0)
        if depth >= self.MAX_PUBLISH_DEPTH:
            # 抑制分支不递增 _publish_depth：_publish_depth 跟踪的是 "app_state.changed"
            # 事件的递归深度，而此分支发布的是 "app_state.publish_suppressed" 元事件，
            # 不属于 change 递归调用链。直接 return 不会增加 change 递归深度，
            # 因此无需递增；若递增反而会在无 try/finally 保护时导致计数泄漏。
            debug_logger.log(
                component="AppState",
                action="publish_depth_limit",
                level="WARN",
                message="AppState change event dropped because publish recursion exceeded the safety limit",
                status_code="APP_STATE_PUBLISH_LIMIT",
                details={"topic": topic, "depth": depth},
            )
            self.event_bus.publish(
                "app_state.publish_suppressed",
                {"topic": topic, "depth": depth, **payload},
            )
            return
        self._publish_depth.value = depth + 1
        try:
            self.event_bus.publish(
                "app_state.changed",
                {
                    "topic": topic,
                    **payload,
                },
            )
        finally:
            self._publish_depth.value = depth

    def _schedule_log_publish(self, count: int) -> None:
        with self._log_publish_lock:
            self._log_publish_pending = True
            self._log_publish_count = int(count)
            timer = self._log_publish_timer
            if timer is not None and timer.is_alive():
                return
            timer = threading.Timer(self.LOG_PUBLISH_INTERVAL_SECONDS, self._flush_pending_log_publish)
            timer.daemon = True
            self._log_publish_timer = timer
            timer.start()

    def _flush_pending_log_publish(self) -> None:
        with self._log_publish_lock:
            if not self._log_publish_pending:
                self._log_publish_timer = None
                return
            count = self._log_publish_count
            self._log_publish_pending = False
            self._log_publish_timer = None
        self._publish_change("logs.append", {"count": count, "batched": True})

    def _cancel_pending_log_publish(self) -> None:
        with self._log_publish_lock:
            timer = self._log_publish_timer
            self._log_publish_timer = None
            self._log_publish_pending = False
        if timer is not None and timer.is_alive():
            timer.cancel()

    @staticmethod
    def _video_item_from_snapshot(snapshot: dict[str, Any]) -> VideoItem:
        item = VideoItem(
            url=str(snapshot.get("url") or ""),
            title=str(snapshot.get("title") or ""),
            source=str(snapshot.get("source") or ""),
        )
        item.id = str(snapshot.get("id") or item.id)
        item.status = str(snapshot.get("status") or "")
        try:
            item.progress = int(snapshot.get("progress") or 0)
        except (TypeError, ValueError):
            item.progress = 0
        item.local_path = str(snapshot.get("local_path") or "")
        meta = snapshot.get("meta")
        item.meta = deepcopy(meta) if isinstance(meta, dict) else {}
        return item
