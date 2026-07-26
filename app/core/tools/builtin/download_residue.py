"""Read-only download residue diagnostics with an explicit, bounded cleanup mode."""

from __future__ import annotations

import os
import inspect
import shutil
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.tools.contracts import ToolContext, ToolManifest, ToolRunResult
from app.utils import runtime_paths


_MAX_DEPTH = 2
_CLEANUP_MARKER = ".ucp-residue-cleanup-"


_PARAMETERS = {
    "roots": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Directories to inspect; defaults to approved workspace roots.",
    },
    "ledger_path": {
        "type": "string",
        "description": "Optional download recovery SQLite ledger path.",
    },
    "max_depth": {
        "type": "integer",
        "minimum": 0,
        "maximum": _MAX_DEPTH,
        "default": _MAX_DEPTH,
    },
    "cleanup": {
        "type": "boolean",
        "default": False,
        "description": "Explicitly remove diagnosed residues and matching ledger records.",
    },
}
_INPUT_SCHEMA = {
    "type": "object",
    "properties": _PARAMETERS,
    "additionalProperties": False,
}


def _construct_contract(contract_type: type, values: Mapping[str, Any]):
    try:
        parameters = inspect.signature(contract_type).parameters.values()
    except (TypeError, ValueError):
        return contract_type(**dict(values))

    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for parameter in parameters:
        if parameter.name in {"self", "args", "kwargs"}:
            continue
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            continue
        if parameter.name in values:
            kwargs[parameter.name] = values[parameter.name]
        elif parameter.default is parameter.empty:
            missing.append(parameter.name)
    if missing:
        names = ", ".join(missing)
        raise TypeError(f"Unsupported {contract_type.__name__} contract fields: {names}")
    return contract_type(**kwargs)


def _build_manifest() -> ToolManifest:
    title = "Download residue diagnostics"
    summary = "Find bounded HLS workspaces and unresolved download recovery records."
    return _construct_contract(
        ToolManifest,
        {
            "id": "download_residue",
            "tool_id": "download_residue",
            "name": title,
            "title": title,
            "description": summary,
            "summary": summary,
            "category": "diagnostics",
            "version": "1.0",
            "parameters": _PARAMETERS,
            "input_schema": _INPUT_SCHEMA,
            "schema": _INPUT_SCHEMA,
            "mutates_files": True,
            "read_only": False,
            "destructive": True,
            "safety_level": "explicit_mutation",
            "execution_mode": "worker",
            "run_in_worker": True,
            "background": True,
            "supports_cancel": True,
            "cancellable": True,
        },
    )


manifest = _build_manifest()


@dataclass(frozen=True)
class _Artifact:
    path: Path
    kind: str
    root: Path
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "root": str(self.root),
            "depth": self.depth,
        }


@dataclass(frozen=True)
class _LedgerRecord:
    state: str
    save_directory: str
    key: str
    generation: str

    def to_dict(self) -> dict[str, str]:
        data = {"state": self.state, "save_directory": self.save_directory}
        if self.state == "active":
            data["video_id"] = self.key
        return data


@dataclass(frozen=True)
class _FrontierRecord:
    root: str
    path: str
    depth: int


@dataclass(frozen=True)
class _LedgerSnapshot:
    path: Path
    present: bool
    records: tuple[_LedgerRecord, ...] = ()
    frontier: tuple[_FrontierRecord, ...] = ()
    error: str = ""

    @property
    def counts(self) -> dict[str, int]:
        return {
            "active": sum(record.state == "active" for record in self.records),
            "pending_cleanup": sum(
                record.state == "pending_cleanup" for record in self.records
            ),
            "legacy_frontier": len(self.frontier),
        }

    def to_dict(self) -> dict[str, Any]:
        files = []
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
        ):
            try:
                if candidate.is_file():
                    files.append({"path": str(candidate), "size_bytes": candidate.stat().st_size})
            except OSError:
                continue
        return {
            "path": str(self.path),
            "present": self.present,
            "counts": self.counts,
            "records": [record.to_dict() for record in self.records],
            "files": files,
            "error": self.error,
        }


