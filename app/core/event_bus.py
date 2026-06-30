"""Thread-safe in-process event bus for desktop/frontend orchestration."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

MAX_PUBLISH_DEPTH = 16
LOCK_WARN_SECONDS = 1.0
HANDLER_WARN_SECONDS = 0.2

class EventBus:
    """Small publish/subscribe bus used to decouple workers, reducers and UI."""

    MAX_PUBLISH_DEPTH = MAX_PUBLISH_DEPTH

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)
        self._publish_depth = contextvars.ContextVar("publish_depth", default=0)
        self._history: deque[dict[str, Any]] = deque(maxlen=100)
        self._topic_publish_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))

    @contextmanager
    def _locked(self, operation: str):
        wait_started = time.monotonic()
        self._lock.acquire()
        acquired_at = time.monotonic()
        waited = acquired_at - wait_started
        if waited > LOCK_WARN_SECONDS:
            self._logger.warning("EventBus lock wait %.3fs during %s", waited, operation)
        try:
            yield
        finally:
            held = time.monotonic() - acquired_at
            self._lock.release()
            if held > LOCK_WARN_SECONDS:
                self._logger.warning("EventBus lock held %.3fs during %s", held, operation)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        with self._locked("subscribe"):
            self._subscribers[topic].append(handler)
        return handler

    def unsubscribe(self, topic: str, handler: Callable[[Any], None] | None = None) -> None:
        with self._locked("unsubscribe"):
            if handler is None:
                self._subscribers.pop(topic, None)
                return
            handlers = self._subscribers.get(topic, [])
            self._subscribers[topic] = [registered for registered in handlers if registered != handler]
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)

    def publish(self, topic: str, payload: Any = None) -> None:
        now = time.monotonic()
        depth = self._publish_depth.get()
        with self._locked("publish.snapshot"):
            storm_count = self._record_topic_publish_locked(topic, now)
            if depth >= self.MAX_PUBLISH_DEPTH:
                handlers = None
            else:
                handlers = list(self._subscribers.get(topic, ()))
                self._history.append(
                    {
                        "topic": topic,
                        "payload": payload,
                        "timestamp": time.time(),
                        "thread_id": threading.get_ident(),
                    }
                )
        if storm_count is not None:
            self._logger.warning(
                "EventBus storm detected for topic %s (%d publishes in 1s)",
                topic,
                storm_count,
            )
        if handlers is None:
            self._logger.warning(
                "EventBus publish suppressed for topic %s because recursion depth reached %s",
                topic,
                depth,
            )
            return
        self._publish_depth.set(depth + 1)
        try:
            for handler in handlers:
                started = time.monotonic()
                try:
                    handler(payload)
                except Exception:  # pragma: no cover - defensive isolation
                    self._logger.exception("EventBus handler failed for topic %s", topic)
                finally:
                    elapsed = time.monotonic() - started
                    if elapsed > HANDLER_WARN_SECONDS:
                        self._logger.warning(
                            "EventBus slow handler %.3fs for topic %s: %r",
                            elapsed,
                            topic,
                            handler,
                        )
        finally:
            self._publish_depth.set(depth)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._locked("snapshot"):
            return [dict(item) for item in self._history]

    def _record_topic_publish_locked(self, topic: str, now: float) -> int | None:
        recent_times = self._topic_publish_times[topic]
        while recent_times and now - recent_times[0] > 1.0:
            recent_times.popleft()
        storm_count = len(recent_times) if len(recent_times) >= 5 else None
        recent_times.append(now)
        return storm_count
