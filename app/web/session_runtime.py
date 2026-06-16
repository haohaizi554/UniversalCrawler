"""Web session runtime: session context, auth token, and directory authorization."""

from __future__ import annotations

import os
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlsplit


SendFactory = Callable[[str], Callable[[str, Any], Any]]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver"}


def normalize_directory(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def is_within_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def normalize_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if not parts.scheme or not parts.hostname:
        raise ValueError("invalid origin")
    host = parts.hostname.lower()
    port = parts.port
    default_port = 443 if parts.scheme == "https" else 80
    if port is None or port == default_port:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def configured_allowed_origins() -> set[str]:
    raw = os.getenv("UCRAWL_ALLOWED_ORIGINS", "")
    origins: set[str] = set()
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            origins.add(normalize_origin(candidate))
        except ValueError:
            continue
    return origins


def is_local_host(host: str | None) -> bool:
    return (host or "").strip().lower() in LOCAL_HOSTS


def is_allowed_origin(origin: str | None, *, expected_origin: str | None = None) -> bool:
    if not origin:
        return False
    try:
        normalized_origin = normalize_origin(origin)
    except ValueError:
        return False
    if expected_origin and normalized_origin == normalize_origin(expected_origin):
        return True
    return normalized_origin in configured_allowed_origins()


class WebSessionContext:
    def __init__(
        self,
        session_id: str,
        *,
        send_factory: SendFactory,
        controller_factory: Callable[[Any, Callable[[str, Any], Any]], Any],
        workflow_factory: Callable[[Any, Callable[[str, Any], Any]], Any],
    ) -> None:
        self.session_id = session_id
        self.send = send_factory(session_id)
        # 不在 create_app 时获取事件循环，因为 uvicorn 可能使用不同的事件循环
        # 传入 None，在首次 emit 时延迟获取正确的事件循环
        self.controller = controller_factory(None, self.send)
        self.workflow = workflow_factory(self.controller, self.send)
        self.session_token = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        self.approved_roots: set[str] = set()
        self.last_access_at = time.monotonic()
        self.approve_directory(self.controller.current_save_dir)

    def approve_directory(self, directory: str) -> str:
        normalized = normalize_directory(directory)
        self.approved_roots.add(normalized)
        return normalized

    def is_directory_allowed(self, directory: str) -> bool:
        normalized = normalize_directory(directory)
        return any(is_within_root(normalized, root) for root in self.approved_roots)

    def require_directory(self, directory: str) -> str:
        normalized = normalize_directory(directory)
        if not self.is_directory_allowed(normalized):
            raise PermissionError("目录未被当前会话授权访问")
        return normalized


class WebSessionRegistry:
    def __init__(
        self,
        *,
        send_factory: SendFactory,
        controller_factory: Callable[[Any, Callable[[str, Any], Any]], Any],
        workflow_factory: Callable[[Any, Callable[[str, Any], Any]], Any],
        max_contexts: int = 64,
        idle_ttl_seconds: float = 30 * 60,
        pinned_session_ids: set[str] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._send_factory = send_factory
        self._controller_factory = controller_factory
        self._workflow_factory = workflow_factory
        self._contexts: dict[str, WebSessionContext] = {}
        self._max_contexts = max(1, int(max_contexts))
        self._idle_ttl_seconds = max(float(idle_ttl_seconds), 0.0)
        self._pinned_session_ids = set(pinned_session_ids or ())
        self._monotonic = monotonic or time.monotonic

    def get_or_create(self, session_id: str) -> WebSessionContext:
        self.prune()
        context = self._contexts.get(session_id)
        if context is None:
            context = WebSessionContext(
                session_id,
                send_factory=self._send_factory,
                controller_factory=self._controller_factory,
                workflow_factory=self._workflow_factory,
            )
            self._contexts[session_id] = context
        context.last_access_at = self._monotonic()
        self._evict_overflow()
        return context

    def prune(self) -> None:
        if self._idle_ttl_seconds <= 0:
            return
        now = self._monotonic()
        expired_session_ids = [
            session_id
            for session_id, context in self._contexts.items()
            if session_id not in self._pinned_session_ids
            and now - getattr(context, "last_access_at", now) > self._idle_ttl_seconds
        ]
        for session_id in expired_session_ids:
            self._dispose_context(session_id)

    def _evict_overflow(self) -> None:
        overflow = len(self._contexts) - self._max_contexts
        if overflow <= 0:
            return
        eviction_candidates = sorted(
            (
                (getattr(context, "last_access_at", 0.0), session_id)
                for session_id, context in self._contexts.items()
                if session_id not in self._pinned_session_ids
            ),
            key=lambda item: item[0],
        )
        for _, session_id in eviction_candidates[:overflow]:
            self._dispose_context(session_id)

    def _dispose_context(self, session_id: str) -> None:
        context = self._contexts.pop(session_id, None)
        if context is None:
            return
        controller = getattr(context, "controller", None)
        shutdown = getattr(controller, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass
