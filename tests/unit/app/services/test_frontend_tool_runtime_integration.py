from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import Mock

import pytest

from app.config import ConfigManager
from app.core.tools.contracts import (
    ToolContext,
    ToolManifest,
    ToolRequirements,
    ToolRunResult,
    ToolValidationResult,
)
from app.core.tools.registry import ToolRegistry
from app.services.frontend_state_service import FrontendStateService
from app.services.tool_history_projection import project_history_record
from app.services.tool_runner_service import PrivateToolResult, ToolRunnerService
from app.ui.main_window import MainWindow
from shared.execution_profile import (
    ExecutionProfile,
    local_execution_profile,
    public_web_profile,
)


class _NoopFailedRecordStore:
    def set_refresh_callback(self, _callback) -> None:
        return None

    def request_refresh(self, **_kwargs) -> None:
        return None

    def shutdown(self) -> None:
        return None


class _FakeToolRunner:
    def __init__(self, *, records: list[dict[str, Any]] | None = None) -> None:
        self.manifests = [
            {
                "id": "file_verify",
                "title": "文件校验",
                "summary": "校验文件完整性",
                "cancellable": True,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "file",
                            "title": "源文件",
                        }
                    },
                    "required": ["source"],
                },
            }
        ]
        self.records = deepcopy(records or [])
        self.calls: list[tuple[Any, ...]] = []

    def list(self) -> list[dict[str, Any]]:
        self.calls.append(("list",))
        return deepcopy(self.manifests)

    def describe(self, tool_id: str) -> dict[str, Any]:
        self.calls.append(("describe", tool_id))
        if tool_id != "file_verify":
            raise ValueError(f"unknown tool: {tool_id}")
        return deepcopy(self.manifests[0])

    def history(
        self,
        *,
        execution_profile: ExecutionProfile,
        tool_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.calls.append(("history", execution_profile, tool_id, limit))
        records = self.records
        if tool_id:
            records = [record for record in records if record.get("tool_id") == tool_id]
        return [project_history_record(record) for record in records[:limit]]

    def validate(
        self,
        tool_id: str,
        parameters: dict[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        self.calls.append(("validate", tool_id, deepcopy(parameters), execution_profile))
        return {
            "status": "ok",
            "valid": True,
            "errors": [],
            "tool_id": tool_id,
        }

    def run(
        self,
        tool_id: str,
        parameters: dict[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        self.calls.append(("run", tool_id, deepcopy(parameters), execution_profile))
        record = {
            "run_id": "run-started",
            "tool_id": tool_id,
            "status": "queued",
            "message": "已加入队列",
            "parameters": deepcopy(parameters),
            "progress": 0,
        }
        self.records.insert(0, record)
        return project_history_record(record)

    def cancel(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        self.calls.append(("cancel", execution_profile, run_id))
        for record in self.records:
            if record.get("run_id") == run_id:
                record["status"] = "cancelling"
                record["message"] = "正在取消"
                return project_history_record(record)
        return {"status": "error", "message": "run not found", "run_id": run_id}

    def get_run(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any] | None:
        self.calls.append(("get_run", execution_profile, run_id))
        for record in self.records:
            if record.get("run_id") == run_id:
                return deepcopy(record)
        return None

    def lookup_private_result(
        self,
        run_id: str,
        *,
        execution_profile: ExecutionProfile,
    ) -> PrivateToolResult | None:
        self.calls.append(("lookup_private_result", execution_profile, run_id))
        for record in self.records:
            if record.get("run_id") != run_id:
                continue
            result = record.get("result")
            if not isinstance(result, dict):
                return None
            output_paths = tuple(
                Path(str(path))
                for path in result.get("output_paths", ())
                if str(path).strip()
            )
            return PrivateToolResult(
                run_id=run_id,
                tool_id=str(record.get("tool_id") or ""),
                output_paths=output_paths,
            )
        return None

    def clear_history(
        self,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        self.calls.append(("clear_history", execution_profile))
        cleared = len(self.records)
        self.records.clear()
        return {"cleared": cleared}

    def reload(
        self,
        *,
        force: bool = False,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        self.calls.append(("reload", execution_profile, force))
        return {"reloaded": True, "force": force, "count": len(self.manifests)}


def _record(
    *,
    run_id: str = "run-finished",
    status: str = "succeeded",
    source: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "message": "校验完成",
        "data": {"checked": 1},
        "output_paths": [str(output_path)] if output_path is not None else [],
    }
    return {
        "run_id": run_id,
        "tool_id": "file_verify",
        "status": status,
        "message": "校验完成" if status == "succeeded" else "运行中",
        "parameters": {"source": str(source)} if source is not None else {},
        "progress": 100 if status == "succeeded" else 25,
        "finished_at": 1_700_000_000 if status == "succeeded" else None,
        "result": result if status == "succeeded" else None,
    }


@contextmanager
def _service(
    tmp_path: Path,
    runner: _FakeToolRunner,
    *,
    opener: Mock | None = None,
    execution_profile: ExecutionProfile | None = None,
    execution_profile_provider: Callable[[], ExecutionProfile] | None = None,
) -> Iterator[FrontendStateService]:
    profile = execution_profile or (
        None if execution_profile_provider is not None else _desktop_profile(tmp_path)
    )
    service = FrontendStateService(
        config_manager=ConfigManager(str(tmp_path / "config.json")),
        failed_record_store=_NoopFailedRecordStore(),
        tool_runner_service=runner,
        execution_profile=profile,
        execution_profile_provider=execution_profile_provider,
    )
    if opener is not None:
        service._open_file_path = opener
    try:
        yield service
    finally:
        service.destroy()


def _desktop_profile(tmp_path: Path, *, owner_id: str = "desktop-test") -> ExecutionProfile:
    return local_execution_profile(
        host_surface="test",
        owner_id=owner_id,
        approved_roots=(tmp_path,),
        tool_permissions=("read_file", "write_file", "destructive", "process", "network"),
        allow_external_plugins=False,
    )


def test_dynamic_toolbox_snapshot_comes_from_injected_runner(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record()])
    profile = _desktop_profile(tmp_path)

    with _service(tmp_path, runner, execution_profile=profile) as service:
        snapshot = service.get_snapshot(
            sections=frozenset(
                {
                    "toolbox_items",
                    "toolbox_recent_items",
                    "toolbox_display_projection",
                }
            )
        )

    assert [item["id"] for item in snapshot["toolbox_items"]] == ["file_verify"]
    assert snapshot["toolbox_items"][0]["parameter_fields"] == [
        {
            "id": "source",
            "name": "source",
            "type": "file",
            "title": "源文件",
            "label": "源文件",
            "required": True,
        }
    ]
    assert snapshot["toolbox_recent_items"][0]["run_id"] == "run-finished"
    projection = snapshot["toolbox_display_projection"]
    assert projection["tool_id"] == "file_verify"
    assert projection["state"] == "success"
    assert "data" not in projection["result"]
    assert "output_paths" not in projection["result"]
    assert "result_path" not in projection["result"]
    assert "has_output" not in projection["result"]
    assert projection["actions"]["tool_open_result"] is False
    assert runner.calls.count(("list",)) == 1
    assert runner.calls.count(("history", profile, None, 20)) == 1


def test_tool_validate_forwards_parameters_and_exact_host_owned_profile(tmp_path: Path) -> None:
    source = tmp_path / "media.mp4"
    source.write_bytes(b"media")
    runner = _FakeToolRunner()
    profile = _desktop_profile(tmp_path)

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(
            "tool_validate",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(source)},
                "_approved_roots": [str(tmp_path / "attacker")],
            },
        )

    assert response["status"] == "ok"
    assert response["data"]["validation"]["valid"] is True
    assert response["data"]["toolbox_display_projection"]["validation"]["state"] == "valid"
    assert (
        "validate",
        "file_verify",
        {"source": str(source)},
        profile,
    ) in runner.calls


def test_tool_start_returns_runner_run_and_exact_host_owned_profile(tmp_path: Path) -> None:
    source = tmp_path / "media.mp4"
    source.write_bytes(b"media")
    runner = _FakeToolRunner()
    profile = _desktop_profile(tmp_path)

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(
            "tool_start",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(source)},
                "_approved_roots": [str(tmp_path / "attacker")],
            },
        )

    assert response["status"] == "ok"
    assert response["data"]["run_id"] == "run-started"
    projection = response["data"]["toolbox_display_projection"]
    assert projection["state"] == "starting"
    assert projection["actions"]["tool_cancel"] is True
    assert (
        "run",
        "file_verify",
        {"source": str(source)},
        profile,
    ) in runner.calls


def test_tool_start_surfaces_runner_denials_and_capacity_as_errors(
    tmp_path: Path,
) -> None:
    profile = _desktop_profile(tmp_path)
    for status, code in (
        ("forbidden", "tool_run_disabled"),
        ("busy", "tool_capacity_reached"),
    ):
        runner = _FakeToolRunner()
        runner.run = Mock(
            return_value={
                "status": status,
                "code": code,
                "message": f"runner returned {status}",
            }
        )
        with _service(tmp_path, runner, execution_profile=profile) as service:
            response = service.handle_action(
                "tool_start",
                {"tool_id": "file_verify", "parameters": {}},
            )

        assert response["status"] == "error"
        assert response["data"]["status"] == status
        assert response["data"]["code"] == code


def test_tool_cancel_surfaces_owner_denial_as_error(tmp_path: Path) -> None:
    runner = _FakeToolRunner()
    runner.cancel = Mock(
        return_value={
            "status": "forbidden",
            "code": "tool_owner_mismatch",
            "message": "tool run belongs to another owner",
            "run_id": "run-other",
        }
    )

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_cancel",
            {"tool_id": "file_verify", "run_id": "run-other"},
        )

    assert response["status"] == "error"
    assert response["data"]["code"] == "tool_owner_mismatch"


def test_tool_cancel_projects_cancelling_state(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record(run_id="run-active", status="running")])
    profile = _desktop_profile(tmp_path)

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(
            "tool_cancel",
            {"tool_id": "file_verify", "run_id": "run-active"},
        )

    assert response["status"] == "ok"
    assert ("cancel", profile, "run-active") in runner.calls
    projection = response["data"]["toolbox_display_projection"]
    assert projection["state"] == "cancelling"
    assert projection["actions"]["tool_cancel"] is False


def test_tool_clear_history_and_reload_refresh_projection(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record()])
    profile = _desktop_profile(tmp_path)

    with _service(tmp_path, runner, execution_profile=profile) as service:
        cleared = service.handle_action("tool_clear_history", {"tool_id": "file_verify"})
        reloaded = service.handle_action("tool_reload", {"tool_id": "file_verify", "force": True})

    assert cleared["status"] == "ok"
    assert cleared["data"]["cleared"] == 1
    assert cleared["data"]["toolbox_display_projection"]["history"] == []
    assert reloaded["status"] == "ok"
    assert reloaded["data"]["reloaded"] is True
    assert reloaded["data"]["toolbox_display_projection"]["tool_id"] == "file_verify"
    assert ("clear_history", profile) in runner.calls
    assert ("reload", profile, True) in runner.calls


