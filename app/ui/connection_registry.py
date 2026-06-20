"""Lifecycle-aware Qt signal connection registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

class ConnectionRegistry:
    """Keep track of signal-slot connections so they can be disconnected cleanly."""

    def __init__(self) -> None:
        self._connections: list[tuple[Any, Callable[..., Any]]] = []

    def connect(self, signal: Any, slot: Callable[..., Any]) -> Callable[..., Any]:
        signal.connect(slot)
        self._connections.append((signal, slot))
        return slot

    def disconnect_all(self) -> None:
        while self._connections:
            signal, slot = self._connections.pop()
            try:
                signal.disconnect(slot)
            except Exception:
                continue
