"""Safe public and durable projections for tool runtime history."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def project_history_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively positive projection for public and durable history."""

    projected: dict[str, Any] = {}
    for key in (
        "run_id",
        "tool_id",
        "host_surface",
        "owner_id",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "progress",
        "message",
    ):
        value = record.get(key)
        if key in record and _is_scalar(value):
            projected[key] = value

    result = record.get("result")
    if isinstance(result, Mapping):
        projected_result: dict[str, Any] = {}
        for key in ("status", "message"):
            value = result.get(key)
            if key in result and _is_scalar(value):
                projected_result[key] = value
        if "warnings" in result:
            warnings = _project_scalar_list(result.get("warnings"))
            if warnings is not None:
                projected_result["warnings"] = warnings
        if projected_result:
            projected["result"] = projected_result
    return projected


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _project_scalar_list(value: Any) -> list[Any] | None:
    if not isinstance(value, (list, tuple)):
        return None
    return [item for item in value if _is_scalar(item)]


__all__ = ["project_history_record"]
