from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import app.services.tool_runner_service as tool_runner_module
from app.core.tools.contracts import (
    ToolManifest,
    ToolRequirements,
    ToolRunResult,
    ToolValidationResult,
)
from app.core.tools.registry import ToolRegistry, ToolReloadResult
from app.services.tool_history_projection import project_history_record
from app.services.tool_runner_service import ToolRunnerService
from shared.execution_profile import local_execution_profile, public_web_profile


class EchoTool:
    manifest = ToolManifest(
        id="echo",
        title="Echo",
        summary="Echo parameters",
        input_schema={"value": {"type": "string", "required": True}},
    )

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return [] if context.parameters.get("value") else ["value is required"]

    def run(self, context):
        context.report_progress(50, "half")
        return ToolRunResult.success("done", data={"value": context.parameters["value"]})


class OutputTool:
    manifest = ToolManifest(
        id="output",
        title="Output",
        summary="Return one private output path",
        input_schema={"path": {"type": "string", "required": True}},
    )

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return [] if context.parameters.get("path") else ["path is required"]

    def run(self, context):
        return ToolRunResult.success(
            "private output",
            data={"artifacts": {"count": 1}},
            output_paths=(str(context.parameters["path"]),),
            private_data={
                "candidates": [
                    {
                        "candidate_id": "candidate-1",
                        "private_url": (
                            "https://example.com/watch?token=private-result-sentinel"
                        ),
                    }
                ]
            },
        )


class BlockingTool:
    manifest = ToolManifest(
        id="blocking",
        title="Blocking",
        summary="Wait for cancellation",
        supports_cancel=True,
    )

    def __init__(self) -> None:
        self.started = threading.Event()

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return []

    def run(self, context):
        self.started.set()
        while not context.is_cancelled():
            context.cancellation.wait(0.01)
        context.raise_if_cancelled()
        raise AssertionError("unreachable")


class StubbornTool:
    manifest = ToolManifest(
        id="stubborn",
        title="Stubborn",
        summary="Ignores cancellation until the test releases it",
        supports_cancel=True,
    )

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return []

    def run(self, context):
        self.started.set()
        self.release.wait()
        return ToolRunResult.success("released")


class PrivateBlockingTool:
    manifest = ToolManifest(
        id="private-blocking",
        title="Private blocking",
        summary="Return private structured data after release",
        supports_cancel=True,
    )

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return []

    def run(self, context):
        self.started.set()
        self.release.wait()
        return ToolRunResult.success(
            "released",
            data={"candidate_id": "terminal-structured"},
            private_data={"candidate_id": "terminal-private"},
        )


class FailedPrivateTool:
    manifest = ToolManifest(
        id="failed-private",
        title="Failed private",
        summary="Return private data with a failed result",
    )

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        del context
        return []

    def run(self, context):
        del context
        return ToolRunResult.failure(
            "failed",
            private_data={"candidate_id": "must-not-be-readable"},
        )


class ReturningTool:
    manifest = ToolManifest(
        id="returning",
        title="Returning",
        summary="Signals immediately before returning",
        supports_cancel=True,
    )

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.returning = threading.Event()

    @staticmethod
    def requirements_for(parameters):
        del parameters
        return ToolRequirements()

    def validate(self, context):
        return []

    def run(self, context):
        self.started.set()
        self.release.wait()
        self.returning.set()
        return ToolRunResult.success("returned")


class CountingTool:
    manifest = ToolManifest(
        id="counting",
        title="Counting",
        summary="Counts plugin callbacks",
        permissions=("read_file", "write_file"),
    )

    def __init__(self) -> None:
        self.requirements_calls = 0
        self.validate_calls = 0
        self.run_calls = 0

    def requirements_for(self, parameters):
        self.requirements_calls += 1
        mode = str(parameters.get("mode") or "read")
        permission = "write_file" if mode == "write" else "read_file"
        return ToolRequirements(frozenset({permission}))

    def validate(self, context):
        self.validate_calls += 1
        if context.parameters.get("normalize_to_write"):
            return ToolValidationResult.ok(parameters={"mode": "write"})
        return ToolValidationResult.ok(parameters=context.parameters)

    def run(self, context):
        self.run_calls += 1
        return ToolRunResult.success(
            "completed",
            data={"token": "plugin-secret", "path": "D:/private/video.mp4"},
            output_paths=("D:/private/video.mp4",),
            warnings=("safe warning",),
        )


def _registry(*tools):
    registry = ToolRegistry(
        tools=[],
        include_builtins=False,
        include_entry_points=False,
    )
    # These test doubles model application-owned built-ins. Registering them with
    # explicit builtin provenance keeps grant checks real without enabling plugins.
    for tool in tools:
        registry._register(tool, provenance="builtin")
    return registry


def _profile(
    tmp_path: Path,
    *,
    owner_id: str = "unit:runner",
    host_surface: str = "test",
    permissions=(),
    allow_external_plugins: bool = False,
):
    return local_execution_profile(
        host_surface=host_surface,
        owner_id=owner_id,
        approved_roots=(tmp_path,),
        tool_permissions=permissions,
        allow_external_plugins=allow_external_plugins,
    )


def _terminal_row(
    run_id: str,
    created_at: float,
    *,
    owner_id: str = "gui:history",
    host_surface: str = "desktop_gui",
) -> dict:
    return {
        "run_id": run_id,
        "tool_id": "echo",
        "host_surface": host_surface,
        "owner_id": owner_id,
        "status": "succeeded",
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": created_at,
        "progress": 100,
        "message": "done",
        "result": {"status": "succeeded", "message": "done", "warnings": []},
    }


def _invalid_profile(tmp_path: Path, *, field: str):
    profile = _profile(tmp_path)
    object.__setattr__(profile, field, "   ")
    return profile


