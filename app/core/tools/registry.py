"""Thread-safe tool discovery and trusted-directory hot reload."""

from __future__ import annotations

import inspect
import os
import pkgutil
import sys
import threading
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

from shared.execution_profile import ExecutionProfile

from .contracts import ToolDescriptor, ToolManifest, ToolPlugin

TOOL_ENTRY_POINT_GROUP = "ucrawl.tools"
TOOL_PLUGIN_ROOT_ENV = "UCRAWL_TOOL_PLUGIN_ROOT"


@dataclass(frozen=True, slots=True)
class ToolReloadResult:
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added": list(self.added),
            "updated": list(self.updated),
            "removed": list(self.removed),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class _ExternalSourceState:
    module_key: str
    module: ModuleType
    tools: dict[str, ToolPlugin]


class ToolRegistry:
    """Owns immutable tool snapshots and reloads trusted local extensions."""

    def __init__(
        self,
        tools: list[ToolPlugin] | None = None,
        *,
        external_dir: str | os.PathLike[str] | None = None,
        include_builtins: bool = True,
        include_entry_points: bool = False,
        enable_external: bool = False,
        execution_profile: ExecutionProfile | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._reload_lock = threading.Lock()
        self._reload_owner_thread_id: int | None = None
        self._snapshot_revision = 0
        self._tools: dict[str, ToolPlugin] = {}
        self._origins: dict[str, str] = {}
        self._external_ids: set[str] = set()
        self._external_sources: dict[Path, _ExternalSourceState] = {}
        self._external_module_namespace = uuid4().hex
        self._external_module_serial = 0
        self._execution_profile = execution_profile
        self._external_enabled = bool(
            enable_external
            and execution_profile is not None
            and execution_profile.allow_external_plugins
        )
        self.external_dir: Path | None = None
        if self._external_enabled:
            override = os.environ.get(TOOL_PLUGIN_ROOT_ENV, "").strip()
            configured_dir = external_dir or override
            if configured_dir:
                self.external_dir = Path(configured_dir).expanduser().resolve()
        self._include_builtins = bool(include_builtins)
        self._include_entry_points = bool(include_entry_points)

        if tools is not None:
            for tool in tools:
                self.register(tool)
        else:
            self._load_static_sources()
        if self._external_enabled and self.external_dir is not None:
            self.reload_external()

    def register(self, tool: ToolPlugin, *, replace: bool = False) -> None:
        """Register an explicitly supplied tool with host-owned provenance."""

        self._register(tool, provenance="explicit", replace=replace)

    def _register(
        self,
        tool: ToolPlugin,
        *,
        provenance: str,
        replace: bool = False,
    ) -> None:
        normalized = _coerce_tool(tool)
        tool_id = normalized.manifest.id
        with self._lock:
            if tool_id in self._tools and not replace:
                raise ValueError(f"duplicate tool id: {tool_id}")
            detached_sources = self._detach_external_tool_unlocked(tool_id)
            self._tools[tool_id] = normalized
            self._origins[tool_id] = str(provenance)
            self._snapshot_revision += 1
            for source in detached_sources:
                _remove_module_if_owned(source.module_key, source.module)

    def unregister(self, tool_id: str) -> bool:
        normalized = str(tool_id or "").strip().lower()
        with self._lock:
            removed = self._tools.pop(normalized, None) is not None
            removed_origin = self._origins.pop(normalized, None) is not None
            detached_sources = self._detach_external_tool_unlocked(normalized)
            if removed or removed_origin or detached_sources:
                self._snapshot_revision += 1
            for source in detached_sources:
                _remove_module_if_owned(source.module_key, source.module)
            return removed

    def _detach_external_tool_unlocked(
        self,
        tool_id: str,
    ) -> list[_ExternalSourceState]:
        detached_sources: list[_ExternalSourceState] = []
        self._external_ids.discard(tool_id)
        for path, source in tuple(self._external_sources.items()):
            if tool_id not in source.tools:
                continue
            remaining = dict(source.tools)
            remaining.pop(tool_id, None)
            if remaining:
                self._external_sources[path] = _ExternalSourceState(
                    module_key=source.module_key,
                    module=source.module,
                    tools=remaining,
                )
            else:
                self._external_sources.pop(path, None)
                detached_sources.append(source)
        return detached_sources

    def get(self, tool_id: str) -> ToolPlugin | None:
        descriptor = self.descriptor(tool_id)
        return descriptor.tool if descriptor is not None else None

    def descriptor(self, tool_id: str) -> ToolDescriptor | None:
        normalized = str(tool_id or "").strip().lower()
        with self._lock:
            tool = self._tools.get(normalized)
            provenance = self._origins.get(normalized, "")
        if tool is None:
            return None
        return ToolDescriptor(tool=tool, provenance=provenance)

    def list(self) -> list[ToolPlugin]:
        with self._lock:
            tools = list(self._tools.values())
        return sorted(
            tools,
            key=lambda tool: (
                int(tool.manifest.sort_order),
                str(tool.manifest.category),
                str(tool.manifest.title).casefold(),
                tool.manifest.id,
            ),
        )

    def manifests(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                (tool, self._origins.get(tool.manifest.id, ""))
                for tool in self._tools.values()
            ]
        rows.sort(
            key=lambda row: (
                int(row[0].manifest.sort_order),
                str(row[0].manifest.category),
                str(row[0].manifest.title).casefold(),
                row[0].manifest.id,
            )
        )
        manifests: list[dict[str, Any]] = []
        for tool, provenance in rows:
            manifest = tool.manifest.to_dict()
            manifest["provenance"] = provenance
            manifests.append(manifest)
        return manifests

    def reload_external(self, *, force: bool = False) -> ToolReloadResult:
        del force  # Every explicit reload reads source directly; no stale bytecode cache is used.
        if not self._external_enabled:
            return ToolReloadResult(errors=("external plugins are disabled",))
        target = self.external_dir
        thread_id = threading.get_ident()
        if self._reload_owner_thread_id == thread_id:
            return ToolReloadResult(errors=("external plugin reload is not reentrant",))
        with self._reload_lock:
            self._reload_owner_thread_id = thread_id
            try:
                paths: tuple[Path, ...] = ()
                if target is not None and target.is_dir():
                    paths = tuple(
                        dict.fromkeys(
                            path.resolve()
                            for path in sorted(target.glob("*.py"))
                            if not path.name.startswith("_")
                        )
                    )
                return self._reload_external_paths(target, paths)
            finally:
                self._reload_owner_thread_id = None

    def _reload_external_paths(
        self,
        target: Path | None,
        paths: tuple[Path, ...],
    ) -> ToolReloadResult:
        errors: list[str] = []
        with self._lock:
            snapshot_revision = self._snapshot_revision
            previous_sources = dict(self._external_sources)
            previous_ids = set(self._external_ids)
            previous_tools = {
                tool_id: self._tools.get(tool_id) for tool_id in previous_ids
            }

        staged: dict[Path, _ExternalSourceState] = {}
        try:
            for path in paths:
                try:
                    staged[path] = self._load_external_source(path)
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")

            with self._lock:
                if self._snapshot_revision != snapshot_revision:
                    errors.append(
                        "tool registry changed during external reload; retry required"
                    )
                    return ToolReloadResult(errors=tuple(errors))
                static_origins = {
                    tool_id: self._origins.get(tool_id, "registered tool")
                    for tool_id in self._tools
                    if not self._origins.get(tool_id, "").startswith("external:")
                }
                next_sources = _resolve_external_source_graph(
                    paths=paths,
                    staged=staged,
                    previous_sources=previous_sources,
                    static_origins=static_origins,
                    errors=errors,
                )

                current_tools = {
                    tool_id: tool
                    for source in next_sources.values()
                    for tool_id, tool in source.tools.items()
                }
                current_ids = set(current_tools)
                next_tools = dict(self._tools)
                next_origins = dict(self._origins)
                for tool_id in previous_ids:
                    if next_origins.get(tool_id, "").startswith("external:"):
                        next_tools.pop(tool_id, None)
                        next_origins.pop(tool_id, None)
                provenance = (
                    f"external:{target.resolve()}" if target is not None else "external:"
                )
                for tool_id, tool in current_tools.items():
                    next_tools[tool_id] = tool
                    next_origins[tool_id] = provenance

                added = current_ids - previous_ids
                removed = previous_ids - current_ids
                updated = {
                    tool_id
                    for tool_id in current_ids & previous_ids
                    if previous_tools.get(tool_id) is not current_tools[tool_id]
                }
                result = ToolReloadResult(
                    tuple(sorted(added)),
                    tuple(sorted(updated)),
                    tuple(sorted(removed)),
                    tuple(errors),
                )
                self._tools = next_tools
                self._origins = next_origins
                self._external_ids = current_ids
                self._external_sources = next_sources
                self._snapshot_revision += 1

                for path, source in previous_sources.items():
                    if next_sources.get(path) is not source:
                        _remove_module_if_owned(source.module_key, source.module)
                return result
        finally:
            with self._lock:
                owned_modules = {
                    source.module_key: source.module
                    for source in self._external_sources.values()
                }
            for source in staged.values():
                if owned_modules.get(source.module_key) is not source.module:
                    _remove_module_if_owned(source.module_key, source.module)

    def _load_external_source(self, path: Path) -> _ExternalSourceState:
        self._external_module_serial += 1
        module_name = _external_module_name(
            path,
            namespace=self._external_module_namespace,
            serial=self._external_module_serial,
        )
        module = _load_source_module(path, module_name=module_name)
        try:
            discovered: dict[str, ToolPlugin] = {}
            for tool in _tools_from_object(module):
                tool_id = tool.manifest.id
                if tool_id in discovered:
                    raise ValueError(f"duplicate external tool id: {tool_id}")
                discovered[tool_id] = tool
            if not discovered:
                raise ValueError("external module did not provide a valid tool")
            if sys.modules.get(module_name) is not module:
                raise RuntimeError(
                    "external module ownership changed during discovery"
                )
        except BaseException:
            try:
                _remove_module_if_owned(module_name, module)
            except BaseException:
                pass
            raise
        return _ExternalSourceState(
            module_key=module_name,
            module=module,
            tools=discovered,
        )

    def _load_static_sources(self) -> None:
        if self._include_builtins:
            for tool in discover_builtin_tools():
                self._register(tool, provenance="builtin")
        if self._include_entry_points and self._external_enabled:
            for tool, provenance in _discover_entry_point_descriptors():
                self._register(tool, provenance=provenance)


def discover_builtin_tools() -> list[ToolPlugin]:
    try:
        package = import_module("app.core.tools.builtin")
    except ImportError:
        return []
    tools: list[ToolPlugin] = []
    package_paths = list(getattr(package, "__path__", ()) or ())
    for module_info in pkgutil.iter_modules(package_paths):
        if module_info.name.startswith("_"):
            continue
        try:
            module = import_module(f"{package.__name__}.{module_info.name}")
            tools.extend(_tools_from_object(module))
        except Exception:
            continue
    return _deduplicate(tools)


def discover_entry_point_tools(
    *,
    execution_profile: ExecutionProfile | None = None,
    enabled: bool = False,
) -> list[ToolPlugin]:
    """Discover installed extensions only under an explicit host grant."""

    if not enabled or execution_profile is None or not execution_profile.allow_external_plugins:
        return []
    return _deduplicate(
        [tool for tool, _provenance in _discover_entry_point_descriptors()]
    )


def _discover_entry_point_descriptors() -> list[tuple[ToolPlugin, str]]:
    descriptors: list[tuple[ToolPlugin, str]] = []
    seen: set[str] = set()
    try:
        discovered = entry_points(group=TOOL_ENTRY_POINT_GROUP)
    except (ImportError, TypeError):
        return []
    for entry_point in discovered:
        try:
            distribution = str(
                getattr(getattr(entry_point, "dist", None), "name", "")
                or getattr(entry_point, "module", "")
                or "unknown"
            ).strip()
            for tool in _tools_from_object(entry_point.load()):
                if tool.manifest.id in seen:
                    continue
                seen.add(tool.manifest.id)
                descriptors.append((tool, f"entry_point:{distribution}"))
        except Exception:
            continue
    return descriptors


def _resolve_external_source_graph(
    *,
    paths: tuple[Path, ...],
    staged: dict[Path, _ExternalSourceState],
    previous_sources: dict[Path, _ExternalSourceState],
    static_origins: dict[str, str],
    errors: list[str],
) -> dict[Path, _ExternalSourceState]:
    """Resolve a complete reload snapshot without depending on file order."""

    current_paths = set(paths)
    candidate_paths = set(staged)
    fixed_fallbacks = {
        path
        for path in current_paths
        if path not in staged and path in previous_sources
    }
    rejected: dict[Path, str] = {}

    for path in sorted(candidate_paths, key=str):
        for tool_id in sorted(staged[path].tools):
            origin = static_origins.get(tool_id)
            if origin is None:
                continue
            rejected[path] = f"{path.name}: {tool_id}: conflicts with {origin}"
            break

    declarations: dict[str, list[Path]] = {}
    for path in sorted(candidate_paths - rejected.keys(), key=str):
        for tool_id in staged[path].tools:
            declarations.setdefault(tool_id, []).append(path)
    for tool_id in sorted(declarations):
        owners = sorted(declarations[tool_id], key=str)
        if len(owners) < 2:
            continue
        owner_names = ", ".join(path.name for path in owners)
        for path in owners:
            rejected.setdefault(
                path,
                f"{path.name}: {tool_id}: declared by multiple external sources "
                f"({owner_names})",
            )

    while True:
        fallback_paths = fixed_fallbacks | {
            path
            for path in rejected
            if path in current_paths and path in previous_sources
        }
        retained_origins = dict(static_origins)
        for path in sorted(fallback_paths, key=str):
            for tool_id in previous_sources[path].tools:
                retained_origins.setdefault(tool_id, f"external source {path.name}")

        newly_rejected: dict[Path, str] = {}
        for path in sorted(candidate_paths - rejected.keys(), key=str):
            for tool_id in sorted(staged[path].tools):
                origin = retained_origins.get(tool_id)
                if origin is None:
                    continue
                newly_rejected[path] = (
                    f"{path.name}: {tool_id}: conflicts with {origin}"
                )
                break
        if not newly_rejected:
            break
        rejected.update(newly_rejected)

    errors.extend(rejected[path] for path in sorted(rejected, key=str))
    return {
        path: staged[path]
        if path in staged and path not in rejected
        else previous_sources[path]
        for path in paths
        if (path in staged and path not in rejected) or path in previous_sources
    }


def _external_module_name(path: Path, *, namespace: str, serial: int) -> str:
    fingerprint = f"{path.stat().st_mtime_ns:x}_{path.stat().st_size:x}"
    return f"ucrawl_external_tool_{path.stem}_{namespace}_{serial:x}_{fingerprint}"


def _remove_module_if_owned(module_key: str, module: ModuleType) -> None:
    try:
        if sys.modules.get(module_key) is module:
            sys.modules.pop(module_key, None)
    except BaseException:
        return


def _load_source_module(path: Path, *, module_name: str) -> ModuleType:
    source = path.read_text(encoding="utf-8-sig")
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
        if sys.modules.get(module_name) is not module:
            raise RuntimeError("external module ownership changed during import")
    except BaseException:
        _remove_module_if_owned(module_name, module)
        raise
    return module


def _tools_from_object(value: Any) -> list[ToolPlugin]:
    if isinstance(value, ModuleType):
        candidates: list[Any] = []
        if "TOOL" in value.__dict__:
            candidates.append(value.__dict__["TOOL"])
        if "TOOLS" in value.__dict__:
            candidates.extend(list(value.__dict__["TOOLS"] or ()))
        if not candidates:
            candidates.extend(
                member
                for name, member in inspect.getmembers(value, inspect.isclass)
                if name.endswith("Tool") and member.__module__ == value.__name__
            )
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = list(value)
    else:
        candidates = [value]

    tools: list[ToolPlugin] = []
    for candidate in candidates:
        try:
            instance = candidate() if inspect.isclass(candidate) else candidate
            tools.append(_coerce_tool(instance))
        except (TypeError, ValueError):
            continue
    return tools


def _coerce_tool(value: Any) -> ToolPlugin:
    manifest = getattr(value, "manifest", None)
    if not isinstance(manifest, ToolManifest):
        raise TypeError("tool manifest must be ToolManifest")
    if not callable(getattr(value, "validate", None)) or not callable(getattr(value, "run", None)):
        raise TypeError(f"tool {manifest.id} must implement validate() and run()")
    if not callable(getattr(value, "requirements_for", None)):
        raise TypeError(f"tool {manifest.id} must implement requirements_for()")
    return value


def _deduplicate(tools: list[ToolPlugin]) -> list[ToolPlugin]:
    result: dict[str, ToolPlugin] = {}
    for tool in tools:
        result.setdefault(tool.manifest.id, tool)
    return list(result.values())


__all__ = [
    "TOOL_ENTRY_POINT_GROUP",
    "TOOL_PLUGIN_ROOT_ENV",
    "ToolRegistry",
    "ToolReloadResult",
    "discover_builtin_tools",
    "discover_entry_point_tools",
]
