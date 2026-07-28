"""Profile-bound public SDK adapter for the application tool runner.

The mainline service is imported only when an operation is used.  Every
stateful operation receives the same immutable, host-owned execution profile.
Closing this facade is terminal: a closed instance never silently creates a
new runner or executor pool.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from importlib import import_module
import threading
import time
from types import TracebackType
from typing import Any, Iterator, Protocol

from shared.execution_profile import ExecutionProfile


_SERVICE_MODULE = "app.services.tool_runner_service"
_SERVICE_CLASS = "ToolRunnerService"
_OPERATIONS = (
    "list/describe/validate/run/cancel/history/reload/get_run/wait_for_run/"
    "clear_history/shutdown"
)
DEFAULT_TOOL_CLOSE_TIMEOUT = 1.0


class ToolRunnerUnavailableError(RuntimeError):
    """Raised when the mainline application service is not available."""


class ToolRunnerServiceContract(Protocol):
    """Contract consumed by the SDK adapter; implemented in ``app.services``."""

    def list(self) -> Any: ...

    def describe(self, tool_id: str) -> Any: ...

    def validate(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def run(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def cancel(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def history(
        self,
        *,
        execution_profile: ExecutionProfile,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> Any: ...

    def reload(
        self,
        *,
        force: bool = False,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def get_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def wait_for_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
        timeout: float | None = None,
    ) -> Any: ...

    def clear_history(
        self,
        *,
        execution_profile: ExecutionProfile,
    ) -> Any: ...

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool: ...


def _create_service() -> ToolRunnerServiceContract:
    qualified_name = f"{_SERVICE_MODULE}.{_SERVICE_CLASS}"
    try:
        module = import_module(_SERVICE_MODULE)
        service_class = getattr(module, _SERVICE_CLASS)
    except (ImportError, AttributeError) as exc:
        raise ToolRunnerUnavailableError(
            f"Tool runner service is unavailable. Expected {qualified_name} "
            f"to implement {_OPERATIONS}."
        ) from exc

    if not callable(service_class):
        raise ToolRunnerUnavailableError(
            f"Tool runner service is unavailable. Expected {qualified_name} "
            f"to be callable and implement {_OPERATIONS}."
        )
    return service_class()


class ToolsAPI:
    """SDK facade bound to one host-owned execution profile and runner."""

    def __init__(
        self,
        execution_profile: ExecutionProfile,
        service: ToolRunnerServiceContract | None = None,
    ) -> None:
        if not isinstance(execution_profile, ExecutionProfile):
            raise TypeError("execution_profile must be an ExecutionProfile")
        self._execution_profile = execution_profile
        self._service = service
        self._cleanup_service: ToolRunnerServiceContract | None = None
        self._closed = False
        self._creating_service = False
        self._active_calls = 0
        self._active_calls_by_thread: dict[int, int] = {}
        self._shutdown_in_progress = False
        self._shutdown_thread_id: int | None = None
        self._shutdown_completed = False
        self._last_cleanup_error: BaseException | None = None
        self._lifecycle = threading.Condition()

    def _ensure_open(self) -> None:
        with self._lifecycle:
            if self._closed:
                raise RuntimeError("ToolsAPI is closed")

    def _get_service_for_active_call(self) -> ToolRunnerServiceContract:
        with self._lifecycle:
            while True:
                if self._closed:
                    raise RuntimeError("ToolsAPI is closed")
                if self._service is not None:
                    return self._service
                if not self._creating_service:
                    self._creating_service = True
                    break
                self._lifecycle.wait()

        try:
            service = _create_service()
        except BaseException:
            with self._lifecycle:
                self._creating_service = False
                self._lifecycle.notify_all()
            raise

        with self._lifecycle:
            self._creating_service = False
            if self._closed:
                self._cleanup_service = service
                self._shutdown_completed = False
                self._lifecycle.notify_all()
            else:
                self._service = service
                self._lifecycle.notify_all()
                return service
        raise RuntimeError("ToolsAPI is closed")

    @contextmanager
    def _active_service(self) -> Iterator[ToolRunnerServiceContract]:
        thread_id = threading.get_ident()
        with self._lifecycle:
            if self._closed:
                raise RuntimeError("ToolsAPI is closed")
            self._active_calls += 1
            self._active_calls_by_thread[thread_id] = (
                self._active_calls_by_thread.get(thread_id, 0) + 1
            )
        try:
            yield self._get_service_for_active_call()
        finally:
            with self._lifecycle:
                self._active_calls -= 1
                remaining = self._active_calls_by_thread[thread_id] - 1
                if remaining:
                    self._active_calls_by_thread[thread_id] = remaining
                else:
                    self._active_calls_by_thread.pop(thread_id, None)
                self._lifecycle.notify_all()

    def list(self) -> Any:
        with self._active_service() as service:
            return service.list()

    def describe(self, tool_id: str) -> Any:
        with self._active_service() as service:
            return service.describe(tool_id)

    def validate(self, tool_id: str, params: Mapping[str, Any] | None) -> Any:
        with self._active_service() as service:
            return service.validate(
                tool_id,
                params,
                execution_profile=self._execution_profile,
            )

    def run(self, tool_id: str, params: Mapping[str, Any] | None) -> Any:
        with self._active_service() as service:
            return service.run(
                tool_id,
                params,
                execution_profile=self._execution_profile,
            )

    def cancel(self, run_id: str) -> Any:
        with self._active_service() as service:
            return service.cancel(
                run_id,
                execution_profile=self._execution_profile,
            )

    def history(
        self,
        *,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> Any:
        with self._active_service() as service:
            return service.history(
                execution_profile=self._execution_profile,
                tool_id=tool_id,
                status=status,
                limit=limit,
            )

    def reload(self, *, force: bool = False) -> Any:
        with self._active_service() as service:
            return service.reload(
                force=force,
                execution_profile=self._execution_profile,
            )

    def get_run(self, run_id: str) -> Any:
        with self._active_service() as service:
            return service.get_run(
                run_id,
                execution_profile=self._execution_profile,
            )

    def wait_for_run(self, run_id: str, *, timeout: float | None = None) -> Any:
        with self._active_service() as service:
            return service.wait_for_run(
                run_id,
                execution_profile=self._execution_profile,
                timeout=timeout,
            )

    def clear_history(self) -> Any:
        with self._active_service() as service:
            return service.clear_history(
                execution_profile=self._execution_profile,
            )

    def run_sync(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        timeout: float | None = None,
    ) -> Any:
        with self._active_service() as service:
            queued = service.run(
                tool_id,
                params,
                execution_profile=self._execution_profile,
            )
            if not isinstance(queued, dict) or queued.get("status") != "queued":
                return queued
            run_id = queued.get("run_id")
            if type(run_id) is not str or not run_id.strip():
                return {
                    "status": "error",
                    "code": "tool_protocol_error",
                    "message": (
                        "tool runner returned a queued result without a valid run_id"
                    ),
                }
            return service.wait_for_run(
                run_id,
                execution_profile=self._execution_profile,
                timeout=timeout,
            )

    def close(
        self,
        *,
        timeout: float | None = DEFAULT_TOOL_CLOSE_TIMEOUT,
    ) -> bool:
        """Close permanently within ``timeout``, retaining cleanup for retry."""

        deadline = self._close_deadline(timeout)

        with self._lifecycle:
            if not self._closed:
                self._closed = True
                if self._service is not None:
                    self._cleanup_service = self._service
                    self._service = None
                    self._shutdown_completed = False
                self._lifecycle.notify_all()

            thread_id = threading.get_ident()
            if (
                self._active_calls_by_thread.get(thread_id, 0)
                or self._shutdown_thread_id == thread_id
            ):
                return False

        while True:
            with self._lifecycle:
                if self._shutdown_in_progress:
                    if not self._wait_for_lifecycle(deadline):
                        return False
                    continue
                if self._creating_service or self._active_calls:
                    if not self._wait_for_lifecycle(deadline):
                        return False
                    continue
                service = self._cleanup_service
                if service is not None and not self._shutdown_completed:
                    self._shutdown_in_progress = True
                    self._shutdown_thread_id = thread_id
                elif service is None:
                    return True
                else:
                    self._cleanup_service = None
                    self._shutdown_completed = False
                    return True

            try:
                remaining = self._remaining_close_timeout(deadline)
                completed = service.shutdown(
                    wait=True,
                    timeout=remaining,
                ) is True
            except BaseException:
                with self._lifecycle:
                    self._shutdown_in_progress = False
                    self._shutdown_thread_id = None
                    self._lifecycle.notify_all()
                raise

            with self._lifecycle:
                if completed and self._cleanup_service is service:
                    self._shutdown_completed = True
                self._shutdown_in_progress = False
                self._shutdown_thread_id = None
                self._lifecycle.notify_all()
            if not completed:
                return False

    @staticmethod
    def _close_deadline(timeout: float | None) -> float | None:
        if timeout is None:
            return None
        normalized = float(timeout)
        if normalized < 0.0:
            raise ValueError("timeout must be non-negative or None")
        return time.monotonic() + normalized

    @staticmethod
    def _remaining_close_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    def _wait_for_lifecycle(self, deadline: float | None) -> bool:
        remaining = self._remaining_close_timeout(deadline)
        if remaining is not None and remaining <= 0.0:
            return False
        self._lifecycle.wait(timeout=remaining)
        return deadline is None or time.monotonic() < deadline

    def __enter__(self) -> "ToolsAPI":
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        cleanup_error: BaseException | None = None
        try:
            if not self.close():
                cleanup_error = RuntimeError(
                    "tool runner shutdown did not complete"
                )
        except BaseException as error:
            cleanup_error = error

        if cleanup_error is None:
            return False
        if exc is None:
            raise cleanup_error
        self._record_cleanup_failure(exc, cleanup_error)
        return False

    def _record_cleanup_failure(
        self,
        body_error: BaseException,
        cleanup_error: BaseException,
    ) -> None:
        try:
            object.__setattr__(self, "_last_cleanup_error", cleanup_error)
        except BaseException:
            pass

        try:
            try:
                note = f"ToolsAPI cleanup failed ({type(cleanup_error).__name__})"
            except BaseException:
                note = "ToolsAPI cleanup failed"
            try:
                add_note = getattr(body_error, "add_note", None)
            except BaseException:
                add_note = None
            if callable(add_note):
                try:
                    add_note(note)
                    return
                except BaseException:
                    pass
            try:
                setattr(body_error, "_tools_api_cleanup_error", cleanup_error)
            except BaseException:
                pass
        except BaseException:
            pass


__all__ = [
    "DEFAULT_TOOL_CLOSE_TIMEOUT",
    "ToolRunnerServiceContract",
    "ToolRunnerUnavailableError",
    "ToolsAPI",
]
