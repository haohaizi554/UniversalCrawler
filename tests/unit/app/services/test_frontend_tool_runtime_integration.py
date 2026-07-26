from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import Mock

from app.config import ConfigManager
from app.services.frontend_state_service import FrontendStateService


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

    def history(self, *, tool_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        self.calls.append(("history", tool_id, limit))
        records = self.records
        if tool_id:
            records = [record for record in records if record.get("tool_id") == tool_id]
        return deepcopy(records[:limit])

    def validate(
        self,
        tool_id: str,
        parameters: dict[str, Any],
        *,
        approved_roots: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append(("validate", tool_id, deepcopy(parameters), tuple(approved_roots)))
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
        approved_roots: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append(("run", tool_id, deepcopy(parameters), tuple(approved_roots)))
        record = {
            "run_id": "run-started",
            "tool_id": tool_id,
            "status": "queued",
            "message": "已加入队列",
            "parameters": deepcopy(parameters),
            "progress": 0,
        }
        self.records.insert(0, record)
        return deepcopy(record)

    def cancel(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("cancel", run_id))
        for record in self.records:
            if record.get("run_id") == run_id:
                record["status"] = "cancelling"
                record["message"] = "正在取消"
                return deepcopy(record)
        return {"status": "error", "message": "run not found", "run_id": run_id}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        self.calls.append(("get_run", run_id))
        for record in self.records:
            if record.get("run_id") == run_id:
                return deepcopy(record)
        return None

    def clear_history(self) -> dict[str, Any]:
        self.calls.append(("clear_history",))
        cleared = len(self.records)
        self.records.clear()
        return {"cleared": cleared}

    def reload(self, *, force: bool = False) -> dict[str, Any]:
        self.calls.append(("reload", force))
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
) -> Iterator[FrontendStateService]:
    service = FrontendStateService(
        config_manager=ConfigManager(str(tmp_path / "config.json")),
        failed_record_store=_NoopFailedRecordStore(),
        tool_runner_service=runner,
    )
    if opener is not None:
        service._open_file_path = opener
    try:
        yield service
    finally:
        service.destroy()


def test_dynamic_toolbox_snapshot_comes_from_injected_runner(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record()])

    with _service(tmp_path, runner) as service:
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
    assert projection["result"]["data"] == {"checked": 1}
    assert projection["actions"]["tool_open_result"] is False
    assert runner.calls.count(("list",)) == 1
    assert runner.calls.count(("history", None, 20)) == 1


def test_tool_validate_forwards_parameters_and_trusted_roots(tmp_path: Path) -> None:
    source = tmp_path / "media.mp4"
    source.write_bytes(b"media")
    runner = _FakeToolRunner()

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_validate",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(source)},
                "_approved_roots": [str(tmp_path)],
            },
        )

    assert response["status"] == "ok"
    assert response["data"]["validation"]["valid"] is True
    assert response["data"]["toolbox_display_projection"]["validation"]["state"] == "valid"
    assert (
        "validate",
        "file_verify",
        {"source": str(source)},
        (str(tmp_path.resolve()),),
    ) in runner.calls


def test_tool_start_returns_runner_run_and_projection(tmp_path: Path) -> None:
    source = tmp_path / "media.mp4"
    source.write_bytes(b"media")
    runner = _FakeToolRunner()

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_start",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(source)},
                "_approved_roots": [str(tmp_path)],
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
        (str(tmp_path.resolve()),),
    ) in runner.calls


def test_tool_cancel_projects_cancelling_state(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record(run_id="run-active", status="running")])

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_cancel",
            {"tool_id": "file_verify", "run_id": "run-active"},
        )

    assert response["status"] == "ok"
    assert ("cancel", "run-active") in runner.calls
    projection = response["data"]["toolbox_display_projection"]
    assert projection["state"] == "cancelling"
    assert projection["actions"]["tool_cancel"] is False


def test_tool_clear_history_and_reload_refresh_projection(tmp_path: Path) -> None:
    runner = _FakeToolRunner(records=[_record()])

    with _service(tmp_path, runner) as service:
        cleared = service.handle_action("tool_clear_history", {"tool_id": "file_verify"})
        reloaded = service.handle_action("tool_reload", {"tool_id": "file_verify", "force": True})

    assert cleared["status"] == "ok"
    assert cleared["data"]["cleared"] == 1
    assert cleared["data"]["toolbox_display_projection"]["history"] == []
    assert reloaded["status"] == "ok"
    assert reloaded["data"]["reloaded"] is True
    assert reloaded["data"]["toolbox_display_projection"]["tool_id"] == "file_verify"
    assert ("clear_history",) in runner.calls
    assert ("reload", True) in runner.calls


def test_web_path_tool_rejects_missing_trusted_roots_before_runner(tmp_path: Path) -> None:
    runner = _FakeToolRunner()

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_validate",
            {
                "tool_id": "file_verify",
                "parameters": {"source": str(tmp_path / "media.mp4")},
                "_approved_roots": [],
            },
        )

    assert response["status"] == "error"
    assert "approved session root" in response["message"]
    assert not any(call[0] == "validate" for call in runner.calls)


def test_web_nested_path_array_rejects_missing_trusted_roots(tmp_path: Path) -> None:
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

    with _service(tmp_path, runner) as service:
        response = service.handle_action(
            "tool_start",
            {
                "tool_id": "file_verify",
                "parameters": {"batch": {"sources": [str(tmp_path / "media.mp4")]}},
                "_approved_roots": [],
            },
        )

    assert response["status"] == "error"
    assert "approved session root" in response["message"]
    assert not any(call[0] == "run" for call in runner.calls)


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

    with _service(tmp_path, runner, opener=opener) as service:
        rejected = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "run-finished",
                "result_path": str(untrusted_root / "client-selected.json"),
                "_approved_roots": [str(untrusted_root)],
            },
        )
        accepted = service.handle_action(
            "tool_open_result",
            {
                "tool_id": "file_verify",
                "result_id": "run-finished",
                "result_path": str(untrusted_root / "client-selected.json"),
                "_approved_roots": [str(trusted_root)],
            },
        )

    assert rejected["status"] == "error"
    assert "outside approved roots" in rejected["message"]
    assert accepted["status"] == "ok"
    assert accepted["data"]["path"] == str(output_path)
    opener.assert_called_once_with(output_path)
