"""CLI contract for ``ucrawl tools``."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

import pytest

from shared.execution_profile import DEFAULT_LOCAL_TOOL_PERMISSIONS, ExecutionProfile


class RunIdStringSubclass(str):
    """A string-like run id must not cross the exact protocol boundary."""


class HostileRunId:
    def __str__(self) -> str:
        raise RuntimeError("run_id string conversion must not be attempted")


class HostileCancellationError(RuntimeError):
    def __str__(self) -> str:
        raise RuntimeError("cancellation error formatting must not be attempted")


class RecordingToolsAPI:
    def __init__(self, execution_profile: ExecutionProfile | None = None) -> None:
        self.execution_profile = execution_profile
        self.close_calls = 0
        self.close_result = True
        self.close_error: BaseException | None = None
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses = {
            name: {"operation": name, "status": "ok"}
            for name in ("list", "describe", "validate", "cancel", "history")
        }
        self.responses["run"] = {"status": "queued", "run_id": "run-42"}
        self.responses["wait_for_run"] = {
            "status": "succeeded",
            "run_id": "run-42",
        }

    def _record(self, operation: str, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls.append((operation, args, kwargs))
        return self.responses[operation]

    def list(self) -> dict[str, str]:
        return self._record("list")

    def describe(self, tool_id: str) -> dict[str, str]:
        return self._record("describe", tool_id)

    def validate(self, tool_id: str, params: dict[str, Any]) -> dict[str, str]:
        return self._record("validate", tool_id, params)

    def run(self, tool_id: str, params: dict[str, Any]) -> dict[str, str]:
        return self._record("run", tool_id, params)

    def cancel(self, run_id: str) -> dict[str, str]:
        return self._record("cancel", run_id)

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        return self._record("wait_for_run", run_id, timeout=timeout)

    def history(self, **filters: Any) -> dict[str, str]:
        return self._record("history", **filters)

    def close(self) -> bool:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error
        return self.close_result


def _hostile_cleanup_error(attack_surface: str) -> BaseException:
    class HostileText(str):
        def __format__(self, format_spec: str) -> str:
            del format_spec
            raise RuntimeError("hostile cleanup metadata formatting")

    if attack_surface == "detail":
        class HostileCleanupDetailError(RuntimeError):
            def __str__(self) -> str:
                return HostileText("attacker-controlled cleanup detail")

        return HostileCleanupDetailError()

    class HostileCleanupType(type):
        def __getattribute__(cls, name: str) -> Any:
            if name == "__name__":
                return HostileText("AttackerControlledCleanupType")
            return super().__getattribute__(name)

    class HostileCleanupTypeError(RuntimeError, metaclass=HostileCleanupType):
        def __str__(self) -> str:
            raise RuntimeError("cleanup string conversion failed")

    return HostileCleanupTypeError()


def _hostile_unavailable_error(attack_surface: str) -> BaseException:
    from ucrawl.tools import ToolRunnerUnavailableError

    class HostileText(str):
        def __format__(self, format_spec: str) -> str:
            del format_spec
            raise RuntimeError("unavailable error formatting must not be attempted")

    if attack_surface == "detail":
        class HostileUnavailableDetailError(ToolRunnerUnavailableError):
            def __str__(self) -> str:
                return HostileText("attacker-controlled unavailable detail")

        return HostileUnavailableDetailError()

    class HostileUnavailableType(type):
        def __getattribute__(cls, name: str) -> Any:
            if name == "__name__":
                return HostileText("AttackerControlledUnavailableType")
            return super().__getattribute__(name)

    class HostileUnavailableTypeError(
        ToolRunnerUnavailableError,
        metaclass=HostileUnavailableType,
    ):
        def __str__(self) -> str:
            raise RuntimeError("unavailable string conversion failed")

    return HostileUnavailableTypeError()


@pytest.mark.parametrize(
    ("argv", "expected_call"),
    (
        (["tools", "list"], ("list", (), {})),
        (
            ["tools", "describe", "media.probe"],
            ("describe", ("media.probe",), {}),
        ),
        (
            ["tools", "validate", "media.probe", "--params", '{"path":"demo.mp4"}'],
            ("validate", ("media.probe", {"path": "demo.mp4"}), {}),
        ),
        (
            [
                "tools",
                "history",
                "--tool-id",
                "media.probe",
                "--status",
                "failed",
                "--limit",
                "7",
            ],
            (
                "history",
                (),
                {"tool_id": "media.probe", "status": "failed", "limit": 7},
            ),
        ),
    ),
)
def test_tools_subcommands_forward_to_sdk_and_emit_json(
    argv: list[str],
    expected_call: tuple[str, tuple[Any, ...], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(argv) == 0
    assert api.calls == [expected_call]
    assert json.loads(capsys.readouterr().out) == {
        "operation": expected_call[0],
        "status": "ok",
    }
    assert api.close_calls == 1
    assert api.execution_profile is not None
    assert api.execution_profile.host_surface == "cli"
    assert api.execution_profile.owner_id == "cli:local"
    assert api.execution_profile.tool_permissions == DEFAULT_LOCAL_TOOL_PERMISSIONS
    assert api.execution_profile.allow_external_plugins is False
    assert api.execution_profile.approved_roots == frozenset(
        {Path(tools_command.get_default_save_dir()).expanduser().resolve()}
    )


def test_tools_run_waits_for_terminal_result_on_the_same_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 0
    assert api.calls == [
        ("run", ("media.probe", {}), {}),
        ("wait_for_run", ("run-42",), {"timeout": None}),
    ]
    assert json.loads(capsys.readouterr().out) == {
        "status": "succeeded",
        "run_id": "run-42",
    }
    assert api.close_calls == 1


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
def test_tools_run_fails_closed_for_an_invalid_queued_run_id_without_waiting(
    run_id: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    api.responses["run"] = {"status": "queued", "run_id": run_id}
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "error",
        "code": "tool_protocol_error",
        "message": "tool runner returned a queued result without a valid run_id",
    }
    assert api.calls == [("run", ("media.probe", {}), {})]
    assert api.close_calls == 1


def test_tools_run_composes_real_runner_to_terminal_and_closes_without_thread_leaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public CLI must keep the actual runner alive through terminal output."""
    from app.services import tool_runner_service as runner_module
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolsAPI

    baseline_threads = set(threading.enumerate())
    transitions: list[dict[str, Any]] = []
    close_results: list[bool] = []
    original_run = ToolsAPI.run
    original_wait_for_run = ToolsAPI.wait_for_run
    original_close = ToolsAPI.close

    def observe_run(
        self: ToolsAPI,
        tool_id: str,
        params: dict[str, Any] | None,
    ) -> Any:
        result = original_run(self, tool_id, params)
        transitions.append(result)
        return result

    def observe_wait_for_run(
        self: ToolsAPI,
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> Any:
        result = original_wait_for_run(self, run_id, timeout=timeout)
        transitions.append(result)
        return result

    def observe_close(self: ToolsAPI) -> bool:
        result = original_close(self)
        close_results.append(result)
        return result

    monkeypatch.setattr(tools_command, "get_default_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(runner_module, "user_cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(runner_module, "user_data_root", lambda: tmp_path / "data")
    monkeypatch.setattr(ToolsAPI, "run", observe_run)
    monkeypatch.setattr(ToolsAPI, "wait_for_run", observe_wait_for_run)
    monkeypatch.setattr(ToolsAPI, "close", observe_close)

    params = {
        "roots": [str(tmp_path)],
        "ledger_path": str(tmp_path / "download-recovery.sqlite3"),
        "max_depth": 0,
        "cleanup": False,
    }
    assert main(
        [
            "tools",
            "run",
            "download_residue",
            "--params",
            json.dumps(params),
        ]
    ) == 0

    terminal = json.loads(capsys.readouterr().out)
    assert [item["status"] for item in transitions] == ["queued", "succeeded"]
    assert terminal["status"] == "succeeded"
    assert terminal["run_id"] == transitions[0]["run_id"]
    assert close_results == [True]
    leaked_threads = [
        thread
        for thread in threading.enumerate()
        if thread not in baseline_threads
        and thread.is_alive()
        and thread.name.startswith(("tool-runner", "tool-history"))
    ]
    assert leaked_threads == []


def test_tools_run_interrupt_cancels_and_briefly_waits_on_the_same_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    wait_calls = 0

    def interrupt_then_cancelled(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        nonlocal wait_calls
        wait_calls += 1
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if wait_calls == 1:
            raise KeyboardInterrupt
        return {"status": "cancelled", "run_id": run_id}

    api.wait_for_run = interrupt_then_cancelled  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 130
    assert api.calls == [
        ("run", ("media.probe", {}), {}),
        ("wait_for_run", ("run-42",), {"timeout": None}),
        ("cancel", ("run-42",), {}),
        ("wait_for_run", ("run-42",), {"timeout": 1.0}),
    ]
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
    assert api.close_calls == 1


def test_tools_standalone_cancel_is_usage_error_without_creating_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    def unexpected_api(**_kwargs: Any) -> RecordingToolsAPI:
        raise AssertionError("standalone cancel must not create ToolsAPI")

    monkeypatch.setattr(tools_command, "ToolsAPI", unexpected_api)

    assert main(["tools", "cancel", "run-42"]) == 2
    assert "cancellation is process-scoped" in capsys.readouterr().err


def test_tools_rejects_non_object_params_before_calling_sdk(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe", "--params", "[]"]) == 2
    assert api.calls == []
    assert "JSON object" in capsys.readouterr().err


def test_tools_reports_unavailable_mainline_service_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolRunnerUnavailableError

    class UnavailableToolsAPI:
        def __init__(self, *, execution_profile: ExecutionProfile) -> None:
            del execution_profile
            self.close_calls = 0

        def list(self) -> None:
            raise ToolRunnerUnavailableError("service contract is unavailable")

        def close(self) -> bool:
            self.close_calls += 1
            return True

    monkeypatch.setattr(tools_command, "ToolsAPI", UnavailableToolsAPI)

    assert main(["tools", "list"]) == 1
    assert "service contract is unavailable" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("attack_surface", "expected_diagnostic"),
    (
        (
            "detail",
            "tool runner operation failed with HostileUnavailableDetailError",
        ),
        ("type_name", "tool runner operation failed with unknown error"),
    ),
)
def test_tools_unavailable_error_survives_hostile_primary_metadata(
    attack_surface: str,
    expected_diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    unavailable_error = _hostile_unavailable_error(attack_surface)

    def unavailable() -> None:
        raise unavailable_error

    api.list = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == expected_diagnostic + "\n"
    assert api.close_calls == 1


@pytest.mark.parametrize("write_error", (ValueError("closed"), TypeError("broken")))
def test_tools_unavailable_exit_is_preserved_when_stderr_write_fails(
    write_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolRunnerUnavailableError

    api = RecordingToolsAPI()

    def unavailable() -> None:
        raise ToolRunnerUnavailableError("service unavailable")

    class FailingStderr:
        def write(self, _message: str) -> int:
            raise write_error

    api.list = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )
    monkeypatch.setattr(tools_command.sys, "stderr", FailingStderr())

    assert main(["tools", "list"]) == 1
    assert api.close_calls == 1


@pytest.mark.parametrize("close_mode", ("false", "exception"))
def test_tools_cleanup_failure_is_observable_after_successful_operation(
    close_mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    if close_mode == "false":
        api.close_result = False
    else:
        api.close_error = RuntimeError("cleanup unavailable")
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["operation"] == "list"
    assert "cleanup" in captured.err.lower()


def test_tools_cleanup_keyboard_interrupt_reaches_cli_cancellation_handler(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cleanup Ctrl+C must remain process cancellation, not a routine error."""
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    api.close_error = KeyboardInterrupt()
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 130
    assert api.close_calls == 1
    assert capsys.readouterr().out == ""


def test_tools_cleanup_system_exit_propagates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cleanup SystemExit must retain its process-control semantics."""
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    api.close_error = SystemExit(7)
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    with pytest.raises(SystemExit) as raised:
        main(["tools", "list"])

    assert raised.value.code == 7
    assert api.close_calls == 1
    assert capsys.readouterr().out == ""


def test_tools_cleanup_exception_does_not_replace_operation_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolRunnerUnavailableError

    api = RecordingToolsAPI()
    api.close_error = RuntimeError("cleanup unavailable")

    def unavailable() -> None:
        raise ToolRunnerUnavailableError("operation unavailable")

    api.list = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 1
    errors = capsys.readouterr().err
    assert "operation unavailable" in errors
    assert "cleanup unavailable" in errors


@pytest.mark.parametrize(
    ("cleanup_error", "cleanup_diagnostic"),
    (
        (KeyboardInterrupt(), "KeyboardInterrupt"),
        (SystemExit(7), "tool runner cleanup failed: 7"),
    ),
)
def test_tools_cleanup_control_error_is_secondary_to_unavailable_operation(
    cleanup_error: BaseException,
    cleanup_diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A recognized operation failure stays primary over cleanup control flow."""
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolRunnerUnavailableError

    api = RecordingToolsAPI()
    api.close_error = cleanup_error

    def unavailable() -> None:
        raise ToolRunnerUnavailableError("operation unavailable")

    api.list = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 1
    errors = capsys.readouterr().err
    assert "operation unavailable" in errors
    assert cleanup_diagnostic in errors


@pytest.mark.parametrize(
    ("attack_surface", "cleanup_diagnostic"),
    (
        ("detail", "HostileCleanupDetailError"),
        ("type_name", "unknown error"),
    ),
)
def test_tools_unavailable_error_survives_hostile_cleanup_metadata(
    attack_surface: str,
    cleanup_diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unavailable-operation handling must use a non-throwing cleanup description."""
    from cli.commands import tools as tools_command
    from cli.main import main
    from ucrawl.tools import ToolRunnerUnavailableError

    api = RecordingToolsAPI()
    api.close_error = _hostile_cleanup_error(attack_surface)

    def unavailable() -> None:
        raise ToolRunnerUnavailableError("operation unavailable")

    api.list = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "list"]) == 1
    errors = capsys.readouterr().err
    assert "operation unavailable" in errors
    assert cleanup_diagnostic in errors


def test_tools_cleanup_exception_is_secondary_to_unexpected_operation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finally cleanup failure must not hide an unexpected operation failure."""
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    api.close_error = RuntimeError("cleanup unavailable")

    def broken_operation() -> None:
        raise ValueError("operation failed")

    api.list = broken_operation  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    with pytest.raises(ValueError, match="operation failed") as raised:
        main(["tools", "list"])
    assert any(
        "cleanup unavailable" in note
        for note in getattr(raised.value, "__notes__", ())
    )


@pytest.mark.parametrize("attack_surface", ("detail", "type_name"))
def test_tools_cleanup_annotation_cannot_replace_hostile_operation_error(
    attack_surface: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup formatting and annotation lookup cannot become the primary error."""
    from cli.commands import tools as tools_command
    from cli.main import main

    class HostileOperationError(ValueError):
        def __getattribute__(self, name: str) -> Any:
            if name == "add_note":
                raise RuntimeError("annotation lookup failed")
            return super().__getattribute__(name)

    api = RecordingToolsAPI()
    api.close_error = _hostile_cleanup_error(attack_surface)
    operation_error = HostileOperationError("operation failed")

    def broken_operation() -> None:
        raise operation_error

    api.list = broken_operation  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    with pytest.raises(HostileOperationError) as raised:
        main(["tools", "list"])
    assert raised.value is operation_error


def test_tools_interrupt_returns_cancelled_even_when_cancel_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C remains process cancellation when cancel or brief wait has trouble."""
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()

    def interrupted_wait(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if timeout is None:
            raise KeyboardInterrupt
        raise TimeoutError("still stopping")

    def failed_cancel(run_id: str) -> dict[str, str]:
        api.calls.append(("cancel", (run_id,), {}))
        raise RuntimeError("cancel request failed")

    api.wait_for_run = interrupted_wait  # type: ignore[method-assign]
    api.cancel = failed_cancel  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 130
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "cancelled", "run_id": "run-42"}
    assert "tool cancellation request failed" in captured.err
    assert "tool cancellation wait failed" in captured.err


@pytest.mark.parametrize(
    ("cancel_error", "brief_wait_error"),
    (
        (ValueError("cancel value failure"), TypeError("wait type failure")),
        (TypeError("cancel type failure"), ValueError("wait value failure")),
    ),
)
def test_tools_interrupt_treats_ordinary_cancel_and_wait_failures_as_secondary(
    cancel_error: Exception,
    brief_wait_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()

    def interrupted_wait(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if timeout is None:
            raise KeyboardInterrupt
        raise brief_wait_error

    def failed_cancel(run_id: str) -> dict[str, str]:
        api.calls.append(("cancel", (run_id,), {}))
        raise cancel_error

    api.wait_for_run = interrupted_wait  # type: ignore[method-assign]
    api.cancel = failed_cancel  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 130
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "cancelled", "run_id": "run-42"}
    assert "tool cancellation request failed" in captured.err
    assert "tool cancellation wait failed" in captured.err


@pytest.mark.parametrize(
    ("stage", "expected_diagnostic"),
    (
        ("cancel", "tool cancellation request failed"),
        ("brief_wait", "tool cancellation wait failed"),
    ),
)
def test_tools_interrupt_survives_hostile_cancellation_error_metadata(
    stage: str,
    expected_diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()

    def interrupted_wait(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if timeout is None:
            raise KeyboardInterrupt
        if stage == "brief_wait":
            raise HostileCancellationError()
        return {"status": "cancelled", "run_id": run_id}

    def cancel(run_id: str) -> dict[str, str]:
        api.calls.append(("cancel", (run_id,), {}))
        if stage == "cancel":
            raise HostileCancellationError()
        return {"status": "cancelling", "run_id": run_id}

    api.wait_for_run = interrupted_wait  # type: ignore[method-assign]
    api.cancel = cancel  # type: ignore[method-assign]
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 130
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "cancelled", "run_id": "run-42"}
    assert expected_diagnostic in captured.err


@pytest.mark.parametrize("write_error", (ValueError("closed"), TypeError("broken")))
def test_secondary_stderr_diagnostic_ignores_ordinary_write_failures(
    write_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import tools as tools_command

    class FailingStderr:
        def write(self, _message: str) -> int:
            raise write_error

    monkeypatch.setattr(tools_command.sys, "stderr", FailingStderr())

    tools_command._write_secondary_diagnostic("stable diagnostic\n")


@pytest.mark.parametrize(
    ("control_type", "control_args"),
    (
        (KeyboardInterrupt, ()),
        (SystemExit, (7,)),
    ),
)
def test_secondary_stderr_diagnostic_does_not_swallow_control_flow(
    control_type: type[BaseException],
    control_args: tuple[object, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import tools as tools_command

    control_error = control_type(*control_args)

    class FailingStderr:
        def write(self, _message: str) -> int:
            raise control_error

    monkeypatch.setattr(tools_command.sys, "stderr", FailingStderr())

    with pytest.raises(control_type) as raised:
        tools_command._write_secondary_diagnostic("stable diagnostic\n")

    assert raised.value is control_error


@pytest.mark.parametrize("stage", ("cancel", "brief_wait"))
@pytest.mark.parametrize(
    ("control_type", "control_args"),
    (
        (KeyboardInterrupt, ()),
        (SystemExit, (7,)),
    ),
)
def test_tools_interrupt_does_not_swallow_control_flow_during_compensation(
    stage: str,
    control_type: type[BaseException],
    control_args: tuple[object, ...],
) -> None:
    from cli.commands import tools as tools_command

    api = RecordingToolsAPI()
    control_error = control_type(*control_args)

    def interrupted_wait(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if timeout is None:
            raise KeyboardInterrupt
        if stage == "brief_wait":
            raise control_error
        return {"status": "cancelled", "run_id": run_id}

    def cancel(run_id: str) -> dict[str, str]:
        api.calls.append(("cancel", (run_id,), {}))
        if stage == "cancel":
            raise control_error
        return {"status": "cancelling", "run_id": run_id}

    api.wait_for_run = interrupted_wait  # type: ignore[method-assign]
    api.cancel = cancel  # type: ignore[method-assign]

    with pytest.raises(control_type) as raised:
        tools_command._wait_for_run(
            api,  # type: ignore[arg-type]
            {"status": "queued", "run_id": "run-42"},
        )

    assert raised.value is control_error


@pytest.mark.parametrize("close_mode", ("false", "exception"))
def test_tools_interrupt_stays_cancelled_when_ordinary_close_cleanup_fails(
    close_mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    wait_calls = 0

    def interrupt_then_cancelled(
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, str]:
        nonlocal wait_calls
        wait_calls += 1
        api.calls.append(("wait_for_run", (run_id,), {"timeout": timeout}))
        if wait_calls == 1:
            raise KeyboardInterrupt
        return {"status": "cancelled", "run_id": run_id}

    api.wait_for_run = interrupt_then_cancelled  # type: ignore[method-assign]
    if close_mode == "false":
        api.close_result = False
    else:
        api.close_error = ValueError("cleanup value failure")
    monkeypatch.setattr(
        tools_command,
        "ToolsAPI",
        lambda *, execution_profile: _bind(api, execution_profile),
    )

    assert main(["tools", "run", "media.probe"]) == 130
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "cancelled", "run_id": "run-42"}
    assert "cleanup" in captured.err.lower()
    assert api.close_calls == 1


def _bind(api: RecordingToolsAPI, profile: ExecutionProfile) -> RecordingToolsAPI:
    api.execution_profile = profile
    return api
