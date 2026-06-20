"""Thread-safe in-process event bus for desktop/frontend orchestration."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

class EventBus:
    """Small publish/subscribe bus used to decouple workers, reducers and UI."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        with self._lock:
            self._subscribers[topic].append(handler)
        return handler

    def unsubscribe(self, topic: str, handler: Callable[[Any], None] | None = None) -> None:
        with self._lock:
            if handler is None:
                self._subscribers.pop(topic, None)
                return
            handlers = self._subscribers.get(topic, [])
            self._subscribers[topic] = [registered for registered in handlers if registered != handler]
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)

    def publish(self, topic: str, payload: Any = None) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
        for handler in handlers:
            try:
                handler(payload)
            except Exception:  # pragma: no cover - defensive isolation
                self._logger.exception("EventBus handler failed for topic %s", topic)
