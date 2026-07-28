from __future__ import annotations

import importlib.util
import inspect
import os
import sqlite3
import subprocess
import sys
import types
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from app.services.download_recovery_store import DownloadRecoveryStore
from shared.execution_profile import local_execution_profile


PROJECT_ROOT = Path(__file__).resolve().parents[5]
MODULE_PATH = PROJECT_ROOT / "app" / "core" / "tools" / "builtin" / "download_residue.py"
CONTRACTS_PATH = PROJECT_ROOT / "app" / "core" / "tools" / "contracts.py"


class _HostileExceptionMeta(type):
    def __getattribute__(cls, name: str) -> object:
        if name == "__name__":
            raise RuntimeError("exception metadata is unavailable")
        return super().__getattribute__(name)


class _HostileOSError(OSError, metaclass=_HostileExceptionMeta):
    def __str__(self) -> str:
        raise RuntimeError("exception text is unavailable")


class _HostileHashMeta(type):
    def __hash__(cls) -> int:
        raise RuntimeError("metadata hashing is unavailable")


class _HostileNotes(metaclass=_HostileHashMeta):
    pass


@pytest.fixture
def contracts(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Temporary contract shape until the parallel contracts task lands."""

    tools_package = types.ModuleType("app.core.tools")
    tools_package.__path__ = [str(PROJECT_ROOT / "app" / "core" / "tools")]
    builtin_package = types.ModuleType("app.core.tools.builtin")
    builtin_package.__path__ = [str(PROJECT_ROOT / "app" / "core" / "tools" / "builtin")]
    monkeypatch.setitem(sys.modules, "app.core.tools", tools_package)
    monkeypatch.setitem(sys.modules, "app.core.tools.builtin", builtin_package)

    if CONTRACTS_PATH.is_file():
        spec = importlib.util.spec_from_file_location("app.core.tools.contracts", CONTRACTS_PATH)
        assert spec is not None and spec.loader is not None
        contracts_module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, "app.core.tools.contracts", contracts_module)
        spec.loader.exec_module(contracts_module)
        return types.SimpleNamespace(
            ToolContext=contracts_module.ToolContext,
            ToolManifest=contracts_module.ToolManifest,
            ToolRunResult=contracts_module.ToolRunResult,
        )

    @dataclass(frozen=True)
    class ToolManifest:
        id: str
        title: str
        summary: str
        parameters: Mapping[str, Any]
        mutates_files: bool = False
        supports_cancel: bool = False

    @dataclass(frozen=True)
    class ToolContext:
        workspace_root: Path
        parameters: Mapping[str, Any] = field(default_factory=dict)
        allowed_paths: tuple[Path, ...] = ()
        cancel_event: Event = field(default_factory=Event)

    @dataclass(frozen=True)
    class ToolRunResult:
        status: str
        message: str = ""
        data: Mapping[str, Any] = field(default_factory=dict)
        changed_paths: tuple[str, ...] = ()

    contracts_module = types.ModuleType("app.core.tools.contracts")
    contracts_module.ToolContext = ToolContext
    contracts_module.ToolManifest = ToolManifest
    contracts_module.ToolRunResult = ToolRunResult
    monkeypatch.setitem(sys.modules, "app.core.tools.contracts", contracts_module)
    return types.SimpleNamespace(
        ToolContext=ToolContext,
        ToolManifest=ToolManifest,
        ToolRunResult=ToolRunResult,
    )


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch, contracts: types.SimpleNamespace) -> types.ModuleType:
    if not MODULE_PATH.is_file():
        pytest.fail("download residue builtin has not been implemented")
    module_name = "app.core.tools.builtin.download_residue"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _context(
    contracts: types.SimpleNamespace,
    workspace_root: Path,
    *,
    parameters: Mapping[str, Any] | None = None,
    allowed_paths: tuple[Path, ...] | None = None,
    cancel_event: Event | None = None,
) -> object:
    context_fields = inspect.signature(contracts.ToolContext).parameters
    normalized_parameters = dict(parameters or {})
    normalized_allowed = allowed_paths or (workspace_root,)
    event = cancel_event or Event()
    if "approved_roots" in context_fields:
        normalized_parameters.setdefault("roots", [str(workspace_root)])

        class EventCancellation:
            def is_cancelled(self) -> bool:
                return event.is_set()

            def raise_if_cancelled(self) -> None:
                if event.is_set():
                    raise RuntimeError("cancelled")

        return contracts.ToolContext(
            parameters=normalized_parameters,
            approved_roots=tuple(str(path) for path in normalized_allowed),
            cancellation=EventCancellation(),
        )
    return contracts.ToolContext(
        workspace_root=workspace_root,
        parameters=normalized_parameters,
        allowed_paths=normalized_allowed,
        cancel_event=event,
    )


def _status(result: object) -> str:
    value = getattr(result, "status", "")
    normalized = str(getattr(value, "value", value)).lower()
    return {
        "succeeded": "success",
        "failed": "error",
        "canceled": "cancelled",
    }.get(normalized, normalized)


def _changed_paths(result: object) -> tuple[str, ...]:
    for name in ("changed_paths", "output_paths"):
        value = getattr(result, name, None)
        if value is not None:
            return tuple(str(path) for path in value)
    return ()


def _manifest_parameters(manifest: object) -> Mapping[str, Any]:
    parameters = getattr(manifest, "parameters", None)
    if isinstance(parameters, Mapping):
        return parameters
    schema = getattr(manifest, "input_schema", None)
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else schema


def _create_recovery_ledger(
    path: Path,
    *,
    active: tuple[tuple[str, Path, str], ...] = (),
    pending: tuple[tuple[Path, str], ...] = (),
    frontier: tuple[tuple[Path, Path, int], ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE download_task_paths (
                video_id TEXT PRIMARY KEY,
                save_directory TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                trace_id TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                updated_at REAL NOT NULL,
                generation TEXT NOT NULL
            );
            CREATE TABLE pending_cleanup_directories (
                save_directory TEXT PRIMARY KEY,
                updated_at REAL NOT NULL,
                generation TEXT NOT NULL
            );
            CREATE TABLE legacy_sweep_frontier (
                root TEXT NOT NULL,
                path TEXT NOT NULL,
                depth INTEGER NOT NULL,
                queued_at REAL NOT NULL,
                PRIMARY KEY(root, path)
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO download_task_paths(
                video_id, save_directory, state, updated_at, generation
            ) VALUES (?, ?, 'active', 1.0, ?)
            """,
            [(video_id, str(directory.resolve()), generation) for video_id, directory, generation in active],
        )
        conn.executemany(
            """
            INSERT INTO pending_cleanup_directories(save_directory, updated_at, generation)
            VALUES (?, 1.0, ?)
            """,
            [(str(directory.resolve()), generation) for directory, generation in pending],
        )
        conn.executemany(
            """
            INSERT INTO legacy_sweep_frontier(root, path, depth, queued_at)
            VALUES (?, ?, ?, 1.0)
            """,
            [(str(root.resolve()), str(directory.resolve()), depth) for root, directory, depth in frontier],
        )


