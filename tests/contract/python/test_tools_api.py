"""Public SDK contract for the application tool runner."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from shared.execution_profile import ExecutionProfile, local_execution_profile


class RunIdStringSubclass(str):
    """A string-like run id must not cross the exact protocol boundary."""


class HostileRunId:
    def __str__(self) -> str:
        raise RuntimeError("run_id string conversion must not be attempted")


def _sdk_profile() -> ExecutionProfile:
    return local_execution_profile(
        host_surface="sdk",
        owner_id="sdk:contract-test",
        approved_roots=(Path.cwd(),),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )


class RecordingToolRunnerService:
    """Small contract double that records the SDK-to-service boundary."""

    def __init__(
        self,
        *,
        shutdown_outcomes: list[bool | BaseException] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses = {
            name: {"operation": name}
            for name in (
                "list",
                "describe",
                "validate",
                "run",
                "cancel",
                "history",
                "reload",
                "get_run",
                "wait_for_run",
                "clear_history",
            )
        }
        self.shutdown_calls: list[dict[str, Any]] = []
        self.shutdown_outcomes = list(shutdown_outcomes or [True])

    def _record(self, operation: str, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append((operation, args, kwargs))
        return self.responses[operation]

    def list(self) -> dict[str, str]:
        return self._record("list")

    def describe(self, tool_id: str) -> dict[str, str]:
        return self._record("describe", tool_id)

    def validate(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record(
            "validate",
            tool_id,
            params,
            execution_profile=execution_profile,
        )

    def run(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record("run", tool_id, params, execution_profile=execution_profile)

    def cancel(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record("cancel", run_id, execution_profile=execution_profile)

    def history(
        self,
        *,
        execution_profile: ExecutionProfile,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> dict[str, str]:
        return self._record(
            "history",
            execution_profile=execution_profile,
            tool_id=tool_id,
            status=status,
            limit=limit,
        )

    def reload(
        self,
        *,
        force: bool = False,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record(
            "reload",
            force=force,
            execution_profile=execution_profile,
        )

    def get_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record("get_run", run_id, execution_profile=execution_profile)

    def wait_for_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
        timeout: float | None = None,
    ) -> dict[str, str]:
        return self._record(
            "wait_for_run",
            run_id,
            execution_profile=execution_profile,
            timeout=timeout,
        )

    def clear_history(
        self,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._record(
            "clear_history",
            execution_profile=execution_profile,
        )

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_calls.append({"wait": wait, "timeout": timeout})
        outcome = self.shutdown_outcomes.pop(0) if self.shutdown_outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BlockingShutdownToolRunnerService(RecordingToolRunnerService):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_entered = threading.Event()
        self.release_shutdown = threading.Event()

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_calls.append({"wait": wait, "timeout": timeout})
        self.shutdown_entered.set()
        if not self.release_shutdown.wait(5.0):
            raise TimeoutError("test did not release shutdown")
        return True


class BlockingValidateToolRunnerService(RecordingToolRunnerService):
    def __init__(self) -> None:
        super().__init__()
        self.validate_entered = threading.Event()
        self.release_validate = threading.Event()
        self.validate_waiting_to_finish = threading.Event()
        self.finish_validate = threading.Event()
        self.shutdown_entered = threading.Event()

    def validate(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        self.validate_entered.set()
        if not self.release_validate.wait(5.0):
            raise TimeoutError("test did not release validate")
        self.validate_waiting_to_finish.set()
        if not self.finish_validate.wait(5.0):
            raise TimeoutError("test did not finish validate")
        return self._record(
            "validate",
            tool_id,
            params,
            execution_profile=execution_profile,
        )

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_calls.append({"wait": wait, "timeout": timeout})
        self.shutdown_entered.set()
        return True


class BudgetConsumingShutdownService(BlockingValidateToolRunnerService):
    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_calls.append({"wait": wait, "timeout": timeout})
        assert timeout is not None
        threading.Event().wait(max(0.0, timeout))
        return True


class BlockingOperationToolRunnerService(RecordingToolRunnerService):
    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation
        self.operation_entered = threading.Event()
        self.release_operation = threading.Event()
        self.shutdown_entered = threading.Event()

    def _block_and_record(
        self,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert operation == self.operation
        self.operation_entered.set()
        if not self.release_operation.wait(5.0):
            raise TimeoutError("test did not release the stateful operation")
        return self._record(operation, *args, **kwargs)

    def run(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._block_and_record(
            "run",
            tool_id,
            params,
            execution_profile=execution_profile,
        )

    def wait_for_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
        timeout: float | None = None,
    ) -> dict[str, str]:
        return self._block_and_record(
            "wait_for_run",
            run_id,
            execution_profile=execution_profile,
            timeout=timeout,
        )

    def cancel(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._block_and_record(
            "cancel",
            run_id,
            execution_profile=execution_profile,
        )

    def history(
        self,
        *,
        execution_profile: ExecutionProfile,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> dict[str, str]:
        return self._block_and_record(
            "history",
            execution_profile=execution_profile,
            tool_id=tool_id,
            status=status,
            limit=limit,
        )

    def reload(
        self,
        *,
        force: bool = False,
        execution_profile: ExecutionProfile,
    ) -> dict[str, str]:
        return self._block_and_record(
            "reload",
            force=force,
            execution_profile=execution_profile,
        )

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_entered.set()
        return super().shutdown(wait=wait, timeout=timeout)


class DestroyingHistoryToolRunnerService(RecordingToolRunnerService):
    """Model a real shutdown that makes an in-flight service call unusable."""

    def __init__(self) -> None:
        super().__init__()
        self.history_entered = threading.Event()
        self.release_history = threading.Event()
        self.shutdown_entered = threading.Event()
        self._resource: dict[str, str] | None = {"operation": "history"}

    def history(
        self,
        *,
        execution_profile: ExecutionProfile,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> dict[str, str]:
        del execution_profile, tool_id, status, limit
        self.history_entered.set()
        if not self.release_history.wait(5.0):
            raise TimeoutError("test did not release history")
        if self._resource is None:
            raise RuntimeError("service resource was destroyed during history")
        return dict(self._resource)

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_calls.append({"wait": wait, "timeout": timeout})
        self._resource = None
        self.shutdown_entered.set()
        return True


class TimedShutdownToolRunnerService(RecordingToolRunnerService):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_called_at: float | None = None

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        self.shutdown_called_at = time.monotonic()
        return super().shutdown(wait=wait, timeout=timeout)


class QueuedRunBarrier(dict[str, Any]):
    def __init__(self) -> None:
        super().__init__(status="queued", run_id="run-barrier")
        self.run_id_read = threading.Event()
        self.release_run_id = threading.Event()

    def get(self, key: str, default: Any = None) -> Any:
        if key == "run_id":
            self.run_id_read.set()
            if not self.release_run_id.wait(5.0):
                raise TimeoutError("test did not release queued run_id")
        return super().get(key, default)


def _assert_bounded_shutdown_calls(
    service: RecordingToolRunnerService,
    *,
    count: int = 1,
) -> None:
    assert len(service.shutdown_calls) == count
    for call in service.shutdown_calls:
        assert call["wait"] is True
        assert isinstance(call["timeout"], float)
        assert 0.0 <= call["timeout"] <= 1.0


def test_tools_api_requires_a_host_owned_execution_profile() -> None:
    from ucrawl.tools import ToolsAPI

    with pytest.raises(TypeError, match="execution_profile"):
        ToolsAPI()  # type: ignore[call-arg]


def test_tools_api_rejects_a_non_profile_authority_object() -> None:
    from ucrawl.tools import ToolsAPI

    with pytest.raises(TypeError, match="ExecutionProfile"):
        ToolsAPI(execution_profile=object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("operation", "args", "kwargs"),
    (
        ("list", (), {}),
        ("describe", ("media.probe",), {}),
        ("validate", ("media.probe", {"path": "demo.mp4"}), {}),
        ("run", ("media.probe", {"path": "demo.mp4"}), {}),
        ("cancel", ("run-42",), {}),
        (
            "history",
            (),
            {"tool_id": "media.probe", "status": "failed", "limit": 7},
        ),
        ("reload", (), {"force": True}),
        ("get_run", ("run-42",), {}),
        ("wait_for_run", ("run-42",), {"timeout": 2.5}),
        ("clear_history", (), {}),
    ),
)
def test_tools_api_forwards_operations_with_one_host_owned_profile(
    operation: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    profile = _sdk_profile()
    api = ToolsAPI(execution_profile=profile, service=service)

    result = getattr(api, operation)(*args, **kwargs)

    assert result is service.responses[operation]
    expected_kwargs = dict(kwargs)
    if operation not in {"list", "describe"}:
        expected_kwargs["execution_profile"] = profile
    if operation == "history":
        expected_kwargs = {
            "execution_profile": profile,
            "tool_id": kwargs.get("tool_id"),
            "status": kwargs.get("status"),
            "limit": kwargs.get("limit"),
        }
    assert service.calls == [(operation, args, expected_kwargs)]
    if operation not in {"list", "describe"}:
        assert service.calls[0][2]["execution_profile"] is profile


def test_run_sync_waits_for_the_queued_run_with_the_same_profile() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    service.responses["run"] = {"status": "queued", "run_id": "run-42"}
    service.responses["wait_for_run"] = {"status": "succeeded", "run_id": "run-42"}
    profile = _sdk_profile()
    api = ToolsAPI(execution_profile=profile, service=service)

    result = api.run_sync("media.probe", {"path": "demo.mp4"}, timeout=4.0)

    assert result is service.responses["wait_for_run"]
    assert service.calls == [
        (
            "run",
            ("media.probe", {"path": "demo.mp4"}),
            {"execution_profile": profile},
        ),
        (
            "wait_for_run",
            ("run-42",),
            {"execution_profile": profile, "timeout": 4.0},
        ),
    ]


def test_run_sync_returns_an_immediate_denial_without_waiting() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    service.responses["run"] = {"status": "forbidden", "code": "tool_run_disabled"}
    profile = _sdk_profile()
    api = ToolsAPI(execution_profile=profile, service=service)

    result = api.run_sync("media.probe", {})

    assert result is service.responses["run"]
    assert service.calls == [
        (
            "run",
            ("media.probe", {}),
            {"execution_profile": profile},
        )
    ]


@pytest.mark.parametrize(
    "run_id",
    (
        None,
        "",
        "   ",
        42,
        RunIdStringSubclass("run-subclass"),
        HostileRunId(),
    ),
)
def test_run_sync_fails_closed_when_a_queued_result_has_no_valid_run_id(
    run_id: object,
) -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    service.responses["run"] = {"status": "queued", "run_id": run_id}
    profile = _sdk_profile()
    api = ToolsAPI(execution_profile=profile, service=service)

    result = api.run_sync("media.probe", {}, timeout=1.25)

    assert result == {
        "status": "error",
        "code": "tool_protocol_error",
        "message": "tool runner returned a queued result without a valid run_id",
    }
    assert service.calls == [
        (
            "run",
            ("media.probe", {}),
            {"execution_profile": profile},
        )
    ]


def test_run_sync_fails_closed_when_a_queued_result_omits_run_id() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    service.responses["run"] = {"status": "queued"}
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)

    assert api.run_sync("media.probe", {}) == {
        "status": "error",
        "code": "tool_protocol_error",
        "message": "tool runner returned a queued result without a valid run_id",
    }


def test_run_sync_holds_one_lease_across_run_and_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    queued = QueuedRunBarrier()
    service = RecordingToolRunnerService()
    service.responses["run"] = queued
    service.responses["wait_for_run"] = {
        "status": "succeeded",
        "run_id": "run-barrier",
    }
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile(), service=service)
    run_results: list[dict[str, Any]] = []
    run_errors: list[BaseException] = []
    close_results: list[bool] = []

    def run_sync() -> None:
        try:
            run_results.append(api.run_sync("media.probe", {}, timeout=3.5))
        except BaseException as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_sync)
    run_thread.start()
    assert queued.run_id_read.wait(2.0)

    close_thread = threading.Thread(target=lambda: close_results.append(api.close()))
    close_thread.start()
    deadline = time.monotonic() + 2.0
    while not api._closed and time.monotonic() < deadline:
        threading.Event().wait(0.001)
    assert api._closed is True
    queued.release_run_id.set()

    run_thread.join(2.0)
    close_thread.join(2.0)
    assert not run_thread.is_alive()
    assert not close_thread.is_alive()
    assert run_errors == []
    assert run_results == [{"status": "succeeded", "run_id": "run-barrier"}]
    assert close_results == [True]
    assert service.calls == [
        (
            "run",
            ("media.probe", {}),
            {"execution_profile": api._execution_profile},
        ),
        (
            "wait_for_run",
            ("run-barrier",),
            {"execution_profile": api._execution_profile, "timeout": 3.5},
        ),
    ]


@pytest.mark.parametrize(
    ("operation", "args", "kwargs"),
    (
        ("run", ("media.probe", {"path": "demo.mp4"}), {}),
        ("wait_for_run", ("run-42",), {"timeout": 2.5}),
        ("cancel", ("run-42",), {}),
        (
            "history",
            (),
            {"tool_id": "media.probe", "status": "failed", "limit": 7},
        ),
        ("reload", (), {"force": True}),
    ),
)
def test_direct_stateful_operation_keeps_its_lease_while_close_seals_admission(
    operation: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    from ucrawl.tools import ToolsAPI

    service = BlockingOperationToolRunnerService(operation)
    profile = _sdk_profile()
    api = ToolsAPI(execution_profile=profile, service=service)
    operation_results: list[dict[str, str]] = []
    operation_errors: list[BaseException] = []
    close_results: list[bool] = []
    close_errors: list[BaseException] = []
    close_done = threading.Event()

    def call_operation() -> None:
        try:
            operation_results.append(getattr(api, operation)(*args, **kwargs))
        except BaseException as exc:
            operation_errors.append(exc)

    def close_api() -> None:
        try:
            close_results.append(api.close(timeout=0.5))
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_done.set()

    operation_thread = threading.Thread(target=call_operation)
    operation_thread.start()
    assert service.operation_entered.wait(2.0)

    close_thread = threading.Thread(target=close_api)
    close_thread.start()
    shutdown_started_before_release = service.shutdown_entered.wait(0.05)
    assert close_done.is_set() is False
    with pytest.raises(RuntimeError, match="closed"):
        api.list()

    service.release_operation.set()
    operation_thread.join(2.0)
    close_thread.join(2.0)
    assert not operation_thread.is_alive()
    assert not close_thread.is_alive()
    assert operation_errors == []
    assert close_errors == []
    assert operation_results == [service.responses[operation]]
    assert close_results == [True]
    assert shutdown_started_before_release is False
    assert service.shutdown_entered.is_set()
    expected_kwargs = dict(kwargs)
    expected_kwargs["execution_profile"] = profile
    assert service.calls == [(operation, args, expected_kwargs)]
    assert len(service.shutdown_calls) == 1


def test_close_never_destroys_service_resources_used_by_an_admitted_call() -> None:
    from ucrawl.tools import ToolsAPI

    service = DestroyingHistoryToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    history_results: list[dict[str, str]] = []
    history_errors: list[BaseException] = []
    close_results: list[bool] = []

    def read_history() -> None:
        try:
            history_results.append(api.history())
        except BaseException as exc:
            history_errors.append(exc)

    history_thread = threading.Thread(target=read_history)
    history_thread.start()
    assert service.history_entered.wait(2.0)

    close_thread = threading.Thread(
        target=lambda: close_results.append(api.close(timeout=0.5))
    )
    close_thread.start()
    shutdown_started_before_release = service.shutdown_entered.wait(0.05)
    service.release_history.set()

    history_thread.join(2.0)
    close_thread.join(2.0)
    assert not history_thread.is_alive()
    assert not close_thread.is_alive()
    assert shutdown_started_before_release is False
    assert history_errors == []
    assert history_results == [{"operation": "history"}]
    assert close_results == [True]
    assert service.shutdown_entered.is_set()
    assert len(service.shutdown_calls) == 1


def test_tools_api_loads_tool_runner_service_only_on_first_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = RecordingToolRunnerService()
    imported_modules: list[str] = []

    def import_service(name: str) -> SimpleNamespace:
        imported_modules.append(name)
        return SimpleNamespace(ToolRunnerService=lambda: service)

    monkeypatch.setattr(tools_module, "import_module", import_service)

    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    assert imported_modules == []

    assert api.list() is service.responses["list"]
    assert api.describe("media.probe") is service.responses["describe"]
    assert imported_modules == ["app.services.tool_runner_service"]


def test_missing_mainline_service_fails_at_call_time_with_contract_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    def missing_service(name: str) -> None:
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(tools_module, "import_module", missing_service)

    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    with pytest.raises(tools_module.ToolRunnerUnavailableError) as raised:
        api.list()

    message = str(raised.value)
    assert "app.services.tool_runner_service.ToolRunnerService" in message
    assert (
        "list/describe/validate/run/cancel/history/reload/get_run/"
        "wait_for_run/clear_history" in message
    )


def test_close_is_idempotent_and_a_closed_api_cannot_reopen() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    api.list()

    assert api.close() is True
    assert api.close() is True

    _assert_bounded_shutdown_calls(service)
    with pytest.raises(RuntimeError, match="closed"):
        api.list()


def test_close_retries_the_same_service_after_incomplete_shutdown() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)

    assert api.close() is False
    assert api._cleanup_service is service
    with pytest.raises(RuntimeError, match="closed"):
        api.list()
    assert api.close() is True
    assert api._cleanup_service is None
    assert api.close() is True

    _assert_bounded_shutdown_calls(service, count=2)


def test_close_retains_the_same_service_when_shutdown_raises() -> None:
    from ucrawl.tools import ToolsAPI

    failure = RuntimeError("shutdown failed")
    service = RecordingToolRunnerService(shutdown_outcomes=[failure, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)

    with pytest.raises(RuntimeError, match="shutdown failed") as raised:
        api.close()
    assert raised.value is failure
    assert api._cleanup_service is service
    with pytest.raises(RuntimeError, match="closed"):
        api.history()

    assert api.close() is True
    assert api._cleanup_service is None
    _assert_bounded_shutdown_calls(service, count=2)


def test_context_manager_makes_incomplete_shutdown_observable_and_retryable() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)

    with pytest.raises(RuntimeError, match="did not complete"):
        with api:
            api.list()

    assert api.close() is True
    _assert_bounded_shutdown_calls(service, count=2)


@pytest.mark.parametrize(
    "cleanup_outcome",
    (False, RuntimeError("cleanup exploded")),
)
def test_context_manager_preserves_body_exception_when_cleanup_fails(
    cleanup_outcome: bool | BaseException,
) -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService(
        shutdown_outcomes=[cleanup_outcome, True]
    )
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = ValueError("body failed")

    with pytest.raises(ValueError, match="body failed") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert api._cleanup_service is service
    assert api._last_cleanup_error is not None
    if hasattr(body_failure, "__notes__"):
        assert any("cleanup" in note.lower() for note in body_failure.__notes__)
    assert api.close() is True


def test_context_cleanup_annotation_cannot_override_the_body_exception() -> None:
    from ucrawl.tools import ToolsAPI

    class BrokenAddNoteError(ValueError):
        def add_note(self, note: str) -> None:
            del note
            raise KeyboardInterrupt("broken add_note")

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = BrokenAddNoteError("body remains primary")

    with pytest.raises(BrokenAddNoteError, match="body remains primary") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert isinstance(api._last_cleanup_error, RuntimeError)
    assert body_failure._tools_api_cleanup_error is api._last_cleanup_error
    assert api.close() is True


def test_cleanup_error_string_failure_cannot_replace_the_body_exception() -> None:
    from ucrawl.tools import ToolsAPI

    class AnnotationFailure(BaseException):
        pass

    class UnstringableCleanupError(RuntimeError):
        def __str__(self) -> str:
            raise AnnotationFailure("cleanup __str__ must remain best effort")

    cleanup_failure = UnstringableCleanupError()
    service = RecordingToolRunnerService(
        shutdown_outcomes=[cleanup_failure, True]
    )
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = ValueError("body remains primary")

    with pytest.raises(ValueError, match="body remains primary") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert api._last_cleanup_error is cleanup_failure
    assert api.close() is True


def test_cleanup_add_note_lookup_failure_cannot_replace_the_body_exception() -> None:
    from ucrawl.tools import ToolsAPI

    class AnnotationFailure(BaseException):
        pass

    class HostileBodyError(ValueError):
        def __getattribute__(self, name: str) -> Any:
            if name == "add_note":
                raise AnnotationFailure("add_note lookup must remain best effort")
            return super().__getattribute__(name)

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = HostileBodyError("body remains primary")

    with pytest.raises(HostileBodyError, match="body remains primary") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert isinstance(api._last_cleanup_error, RuntimeError)
    assert body_failure._tools_api_cleanup_error is api._last_cleanup_error
    assert api.close() is True


def test_cleanup_annotation_fallback_failure_cannot_replace_body_exception() -> None:
    from ucrawl.tools import ToolsAPI

    class AnnotationFailure(BaseException):
        pass

    class HostileBodyError(ValueError):
        def add_note(self, note: str) -> None:
            del note
            raise AnnotationFailure("add_note must remain best effort")

        def __setattr__(self, name: str, value: Any) -> None:
            if name == "_tools_api_cleanup_error":
                raise AnnotationFailure("fallback setattr must remain best effort")
            super().__setattr__(name, value)

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = HostileBodyError("body remains primary")

    with pytest.raises(HostileBodyError, match="body remains primary") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert isinstance(api._last_cleanup_error, RuntimeError)
    assert api.close() is True


def test_cleanup_failure_recording_bypasses_hostile_instance_setattr() -> None:
    from ucrawl.tools import ToolsAPI

    class LastCleanupRecordFailure(BaseException):
        pass

    class HostileToolsAPI(ToolsAPI):
        def __setattr__(self, name: str, value: Any) -> None:
            if name == "_last_cleanup_error" and isinstance(value, BaseException):
                raise LastCleanupRecordFailure("recording must remain best effort")
            super().__setattr__(name, value)

    service = RecordingToolRunnerService(shutdown_outcomes=[False, True])
    api = HostileToolsAPI(execution_profile=_sdk_profile(), service=service)
    body_failure = ValueError("body remains primary")

    with pytest.raises(ValueError, match="body remains primary") as raised:
        with api:
            api.list()
            raise body_failure

    assert raised.value is body_failure
    assert isinstance(api._last_cleanup_error, RuntimeError)
    assert api.close() is True


def test_close_from_an_active_lease_returns_false_without_deadlocking() -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)

    def reentrant_list() -> bool:
        return api.close()

    service.list = reentrant_list  # type: ignore[method-assign]

    assert api.list() is False
    assert service.shutdown_calls == []
    assert api._cleanup_service is service
    assert api.close() is True
    _assert_bounded_shutdown_calls(service)


def test_close_linearizes_with_lazy_creation_without_holding_lock_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = BlockingShutdownToolRunnerService()
    creation_entered = threading.Event()
    release_creation = threading.Event()

    def create_service() -> BlockingShutdownToolRunnerService:
        creation_entered.set()
        if not release_creation.wait(5.0):
            raise TimeoutError("test did not release service creation")
        return service

    monkeypatch.setattr(tools_module, "_create_service", create_service)
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    operation_errors: list[BaseException] = []
    close_results: list[bool] = []

    def use_api() -> None:
        try:
            api.list()
        except BaseException as exc:
            operation_errors.append(exc)

    operation_thread = threading.Thread(target=use_api)
    operation_thread.start()
    assert creation_entered.wait(2.0)

    close_thread = threading.Thread(target=lambda: close_results.append(api.close()))
    close_thread.start()
    deadline = time.monotonic() + 2.0
    while not api._closed and time.monotonic() < deadline:
        threading.Event().wait(0.001)
    assert api._closed is True

    release_creation.set()
    assert service.shutdown_entered.wait(2.0)

    rejected_errors: list[BaseException] = []
    rejected_done = threading.Event()

    def use_during_shutdown() -> None:
        try:
            api.describe("media.probe")
        except BaseException as exc:
            rejected_errors.append(exc)
        finally:
            rejected_done.set()

    rejected_thread = threading.Thread(target=use_during_shutdown)
    rejected_thread.start()
    assert rejected_done.wait(2.0), "shutdown must not hold the lifecycle lock"
    service.release_shutdown.set()

    operation_thread.join(2.0)
    rejected_thread.join(2.0)
    close_thread.join(2.0)
    assert not operation_thread.is_alive()
    assert not rejected_thread.is_alive()
    assert not close_thread.is_alive()
    assert close_results == [True]
    assert len(operation_errors) == 1
    assert isinstance(operation_errors[0], RuntimeError)
    assert len(rejected_errors) == 1
    assert isinstance(rejected_errors[0], RuntimeError)
    assert service.calls == []
    _assert_bounded_shutdown_calls(service)
    assert api._service is None
    assert api._cleanup_service is None


def test_lazy_creation_time_is_deducted_from_the_shutdown_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = TimedShutdownToolRunnerService()
    creation_entered = threading.Event()
    release_creation = threading.Event()
    close_budget = 0.5

    def create_service() -> TimedShutdownToolRunnerService:
        creation_entered.set()
        if not release_creation.wait(5.0):
            raise TimeoutError("test did not release service creation")
        return service

    monkeypatch.setattr(tools_module, "_create_service", create_service)
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    operation_errors: list[BaseException] = []
    close_results: list[bool] = []
    close_errors: list[BaseException] = []
    close_started_at: list[float] = []

    def use_api() -> None:
        try:
            api.list()
        except BaseException as exc:
            operation_errors.append(exc)

    def close_api() -> None:
        close_started_at.append(time.monotonic())
        try:
            close_results.append(api.close(timeout=close_budget))
        except BaseException as exc:
            close_errors.append(exc)

    operation_thread = threading.Thread(target=use_api)
    operation_thread.start()
    assert creation_entered.wait(2.0)

    close_thread = threading.Thread(target=close_api)
    close_thread.start()
    deadline = time.monotonic() + 2.0
    while not api._closed and time.monotonic() < deadline:
        threading.Event().wait(0.001)
    assert api._closed is True
    threading.Event().wait(0.05)
    release_creation.set()

    operation_thread.join(2.0)
    close_thread.join(2.0)
    assert not operation_thread.is_alive()
    assert not close_thread.is_alive()
    assert len(operation_errors) == 1
    assert isinstance(operation_errors[0], RuntimeError)
    assert close_errors == []
    assert close_results == [True]
    assert service.shutdown_called_at is not None
    assert len(service.shutdown_calls) == 1
    shutdown_timeout = service.shutdown_calls[0]["timeout"]
    assert isinstance(shutdown_timeout, float)
    consumed_before_shutdown = service.shutdown_called_at - close_started_at[0]
    assert consumed_before_shutdown >= 0.04
    assert shutdown_timeout <= max(0.0, close_budget - consumed_before_shutdown) + 0.02
    assert shutdown_timeout < close_budget - 0.03


def test_twelve_cold_start_callers_share_one_lazily_created_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = RecordingToolRunnerService()
    start = threading.Barrier(13)
    factory_entered = threading.Event()
    release_factory = threading.Event()
    factory_calls = 0
    factory_lock = threading.Lock()

    def create_service() -> RecordingToolRunnerService:
        nonlocal factory_calls
        with factory_lock:
            factory_calls += 1
        factory_entered.set()
        if not release_factory.wait(5.0):
            raise TimeoutError("test did not release cold-start factory")
        return service

    monkeypatch.setattr(tools_module, "_create_service", create_service)
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    results: list[dict[str, str]] = []
    errors: list[BaseException] = []

    def use_api() -> None:
        start.wait()
        try:
            results.append(api.list())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=use_api) for _ in range(12)]
    for thread in threads:
        thread.start()
    start.wait()
    assert factory_entered.wait(2.0)
    deadline = time.monotonic() + 2.0
    while getattr(api, "_active_calls", 0) != 12 and time.monotonic() < deadline:
        threading.Event().wait(0.001)
    assert api._active_calls == 12
    release_factory.set()
    for thread in threads:
        thread.join(2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert results == [service.responses["list"]] * 12
    assert factory_calls == 1
    assert api.close() is True


def test_factory_failure_wakes_waiter_to_retry_cold_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = RecordingToolRunnerService()
    start = threading.Barrier(3)
    first_factory_entered = threading.Event()
    release_first_factory = threading.Event()
    factory_calls = 0
    factory_lock = threading.Lock()
    first_failure = RuntimeError("first factory failed")

    def create_service() -> RecordingToolRunnerService:
        nonlocal factory_calls
        with factory_lock:
            factory_calls += 1
            call_number = factory_calls
        if call_number == 1:
            first_factory_entered.set()
            if not release_first_factory.wait(5.0):
                raise TimeoutError("test did not release first factory")
            raise first_failure
        return service

    monkeypatch.setattr(tools_module, "_create_service", create_service)
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())
    results: list[dict[str, str]] = []
    errors: list[BaseException] = []

    def use_api() -> None:
        start.wait()
        try:
            results.append(api.list())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=use_api) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    assert first_factory_entered.wait(2.0)
    release_first_factory.set()
    for thread in threads:
        thread.join(2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [service.responses["list"]]
    assert errors == [first_failure]
    assert factory_calls == 2
    assert api.close() is True


def test_close_waits_for_an_admitted_validate_before_shutdown() -> None:
    from ucrawl.tools import ToolsAPI

    service = BlockingValidateToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_results: list[dict[str, str]] = []
    validate_errors: list[BaseException] = []
    close_results: list[bool] = []
    close_done = threading.Event()

    def validate() -> None:
        try:
            validate_results.append(api.validate("media.probe", {}))
        except BaseException as exc:
            validate_errors.append(exc)

    def close() -> None:
        close_results.append(api.close())
        close_done.set()

    validate_thread = threading.Thread(target=validate)
    validate_thread.start()
    assert service.validate_entered.wait(2.0)

    close_thread = threading.Thread(target=close)
    close_thread.start()
    shutdown_started_before_release = service.shutdown_entered.wait(0.05)
    service.release_validate.set()
    assert service.validate_waiting_to_finish.wait(2.0)
    shutdown_started_before_return = service.shutdown_entered.is_set()
    assert close_done.is_set() is False
    service.finish_validate.set()

    validate_thread.join(2.0)
    close_thread.join(2.0)
    assert not validate_thread.is_alive()
    assert not close_thread.is_alive()
    assert validate_errors == []
    assert validate_results == [service.responses["validate"]]
    assert close_results == [True]
    assert shutdown_started_before_release is False
    assert shutdown_started_before_return is False
    assert service.shutdown_entered.is_set()
    _assert_bounded_shutdown_calls(service)


def test_close_respects_an_explicit_short_budget_when_an_active_call_never_finishes() -> None:
    from ucrawl.tools import ToolsAPI

    service = BlockingValidateToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_thread = threading.Thread(
        target=lambda: api.validate("media.probe", {}),
    )
    validate_thread.start()
    assert service.validate_entered.wait(2.0)

    started_at = time.monotonic()
    assert api.close(timeout=0.05) is False
    elapsed = time.monotonic() - started_at
    shutdown_calls_before_release = list(service.shutdown_calls)

    assert elapsed < 0.5

    service.release_validate.set()
    service.finish_validate.set()
    validate_thread.join(2.0)
    assert not validate_thread.is_alive()
    assert api.close(timeout=0.5) is True
    assert shutdown_calls_before_release == []
    _assert_bounded_shutdown_calls(service)


def test_default_close_budget_is_public_and_actually_bounds_active_wait() -> None:
    from ucrawl.tools import DEFAULT_TOOL_CLOSE_TIMEOUT, ToolsAPI

    assert DEFAULT_TOOL_CLOSE_TIMEOUT == 1.0
    service = BlockingValidateToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_thread = threading.Thread(
        target=lambda: api.validate("media.probe", {}),
    )
    validate_thread.start()
    assert service.validate_entered.wait(2.0)

    started_at = time.monotonic()
    assert api.close() is False
    elapsed = time.monotonic() - started_at
    shutdown_calls_before_release = list(service.shutdown_calls)

    assert DEFAULT_TOOL_CLOSE_TIMEOUT * 0.75 <= elapsed < 1.5
    service.release_validate.set()
    service.finish_validate.set()
    validate_thread.join(2.0)
    assert not validate_thread.is_alive()
    assert api.close(timeout=0.5) is True
    assert shutdown_calls_before_release == []
    _assert_bounded_shutdown_calls(service)


def test_zero_close_budget_retains_cleanup_without_shutting_down_an_active_call() -> None:
    from ucrawl.tools import ToolsAPI

    service = BlockingValidateToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_thread = threading.Thread(
        target=lambda: api.validate("media.probe", {}),
    )
    validate_thread.start()
    assert service.validate_entered.wait(2.0)

    started_at = time.monotonic()
    assert api.close(timeout=0.0) is False
    elapsed = time.monotonic() - started_at
    shutdown_calls_before_release = list(service.shutdown_calls)

    assert elapsed < 0.2
    assert api._cleanup_service is service
    service.release_validate.set()
    service.finish_validate.set()
    validate_thread.join(2.0)
    assert not validate_thread.is_alive()
    assert api.close(timeout=0.5) is True
    assert shutdown_calls_before_release == []
    _assert_bounded_shutdown_calls(service)


def test_active_wait_is_deducted_from_the_shutdown_budget() -> None:
    from ucrawl.tools import ToolsAPI

    service = BudgetConsumingShutdownService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_thread = threading.Thread(
        target=lambda: api.validate("media.probe", {}),
    )
    validate_thread.start()
    assert service.validate_entered.wait(2.0)

    def finish_validate_after_part_of_budget() -> None:
        threading.Event().wait(0.02)
        service.release_validate.set()
        if not service.validate_waiting_to_finish.wait(2.0):
            return
        service.finish_validate.set()

    release_thread = threading.Thread(target=finish_validate_after_part_of_budget)
    release_thread.start()
    started_at = time.monotonic()
    assert api.close(timeout=0.05) is True
    elapsed = time.monotonic() - started_at

    assert 0.04 <= elapsed < 0.3
    assert api._cleanup_service is None
    release_thread.join(2.0)
    validate_thread.join(2.0)
    assert not release_thread.is_alive()
    assert not validate_thread.is_alive()
    assert len(service.shutdown_calls) == 1
    shutdown_timeout = service.shutdown_calls[0]["timeout"]
    assert isinstance(shutdown_timeout, float)
    assert 0.0 <= shutdown_timeout < 0.05


def test_overlapping_close_callers_use_independent_budgets_and_shutdown_once() -> None:
    from ucrawl.tools import ToolsAPI

    service = BlockingShutdownToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    first_results: list[bool] = []
    first_errors: list[BaseException] = []

    def close_with_longer_budget() -> None:
        try:
            first_results.append(api.close(timeout=0.5))
        except BaseException as exc:
            first_errors.append(exc)

    first_thread = threading.Thread(target=close_with_longer_budget)
    first_thread.start()
    assert service.shutdown_entered.wait(2.0)

    second_started = time.monotonic()
    assert api.close(timeout=0.03) is False
    second_elapsed = time.monotonic() - second_started
    assert 0.015 <= second_elapsed < 0.2
    assert len(service.shutdown_calls) == 1

    service.release_shutdown.set()
    first_thread.join(2.0)
    assert not first_thread.is_alive()
    assert first_errors == []
    assert first_results == [True]
    assert api._cleanup_service is None
    assert api.close(timeout=0.0) is True
    assert len(service.shutdown_calls) == 1


def test_context_manager_uses_the_bounded_default_close_budget() -> None:
    from ucrawl.tools import DEFAULT_TOOL_CLOSE_TIMEOUT, ToolsAPI

    service = BlockingValidateToolRunnerService()
    api = ToolsAPI(execution_profile=_sdk_profile(), service=service)
    validate_thread = threading.Thread(
        target=lambda: api.validate("media.probe", {}),
    )

    started_at = time.monotonic()
    with pytest.raises(RuntimeError, match="did not complete"):
        with api:
            validate_thread.start()
            assert service.validate_entered.wait(2.0)
    elapsed = time.monotonic() - started_at

    assert DEFAULT_TOOL_CLOSE_TIMEOUT * 0.75 <= elapsed < 1.5
    assert api._cleanup_service is service
    shutdown_calls_before_release = list(service.shutdown_calls)
    service.release_validate.set()
    service.finish_validate.set()
    validate_thread.join(2.0)
    assert not validate_thread.is_alive()
    assert api.close(timeout=0.5) is True
    assert shutdown_calls_before_release == []
    _assert_bounded_shutdown_calls(service)


def test_close_before_first_use_does_not_load_the_lazy_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    imported_modules: list[str] = []

    def import_service(name: str) -> SimpleNamespace:
        imported_modules.append(name)
        return SimpleNamespace(ToolRunnerService=RecordingToolRunnerService)

    monkeypatch.setattr(tools_module, "import_module", import_service)
    api = tools_module.ToolsAPI(execution_profile=_sdk_profile())

    assert api.close() is True

    assert imported_modules == []
    with pytest.raises(RuntimeError, match="closed"):
        api.history()
    assert imported_modules == []


def test_context_manager_closes_the_lazily_loaded_service_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ucrawl.tools as tools_module

    service = RecordingToolRunnerService()
    monkeypatch.setattr(
        tools_module,
        "import_module",
        lambda _name: SimpleNamespace(ToolRunnerService=lambda: service),
    )

    with tools_module.ToolsAPI(execution_profile=_sdk_profile()) as api:
        assert api.list() is service.responses["list"]

    _assert_bounded_shutdown_calls(service)


def test_ucrawl_sdk_exposes_one_cached_tools_api() -> None:
    from ucrawl import ToolsAPI, UcrawlSDK

    sdk = UcrawlSDK(save_dir=".")

    assert isinstance(sdk.tools, ToolsAPI)
    assert sdk.tools is sdk.tools
    assert sdk.tools._execution_profile is sdk.execution_profile


def test_ucrawl_sdk_cached_tools_close_is_terminal(tmp_path: Path) -> None:
    from ucrawl import UcrawlSDK

    first = UcrawlSDK(save_dir=str(tmp_path / "shared"))

    tools = first.tools
    profile = first.execution_profile
    assert tools._execution_profile is profile
    assert tools._execution_profile.owner_id == profile.owner_id

    first.close()
    first.close()

    with pytest.raises(RuntimeError, match="closed"):
        first.tools
    with pytest.raises(RuntimeError, match="closed"):
        tools.list()
