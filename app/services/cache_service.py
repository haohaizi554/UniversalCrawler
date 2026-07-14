"""前端状态缓存：短期内存缓存 + 安全 SQLite 持久化。"""

from __future__ import annotations

import base64
import json
import math
import sqlite3
import threading
import time
from contextlib import closing
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_data_root


_PERSISTENT_FORMAT_PREFIX = b"UCACHE2\n"
_PERSISTENT_TYPE_KEY = "__ucache_type__"
_MAX_PERSISTENT_PAYLOAD_BYTES = 64 * 1024 * 1024
_MAX_PERSISTENT_DEPTH = 64


def _pack_persistent_value(value: Any, *, depth: int = 0) -> Any:
    """把缓存值收敛到不会触发对象构造的 JSON 类型树。"""
    if depth > _MAX_PERSISTENT_DEPTH:
        raise ValueError("persistent cache value is nested too deeply")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {_PERSISTENT_TYPE_KEY: "float", "value": repr(value)}
    if isinstance(value, bytes):
        return {
            _PERSISTENT_TYPE_KEY: "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, list):
        return {
            _PERSISTENT_TYPE_KEY: "list",
            "items": [_pack_persistent_value(item, depth=depth + 1) for item in value],
        }
    if isinstance(value, tuple):
        return {
            _PERSISTENT_TYPE_KEY: "tuple",
            "items": [_pack_persistent_value(item, depth=depth + 1) for item in value],
        }
    if isinstance(value, (set, frozenset)):
        return {
            _PERSISTENT_TYPE_KEY: "frozenset" if isinstance(value, frozenset) else "set",
            "items": [_pack_persistent_value(item, depth=depth + 1) for item in value],
        }
    if isinstance(value, dict):
        # 键也按同一白名单编码，避免 JSON 强制把 int/tuple 键转换为字符串。
        return {
            _PERSISTENT_TYPE_KEY: "dict",
            "items": [
                [
                    _pack_persistent_value(key, depth=depth + 1),
                    _pack_persistent_value(item, depth=depth + 1),
                ]
                for key, item in value.items()
            ],
        }
    raise TypeError(f"unsupported persistent cache value type: {type(value).__name__}")


def _unpack_persistent_value(value: Any, *, depth: int = 0) -> Any:
    """严格恢复白名单类型；任何未知标签都按损坏缓存处理。"""
    if depth > _MAX_PERSISTENT_DEPTH:
        raise ValueError("persistent cache payload is nested too deeply")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if not isinstance(value, dict):
        raise ValueError("persistent cache payload contains an untagged container")

    kind = value.get(_PERSISTENT_TYPE_KEY)
    if kind == "float" and set(value) == {_PERSISTENT_TYPE_KEY, "value"}:
        special = value.get("value")
        if special == "nan":
            return float("nan")
        if special == "inf":
            return float("inf")
        if special == "-inf":
            return float("-inf")
        raise ValueError("persistent cache payload contains an invalid float")
    if kind == "bytes" and set(value) == {_PERSISTENT_TYPE_KEY, "value"}:
        encoded = value.get("value")
        if not isinstance(encoded, str):
            raise ValueError("persistent cache byte payload is not text")
        return base64.b64decode(encoded, validate=True)

    if set(value) != {_PERSISTENT_TYPE_KEY, "items"} or not isinstance(value.get("items"), list):
        raise ValueError("persistent cache container has an invalid shape")
    items = value["items"]
    if kind == "list":
        return [_unpack_persistent_value(item, depth=depth + 1) for item in items]
    if kind == "tuple":
        return tuple(_unpack_persistent_value(item, depth=depth + 1) for item in items)
    if kind in {"set", "frozenset"}:
        unpacked = {_unpack_persistent_value(item, depth=depth + 1) for item in items}
        return frozenset(unpacked) if kind == "frozenset" else unpacked
    if kind == "dict":
        result: dict[Any, Any] = {}
        for pair in items:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("persistent cache mapping entry has an invalid shape")
            key = _unpack_persistent_value(pair[0], depth=depth + 1)
            item = _unpack_persistent_value(pair[1], depth=depth + 1)
            result[key] = item
        return result
    raise ValueError(f"persistent cache payload has an unknown type tag: {kind!r}")


def _encode_persistent_value(value: Any) -> bytes:
    encoded = json.dumps(
        _pack_persistent_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    payload = _PERSISTENT_FORMAT_PREFIX + encoded
    if len(payload) > _MAX_PERSISTENT_PAYLOAD_BYTES:
        raise ValueError("persistent cache payload is too large")
    return payload


def _decode_persistent_value(payload: Any) -> Any:
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    if not isinstance(payload, bytes):
        raise ValueError("persistent cache payload is not bytes")
    if len(payload) > _MAX_PERSISTENT_PAYLOAD_BYTES:
        raise ValueError("persistent cache payload is too large")
    if not payload.startswith(_PERSISTENT_FORMAT_PREFIX):
        raise ValueError("persistent cache payload uses an unsupported legacy format")
    decoded = json.loads(payload[len(_PERSISTENT_FORMAT_PREFIX) :].decode("utf-8"))
    return _unpack_persistent_value(decoded)


try:
    CachetoolsTTLCache = getattr(import_module("cachetools"), "TTLCache")  # noqa: B009 - optional runtime module
except Exception:  # pragma: no cover - fallback keeps runtime optional
    CachetoolsTTLCache = None

class _FallbackTTLCache(dict):
    """cachetools 不可用时的最小 TTL 实现，保证运行时依赖可选。"""

    def __init__(self, maxsize: int, ttl: float) -> None:
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._expires: dict[str, float] = {}

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
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
    """混合缓存：热路径读内存，需要跨启动保留时再落盘。"""

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
        self._operation_lock = threading.RLock()
        self._memory_lock = threading.RLock()
        cache_cls = CachetoolsTTLCache or _FallbackTTLCache
        self._memory_cache = cache_cls(maxsize=memory_maxsize, ttl=memory_ttl_seconds)
        self._db_lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._db_lock:
            with closing(sqlite3.connect(self._db_path)) as conn:
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
        """优先读内存，未命中再读持久化；返回深拷贝避免外部修改缓存体。"""
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
        """写缓存；persist=False 只进内存，persist=True 才写安全 SQLite。"""
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
            with self._db_lock:
                try:
                    with closing(sqlite3.connect(self._db_path)) as conn:
                        conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                        conn.commit()
                except Exception as exc:
                    debug_logger.log_exception(
                        "CacheService",
                        "delete_sqlite",
                        exc,
                        details={"key": key, "db_path": str(self._db_path)},
                    )

    def close(self) -> None:
        """保留统一生命周期接口；SQLite 连接均按操作即时关闭。"""

    def _read_local_persistent(self, key: str) -> tuple[Any, float | None] | None:
        """持久化只走受控 SQLite BLOB，不委托第三方对象反序列化器。"""
        return self._read_persistent(key)

    def _write_persistent(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None,
        expires_at: float | None,
    ) -> None:
        """先编码为安全类型树，再原子提交到 SQLite。"""
        payload = _encode_persistent_value(value)
        self._write_sqlite_persistent(key, payload, expires_at=expires_at)

    def _write_sqlite_persistent(self, key: str, payload: bytes, *, expires_at: float | None) -> None:
        with self._db_lock:
            with closing(sqlite3.connect(self._db_path)) as conn:
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
        """读取 SQLite 兜底缓存；旧格式或损坏条目直接删除，不做对象反序列化。"""
        with self._db_lock:
            with closing(sqlite3.connect(self._db_path)) as conn:
                row = conn.execute("SELECT value, expires_at FROM cache_entries WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return _decode_persistent_value(row[0]), row[1]
        except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
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
                with closing(sqlite3.connect(self._db_path)) as conn:
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
        except Exception as exc:
            raise TypeError("cache values must support isolated deep copies") from exc
