"""为无副作用的 Spider 解析结果提供内部持久缓存。

缓存键包含载荷哈希；载荷变化后旧哈希键不会被主动删除。持久化 TTL 仅在命中对应
键时惰性处理，不构成全局保留上限，因此旧键可能在 SQLite 中累积。
"""

from __future__ import annotations

import hashlib
import pickle
import threading
from collections.abc import Callable
from typing import TypeVar

from app.debug_logger import debug_logger
from app.services.cache_service import CacheService

T = TypeVar("T")

_CACHE_LOCK = threading.RLock()
_PARSER_CACHE_SERVICE: CacheService | None = None


def cached_parser_result(
    namespace: str,
    payload: object,
    producer: Callable[[], T],
    *,
    ttl_seconds: float = 24 * 60 * 60,
) -> T:
    """返回缓存的纯解析结果；缓存异常时回退到 ``producer``。"""
    key = _cache_key(namespace, payload)
    cache = _parser_cache_service()
    try:
        sentinel = object()
        cached = cache.get(key, sentinel)
        if cached is not sentinel:
            return cached
    except Exception as exc:
        debug_logger.log_exception(
            "ParserCache",
            "read_parser_cache",
            exc,
            details={"namespace": namespace, "key": key},
        )

    value = producer()
    try:
        cache.set(key, value, ttl_seconds=ttl_seconds, persist=True)
    except Exception as exc:
        debug_logger.log_exception(
            "ParserCache",
            "write_parser_cache",
            exc,
            details={"namespace": namespace, "key": key},
        )
    return value


def _parser_cache_service() -> CacheService:
    global _PARSER_CACHE_SERVICE
    with _CACHE_LOCK:
        if _PARSER_CACHE_SERVICE is None:
            _PARSER_CACHE_SERVICE = CacheService(namespace="spider_parser", memory_ttl_seconds=60.0)
        return _PARSER_CACHE_SERVICE


def _cache_key(namespace: str, payload: object) -> str:
    try:
        raw = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        raw = repr(payload).encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return f"spider.parser.{namespace}.{digest}"