def test_tool_clear_history_does_not_wrap_runner_denial_as_success(tmp_path: Path) -> None:
    runner = _FakeToolRunner()
    runner.clear_history = Mock(
        return_value={
            "status": "forbidden",
            "code": "invalid_execution_profile",
            "message": "execution profile is invalid",
        }
    )

    with _service(tmp_path, runner) as service:
        response = service.handle_action("tool_clear_history", {})

    assert response["status"] == "error"
    assert response["data"]["status"] == "forbidden"
    assert response["data"]["code"] == "invalid_execution_profile"


def test_public_web_validate_is_denied_before_manifest_or_runner_lookup(tmp_path: Path) -> None:
    runner = _FakeToolRunner()
    profile = public_web_profile(owner_id="web-session", approved_roots=())

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(
            "tool_validate",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(tmp_path / "media.mp4")},
                "_approved_roots": [],
            },
        )

    assert response == {
        "status": "forbidden",
        "code": "tool_run_disabled",
        "message": "tool execution is disabled for this host",
    }
    assert runner.calls == []


def test_public_web_start_is_denied_before_nested_payload_or_runner_lookup(tmp_path: Path) -> None:
    runner = _FakeToolRunner()
    runner.manifests[0]["input_schema"] = {
        "type": "object",
        "properties": {
            "batch": {
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "format": "path"},
                    }
                },
            }
        },
    }
    profile = public_web_profile(owner_id="web-session", approved_roots=())

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(
            "tool_start",
            {
                "tool_id": "file_verify",
                "parameters": {"batch": {"sources": [str(tmp_path / "media.mp4")]}},
                "_approved_roots": [],
            },
        )

    assert response == {
        "status": "forbidden",
        "code": "tool_run_disabled",
        "message": "tool execution is disabled for this host",
    }
    assert runner.calls == []


