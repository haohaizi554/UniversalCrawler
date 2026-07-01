from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class MetadataProbeQueue:
    """Debounced batch queue for completed-media metadata probes."""

    def __init__(
        self,
        *,
        retry_callback: Callable[[str, str], bool],
        key_factory: Callable[[str, str], str],
        batch_size_provider: Callable[[], int],
        closed_checker: Callable[[], bool] | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        delay_seconds: float = 0.25,
    ) -> None:
        self._retry_callback = retry_callback
        self._key_factory = key_factory
        self._batch_size_provider = batch_size_provider
        self._closed_checker = closed_checker or (lambda: False)
        self._timer_factory = timer_factory
        self._delay_seconds = delay_seconds
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[str, str]] = {}
        self._timer: Any | None = None
        self._generation = 0
        self._closed = False

    @property
    def pending(self) -> dict[str, tuple[str, str]]:
        with self._lock:
            return dict(self._pending)

    @property
    def timer(self) -> Any | None:
        with self._lock:
            return self._timer

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def queue(self, video_id: str, source_path: str) -> None:
        video_id = str(video_id or "")
        source_path = str(source_path or "")
        if not video_id or not source_path:
            return

        key = self._key_factory(video_id, source_path)
        with self._lock:
            if self._closed or self._closed_checker():
                return
            self._pending[key] = (video_id, source_path)
            if self._timer is None:
                self._schedule_locked()

    def drain(self, generation: int | None = None) -> None:
        with self._lock:
            if self._closed or self._closed_checker() or (
                generation is not None and generation != self._generation
            ):
                return
            self._timer = None
            batch_size = max(1, int(self._batch_size_provider() or 1))
            items = list(self._pending.items())[:batch_size]
            for key, _value in items:
                self._pending.pop(key, None)

        for _key, (video_id, source_path) in items:
            if self._closed_checker():
                return
            self._retry_callback(video_id, source_path)

        with self._lock:
            if not self._closed and not self._closed_checker() and self._pending and self._timer is None:
                self._schedule_locked()

    def drop_for(self, video_id: str) -> None:
        prefix = f"{str(video_id or '')}\0"
        with self._lock:
            for key in list(self._pending):
                if key.startswith(prefix):
                    self._pending.pop(key, None)

    def cancel(self, *, close: bool = False) -> None:
        with self._lock:
            self._generation += 1
            if close:
                self._closed = True
            timer = self._timer
            self._timer = None
            self._pending.clear()
        if timer is not None:
            timer.cancel()

    def _schedule_locked(self) -> None:
        generation = self._generation
        timer = self._timer_factory(self._delay_seconds, lambda: self.drain(generation))
        try:
            timer.daemon = True
        except Exception:
            pass
        self._timer = timer
        timer.start()
