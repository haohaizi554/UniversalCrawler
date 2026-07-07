"""Frontend-oriented cache abstractions for in-memory and local persistence."""

from __future__ import annotations

import pickle
import sqlite3
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_data_root

try:
    from cachetools import TTLCache as CachetoolsTTLCache
except Exception:  # pragma: no cover - fallback keeps runtime optional
    CachetoolsTTLCache = None

try:
    from diskcache import Cache as DiskCache
except Exception:  # pragma: no cover - SQLite fallback keeps runtime optional
    DiskCache = None

class _FallbackTTLCache(dict):
    def __init__(self, maxsize: int, ttl: float) -> None:
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._expires: dict[str, float] = {}

    def __contains__(self, key: object) -> bool:
        if key not in self._expires:
            return False
        if self._expires[key] < time.monotonic():
            self.pop(key, None)
            self._expires.pop(key, None)
            return False
        return dict.__contains__(self, key)

    def __getitem__(self, key: str) -> Any:
        if key not in self:
            raise KeyError(key)
        return dict.__getitem__(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        self._evict_expired()
        if len(self) >= self.maxsize:
            oldest = next(iter(self.keys()), None)
            if oldest is not None:
                self.pop(oldest, None)
                self._expires.pop(oldest, None)
        dict.__setitem__(self, key, value)
        self._expires[key] = time.monotonic() + self.ttl

    def pop(self, key: str, default: Any = None) -> Any:
        self._expires.pop(key, None)
        return dict.pop(self, key, default)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        for key, expires_at in list(self._expires.items()):
            if expires_at < now:
                self.pop(key, None)
                self._expires.pop(key, None)

class CacheService:
    """Hybrid cache using TTL memory cache plus SQLite persistence."""

    def __init__(
        self,
        *,
        namespace: str = "default",
        memory_ttl_seconds: float = 5.0,
        memory_maxsize: int = 256,
        cache_dir: str | None = None,
    ) -> None:
        cache_root = Path(cache_dir or (Path(user_data_root()) / "cache"))
        cache_root.mkdir(parents=True, exist_ok=True)
        self._db_path = cache_root / f"{namespace}.sqlite3"
        self._disk_cache_path = cache_root / f"{namespace}.diskcache"
        self._operation_lock = threading.RLock()
        self._memory_lock = threading.RLock()
        cache_cls = CachetoolsTTLCache or _FallbackTTLCache
        self._memory_cache = cache_cls(maxsize=memory_maxsize, ttl=memory_ttl_seconds)
        self._db_lock = threading.RLock()
        self._disk_lock = threading.RLock()
        self._disk_cache = DiskCache(str(self._disk_cache_path)) if DiskCache is not None else None
        self._init_db()

    def _init_db(self) -> None:
        with self._db_lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        key TEXT PRIMARY KEY,
                        value BLOB NOT NULL,
                        expires_at REAL
                    )
                    """
                )
                conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        with self._operation_lock:
            with self._memory_lock:
                try:
                    return self._clone_value(self._memory_cache[key])
                except KeyError:
                    pass
            record = self._read_local_persistent(key)
            if record is None:
                return default
            value, expires_at = record
            if expires_at is not None and expires_at < time.time():
                self.delete(key)
                return default
            with self._memory_lock:
                self._memory_cache[key] = self._clone_value(value)
            return self._clone_value(value)

    def set(self, key: str, value: Any, *, ttl_seconds: float | None = None, persist: bool = False) -> None:
        value_snapshot = self._clone_value(value)
        if not persist:
            with self._operation_lock:
                with self._memory_lock:
                    self._memory_cache[key] = value_snapshot
            return
        expires_at = None if ttl_seconds is None else time.time() + ttl_seconds
        with self._operation_lock:
            self._write_persistent(key, value_snapshot, ttl_seconds=ttl_seconds, expires_at=expires_at)
            with self._memory_lock:
                self._memory_cache[key] = value_snapshot

    def delete(self, key: str) -> None:
        with self._operation_lock:
            with self._memory_lock:
                self._memory_cache.pop(key, None)
            if self._disk_cache is not None:
                with self._disk_lock:
                    self._disk_cache.delete(key)
            with self._db_lock:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                    conn.commit()

    def close(self) -> None:
        with self._disk_lock:
            disk_cache = self._disk_cache
            if disk_cache is None:
                return
            try:
                disk_cache.close()
            except Exception as exc:
                debug_logger.log_exception(
                    "CacheService",
                    "close_diskcache",
                    exc,
                    details={"cache_path": str(self._disk_cache_path)},
                )
            finally:
                self._disk_cache = None

    def _read_local_persistent(self, key: str) -> tuple[Any, float | None] | None:
        if self._disk_cache is not None:
            sentinel = object()
            try:
                with self._disk_lock:
                    value = self._disk_cache.get(key, default=sentinel)
                if value is not sentinel:
                    return value, None
            except Exception as exc:
                debug_logger.log_exception(
                    "CacheService",
                    "read_diskcache",
                    exc,
                    details={"key": key, "cache_path": str(self._disk_cache_path)},
                )
        return self._read_persistent(key)

    def _write_persistent(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None,
        expires_at: float | None,
    ) -> None:
        if self._disk_cache is not None:
            with self._disk_lock:
                self._disk_cache.set(key, value, expire=ttl_seconds)
            return
        self._write_sqlite_persistent(key, value, expires_at=expires_at)

    def _write_sqlite_persistent(self, key: str, value: Any, *, expires_at: float | None) -> None:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._db_lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO cache_entries(key, value, expires_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at
                    """,
                    (key, payload, expires_at),
                )
                conn.commit()

    def _read_persistent(self, key: str) -> tuple[Any, float | None] | None:
        with self._db_lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute("SELECT value, expires_at FROM cache_entries WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return pickle.loads(row[0]), row[1]
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError, TypeError, ValueError) as exc:
            debug_logger.log_exception(
                "CacheService",
                "read_persistent",
                exc,
                details={"key": key, "db_path": str(self._db_path)},
            )
            self._delete_persistent_corrupt_entry(key)
            return None

    def _delete_persistent_corrupt_entry(self, key: str) -> None:
        try:
            with self._db_lock:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                    conn.commit()
        except sqlite3.Error as exc:
            debug_logger.log_exception(
                "CacheService",
                "delete_corrupt_entry",
                exc,
                details={"key": key, "db_path": str(self._db_path)},
            )

    @staticmethod
    def _clone_value(value: Any) -> Any:
        try:
            return deepcopy(value)
        except Exception:
            return value