def test_tool_open_result_uses_stored_path_and_enforces_trusted_root(tmp_path: Path) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    output_path = trusted_root / "report.json"
    output_path.write_text("{}", encoding="utf-8")
    untrusted_root = tmp_path / "elsewhere"
    untrusted_root.mkdir()
    runner = _FakeToolRunner(
        records=[
            _record(
                source=trusted_root / "media.mp4",
                output_path=output_path,
            )
        ]
    )
    opener = Mock()
    untrusted_profile = local_execution_profile(
        host_surface="test",
        owner_id="desktop-untrusted",
        approved_roots=(untrusted_root,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    trusted_profile = local_execution_profile(
        host_surface="test",
        owner_id="desktop-trusted",
        approved_roots=(trusted_root,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )

    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=untrusted_profile,
    ) as service:
        rejected = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "run-finished",
                "result_path": str(untrusted_root / "client-selected.json"),
            },
        )

    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=trusted_profile,
    ) as service:
        accepted = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "run-finished",
                "result_path": str(output_path),
            },
        )

    assert rejected["status"] == "error"
    assert rejected == {
        "status": "error",
        "message": "tool result path could not be authorized",
        "data": {"run_id": "run-finished"},
    }
    assert str(output_path) not in repr(rejected)
    assert accepted["status"] == "ok"
    assert accepted["data"] == {"run_id": "run-finished"}
    assert str(output_path) not in repr(accepted)
    assert (
        "lookup_private_result",
        trusted_profile,
        "run-finished",
    ) in runner.calls
    opener.assert_called_once_with(output_path)


