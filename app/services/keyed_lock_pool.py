"""Bounded keyed locks for short-lived per-resource critical sections."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass
class _LockEntry:
    lock: threading.RLock
    users: int = 0


class KeyedLockPool:
    """Provide reusable per-key locks without retaining inactive keys forever."""

    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._entries: dict[str, _LockEntry] = {}

    @contextmanager
    def hold(self, key: object) -> Iterator[None]:
        normalized = str(key or "")
        with self._guard:
            entry = self._entries.get(normalized)
            if entry is None:
                entry = _LockEntry(threading.RLock())
                self._entries[normalized] = entry
            entry.users += 1
        entry.lock.acquire()
        try:
            yield
        finally:
            entry.lock.release()
            with self._guard:
                entry.users -= 1
                if entry.users == 0 and self._entries.get(normalized) is entry:
                    self._entries.pop(normalized, None)

    @contextmanager
    def hold_many(self, keys: Iterable[object]) -> Iterator[None]:
        normalized = sorted({str(key or "") for key in keys if str(key or "")})
        with ExitStack() as stack:
            for key in normalized:
                stack.enter_context(self.hold(key))
            yield
