"""Thread-safe in-process event bus for desktop/frontend orchestration."""

from __future__ import annotations

import contextvars
import logging
import queue
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
        self._async_subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)
        self._publish_depth = contextvars.ContextVar("publish_depth", default=0)
        self._history: deque[dict[str, Any]] = deque(maxlen=100)
        self._topic_publish_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._async_queue: queue.Queue[tuple[str, Any, Callable[[Any], None]] | None] = queue.Queue(maxsize=1024)
        self._async_thread: threading.Thread | None = None
        self._async_shutdown = False

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

    def subscribe_async(self, topic: str, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        """Subscribe a handler that must not run on the publisher thread."""
        with self._locked("subscribe_async"):
            self._async_subscribers[topic].append(handler)
            self._ensure_async_worker_locked()
        return handler

    def unsubscribe(self, topic: str, handler: Callable[[Any], None] | None = None) -> None:
        with self._locked("unsubscribe"):
            if handler is None:
                self._subscribers.pop(topic, None)
                self._async_subscribers.pop(topic, None)
                return
            handlers = self._subscribers.get(topic, [])
            self._subscribers[topic] = [registered for registered in handlers if registered != handler]
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)
            async_handlers = self._async_subscribers.get(topic, [])
            self._async_subscribers[topic] = [
                registered for registered in async_handlers if registered != handler
            ]
            if not self._async_subscribers[topic]:
                self._async_subscribers.pop(topic, None)

    def publish(self, topic: str, payload: Any = None) -> None:
        now = time.monotonic()
        depth = self._publish_depth.get()
        with self._locked("publish.snapshot"):
            storm_count = self._record_topic_publish_locked(topic, now)
            if depth >= self.MAX_PUBLISH_DEPTH:
                handlers = None
                async_handlers = ()
            else:
                handlers = list(self._subscribers.get(topic, ()))
                async_handlers = tuple(self._async_subscribers.get(topic, ()))
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
            self._enqueue_async_handlers(topic, payload, async_handlers)
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

    def shutdown(self) -> None:
        with self._locked("shutdown"):
            self._async_shutdown = True
            thread = self._async_thread
            self._async_thread = None
        if thread is None:
            return
        try:
            self._async_queue.put_nowait(None)
        except queue.Full:
            pass
        thread.join(timeout=1.0)
        self._drain_async_queue()

    def _record_topic_publish_locked(self, topic: str, now: float) -> int | None:
        recent_times = self._topic_publish_times[topic]
        while recent_times and now - recent_times[0] > 1.0:
            recent_times.popleft()
        storm_count = len(recent_times) if len(recent_times) >= 5 else None
        recent_times.append(now)
        return storm_count

    def _ensure_async_worker_locked(self) -> None:
        if self._async_thread is not None and self._async_thread.is_alive():
            return
        self._async_shutdown = False
        self._async_thread = threading.Thread(
            target=self._run_async_handlers,
            name="event-bus-async-handlers",
            daemon=True,
        )
        self._async_thread.start()

    def _enqueue_async_handlers(
        self,
        topic: str,
        payload: Any,
        handlers: tuple[Callable[[Any], None], ...],
    ) -> None:
        for handler in handlers:
            try:
                self._async_queue.put_nowait((topic, payload, handler))
            except queue.Full:
                self._logger.warning("EventBus async handler queue full for topic %s", topic)
                return

    def _run_async_handlers(self) -> None:
        while True:
            item = self._async_queue.get()
            if item is None:
                return
            topic, payload, handler = item
            if self._async_shutdown:
                return
            started = time.monotonic()
            try:
                handler(payload)
            except Exception:  # pragma: no cover - defensive isolation
                self._logger.exception("EventBus async handler failed for topic %s", topic)
            finally:
                elapsed = time.monotonic() - started
                if elapsed > HANDLER_WARN_SECONDS:
                    self._logger.warning(
                        "EventBus slow async handler %.3fs for topic %s: %r",
                        elapsed,
                        topic,
                        handler,
                    )

    def _drain_async_queue(self) -> None:
        while True:
            try:
                self._async_queue.get_nowait()
            except queue.Empty:
                return