def test_profile_rebind_rejects_cross_owner_identity_change(tmp_path: Path) -> None:
    runner = _FakeToolRunner()
    profile = _desktop_profile(tmp_path, owner_id="owner-a")

    with _service(tmp_path, runner, execution_profile=profile) as service:
        service.set_tool_execution_profile(_desktop_profile(tmp_path, owner_id="owner-a"))
        try:
            service.set_tool_execution_profile(_desktop_profile(tmp_path, owner_id="owner-b"))
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError("cross-owner profile rebind must be rejected")

    assert "identity" in message


@pytest.mark.parametrize(
    ("action", "payload"),
    (
        ("tool_validate", {"parameters": []}),
        ("tool_start", {}),
        ("tool_cancel", {"run_id": 7}),
        ("tool_open_result", {"result_path": []}),
        ("tool_clear_history", {}),
        ("tool_reload", {"force": "yes"}),
        ("run_tool", {"parameters": []}),
    ),
)
def test_public_web_forged_tool_actions_fail_before_payload_or_runner_callbacks(
    tmp_path: Path,
    action: str,
    payload: dict[str, Any],
) -> None:
    runner = _FakeToolRunner(records=[_record()])
    profile = public_web_profile(
        owner_id="web:forged-session",
        approved_roots=(tmp_path,),
    )

    with _service(tmp_path, runner, execution_profile=profile) as service:
        response = service.handle_action(action, payload)

    assert response == {
        "status": "forbidden",
        "code": "tool_run_disabled",
        "message": "tool execution is disabled for this host",
    }
    assert runner.calls == []