def _persisted_by_id(history_path: Path) -> dict[str, dict]:
    return {
        row["run_id"]: row
        for row in json.loads(history_path.read_text(encoding="utf-8"))
    }


def _active_tool_threads() -> list[str]:
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith(("tool-runner", "tool-history"))
    ]


def test_history_projection_drops_nested_unknown_and_secret_fields() -> None:
    raw = {
        "run_id": "run-1",
        "tool_id": "media_health",
        "status": "failed",
        "parameters": {"cookie": "secret"},
        "progress_details": {
            "phase": "probe",
            "headers": {"Authorization": "secret"},
        },
        "result": {
            "status": "failed",
            "message": "safe",
            "data": {"token": "secret"},
            "output_paths": ["D:/private/video.mp4"],
        },
    }

    assert project_history_record(raw) == {
        "run_id": "run-1",
        "tool_id": "media_health",
        "status": "failed",
        "result": {
            "status": "failed",
            "message": "safe",
        },
    }


def test_runner_denies_missing_permission_before_plugin_validation_or_run(
    tmp_path: Path,
) -> None:
    tool = CountingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
    )
    profile = _profile(tmp_path, permissions=("read_file",))

    validation = service.validate(
        "counting",
        {"mode": "write"},
        execution_profile=profile,
    )
    run = service.run(
        "counting",
        {"mode": "write"},
        execution_profile=profile,
    )

    assert validation == {
        "status": "forbidden",
        "code": "tool_permission_denied",
        "message": "tool permissions are not granted",
        "tool_id": "counting",
    }
    assert run == validation
    assert tool.validate_calls == 0
    assert tool.run_calls == 0
    service.shutdown(wait=True)


def test_runner_rechecks_requirements_after_validation_normalizes_parameters(
    tmp_path: Path,
) -> None:
    tool = CountingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
    )
    profile = _profile(tmp_path, permissions=("read_file",))

    result = service.run(
        "counting",
        {"mode": "read", "normalize_to_write": True},
        execution_profile=profile,
    )

    assert result["status"] == "forbidden"
    assert result["code"] == "tool_permission_denied"
    assert tool.validate_calls == 1
    assert tool.run_calls == 0
    assert service.history(execution_profile=profile) == []
    service.shutdown(wait=True)


def test_runner_denies_external_provenance_before_plugin_callbacks(tmp_path: Path) -> None:
    tool = CountingTool()
    registry = _registry()
    registry._register(tool, provenance=f"external:{tmp_path.resolve()}")
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "history.json",
    )
    profile = _profile(
        tmp_path,
        permissions=("read_file", "write_file"),
        allow_external_plugins=False,
    )

    result = service.run("counting", {"mode": "read"}, execution_profile=profile)

    assert result["status"] == "forbidden"
    assert result["code"] == "external_plugins_disabled"
    assert tool.requirements_calls == 0
    assert tool.validate_calls == 0
    assert tool.run_calls == 0
    service.shutdown(wait=True)


def test_runner_validates_runs_and_persists_history(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    history_path = tmp_path / "tool-history.json"
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
        event_callback=lambda topic, payload: events.append((topic, payload)),
        max_workers=1,
    )

    profile = _profile(tmp_path)

    assert service.validate("echo", {}, execution_profile=profile)["status"] == "error"
    started = service.run("echo", {"value": "hello"}, execution_profile=profile)
    assert started["status"] == "queued"
    assert service.wait_for_idle(timeout=2.0)

    rows = service.history(execution_profile=profile, limit=10)
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["result"] == {
        "status": "succeeded",
        "message": "done",
        "warnings": [],
    }
    assert any(topic == "tools.progress" for topic, _ in events)
    assert all(payload == {} for topic, payload in events if topic.startswith("tools."))

    service.shutdown(wait=True)
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["tool_id"] == "echo"
    assert persisted[0]["status"] == "succeeded"
    assert "hello" not in history_path.read_text(encoding="utf-8")


