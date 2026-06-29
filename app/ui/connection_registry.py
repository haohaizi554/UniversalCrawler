"""Lifecycle-aware Qt signal connection registry."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any

from PyQt6.QtCore import QMetaObject, QObject

_LOGGER = logging.getLogger(__name__)

class ConnectionRegistry:
    """Keep track of signal-slot connections so they can be disconnected cleanly."""

    def __init__(self) -> None:
        self._connections: list[tuple[Any, QMetaObject.Connection, Callable[..., Any]]] = []

    def connect(
        self,
        signal: Any,
        slot: Callable[..., Any],
        connection_type: Any = None,
    ) -> QMetaObject.Connection:
        if connection_type is None:
            connection = signal.connect(slot)
        else:
            connection = signal.connect(slot, connection_type)
        self._connections.append((signal, connection, slot))
        return connection

    @contextmanager
    def scoped(self) -> Iterator["ConnectionRegistry"]:
        start = len(self._connections)
        try:
            yield self
        finally:
            self._disconnect_from(start)

    def disconnect_all(self) -> None:
        self._disconnect_from(0)

    def _disconnect_from(self, start: int) -> None:
        pending = self._connections[start:]
        del self._connections[start:]
        for signal, connection, slot in reversed(pending):
            self._disconnect_one(signal, connection, slot)

    @staticmethod
    def _disconnect_one(signal: Any, connection: QMetaObject.Connection, slot: Callable[..., Any]) -> None:
        try:
            QObject.disconnect(connection)
            return
        except Exception:
            _LOGGER.warning("QObject.disconnect(connection) failed; trying signal.disconnect(connection)", exc_info=True)
        try:
            signal.disconnect(connection)
            return
        except Exception:
            _LOGGER.warning("signal.disconnect(connection) failed; trying signal.disconnect(slot)", exc_info=True)
        try:
            signal.disconnect(slot)
        except Exception:
            _LOGGER.warning("signal.disconnect(slot) failed", exc_info=True)

    def __enter__(self) -> "ConnectionRegistry":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.disconnect_all()
