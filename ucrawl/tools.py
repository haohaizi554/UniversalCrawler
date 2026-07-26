"""Thin public SDK adapter for the application tool runner.

The mainline service is intentionally imported only when an operation is used.
``app.services.tool_runner_service.ToolRunnerService`` must be constructible
without arguments and implement ``list``, ``describe``, ``validate``, ``run``,
``cancel``, and ``history``. Results must be JSON-compatible so the same
values can be returned by the SDK and rendered by the CLI.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol


_SERVICE_MODULE = "app.services.tool_runner_service"
_SERVICE_CLASS = "ToolRunnerService"
_OPERATIONS = "list/describe/validate/run/cancel/history"


class ToolRunnerUnavailableError(RuntimeError):
    """Raised when the mainline application service is not available."""


class ToolRunnerServiceContract(Protocol):
    """Contract consumed by the SDK adapter; implemented in ``app.services``."""

    def list(self) -> Any: ...

    def describe(self, tool_id: str) -> Any: ...

    def validate(self, tool_id: str, params: dict[str, Any]) -> Any: ...

    def run(self, tool_id: str, params: dict[str, Any]) -> Any: ...

    def cancel(self, run_id: str) -> Any: ...

    def history(self, **filters: Any) -> Any: ...


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
    """SDK facade that forwards every operation to ``ToolRunnerService``."""

    def __init__(self, service: ToolRunnerServiceContract | None = None) -> None:
        self._service = service

    def _get_service(self) -> ToolRunnerServiceContract:
        if self._service is None:
            self._service = _create_service()
        return self._service

    def list(self) -> Any:
        return self._get_service().list()

    def describe(self, tool_id: str) -> Any:
        return self._get_service().describe(tool_id)

    def validate(self, tool_id: str, params: dict[str, Any]) -> Any:
        return self._get_service().validate(tool_id, params)

    def run(self, tool_id: str, params: dict[str, Any]) -> Any:
        return self._get_service().run(tool_id, params)

    def cancel(self, run_id: str) -> Any:
        return self._get_service().cancel(run_id)

    def history(self, **filters: Any) -> Any:
        return self._get_service().history(**filters)


__all__ = [
    "ToolRunnerServiceContract",
    "ToolRunnerUnavailableError",
    "ToolsAPI",
]