def test_runner_private_result_lookup_is_owner_scoped_and_never_public(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "private-artifact.txt"
    output_path.write_text("artifact", encoding="utf-8")
    history_path = tmp_path / "tool-history.json"
    owner = _profile(tmp_path, owner_id="gui:owner", host_surface="desktop_gui")
    other_owner = _profile(tmp_path, owner_id="gui:other", host_surface="desktop_gui")
    other_host = _profile(tmp_path, owner_id="gui:owner", host_surface="sdk")
    events: list[tuple[str, dict]] = []
    service = ToolRunnerService(
        registry=_registry(OutputTool()),
        history_path=history_path,
        max_workers=1,
        event_callback=lambda topic, payload: events.append((topic, payload)),
    )

    queued = service.run(
        "output",
        {"path": str(output_path), "secret": "request-sentinel"},
        execution_profile=owner,
    )
    terminal = service.wait_for_run(
        queued["run_id"],
        execution_profile=owner,
        timeout=2.0,
    )

    private = service.lookup_private_result(
        queued["run_id"],
        execution_profile=owner,
    )
    assert terminal["status"] == "succeeded"
    assert private is not None
    assert private.run_id == queued["run_id"]
    assert private.tool_id == "output"
    assert private.output_paths == (output_path,)
    assert private.structured_data["artifacts"]["count"] == 1
    assert private.private_data["candidates"][0]["private_url"] == (
        "https://example.com/watch?token=private-result-sentinel"
    )
    private_again = service.lookup_private_result(
        queued["run_id"],
        execution_profile=owner,
    )
    assert private_again is not None
    assert private_again.structured_data is not private.structured_data
    assert private_again.private_data is not private.private_data
    with pytest.raises(TypeError):
        private.structured_data["new"] = "mutation"
    with pytest.raises(TypeError):
        private.structured_data["artifacts"]["count"] = 2
    with pytest.raises(TypeError):
        private.private_data["new"] = "mutation"
    with pytest.raises(TypeError):
        private.private_data["candidates"][0]["private_url"] = "mutation"
    assert "private-result-sentinel" not in repr(private)
    try:
        private.run_id = "mutated"
    except AttributeError:
        pass
    else:
        raise AssertionError("private result handles must be immutable")
    assert service.lookup_private_result(
        queued["run_id"],
        execution_profile=other_owner,
    ) is None
    assert service.lookup_private_result(
        queued["run_id"],
        execution_profile=other_host,
    ) is None
    assert service.lookup_private_result(
        "unknown-run",
        execution_profile=owner,
    ) is None

    candidate_ids = ("a" * 64, "b" * 64)
    assert service._claim_private_candidates(
        queued["run_id"],
        candidate_ids,
        execution_profile=owner,
    )
    assert not service._claim_private_candidates(
        queued["run_id"],
        (candidate_ids[0],),
        execution_profile=owner,
    )
    assert not service._release_private_candidates(
        queued["run_id"],
        candidate_ids,
        execution_profile=other_owner,
    )
    assert service._release_private_candidates(
        queued["run_id"],
        candidate_ids,
        execution_profile=owner,
    )
    assert service._claim_private_candidates(
        queued["run_id"],
        candidate_ids,
        execution_profile=owner,
    )

    public_run = service.get_run(queued["run_id"], execution_profile=owner)
    public_history = service.history(execution_profile=owner)
    public_text = json.dumps(
        {"run": public_run, "history": public_history},
        ensure_ascii=False,
    )
    internal_text = json.dumps(
        service._records[queued["run_id"]].to_dict(),
        ensure_ascii=False,
    )
    assert str(output_path) not in public_text
    assert "request-sentinel" not in public_text
    assert "private-result-sentinel" not in public_text
    assert "private-result-sentinel" not in internal_text
    assert all(payload == {} for _topic, payload in events)

    assert service.shutdown(wait=True)
    persisted_text = history_path.read_text(encoding="utf-8")
    assert str(output_path) not in persisted_text
    assert "request-sentinel" not in persisted_text
    assert "private-result-sentinel" not in persisted_text

    reloaded = ToolRunnerService(
        registry=_registry(OutputTool()),
        history_path=history_path,
        max_workers=1,
    )
    assert reloaded.lookup_private_result(
        queued["run_id"],
        execution_profile=owner,
    ) is None
    assert reloaded.shutdown(wait=True)


def test_runner_private_structured_data_is_unavailable_before_terminal(
    tmp_path: Path,
) -> None:
    tool = PrivateBlockingTool()
    profile = _profile(tmp_path, owner_id="gui:terminal", host_surface="desktop_gui")
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "private-terminal-history.json",
        max_workers=1,
    )
    queued = service.run("private-blocking", {}, execution_profile=profile)
    assert tool.started.wait(1.0)
    try:
        assert service.lookup_private_result(
            queued["run_id"], execution_profile=profile
        ) is None
    finally:
        tool.release.set()
    terminal = service.wait_for_run(
        queued["run_id"], execution_profile=profile, timeout=2.0
    )
    private = service.lookup_private_result(
        queued["run_id"], execution_profile=profile
    )
    assert terminal["status"] == "succeeded"
    assert private is not None
    assert private.structured_data["candidate_id"] == "terminal-structured"
    assert private.private_data["candidate_id"] == "terminal-private"
    assert service.shutdown(wait=True)


def test_runner_private_result_is_unavailable_for_failed_terminal_run(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path, owner_id="gui:failed", host_surface="desktop_gui")
    service = ToolRunnerService(
        registry=_registry(FailedPrivateTool()),
        history_path=tmp_path / "failed-private-history.json",
        max_workers=1,
    )

    queued = service.run("failed-private", {}, execution_profile=profile)
    terminal = service.wait_for_run(
        queued["run_id"], execution_profile=profile, timeout=2.0
    )

    assert terminal["status"] == "failed"
    assert (
        service.lookup_private_result(
            queued["run_id"], execution_profile=profile
        )
        is None
    )
    assert service.shutdown(wait=True)


def test_runner_rejects_non_exact_execution_profiles_before_owner_state_access(
    tmp_path: Path,
) -> None:
    class IdentityString(str):
        pass

    class ForgedExecutionProfile:
        host_surface = "desktop_gui"
        owner_id = "gui:victim"

    output_path = tmp_path / "private-artifact.txt"
    output_path.write_text("artifact", encoding="utf-8")
    owner = _profile(tmp_path, owner_id="gui:victim", host_surface="desktop_gui")
    mutated_host = _profile(
        tmp_path,
        owner_id="gui:victim",
        host_surface="desktop_gui",
    )
    object.__setattr__(mutated_host, "host_surface", IdentityString("desktop_gui"))
    mutated_owner = _profile(
        tmp_path,
        owner_id="gui:victim",
        host_surface="desktop_gui",
    )
    object.__setattr__(mutated_owner, "owner_id", IdentityString("gui:victim"))
    service = ToolRunnerService(
        registry=_registry(OutputTool()),
        history_path=tmp_path / "tool-history.json",
        max_workers=1,
    )

    queued = service.run(
        "output",
        {"path": str(output_path)},
        execution_profile=owner,
    )
    terminal = service.wait_for_run(
        queued["run_id"],
        execution_profile=owner,
        timeout=2.0,
    )

    assert terminal["status"] == "succeeded"
    for invalid_profile in (
        ForgedExecutionProfile(),
        mutated_host,
        mutated_owner,
    ):
        assert service.history(execution_profile=invalid_profile) == []
        assert (
            service.get_run(
                queued["run_id"],
                execution_profile=invalid_profile,
            )
            is None
        )
        assert (
            service.lookup_private_result(
                queued["run_id"],
                execution_profile=invalid_profile,
            )
            is None
        )

    assert service.lookup_private_result(
        queued["run_id"],
        execution_profile=owner,
    ) is not None
    assert service.shutdown(wait=True)


