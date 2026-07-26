"""Public SDK contract for the application tool runner."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class RecordingToolRunnerService:
    """Small contract double that records the SDK-to-service boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.responses = {
            name: {"operation": name}
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
    ),
)
def test_tools_api_forwards_each_operation_without_rewriting_payloads(
    operation: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    from ucrawl.tools import ToolsAPI

    service = RecordingToolRunnerService()
    api = ToolsAPI(service=service)

    result = getattr(api, operation)(*args, **kwargs)

    assert result is service.responses[operation]
    assert service.calls == [(operation, args, kwargs)]


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

    api = tools_module.ToolsAPI()
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

    api = tools_module.ToolsAPI()
    with pytest.raises(tools_module.ToolRunnerUnavailableError) as raised:
        api.list()

    message = str(raised.value)
    assert "app.services.tool_runner_service.ToolRunnerService" in message
    assert "list/describe/validate/run/cancel/history" in message


def test_ucrawl_sdk_exposes_one_cached_tools_api() -> None:
    from ucrawl import ToolsAPI, UcrawlSDK

    sdk = UcrawlSDK(save_dir=".")

    assert isinstance(sdk.tools, ToolsAPI)
    assert sdk.tools is sdk.tools
