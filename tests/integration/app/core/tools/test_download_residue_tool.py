from __future__ import annotations

import importlib.util
import inspect
import os
import sqlite3
import sys
import types
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[5]
MODULE_PATH = PROJECT_ROOT / "app" / "core" / "tools" / "builtin" / "download_residue.py"
CONTRACTS_PATH = PROJECT_ROOT / "app" / "core" / "tools" / "contracts.py"


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
    context = contracts.ToolContext(
        parameters={"roots": [str(workspace)], "cleanup": True},
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
        active=(
            ("owned", workspace, "gen-owned"),
            ("unrelated", unrelated, "gen-unrelated"),
        ),
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
    assert set(_changed_paths(result)) == {
        str(nm3u8.resolve()),
        str(curl.resolve()),
        str(ledger.resolve()),
    }


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


def test_ledger_disappearing_before_commit_does_not_create_a_phantom_database(
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
    original_stage = tool._stage_artifacts

    def stage_then_remove_ledger(*args: object, **kwargs: object):
        staged = original_stage(*args, **kwargs)
        ledger.unlink()
        return staged

    monkeypatch.setattr(tool, "_stage_artifacts", stage_then_remove_ledger)
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
    original_stage = tool._stage_artifacts

    def stage_then_replace_generation(*args: object, **kwargs: object):
        staged = original_stage(*args, **kwargs)
        with closing(sqlite3.connect(ledger)) as conn, conn:
            conn.execute(
                """
                UPDATE pending_cleanup_directories
                SET generation = 'new-generation'
                WHERE save_directory = ?
                """,
                (str(workspace.resolve()),),
            )
        return staged

    monkeypatch.setattr(tool, "_stage_artifacts", stage_then_replace_generation)
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