def test_runner_cancels_active_tool(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )

    started = service.run("blocking", {}, execution_profile=_profile(tmp_path))
    assert tool.started.wait(1.0)
    profile = _profile(tmp_path)
    cancelled = service.cancel(started["run_id"], execution_profile=profile)
    assert cancelled["status"] in {"cancelling", "cancelled"}
    assert service.wait_for_idle(timeout=2.0)
    assert service.history(execution_profile=profile, limit=1)[0]["status"] == "cancelled"

    service.shutdown(wait=True)


def test_runner_public_list_and_describe_match_sdk_contract(tmp_path: Path) -> None:
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
    )

    assert service.list()[0]["id"] == "echo"
    assert service.describe("echo")["id"] == "echo"
    assert service.describe("missing")["status"] == "error"

    service.shutdown(wait=True)


def test_runner_shutdown_cancels_cooperative_tool_and_flushes_history(tmp_path: Path) -> None:
    tool = BlockingTool()
    history_path = tmp_path / "history.json"
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
    )

    service.run("blocking", {}, execution_profile=_profile(tmp_path))
    assert tool.started.wait(1.0)

    assert service.shutdown(wait=True, timeout=1.0) is True
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["status"] == "cancelled"


def test_runner_shutdown_timeout_is_bounded_and_persists_cancelling_state(tmp_path: Path) -> None:
    tool = StubbornTool()
    history_path = tmp_path / "history.json"
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
    )

    service.run("stubborn", {}, execution_profile=_profile(tmp_path))
    assert tool.started.wait(1.0)
    started_at = time.monotonic()
    try:
        assert service.shutdown(wait=True, timeout=0.01) is False
        assert time.monotonic() - started_at < 0.5
        persisted = json.loads(history_path.read_text(encoding="utf-8"))
        assert persisted[0]["status"] == "cancelling"
    finally:
        tool.release.set()
        assert service.wait_for_idle(timeout=1.0)
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["status"] == "cancelled"


