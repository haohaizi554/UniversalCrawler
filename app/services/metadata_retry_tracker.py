from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class MetadataRetryTracker:
    """记录空元数据探测失败次数，并为单个视频安排有上限的延迟重试。"""

    def __init__(
        self,
        *,
        retry_callback: Callable[[str, str], bool],
        event_callback: Callable[[str, dict[str, Any]], None],
        key_factory: Callable[[str, str], str],
        max_retries_provider: Callable[[], int],
        delay_provider: Callable[[], float],
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
    ) -> None:
        self._retry_callback = retry_callback
        self._event_callback = event_callback
        self._key_factory = key_factory
        self._max_retries_provider = max_retries_provider
        self._delay_provider = delay_provider
        self._timer_factory = timer_factory
        self._lock = threading.RLock()
        self._timers: dict[str, Any] = {}
        self._empty_failures: dict[str, int] = {}

    @property
    def timers(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._timers)

    @property
    def empty_failures(self) -> dict[str, int]:
        with self._lock:
            return dict(self._empty_failures)

    def record_empty_failure(self, video_id: str, source_path: str) -> int:
        """按 video/path 维度累计失败，避免同一视频换文件后沿用旧计数。"""
        failure_key = self._key_factory(video_id, source_path)
        with self._lock:
            attempts = self._empty_failures.get(failure_key, 0) + 1
            self._empty_failures[failure_key] = attempts
            return attempts

    def exhausted(self, failure_key: str) -> bool:
        max_retries = max(1, int(self._max_retries_provider() or 1))
        with self._lock:
            return self._empty_failures.get(failure_key, 0) >= max_retries

    def clear_failures(self, video_id: str | None = None, source_path: str | None = None) -> None:
        with self._lock:
            if not video_id:
                self._empty_failures.clear()
                return
            if source_path:
                self._empty_failures.pop(self._key_factory(video_id, source_path), None)
                return
            prefix = f"{str(video_id)}\0"
            for key in list(self._empty_failures):
                if key.startswith(prefix):
                    self._empty_failures.pop(key, None)

    def schedule(self, video_id: str, source_path: str) -> None:
        """同一 video_id 同时只保留一个重试 Timer，防止探测风暴。"""
        key = str(video_id or "")
        if not key:
            return
        with self._lock:
            if key in self._timers:
                return
            timer = self._timer_factory(self._retry_delay_seconds(), lambda: self._fire(key, source_path))
            try:
                timer.daemon = True
            except Exception:
                pass
            self._timers[key] = timer
            timer.start()

    def cancel(self, video_id: str) -> None:
        key = str(video_id or "")
        if not key:
            return
        with self._lock:
            timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    def cancel_all(self, *, clear_failures: bool = False) -> None:
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
            if clear_failures:
                self._empty_failures.clear()
        for timer in timers:
            timer.cancel()

    def _fire(self, video_id: str, source_path: str) -> None:
        """Timer 触发后执行回调，并把是否成功排期写回前端事件。"""
        with self._lock:
            self._timers.pop(video_id, None)
        retried = self._retry_callback(video_id, source_path)
        self._event_callback(
            "videos.metadata",
            {"video_id": video_id, "metadata": False, "retry": True, "scheduled": retried},
        )

    def _retry_delay_seconds(self) -> float:
        try:
            delay = float(self._delay_provider() or 30.0)
        except (TypeError, ValueError):
            delay = 30.0
        return max(1.0, min(delay, 60.0)) + 0.25