def test_public_web_snapshot_masks_every_tool_action_and_private_result_field(
    tmp_path: Path,
) -> None:
    record = _record(output_path=tmp_path / "private-result.json")
    record["parameters"] = {"token": "parameter-secret-sentinel"}
    record["result"]["data"] = {"secret": "result-secret-sentinel"}
    runner = _FakeToolRunner(records=[record])
    profile = public_web_profile(owner_id="web:snapshot", approved_roots=(tmp_path,))

    with _service(tmp_path, runner, execution_profile=profile) as service:
        snapshot = service.get_snapshot(
            sections=frozenset(
                {
                    "toolbox_items",
                    "toolbox_recent_items",
                    "toolbox_display_projection",
                }
            )
        )

    assert snapshot["toolbox_items"]
    assert all(
        enabled is False
        for item in snapshot["toolbox_items"]
        for enabled in item["actions"].values()
    )
    projection = snapshot["toolbox_display_projection"]
    assert projection["actions"]
    assert all(enabled is False for enabled in projection["actions"].values())
    assert "parameters" not in snapshot["toolbox_recent_items"][0]
    assert "data" not in projection["result"]
    assert "output_paths" not in projection["result"]
    assert "result_path" not in projection["result"]
    assert "has_output" not in projection["result"]
    rendered = repr(snapshot)
    assert "parameter-secret-sentinel" not in rendered
    assert "result-secret-sentinel" not in rendered
    assert str(tmp_path / "private-result.json") not in rendered


def test_each_local_action_captures_one_dynamic_profile_without_payload_root_expansion(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    attacker_root = tmp_path / "attacker"
    for root in (first_root, second_root, attacker_root):
        root.mkdir()
    current_root = [first_root]
    captured_profiles: list[ExecutionProfile] = []

    def profile_provider() -> ExecutionProfile:
        profile = local_execution_profile(
            host_surface="desktop_gui",
            owner_id="gui:stable-owner",
            approved_roots=(current_root[0],),
            tool_permissions=("read_file", "write_file", "destructive", "process", "network"),
            allow_external_plugins=False,
        )
        captured_profiles.append(profile)
        return profile

    runner = _FakeToolRunner()
    with _service(
        tmp_path,
        runner,
        execution_profile_provider=profile_provider,
    ) as service:
        validated = service.handle_action(
            "tool_validate",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(attacker_root / "forged.mp4")},
                "_approved_roots": [str(attacker_root)],
            },
        )
        first_action_calls = list(runner.calls)
        current_root[0] = second_root
        started = service.handle_action(
            "tool_start",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(attacker_root / "forged.mp4")},
                "approved_roots": [str(attacker_root)],
            },
        )

    assert validated["status"] == "ok"
    assert started["status"] == "ok"
    assert len(captured_profiles) == 2
    first_profile, second_profile = captured_profiles
    assert first_profile.owner_id == second_profile.owner_id == "gui:stable-owner"
    assert first_profile.approved_roots == frozenset({first_root.resolve()})
    assert second_profile.approved_roots == frozenset({second_root.resolve()})
    assert attacker_root.resolve() not in first_profile.approved_roots
    assert attacker_root.resolve() not in second_profile.approved_roots
    assert any(call[0] == "validate" and call[-1] is first_profile for call in first_action_calls)
    second_action_calls = runner.calls[len(first_action_calls) :]
    assert any(call[0] == "run" and call[-1] is second_profile for call in second_action_calls)
    assert all(
        call[1] is second_profile
        for call in second_action_calls
        if call[0] == "history"
    )


@pytest.mark.parametrize(
    ("action", "payload"),
    (
        ("tool_validate", {"tool_id": "file_verify", "parameters": {}}),
        ("tool_start", {"tool_id": "file_verify", "parameters": {}}),
        ("run_tool", {"tool_id": "file_verify", "parameters": {}}),
        ("tool_cancel", {"tool_id": "file_verify", "run_id": "run-active"}),
        ("tool_open_result", {"tool_id": "file_verify", "result_id": "run-finished"}),
        ("tool_clear_history", {"tool_id": "file_verify"}),
        ("tool_reload", {"tool_id": "file_verify", "force": True}),
    ),
)
def test_every_local_tool_action_captures_exactly_one_profile(
    tmp_path: Path,
    action: str,
    payload: dict[str, Any],
) -> None:
    output_path = tmp_path / "result.json"
    output_path.write_text("{}", encoding="utf-8")
    runner = _FakeToolRunner(
        records=[
            _record(run_id="run-active", status="running"),
            _record(run_id="run-finished", output_path=output_path),
        ]
    )
    profile = _desktop_profile(tmp_path, owner_id="gui:single-capture")
    captures: list[ExecutionProfile] = []

    def provider() -> ExecutionProfile:
        captures.append(profile)
        return profile

    with _service(
        tmp_path,
        runner,
        opener=Mock(),
        execution_profile_provider=provider,
    ) as service:
        response = service.handle_action(action, payload)

    forwarded_profiles = [
        value
        for call in runner.calls
        for value in call
        if isinstance(value, ExecutionProfile)
    ]
    assert response["status"] == "ok"
    assert captures == [profile]
    assert forwarded_profiles
    assert all(value is profile for value in forwarded_profiles)