def test_runner_shutdown_timeout_bounds_slow_history_write(tmp_path: Path) -> None:
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
    )
    profile = _profile(tmp_path)
    row = service.run("echo", {"value": "done"}, execution_profile=profile)
    assert service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )["status"] == "succeeded"
    original_persist_now = service._persist_history_now
    persist_entered = threading.Event()
    release_persist = threading.Event()

    def slow_persist_now(*, timeout=None):
        persist_entered.set()
        release_persist.wait(1.0)
        return original_persist_now(timeout=timeout)

    service._persist_history_now = slow_persist_now
    started_at = time.monotonic()
    try:
        assert service.shutdown(wait=True, timeout=0.01) is False
        assert persist_entered.wait(0.5)
        assert time.monotonic() - started_at < 0.5
        persist_guard = service._shutdown_persist_thread
        assert persist_guard is not None
        assert persist_guard.is_alive()
        assert persist_guard.daemon is False
    finally:
        release_persist.set()
    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_admission_is_bounded_per_owner_and_globally(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
        max_pending=2,
        max_pending_per_owner=1,
    )
    gui = _profile(tmp_path, owner_id="gui:1", host_surface="desktop_gui")
    sdk = _profile(tmp_path, owner_id="sdk:1", host_surface="sdk")
    cli = _profile(tmp_path, owner_id="cli:1", host_surface="cli")

    first = service.run("blocking", {}, execution_profile=gui)
    assert first["status"] == "queued"
    assert tool.started.wait(1.0)
    rejected_owner = service.run("blocking", {}, execution_profile=gui)
    assert rejected_owner == {
        "status": "busy",
        "code": "tool_capacity_reached",
        "message": "tool runner capacity reached",
    }
    assert service.run("blocking", {}, execution_profile=sdk)["status"] == "queued"
    rejected_global = service.run("blocking", {}, execution_profile=cli)
    assert rejected_global == {
        "status": "busy",
        "code": "tool_capacity_reached",
        "message": "tool runner capacity reached",
    }
    assert "run_id" not in rejected_owner
    assert "run_id" not in rejected_global
    assert len(service.history(execution_profile=gui)) == 1
    assert len(service.history(execution_profile=sdk)) == 1
    assert service.history(execution_profile=cli) == []

    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_owner_cannot_read_cancel_or_clear_another_owner_run(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )
    owner = _profile(tmp_path, owner_id="gui:1", host_surface="desktop_gui")
    other = _profile(tmp_path, owner_id="gui:2", host_surface="desktop_gui")

    row = service.run("blocking", {}, execution_profile=owner)
    assert tool.started.wait(1.0)

    assert service.get_run(row["run_id"], execution_profile=other) is None
    assert service.history(execution_profile=other) == []
    assert service.cancel(row["run_id"], execution_profile=other) == {
        "status": "forbidden",
        "code": "tool_owner_mismatch",
        "message": "tool run belongs to another owner",
        "run_id": row["run_id"],
    }
    assert service.clear_history(execution_profile=other)["removed"] == 0
    assert service.get_run(row["run_id"], execution_profile=owner) is not None

    assert service.cancel(row["run_id"], execution_profile=owner)["status"] in {
        "cancelling",
        "cancelled",
    }
    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_same_owner_id_is_isolated_between_host_surfaces(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )
    gui = _profile(tmp_path, owner_id="session:shared", host_surface="desktop_gui")
    web = public_web_profile(
        owner_id="session:shared",
        approved_roots=(tmp_path,),
    )

    row = service.run("blocking", {}, execution_profile=gui)
    try:
        assert tool.started.wait(1.0)
        assert service.get_run(row["run_id"], execution_profile=web) is None
        assert service.history(execution_profile=web) == []
        assert service.cancel(row["run_id"], execution_profile=web) == {
            "status": "forbidden",
            "code": "tool_owner_mismatch",
            "message": "tool run belongs to another owner",
            "run_id": row["run_id"],
        }
        assert service.clear_history(execution_profile=web) == {
            "status": "ok",
            "removed": 0,
        }
        assert service.get_run(row["run_id"], execution_profile=gui) is not None
    finally:
        service.cancel(row["run_id"], execution_profile=gui)
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_reload_denies_untrusted_profiles_before_registry_callback(
    tmp_path: Path,
) -> None:
    registry = _registry()
    reload_calls: list[bool] = []

    def reload_external(*, force: bool = False) -> ToolReloadResult:
        reload_calls.append(force)
        return ToolReloadResult(added=("new_tool",))

    registry.reload_external = reload_external  # type: ignore[method-assign]
    events: list[tuple[str, dict]] = []
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "history.json",
        event_callback=lambda topic, payload: events.append((topic, payload)),
    )

    public = public_web_profile(owner_id="web:session-1", approved_roots=())
    external_disabled = _profile(
        tmp_path,
        owner_id="gui:reload",
        host_surface="desktop_gui",
        allow_external_plugins=False,
    )
    invalid_identity = _invalid_profile(tmp_path, field="owner_id")

    try:
        assert service.reload(force=True, execution_profile=public) == {
            "status": "forbidden",
            "code": "tool_run_disabled",
            "message": "tool execution is disabled for this host",
        }
        assert service.reload(force=True, execution_profile=external_disabled) == {
            "status": "forbidden",
            "code": "external_plugins_disabled",
            "message": "external tools are disabled for this host",
        }
        assert service.reload(force=True, execution_profile=invalid_identity) == {
            "status": "forbidden",
            "code": "tool_profile_identity_required",
            "message": "tool execution profile identity is required",
        }

        assert reload_calls == []
        assert events == []
    finally:
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_reload_forwards_original_profile_authority_only_after_admission(
    tmp_path: Path,
) -> None:
    registry = _registry()
    reload_calls: list[bool] = []

    def reload_external(*, force: bool = False) -> ToolReloadResult:
        reload_calls.append(force)
        return ToolReloadResult(updated=("tool_a",))

    registry.reload_external = reload_external  # type: ignore[method-assign]
    service = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "history.json",
    )
    profile = _profile(
        tmp_path,
        owner_id="test:reload",
        allow_external_plugins=True,
    )

    try:
        assert service.reload(force=True, execution_profile=profile) == {
            "added": [],
            "updated": ["tool_a"],
            "removed": [],
            "errors": [],
        }
        assert reload_calls == [True]
    finally:
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_per_owner_admission_counts_owner_id_across_host_surfaces(
    tmp_path: Path,
) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
        max_pending=4,
        max_pending_per_owner=1,
    )
    gui = _profile(tmp_path, owner_id="session:shared", host_surface="desktop_gui")
    sdk = _profile(tmp_path, owner_id="session:shared", host_surface="sdk")
    row = service.run("blocking", {}, execution_profile=gui)
    try:
        assert tool.started.wait(1.0)
        assert service.run("blocking", {}, execution_profile=sdk) == {
            "status": "busy",
            "code": "tool_capacity_reached",
            "message": "tool runner capacity reached",
        }
        assert service.get_run(row["run_id"], execution_profile=sdk) is None
        assert service.history(execution_profile=sdk) == []
    finally:
        service.cancel(row["run_id"], execution_profile=gui)
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_loaded_history_is_newest_first_at_api_boundary(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps([_terminal_row("old", 1.0), _terminal_row("new", 2.0)]),
        encoding="utf-8",
    )
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
    )
    profile = _profile(
        tmp_path,
        owner_id="gui:history",
        host_surface="desktop_gui",
    )

    assert [
        row["run_id"] for row in service.history(execution_profile=profile)
    ] == ["new", "old"]

    service.shutdown(wait=True)


def test_runner_clear_history_preserves_other_owner_terminal_rows(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [
                _terminal_row("gui-row", 1.0, owner_id="gui:1"),
                _terminal_row(
                    "sdk-row",
                    2.0,
                    owner_id="sdk:1",
                    host_surface="sdk",
                ),
            ]
        ),
        encoding="utf-8",
    )
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
    )
    gui = _profile(tmp_path, owner_id="gui:1", host_surface="desktop_gui")
    sdk = _profile(tmp_path, owner_id="sdk:1", host_surface="sdk")

    assert service.clear_history(execution_profile=gui) == {"status": "ok", "removed": 1}
    assert service.history(execution_profile=gui) == []
    assert [row["run_id"] for row in service.history(execution_profile=sdk)] == ["sdk-row"]

    service.shutdown(wait=True)


