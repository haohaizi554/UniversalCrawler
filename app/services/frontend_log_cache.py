"""前端日志缓存：合并内存日志和调试日志文件尾部内容。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from app.services import frontend_log_adapter as log_adapter


@dataclass(frozen=True)
class _TailCacheState:
    cache_key: str
    path_key: str
    offset: int


class _TailLogFileReader:
    """增量读取当前调试日志，避免每次状态快照都全文件扫描。"""

    INITIAL_WINDOW_BYTES = 1024 * 1024
    MAX_WINDOW_BYTES = 8 * 1024 * 1024

    def __init__(self, path_provider: Callable[[], str | Path]) -> None:
        self._path_provider = path_provider
        self._path_key = ""
        self._offset = 0
        self._items: list[dict[str, Any]] = []
        self._initialized = False

    def reset(self) -> None:
        self._path_key = ""
        self._offset = 0
        self._items = []
        self._initialized = False

    def cache_state(self, *, limit: int) -> _TailCacheState | None:
        """用路径、大小和 mtime 生成缓存指纹；文件轮转后会自动失效。"""
        path = Path(self._path_provider())
        try:
            stat = path.stat()
            resolved = str(path.resolve())
        except OSError:
            return None
        size = max(0, int(stat.st_size))
        fingerprint = "|".join(
            [
                resolved,
                str(getattr(stat, "st_dev", "")),
                str(getattr(stat, "st_ino", "")),
                str(size),
                str(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
            ]
        )
        digest = sha256(fingerprint.encode("utf-8", errors="replace")).hexdigest()[:24]
        return _TailCacheState(
            cache_key=f"frontend.file_log_cache.tail.{digest}.{int(limit)}",
            path_key=resolved,
            offset=size,
        )

    def hydrate(self, state: _TailCacheState, items: list[dict[str, Any]], *, limit: int) -> None:
        """从持久缓存恢复尾读状态，启动后不必立刻重扫大日志。"""
        self._path_key = state.path_key
        self._offset = state.offset
        self._items = deepcopy(items[-limit:])
        self._initialized = True

    def read(self, *, limit: int) -> list[dict[str, Any]]:
        """读取新增字节；文件变小或路径变化时按尾窗重新初始化。"""
        path = Path(self._path_provider())
        try:
            stat = path.stat()
        except OSError:
            self.reset()
            return []
        size = max(0, int(stat.st_size))
        path_key = str(path.resolve())
        if not self._initialized or path_key != self._path_key or size < self._offset:
            return self._read_tail_window(path, path_key, size, limit=limit)
        if size == self._offset:
            return deepcopy(self._items[-limit:])
        text = self._read_range(path, self._offset, size - self._offset)
        self._offset = size
        parsed = log_adapter.parse_debug_log_text(text, limit=limit)
        if parsed:
            self._items = [*self._items, *parsed][-limit:]
        return deepcopy(self._items[-limit:])

    def _read_tail_window(self, path: Path, path_key: str, size: int, *, limit: int) -> list[dict[str, Any]]:
        """从文件尾部逐步扩大窗口，尽量读够 UI 需要的最近日志。"""
        window = min(size, self.INITIAL_WINDOW_BYTES)
        items: list[dict[str, Any]] = []
        while True:
            start = max(0, size - window)
            text = self._read_range(path, start, size - start)
            items = log_adapter.parse_debug_log_text(text, limit=limit)
            if len(items) >= limit or start == 0 or window >= self.MAX_WINDOW_BYTES:
                break
            window = min(size, window * 2)
        self._path_key = path_key
        self._offset = size
        self._items = deepcopy(items[-limit:])
        self._initialized = True
        return deepcopy(self._items)

    @staticmethod
    def _read_range(path: Path, offset: int, size: int) -> str:
        if size <= 0:
            return ""
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, offset))
                data = handle.read(max(0, size))
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")


class FrontendLogCache:
    """把文件尾读结果缓存起来，让状态快照只做内存合并。"""

    def __init__(
        self,
        *,
        cache_service: Any,
        limit_provider: Callable[[], int],
        reader: Callable[..., list[dict[str, Any]]] | None = None,
        log_path_provider: Callable[[], str | Path] | None = None,
        ttl_seconds: float = 1.0,
        backfill_limit: int = 500,
        clock: Callable[[], float] = time.monotonic,
        worker_enabled: bool = False,
        on_refresh: Callable[[int], None] | None = None,
    ) -> None:
        self._cache_service = cache_service
        self._limit_provider = limit_provider
        self._ttl_seconds = float(ttl_seconds)
        self._backfill_limit = int(backfill_limit)
        self._clock = clock
        self._items: list[dict[str, Any]] = []
        self._at = 0.0
        self._limit = 0
        self._lock = threading.RLock()
        self._reader = reader
        self._tail_reader = _TailLogFileReader(log_path_provider) if log_path_provider is not None else None
        self._known_cache_keys: set[str] = set()
        if self._reader is None and self._tail_reader is None:
            self._reader = lambda *, limit: []
        self._worker_enabled = bool(worker_enabled)
        self._on_refresh = on_refresh
        self._worker_event = threading.Event()
        self._worker_lock = threading.RLock()
        self._worker_thread: threading.Thread | None = None
        self._pending_read_limit = 0
        self._refresh_in_flight = False
        self._shutdown = False

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

    def _cache_key_for_read(self, read_limit: int) -> tuple[str, _TailCacheState | None]:
        if self._tail_reader is None:
            return self.cache_key(read_limit), None
        state = self._tail_reader.cache_state(limit=read_limit)
        if state is None:
            return self.cache_key(read_limit), None
        return state.cache_key, state

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
            known_cache_keys = list(self._known_cache_keys)
            self._known_cache_keys.clear()
        if self._tail_reader is not None:
            self._tail_reader.reset()
        self._delete_cache_key("frontend.file_log_cache")
        self._delete_cache_key(self.cache_key(normalized_limit))
        for key in known_cache_keys:
            self._delete_cache_key(key)

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
        """合并文件日志和当前 UI 环形缓冲，保证日志中心能看到启动前后的记录。"""
        limit = self._current_limit()
        read_limit = self._next_read_limit(limit)
        if read_limit > 0:
            if self._worker_enabled:
                self.request_refresh(read_limit)
            else:
                self._refresh_from_source(read_limit)
        file_items = self.items_snapshot
        merged = [*file_items, *[dict(item) for item in buffer]][-limit:]
        return merged

    def request_refresh(self, limit: Any | None = None) -> None:
        """请求后台读取日志文件；连续请求只保留最大的 read_limit。"""
        read_limit = self.normalize_limit(limit if limit is not None else self._current_limit())
        with self._worker_lock:
            if self._shutdown:
                return
            self._pending_read_limit = max(self._pending_read_limit, read_limit)
            self._ensure_worker_locked()
            self._refresh_in_flight = True
            self._worker_event.set()

    def refresh_now(self, limit: Any | None = None) -> list[dict[str, Any]]:
        read_limit = self.normalize_limit(limit if limit is not None else self._current_limit())
        self._refresh_from_source(read_limit)
        return self.items_snapshot

    def wait_for_idle(self, timeout: float = 2.0) -> bool:
        deadline = self._clock() + max(0.0, float(timeout))
        while self._clock() < deadline:
            with self._worker_lock:
                idle = not self._refresh_in_flight and self._pending_read_limit <= 0
            if idle:
                return True
            time.sleep(0.01)
        with self._worker_lock:
            return not self._refresh_in_flight and self._pending_read_limit <= 0

    def shutdown(self) -> None:
        with self._worker_lock:
            self._shutdown = True
            self._worker_event.set()
            thread = self._worker_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _current_limit(self) -> int:
        try:
            return self.normalize_limit(self._limit_provider())
        except Exception:
            return 300

    def _next_read_limit(self, limit: int) -> int:
        """根据 TTL 判断是否需要重新读文件；列表缩小时先裁剪内存项。"""
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

    def _refresh_from_source(self, read_limit: int) -> None:
        """从缓存或文件源刷新项目，并清掉旧 tail 指纹缓存。"""
        cache_key, tail_state = self._cache_key_for_read(read_limit)
        if self._tail_reader is not None:
            with self._lock:
                self._known_cache_keys.add(cache_key)
        cached = self._read_cache(cache_key)
        if cached is None:
            cached = self._source_read(limit=read_limit)
            self._write_cache(
                cache_key,
                cached,
                ttl_seconds=self._ttl_seconds,
                persist=self._tail_reader is not None,
            )
        elif tail_state is not None and self._tail_reader is not None:
            self._tail_reader.hydrate(tail_state, cached, limit=read_limit)
        if tail_state is not None:
            self._delete_stale_tail_cache_keys(cache_key)
        with self._lock:
            self._items = deepcopy(cached)[-read_limit:]
            self._limit = read_limit
            self._at = self._clock()
        if self._on_refresh is not None:
            self._on_refresh(len(self._items))

    def _read_cache(self, key: str) -> Any | None:
        try:
            return self._cache_service.get(key)
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendLogCache",
                "read_cache",
                exc,
                details={"key": key},
            )
            return None

    def _write_cache(
        self,
        key: str,
        value: list[dict[str, Any]],
        *,
        ttl_seconds: float,
        persist: bool,
    ) -> None:
        try:
            self._cache_service.set(
                key,
                value,
                ttl_seconds=ttl_seconds,
                persist=persist,
            )
        except Exception as exc:
            debug_logger.log_exception(
                "FrontendLogCache",
                "write_cache",
                exc,
                details={"key": key, "persist": persist},
            )

    def _source_read(self, *, limit: int) -> list[dict[str, Any]]:
        if self._tail_reader is not None:
            return self._tail_reader.read(limit=limit)
        if self._reader is None:
            return []
        return self._reader(limit=limit)

    def _ensure_worker_locked(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="frontend-log-tail-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        """后台串行刷新日志，避免 UI 快照线程被磁盘 IO 卡住。"""
        while True:
            self._worker_event.wait()
            with self._worker_lock:
                if self._shutdown:
                    return
                read_limit = self._pending_read_limit
                self._pending_read_limit = 0
                self._worker_event.clear()
            if read_limit > 0:
                try:
                    self._refresh_from_source(read_limit)
                except Exception as exc:
                    debug_logger.log_exception(
                        "FrontendLogCache",
                        "worker_refresh",
                        exc,
                        details={"read_limit": read_limit},
                    )
                finally:
                    with self._worker_lock:
                        if self._pending_read_limit > 0:
                            self._worker_event.set()
                        else:
                            self._refresh_in_flight = False

    def _delete_cache_key(self, key: str) -> None:
        delete = getattr(self._cache_service, "delete", None)
        if callable(delete):
            try:
                delete(key)
            except Exception as exc:
                debug_logger.log_exception(
                    "FrontendLogCache",
                    "delete_cache_key",
                    exc,
                    details={"key": key},
                )

    def _delete_stale_tail_cache_keys(self, current_key: str) -> None:
        prefix = "frontend.file_log_cache.tail."
        with self._lock:
            stale_keys = [
                key for key in self._known_cache_keys if key != current_key and key.startswith(prefix)
            ]
            for key in stale_keys:
                self._known_cache_keys.discard(key)
        for key in stale_keys:
            self._delete_cache_key(key)