def _ledger_counts(path: Path) -> tuple[int, int, int]:
    with closing(sqlite3.connect(path)) as conn:
        return (
            int(conn.execute("SELECT COUNT(*) FROM download_task_paths").fetchone()[0]),
            int(conn.execute("SELECT COUNT(*) FROM pending_cleanup_directories").fetchone()[0]),
            int(conn.execute("SELECT COUNT(*) FROM legacy_sweep_frontier").fetchone()[0]),
        )


def _active_ledger_rows(path: Path) -> list[tuple[str, str, str]]:
    with closing(sqlite3.connect(path)) as conn:
        return [
            (str(video_id), str(save_directory), str(generation))
            for video_id, save_directory, generation in conn.execute(
                """
                SELECT video_id, save_directory, generation
                FROM download_task_paths
                ORDER BY video_id
                """
            )
        ]


def test_contract_aliases_keep_the_builtin_importable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True)
    class AlternateManifest:
        id: str
        title: str
        summary: str
        input_schema: Mapping[str, Any]
        safety_level: str
        execution_mode: str
        supports_cancel: bool = False

    @dataclass(frozen=True)
    class AlternateResult:
        status: str
        message: str = ""
        data: Mapping[str, Any] = field(default_factory=dict)
        error_code: str = ""

    @dataclass(frozen=True)
    class AlternateRequirements:
        permissions: frozenset[str] = frozenset()
        requires_approved_roots: bool = False

    contracts_module = types.ModuleType("app.core.tools.contracts")
    contracts_module.ToolContext = object
    contracts_module.ToolManifest = AlternateManifest
    contracts_module.ToolRequirements = AlternateRequirements
    contracts_module.ToolRunResult = AlternateResult
    monkeypatch.setitem(sys.modules, "app.core.tools.contracts", contracts_module)
    module_name = "app.core.tools.builtin.download_residue_alternate_contract"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)

    spec.loader.exec_module(module)

    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    context = types.SimpleNamespace(
        workspace_root=workspace,
        inputs={},
        allowed_paths=(workspace,),
        cancel_event=Event(),
    )
    result = module.run(context)
    assert module.manifest.safety_level == "explicit_mutation"
    assert module.manifest.input_schema["properties"]["cleanup"]["default"] is False
    assert _status(result) == "success"
    assert result.data["artifacts"][0]["path"] == str(residue.resolve())