def test_runner_trims_oldest_terminal_rows_behind_an_active_run(tmp_path: Path) -> None:
    blocking = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(blocking, EchoTool()),
        history_path=tmp_path / "history.json",
        max_workers=2,
        max_pending=20,
        max_pending_per_owner=20,
        history_limit=10,
    )
    profile = _profile(tmp_path, owner_id="gui:trim", host_surface="desktop_gui")
    active = service.run("blocking", {}, execution_profile=profile)
    try:
        assert blocking.started.wait(1.0)
        terminal = None
        for index in range(12):
            terminal = service.run(
                "echo",
                {"value": str(index)},
                execution_profile=profile,
            )
        assert terminal is not None
        assert service.wait_for_run(
            terminal["run_id"],
            execution_profile=profile,
            timeout=2.0,
        )["status"] == "succeeded"

        retained = service.history(execution_profile=profile, limit=20)
        assert retained[-1]["run_id"] == active["run_id"]
        assert len([row for row in retained if row["status"] == "succeeded"]) == 9

        assert service.clear_history(execution_profile=profile) == {
            "status": "ok",
            "removed": 9,
        }
        assert service.get_run(active["run_id"], execution_profile=profile) is not None
    finally:
        service.cancel(active["run_id"], execution_profile=profile)
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_wait_for_run_times_out_without_cross_owner_visibility(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )
    owner = _profile(tmp_path, owner_id="gui:wait", host_surface="desktop_gui")
    other = _profile(tmp_path, owner_id="sdk:wait", host_surface="sdk")
    row = service.run("blocking", {}, execution_profile=owner)
    assert tool.started.wait(1.0)

    assert service.wait_for_run(
        row["run_id"],
        execution_profile=owner,
        timeout=0.01,
    ) == {"status": "timeout", "run_id": row["run_id"]}
    assert service.wait_for_run(
        row["run_id"],
        execution_profile=other,
        timeout=0.01,
    ) == {
        "status": "forbidden",
        "code": "tool_owner_mismatch",
        "message": "tool run belongs to another owner",
        "run_id": row["run_id"],
    }

    assert service.cancel(row["run_id"], execution_profile=owner)["status"] in {
        "cancelling",
        "cancelled",
    }
    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_wait_and_shutdown_timeout_include_history_barrier(tmp_path: Path) -> None:
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
    )
    profile = _profile(tmp_path)
    service._history_loaded.wait(1.0)
    service._history_loaded.clear()

    started_at = time.monotonic()
    assert service.wait_for_run(
        "missing",
        execution_profile=profile,
        timeout=0.01,
    ) == {"status": "timeout", "run_id": "missing"}
    assert time.monotonic() - started_at < 0.2

    started_at = time.monotonic()
    assert service.shutdown(wait=True, timeout=0.01) is False
    assert time.monotonic() - started_at < 0.2
    service._history_loaded.set()
    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_shutdown_wait_false_does_not_cancel_a_queued_history_load(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_executor = tool_runner_module.ThreadPoolExecutor
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    def executor_factory(*args, **kwargs):
        executor = real_executor(*args, **kwargs)
        if kwargs.get("thread_name_prefix") == "tool-history":
            executor.submit(
                lambda: (blocker_started.set(), release_blocker.wait())
            )
        return executor

    monkeypatch.setattr(tool_runner_module, "ThreadPoolExecutor", executor_factory)
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [
                _terminal_row(
                    "loaded",
                    1.0,
                    owner_id="unit:runner",
                    host_surface="test",
                )
            ]
        ),
        encoding="utf-8",
    )
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
    )
    assert blocker_started.wait(1.0)
    shutdown_returned = threading.Event()
    first_result: list[bool] = []

    def call_shutdown() -> None:
        first_result.append(service.shutdown(wait=False))
        shutdown_returned.set()

    caller = threading.Thread(target=call_shutdown, name="shutdown-wait-false-probe", daemon=True)
    caller.start()
    try:
        returned_without_history = shutdown_returned.wait(0.2)
    finally:
        release_blocker.set()
        caller.join(1.0)

    assert returned_without_history is True
    assert first_result == [False]
    assert service._history_loaded.wait(1.0)
    assert service.shutdown(wait=True, timeout=1.0) is True
    assert [
        row["run_id"]
        for row in service.history(execution_profile=_profile(tmp_path))
    ] == ["loaded"]
    assert _active_tool_threads() == []


def test_runner_cancel_terminal_run_does_not_emit_cancelling_event(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
        event_callback=lambda topic, payload: events.append((topic, payload)),
    )
    profile = _profile(tmp_path)
    queued = service.run("echo", {"value": "done"}, execution_profile=profile)
    assert service.wait_for_run(
        queued["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )["status"] == "succeeded"
    events.clear()

    assert service.cancel(queued["run_id"], execution_profile=profile)["status"] == "succeeded"
    assert events == []

    service.shutdown(wait=True)


def test_runner_shutdown_marks_queued_future_cancelled_and_flushes_history(tmp_path: Path) -> None:
    tool = BlockingTool()
    history_path = tmp_path / "history.json"
    profile = _profile(tmp_path, owner_id="unit:shutdown")
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
    )
    service.run("blocking", {"slot": 1}, execution_profile=profile)
    assert tool.started.wait(1.0)
    queued = service.run("blocking", {"slot": 2}, execution_profile=profile)

    service.shutdown(wait=False)

    persisted = {
        row["run_id"]: row
        for row in json.loads(history_path.read_text(encoding="utf-8"))
    }
    assert persisted[queued["run_id"]]["status"] == "cancelled"
    assert persisted[queued["run_id"]]["finished_at"] is not None


def test_runner_load_merges_duplicate_unsorted_and_tied_rows_and_drops_blank_identity(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "history.json"
    duplicate_old = _terminal_row("duplicate", 1.0)
    duplicate_old["message"] = "old"
    duplicate_new = _terminal_row("duplicate", 4.0)
    duplicate_new["message"] = "new"
    blank_host = _terminal_row("blank-host", 5.0)
    blank_host["host_surface"] = "   "
    blank_owner = _terminal_row("blank-owner", 6.0)
    blank_owner["owner_id"] = ""
    history_path.write_text(
        json.dumps(
            [
                _terminal_row("tie-b", 3.0),
                duplicate_old,
                blank_host,
                _terminal_row("tie-a", 3.0),
                duplicate_new,
                blank_owner,
                _terminal_row("oldest", 0.0),
            ]
        ),
        encoding="utf-8",
    )
    service = ToolRunnerService(registry=_registry(EchoTool()), history_path=history_path)
    profile = _profile(tmp_path, owner_id="gui:history", host_surface="desktop_gui")

    rows = service.history(execution_profile=profile)

    assert [row["run_id"] for row in rows] == [
        "duplicate",
        "tie-b",
        "tie-a",
        "oldest",
    ]
    assert rows[0]["message"] == "new"
    service.shutdown(wait=True)


def test_record_from_dict_rejects_noncanonical_identity_fields() -> None:
    class IdentityString(str):
        pass

    invalid_identities = (
        ("host_surface", 1),
        ("host_surface", " desktop_gui "),
        ("host_surface", "unknown_surface"),
        ("host_surface", IdentityString("desktop_gui")),
        ("owner_id", 1),
        ("owner_id", " gui:history "),
        ("owner_id", IdentityString("gui:history")),
    )

    for field, value in invalid_identities:
        row = _terminal_row(f"invalid-{field}-{value!s}", 1.0)
        row[field] = value
        assert tool_runner_module._record_from_dict(row) is None, (field, value)


def test_runner_load_sorts_all_valid_rows_before_applying_history_limit(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [_terminal_row("newest", 100.0)]
            + [_terminal_row(f"old-{index}", float(index)) for index in range(1, 13)]
        ),
        encoding="utf-8",
    )
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
        history_limit=10,
    )
    profile = _profile(tmp_path, owner_id="gui:history", host_surface="desktop_gui")
    try:
        assert [
            row["run_id"] for row in service.history(execution_profile=profile)
        ] == [
            "newest",
            "old-12",
            "old-11",
            "old-10",
            "old-9",
            "old-8",
            "old-7",
            "old-6",
            "old-5",
            "old-4",
        ]
    finally:
        service.shutdown(wait=True)


