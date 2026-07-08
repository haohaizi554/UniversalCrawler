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
from dataclasses import dataclass
from typing import Any

MAX_PUBLISH_DEPTH = 16
LOCK_WARN_SECONDS = 1.0
HANDLER_WARN_SECONDS = 0.2
ASYNC_NOISY_TOPICS = frozenset(
    {"app_state.changed", "videos.update", "videos.metadata", "video_state_changed", "task_progress", "logs.append", "log"}
)
ASYNC_TOPIC_LATEST_KEYS = frozenset({"logs.append"})


@dataclass(frozen=True, slots=True)
class _AsyncTask:
    topic: str
    payload: Any
    handler: Callable[[Any], None]


@dataclass(frozen=True, slots=True)
class _AsyncTaskKey:
    key: tuple[int, str, str, str]


class EventBus:
    """Small publish/subscribe bus used to decouple workers, reducers and UI."""

    MAX_PUBLISH_DEPTH = MAX_PUBLISH_DEPTH

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._async_idle_condition = threading.Condition(self._lock)
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._async_subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)
        self._publish_depth = contextvars.ContextVar("publish_depth", default=0)
        self._history: deque[dict[str, Any]] = deque(maxlen=100)
        self._topic_publish_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._async_queue: queue.Queue[_AsyncTask | _AsyncTaskKey | None] = queue.Queue(maxsize=1024)
        self._async_pending_latest: dict[tuple[int, str, str, str], _AsyncTask] = {}
        self._async_enqueued_latest_keys: set[tuple[int, str, str, str]] = set()
        self._async_inflight = 0
        self._async_thread: threading.Thread | None = None
        self._async_thread_id: int | None = None
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

    def wait_for_async_idle(self, timeout: float | None = None) -> bool:
        """Wait until queued async handlers have finished without pumping UI events."""
        if threading.get_ident() == self._async_thread_id:
            return False
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._async_idle_condition:
            while self._async_inflight > 0:
                if deadline is None:
                    self._async_idle_condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._async_idle_condition.wait(remaining)
            return True

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
            if self._enqueue_latest_async_handler(topic, payload, handler):
                continue
            self._track_async_task_enqueued()
            try:
                self._async_queue.put_nowait(_AsyncTask(topic, payload, handler))
            except queue.Full:
                self._track_async_task_finished()
                self._logger.warning("EventBus async handler queue full for topic %s", topic)
                return

    def _enqueue_latest_async_handler(
        self,
        topic: str,
        payload: Any,
        handler: Callable[[Any], None],
    ) -> bool:
        key = self._async_latest_key(topic, payload, handler)
        if key is None:
            return False
        task = _AsyncTask(topic, payload, handler)
        with self._locked("async.latest"):
            self._async_pending_latest[key] = task
            if key in self._async_enqueued_latest_keys:
                return True
            self._async_enqueued_latest_keys.add(key)
            self._async_inflight += 1
            self._async_idle_condition.notify_all()
        try:
            self._async_queue.put_nowait(_AsyncTaskKey(key))
        except queue.Full:
            with self._locked("async.latest.full"):
                self._async_pending_latest.pop(key, None)
                self._async_enqueued_latest_keys.discard(key)
                self._async_inflight = max(0, self._async_inflight - 1)
                self._async_idle_condition.notify_all()
            self._logger.warning("EventBus async handler queue full for topic %s", topic)
        return True

    def _track_async_task_enqueued(self) -> None:
        with self._async_idle_condition:
            self._async_inflight += 1
            self._async_idle_condition.notify_all()

    def _track_async_task_finished(self) -> None:
        with self._async_idle_condition:
            self._async_inflight = max(0, self._async_inflight - 1)
            self._async_idle_condition.notify_all()

    @staticmethod
    def _async_latest_key(
        topic: str,
        payload: Any,
        handler: Callable[[Any], None],
    ) -> tuple[int, str, str, str] | None:
        normalized = str(topic or "")
        if normalized not in ASYNC_NOISY_TOPICS or not isinstance(payload, dict):
            return None
        topic_key = EventBus._async_topic_latest_key(normalized, payload)
        if topic_key is not None:
            return (id(handler), normalized, "topic", topic_key)
        entity_id = (
            payload.get("video_id")
            or payload.get("id")
            or payload.get("entity_id")
            or payload.get("trace_id")
        )
        if not entity_id:
            return None
        return (id(handler), normalized, type(entity_id).__name__, str(entity_id))

    @staticmethod
    def _async_topic_latest_key(topic: str, payload: dict[str, Any]) -> str | None:
        if topic in ASYNC_TOPIC_LATEST_KEYS:
            return topic
        if topic == "app_state.changed":
            inner_topic = str(payload.get("topic") or "")
            if inner_topic in ASYNC_TOPIC_LATEST_KEYS:
                return inner_topic
        return None

    def _run_async_handlers(self) -> None:
        self._async_thread_id = threading.get_ident()
        try:
            while True:
                item = self._async_queue.get()
                if item is None:
                    return
                try:
                    task = self._resolve_async_task(item)
                    if task is None:
                        continue
                    if self._async_shutdown:
                        return
                    started = time.monotonic()
                    try:
                        task.handler(task.payload)
                    except Exception:  # pragma: no cover - defensive isolation
                        self._logger.exception("EventBus async handler failed for topic %s", task.topic)
                    finally:
                        elapsed = time.monotonic() - started
                        if elapsed > HANDLER_WARN_SECONDS:
                            self._logger.warning(
                                "EventBus slow async handler %.3fs for topic %s: %r",
                                elapsed,
                                task.topic,
                                task.handler,
                            )
                finally:
                    self._track_async_task_finished()
        finally:
            self._async_thread_id = None

    def _resolve_async_task(self, item: _AsyncTask | _AsyncTaskKey) -> _AsyncTask | None:
        if isinstance(item, _AsyncTask):
            return item
        with self._locked("async.latest.resolve"):
            self._async_enqueued_latest_keys.discard(item.key)
            return self._async_pending_latest.pop(item.key, None)

    def _drain_async_queue(self) -> None:
        with self._locked("async.drain"):
            self._async_pending_latest.clear()
            self._async_enqueued_latest_keys.clear()
            self._async_inflight = 0
            self._async_idle_condition.notify_all()
        while True:
            try:
                self._async_queue.get_nowait()
            except queue.Empty:
                return
