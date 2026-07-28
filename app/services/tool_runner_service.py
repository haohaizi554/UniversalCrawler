"""Bounded asynchronous runtime for built-in and hot-loaded tools."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.tools.contracts import (
    CancellationToken,
    ToolCancelledError,
    ToolContext,
    ToolDescriptor,
    ToolGrant,
    ToolGrantEvaluator,
    ToolRequirements,
    ToolRunResult,
    ToolRunStatus,
    ToolValidationResult,
)
from app.core.tools.registry import ToolRegistry
from app.debug_logger import debug_logger
from app.services.tool_history_projection import project_history_record
from app.utils.runtime_paths import user_cache_root, user_data_root
from shared.execution_profile import ExecutionProfile

ToolEventCallback = Callable[[str, dict[str, Any]], None]


@dataclass(slots=True)
class _RunRecord:
    run_id: str
    tool_id: str
    status: ToolRunStatus
    parameters: dict[str, Any]
    host_surface: str = ""
    owner_id: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: int = 0
    message: str = ""
    progress_details: dict[str, Any] = field(default_factory=dict)
    result: ToolRunResult | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "tool_id": self.tool_id,
            "host_surface": self.host_surface,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "parameters": _json_value(self.parameters),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "message": self.message,
            "progress_details": _json_value(self.progress_details),
        }
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        return payload

    def to_public_dict(self) -> dict[str, Any]:
        return project_history_record(self.to_dict())


class ToolRunnerService:
    """Runs tools outside frontend threads with cancellation and durable history."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        history_path: str | os.PathLike[str] | None = None,
        external_tool_dir: str | os.PathLike[str] | None = None,
        max_workers: int = 2,
        history_limit: int = 200,
        event_callback: ToolEventCallback | None = None,
        settings_provider: Callable[[], Mapping[str, Any]] | None = None,
        services: Mapping[str, Any] | None = None,
    ) -> None:
        default_external_dir = Path(user_data_root()) / "tools"
        self.registry = registry or ToolRegistry(
            external_dir=external_tool_dir or default_external_dir,
        )
        self.history_path = Path(history_path or (Path(user_cache_root()) / "tool_history.json"))
        self.history_limit = max(10, int(history_limit))
        self._event_callback = event_callback
        self._settings_provider = settings_provider
        self._services = dict(services or {})
        self._lock = threading.RLock()
        self._history_write_lock = threading.Lock()
        self._records: dict[str, _RunRecord] = {}
        self._order: list[str] = []
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._closed = False
        self._persist_generation = 0
        self._persist_running = False
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="tool-runner",
        )
        self._io_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool-history")
        self._history_loaded = threading.Event()
        self._io_executor.submit(self._load_history)

    # Public SDK/CLI contract.

    def list(self) -> list[dict[str, Any]]:
        return self.registry.manifests()

    def describe(self, tool_id: str) -> dict[str, Any]:
        tool = self.registry.get(tool_id)
        if tool is None:
            return {"status": "error", "message": "unknown tool", "tool_id": str(tool_id or "")}
        return tool.manifest.to_dict()

    def validate(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        descriptor = self.registry.descriptor(tool_id)
        if descriptor is None:
            return {"status": "error", "valid": False, "errors": ["unknown tool"], "tool_id": tool_id}
        return self._validate_descriptor(
            descriptor,
            dict(params or {}),
            execution_profile,
        )

    def _validate_descriptor(
        self,
        descriptor: ToolDescriptor,
        parameters: dict[str, Any],
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        tool = descriptor.tool
        try:
            grant = self._evaluate_grant(descriptor, parameters, execution_profile)
        except Exception as exc:
            debug_logger.log_exception("ToolRunnerService", "requirements", exc)
            return {
                "status": "error",
                "valid": False,
                "errors": [str(exc)],
                "tool_id": tool.manifest.id,
            }
        if not grant.allowed:
            return _forbidden_payload(tool.manifest.id, grant)
        context = self._make_context(
            tool_id=tool.manifest.id,
            run_id="",
            parameters=parameters,
            execution_profile=execution_profile,
            provenance=descriptor.provenance,
            cancellation=CancellationToken(),
        )
        try:
            validation = _normalize_validation(tool.validate(context), context.parameters)
        except Exception as exc:
            debug_logger.log_exception("ToolRunnerService", "validate", exc)
            validation = ToolValidationResult.rejected(str(exc))
        payload = validation.to_dict()
        payload["tool_id"] = tool.manifest.id
        return payload

    def run(
        self,
        tool_id: str,
        params: Mapping[str, Any] | None,
        *,
        execution_profile: ExecutionProfile,
    ) -> dict[str, Any]:
        if self._closed:
            return {"status": "error", "message": "tool runner is shut down"}
        descriptor = self.registry.descriptor(tool_id)
        if descriptor is None:
            return {"status": "error", "message": "unknown tool", "tool_id": str(tool_id or "")}
        tool = descriptor.tool
        validation = self._validate_descriptor(
            descriptor,
            dict(params or {}),
            execution_profile,
        )
        if validation.get("status") != "ok":
            return validation
        normalized_parameters = dict(validation.get("parameters") or params or {})
        try:
            grant = self._evaluate_grant(
                descriptor,
                normalized_parameters,
                execution_profile,
            )
        except Exception as exc:
            debug_logger.log_exception("ToolRunnerService", "requirements.normalized", exc)
            return {
                "status": "error",
                "message": str(exc),
                "tool_id": tool.manifest.id,
            }
        if not grant.allowed:
            return _forbidden_payload(tool.manifest.id, grant)
        run_id = f"tool_{uuid.uuid4().hex}"
        token = CancellationToken()
        record = _RunRecord(
            run_id,
            tool.manifest.id,
            ToolRunStatus.QUEUED,
            _redact_parameters(normalized_parameters),
            host_surface=execution_profile.host_surface,
            owner_id=execution_profile.owner_id,
        )
        with self._lock:
            self._records[run_id] = record
            self._order.append(run_id)
            self._trim_history_locked()
            self._tokens[run_id] = token
            queued_payload = record.to_public_dict()
            future = self._executor.submit(
                self._execute,
                run_id,
                tool,
                normalized_parameters,
                execution_profile,
                descriptor.provenance,
                token,
            )
            self._futures[run_id] = future
        self._emit("tools.queued", queued_payload)
        self._schedule_persist()
        return queued_payload

    @staticmethod
    def _evaluate_grant(
        descriptor: ToolDescriptor,
        parameters: Mapping[str, Any],
        execution_profile: ExecutionProfile,
    ) -> ToolGrant:
        declared_permissions = frozenset(descriptor.tool.manifest.permissions)
        preliminary = ToolGrantEvaluator.evaluate(
            requirements=ToolRequirements(),
            declared_permissions=declared_permissions,
            provenance=descriptor.provenance,
            execution_profile=execution_profile,
        )
        if not preliminary.allowed:
            return preliminary
        requirements = descriptor.tool.requirements_for(dict(parameters))
        if not isinstance(requirements, ToolRequirements):
            raise TypeError("requirements_for() must return ToolRequirements")
        return ToolGrantEvaluator.evaluate(
            requirements=requirements,
            declared_permissions=declared_permissions,
            provenance=descriptor.provenance,
            execution_profile=execution_profile,
        )

    def cancel(self, run_id: str) -> dict[str, Any]:
        normalized = str(run_id or "").strip()
        with self._lock:
            record = self._records.get(normalized)
            token = self._tokens.get(normalized)
            future = self._futures.get(normalized)
            if record is None:
                return {"status": "error", "message": "unknown tool run", "run_id": normalized}
            if record.status in {ToolRunStatus.SUCCEEDED, ToolRunStatus.FAILED, ToolRunStatus.CANCELLED}:
                return record.to_public_dict()
            if token is not None:
                token.cancel()
            record.status = ToolRunStatus.CANCELLING
            record.message = "cancellation requested"
            cancelled_before_start = bool(future and future.cancel())
            if cancelled_before_start:
                record.status = ToolRunStatus.CANCELLED
                record.finished_at = time.time()
                record.result = ToolRunResult.cancelled()
                self._tokens.pop(normalized, None)
                self._futures.pop(normalized, None)
            payload = record.to_public_dict()
        self._emit("tools.cancelled" if cancelled_before_start else "tools.cancelling", payload)
        self._schedule_persist()
        return payload

    def history(
        self,
        *,
        tool_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_status = str(status or "").strip().lower()
        normalized_tool = str(tool_id or "").strip().lower()
        row_limit = max(1, min(self.history_limit, int(limit or self.history_limit)))
        with self._lock:
            rows = [
                self._records[run_id].to_public_dict()
                for run_id in reversed(self._order)
                if run_id in self._records
            ]
        if normalized_tool:
            rows = [row for row in rows if row.get("tool_id") == normalized_tool]
        if normalized_status:
            rows = [row for row in rows if row.get("status") == normalized_status]
        return rows[:row_limit]

    # Additional application-runtime operations.

    def reload(self, *, force: bool = False) -> dict[str, list[str]]:
        result = self.registry.reload_external(force=force).to_dict()
        self._emit("tools.reloaded", result)
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(str(run_id or ""))
            return record.to_public_dict() if record is not None else None

    def snapshot(self, *, history_limit: int = 20) -> dict[str, Any]:
        return {
            "toolbox_items": self.list(),
            "toolbox_recent_items": self.history(limit=history_limit),
        }

    def clear_history(self) -> dict[str, Any]:
        with self._lock:
            active = set(self._futures)
            removed = [run_id for run_id in self._order if run_id not in active]
            for run_id in removed:
                self._records.pop(run_id, None)
            self._order = [run_id for run_id in self._order if run_id in active]
        self._schedule_persist()
        payload = {"status": "ok", "removed": len(removed)}
        self._emit("tools.history_cleared", payload)
        return payload

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while True:
            with self._lock:
                futures = tuple(self._futures.values())
            if not futures:
                return True
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            _, pending = wait(futures, timeout=remaining)
            if pending and deadline is not None and time.monotonic() >= deadline:
                return False

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> bool:
        """Cancel active runs, wait within the caller budget, and durably flush history."""

        with self._lock:
            if self._closed:
                return not self._futures
            self._closed = True
            active_run_ids = tuple(self._futures)
        for run_id in active_run_ids:
            self.cancel(run_id)

        with self._lock:
            drained = not self._futures
        if wait and not drained:
            drained = self.wait_for_idle(timeout=timeout)
        self._executor.shutdown(wait=bool(wait and drained), cancel_futures=True)

        # Drain already queued writes first, then write one authoritative final snapshot.
        # This prevents an older asynchronous snapshot from overwriting shutdown state.
        self._io_executor.shutdown(wait=True, cancel_futures=False)
        self._persist_history_now()
        if not drained:
            debug_logger.log(
                component="ToolRunnerService",
                action="shutdown_timeout",
                level="WARN",
                message="Tool runtime exceeded the bounded shutdown window",
                status_code="TOOL_SHUTDOWN_TIMEOUT",
                details={"active_run_ids": list(active_run_ids), "timeout": timeout},
            )
        return drained

    def _execute(
        self,
        run_id: str,
        tool: Any,
        parameters: dict[str, Any],
        execution_profile: ExecutionProfile,
        provenance: str,
        token: CancellationToken,
    ) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return
            if token.is_cancelled():
                record.status = ToolRunStatus.CANCELLED
                record.result = ToolRunResult.cancelled()
                record.finished_at = time.time()
                self._finish_run_locked(run_id)
                return
            record.status = ToolRunStatus.RUNNING
            record.started_at = time.time()
            record.message = "tool run started"
            running_payload = record.to_public_dict()
        self._emit("tools.running", running_payload)
        context = self._make_context(
            tool_id=tool.manifest.id,
            run_id=run_id,
            parameters=parameters,
            execution_profile=execution_profile,
            provenance=provenance,
            cancellation=token,
        )
        try:
            token.raise_if_cancelled()
            result = _normalize_result(tool.run(context))
            token.raise_if_cancelled()
        except ToolCancelledError as exc:
            result = ToolRunResult.cancelled(str(exc))
        except Exception as exc:
            debug_logger.log_exception("ToolRunnerService", f"run.{tool.manifest.id}", exc)
            result = ToolRunResult.failure(str(exc))
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return
            result_status = _coerce_run_status(result.status)
            record.status = result_status
            record.result = result
            record.message = result.message
            record.progress = 100 if result_status == ToolRunStatus.SUCCEEDED else record.progress
            record.finished_at = time.time()
            completed_payload = record.to_public_dict()
            self._finish_run_locked(run_id)
        self._emit("tools.finished", completed_payload)
        self._schedule_persist()

    def _make_context(
        self,
        *,
        tool_id: str,
        run_id: str,
        parameters: dict[str, Any],
        execution_profile: ExecutionProfile,
        provenance: str,
        cancellation: CancellationToken,
    ) -> ToolContext:
        settings: Mapping[str, Any] = {}
        if self._settings_provider is not None:
            try:
                settings = dict(self._settings_provider() or {})
            except Exception as exc:
                debug_logger.log_exception("ToolRunnerService", "settings_provider", exc)
        return ToolContext(
            parameters=dict(parameters),
            run_id=run_id,
            execution_profile=execution_profile,
            provenance=provenance,
            settings=settings,
            services=self._services,
            cancellation=cancellation,
            progress_callback=lambda percent, message, details: self._on_progress(
                run_id,
                percent,
                message,
                details,
            ),
        )

    def _on_progress(
        self,
        run_id: str,
        percent: int,
        message: str,
        details: Mapping[str, Any],
    ) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None or record.status not in {ToolRunStatus.RUNNING, ToolRunStatus.CANCELLING}:
                return
            record.progress = max(record.progress, max(0, min(100, int(percent))))
            if message:
                record.message = str(message)
            record.progress_details = dict(details or {})
            payload = record.to_public_dict()
        self._emit("tools.progress", payload)

    def _finish_run_locked(self, run_id: str) -> None:
        self._tokens.pop(run_id, None)
        self._futures.pop(run_id, None)

    def _trim_history_locked(self) -> None:
        while len(self._order) > self.history_limit:
            candidate = self._order[0]
            if candidate in self._futures:
                break
            self._order.pop(0)
            self._records.pop(candidate, None)

    def _emit(self, topic: str, payload: Mapping[str, Any]) -> None:
        callback = self._event_callback
        if callback is None:
            return
        try:
            callback(str(topic), dict(payload))
        except Exception as exc:
            debug_logger.log_exception("ToolRunnerService", "event_callback", exc)

    def _load_history(self) -> None:
        try:
            if not self.history_path.is_file():
                return
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return
            loaded: dict[str, _RunRecord] = {}
            order: list[str] = []
            for item in raw[-self.history_limit :]:
                record = _record_from_dict(item)
                if record is None:
                    continue
                loaded[record.run_id] = record
                order.append(record.run_id)
            with self._lock:
                for run_id in order:
                    if run_id not in self._records:
                        self._records[run_id] = loaded[run_id]
                        self._order.insert(0, run_id)
                self._trim_history_locked()
        except (OSError, ValueError, TypeError) as exc:
            debug_logger.log_exception("ToolRunnerService", "load_history", exc)
        finally:
            self._history_loaded.set()

    def _schedule_persist(self) -> None:
        with self._lock:
            self._persist_generation += 1
            if self._persist_running:
                return
            self._persist_running = True
        try:
            self._io_executor.submit(self._persist_loop)
        except RuntimeError:
            with self._lock:
                self._persist_running = False

    def _persist_loop(self) -> None:
        while True:
            with self._lock:
                generation = self._persist_generation
                snapshot = [
                    self._records[run_id].to_public_dict()
                    for run_id in self._order
                    if run_id in self._records
                ]
            try:
                with self._history_write_lock:
                    _atomic_write_json(self.history_path, snapshot)
            except OSError as exc:
                debug_logger.log_exception("ToolRunnerService", "persist_history", exc)
            with self._lock:
                if generation == self._persist_generation:
                    self._persist_running = False
                    return

    def _persist_history_now(self) -> None:
        with self._lock:
            snapshot = [
                self._records[run_id].to_public_dict()
                for run_id in self._order
                if run_id in self._records
            ]
        try:
            with self._history_write_lock:
                _atomic_write_json(self.history_path, snapshot)
        except OSError as exc:
            debug_logger.log_exception("ToolRunnerService", "persist_history.shutdown", exc)


def _normalize_validation(value: Any, parameters: Mapping[str, Any]) -> ToolValidationResult:
    if isinstance(value, ToolValidationResult):
        if value.parameters:
            return value
        return ToolValidationResult(value.valid, value.errors, value.warnings, dict(parameters))
    if isinstance(value, ToolRunResult):
        valid = _coerce_run_status(value.status) != ToolRunStatus.FAILED
        return ToolValidationResult(valid, () if valid else (value.message,), value.warnings, dict(parameters))
    if value is None or value is True:
        return ToolValidationResult.ok(parameters=parameters)
    if value is False:
        return ToolValidationResult.rejected("tool input is invalid")
    if isinstance(value, str):
        return ToolValidationResult.rejected(value)
    if isinstance(value, Mapping):
        errors = tuple(str(item) for item in value.get("errors", ()) if str(item).strip())
        warnings = tuple(str(item) for item in value.get("warnings", ()) if str(item).strip())
        normalized = value.get("parameters")
        return ToolValidationResult(
            not errors and bool(value.get("valid", True)),
            errors,
            warnings,
            dict(normalized) if isinstance(normalized, Mapping) else dict(parameters),
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        errors = tuple(str(item) for item in value if str(item).strip())
        return ToolValidationResult(not errors, errors, (), dict(parameters))
    return ToolValidationResult.rejected("unsupported validation result")


def _normalize_result(value: Any) -> ToolRunResult:
    if isinstance(value, ToolRunResult):
        return value
    if value is None:
        return ToolRunResult.success("tool run completed")
    if isinstance(value, Mapping):
        status = str(value.get("status") or "succeeded").strip().lower()
        if status in {"error", "failed", ToolRunStatus.FAILED.value}:
            return ToolRunResult.failure(str(value.get("message") or "tool run failed"), data=dict(value.get("data") or {}))
        if status in {"cancelled", "canceled"}:
            return ToolRunResult.cancelled(str(value.get("message") or "tool run cancelled"))
        return ToolRunResult.success(
            str(value.get("message") or "tool run completed"),
            data=dict(value.get("data") or value),
            output_paths=tuple(str(path) for path in value.get("output_paths", ()) or ()),
            warnings=tuple(str(item) for item in value.get("warnings", ()) or ()),
        )
    return ToolRunResult.success("tool run completed", data={"value": _json_value(value)})


def _record_from_dict(value: Any) -> _RunRecord | None:
    if not isinstance(value, Mapping):
        return None
    try:
        status = _coerce_run_status(value.get("status"))
        if status in {ToolRunStatus.QUEUED, ToolRunStatus.RUNNING, ToolRunStatus.CANCELLING}:
            status = ToolRunStatus.FAILED
        record = _RunRecord(
            run_id=str(value["run_id"]),
            tool_id=str(value["tool_id"]),
            status=status,
            parameters=dict(value.get("parameters") or {}),
            host_surface=str(value.get("host_surface") or ""),
            owner_id=str(value.get("owner_id") or ""),
            created_at=float(value.get("created_at") or time.time()),
            started_at=float(value["started_at"]) if value.get("started_at") is not None else None,
            finished_at=float(value["finished_at"]) if value.get("finished_at") is not None else None,
            progress=int(value.get("progress") or 0),
            message=str(value.get("message") or ""),
            progress_details=dict(value.get("progress_details") or {}),
        )
        result = value.get("result")
        if isinstance(result, Mapping):
            result_status = _coerce_run_status(result.get("status") or status.value)
            record.result = ToolRunResult(
                result_status,
                str(result.get("message") or ""),
                dict(result.get("data") or {}),
                tuple(str(path) for path in result.get("output_paths", ()) or ()),
                tuple(str(item) for item in result.get("warnings", ()) or ()),
            )
        return record
    except (KeyError, TypeError, ValueError):
        return None


def _forbidden_payload(tool_id: str, grant: ToolGrant) -> dict[str, Any]:
    return {
        "status": "forbidden",
        "code": grant.code,
        "message": grant.message,
        "tool_id": str(tool_id),
    }


def _redact_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    sensitive = ("token", "secret", "password", "cookie", "authorization", "proxy_auth")
    result: dict[str, Any] = {}
    for key, value in parameters.items():
        normalized = str(key).casefold()
        result[str(key)] = "[redacted]" if any(marker in normalized for marker in sensitive) else _json_value(value)
    return result


def _coerce_run_status(value: Any) -> ToolRunStatus:
    normalized = str(value or "").strip().lower()
    aliases = {
        "ok": ToolRunStatus.SUCCEEDED,
        "success": ToolRunStatus.SUCCEEDED,
        "error": ToolRunStatus.FAILED,
        "canceled": ToolRunStatus.CANCELLED,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return ToolRunStatus(normalized)
    except ValueError:
        return ToolRunStatus.FAILED


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


__all__ = ["ToolRunnerService"]