def test_runner_rejects_blank_profile_identity_before_callbacks_or_state_access(
    tmp_path: Path,
) -> None:
    tool = CountingTool()
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [
                _terminal_row(
                    "existing",
                    1.0,
                    owner_id="unit:runner",
                    host_surface="test",
                )
            ]
        ),
        encoding="utf-8",
    )
    service = ToolRunnerService(registry=_registry(tool), history_path=history_path)
    invalid_host = _invalid_profile(tmp_path, field="host_surface")
    invalid_owner = _invalid_profile(tmp_path, field="owner_id")

    validation = service.validate("counting", {"mode": "read"}, execution_profile=invalid_host)
    run = service.run("counting", {"mode": "read"}, execution_profile=invalid_owner)

    assert validation["code"] == "tool_profile_identity_required"
    assert run["code"] == "tool_profile_identity_required"
    assert tool.requirements_calls == 0
    assert tool.validate_calls == 0
    assert tool.run_calls == 0
    assert service.history(execution_profile=invalid_host) == []
    assert service.get_run("existing", execution_profile=invalid_owner) is None
    assert service.cancel("existing", execution_profile=invalid_host)["code"] == (
        "tool_profile_identity_required"
    )
    assert service.wait_for_run(
        "existing",
        execution_profile=invalid_owner,
        timeout=0,
    )["code"] == "tool_profile_identity_required"
    assert service.clear_history(execution_profile=invalid_host)["code"] == (
        "tool_profile_identity_required"
    )
    assert service.history(
        execution_profile=_profile(tmp_path, owner_id="unit:runner")
    )[0]["run_id"] == "existing"
    service.shutdown(wait=True)


def test_runner_clear_history_preserves_all_active_rows_and_other_owner_terminals(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            [
                _terminal_row("gui-terminal", 1.0, owner_id="gui:1"),
                _terminal_row(
                    "sdk-terminal",
                    2.0,
                    owner_id="sdk:1",
                    host_surface="sdk",
                ),
            ]
        ),
        encoding="utf-8",
    )
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
        max_pending_per_owner=4,
    )
    gui = _profile(tmp_path, owner_id="gui:1", host_surface="desktop_gui")
    sdk = _profile(tmp_path, owner_id="sdk:1", host_surface="sdk")
    gui_active = service.run("blocking", {}, execution_profile=gui)
    assert tool.started.wait(1.0)
    sdk_active = service.run("blocking", {}, execution_profile=sdk)
    try:
        assert service.clear_history(execution_profile=gui) == {
            "status": "ok",
            "removed": 1,
        }
        assert service.get_run(gui_active["run_id"], execution_profile=gui) is not None
        assert service.get_run(sdk_active["run_id"], execution_profile=sdk) is not None
        assert [row["run_id"] for row in service.history(execution_profile=sdk)] == [
            sdk_active["run_id"],
            "sdk-terminal",
        ]
    finally:
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_wait_for_run_returns_existing_terminal_row(tmp_path: Path) -> None:
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
    )
    profile = _profile(tmp_path)
    row = service.run("echo", {"value": "ready"}, execution_profile=profile)

    terminal = service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )
    repeated = service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=0,
    )

    assert terminal["status"] == "succeeded"
    assert repeated == terminal
    service.shutdown(wait=True)


def test_runner_worker_start_cancellation_emits_and_persists_one_terminal_event(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    entered_execute = threading.Event()
    history_path = tmp_path / "history.json"
    profile = _profile(tmp_path)
    service = ToolRunnerService(
        registry=_registry(BlockingTool()),
        history_path=history_path,
        max_workers=1,
        event_callback=lambda topic, payload: events.append(topic),
    )
    original_execute = service._execute

    def execute_after_signal(*args):
        entered_execute.set()
        return original_execute(*args)

    service._execute = execute_after_signal
    with service._lock:
        row = service.run("blocking", {}, execution_profile=profile)
        assert entered_execute.wait(1.0)
        requested = service.cancel(row["run_id"], execution_profile=profile)
        assert requested["status"] == "cancelling"

    terminal = service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )
    assert terminal["status"] == "cancelled"
    assert events.count("tools.cancelled") == 1
    service.shutdown(wait=True)
    assert _persisted_by_id(history_path)[row["run_id"]]["status"] == "cancelled"


