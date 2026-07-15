"""基于 QTimer 的 UI 刷新合并器。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal

from app.services.frontend_event_aggregator import FrontendEventPriority, priority_for_topic

class UiUpdateScheduler(QObject):
    """收集脏 `topic`，并按固定节奏批量刷新 UI。"""

    _schedule_requested = pyqtSignal(bool)

    def __init__(
        self,
        *,
        interval_ms: int = 100,
        on_flush: Callable[[set[str]], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_flush = on_flush
        self._lock = threading.RLock()
        self._dirty_topics: set[str] = set()
        self._scheduled_count = 0
        self._flush_count = 0
        self._coalesced_count = 0
        self._last_flush_duration_ms = 0.0
        self._last_dirty_topics: list[str] = []
        self._interval_ms = int(interval_ms)
        self._flush_scheduled = False
        self._force_flush_requested = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._flush)
        self._schedule_requested.connect(self._drain_schedule, Qt.ConnectionType.QueuedConnection)

    def schedule(self, topic: str = "frontend", *, force: bool = False) -> None:
        """记录一次刷新请求；关键 `topic` 会提升为立即刷新。"""

        priority = priority_for_topic(topic)
        force = force or priority == FrontendEventPriority.CRITICAL
        with self._lock:
            already_dirty = topic in self._dirty_topics
            self._dirty_topics.add(topic)
            self._scheduled_count += 1
            if already_dirty:
                self._coalesced_count += 1
            if force:
                self._force_flush_requested = True
            should_signal = force or not self._flush_scheduled
            if should_signal:
                self._flush_scheduled = True
        if force:
            self._schedule_requested.emit(True)
            return
        if should_signal:
            self._schedule_requested.emit(False)

    def _drain_schedule(self, force: bool) -> None:
        """在 Qt 主线程启动/触发 timer，避免跨线程直接操作 QTimer。"""

        with self._lock:
            force = bool(force or self._force_flush_requested)
            has_dirty_topics = bool(self._dirty_topics)
        if not has_dirty_topics:
            with self._lock:
                self._flush_scheduled = False
                self._force_flush_requested = False
            return
        if force:
            self._timer.stop()
            self._flush()
            return
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        with self._lock:
            self._dirty_topics.clear()
            self._flush_scheduled = False
            self._force_flush_requested = False

    def set_interval_ms(self, interval_ms: int) -> None:
        self._interval_ms = max(16, int(interval_ms))
        self._timer.setInterval(self._interval_ms)

    def metrics(self) -> dict[str, object]:
        with self._lock:
            return {
                "interval_ms": self._interval_ms,
                "scheduled_count": self._scheduled_count,
                "flush_count": self._flush_count,
                "coalesced_count": self._coalesced_count,
                "last_flush_duration_ms": self._last_flush_duration_ms,
                "last_dirty_topics": list(self._last_dirty_topics),
                "pending_topics": sorted(self._dirty_topics),
            }

    def _flush(self) -> None:

        with self._lock:
            if not self._dirty_topics:
                self._flush_scheduled = False
                self._force_flush_requested = False
                return
            topics = set(self._dirty_topics)
            self._dirty_topics.clear()
            self._flush_scheduled = False
            self._force_flush_requested = False
        started = time.perf_counter()
        self._on_flush(topics)
        duration_ms = (time.perf_counter() - started) * 1000
        with self._lock:
            self._flush_count += 1
            self._last_flush_duration_ms = duration_ms
            self._last_dirty_topics = sorted(topics)
