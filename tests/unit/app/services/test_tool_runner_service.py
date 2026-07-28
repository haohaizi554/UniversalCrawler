from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from app.core.tools.contracts import (
    ToolManifest,
    ToolRequirements,
    ToolRunResult,
    ToolValidationResult,
)
from app.core.tools.registry import ToolRegistry
from app.services.tool_history_projection import project_history_record
from app.services.tool_runner_service import ToolRunnerService
from shared.execution_profile import local_execution_profile


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
    return ToolRegistry(
        tools=list(tools),
        include_builtins=False,
        include_entry_points=False,
    )


def _profile(tmp_path: Path, *, permissions=(), allow_external_plugins: bool = False):
    return local_execution_profile(
        host_surface="test",
        owner_id="unit:runner",
        approved_roots=(tmp_path,),
        tool_permissions=permissions,
        allow_external_plugins=allow_external_plugins,
    )


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
        "result": {"status": "failed", "message": "safe"},
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
    assert service.history() == []
    service.shutdown(wait=True)


def test_runner_denies_external_provenance_before_plugin_callbacks(tmp_path: Path) -> None:
    tool = CountingTool()
    registry = _registry()
    registry._register(tool, provenance="external:test")
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

    rows = service.history(limit=10)
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["result"] == {
        "status": "succeeded",
        "message": "done",
        "warnings": [],
    }
    assert any(topic == "tools.progress" for topic, _ in events)

    service.shutdown(wait=True)
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["tool_id"] == "echo"
    assert persisted[0]["status"] == "succeeded"
    assert "hello" not in history_path.read_text(encoding="utf-8")


def test_runner_cancels_active_tool(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )

    started = service.run("blocking", {}, execution_profile=_profile(tmp_path))
    assert tool.started.wait(1.0)
    cancelled = service.cancel(started["run_id"])
    assert cancelled["status"] in {"cancelling", "cancelled"}
    assert service.wait_for_idle(timeout=2.0)
    assert service.history(limit=1)[0]["status"] == "cancelled"

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