class _Cancelled(RuntimeError):
    pass


def _parameters(context: ToolContext) -> Mapping[str, Any]:
    for name in (
        "parameters",
        "inputs",
        "input",
        "arguments",
        "params",
        "options",
        "data",
        "payload",
    ):
        value = getattr(context, name, None)
        if isinstance(value, Mapping):
            return value
    if isinstance(context, Mapping):
        return context
    return {}


def _workspace_root(context: ToolContext) -> Path:
    raw_root = getattr(context, "workspace_root", Path.cwd())
    return Path(raw_root).expanduser().resolve(strict=False)


def _resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def _absolute_without_resolving(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return Path(os.path.abspath(path))


def _raw_roots(context: ToolContext) -> Sequence[object]:
    raw = _parameters(context).get("roots")
    if raw is None:
        for name in ("approved_roots", "allowed_paths", "authorized_roots"):
            approved = getattr(context, name, ())
            if isinstance(approved, (str, os.PathLike)):
                return (approved,)
            if isinstance(approved, Sequence) and approved:
                return approved
        return (_workspace_root(context),)
    if isinstance(raw, (str, os.PathLike)):
        return (raw,)
    if isinstance(raw, Sequence):
        return raw
    return ()


def _roots(context: ToolContext) -> tuple[Path, ...]:
    base = _workspace_root(context)
    roots: list[Path] = []
    seen: set[str] = set()
    for raw_root in _raw_roots(context):
        if not isinstance(raw_root, (str, os.PathLike)):
            continue
        try:
            root = _resolve_path(raw_root, base=base)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        normalized = os.path.normcase(str(root))
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(root)
    return tuple(roots)


def _ledger_path(context: ToolContext) -> Path:
    raw_path = _parameters(context).get("ledger_path")
    if raw_path is None:
        override = os.environ.get(runtime_paths.USER_DATA_ROOT_ENV, "").strip()
        if override:
            data_root = Path(override).expanduser()
        elif runtime_paths.is_development_runtime():
            data_root = runtime_paths.project_root() / "user_data"
        else:
            data_root = runtime_paths.local_appdata_root() / runtime_paths.APP_DIR_NAME
        return (data_root / "cache" / "download_recovery.sqlite3").resolve(strict=False)
    return _resolve_path(raw_path, base=_workspace_root(context))


def _max_depth(context: ToolContext) -> int:
    value = _parameters(context).get("max_depth", _MAX_DEPTH)
    if isinstance(value, bool) or not isinstance(value, int):
        return _MAX_DEPTH
    return value


def _is_cleanup(context: ToolContext) -> bool:
    return _parameters(context).get("cleanup", False) is True


def _is_cancelled(context: ToolContext) -> bool:
    callback = getattr(context, "is_cancelled", None)
    if callable(callback):
        try:
            if callback():
                return True
        except TypeError:
            pass
    event = getattr(context, "cancel_event", None)
    is_set = getattr(event, "is_set", None)
    if callable(is_set) and is_set():
        return True
    value = getattr(context, "cancelled", False)
    return bool(value() if callable(value) else value)


def _raise_if_cancelled(context: ToolContext) -> None:
    if _is_cancelled(context):
        raise _Cancelled("download residue operation was cancelled")


def _within(path: Path, root: Path) -> bool:
    try:
        normalized_path = os.path.normcase(os.path.abspath(path))
        normalized_root = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath((normalized_path, normalized_root)) == normalized_root
    except (OSError, TypeError, ValueError):
        return False


def _allowed_roots(context: ToolContext) -> tuple[Path, ...]:
    raw_allowed: object = ()
    found_authorization_field = False
    for name in ("approved_roots", "allowed_paths", "authorized_roots"):
        if hasattr(context, name):
            found_authorization_field = True
            raw_allowed = getattr(context, name, ()) or ()
            if raw_allowed:
                break
    if not raw_allowed and not found_authorization_field and hasattr(
        context, "workspace_root"
    ):
        raw_allowed = (_workspace_root(context),)
    if isinstance(raw_allowed, (str, os.PathLike)):
        raw_allowed = (raw_allowed,)
    allowed: list[Path] = []
    for raw_path in raw_allowed:
        try:
            allowed.append(_resolve_path(raw_path, base=_workspace_root(context)))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return tuple(allowed)


def _is_authorized(context: ToolContext, path: Path) -> bool:
    authorizer = getattr(context, "is_path_allowed", None)
    if callable(authorizer):
        try:
            return bool(authorizer(path))
        except TypeError:
            return bool(authorizer(str(path)))
    if getattr(context, "path_authorizer", None) is not None:
        shared_authorizer = getattr(context, "authorize_path", None)
        if callable(shared_authorizer):
            try:
                authorized = Path(shared_authorizer(path)).expanduser().resolve(
                    strict=False
                )
            except (OSError, PermissionError, RuntimeError, TypeError, ValueError):
                return False
            return authorized == path.resolve(strict=False)
    return any(_within(path, allowed) for allowed in _allowed_roots(context))


def validate(context: ToolContext) -> list[str]:
    errors: list[str] = []
    raw_parameters = _parameters(context)

    raw_roots = raw_parameters.get("roots")
    if raw_roots is not None:
        if isinstance(raw_roots, (str, os.PathLike)):
            values: Sequence[object] = (raw_roots,)
        elif isinstance(raw_roots, Sequence):
            values = raw_roots
        else:
            values = ()
            errors.append("roots must be a path or a sequence of paths")
        if not values:
            errors.append("roots must not be empty")
        if any(not isinstance(value, (str, os.PathLike)) for value in values):
            errors.append("roots entries must be paths")

    raw_depth = raw_parameters.get("max_depth", _MAX_DEPTH)
    if (
        isinstance(raw_depth, bool)
        or not isinstance(raw_depth, int)
        or not 0 <= raw_depth <= _MAX_DEPTH
    ):
        errors.append(f"max_depth must be an integer between 0 and {_MAX_DEPTH}")

    raw_cleanup = raw_parameters.get("cleanup", False)
    if not isinstance(raw_cleanup, bool):
        errors.append("cleanup must be a boolean")

    raw_ledger = raw_parameters.get("ledger_path")
    if raw_ledger is not None and not isinstance(raw_ledger, (str, os.PathLike)):
        errors.append("ledger_path must be a path")

    if raw_cleanup is True:
        for raw_root in _raw_roots(context):
            if not isinstance(raw_root, (str, os.PathLike)):
                continue
            try:
                lexical_root = _absolute_without_resolving(
                    raw_root,
                    base=_workspace_root(context),
                )
                if lexical_root.is_symlink():
                    errors.append(f"cleanup root must not be a symlink: {lexical_root}")
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
        for root in _roots(context):
            if root == Path(root.anchor):
                errors.append(f"cleanup root is too broad: {root}")
            if not _is_authorized(context, root):
                errors.append(f"cleanup root is not authorized: {root}")
            try:
                if root.is_symlink():
                    errors.append(f"cleanup root must not be a symlink: {root}")
            except OSError:
                errors.append(f"cleanup root could not be inspected: {root}")
        if raw_ledger is not None:
            try:
                ledger = _ledger_path(context)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                errors.append(f"ledger_path is invalid: {exc}")
            else:
                if not _is_authorized(context, ledger):
                    errors.append(f"ledger_path is not authorized: {ledger}")

    return list(dict.fromkeys(errors))


def _artifact_kind(name: str) -> str | None:
    lowered = name.lower()
    if lowered == ".ucp-nm3u8-tmp":
        return "nm3u8_temp_root"
    if lowered.endswith("_curl_cffi_hls"):
        return "curl_cffi_hls"
    if lowered.endswith("_playwright_hls"):
        return "playwright_hls"
    return None


def _scan_root(
    context: ToolContext,
    root: Path,
    *,
    max_depth: int,
) -> tuple[list[_Artifact], list[str]]:
    artifacts: list[_Artifact] = []
    errors: list[str] = []
    _raise_if_cancelled(context)
    try:
        if root.is_symlink() or not root.is_dir():
            return artifacts, errors
    except OSError as exc:
        return artifacts, [f"{root}: {exc}"]

    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        _raise_if_cancelled(context)
        directory, owner_depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    _raise_if_cancelled(context)
                    try:
                        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    candidate = Path(entry.path).resolve(strict=False)
                    kind = _artifact_kind(entry.name)
                    if kind is not None:
                        artifacts.append(
                            _Artifact(
                                path=candidate,
                                kind=kind,
                                root=root,
                                depth=owner_depth + 1,
                            )
                        )
                    elif owner_depth < max_depth:
                        pending.append((candidate, owner_depth + 1))
        except OSError as exc:
            errors.append(f"{directory}: {exc}")
    return artifacts, errors


def _scan_artifacts(
    context: ToolContext,
    roots: tuple[Path, ...],
    *,
    max_depth: int,
) -> tuple[tuple[_Artifact, ...], list[str]]:
    found: dict[str, _Artifact] = {}
    errors: list[str] = []
    for root in roots:
        artifacts, scan_errors = _scan_root(context, root, max_depth=max_depth)
        errors.extend(scan_errors)
        for artifact in artifacts:
            found.setdefault(os.path.normcase(str(artifact.path)), artifact)
    return tuple(sorted(found.values(), key=lambda item: str(item.path))), errors


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def _read_ledger(context: ToolContext) -> _LedgerSnapshot:
    try:
        path = _ledger_path(context)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        fallback = _workspace_root(context) / "download_recovery.sqlite3"
        return _LedgerSnapshot(fallback, False, error=str(exc))
    _raise_if_cancelled(context)
    if not path.is_file():
        return _LedgerSnapshot(path, False)

    records: list[_LedgerRecord] = []
    frontier: list[_FrontierRecord] = []
    try:
        uri = f"{path.as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as conn:
            conn.execute("PRAGMA query_only = ON")
            if _table_exists(conn, "download_task_paths"):
                records.extend(
                    _LedgerRecord(
                        state="active",
                        save_directory=str(save_directory),
                        key=str(video_id),
                        generation=str(generation),
                    )
                    for video_id, save_directory, generation in conn.execute(
                        """
                        SELECT video_id, save_directory, generation
                        FROM download_task_paths
                        ORDER BY video_id
                        """
                    )
                )
            if _table_exists(conn, "pending_cleanup_directories"):
                records.extend(
                    _LedgerRecord(
                        state="pending_cleanup",
                        save_directory=str(save_directory),
                        key=str(save_directory),
                        generation=str(generation),
                    )
                    for save_directory, generation in conn.execute(
                        """
                        SELECT save_directory, generation
                        FROM pending_cleanup_directories
                        ORDER BY save_directory
                        """
                    )
                )
            if _table_exists(conn, "legacy_sweep_frontier"):
                frontier.extend(
                    _FrontierRecord(str(root), str(directory), int(depth))
                    for root, directory, depth in conn.execute(
                        """
                        SELECT root, path, depth
                        FROM legacy_sweep_frontier
                        ORDER BY root, depth, path
                        """
                    )
                )
    except sqlite3.Error as exc:
        return _LedgerSnapshot(path, True, error=str(exc))
    return _LedgerSnapshot(path, True, tuple(records), tuple(frontier))


def _diagnostic_data(
    *,
    roots: tuple[Path, ...],
    artifacts: tuple[_Artifact, ...],
    ledger: _LedgerSnapshot,
    scan_errors: list[str],
    cleanup_requested: bool,
) -> dict[str, Any]:
    return {
        "mode": "cleanup" if cleanup_requested else "diagnose",
        "roots": [str(root) for root in roots],
        "artifacts": [artifact.to_dict() for artifact in artifacts],
        "ledger": ledger.to_dict(),
        "scan_errors": list(scan_errors),
        "removed": [],
    }


def _build_result(
    status: str,
    message: str,
    *,
    data: Mapping[str, Any] | None = None,
    changed_paths: tuple[str, ...] = (),
    error_code: str = "",
) -> ToolRunResult:
    payload = dict(data or {})
    if error_code:
        payload.setdefault("error_code", error_code)
    if status == "success":
        factory = getattr(ToolRunResult, "success", None)
        if callable(factory):
            return factory(message, data=payload, output_paths=changed_paths)
    elif status == "cancelled":
        factory = getattr(ToolRunResult, "cancelled", None)
        if callable(factory):
            return factory(message)
    else:
        factory = getattr(ToolRunResult, "failure", None)
        if callable(factory):
            return factory(message, data=payload)
    failed = status != "success"
    return _construct_contract(
        ToolRunResult,
        {
            "status": status,
            "success": not failed,
            "ok": not failed,
            "cancelled": status == "cancelled",
            "message": message,
            "data": payload,
            "output": payload,
            "details": payload,
            "result": payload,
            "payload": payload,
            "changed_paths": changed_paths,
            "modified_paths": changed_paths,
            "output_paths": changed_paths,
            "error_code": error_code,
            "code": error_code,
            "error": message if failed else "",
            "errors": (message,) if failed else (),
        },
    )


def _error_result(message: str, data: Mapping[str, Any] | None = None) -> ToolRunResult:
    return _build_result("error", message, data=data, error_code="operation_failed")


def _cancelled_result(data: Mapping[str, Any] | None = None) -> ToolRunResult:
    return _build_result(
        "cancelled",
        "Download residue operation cancelled",
        data=data,
        error_code="cancelled",
    )


def _artifact_is_still_safe(
    context: ToolContext,
    artifact: _Artifact,
    *,
    max_depth: int,
) -> bool:
    path = artifact.path
    try:
        if path.is_symlink() or not path.is_dir():
            return False
        if _artifact_kind(path.name) != artifact.kind:
            return False
        relative = path.relative_to(artifact.root)
    except (OSError, RuntimeError, ValueError):
        return False
    return (
        1 <= len(relative.parts) <= max_depth + 1
        and _is_authorized(context, path)
    )


def _rollback_staged(staged: list[tuple[Path, Path]]) -> list[str]:
    errors: list[str] = []
    for original, quarantine in reversed(staged):
        try:
            if quarantine.exists() and not original.exists():
                quarantine.replace(original)
        except OSError as exc:
            errors.append(f"{original}: {exc}")
    return errors


def _stage_artifacts(
    context: ToolContext,
    artifacts: tuple[_Artifact, ...],
    *,
    max_depth: int,
) -> list[tuple[Path, Path]]:
    staged: list[tuple[Path, Path]] = []
    try:
        for artifact in artifacts:
            _raise_if_cancelled(context)
            if not _artifact_is_still_safe(context, artifact, max_depth=max_depth):
                raise OSError(f"artifact is no longer safe to clean: {artifact.path}")
            quarantine = artifact.path.with_name(
                f".{artifact.path.name}{_CLEANUP_MARKER}{uuid.uuid4().hex}"
            )
            artifact.path.replace(quarantine)
            staged.append((artifact.path, quarantine))
        _raise_if_cancelled(context)
    except BaseException:
        rollback_errors = _rollback_staged(staged)
        if rollback_errors:
            raise OSError("; ".join(rollback_errors))
        raise
    return staged


def _record_matches_roots(save_directory: str, roots: tuple[Path, ...]) -> bool:
    try:
        path = Path(save_directory).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return any(_within(path, root) for root in roots)


def _consume_matching_ledger_records(
    context: ToolContext,
    ledger: _LedgerSnapshot,
    roots: tuple[Path, ...],
) -> int:
    if not ledger.present or not _is_authorized(context, ledger.path):
        return 0
    matching_records = tuple(
        record
        for record in ledger.records
        if _record_matches_roots(record.save_directory, roots)
    )
    matching_frontier = tuple(
        record
        for record in ledger.frontier
        if _record_matches_roots(record.root, roots)
    )
    if not matching_records and not matching_frontier:
        return 0

    changed = 0
    conn = sqlite3.connect(
        f"{ledger.path.as_uri()}?mode=rw",
        uri=True,
        timeout=5.0,
    )
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        for record in matching_records:
            _raise_if_cancelled(context)
            if record.state == "active":
                cursor = conn.execute(
                    """
                    DELETE FROM download_task_paths
                    WHERE video_id = ? AND generation = ?
                    """,
                    (record.key, record.generation),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM pending_cleanup_directories
                    WHERE save_directory = ? AND generation = ?
                    """,
                    (record.key, record.generation),
                )
            affected = max(0, int(cursor.rowcount or 0))
            if affected != 1:
                raise sqlite3.IntegrityError(
                    "recovery ledger changed during cleanup"
                )
            changed += affected
        for record in matching_frontier:
            _raise_if_cancelled(context)
            cursor = conn.execute(
                """
                DELETE FROM legacy_sweep_frontier
                WHERE root = ? AND path = ? AND depth = ?
                """,
                (record.root, record.path, record.depth),
            )
            affected = max(0, int(cursor.rowcount or 0))
            if affected != 1:
                raise sqlite3.IntegrityError(
                    "recovery ledger frontier changed during cleanup"
                )
            changed += affected
        _raise_if_cancelled(context)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return changed


def _purge_staged(staged: list[tuple[Path, Path]]) -> None:
    for original, quarantine in staged:
        try:
            shutil.rmtree(quarantine)
        except OSError:
            if quarantine.exists() and not original.exists():
                quarantine.replace(original)
            raise


def run(context: ToolContext) -> ToolRunResult:
    errors = validate(context)
    if errors:
        return _error_result("; ".join(errors), {"validation_errors": errors})

    roots = _roots(context)
    max_depth = _max_depth(context)
    cleanup_requested = _is_cleanup(context)
    try:
        _raise_if_cancelled(context)
        artifacts, scan_errors = _scan_artifacts(context, roots, max_depth=max_depth)
        ledger = _read_ledger(context)
    except _Cancelled:
        return _cancelled_result()

    data = _diagnostic_data(
        roots=roots,
        artifacts=artifacts,
        ledger=ledger,
        scan_errors=scan_errors,
        cleanup_requested=cleanup_requested,
    )
    if not cleanup_requested:
        return _build_result(
            "success",
            f"Found {len(artifacts)} download residue artifact(s)",
            data=data,
        )
    if ledger.error:
        return _error_result(f"recovery ledger could not be read: {ledger.error}", data)

    staged: list[tuple[Path, Path]] = []
    ledger_changes = 0
    try:
        staged = _stage_artifacts(context, artifacts, max_depth=max_depth)
        ledger_changes = _consume_matching_ledger_records(context, ledger, roots)
    except _Cancelled:
        rollback_errors = _rollback_staged(staged)
        if rollback_errors:
            return _error_result("; ".join(rollback_errors), data)
        return _cancelled_result(data)
    except (OSError, sqlite3.Error) as exc:
        rollback_errors = _rollback_staged(staged)
        message = str(exc)
        if rollback_errors:
            message = f"{message}; rollback failed: {'; '.join(rollback_errors)}"
        return _error_result(message, data)

    try:
        _purge_staged(staged)
    except OSError as exc:
        return _error_result(f"cleanup purge failed: {exc}", data)

    removed_paths = [str(original) for original, _quarantine in staged]
    data["removed"] = removed_paths
    changed_paths = list(removed_paths)
    if ledger_changes:
        changed_paths.append(str(ledger.path))
    return _build_result(
        "success",
        f"Removed {len(removed_paths)} download residue artifact(s)",
        data=data,
        changed_paths=tuple(changed_paths),
    )


class DownloadResidueTool:
    manifest = manifest

    @staticmethod
    def validate(context: ToolContext) -> list[str]:
        return validate(context)

    @staticmethod
    def run(context: ToolContext) -> ToolRunResult:
        return run(context)


TOOL = DownloadResidueTool()
tool = TOOL


__all__ = [
    "DownloadResidueTool",
    "TOOL",
    "manifest",
    "run",
    "tool",
    "validate",
]
