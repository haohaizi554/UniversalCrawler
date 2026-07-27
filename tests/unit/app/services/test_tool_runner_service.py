from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from app.core.tools.contracts import ToolManifest, ToolRequirements, ToolRunResult
from app.core.tools.registry import ToolRegistry
from app.services.tool_runner_service import ToolRunnerService


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


def _registry(*tools):
    return ToolRegistry(
        tools=list(tools),
        include_builtins=False,
        include_entry_points=False,
    )


def test_runner_validates_runs_and_persists_history(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    history_path = tmp_path / "tool-history.json"
    service = ToolRunnerService(
        registry=_registry(EchoTool()),
        history_path=history_path,
        event_callback=lambda topic, payload: events.append((topic, payload)),
        max_workers=1,
    )

    assert service.validate("echo", {})["status"] == "error"
    started = service.run("echo", {"value": "hello"})
    assert started["status"] == "queued"
    assert service.wait_for_idle(timeout=2.0)

    rows = service.history(limit=10)
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["result"]["data"] == {"value": "hello"}
    assert any(topic == "tools.progress" for topic, _ in events)

    service.shutdown(wait=True)
    persisted = json.loads(history_path.read_text(encoding="utf-8"))
    assert persisted[0]["tool_id"] == "echo"
    assert persisted[0]["status"] == "succeeded"


def test_runner_cancels_active_tool(tmp_path: Path) -> None:
    tool = BlockingTool()
    service = ToolRunnerService(
        registry=_registry(tool),
        history_path=tmp_path / "history.json",
        max_workers=1,
    )

    started = service.run("blocking", {})
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

    service.run("blocking", {})
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

    service.run("stubborn", {})
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
