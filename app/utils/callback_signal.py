"""Lightweight callback signal for non-Qt runtime paths."""

from __future__ import annotations

import threading
import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from PyQt6.QtWidgets import QWidget
except Exception:  # pragma: no cover - PyQt may be absent in some entry paths
    QWidget = None

class CallbackSignal:
    """A tiny thread-safe signal helper with a Qt-like API surface."""

    SLOW_CALLBACK_SECONDS = 0.05

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def connect(self, callback: Callable[..., Any], *_args: Any) -> Callable[..., Any]:
        """Register a callback.

        Extra positional arguments are ignored so existing `.connect(cb, Qt.ConnectionType...)`
        call sites can be simplified incrementally without breaking compatibility.
        """
        bound_self = getattr(callback, "__self__", None)
        if QWidget is not None and isinstance(bound_self, QWidget):
            raise TypeError("worker signals must not connect directly to QWidget methods; route through EventBus/bridge")
        with self._lock:
            self._callbacks.append(callback)
        return callback

    def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
        """Remove a single callback or clear the signal entirely."""
        with self._lock:
            if callback is None:
                self._callbacks.clear()
                return
            self._callbacks = [registered for registered in self._callbacks if registered != callback]

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Invoke all currently registered callbacks.

        Worker signals must isolate subscribers: one failing observer should not
        abort the download/spider thread or prevent later observers from seeing
        the same event.
        """
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            started = time.perf_counter()
            try:
                callback(*args, **kwargs)
            except Exception:  # pragma: no cover - logging branch is covered via tests
                self._logger.exception("CallbackSignal subscriber failed: %r", callback)
                continue
            elapsed = time.perf_counter() - started
            if elapsed >= self.SLOW_CALLBACK_SECONDS:
                self._logger.warning(
                    "CallbackSignal subscriber was slow: callback=%r elapsed_ms=%.2f",
                    callback,
                    elapsed * 1000,
                )
