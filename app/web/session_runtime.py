"""Web 会话运行时：会话上下文、鉴权令牌与目录授权。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait as wait_for_futures
import os
import ipaddress
import secrets
import threading
import time
import asyncio
import logging
from typing import Any, Callable
from urllib.parse import urlsplit

SendFactory = Callable[[str], Callable[[str, Any], Any]]
TEST_TRANSPORT_HOSTS = {"testserver", "testclient"}
DEFAULT_DISPOSAL_WORKERS = 2
DEFAULT_DISPOSAL_QUEUE_CAPACITY = 8

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

def is_loopback_host(host: str | None) -> bool:
    normalized = (host or "").strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def is_local_host(host: str | None) -> bool:
    normalized = (host or "").strip().lower()
    return is_loopback_host(normalized) or normalized in TEST_TRANSPORT_HOSTS


def is_loopback_request_host(host: str | None, client_host: str | None) -> bool:
    """仅为 TestClient 的模拟客户端放行对应的模拟主机名。"""
    normalized_host = (host or "").strip().lower()
    normalized_client = (client_host or "").strip().lower()
    return is_loopback_host(normalized_host) or (
        normalized_host in TEST_TRANSPORT_HOSTS
        and normalized_client in TEST_TRANSPORT_HOSTS
    )

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
        # `controller`、`workflow`、令牌和授权目录均归当前会话，不能跨会话复用。
        self.session_id = session_id
        self.send = send_factory(session_id)
        # 不在 create_app 时获取事件循环，因为 uvicorn 可能使用不同的事件循环
        # 传入 None，在首次 emit 时延迟获取正确的事件循环
        self.controller = controller_factory(None, self.send)
        self.workflow = workflow_factory(self.controller, self.send)
        self.session_token = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        self.approved_roots: set[str] = set()
        self._approved_roots_lock = threading.RLock()
        self._prepared_update_lock = threading.RLock()
        self._prepared_update: Any = None
        self.background_tasks: set[asyncio.Task] = set()
        self._background_tasks_lock = threading.RLock()
        self._access_lock = threading.RLock()
        self._monotonic: Callable[[], float] = time.monotonic
        self._active_websockets = 0
        self.last_access_at = self._monotonic()
        self.approve_directory(self.controller.current_save_dir)

    def touch(self) -> None:
        with self._access_lock:
            self.last_access_at = self._monotonic()

    def mark_websocket_connected(self) -> None:
        with self._access_lock:
            self._active_websockets += 1
            self.last_access_at = self._monotonic()

    def mark_websocket_disconnected(self) -> None:
        with self._access_lock:
            self._active_websockets = max(0, self._active_websockets - 1)
            self.last_access_at = self._monotonic()

    def has_active_websocket(self) -> bool:
        with self._access_lock:
            return self._active_websockets > 0

    def track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        with self._background_tasks_lock:
            self.background_tasks.add(task)

        def _discard(done_task: asyncio.Task) -> None:
            with self._background_tasks_lock:
                self.background_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logging.getLogger(__name__).exception("Web session background task failed")

        task.add_done_callback(_discard)
        return task

    def approve_directory(self, directory: str) -> str:
        normalized = normalize_directory(directory)
        with self._approved_roots_lock:
            self.approved_roots.add(normalized)
        return normalized

    def is_directory_allowed(self, directory: str) -> bool:
        normalized = normalize_directory(directory)
        with self._approved_roots_lock:
            roots = tuple(self.approved_roots)
        return any(is_within_root(normalized, root) for root in roots)

    def approved_roots_snapshot(self) -> tuple[str, ...]:
        """返回稳定快照，供工作线程校验路径。"""
        with self._approved_roots_lock:
            return tuple(self.approved_roots)

    def store_prepared_update(self, prepared: Any) -> None:
        with self._prepared_update_lock:
            self._prepared_update = prepared

    def prepared_update_snapshot(self) -> Any:
        with self._prepared_update_lock:
            return self._prepared_update

    def take_prepared_update(self) -> Any:
        """以原子方式取走已校验的更新包，确保它只能启动一次。"""
        with self._prepared_update_lock:
            prepared = self._prepared_update
            self._prepared_update = None
            return prepared

    def clear_prepared_update(self) -> None:
        with self._prepared_update_lock:
            self._prepared_update = None

    def require_directory(self, directory: str) -> str:
        normalized = normalize_directory(directory)
        if not self.is_directory_allowed(normalized):
            raise PermissionError("目录未被当前会话授权访问")
        return normalized

class WebSessionRegistry:
    """管理会话上下文及其最终关闭。

    `pinned_session_ids` 中的固定会话和存在活动 WebSocket 的会话不参与 TTL 或容量淘汰，
    因此 `max_contexts` 是上下文总量的软目标，受保护会话可使总量超过该值。其余会话
    超过 `idle_ttl_seconds` 后可被清理，容量溢出时按最久未访问顺序淘汰。注册表先摘除
    上下文并取消其工作流和后台任务，再在线程池调用控制器的 `shutdown()`；
    `shutdown_all()` 取得包括固定会话和活动会话在内的最终关闭所有权。
    """
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
        disposal_workers: int = DEFAULT_DISPOSAL_WORKERS,
        disposal_queue_capacity: int = DEFAULT_DISPOSAL_QUEUE_CAPACITY,
    ) -> None:
        self._send_factory = send_factory
        self._controller_factory = controller_factory
        self._workflow_factory = workflow_factory
        self._contexts: dict[str, WebSessionContext] = {}
        self._lock = threading.RLock()
        self._max_contexts = max(1, int(max_contexts))
        self._idle_ttl_seconds = max(float(idle_ttl_seconds), 0.0)
        self._pinned_session_ids = set(pinned_session_ids or ())
        self._monotonic = monotonic or time.monotonic
        self._closed = False
        self._disposal_submit_lock = threading.RLock()
        self._disposal_executor = ThreadPoolExecutor(
            max_workers=max(1, int(disposal_workers)),
            thread_name_prefix="web-session-shutdown",
        )
        disposal_capacity = max(1, int(disposal_workers)) + max(0, int(disposal_queue_capacity))
        self._disposal_slots = threading.BoundedSemaphore(disposal_capacity)
        self._disposal_futures: set[Future[Any]] = set()
        self._disposal_executor_closed = False

    def get_or_create(self, session_id: str) -> WebSessionContext:
        self.prune()
        with self._lock:
            if self._closed:
                raise RuntimeError("Web session registry is shutting down")
            context = self._contexts.get(session_id)
            if context is None:
                context = WebSessionContext(
                    session_id,
                    send_factory=self._send_factory,
                    controller_factory=self._controller_factory,
                    workflow_factory=self._workflow_factory,
                )
                context._monotonic = self._monotonic
                self._contexts[session_id] = context
            context.touch()
        self._evict_overflow()
        return context

    def prune(self) -> None:
        if self._idle_ttl_seconds <= 0:
            return
        now = self._monotonic()
        with self._lock:
            expired_session_ids = [
                session_id
                for session_id, context in self._contexts.items()
                if session_id not in self._pinned_session_ids
                and not context.has_active_websocket()
                and now - getattr(context, "last_access_at", now) > self._idle_ttl_seconds
            ]
        for session_id in expired_session_ids:
            self._dispose_context(session_id)

    def _evict_overflow(self) -> None:
        with self._lock:
            overflow = len(self._contexts) - self._max_contexts
            if overflow <= 0:
                return
            eviction_candidates = sorted(
                (
                    (getattr(context, "last_access_at", 0.0), session_id)
                    for session_id, context in self._contexts.items()
                    if session_id not in self._pinned_session_ids
                    and not context.has_active_websocket()
                ),
                key=lambda item: item[0],
            )
        if overflow <= 0:
            return
        for _, session_id in eviction_candidates[:overflow]:
            self._dispose_context(session_id)

    def _dispose_context(self, session_id: str) -> Future[Any] | None:
        with self._disposal_submit_lock:
            with self._lock:
                context = self._contexts.pop(session_id, None)
            if context is None:
                return None
            return self._dispose_detached_context(context)

    def _dispose_detached_context(self, context: WebSessionContext) -> Future[Any] | None:
        """取消会话所属任务，再将其控制器排队关闭。"""
        with self._disposal_submit_lock:
            workflow = getattr(context, "workflow", None)
            cancel_broadcasts = getattr(workflow, "cancel_pending_broadcasts", None)
            if callable(cancel_broadcasts):
                cancel_broadcasts()
            tasks: list = []
            with context._background_tasks_lock:
                tasks = list(context.background_tasks)
            for task in tasks:
                if not task.done():
                    task.cancel()
            controller = getattr(context, "controller", None)
            shutdown = getattr(controller, "shutdown", None)
            if not callable(shutdown):
                return None

            self._disposal_slots.acquire()
            try:
                future = self._disposal_executor.submit(
                    self._safe_shutdown_controller,
                    shutdown,
                )
            except RuntimeError:
                self._disposal_slots.release()
                raise
            with self._lock:
                self._disposal_futures.add(future)
            future.add_done_callback(self._disposal_finished)
            return future

    def _disposal_finished(self, future: Future[Any]) -> None:
        self._disposal_slots.release()
        with self._lock:
            self._disposal_futures.discard(future)

    def shutdown_all(self, *, wait: bool = False, timeout: float | None = 5.0) -> None:
        """封闭会话注册表，并释放包括固定会话在内的所有上下文。

        常规空闲淘汰会保留固定会话；进程关闭时则必须释放所有控制器
        持有的工作线程和文件句柄，之后解释器才能退出。
        """
        with self._disposal_submit_lock:
            with self._lock:
                self._closed = True
                contexts = tuple(self._contexts.values())
                self._contexts.clear()

            for context in contexts:
                self._dispose_detached_context(context)
            with self._lock:
                disposal_futures = tuple(self._disposal_futures)
            if not self._disposal_executor_closed:
                self._disposal_executor_closed = True
                self._disposal_executor.shutdown(wait=False, cancel_futures=False)
        if not wait:
            return

        wait_timeout = None if timeout is None else max(0.0, float(timeout))
        wait_for_futures(disposal_futures, timeout=wait_timeout)

    @staticmethod
    def _safe_shutdown_controller(shutdown: Callable[[], Any]) -> None:
        try:
            shutdown()
        except (RuntimeError, OSError, AttributeError):
            logging.getLogger(__name__).warning("Controller shutdown callback failed", exc_info=True)
