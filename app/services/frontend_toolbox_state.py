"""Toolbox runtime projections, path authorization, and actions."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.tools.builtin.link_parser import LINK_FORMAT_HINTS, normalize_link_url
from app.core.tools.contracts import ToolContext
from app.debug_logger import debug_logger
from app.services.frontend_action_result import FrontendActionResult
from shared.execution_profile import (
    DEFAULT_GUI_TOOL_OWNER_ID,
    DEFAULT_LOCAL_TOOL_PERMISSIONS,
    ExecutionProfile,
    local_execution_profile,
)


class FrontendToolboxStateMixin:
    """Keep toolbox behavior independent from the broader frontend state service."""

    _TOOL_RESULT_MAX_ROWS = 64
    _TOOL_RESULT_MAX_STRING_LENGTH = 256
    _TOOL_RESULT_MAX_TOTAL_TEXT = 16_384
    _TOOL_RESULT_MAX_WARNINGS = 16
    _TOOL_RESULT_TRUNCATION_WARNING = "Tool result display was truncated."

    _TOOL_ACTIONS = frozenset(
        {
            "tool_validate",
            "tool_start",
            "tool_cancel",
            "tool_open_result",
            "tool_clear_history",
            "tool_reload",
            "run_tool",
        }
    )
    _TOOL_RUN_DISABLED_RESULT = {
        "status": "forbidden",
        "code": "tool_run_disabled",
        "message": "tool execution is disabled for this host",
    }

    def _initialize_tool_execution_profile(
        self,
        execution_profile: ExecutionProfile | None,
        execution_profile_provider: Callable[[], ExecutionProfile] | None,
    ) -> None:
        if execution_profile is not None and execution_profile_provider is not None:
            raise ValueError(
                "execution_profile and execution_profile_provider are mutually exclusive"
            )
        self._tool_execution_profile_lock = threading.RLock()
        self._tool_execution_profile_provider_is_default = (
            execution_profile is None and execution_profile_provider is None
        )
        if execution_profile_provider is not None:
            self._tool_execution_profile_provider = execution_profile_provider
            self._tool_execution_profile_identity: tuple[str, str] | None = None
        elif execution_profile is not None:
            self._tool_execution_profile_provider = lambda: execution_profile
            self._tool_execution_profile_identity = (
                execution_profile.host_surface,
                execution_profile.owner_id,
            )
        else:
            self._tool_execution_profile_provider = self._default_tool_execution_profile
            self._tool_execution_profile_identity = None

    def _default_tool_execution_profile(self) -> ExecutionProfile:
        roots: tuple[Path, ...] = ()
        try:
            configured_root = str(self._current_save_dir() or "").strip()
        except (AttributeError, TypeError, ValueError):
            configured_root = ""
        if configured_root:
            try:
                roots = (Path(configured_root).expanduser().resolve(),)
            except (OSError, RuntimeError, ValueError):
                roots = ()
        return local_execution_profile(
            host_surface="desktop_gui",
            owner_id=DEFAULT_GUI_TOOL_OWNER_ID,
            approved_roots=roots,
            tool_permissions=DEFAULT_LOCAL_TOOL_PERMISSIONS,
            allow_external_plugins=False,
        )

    @property
    def tool_execution_profile(self) -> ExecutionProfile:
        return self._capture_tool_execution_profile()

    def _capture_tool_execution_profile(self) -> ExecutionProfile:
        with self._tool_execution_profile_lock:
            provider = self._tool_execution_profile_provider
        profile = provider()
        if not isinstance(profile, ExecutionProfile):
            raise TypeError("execution profile provider must return ExecutionProfile")
        identity = (profile.host_surface, profile.owner_id)
        with self._tool_execution_profile_lock:
            expected = self._tool_execution_profile_identity
            if expected is None:
                self._tool_execution_profile_identity = identity
            elif identity != expected:
                raise ValueError("tool execution profile identity cannot change")
        return profile

    def set_tool_execution_profile(self, profile: ExecutionProfile) -> None:
        """Bind host-owned tool authority without permitting identity swaps."""

        if not isinstance(profile, ExecutionProfile):
            raise TypeError("profile must be an ExecutionProfile")
        self.set_tool_execution_profile_provider(lambda: profile)

    def set_tool_execution_profile_provider(
        self,
        provider: Callable[[], ExecutionProfile],
    ) -> None:
        """Bind a host-owned provider while preserving one stable host identity."""

        if not callable(provider):
            raise TypeError("execution profile provider must be callable")
        candidate = provider()
        if not isinstance(candidate, ExecutionProfile):
            raise TypeError("execution profile provider must return ExecutionProfile")
        candidate_identity = (candidate.host_surface, candidate.owner_id)
        with self._tool_execution_profile_lock:
            current_identity = self._tool_execution_profile_identity
            if (
                not self._tool_execution_profile_provider_is_default
                and current_identity is not None
                and candidate_identity != current_identity
            ):
                raise ValueError("tool execution profile identity cannot change")
            self._tool_execution_profile_provider = provider
            self._tool_execution_profile_identity = candidate_identity
            self._tool_execution_profile_provider_is_default = False
        self._static_snapshot_cache = None

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

    def toolbox_items(
        self,
        *,
        execution_profile: ExecutionProfile | None = None,
    ) -> list[dict[str, Any]]:
        profile = execution_profile or self.tool_execution_profile
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
            execution_enabled = bool(profile.allow_tool_execution)
            item["actions"] = {
                "tool_validate": execution_enabled,
                "tool_start": execution_enabled,
                "tool_cancel": execution_enabled
                and bool(item.get("cancellable", item.get("supports_cancel", True))),
                "tool_open_result": False,
                "tool_clear_history": False,
            }
            items.append(item)
        return items

    def _tool_history_records(
        self,
        *,
        execution_profile: ExecutionProfile | None = None,
        tool_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        profile = execution_profile or self.tool_execution_profile
        try:
            records = self.tool_runner_service.history(
                execution_profile=profile,
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
        execution_profile: ExecutionProfile | None = None,
        items: Sequence[Mapping[str, Any]] | None = None,
        records: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        profile = execution_profile or self.tool_execution_profile
        item_snapshot = (
            list(items)
            if items is not None
            else self.toolbox_items(execution_profile=profile)
        )
        record_snapshot = (
            list(records)
            if records is not None
            else self._tool_history_records(execution_profile=profile)
        )
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

    def _tool_result_projection(
        self,
        record: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any] | None:
        result = record.get("result")
        if not isinstance(result, Mapping):
            return None

        run_id, run_id_truncated = self._bounded_tool_result_text(
            record.get("run_id")
        )
        display_text, display_truncated = self._bounded_tool_result_text(
            result.get("message") or record.get("message")
        )
        warnings, warnings_truncated = self._bounded_tool_result_warnings(
            result.get("warnings")
        )
        projection = {
            "id": run_id,
            "result_id": run_id,
            "display_text": display_text,
            "rows": [],
            "warnings": warnings,
        }
        truncated = run_id_truncated or display_truncated or warnings_truncated
        remaining_budget = (
            self._TOOL_RESULT_MAX_TOTAL_TEXT
            - len(self._TOOL_RESULT_TRUNCATION_WARNING)
            - sum(len(value) for value in (run_id, run_id, display_text, *warnings))
        )

        if (
            execution_profile.allow_tool_execution
            and str(record.get("status") or "").strip().lower() == "succeeded"
            and str(record.get("tool_id") or "").strip() == "link_parser"
            and run_id
        ):
            try:
                private_result = self.tool_runner_service.lookup_private_result(
                    run_id,
                    execution_profile=execution_profile,
                )
            except Exception as exc:
                self._log_tool_result_exception("project_tool_result_rows", exc)
                private_result = None
            if private_result is not None and private_result.tool_id == "link_parser":
                rows, rows_truncated = self._project_link_parser_rows(
                    private_result.structured_data,
                    text_budget=max(0, remaining_budget),
                )
                projection["rows"] = rows
                truncated = truncated or rows_truncated

        if truncated:
            projection["warnings"] = [
                warning
                for warning in projection["warnings"]
                if warning != self._TOOL_RESULT_TRUNCATION_WARNING
            ]
            projection["warnings"].append(self._TOOL_RESULT_TRUNCATION_WARNING)
        return projection

    def _project_link_parser_rows(
        self,
        structured_data: Mapping[str, Any],
        *,
        text_budget: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        links = (
            structured_data.get("links")
            if isinstance(structured_data, Mapping)
            else None
        )
        if not isinstance(links, Sequence) or isinstance(
            links, (str, bytes, bytearray)
        ):
            return [], False

        rows: list[dict[str, Any]] = []
        remaining_budget = max(0, int(text_budget))
        truncated = False
        for index, item in enumerate(links):
            if index >= self._TOOL_RESULT_MAX_ROWS:
                truncated = True
                break
            row, row_truncated = self._project_link_parser_row(item)
            truncated = truncated or row_truncated
            if row is None:
                continue
            row_text_size = sum(
                len(value) for value in row.values() if isinstance(value, str)
            )
            if row_text_size > remaining_budget:
                truncated = True
                break
            rows.append(row)
            remaining_budget -= row_text_size
        return rows, truncated

    def _project_link_parser_row(
        self,
        item: Any,
    ) -> tuple[dict[str, Any] | None, bool]:
        if not isinstance(item, Mapping):
            return None, False
        candidate_id = item.get("candidate_id")
        display_url = item.get("display_url")
        platform = item.get("platform")
        resource_kind = item.get("resource_kind")
        format_hint = item.get("format_hint")
        expanded = item.get("expanded")
        if (
            not self._is_safe_candidate_id(candidate_id)
            or not self._is_safe_display_url(display_url)
            or not self._is_safe_projection_text(platform)
            or not self._is_safe_projection_text(resource_kind)
            or not isinstance(format_hint, str)
            or format_hint not in LINK_FORMAT_HINTS
            or type(expanded) is not bool
        ):
            return None, False

        bounded_platform, platform_truncated = self._bounded_tool_result_text(platform)
        bounded_kind, kind_truncated = self._bounded_tool_result_text(resource_kind)
        bounded_format, format_truncated = self._bounded_tool_result_text(format_hint)
        label, label_truncated = self._bounded_tool_result_text(
            f"{bounded_platform} {bounded_kind} · {bounded_format}"
        )
        return (
            {
                "id": candidate_id,
                "candidate_id": candidate_id,
                "label": label,
                "value": display_url,
                "platform": bounded_platform,
                "resource_kind": bounded_kind,
                "format_hint": bounded_format,
                "expanded": expanded,
            },
            (
                platform_truncated
                or kind_truncated
                or format_truncated
                or label_truncated
            ),
        )

    @classmethod
    def _bounded_tool_result_text(cls, value: Any) -> tuple[str, bool]:
        text = str(value or "")
        if len(text) <= cls._TOOL_RESULT_MAX_STRING_LENGTH:
            return text, False
        return text[: cls._TOOL_RESULT_MAX_STRING_LENGTH - 3] + "...", True

    @classmethod
    def _bounded_tool_result_warnings(cls, value: Any) -> tuple[list[str], bool]:
        if not isinstance(value, (list, tuple)):
            return [], False
        warnings: list[str] = []
        truncated = len(value) > cls._TOOL_RESULT_MAX_WARNINGS
        for item in value[: cls._TOOL_RESULT_MAX_WARNINGS]:
            if item is None or type(item) in {str, int, float, bool}:
                warning, was_truncated = cls._bounded_tool_result_text(item)
                warnings.append(warning)
                truncated = truncated or was_truncated
        return warnings, truncated

    @staticmethod
    def _is_safe_candidate_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @classmethod
    def _is_safe_projection_text(cls, value: Any) -> bool:
        return (
            isinstance(value, str)
            and bool(value)
            and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        )

    @classmethod
    def _is_safe_display_url(cls, value: Any) -> bool:
        if (
            not cls._is_safe_projection_text(value)
            or len(value) > cls._TOOL_RESULT_MAX_STRING_LENGTH
            or any(character.isspace() for character in value)
        ):
            return False
        try:
            parts = urlsplit(value)
            canonical_url = normalize_link_url(value)
        except (TypeError, ValueError):
            return False
        return (
            canonical_url == value
            and not parts.query
            and not parts.fragment
            and parts.path in {"/", "/[redacted]"}
        )

    def _tool_result_has_private_output(
        self,
        record: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> bool:
        if not execution_profile.allow_tool_execution:
            return False
        run_id = str(record.get("run_id") or "").strip()
        if not run_id or not isinstance(record.get("result"), Mapping):
            return False
        try:
            private_result = self.tool_runner_service.lookup_private_result(
                run_id,
                execution_profile=execution_profile,
            )
            return bool(
                private_result is not None
                and private_result.tool_id == str(record.get("tool_id") or "")
                and private_result.output_paths
            )
        except Exception as exc:
            self._log_tool_result_exception("project_tool_result_capability", exc)
            return False

    def _toolbox_projection(
        self,
        tool_id: str = "",
        *,
        record: Mapping[str, Any] | None = None,
        validation: Mapping[str, Any] | None = None,
        execution_profile: ExecutionProfile | None = None,
        items: Sequence[Mapping[str, Any]] | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profile = execution_profile or self.tool_execution_profile
        item_snapshot = (
            list(items)
            if items is not None
            else self.toolbox_items(execution_profile=profile)
        )
        item_by_id = {str(item.get("id") or ""): item for item in item_snapshot}
        normalized_tool_id = str(tool_id or (record or {}).get("tool_id") or "")
        if not normalized_tool_id and item_snapshot:
            normalized_tool_id = str(item_snapshot[0].get("id") or "")
        if record is None and normalized_tool_id:
            latest_records = self._tool_history_records(
                execution_profile=profile,
                tool_id=normalized_tool_id,
                limit=1,
            )
            record = latest_records[0] if latest_records else None
        record = dict(record or {})
        state, status_text = self._tool_status_projection(record.get("status"))
        item = item_by_id.get(normalized_tool_id, {})
        fields = list(item.get("parameter_fields") or ())
        parameters: dict[str, Any] = {}
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
        result = self._tool_result_projection(
            record,
            execution_profile=profile,
        )
        has_private_output = bool(result) and self._tool_result_has_private_output(
            record,
            execution_profile=profile,
        )
        run_id = str(record.get("run_id") or "")
        cancellable = bool(item.get("cancellable", item.get("supports_cancel", True)))
        history_snapshot = (
            list(history)
            if history is not None
            else self.toolbox_recent_items(
                execution_profile=profile,
                items=item_snapshot,
            )
        )
        execution_enabled = bool(profile.allow_tool_execution)
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
                "tool_validate": execution_enabled
                and state not in {"starting", "running", "cancelling"},
                "tool_start": execution_enabled
                and state not in {"starting", "running", "cancelling"},
                "tool_cancel": execution_enabled
                and cancellable
                and state in {"starting", "running"},
                "tool_open_result": execution_enabled
                and has_private_output,
                "tool_clear_history": execution_enabled and bool(history_snapshot),
            },
            "action_payloads": {
                "tool_cancel": {"tool_id": normalized_tool_id, "run_id": run_id},
                "tool_open_result": {"tool_id": normalized_tool_id, "result_id": run_id},
                "tool_clear_history": {"tool_id": normalized_tool_id},
            },
        }

    def _toolbox_snapshot_parts(self) -> dict[str, Any]:
        profile = self.tool_execution_profile
        items = self.toolbox_items(execution_profile=profile)
        records = self._tool_history_records(execution_profile=profile)
        recent = self.toolbox_recent_items(
            execution_profile=profile,
            items=items,
            records=records,
        )
        selected_tool_id = str(recent[0].get("tool_id") or "") if recent else ""
        if not selected_tool_id and items:
            selected_tool_id = str(items[0].get("id") or "")
        return {
            "toolbox_items": items,
            "toolbox_recent_items": recent,
            "toolbox_display_projection": self._toolbox_projection(
                selected_tool_id,
                record=records[0] if records else None,
                execution_profile=profile,
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

    def _action_tool_validate(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "").strip()
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        try:
            parameters = self._tool_action_parameters(payload)
            validation = self.tool_runner_service.validate(
                tool_id,
                parameters,
                execution_profile=execution_profile,
            )
        except (OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
            validation = {"status": "error", "valid": False, "errors": [str(exc)], "tool_id": tool_id}
        public_validation = self._tool_validation_projection(validation)
        projection = self._toolbox_projection(
            tool_id,
            validation=public_validation,
            execution_profile=execution_profile,
        )
        status = (
            "ok"
            if public_validation.get("status") == "ok"
            and public_validation.get("valid")
            else "error"
        )
        message = str(projection.get("validation", {}).get("message") or "")
        self.record_event("tools.validated", {"tool_id": tool_id, "valid": status == "ok"})
        return FrontendActionResult(
            status,
            message,
            {
                "tool_id": tool_id,
                "validation": public_validation,
                "toolbox_display_projection": projection,
            },
        )

    def _action_tool_start(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or payload.get("id") or "").strip()
        if not tool_id:
            return FrontendActionResult("error", "tool id is required")
        try:
            parameters = self._tool_action_parameters(payload)
            run = self.tool_runner_service.run(
                tool_id,
                parameters,
                execution_profile=execution_profile,
            )
        except (OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
            return FrontendActionResult("error", str(exc), {"tool_id": tool_id})
        if self._tool_runner_response_failed(run):
            return FrontendActionResult("error", str(run.get("message") or "tool start failed"), dict(run))
        projection = self._toolbox_projection(
            tool_id,
            record=run,
            execution_profile=execution_profile,
        )
        return FrontendActionResult(
            "ok",
            str(run.get("message") or "tool queued"),
            {**dict(run), "toolbox_display_projection": projection},
        )

    def _action_tool_cancel(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            return FrontendActionResult("error", "run id is required", {"tool_id": tool_id})
        run = self.tool_runner_service.cancel(
            run_id,
            execution_profile=execution_profile,
        )
        if self._tool_runner_response_failed(run):
            return FrontendActionResult("error", str(run.get("message") or "tool cancellation failed"), dict(run))
        tool_id = str(run.get("tool_id") or tool_id)
        projection = self._toolbox_projection(
            tool_id,
            record=run,
            execution_profile=execution_profile,
        )
        return FrontendActionResult(
            "ok",
            str(run.get("message") or "cancellation requested"),
            {**dict(run), "toolbox_display_projection": projection},
        )

    def _action_tool_open_result(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        run_id = str(payload.get("result_id") or payload.get("history_id") or "").strip()
        if not run_id:
            return FrontendActionResult("error", "result id is required", {"tool_id": tool_id})
        try:
            private_result = self.tool_runner_service.lookup_private_result(
                run_id,
                execution_profile=execution_profile,
            )
        except Exception as exc:
            return self._tool_result_failure(
                "lookup_private_tool_result",
                exc,
                message="tool result is unavailable",
                run_id=run_id,
            )
        if private_result is None:
            return FrontendActionResult("error", "tool result is unavailable")
        try:
            if tool_id and private_result.tool_id != tool_id:
                return FrontendActionResult("error", "tool result is unavailable")
            paths = tuple(Path(path) for path in private_result.output_paths)
        except Exception as exc:
            return self._tool_result_failure(
                "read_private_tool_result",
                exc,
                message="tool result is unavailable",
                run_id=run_id,
            )
        if not paths:
            return FrontendActionResult("error", "tool result has no available output file", {"run_id": run_id})

        context = ToolContext(
            parameters={},
            execution_profile=execution_profile,
            provenance="builtin",
        )
        try:
            authorized_paths = tuple(context.authorize_path(path) for path in paths)
        except Exception as exc:
            return self._tool_result_failure(
                "authorize_tool_result_paths",
                exc,
                message="tool result path could not be authorized",
                run_id=run_id,
            )

        path = authorized_paths[0]
        requested_path = payload.get("result_path")
        if requested_path is not None:
            if not isinstance(requested_path, str) or not requested_path.strip():
                return FrontendActionResult(
                    "error",
                    "tool result selection is invalid",
                    {"run_id": run_id},
                )
            try:
                requested = Path(requested_path).expanduser().resolve()
                stored_paths = {candidate.resolve(): candidate for candidate in authorized_paths}
            except Exception as exc:
                return self._tool_result_failure(
                    "resolve_tool_result_selection",
                    exc,
                    message="tool result path could not be authorized",
                    run_id=run_id,
                )
            path = stored_paths.get(requested)
            if path is None:
                return FrontendActionResult(
                    "error",
                    "tool result selection is unavailable",
                    {"run_id": run_id},
                )
        elif "result_index" in payload:
            index = payload.get("result_index")
            if type(index) is not int or not 0 <= index < len(authorized_paths):
                return FrontendActionResult(
                    "error",
                    "tool result selection is invalid",
                    {"run_id": run_id},
                )
            path = authorized_paths[index]
        try:
            path_is_file = path.exists() and path.is_file()
        except Exception as exc:
            return self._tool_result_failure(
                "inspect_tool_result_path",
                exc,
                message="tool result is unavailable",
                run_id=run_id,
            )
        if not path_is_file:
            return FrontendActionResult("error", "tool result has no available output file", {"run_id": run_id})
        try:
            self._open_file_path(path)
        except Exception as exc:
            return self._tool_result_failure(
                "open_tool_result",
                exc,
                message="tool result could not be opened",
                run_id=run_id,
            )
        self.record_event("tools.result_opened", {"tool_id": tool_id, "run_id": run_id})
        return FrontendActionResult("ok", "tool result opened", {"run_id": run_id})

    @staticmethod
    def _log_tool_result_exception(action: str, exc: Exception) -> None:
        try:
            debug_logger.log_exception("FrontendStateService", action, exc)
        except BaseException:
            # Diagnostics are best-effort and must never replace the stable UI response.
            return

    def _tool_result_failure(
        self,
        action: str,
        exc: Exception,
        *,
        message: str,
        run_id: str,
    ) -> FrontendActionResult:
        self._log_tool_result_exception(action, exc)
        return FrontendActionResult("error", message, {"run_id": run_id})

    @staticmethod
    def _tool_runner_response_failed(response: Mapping[str, Any]) -> bool:
        return str(response.get("status") or "").strip().lower() in {
            "error",
            "forbidden",
            "busy",
            "timeout",
        }

    @staticmethod
    def _tool_validation_projection(
        validation: Mapping[str, Any],
    ) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for key in ("status", "valid", "tool_id", "code", "message"):
            value = validation.get(key)
            if key in validation and (
                value is None or type(value) in {str, int, float, bool}
            ):
                projected[key] = value
        for key in ("errors", "warnings"):
            values = validation.get(key)
            if isinstance(values, (list, tuple)):
                projected[key] = [
                    value
                    for value in values
                    if value is None or type(value) in {str, int, float, bool}
                ]
        return projected

    def _action_tool_clear_history(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        tool_id = str(payload.get("tool_id") or "").strip()
        result = self.tool_runner_service.clear_history(
            execution_profile=execution_profile,
        )
        if self._tool_runner_response_failed(result):
            return FrontendActionResult(
                "error",
                str(result.get("message") or "tool history clear failed"),
                dict(result),
            )
        projection = self._toolbox_projection(
            tool_id,
            execution_profile=execution_profile,
        )
        return FrontendActionResult(
            "ok",
            "tool history cleared",
            {**dict(result), "tool_id": tool_id, "toolbox_display_projection": projection},
        )

    def _action_tool_reload(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        force = bool(payload.get("force", False))
        result = self.tool_runner_service.reload(
            force=force,
            execution_profile=execution_profile,
        )
        if self._tool_runner_response_failed(result):
            return FrontendActionResult(
                "error",
                str(result.get("message") or "tool registry reload failed"),
                dict(result),
            )
        self._static_snapshot_cache = None
        projection = self._toolbox_projection(
            str(payload.get("tool_id") or ""),
            execution_profile=execution_profile,
        )
        return FrontendActionResult(
            "ok",
            "tool registry reloaded",
            {**dict(result), "toolbox_display_projection": projection},
        )

    def _action_run_tool(
        self,
        payload: Mapping[str, Any],
        *,
        execution_profile: ExecutionProfile,
    ) -> FrontendActionResult:
        return self._action_tool_start(
            payload,
            execution_profile=execution_profile,
        )
