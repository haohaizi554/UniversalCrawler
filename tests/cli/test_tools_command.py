"""CLI contract for ``ucrawl tools``."""

from __future__ import annotations

import json
from typing import Any

import pytest


class RecordingToolsAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses = {
            name: {"operation": name, "status": "ok"}
            for name in ("list", "describe", "validate", "run", "cancel", "history")
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

    def history(self, **filters: Any) -> dict[str, str]:
        return self._record("history", **filters)


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
            ["tools", "run", "media.probe", "--params", '{"path":"demo.mp4"}'],
            ("run", ("media.probe", {"path": "demo.mp4"}), {}),
        ),
        (["tools", "cancel", "run-42"], ("cancel", ("run-42",), {})),
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
    monkeypatch.setattr(tools_command, "ToolsAPI", lambda: api)

    assert main(argv) == 0
    assert api.calls == [expected_call]
    assert json.loads(capsys.readouterr().out) == {
        "operation": expected_call[0],
        "status": "ok",
    }


def test_tools_run_maps_service_status_to_process_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    api.responses["run"] = {"status": "cancelled", "run_id": "run-42"}
    monkeypatch.setattr(tools_command, "ToolsAPI", lambda: api)

    assert main(["tools", "run", "media.probe"]) == 130
    assert json.loads(capsys.readouterr().out)["run_id"] == "run-42"


def test_tools_rejects_non_object_params_before_calling_sdk(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli.commands import tools as tools_command
    from cli.main import main

    api = RecordingToolsAPI()
    monkeypatch.setattr(tools_command, "ToolsAPI", lambda: api)

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
        def list(self) -> None:
            raise ToolRunnerUnavailableError("service contract is unavailable")

    monkeypatch.setattr(tools_command, "ToolsAPI", UnavailableToolsAPI)

    assert main(["tools", "list"]) == 1
    assert "service contract is unavailable" in capsys.readouterr().err