def test_manifest_and_default_run_are_read_only(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    nm3u8 = workspace / ".ucp-nm3u8-tmp"
    curl = workspace / "clip_curl_cffi_hls"
    nm3u8.mkdir(parents=True)
    curl.mkdir()
    (nm3u8 / "segment.ts").write_bytes(b"segment")

    context = _context(contracts, workspace)

    assert tool.manifest.id == "download_residue"
    assert _manifest_parameters(tool.manifest)["cleanup"]["default"] is False
    assert tool.validate(context) == []

    result = tool.run(context)

    assert _status(result) == "success"
    assert {item["kind"] for item in result.data["artifacts"]} == {
        "nm3u8_temp_root",
        "curl_cffi_hls",
    }
    assert nm3u8.is_dir()
    assert curl.is_dir()
    assert _changed_paths(result) == ()


def test_builtin_exposes_a_registry_compatible_tool_object(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    context = _context(contracts, workspace)

    assert tool.TOOL.manifest is tool.manifest
    assert tool.TOOL.validate(context) == []
    assert _status(tool.TOOL.run(context)) == "success"


def test_default_ledger_probe_does_not_create_the_user_data_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    absent_user_data = tmp_path / "absent-user-data"
    monkeypatch.setenv("UCRAWL_USER_DATA_ROOT", str(absent_user_data))
    context = _context(contracts, workspace)

    result = tool.run(context)

    assert _status(result) == "success"
    assert result.data["ledger"]["path"] == str(
        absent_user_data / "cache" / "download_recovery.sqlite3"
    )
    assert not absent_user_data.exists()


def test_cleanup_uses_the_fixed_internal_ledger_without_caller_path_authority(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    user_data = tmp_path / "internal-user-data"
    ledger = user_data / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    monkeypatch.setenv("UCRAWL_USER_DATA_ROOT", str(user_data))
    context = _context(
        contracts,
        workspace,
        parameters={"roots": [str(workspace)], "cleanup": True},
        allowed_paths=(workspace,),
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert not residue.exists()
    assert _ledger_counts(ledger) == (0, 0, 0)
    assert _changed_paths(result) == ()


def test_scan_stops_after_two_owner_directory_levels_and_skips_symlinks(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    shallow = workspace / "collection" / "season" / "clip_playwright_hls"
    too_deep = workspace / "collection" / "season" / "extras" / "deep_curl_cffi_hls"
    outside = tmp_path / "outside"
    shallow.mkdir(parents=True)
    too_deep.mkdir(parents=True)
    outside.mkdir()
    symlink = workspace / "linked_curl_cffi_hls"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable on this host")

    context = _context(contracts, workspace)

    result = tool.run(context)
    found = {Path(item["path"]) for item in result.data["artifacts"]}

    assert shallow.resolve() in found
    assert too_deep.resolve() not in found
    assert symlink.resolve() not in found


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are unavailable")
def test_scan_does_not_follow_a_junction_outside_the_approved_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    outside = tmp_path / "outside"
    residue = outside / "secret_curl_cffi_hls"
    workspace.mkdir()
    residue.mkdir(parents=True)
    junction = workspace / "bridge"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("directory junctions are unavailable on this host")
    junction_probe = getattr(junction, "is_junction", None)
    assert junction_probe() if callable(junction_probe) else junction.is_dir()
    context = _context(
        contracts,
        workspace,
        parameters={"roots": [str(workspace)], "max_depth": 2},
        allowed_paths=(workspace,),
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert result.data["artifacts"] == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are unavailable")
def test_scan_does_not_follow_a_junction_within_the_approved_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    target = workspace / "deep-one" / "deep-two" / "target"
    residue = target / "secret_playwright_hls"
    workspace.mkdir()
    residue.mkdir(parents=True)
    junction = workspace / "bridge"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("directory junctions are unavailable on this host")
    junction_probe = getattr(junction, "is_junction", None)
    assert junction_probe() if callable(junction_probe) else junction.is_dir()
    context = _context(
        contracts,
        workspace,
        parameters={"roots": [str(workspace)], "max_depth": 2},
        allowed_paths=(workspace,),
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert result.data["artifacts"] == []


def test_read_only_run_reports_recovery_ledger_without_consuming_it(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("active-1", workspace, "gen-active"),),
        pending=((workspace, "gen-pending"),),
        frontier=((workspace, workspace / "collection", 1),),
    )
    before = ledger.read_bytes()
    context = _context(
        contracts,
        tmp_path,
        parameters={"roots": [str(workspace)], "ledger_path": str(ledger)},
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert result.data["ledger"]["counts"] == {
        "active": 1,
        "pending_cleanup": 1,
        "legacy_frontier": 1,
    }
    assert {record["state"] for record in result.data["ledger"]["records"]} == {
        "active",
        "pending_cleanup",
    }
    assert _ledger_counts(ledger) == (1, 1, 1)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("max_depth", [-1, 3, "2"])
def test_validate_rejects_non_shallow_depths(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    max_depth: object,
) -> None:
    context = _context(contracts, tmp_path, parameters={"max_depth": max_depth})

    errors = tool.validate(context)

    assert errors
    assert any("max_depth" in error for error in errors)


def test_cleanup_rejects_an_unauthorized_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    allowed = tmp_path / "allowed"
    unauthorized = tmp_path / "unauthorized"
    allowed.mkdir()
    residue = unauthorized / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    context = _context(
        contracts,
        allowed,
        parameters={"roots": [str(unauthorized)], "cleanup": True},
        allowed_paths=(allowed,),
    )

    errors = tool.validate(context)
    result = tool.run(context)

    assert any("authorized" in error.lower() for error in errors)
    assert _status(result) == "error"
    assert residue.is_dir()


def test_cleanup_rejects_an_explicit_ledger_outside_authorized_roots(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    unauthorized_ledger = tmp_path / "private" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        unauthorized_ledger,
        active=(("private-task", tmp_path / "private-save", "private-generation"),),
    )
    context = _context(
        contracts,
        workspace,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(unauthorized_ledger),
            "cleanup": True,
        },
        allowed_paths=(workspace,),
    )

    result = tool.run(context)
    assert _status(result) == "error"
    assert residue.is_dir()
    assert _ledger_counts(unauthorized_ledger) == (1, 0, 0)
    assert "private-task" not in repr(result.data)
    assert _changed_paths(result) == ()


def test_diagnose_rejects_an_explicit_ledger_before_reading_private_rows(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    unauthorized_ledger = tmp_path / "private" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        unauthorized_ledger,
        active=(("private-task", tmp_path / "private-save", "private-generation"),),
    )
    context = _context(
        contracts,
        workspace,
        parameters={"ledger_path": str(unauthorized_ledger)},
        allowed_paths=(workspace,),
    )

    result = tool.run(context)
    assert _status(result) == "error"
    assert "private-task" not in repr(result.data)
    assert "private-save" not in repr(result.data)
    assert _changed_paths(result) == ()


def test_real_execution_profile_authorizes_explicit_ledger_and_scan_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    ledger = tmp_path / "download-recovery.sqlite3"
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:download-residue-profile",
        approved_roots=(tmp_path,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    context = contracts.ToolContext(
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": False,
        },
        execution_profile=profile,
    )

    assert context.approved_roots == ()
    assert context.authorize_path(ledger) == ledger.resolve()
    assert tool.validate(context) == []
    assert _status(tool.run(context)) == "success"


def test_real_execution_profile_supplies_the_default_scan_root(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:download-residue-default-root",
        approved_roots=(workspace,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    context = contracts.ToolContext(parameters={}, execution_profile=profile)

    result = tool.run(context)

    assert _status(result) == "success"
    assert [item["path"] for item in result.data["artifacts"]] == [
        str(residue.resolve())
    ]


def test_diagnose_rejects_a_root_outside_the_real_execution_profile(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "approved"
    outside = tmp_path / "outside"
    residue = outside / "secret_curl_cffi_hls"
    workspace.mkdir()
    residue.mkdir(parents=True)
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:download-residue-denied-root",
        approved_roots=(workspace,),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    context = contracts.ToolContext(
        parameters={"roots": [str(outside)]},
        execution_profile=profile,
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.data["validation_errors"] == [
        f"scan root is not authorized: {outside.resolve()}"
    ]
    assert "secret_curl_cffi_hls" not in repr(result.data)


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive")
def test_path_boundaries_use_windows_case_normalization(tool: types.ModuleType) -> None:
    assert tool._within(Path("C:/Approved/Child"), Path("c:/approved"))


def test_cleanup_accepts_a_root_explicitly_approved_by_the_shared_context(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    if "approved_roots" not in inspect.signature(contracts.ToolContext).parameters:
        pytest.skip("shared ToolContext is not available")
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = workspace / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    context = contracts.ToolContext(
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
        approved_roots=(str(workspace),),
    )

    assert tool.validate(context) == []
    result = tool.run(context)

    assert _status(result) == "success"
    assert not residue.exists()


def test_shared_context_uses_approved_roots_as_the_default_scan_workspace(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    if "approved_roots" not in inspect.signature(contracts.ToolContext).parameters:
        pytest.skip("shared ToolContext is not available")
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    context = contracts.ToolContext(
        parameters={},
        approved_roots=(str(workspace),),
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert [item["path"] for item in result.data["artifacts"]] == [
        str(residue.resolve())
    ]
    assert residue.is_dir()


def test_cleanup_rejects_a_symlink_scan_root_even_when_the_link_is_authorized(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    target = tmp_path / "outside"
    residue = target / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    linked_root = tmp_path / "authorized-link"
    try:
        linked_root.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable on this host")
    context = _context(
        contracts,
        tmp_path,
        parameters={"roots": [str(linked_root)], "cleanup": True},
        allowed_paths=(linked_root,),
    )

    errors = tool.validate(context)
    result = tool.run(context)

    assert any("symlink" in error.lower() for error in errors)
    assert _status(result) == "error"
    assert residue.is_dir()


def test_explicit_cleanup_removes_only_diagnosed_artifacts_and_consumes_matching_records(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    nm3u8 = workspace / ".ucp-nm3u8-tmp"
    curl = workspace / "clip_curl_cffi_hls"
    normal = workspace / "my_videos"
    for directory in (nm3u8, curl, normal):
        directory.mkdir()
        (directory / "keep.bin").write_bytes(b"data")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("unrelated", unrelated, "gen-unrelated"),),
        pending=((workspace, "gen-pending"), (unrelated, "gen-unrelated-pending")),
        frontier=((workspace, workspace / "collection", 1),),
    )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert not nm3u8.exists()
    assert not curl.exists()
    assert normal.is_dir()
    assert unrelated.is_dir()
    assert _ledger_counts(ledger) == (1, 1, 0)
    assert result.data["quarantined"] == []
    assert {
        item["original_path"] for item in result.data["purged"]
    } == {str(nm3u8.resolve()), str(curl.resolve())}
    assert all(
        set(item) == {"original_path", "quarantine_path"}
        for item in result.data["purged"]
    )
    assert _changed_paths(result) == ()


def test_cleanup_never_deletes_active_ledger_row_or_nested_workspace(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    active_root = workspace / "video-a"
    residue = active_root / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("video-a", active_root, "gen-active"),),
    )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert residue.is_dir()
    assert _active_ledger_rows(ledger) == [
        ("video-a", str(active_root.resolve()), "gen-active")
    ]
    assert result.data["protected"] == [str(residue.resolve())]
    assert _changed_paths(result) == ()


def test_cleanup_preserves_residue_ancestor_of_active_workspace(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / ".ucp-nm3u8-tmp"
    active_root = residue / "ucp-video-a"
    active_root.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("video-a", active_root, "gen-active"),),
    )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert active_root.is_dir()
    assert _active_ledger_rows(ledger) == [
        ("video-a", str(active_root.resolve()), "gen-active")
    ]
    assert result.data["protected"] == [str(residue.resolve())]


def test_cleanup_preserves_residue_equal_to_active_workspace(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("video-a", residue, "gen-active"),),
    )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert residue.is_dir()
    assert _active_ledger_rows(ledger) == [
        ("video-a", str(residue.resolve()), "gen-active")
    ]
    assert result.data["protected"] == [str(residue.resolve())]
    assert _changed_paths(result) == ()


def test_cleanup_does_not_consume_unrelated_active_row(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    active_root = tmp_path / "active"
    stale_root = tmp_path / "stale"
    active_root.mkdir()
    residue = stale_root / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("video-a", active_root, "gen-active"),),
    )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(stale_root)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert not residue.exists()
    assert _active_ledger_rows(ledger) == [
        ("video-a", str(active_root.resolve()), "gen-active")
    ]


def test_cleanup_rechecks_active_rows_registered_after_initial_snapshot(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    active_root = workspace / "video-a"
    residue = active_root / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    original_read_ledger = tool._read_ledger

    def read_then_register(context: object) -> object:
        snapshot = original_read_ledger(context)
        recovery_store.register_task(
            video_id="late-active",
            save_directory=active_root,
        )
        return snapshot

    monkeypatch.setattr(tool, "_read_ledger", read_then_register)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert residue.is_dir()
    assert result.data["protected"] == [str(residue.resolve())]
    assert len(_active_ledger_rows(ledger)) == 1
    assert _active_ledger_rows(ledger)[0][:2] == (
        "late-active",
        os.path.normcase(str(active_root.resolve())),
    )
    assert _changed_paths(result) == ()


def test_cleanup_keeps_the_write_lock_until_staging_and_ledger_cas_finish(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    (residue / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    assert recovery_store.recovery_counts() == {
        "active": 0,
        "pending_cleanup": 1,
    }
    original_stage_artifacts = tool._stage_artifacts
    writer_started = Event()
    writer_finished = Event()
    writer_errors: list[BaseException] = []
    writer_finished_while_staging: list[bool] = []

    def register_new_task() -> None:
        writer_started.set()
        try:
            recovery_store.register_task(
                video_id="concurrent-active",
                save_directory=residue,
            )
            residue.mkdir(parents=True, exist_ok=True)
            (residue / "new.bin").write_bytes(b"new")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    writer = Thread(target=register_new_task, daemon=True)

    def stage_with_concurrent_registration(
        *args: object,
        **kwargs: object,
    ) -> object:
        staged = original_stage_artifacts(*args, **kwargs)
        writer.start()
        assert writer_started.wait(timeout=2.0)
        writer_finished_while_staging.append(writer_finished.wait(timeout=0.1))
        return staged

    monkeypatch.setattr(tool, "_stage_artifacts", stage_with_concurrent_registration)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)
    writer.join(timeout=5.0)

    assert _status(result) == "success"
    assert writer_finished_while_staging == [False]
    assert not writer.is_alive()
    assert writer_errors == []
    assert (residue / "new.bin").read_bytes() == b"new"
    assert not (residue / "old.bin").exists()
    assert len(_active_ledger_rows(ledger)) == 1
    assert _active_ledger_rows(ledger)[0][:2] == (
        "concurrent-active",
        os.path.normcase(str(residue.resolve())),
    )


def test_cleanup_fails_closed_when_the_recovery_ledger_is_absent(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)
    assert _status(result) == "error"
    assert residue.is_dir()
    assert not ledger.exists()
    assert _changed_paths(result) == ()


def test_cleanup_fails_closed_when_the_active_task_table_is_absent(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    ledger.parent.mkdir(parents=True)
    with closing(sqlite3.connect(ledger)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE pending_cleanup_directories (
                save_directory TEXT PRIMARY KEY,
                updated_at REAL NOT NULL,
                generation TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO pending_cleanup_directories(
                save_directory, updated_at, generation
            ) VALUES (?, 1.0, 'gen-pending')
            """,
            (str(workspace.resolve()),),
        )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    with closing(sqlite3.connect(ledger)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pending_cleanup_directories"
            ).fetchone()[0]
            == 1
        )
    assert _changed_paths(result) == ()


def test_cleanup_fails_closed_when_an_active_save_path_cannot_be_resolved(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    unresolvable = tmp_path / "unresolvable-active-root"
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("broken-active", unresolvable, "gen-active"),),
    )
    original_resolve = Path.resolve

    def fail_active_path_resolution(
        path: Path,
        strict: bool = False,
    ) -> Path:
        if path == unresolvable:
            raise OSError("injected active path resolution failure")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_active_path_resolution)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    assert len(_active_ledger_rows(ledger)) == 1
    assert _changed_paths(result) == ()


def test_cleanup_fails_closed_when_an_active_save_path_is_relative(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("broken-active", workspace, "gen-active"),),
    )
    with closing(sqlite3.connect(ledger)) as conn, conn:
        conn.execute(
            """
            UPDATE download_task_paths
            SET save_directory = 'relative-active-root'
            WHERE video_id = 'broken-active'
            """
        )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    assert len(_active_ledger_rows(ledger)) == 1
    assert _changed_paths(result) == ()


def test_cleanup_fails_closed_when_an_active_save_path_is_empty(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "cache" / "download_recovery.sqlite3"
    _create_recovery_ledger(
        ledger,
        active=(("broken-active", workspace, "gen-active"),),
    )
    with closing(sqlite3.connect(ledger)) as conn, conn:
        conn.execute(
            """
            UPDATE download_task_paths
            SET save_directory = ''
            WHERE video_id = 'broken-active'
            """
        )
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    assert len(_active_ledger_rows(ledger)) == 1
    assert _changed_paths(result) == ()


def test_cleanup_cancelled_before_mutation_preserves_files_and_ledger(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    cancelled = Event()
    cancelled.set()
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
        cancel_event=cancelled,
    )

    result = tool.run(context)

    assert _status(result) == "cancelled"
    assert residue.is_dir()
    assert _ledger_counts(ledger) == (0, 1, 0)
    assert _changed_paths(result) == ()


def test_cleanup_cancelled_after_staging_preserves_files_and_ledger(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    cancelled = Event()
    original_stage_artifacts = tool._stage_artifacts
    original_rollback_staged = tool._rollback_staged
    rollback_lock_errors: list[str] = []

    def stage_then_cancel(*args: object, **kwargs: object) -> object:
        staged = original_stage_artifacts(*args, **kwargs)
        cancelled.set()
        return staged

    def rollback_with_lock_probe(staged: object) -> object:
        with closing(sqlite3.connect(ledger, timeout=0.0)) as contender:
            try:
                contender.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                rollback_lock_errors.append(str(exc).lower())
            else:
                contender.rollback()
        return original_rollback_staged(staged)

    monkeypatch.setattr(tool, "_stage_artifacts", stage_then_cancel)
    monkeypatch.setattr(tool, "_rollback_staged", rollback_with_lock_probe)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
        cancel_event=cancelled,
    )

    result = tool.run(context)

    assert _status(result) == "cancelled"
    assert residue.is_dir()
    assert _ledger_counts(ledger) == (0, 1, 0)
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))
    assert len(rollback_lock_errors) == 1
    assert "locked" in rollback_lock_errors[0]
    assert _changed_paths(result) == ()


def test_staging_failure_rolls_back_all_renames_before_ledger_commit(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    first = workspace / "a_curl_cffi_hls"
    second = workspace / "b_playwright_hls"
    first.mkdir(parents=True)
    second.mkdir()
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_replace = Path.replace
    calls = 0

    def fail_second_replace(path: Path, target: Path) -> Path:
        nonlocal calls
        if ".ucp-residue-cleanup-" in target.name:
            calls += 1
            if calls == 2:
                raise OSError("injected staging failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert first.is_dir()
    assert second.is_dir()
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))
    assert _ledger_counts(ledger) == (0, 1, 0)
    assert _changed_paths(result) == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are unavailable")
def test_stage_recheck_rejects_an_artifact_replaced_by_a_junction(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    target = workspace / "replacement-target"
    residue.mkdir(parents=True)
    target.mkdir()
    (target / "keep.bin").write_bytes(b"target")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_read_ledger = tool._read_ledger

    def read_then_replace_with_junction(context: object) -> object:
        snapshot = original_read_ledger(context)
        residue.rmdir()
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(residue), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip("directory junctions are unavailable on this host")
        return snapshot

    monkeypatch.setattr(tool, "_read_ledger", read_then_replace_with_junction)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.message.startswith("artifact is no longer safe to clean")
    junction_probe = getattr(residue, "is_junction", None)
    assert junction_probe() if callable(junction_probe) else residue.is_dir()
    assert (target / "keep.bin").read_bytes() == b"target"
    assert _ledger_counts(ledger) == (0, 1, 0)
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))


def test_rollback_failure_does_not_replace_the_staging_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    first = workspace / "a_curl_cffi_hls"
    second = workspace / "b_playwright_hls"
    first.mkdir(parents=True)
    second.mkdir()
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    original_replace = Path.replace
    staging_calls = 0

    def fail_staging_and_rollback(path: Path, target: Path) -> Path:
        nonlocal staging_calls
        if _is_quarantine_path(target):
            staging_calls += 1
            if staging_calls == 2:
                raise OSError("injected staging failure")
        if _is_quarantine_path(path) and target == first:
            raise OSError("injected rollback failure")
        return original_replace(path, target)

    def _is_quarantine_path(path: Path) -> bool:
        return ".ucp-residue-cleanup-" in path.name

    monkeypatch.setattr(Path, "replace", fail_staging_and_rollback)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.message.startswith("injected staging failure")
    assert "rollback failed" in result.message
    assert "injected rollback failure" in result.message
    assert second.is_dir()
    assert _changed_paths(result) == ()


def test_hostile_rollback_exception_does_not_replace_the_staging_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    first = workspace / "a_curl_cffi_hls"
    second = workspace / "b_playwright_hls"
    first.mkdir(parents=True)
    second.mkdir()
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    original_replace = Path.replace
    staging_calls = 0

    def fail_staging_and_rollback(path: Path, target: Path) -> Path:
        nonlocal staging_calls
        if _is_quarantine_path(target):
            staging_calls += 1
            if staging_calls == 2:
                raise OSError("primary staging failure")
        if _is_quarantine_path(path) and target == first:
            raise _HostileOSError("private rollback detail")
        return original_replace(path, target)

    def _is_quarantine_path(path: Path) -> bool:
        return ".ucp-residue-cleanup-" in path.name

    monkeypatch.setattr(Path, "replace", fail_staging_and_rollback)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    escaped = False
    result: object | None = None
    try:
        result = tool.run(context)
    except BaseException:
        escaped = True

    assert not escaped, "hostile rollback exception escaped the tool boundary"
    assert result is not None
    assert _status(result) == "error"
    assert result.message.startswith("primary staging failure")
    assert "rollback failed" in result.message
    assert "private rollback detail" not in result.message
    assert second.is_dir()
    assert _changed_paths(result) == ()


def test_non_os_rollback_exception_does_not_replace_the_staging_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    first = workspace / "a_curl_cffi_hls"
    second = workspace / "b_playwright_hls"
    first.mkdir(parents=True)
    second.mkdir()
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    original_replace = Path.replace
    staging_calls = 0

    def fail_staging_and_rollback(path: Path, target: Path) -> Path:
        nonlocal staging_calls
        if ".ucp-residue-cleanup-" in target.name:
            staging_calls += 1
            if staging_calls == 2:
                raise OSError("primary staging failure")
        if ".ucp-residue-cleanup-" in path.name and target == first:
            raise RuntimeError("non-os rollback failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_and_rollback)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    escaped = False
    result: object | None = None
    try:
        result = tool.run(context)
    except BaseException:
        escaped = True

    assert not escaped, "secondary rollback exception escaped the tool boundary"
    assert result is not None
    assert _status(result) == "error"
    assert result.message.startswith("primary staging failure")
    assert "rollback failed" in result.message
    assert "non-os rollback failure" in result.message
    assert second.is_dir()
    assert _changed_paths(result) == ()


def test_exception_message_ignores_hostile_notes_metadata(
    tool: types.ModuleType,
) -> None:
    error = OSError("primary failure")
    object.__setattr__(error, "__notes__", _HostileNotes())
    escaped = False
    message = ""

    try:
        message = tool._exception_message(error)
    except BaseException:
        escaped = True

    assert not escaped, "hostile note metadata escaped error formatting"
    assert message == "primary failure"


def test_hostile_ledger_rollback_exception_does_not_replace_the_primary_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    original_connect = tool.sqlite3.connect

    class ConnectionWithHostileRollback:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def rollback(self) -> None:
            raise _HostileOSError("private ledger rollback detail")

        def close(self) -> None:
            self._connection.close()

    def fail_staging(*_args: object, **_kwargs: object) -> object:
        raise OSError("primary staging failure")

    monkeypatch.setattr(tool.sqlite3, "connect", ConnectionWithHostileRollback)
    monkeypatch.setattr(tool, "_stage_artifacts", fail_staging)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    escaped = False
    result: object | None = None
    try:
        result = tool.run(context)
    except BaseException:
        escaped = True

    assert not escaped, "hostile ledger exception escaped the tool boundary"
    assert result is not None
    assert _status(result) == "error"
    assert result.message.startswith("primary staging failure")
    assert "ledger rollback failed" in result.message
    assert "private ledger rollback detail" not in result.message
    assert residue.is_dir()
    assert _changed_paths(result) == ()


def test_hostile_connection_close_does_not_replace_a_commit_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_connect = tool.sqlite3.connect
    connect_calls = 0

    class ConnectionWithFailingCommitAndClose:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def commit(self) -> None:
            raise sqlite3.OperationalError("primary commit failure")

        def close(self) -> None:
            self._connection.close()
            raise _HostileOSError("private close detail")

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return original_connect(*args, **kwargs)
        return ConnectionWithFailingCommitAndClose(*args, **kwargs)

    monkeypatch.setattr(tool.sqlite3, "connect", connect)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.message.startswith("primary commit failure")
    assert "ledger close failed" in result.message
    assert "private close detail" not in result.message
    assert residue.is_dir()
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))
    with closing(original_connect(ledger)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pending_cleanup_directories"
            ).fetchone()[0]
            == 1
        )


def test_hostile_connection_close_after_commit_keeps_the_staged_manifest(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_connect = tool.sqlite3.connect
    connect_calls = 0

    class ConnectionWithHostileClose:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def close(self) -> None:
            self._connection.close()
            raise _HostileOSError("private close detail")

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return original_connect(*args, **kwargs)
        return ConnectionWithHostileClose(*args, **kwargs)

    monkeypatch.setattr(tool.sqlite3, "connect", connect)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert not residue.exists()
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))
    assert _changed_paths(result) == ()
    with closing(original_connect(ledger)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pending_cleanup_directories"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "close_error_type",
    (KeyboardInterrupt, SystemExit),
    ids=("keyboard-interrupt", "system-exit"),
)
def test_control_flow_interrupt_from_successful_connection_close_propagates(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    close_error_type: type[BaseException],
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_connect = tool.sqlite3.connect
    connect_calls = 0

    class ConnectionWithInterruptedClose:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def close(self) -> None:
            self._connection.close()
            raise close_error_type("close control-flow interrupt")

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return original_connect(*args, **kwargs)
        return ConnectionWithInterruptedClose(*args, **kwargs)

    monkeypatch.setattr(tool.sqlite3, "connect", connect)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    with pytest.raises(close_error_type, match="close control-flow interrupt"):
        tool.run(context)

    assert not residue.exists()
    assert len(list(workspace.glob("*.ucp-residue-cleanup-*"))) == 1
    with closing(original_connect(ledger)) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pending_cleanup_directories"
            ).fetchone()[0]
            == 0
        )


def test_control_flow_interrupt_from_close_is_secondary_to_commit_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_connect = tool.sqlite3.connect
    connect_calls = 0

    class ConnectionWithFailingCommitAndInterruptedClose:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def commit(self) -> None:
            raise sqlite3.OperationalError("primary commit failure")

        def close(self) -> None:
            self._connection.close()
            raise KeyboardInterrupt("close control-flow interrupt")

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return original_connect(*args, **kwargs)
        return ConnectionWithFailingCommitAndInterruptedClose(*args, **kwargs)

    monkeypatch.setattr(tool.sqlite3, "connect", connect)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.message.startswith("primary commit failure")
    assert "ledger close failed: close control-flow interrupt" in result.message
    assert residue.is_dir()
    with closing(original_connect(ledger)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM download_task_paths").fetchone()[
            0
        ] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM pending_cleanup_directories"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM legacy_sweep_frontier").fetchone()[
            0
        ] == 0


@pytest.mark.parametrize(
    ("close_error_kind", "expected_diagnostic"),
    (
        (
            "keyboard-interrupt",
            "ledger close failed: purge close control-flow interrupt",
        ),
        (
            "system-exit",
            "ledger close failed: purge close control-flow interrupt",
        ),
        (
            "hostile-os-error",
            "ledger close failed: download residue operation failed",
        ),
    ),
    ids=("keyboard-interrupt", "system-exit", "hostile-os-error"),
)
def test_purge_close_failure_is_secondary_to_commit_failure(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    close_error_kind: str,
    expected_diagnostic: str,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_connect = tool.sqlite3.connect
    connect_calls = 0
    if close_error_kind == "keyboard-interrupt":
        close_error: BaseException = KeyboardInterrupt(
            "purge close control-flow interrupt"
        )
    elif close_error_kind == "system-exit":
        close_error = SystemExit("purge close control-flow interrupt")
    else:
        close_error = _HostileOSError("private purge close detail")

    class PurgeConnectionWithFailingCommitAndClose:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._connection = original_connect(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def commit(self) -> None:
            raise sqlite3.OperationalError("primary purge commit failure")

        def close(self) -> None:
            self._connection.close()
            raise close_error

    def connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 3:
            return PurgeConnectionWithFailingCommitAndClose(*args, **kwargs)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(tool.sqlite3, "connect", connect)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert result.message.startswith(
        "cleanup purge failed: primary purge commit failure"
    )
    assert expected_diagnostic in result.message
    assert "private purge close detail" not in result.message
    assert not residue.exists()
    assert _changed_paths(result) == ()


def test_ledger_disappearing_after_snapshot_does_not_create_a_phantom_database(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_read_ledger = tool._read_ledger

    def read_then_remove_ledger(context: object) -> object:
        snapshot = original_read_ledger(context)
        ledger.unlink()
        return snapshot

    monkeypatch.setattr(tool, "_read_ledger", read_then_remove_ledger)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    assert not ledger.exists()
    assert not list(workspace.glob("*.ucp-residue-cleanup-*"))


def test_ledger_generation_change_aborts_and_rolls_back_workspace_cleanup(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "old-generation"),))
    original_read_ledger = tool._read_ledger

    def read_then_replace_generation(context: object) -> object:
        snapshot = original_read_ledger(context)
        with closing(sqlite3.connect(ledger)) as conn, conn:
            conn.execute(
                """
                UPDATE pending_cleanup_directories
                SET generation = 'new-generation'
                WHERE save_directory = ?
                """,
                (str(workspace.resolve()),),
            )
        return snapshot

    monkeypatch.setattr(tool, "_read_ledger", read_then_replace_generation)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert residue.is_dir()
    assert _ledger_counts(ledger) == (0, 1, 0)
    with closing(sqlite3.connect(ledger)) as conn:
        generation = conn.execute(
            "SELECT generation FROM pending_cleanup_directories"
        ).fetchone()[0]
    assert generation == "new-generation"


def test_purge_failure_after_commit_never_restores_over_a_new_active_task(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    (residue / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    assert recovery_store.recovery_counts() == {
        "active": 0,
        "pending_cleanup": 1,
    }
    original_rmtree = tool.shutil.rmtree
    quarantine_paths: list[Path] = []
    writer_started = Event()
    writer_finished = Event()
    writer_finished_during_purge: list[bool] = []
    writer_errors: list[BaseException] = []
    writers: list[Thread] = []

    def register_new_task() -> None:
        writer_started.set()
        try:
            recovery_store.register_task(
                video_id="new-active",
                save_directory=residue,
            )
            residue.mkdir(parents=True, exist_ok=True)
            (residue / "new.bin").write_bytes(b"new")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def register_then_fail_purge(quarantine: Path) -> None:
        quarantine_paths.append(quarantine)
        writer = Thread(target=register_new_task, daemon=True)
        writers.append(writer)
        writer.start()
        assert writer_started.wait(timeout=2.0)
        writer_finished_during_purge.append(writer_finished.wait(timeout=0.1))
        raise _HostileOSError("private purge detail")

    monkeypatch.setattr(tool.shutil, "rmtree", register_then_fail_purge)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    escaped = False
    result: object | None = None
    try:
        result = tool.run(context)
    except BaseException:
        escaped = True
    for writer in writers:
        writer.join(timeout=5.0)

    assert not escaped, "hostile purge exception escaped the tool boundary"
    assert result is not None
    assert _status(result) == "error"
    assert writer_finished_during_purge == [False]
    assert all(not writer.is_alive() for writer in writers)
    assert writer_errors == []
    assert result.message == (
        "cleanup purge failed: download residue operation failed"
    )
    assert "private purge detail" not in result.message
    assert (residue / "new.bin").read_bytes() == b"new"
    assert not (residue / "old.bin").exists()
    assert len(quarantine_paths) == 1
    assert (quarantine_paths[0] / "old.bin").read_bytes() == b"old"
    assert _ledger_counts(ledger) == (1, 0, 0)
    assert _active_ledger_rows(ledger)[0][:2] == (
        "new-active",
        os.path.normcase(str(residue.resolve())),
    )
    quarantine = quarantine_paths[0]
    assert result.data["purged"] == []
    assert result.data["quarantined"] == [
        {
            "original_path": str(residue.resolve()),
            "quarantine_path": str(quarantine),
        }
    ]
    assert _changed_paths(result) == (str(quarantine),)

    diagnose_context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": False,
        },
    )
    diagnosed = tool.run(diagnose_context)
    diagnosed_kinds = {
        item["path"]: item["kind"] for item in diagnosed.data["artifacts"]
    }
    assert diagnosed_kinds[str(quarantine)] == "cleanup_quarantine"
    assert diagnosed_kinds[str(residue.resolve())] == "curl_cffi_hls"
    assert diagnosed.data["protected"] == [str(residue.resolve())]

    monkeypatch.setattr(tool.shutil, "rmtree", original_rmtree)
    retried = tool.run(context)
    assert _status(retried) == "success"
    assert not quarantine.exists()
    assert (residue / "new.bin").read_bytes() == b"new"
    assert len(_active_ledger_rows(ledger)) == 1


def test_purge_reports_each_purged_and_quarantined_artifact(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    first = workspace / "a_curl_cffi_hls"
    second = workspace / "b_playwright_hls"
    first.mkdir(parents=True)
    second.mkdir()
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    original_rmtree = tool.shutil.rmtree
    attempted: list[Path] = []

    def fail_first_purge(quarantine: Path) -> None:
        attempted.append(quarantine)
        if "a_curl_cffi_hls" in quarantine.name:
            raise OSError("first purge failed")
        original_rmtree(quarantine)

    monkeypatch.setattr(tool.shutil, "rmtree", fail_first_purge)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "error"
    assert len(attempted) == 2
    assert [item["original_path"] for item in result.data["purged"]] == [
        str(second.resolve())
    ]
    assert [
        item["original_path"] for item in result.data["quarantined"]
    ] == [str(first.resolve())]
    quarantine = Path(result.data["quarantined"][0]["quarantine_path"])
    assert quarantine.is_dir()
    assert _changed_paths(result) == (str(quarantine),)
    assert not first.exists()
    assert not second.exists()


def test_retrying_a_quarantine_never_purges_a_new_task_at_its_old_path(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    quarantine = workspace / (
        ".clip_curl_cffi_hls.ucp-residue-cleanup-"
        "00000000000000000000000000000000"
    )
    quarantine.mkdir(parents=True)
    (quarantine / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger)
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    assert recovery_store.recovery_counts() == {
        "active": 0,
        "pending_cleanup": 0,
    }
    original_rmtree = tool.shutil.rmtree
    staged_paths: list[Path] = []
    writer_started = Event()
    writer_finished = Event()
    writer_finished_during_purge: list[bool] = []
    writer_errors: list[BaseException] = []
    writers: list[Thread] = []

    def register_new_task() -> None:
        writer_started.set()
        try:
            recovery_store.register_task(
                video_id="new-quarantine-owner",
                save_directory=quarantine,
            )
            quarantine.mkdir(parents=True, exist_ok=True)
            (quarantine / "new.bin").write_bytes(b"new")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def register_then_purge(staged_path: Path) -> None:
        staged_paths.append(staged_path)
        writer = Thread(target=register_new_task, daemon=True)
        writers.append(writer)
        writer.start()
        assert writer_started.wait(timeout=2.0)
        writer_finished_during_purge.append(writer_finished.wait(timeout=0.1))
        original_rmtree(staged_path)

    monkeypatch.setattr(tool.shutil, "rmtree", register_then_purge)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)
    for writer in writers:
        writer.join(timeout=5.0)

    assert _status(result) == "success"
    assert writer_finished_during_purge == [False]
    assert all(not writer.is_alive() for writer in writers)
    assert writer_errors == []
    assert len(staged_paths) == 1
    assert staged_paths[0] != quarantine
    assert (quarantine / "new.bin").read_bytes() == b"new"
    assert not (quarantine / "old.bin").exists()
    assert _active_ledger_rows(ledger)[0][:2] == (
        "new-quarantine-owner",
        os.path.normcase(str(quarantine.resolve())),
    )


def test_purge_defers_a_quarantine_registered_before_the_purge_lock(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    (residue / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    original_purge = tool._purge_staged
    quarantine_paths: list[Path] = []

    def register_before_purge(*args: object, **kwargs: object) -> object:
        staged = next(arg for arg in args if isinstance(arg, list))
        quarantine = staged[0][1]
        quarantine_paths.append(quarantine)
        recovery_store.register_task(
            video_id="purge-active",
            save_directory=quarantine,
        )
        (quarantine / "active.bin").write_bytes(b"active")
        return original_purge(*args, **kwargs)

    monkeypatch.setattr(tool, "_purge_staged", register_before_purge)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert len(quarantine_paths) == 1
    quarantine = quarantine_paths[0]
    assert (quarantine / "old.bin").read_bytes() == b"old"
    assert (quarantine / "active.bin").read_bytes() == b"active"
    assert _active_ledger_rows(ledger)[0][:2] == (
        "purge-active",
        os.path.normcase(str(quarantine.resolve())),
    )
    assert result.data["purged"] == []
    assert result.data["quarantined"] == []
    assert result.data["deferred"] == [
        {
            "original_path": str(residue.resolve()),
            "quarantine_path": str(quarantine),
            "reason": "active_recovery_path",
        }
    ]
    assert str(quarantine) in result.data["protected"]
    assert _changed_paths(result) == ()
    assert "deferred 1" in result.message.lower()

    monkeypatch.setattr(tool, "_purge_staged", original_purge)
    assert recovery_store.delete_task("purge-active") is True
    retried = tool.run(context)

    assert _status(retried) == "success"
    assert not quarantine.exists()
    assert retried.data["deferred"] == []


def test_purge_holds_the_write_lock_until_quarantine_deletion_finishes(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_playwright_hls"
    residue.mkdir(parents=True)
    (residue / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    assert recovery_store.recovery_counts() == {
        "active": 0,
        "pending_cleanup": 1,
    }
    original_rmtree = tool.shutil.rmtree
    writer_started = Event()
    writer_finished = Event()
    writer_finished_during_purge: list[bool] = []
    writer_errors: list[BaseException] = []
    writers: list[Thread] = []
    quarantine_paths: list[Path] = []

    def register_new_task(quarantine: Path) -> None:
        writer_started.set()
        try:
            recovery_store.register_task(
                video_id="post-purge-active",
                save_directory=quarantine,
            )
            quarantine.mkdir(parents=True, exist_ok=True)
            (quarantine / "new.bin").write_bytes(b"new")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def purge_with_concurrent_registration(quarantine: Path) -> None:
        quarantine_paths.append(quarantine)
        writer = Thread(
            target=register_new_task,
            args=(quarantine,),
            daemon=True,
        )
        writers.append(writer)
        writer.start()
        assert writer_started.wait(timeout=2.0)
        writer_finished_during_purge.append(writer_finished.wait(timeout=0.1))
        original_rmtree(quarantine)

    monkeypatch.setattr(tool.shutil, "rmtree", purge_with_concurrent_registration)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)
    for writer in writers:
        writer.join(timeout=5.0)

    assert _status(result) == "success"
    assert writer_finished_during_purge == [False]
    assert all(not writer.is_alive() for writer in writers)
    assert writer_errors == []
    assert len(quarantine_paths) == 1
    quarantine = quarantine_paths[0]
    assert (quarantine / "new.bin").read_bytes() == b"new"
    assert not (quarantine / "old.bin").exists()
    assert _active_ledger_rows(ledger)[0][:2] == (
        "post-purge-active",
        os.path.normcase(str(quarantine.resolve())),
    )
    assert _changed_paths(result) == ()


def test_success_does_not_expose_an_original_path_reused_before_purge(
    tmp_path: Path,
    tool: types.ModuleType,
    contracts: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "downloads"
    residue = workspace / "clip_curl_cffi_hls"
    residue.mkdir(parents=True)
    (residue / "old.bin").write_bytes(b"old")
    ledger = tmp_path / "download_recovery.sqlite3"
    _create_recovery_ledger(ledger, pending=((workspace, "gen-pending"),))
    recovery_store = DownloadRecoveryStore(db_path=ledger)
    assert recovery_store.recovery_counts() == {
        "active": 0,
        "pending_cleanup": 1,
    }
    original_purge = tool._purge_staged
    quarantine_paths: list[Path] = []

    def register_original_before_purge(*args: object, **kwargs: object) -> object:
        staged = next(arg for arg in args if isinstance(arg, list))
        quarantine = staged[0][1]
        quarantine_paths.append(quarantine)
        recovery_store.register_task(
            video_id="reused-original",
            save_directory=residue,
        )
        residue.mkdir(parents=True, exist_ok=True)
        (residue / "new.bin").write_bytes(b"new")
        return original_purge(*args, **kwargs)

    monkeypatch.setattr(tool, "_purge_staged", register_original_before_purge)
    context = _context(
        contracts,
        tmp_path,
        parameters={
            "roots": [str(workspace)],
            "ledger_path": str(ledger),
            "cleanup": True,
        },
    )

    result = tool.run(context)

    assert _status(result) == "success"
    assert len(quarantine_paths) == 1
    quarantine = quarantine_paths[0]
    assert (residue / "new.bin").read_bytes() == b"new"
    assert not (residue / "old.bin").exists()
    assert not quarantine.exists()
    assert _active_ledger_rows(ledger)[0][:2] == (
        "reused-original",
        os.path.normcase(str(residue.resolve())),
    )
    assert result.data["removed"] == [str(residue.resolve())]
    assert result.data["ledger"]["path"] == str(ledger.resolve())
    assert result.data["protected"] == []
    assert result.data["deferred"] == []
    assert _changed_paths(result) == ()
