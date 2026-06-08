"""Lightweight callback signal for non-Qt runtime paths."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class CallbackSignal:
    """A tiny thread-safe signal helper with a Qt-like API surface."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable[..., Any], *_args: Any) -> Callable[..., Any]:
        """Register a callback.

        Extra positional arguments are ignored so existing `.connect(cb, Qt.ConnectionType...)`
        call sites can be simplified incrementally without breaking compatibility.
        """
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
        """Invoke all currently registered callbacks."""
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            callback(*args, **kwargs)
