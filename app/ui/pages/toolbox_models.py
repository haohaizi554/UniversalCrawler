from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ToolboxSnapshot:
    """Immutable display data retained by the toolbox composition page."""

    items: tuple[Mapping[str, Any], ...]
    recent_items: tuple[Mapping[str, Any], ...]
    projections: Mapping[str, Mapping[str, Any]]
    selected_tool_id: str = ""


def mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def freeze_display(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), freeze_display(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(freeze_display(item) for item in value)
    try:
        hash(value)
    except TypeError:
        return str(value)
    return value


def phase_for(projection: Mapping[str, Any]) -> str:
    return str(projection.get("state") or projection.get("phase") or "idle").strip().lower()


def action_enabled(projection: Mapping[str, Any], action: str, default: bool) -> bool:
    actions = projection.get("actions")
    if isinstance(actions, Mapping) and action in actions:
        value = actions[action]
        if isinstance(value, Mapping):
            return bool(value.get("enabled", True))
        return bool(value)
    if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
        return action in actions
    short_name = action.removeprefix("tool_")
    for key in (f"can_{short_name}", f"{short_name}_enabled"):
        if key in projection:
            return bool(projection[key])
    return default


def build_action_payload(
    action: str,
    tool_id: str,
    projection: Mapping[str, Any],
    parameter_values: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    action_payloads = projection.get("action_payloads")
    if isinstance(action_payloads, Mapping) and isinstance(action_payloads.get(action), Mapping):
        payload.update(action_payloads[action])
    actions = projection.get("actions")
    if isinstance(actions, Mapping) and isinstance(actions.get(action), Mapping):
        explicit_payload = actions[action].get("payload")
        if isinstance(explicit_payload, Mapping):
            payload.update(explicit_payload)
    payload.setdefault("tool_id", tool_id)
    if action in {"tool_validate", "tool_start"}:
        payload["parameters"] = dict(parameter_values)
    elif action == "tool_cancel":
        run_id = projection.get("run_id") or projection.get("execution_id")
        if run_id:
            payload.setdefault("run_id", str(run_id))
    elif action == "tool_open_result":
        result = projection.get("result")
        if isinstance(result, Mapping):
            result_id = result.get("id") or result.get("result_id")
            if result_id:
                payload.setdefault("result_id", str(result_id))
    return payload


def parameter_fields_and_values(
    item: Mapping[str, Any], projection: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    form = projection.get("form") if isinstance(projection.get("form"), Mapping) else {}
    fields_value = form.get("fields") if form else None
    if fields_value is None:
        fields_value = projection.get("parameter_fields")
    if fields_value is None and isinstance(projection.get("parameters"), Sequence):
        fields_value = projection.get("parameters")
    if fields_value is None:
        fields_value = item.get("parameter_fields") or item.get("parameters") or ()
    values: dict[str, Any] = {}
    if isinstance(item.get("parameter_values"), Mapping):
        values.update(item["parameter_values"])
    projection_values = projection.get("parameter_values") or projection.get("values")
    if isinstance(projection_values, Mapping):
        values.update(projection_values)
    if form and isinstance(form.get("values"), Mapping):
        values.update(form["values"])
    if isinstance(projection.get("parameters"), Mapping):
        values.update(projection["parameters"])
    return mapping_list(fields_value), values


def result_lines(result: Any, translate: Callable[[object], str]) -> list[str]:
    lines: list[str] = []
    source = result if isinstance(result, Mapping) else {"display_text": result}
    for value in (source.get("display_text"), source.get("summary")):
        _append_unique(lines, _display_scalar(value))
    for row in source.get("rows") or source.get("detail_rows") or ():
        if isinstance(row, Mapping):
            label = _display_scalar(row.get("label") or row.get("title"))
            value = _display_scalar(row.get("value") or row.get("display_value"))
            rendered = (
                f"{translate(label)}: {translate(value)}"
                if label and value
                else _display_scalar(row.get("display_text"))
            )
            _append_unique(lines, rendered)
        else:
            _append_unique(lines, _display_scalar(row))
    return lines


def history_line(item: Mapping[str, Any], translate: Callable[[object], str]) -> str:
    display_text = _display_scalar(item.get("display_text"))
    if display_text:
        return translate(display_text)
    parts = (
        item.get("finished_at") or item.get("last_used") or item.get("time_display"),
        item.get("title") or item.get("tool_title"),
        item.get("status_text"),
        item.get("summary"),
    )
    return "  ".join(translate(text) for part in parts if (text := _display_scalar(part)))


def normalize_toolbox_snapshot(
    raw: Mapping[str, Any],
    previous: ToolboxSnapshot | None = None,
) -> ToolboxSnapshot:
    previous = previous or ToolboxSnapshot((), (), MappingProxyType({}))
    items = mapping_list(raw["toolbox_items"]) if "toolbox_items" in raw else [dict(item) for item in previous.items]
    recent = mapping_list(raw["toolbox_recent_items"]) if "toolbox_recent_items" in raw else [dict(item) for item in previous.recent_items]
    projections = {tool_id: dict(projection) for tool_id, projection in previous.projections.items()}
    selected = str(raw.get("toolbox_selected_tool_id") or previous.selected_tool_id)
    for key in ("toolbox_display_projection", "toolbox_projection", "toolbox_display"):
        projection = raw.get(key)
        if isinstance(projection, Mapping):
            selected = _store_projection(projections, projection, selected) or selected
    for key in ("toolbox_display_batch", "toolbox_projection_batch", "toolbox_batch"):
        batch = raw.get(key)
        if isinstance(batch, Mapping):
            selected = str(batch.get("selected_tool_id") or selected)
            if "history" in batch:
                recent = mapping_list(batch.get("history"))
            candidates = batch.get("projections") or batch.get("updates") or ()
            if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)):
                for projection in candidates:
                    if isinstance(projection, Mapping):
                        _store_projection(projections, projection, selected)
            elif batch.get("tool_id") or batch.get("id"):
                _store_projection(projections, batch, selected)
        elif isinstance(batch, Sequence) and not isinstance(batch, (str, bytes)):
            for projection in batch:
                if isinstance(projection, Mapping):
                    _store_projection(projections, projection, selected)
    for projection in projections.values():
        if "history" in projection:
            recent = mapping_list(projection.get("history"))
    return ToolboxSnapshot(
        tuple(MappingProxyType(item) for item in items),
        tuple(MappingProxyType(item) for item in recent),
        MappingProxyType({key: MappingProxyType(value) for key, value in projections.items()}),
        selected,
    )


def _store_projection(projections: dict[str, dict[str, Any]], projection: Mapping[str, Any], selected: str) -> str:
    tool_id = str(projection.get("tool_id") or projection.get("id") or selected)
    if not tool_id:
        return ""
    merged = dict(projections.get(tool_id, {}))
    incoming = dict(projection)
    if isinstance(merged.get("form"), Mapping) and isinstance(incoming.get("form"), Mapping):
        incoming["form"] = {**merged["form"], **incoming["form"]}
    merged.update(incoming)
    merged["tool_id"] = tool_id
    projections[tool_id] = merged
    return tool_id


def _display_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, Mapping):
        return _display_scalar(value.get("display_text") or value.get("text"))
    return ""


def _append_unique(lines: list[str], value: str) -> None:
    if value and value not in lines:
        lines.append(value)
