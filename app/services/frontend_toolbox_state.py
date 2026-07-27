"""Toolbox runtime projections, path authorization, and actions."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from app.services.frontend_action_result import FrontendActionResult


class FrontendToolboxStateMixin:
    """Keep toolbox behavior independent from the broader frontend state service."""

    def _tool_settings_snapshot(self) -> dict[str, Any]:
        try:
            return deepcopy(dict(getattr(self.config, "data", {}) or {}))
        except (AttributeError, TypeError, ValueError) as exc:
            debug_logger.log_exception(
                "FrontendStateService",
                "tool_settings_snapshot",
                exc,
            )
            return {}

    @staticmethod
    def _tool_parameter_fields(schema: Any) -> list[dict[str, Any]]:
        if not isinstance(schema, Mapping):
            return []
        properties = schema.get("properties")
        required = {
            str(item)
            for item in schema.get("required", ())
            if isinstance(item, (str, int, float))
        }
        source = properties if isinstance(properties, Mapping) else schema
        fields: list[dict[str, Any]] = []
        for name, definition in source.items():
            if not isinstance(definition, Mapping):
                continue
            field = dict(definition)
            field_id = str(field.get("id") or field.get("name") or name)
            field["id"] = field_id
            field["name"] = field_id
            field.setdefault("label", field.get("title") or field_id)
            field["required"] = bool(field.get("required") or field_id in required)
            if "enum" in field and "options" not in field:
                field["options"] = list(field.get("enum") or ())
                field["type"] = "select"
            fields.append(field)
        return fields

    @staticmethod
    def _tool_path_selectors(schema: Any) -> tuple[tuple[str, ...], ...]:
        """Return nested parameter selectors whose schema represents a local path."""

        selectors: list[tuple[str, ...]] = []
        path_markers = {"file", "directory", "dir", "folder", "path"}
        schema_keywords = {
            "$defs",
            "$ref",
            "allOf",
            "anyOf",
            "default",
            "description",
            "enum",
            "format",
            "items",
            "oneOf",
            "properties",
            "required",
            "title",
            "type",
        }

        def walk(node: Any, selector: tuple[str, ...], *, implicit_map: bool = False) -> None:
            if not isinstance(node, Mapping):
                return
            field_type = str(node.get("type") or "").strip().lower()
            field_format = str(node.get("format") or "").strip().lower()
            if field_type in path_markers or field_format in path_markers:
                selectors.append(selector)

            properties = node.get("properties")
            if isinstance(properties, Mapping):
                for name, child in properties.items():
                    walk(child, (*selector, str(name)))
            elif implicit_map or not any(str(key) in schema_keywords for key in node):
                for name, child in node.items():
                    if isinstance(child, Mapping):
                        walk(child, (*selector, str(name)))

            items = node.get("items")
            if isinstance(items, Mapping):
                walk(items, (*selector, "*"))
            for keyword in ("allOf", "anyOf", "oneOf"):
                variants = node.get(keyword)
                if isinstance(variants, Sequence) and not isinstance(variants, (str, bytes)):
                    for variant in variants:
                        walk(variant, selector)

        walk(schema, (), implicit_map=True)
        return tuple(dict.fromkeys(selectors))

    @staticmethod
    def _tool_path_values(
        parameters: Mapping[str, Any],
        selector: Sequence[str],
    ) -> tuple[object, ...]:
        values: list[object] = [parameters]
        for part in selector:
            next_values: list[object] = []
            for value in values:
                if part == "*":
                    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                        next_values.extend(value)
                elif isinstance(value, Mapping) and part in value:
                    next_values.append(value[part])
            values = next_values
            if not values:
                break
        return tuple(values)

    @staticmethod
    def _tool_status_projection(status: object) -> tuple[str, str]:
        normalized = str(status or "idle").strip().lower()
        return {
            "queued": ("starting", "正在启动"),
            "running": ("running", "运行中"),
            "cancelling": ("cancelling", "正在取消"),
            "cancelled": ("cancelled", "已取消"),
            "canceled": ("cancelled", "已取消"),
            "succeeded": ("success", "执行成功"),
            "completed": ("success", "执行成功"),
            "failed": ("error", "执行失败"),
            "error": ("error", "执行失败"),
        }.get(normalized, ("idle", "等待操作"))

    @staticmethod
    def _tool_timestamp_text(value: object) -> str:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return ""
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def toolbox_items(self) -> list[dict[str, Any]]:
        try:
            manifests = self.tool_runner_service.list()
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            debug_logger.log_exception("FrontendStateService", "toolbox_items", exc)
            return []
        items: list[dict[str, Any]] = []
        for manifest in manifests:
            if not isinstance(manifest, Mapping):
                continue
            item = dict(manifest)
            item["id"] = str(item.get("id") or item.get("tool_id") or "")
            item["parameter_fields"] = self._tool_parameter_fields(item.get("input_schema"))
            item["parameters"] = list(item["parameter_fields"])
            item["available"] = True
            item["contract_version"] = 1
            item["actions"] = {
                "tool_validate": True,
                "tool_start": True,
                "tool_cancel": bool(item.get("cancellable", item.get("supports_cancel", True))),
                "tool_open_result": False,
                "tool_clear_history": False,
            }
            items.append(item)
        return items

    def _tool_history_records(
        self,
        *,
        tool_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        try:
            records = self.tool_runner_service.history(
                tool_id=tool_id or None,
                limit=limit,
            )
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            debug_logger.log_exception("FrontendStateService", "toolbox_recent_items", exc)
            return []
        return [dict(record) for record in records if isinstance(record, Mapping)]

    def toolbox_recent_items(
        self,
        *,
        items: Sequence[Mapping[str, Any]] | None = None,
        records: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        item_snapshot = list(items) if items is not None else self.toolbox_items()
        record_snapshot = list(records) if records is not None else self._tool_history_records()
        titles = {
            str(item.get("id") or ""): str(item.get("title") or "")
            for item in item_snapshot
        }
        return [self._tool_history_item(record, titles=titles) for record in record_snapshot]

    def _tool_history_item(
        self,
        record: Mapping[str, Any],
        *,
        titles: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        run_id = str(record.get("run_id") or record.get("id") or "")
        tool_id = str(record.get("tool_id") or "")
        state, status_text = self._tool_status_projection(record.get("status"))
        result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
        message = str(record.get("message") or result.get("message") or "")
        return {
            "id": run_id,
            "run_id": run_id,
            "history_id": run_id,
            "result_id": run_id if result else "",
            "tool_id": tool_id,
            "title": str((titles or {}).get(tool_id) or tool_id),
            "state": state,
            "status": str(record.get("status") or ""),
            "status_text": status_text,
            "finished_at": self._tool_timestamp_text(record.get("finished_at")),
            "summary": message,
            "display_text": message,
        }

    @staticmethod
    def _tool_result_projection(record: Mapping[str, Any]) -> dict[str, Any] | None:
        result = record.get("result")
        if not isinstance(result, Mapping):
            return None
        run_id = str(record.get("run_id") or "")
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        output_paths = [str(path) for path in result.get("output_paths", ()) if str(path).strip()]
        rows = [
            {"label": str(key), "value": value if isinstance(value, (str, int, float, bool)) else str(value)}
            for key, value in data.items()
        ]
        rows.extend({"label": "输出路径", "value": path} for path in output_paths)
        return {
            "id": run_id,
            "result_id": run_id,
            "display_text": str(result.get("message") or record.get("message") or ""),
            "rows": rows,
            "data": dict(data),
            "output_paths": output_paths,
            "result_path": output_paths[0] if output_paths else "",
            "warnings": list(result.get("warnings") or ()),
        }

    def _toolbox_projection(
        self,
        tool_id: str = "",
        *,
        record: Mapping[str, Any] | None = None,
        validation: Mapping[str, Any] | None = None,
        items: Sequence[Mapping[str, Any]] | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        item_snapshot = list(items) if items is not None else self.toolbox_items()
        item_by_id = {str(item.get("id") or ""): item for item in item_snapshot}
        normalized_tool_id = str(tool_id or (record or {}).get("tool_id") or "")
        if not normalized_tool_id and item_snapshot:
            normalized_tool_id = str(item_snapshot[0].get("id") or "")
        if record is None and normalized_tool_id:
            latest_records = self._tool_history_records(tool_id=normalized_tool_id, limit=1)
            record = latest_records[0] if latest_records else None
        record = dict(record or {})
        state, status_text = self._tool_status_projection(record.get("status"))
        item = item_by_id.get(normalized_tool_id, {})
        fields = list(item.get("parameter_fields") or ())
        parameters = dict(record.get("parameters") or {})
        validation_payload = dict(validation or {})
        if validation is not None:
            valid = bool(validation_payload.get("valid")) and validation_payload.get("status") != "error"
            errors = [str(error) for error in validation_payload.get("errors", ()) if str(error).strip()]
            validation_payload = {
                **validation_payload,
                "state": "valid" if valid else "invalid",
                "message": "参数可用" if valid else "；".join(errors) or "参数无效",
            }
            state, status_text = ("ready", "准备就绪") if valid else ("error", "参数无效")
        result = self._tool_result_projection(record)
        run_id = str(record.get("run_id") or "")
        cancellable = bool(item.get("cancellable", item.get("supports_cancel", True)))
        history_snapshot = (
            list(history)
            if history is not None
            else self.toolbox_recent_items(items=item_snapshot)
        )
        return {
            "tool_id": normalized_tool_id,
            "selected_tool_id": normalized_tool_id,
            "state": state,
            "status_text": str(record.get("message") or status_text),
            "run_id": run_id,
            "form": {"fields": fields, "values": parameters},
            "parameter_fields": fields,
            "parameter_values": parameters,
            "validation": validation_payload,
            "progress": {
                "value": int(record.get("progress") or 0),
                "text": str(record.get("message") or ""),
            },
            "result": result,
            "history": history_snapshot,
            "actions": {
                "tool_validate": state not in {"starting", "running", "cancelling"},
                "tool_start": state not in {"starting", "running", "cancelling"},
                "tool_cancel": cancellable and state in {"starting", "running"},
                "tool_open_result": bool(result and result.get("output_paths")),
                "tool_clear_history": bool(history_snapshot),
            },
            "action_payloads": {
                "tool_cancel": {"tool_id": normalized_tool_id, "run_id": run_id},
                "tool_open_result": {"tool_id": normalized_tool_id, "result_id": run_id},
                "tool_clear_history": {"tool_id": normalized_tool_id},
            },
        }

    def _toolbox_snapshot_parts(self) -> dict[str, Any]:
        items = self.toolbox_items()
        records = self._tool_history_records()
        recent = self.toolbox_recent_items(items=items, records=records)
        selected_tool_id = str(recent[0].get("tool_id") or "") if recent else ""
        if not selected_tool_id and items:
            selected_tool_id = str(items[0].get("id") or "")
        return {
            "toolbox_items": items,
            "toolbox_recent_items": recent,
            "toolbox_display_projection": self._toolbox_projection(
                selected_tool_id,
                record=records[0] if records else None,
                items=items,
                history=recent,
            ),
        }

    @staticmethod
    def _tool_action_parameters(payload: Mapping[str, Any]) -> dict[str, Any]:
        parameters = payload.get("parameters")
        if parameters is None:
            return {}
        if not isinstance(parameters, Mapping):
            raise ValueError("parameters must be an object")
        return dict(parameters)

    def _tool_action_roots(
        self,
        payload: Mapping[str, Any],
        tool_id: str,
        parameters: Mapping[str, Any],
    ) -> tuple[str, ...]:
        web_boundary = "_approved_roots" in payload
        roots_value = payload.get("_approved_roots") if web_boundary else ()
        if isinstance(roots_value, Sequence) and not isinstance(roots_value, (str, bytes)):
            roots = [str(root) for root in roots_value if str(root).strip()]
        else:
            roots = []

        manifest = self.tool_runner_service.describe(tool_id)
        input_schema = manifest.get("input_schema")
        path_selectors = self._tool_path_selectors(input_schema)
        permissions = {
            str(permission).strip().lower()
            for permission in manifest.get("permissions", ())
            if str(permission).strip()
        }
        requires_path_authorization = bool(
            path_selectors
            or any(
                marker in permission
                for permission in permissions
                for marker in ("file", "directory", "folder", "path", "filesystem")
            )
        )
        if web_boundary and requires_path_authorization and not roots:
            raise PermissionError("tool path access requires an approved session root")

        if not web_boundary:
            try:
                configured_root = str(self.config.get("common", "save_directory", "") or "")
            except (AttributeError, TypeError, ValueError):
                configured_root = ""
            if configured_root:
                roots.append(configured_root)
            for selector in path_selectors:
                for candidate in self._tool_path_values(parameters, selector):
                    if candidate is None or not str(candidate).strip():
                        continue
                    roots.append(str(Path(str(candidate)).expanduser()))

        unique: list[str] = []
        seen: set[str] = set()
        for root in roots:
            try:
                normalized = str(Path(root).expanduser().resolve())
            except (OSError, RuntimeError, ValueError):
                continue
            key = os.path.normcase(normalized)
            if key not in seen:
                seen.add(key)
                unique.append(normalized)
        return tuple(unique)

    @staticmethod
    def _path_within_roots(path: Path, roots: Sequence[str]) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        for root in roots:
            try:
                resolved.relative_to(Path(root).expanduser().resolve())
                return True
            except (OSError, RuntimeError, ValueError):
                continue
        return False

    def _action_tool_validate(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "").strip()
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        try:
            parameters = self._tool_action_parameters(payload)
            approved_roots = self._tool_action_roots(payload, tool_id, parameters)
            validation = self.tool_runner_service.validate(
                tool_id,
                parameters,
                approved_roots=approved_roots,
            )
        except (OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
            validation = {"status": "error", "valid": False, "errors": [str(exc)], "tool_id": tool_id}
        projection = self._toolbox_projection(tool_id, validation=validation)
        status = "ok" if validation.get("status") == "ok" and validation.get("valid") else "error"
        message = str(projection.get("validation", {}).get("message") or "")
        self.record_event("tools.validated", {"tool_id": tool_id, "valid": status == "ok"})
        return FrontendActionResult(
            status,
            message,
            {
                "tool_id": tool_id,
                "validation": validation,
                "toolbox_display_projection": projection,
            },
        )

    def _action_tool_start(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "").strip()
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        try:
            parameters = self._tool_action_parameters(payload)
            approved_roots = self._tool_action_roots(payload, tool_id, parameters)
            run = self.tool_runner_service.run(
                tool_id,
                parameters,
                approved_roots=approved_roots,
            )
        except (OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
            return FrontendActionResult("error", str(exc), {"tool_id": tool_id})
        if run.get("status") == "error":
            return FrontendActionResult("error", str(run.get("message") or "tool start failed"), dict(run))
        projection = self._toolbox_projection(tool_id, record=run)
        return FrontendActionResult(
            "ok",
            str(run.get("message") or "tool queued"),
            {**dict(run), "toolbox_display_projection": projection},
        )

    def _action_tool_cancel(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            return FrontendActionResult("error", "run id is required", {"tool_id": tool_id})
        run = self.tool_runner_service.cancel(run_id)
        if run.get("status") == "error":
            return FrontendActionResult("error", str(run.get("message") or "tool cancellation failed"), dict(run))
        tool_id = str(run.get("tool_id") or tool_id)
        projection = self._toolbox_projection(tool_id, record=run)
        return FrontendActionResult(
            "ok",
            str(run.get("message") or "cancellation requested"),
            {**dict(run), "toolbox_display_projection": projection},
        )

    def _action_tool_open_result(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        run_id = str(payload.get("result_id") or payload.get("history_id") or "").strip()
        if not run_id:
            return FrontendActionResult("error", "result id is required", {"tool_id": tool_id})
        record = self.tool_runner_service.get_run(run_id)
        if not isinstance(record, Mapping):
            return FrontendActionResult("error", "tool result is unavailable", {"tool_id": tool_id, "run_id": run_id})
        if tool_id and str(record.get("tool_id") or "") != tool_id:
            return FrontendActionResult("error", "tool result does not belong to the selected tool")
        parameters = record.get("parameters") if isinstance(record.get("parameters"), Mapping) else {}
        try:
            approved_roots = self._tool_action_roots(payload, str(record.get("tool_id") or tool_id), parameters)
        except (OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
            return FrontendActionResult("error", str(exc), {"tool_id": tool_id, "run_id": run_id})
        result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
        paths = [Path(str(path)) for path in result.get("output_paths", ()) if str(path).strip()]
        path = next((candidate for candidate in paths if candidate.exists()), None)
        if path is None:
            return FrontendActionResult("error", "tool result has no available output file", {"run_id": run_id})
        if not approved_roots or not self._path_within_roots(path, approved_roots):
            return FrontendActionResult("error", "tool result path is outside approved roots", {"run_id": run_id})
        try:
            self._open_file_path(path)
        except (OSError, RuntimeError, ValueError) as exc:
            return FrontendActionResult("error", str(exc), {"run_id": run_id, "path": str(path)})
        self.record_event("tools.result_opened", {"tool_id": tool_id, "run_id": run_id})
        return FrontendActionResult("ok", "tool result opened", {"run_id": run_id, "path": str(path)})

    def _action_tool_clear_history(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        result = self.tool_runner_service.clear_history()
        projection = self._toolbox_projection(tool_id)
        return FrontendActionResult(
            "ok",
            "tool history cleared",
            {**dict(result), "tool_id": tool_id, "toolbox_display_projection": projection},
        )

    def _action_tool_reload(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        force = bool(payload.get("force", False))
        result = self.tool_runner_service.reload(force=force)
        self._static_snapshot_cache = None
        projection = self._toolbox_projection(str(payload.get("tool_id") or ""))
        return FrontendActionResult(
            "ok",
            "tool registry reloaded",
            {**dict(result), "toolbox_display_projection": projection},
        )

    def _action_run_tool(self, payload: Mapping[str, Any]) -> FrontendActionResult:
        return self._action_tool_start(payload)