def test_open_result_rejects_client_path_outside_private_handle_and_non_files(
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    stored_file = trusted_root / "stored.json"
    stored_file.write_text("{}", encoding="utf-8")
    stored_directory = trusted_root / "not-a-file"
    stored_directory.mkdir()
    forged_file = trusted_root / "forged.json"
    forged_file.write_text("{}", encoding="utf-8")
    runner = _FakeToolRunner(
        records=[
            _record(run_id="stored-file", output_path=stored_file),
            _record(run_id="stored-directory", output_path=stored_directory),
        ]
    )
    profile = _desktop_profile(trusted_root)
    opener = Mock()

    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=profile,
    ) as service:
        forged = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "stored-file",
                "result_path": str(forged_file),
            },
        )
        directory = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "stored-directory",
            },
        )
        accepted = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "stored-file",
                "result_path": str(stored_file),
            },
        )

    assert forged["status"] == "error"
    assert directory["status"] == "error"
    assert accepted == {
        "status": "ok",
        "message": "tool result opened",
        "data": {"run_id": "stored-file"},
    }
    assert str(stored_file) not in repr(accepted)
    opener.assert_called_once_with(stored_file.resolve())


def test_open_result_does_not_echo_private_path_when_host_opener_fails(
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    stored_file = trusted_root / "private-result.json"
    stored_file.write_text("{}", encoding="utf-8")
    runner = _FakeToolRunner(records=[_record(run_id="opener-failure", output_path=stored_file)])
    profile = _desktop_profile(trusted_root)
    opener = Mock(side_effect=OSError(f"host failed to open {stored_file}"))

    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=profile,
    ) as service:
        response = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "opener-failure",
            },
        )

    assert response == {
        "status": "error",
        "message": "tool result could not be opened",
        "data": {"run_id": "opener-failure"},
    }
    assert str(stored_file) not in repr(response)
    opener.assert_called_once_with(stored_file.resolve())


@pytest.mark.parametrize(
    ("failure_stage", "expected_message"),
    (
        ("lookup", "tool result is unavailable"),
        ("authorize", "tool result path could not be authorized"),
        ("resolve", "tool result path could not be authorized"),
        ("exists", "tool result is unavailable"),
        ("is_file", "tool result is unavailable"),
    ),
)
def test_open_result_sanitizes_private_path_operation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_message: str,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    stored_file = trusted_root / "private-sentinel-result.json"
    stored_file.write_text("{}", encoding="utf-8")
    runner = _FakeToolRunner(records=[_record(run_id="hostile-path", output_path=stored_file)])
    profile = _desktop_profile(trusted_root)
    opener = Mock()
    sentinel = str(stored_file.resolve())

    def fail(*_args, **_kwargs):
        raise OSError(f"hostile path operation exposed {sentinel}")

    payload: dict[str, Any] = {
        "tool_id": "file_verify",
        "result_id": "hostile-path",
    }
    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=profile,
    ) as service:
        with monkeypatch.context() as scoped_patch:
            if failure_stage == "lookup":
                scoped_patch.setattr(runner, "lookup_private_result", fail)
            elif failure_stage == "authorize":
                scoped_patch.setattr(ToolContext, "authorize_path", fail)
            elif failure_stage == "resolve":
                scoped_patch.setattr(
                    ToolContext,
                    "authorize_path",
                    lambda _self, path: Path(path),
                )
                scoped_patch.setattr(Path, "resolve", fail)
                payload["result_path"] = str(stored_file)
            elif failure_stage == "exists":
                scoped_patch.setattr(Path, "exists", fail)
            else:
                scoped_patch.setattr(Path, "is_file", fail)
            response = service.handle_action("tool_open_result", payload)

    assert response == {
        "status": "error",
        "message": expected_message,
        "data": {"run_id": "hostile-path"},
    }
    assert sentinel not in repr(response)
    opener.assert_not_called()


