"""GUI/Web 前端状态中心，统一保存页面状态、日志缓冲和任务进度。"""

from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from typing import Any, Mapping

from app.core.event_bus import EventBus
from app.debug_logger import debug_logger
from app.models import VideoItem
from app.config.settings import normalize_ui_log_max_display_count
from app.services.cache_service import CacheService
from app.services.keyed_lock_pool import KeyedLockPool

class AppState:
    """GUI/Web 状态单一来源；修改在锁内完成，并通过 EventBus 广播给前端。"""

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
        self._media_item_locks = KeyedLockPool()
        self.videos: dict[str, Any] = {}
        self.current_playing_id: str | None = None
        self.running_state = "空闲中"
        self.page_state: dict[str, dict[str, Any]] = {}
        self.task_state: dict[str, dict[str, Any]] = {}
        self.log_buffer: deque[dict[str, Any]] = deque(maxlen=self.LOG_BUFFER_LIMIT)
        self._next_log_sequence = 0
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
        """记录当前可见页面；只持久化最近页面，不把整份 page_state 写入缓存。"""
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
        with self._media_item_locks.hold(item.id):
            with self._lock:
                self.videos[item.id] = item
        self._publish_change("videos.upsert", {"video_id": item.id})

    def upsert_videos(self, items: Any) -> list[str]:
        video_items = [item for item in items if getattr(item, "id", None)]
        if not video_items:
            return []
        video_ids = [item.id for item in video_items]
        with self._media_item_locks.hold_many(video_ids):
            with self._lock:
                for item in video_items:
                    self.videos[item.id] = item
        self._publish_change("videos.upsert_many", {"video_ids": video_ids, "count": len(video_ids)})
        return video_ids

    def reconcile_videos(
        self,
        items: Any,
        *,
        remove_if_matches: Mapping[str, Any] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Atomically apply one media scan without clearing unchanged rows.

        Removals use object identity captured by the scan worker. If a download
        replaces an item while the scan is in flight, that newer object wins.
        """

        video_items = [item for item in items if getattr(item, "id", None)]
        expected_items = {
            str(video_id): item
            for video_id, item in (remove_if_matches or {}).items()
            if video_id and item is not None
        }
        coordinated_ids = set(expected_items) | {str(item.id) for item in video_items}
        if not coordinated_ids:
            return [], []

        added: list[str] = []
        removed: list[str] = []
        with self._media_item_locks.hold_many(coordinated_ids):
            with self._lock:
                for video_id, expected in expected_items.items():
                    if self.videos.get(video_id) is not expected:
                        continue
                    self.videos.pop(video_id, None)
                    self.task_state.pop(video_id, None)
                    self._last_progress_emit_at.pop(video_id, None)
                    removed.append(video_id)
                for item in video_items:
                    video_id = str(item.id)
                    if self.videos.get(video_id) is item:
                        continue
                    if video_id not in self.videos:
                        added.append(video_id)
                    self.videos[video_id] = item
                if self.current_playing_id in removed:
                    self.current_playing_id = None

        if added or removed:
            self._publish_change(
                "videos.reconcile",
                {
                    "added_ids": list(added),
                    "removed_ids": list(removed),
                    "video_ids": list(removed),
                    "added_count": len(added),
                    "removed_count": len(removed),
                },
            )
        return added, removed

    def remove_video(self, video_id: str) -> None:
        removed = self.remove_videos({video_id}, publish=False)
        if removed:
            self._publish_change("videos.remove", {"video_id": video_id})

    def remove_video_if_matches(
        self,
        video_id: str,
        expected: Any,
        *,
        publish: bool = True,
    ) -> bool:
        """Remove one item only while the captured object still owns its ID."""

        normalized_id = str(video_id or "")
        if not normalized_id:
            return False
        removed = False
        matched = False
        with self._media_item_locks.hold(normalized_id):
            with self._lock:
                current = self.videos.get(normalized_id)
                if current is None:
                    matched = True
                elif current is expected:
                    self.videos.pop(normalized_id, None)
                    self.task_state.pop(normalized_id, None)
                    self._last_progress_emit_at.pop(normalized_id, None)
                    removed = True
                    matched = True
        if removed and publish:
            self._publish_change("videos.remove", {"video_id": normalized_id})
        return matched

    def remove_videos_if_matches(
        self,
        expected_by_id: Mapping[str, Any],
        *,
        publish: bool = True,
    ) -> list[str]:
        """Remove a frozen batch without deleting same-ID replacements."""

        expected_items = {
            str(video_id): item
            for video_id, item in expected_by_id.items()
            if video_id and item is not None
        }
        video_ids = sorted(expected_items)
        if not video_ids:
            return []
        removed: list[str] = []
        with self._media_item_locks.hold_many(video_ids):
            with self._lock:
                for video_id in video_ids:
                    if self.videos.get(video_id) is not expected_items[video_id]:
                        continue
                    self.videos.pop(video_id, None)
                    self.task_state.pop(video_id, None)
                    self._last_progress_emit_at.pop(video_id, None)
                    removed.append(video_id)
        if removed and publish:
            self._publish_change(
                "videos.remove_many",
                {"video_ids": list(removed), "count": len(removed)},
            )
        return removed

    def remove_videos(self, video_ids, *, publish: bool = True) -> list[str]:
        """删除视频项时同步清理任务进度节流状态，避免残留进度影响同 ID 新任务。"""
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
        """批量替换列表快照，并清除不再存在视频的派生任务状态。"""
        with self._lock:
            coordinated_ids = set(self.videos) | set(videos)
        with self._media_item_locks.hold_many(coordinated_ids):
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
        """对中间进度做节流，但 0/100 必须放行，保证开始和完成态不会丢。"""
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
        """写入 UI 环形日志；普通追加会被短延迟合并，减少高频日志刷新压力。"""
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
            # ID 单调递增且不随环形缓冲淘汰重排，前端才能稳定保持选中行。
            self._next_log_sequence += 1
            entry["id"] = f"runtime-log:{self._next_log_sequence}"
            self.log_buffer.append(entry)
            count = len(self.log_buffer)
        if topic == "logs.append":
            self._schedule_log_publish(count)
        else:
            self._publish_change(topic, {"count": count})
        return entry

    def configure_log_buffer(self, max_entries: int) -> int:
        """调整 UI 环形日志容量，只保留最近记录，避免设置变小时旧日志撑爆页面。"""
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
        """取消尚未发出的异步通知；仅关闭自己创建的缓存服务。"""
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
        """发布状态变化事件，并用线程局部计数防止订阅者递归触发无限广播。"""
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
        """把多条日志追加合并成一次变更事件，避免日志洪峰导致表格反复重绘。"""
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
        """从快照重建 VideoItem，返回给调用方时避免暴露内部可变对象。"""
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
