"""Bounded frontend log cache used by GUI and WebUI snapshots."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any


class FrontendLogCache:
    """Cache tail log rows without rereading large files on UI limit changes."""

    def __init__(
        self,
        *,
        cache_service: Any,
        reader: Callable[..., list[dict[str, Any]]],
        limit_provider: Callable[[], int],
        ttl_seconds: float = 1.0,
        backfill_limit: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache_service = cache_service
        self._reader = reader
        self._limit_provider = limit_provider
        self._ttl_seconds = float(ttl_seconds)
        self._backfill_limit = int(backfill_limit)
        self._clock = clock
        self._items: list[dict[str, Any]] = []
        self._at = 0.0
        self._limit = 0
        self._lock = threading.RLock()

    @staticmethod
    def normalize_limit(value: Any, *, default: int = 300) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = default
        return max(100, min(limit, 5000))

    @staticmethod
    def cache_key(limit: int) -> str:
        return f"frontend.file_log_cache.{int(limit)}"

    @property
    def items_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._items)

    @property
    def limit(self) -> int:
        with self._lock:
            return self._limit

    @property
    def cached_at(self) -> float:
        with self._lock:
            return self._at

    def invalidate(self, *, limit: Any | None = None) -> None:
        normalized_limit = self._current_limit() if limit is None else self.normalize_limit(limit)
        with self._lock:
            self._items = []
            self._at = 0.0
            self._limit = 0
        self._delete_cache_key("frontend.file_log_cache")
        self._delete_cache_key(self.cache_key(normalized_limit))

    def resize_limit(self, limit: Any) -> None:
        normalized_limit = self.normalize_limit(limit)
        with self._lock:
            if self._limit and normalized_limit < self._limit:
                self._limit = normalized_limit
                self._at = self._clock()
            if len(self._items) > normalized_limit:
                self._items = self._items[-normalized_limit:]
                self._limit = min(self._limit or normalized_limit, normalized_limit)
                self._at = self._clock()

    def merged_items(self, buffer: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        limit = self._current_limit()
        read_limit = self._next_read_limit(limit)
        if read_limit > 0:
            self._refresh_from_file(read_limit)
        file_items = self.items_snapshot
        merged = [*file_items, *[dict(item) for item in buffer]][-limit:]
        return merged

    def _current_limit(self) -> int:
        try:
            return self.normalize_limit(self._limit_provider())
        except Exception:
            return 300

    def _next_read_limit(self, limit: int) -> int:
        now = self._clock()
        with self._lock:
            if len(self._items) > limit:
                self._items = self._items[-limit:]
                if self._limit:
                    self._limit = min(self._limit, limit)
                self._at = now
            if self._limit <= 0:
                return min(limit, self._backfill_limit)
            if now - self._at >= self._ttl_seconds:
                return min(limit, max(1, self._limit, len(self._items)))
        return 0

    def _refresh_from_file(self, read_limit: int) -> None:
        cache_key = self.cache_key(read_limit)
        cached = self._cache_service.get(cache_key)
        if cached is None:
            cached = self._reader(limit=read_limit)
            self._cache_service.set(
                cache_key,
                cached,
                ttl_seconds=self._ttl_seconds,
                persist=False,
            )
        with self._lock:
            self._items = deepcopy(cached)[-read_limit:]
            self._limit = read_limit
            self._at = self._clock()

    def _delete_cache_key(self, key: str) -> None:
        delete = getattr(self._cache_service, "delete", None)
        if callable(delete):
            delete(key)