def test_open_result_rejects_private_handle_with_any_unapproved_path(
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    stored_file = trusted_root / "stored.json"
    stored_file.write_text("{}", encoding="utf-8")
    untrusted_file = tmp_path / "outside.json"
    untrusted_file.write_text("{}", encoding="utf-8")
    record = _record(run_id="mixed-handle", output_path=stored_file)
    record["result"]["output_paths"].append(str(untrusted_file))
    runner = _FakeToolRunner(records=[record])
    opener = Mock()

    with _service(
        tmp_path,
        runner,
        opener=opener,
        execution_profile=_desktop_profile(trusted_root),
    ) as service:
        rejected = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "mixed-handle",
                "result_path": str(stored_file),
            },
        )

    assert rejected["status"] == "error"
    opener.assert_not_called()


class _BuiltinOutputTool:
    manifest = ToolManifest(
        id="frontend_output",
        title="Frontend output",
        summary="Create an output file for frontend composition tests",
        permissions=("write_file",),
        input_schema={
            "type": "object",
            "properties": {"output": {"type": "string", "format": "path"}},
            "required": ["output"],
        },
    )

    @staticmethod
    def requirements_for(_parameters: dict[str, Any]) -> ToolRequirements:
        return ToolRequirements(
            permissions=frozenset({"write_file"}),
            requires_approved_roots=True,
        )

    @staticmethod
    def validate(context) -> ToolValidationResult:
        if not context.parameters.get("output"):
            return ToolValidationResult.rejected("output is required")
        context.authorize_path(context.parameters["output"])
        return ToolValidationResult.ok(parameters=context.parameters)

    @staticmethod
    def run(context) -> ToolRunResult:
        output = context.authorize_path(context.parameters["output"])
        output.write_text("private-result", encoding="utf-8")
        return ToolRunResult.success(
            "created",
            data={"secret": "real-runner-secret-sentinel"},
            output_paths=(str(output),),
        )