def test_runner_queued_and_repeated_cancel_transition_and_persist_only_once(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    tool = BlockingTool()
    profile = _profile(tmp_path)
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
        event_callback=lambda topic, payload: events.append(topic),
    )
    running = service.run("blocking", {"slot": 1}, execution_profile=profile)
    assert tool.started.wait(1.0)
    queued = service.run("blocking", {"slot": 2}, execution_profile=profile)
    generation_before_cancel = service._persist_generation

    first = service.cancel(queued["run_id"], execution_profile=profile)
    second = service.cancel(queued["run_id"], execution_profile=profile)

    assert first["status"] == "cancelled"
    assert second == first
    assert events.count("tools.cancelled") == 1
    assert service._persist_generation == generation_before_cancel + 1
    service.cancel(running["run_id"], execution_profile=profile)
    assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_cancel_wins_finish_race_and_terminal_cancel_is_idempotent(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    tool = ReturningTool()
    profile = _profile(tmp_path)
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
        event_callback=lambda topic, payload: events.append(topic),
    )
    row = service.run("returning", {}, execution_profile=profile)
    assert tool.started.wait(1.0)
    with service._lock:
        tool.release.set()
        assert tool.returning.wait(1.0)
        assert service.cancel(row["run_id"], execution_profile=profile)["status"] == (
            "cancelling"
        )

    terminal = service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )
    generation_at_terminal = service._persist_generation
    event_count_at_terminal = len(events)

    assert terminal["status"] == "cancelled"
    assert events.count("tools.cancelled") == 1
    assert events.count("tools.finished") == 0
    assert service.cancel(row["run_id"], execution_profile=profile) == terminal
    assert service.cancel(row["run_id"], execution_profile=profile) == terminal
    assert len(events) == event_count_at_terminal
    assert service._persist_generation == generation_at_terminal
    service.shutdown(wait=True)


def test_runner_terminal_visibility_marks_persistence_dirty_before_waiter_returns(
    tmp_path: Path,
) -> None:
    terminal_emit_entered = threading.Event()
    allow_terminal_emit = threading.Event()
    tool = ReturningTool()

    def block_terminal_event(topic: str, payload: dict) -> None:
        del payload
        if topic == "tools.finished":
            terminal_emit_entered.set()
            allow_terminal_emit.wait()

    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
        event_callback=block_terminal_event,
    )
    profile = _profile(tmp_path)
    row = service.run("returning", {}, execution_profile=profile)
    assert tool.started.wait(1.0)
    generation_before_terminal = service._persist_generation
    try:
        tool.release.set()
        assert terminal_emit_entered.wait(1.0)
        terminal = service.wait_for_run(
            row["run_id"],
            execution_profile=profile,
            timeout=0,
        )
        assert terminal["status"] == "succeeded"
        assert service._persist_generation == generation_before_terminal + 1
    finally:
        allow_terminal_emit.set()
        assert service.shutdown(wait=True, timeout=1.0) is True


def test_runner_cancel_on_succeeded_run_has_no_new_event_or_persist(tmp_path: Path) -> None:
    events: list[str] = []
    profile = _profile(tmp_path)
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=tmp_path / "history.json",
        event_callback=lambda topic, payload: events.append(topic),
    )
    row = service.run("echo", {"value": "done"}, execution_profile=profile)
    terminal = service.wait_for_run(
        row["run_id"],
        execution_profile=profile,
        timeout=1.0,
    )
    generation = service._persist_generation
    event_count = len(events)

    assert terminal["status"] == "succeeded"
    assert service.cancel(row["run_id"], execution_profile=profile) == terminal
    assert service.cancel(row["run_id"], execution_profile=profile) == terminal
    assert len(events) == event_count
    assert service._persist_generation == generation
    service.shutdown(wait=True)


def test_runner_repeated_shutdown_waits_for_late_terminal_persist_and_joins_threads(
    tmp_path: Path,
) -> None:
    tool = StubbornTool()
    history_path = tmp_path / "history.json"
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
    )
    profile = _profile(tmp_path)
    row = service.run("stubborn", {}, execution_profile=profile)
    assert tool.started.wait(1.0)
    original_persist_now = service._persist_history_now
    late_persist_entered = threading.Event()
    allow_late_persist = threading.Event()

    def controlled_persist_now(*, timeout=None):
        if threading.current_thread().name.startswith("tool-runner"):
            late_persist_entered.set()
            allow_late_persist.wait()
        return original_persist_now(timeout=timeout)

    service._persist_history_now = controlled_persist_now
    assert service.shutdown(wait=False) is False
    assert _persisted_by_id(history_path)[row["run_id"]]["status"] == "cancelling"

    tool.release.set()
    assert late_persist_entered.wait(1.0)
    zero_budget_result = service.shutdown(wait=True, timeout=0)
    allow_late_persist.set()
    final_result = service.shutdown(wait=True, timeout=1.0)

    assert zero_budget_result is False
    assert final_result is True
    assert _persisted_by_id(history_path)[row["run_id"]]["status"] == "cancelled"
    assert _active_tool_threads() == []


def test_runner_shutdown_timeout_can_be_repeated_to_flush_late_terminal_state(
    tmp_path: Path,
) -> None:
    tool = StubbornTool()
    history_path = tmp_path / "history.json"
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=history_path,
        max_workers=1,
    )
    profile = _profile(tmp_path)
    row = service.run("stubborn", {}, execution_profile=profile)
    assert tool.started.wait(1.0)

    assert service.shutdown(wait=True, timeout=0) is False
    assert _persisted_by_id(history_path)[row["run_id"]]["status"] == "cancelling"
    tool.release.set()
    assert service.shutdown(wait=True, timeout=1.0) is True

    assert _persisted_by_id(history_path)[row["run_id"]]["status"] == "cancelled"
    assert _active_tool_threads() == []