def test_default_gui_history_survives_fss_and_main_window_rebuild_and_stays_scoped(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "downloads-first"
    second_root = tmp_path / "downloads-second"
    first_root.mkdir()
    second_root.mkdir()
    history_path = tmp_path / "history.json"

    def make_runner() -> ToolRunnerService:
        registry = ToolRegistry(
            tools=[],
            include_builtins=False,
            include_entry_points=False,
        )
        registry._register(_BuiltinOutputTool(), provenance="builtin")
        return ToolRunnerService(registry=registry, history_path=history_path)

    first_config = ConfigManager(str(tmp_path / "first-config.json"))
    first_config.set("common", "save_directory", str(first_root))
    first_runner = make_runner()
    first_service = FrontendStateService(
        config_manager=first_config,
        failed_record_store=_NoopFailedRecordStore(),
        tool_runner_service=first_runner,
    )
    try:
        first_profile = first_service.tool_execution_profile
        queued = first_service.handle_action(
            "tool_start",
            {
                "tool_id": "frontend_output",
                "parameters": {"output": str(first_root / "result.txt")},
            },
        )
        run_id = queued["data"]["run_id"]
        terminal = first_runner.wait_for_run(
            run_id,
            execution_profile=first_profile,
            timeout=2.0,
        )
        assert terminal["status"] == "succeeded"
    finally:
        first_service.destroy()
        assert first_runner.shutdown(wait=True, timeout=2.0) is True

    rebuilt_window = MainWindow.__new__(MainWindow)
    rebuilt_window.__dict__["_save_dir_lock"] = threading.RLock()
    rebuilt_window.__dict__["_current_save_dir"] = str(second_root)
    rebuilt_window.__dict__["_tool_execution_owner_id"] = "gui:legacy-other-process"
    rebuilt_profile = MainWindow._build_tool_execution_profile(rebuilt_window)
    second_runner = make_runner()
    second_service = FrontendStateService(
        config_manager=ConfigManager(str(tmp_path / "second-config.json")),
        failed_record_store=_NoopFailedRecordStore(),
        tool_runner_service=second_runner,
        execution_profile=rebuilt_profile,
    )
    different_host = local_execution_profile(
        host_surface="sdk",
        owner_id="gui:local",
        approved_roots=(second_root,),
        tool_permissions=rebuilt_profile.tool_permissions,
        allow_external_plugins=False,
    )
    different_owner = local_execution_profile(
        host_surface="desktop_gui",
        owner_id="gui:other",
        approved_roots=(second_root,),
        tool_permissions=rebuilt_profile.tool_permissions,
        allow_external_plugins=False,
    )
    try:
        snapshot = second_service.get_snapshot(
            sections=frozenset({"toolbox_recent_items"})
        )
        assert [row["run_id"] for row in snapshot["toolbox_recent_items"]] == [run_id]
        assert first_profile.owner_id == rebuilt_profile.owner_id == "gui:local"
        assert first_profile.approved_roots == frozenset({first_root.resolve()})
        assert rebuilt_profile.approved_roots == frozenset({second_root.resolve()})
        assert second_runner.history(execution_profile=different_host) == []
        assert second_runner.history(execution_profile=different_owner) == []

        cleared = second_service.handle_action("tool_clear_history", {})
        after_clear = second_service.get_snapshot(
            sections=frozenset({"toolbox_recent_items"})
        )
        assert cleared["status"] == "ok"
        assert cleared["data"]["removed"] == 1
        assert after_clear["toolbox_recent_items"] == []
    finally:
        second_service.destroy()
        assert second_runner.shutdown(wait=True, timeout=2.0) is True

    assert json.loads(history_path.read_text(encoding="utf-8")) == []


def test_frontend_real_runner_keeps_public_projection_safe_and_private_open_owner_scoped(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(
        tools=[],
        include_builtins=False,
        include_entry_points=False,
    )
    registry._register(_BuiltinOutputTool(), provenance="builtin")
    runner = ToolRunnerService(
        registry=registry,
        history_path=tmp_path / "history.json",
    )
    root = tmp_path / "owner-root"
    root.mkdir()
    output = root / "result.txt"
    owner = _desktop_profile(root, owner_id="gui:owner-a")
    other = _desktop_profile(root, owner_id="gui:owner-b")
    opener = Mock()

    try:
        with _service(
            tmp_path,
            runner,  # type: ignore[arg-type]
            opener=opener,
            execution_profile=owner,
        ) as owner_service:
            queued = owner_service.handle_action(
                "tool_start",
                {
                    "tool_id": "frontend_output",
                    "parameters": {"output": str(output)},
                },
            )
            run_id = queued["data"]["run_id"]
            terminal = runner.wait_for_run(
                run_id,
                execution_profile=owner,
                timeout=2.0,
            )
            snapshot = owner_service.get_snapshot(
                sections=frozenset(
                    {
                        "toolbox_items",
                        "toolbox_recent_items",
                        "toolbox_display_projection",
                    }
                )
            )
            opened = owner_service.handle_action(
                "tool_open_result",
                {"tool_id": "frontend_output", "result_id": run_id},
            )

        with _service(
            tmp_path,
            runner,  # type: ignore[arg-type]
            execution_profile=other,
        ) as other_service:
            unknown = other_service.handle_action(
                "tool_open_result",
                {"tool_id": "frontend_output", "result_id": "unknown-run"},
            )
            cross_owner = other_service.handle_action(
                "tool_open_result",
                {"tool_id": "frontend_output", "result_id": run_id},
            )
            other_snapshot = other_service.get_snapshot(
                sections=frozenset({"toolbox_recent_items"})
            )

        assert queued["status"] == "ok"
        assert terminal is not None and terminal["status"] == "succeeded"
        display_projection = snapshot["toolbox_display_projection"]
        assert display_projection["actions"]["tool_open_result"] is True
        assert "has_output" not in display_projection["result"]
        assert opened["status"] == "ok"
        assert opened["data"] == {"run_id": run_id}
        opener.assert_called_once_with(output.resolve())
        assert cross_owner == unknown
        assert other_snapshot["toolbox_recent_items"] == []
        rendered = repr({"queued": queued, "terminal": terminal, "snapshot": snapshot})
        assert str(output) not in rendered
        assert "real-runner-secret-sentinel" not in rendered
        assert "output_paths" not in rendered
        assert "parameters" not in terminal
    finally:
        assert runner.shutdown(wait=True, timeout=2.0) is True
