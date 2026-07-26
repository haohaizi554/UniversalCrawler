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

from .contracts import ToolManifest, ToolPlugin

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


class ToolRegistry:
    """Owns immutable tool snapshots and reloads trusted local extensions."""

    def __init__(
        self,
        tools: list[ToolPlugin] | None = None,
        *,
        external_dir: str | os.PathLike[str] | None = None,
        include_builtins: bool = True,
        include_entry_points: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._tools: dict[str, ToolPlugin] = {}
        self._origins: dict[str, str] = {}
        self._external_ids: set[str] = set()
        override = os.environ.get(TOOL_PLUGIN_ROOT_ENV, "").strip()
        self.external_dir = Path(external_dir or override).expanduser() if external_dir or override else None
        self._include_builtins = bool(include_builtins)
        self._include_entry_points = bool(include_entry_points)

        if tools is not None:
            for tool in tools:
                self.register(tool, origin="explicit")
        else:
            self._load_static_sources()
        if self.external_dir is not None:
            self.reload_external()

    def register(self, tool: ToolPlugin, *, origin: str = "runtime", replace: bool = False) -> None:
        normalized = _coerce_tool(tool)
        tool_id = normalized.manifest.id
        with self._lock:
            if tool_id in self._tools and not replace:
                raise ValueError(f"duplicate tool id: {tool_id}")
            self._tools[tool_id] = normalized
            self._origins[tool_id] = str(origin)

    def unregister(self, tool_id: str) -> bool:
        normalized = str(tool_id or "").strip().lower()
        with self._lock:
            removed = self._tools.pop(normalized, None) is not None
            self._origins.pop(normalized, None)
            self._external_ids.discard(normalized)
            return removed

    def get(self, tool_id: str) -> ToolPlugin | None:
        with self._lock:
            return self._tools.get(str(tool_id or "").strip().lower())

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
        return [tool.manifest.to_dict() for tool in self.list()]

    def reload_external(self, *, force: bool = False) -> ToolReloadResult:
        del force  # Every explicit reload reads source directly; no stale bytecode cache is used.
        target = self.external_dir
        discovered: dict[str, ToolPlugin] = {}
        errors: list[str] = []
        if target is not None and target.is_dir():
            for path in sorted(target.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    module = _load_source_module(path)
                    for tool in _tools_from_object(module):
                        tool_id = tool.manifest.id
                        if tool_id in discovered:
                            raise ValueError(f"duplicate external tool id: {tool_id}")
                        discovered[tool_id] = tool
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")

        with self._lock:
            previous = set(self._external_ids)
            current = set(discovered)
            added = current - previous
            removed = previous - current
            updated = current & previous
            for tool_id in removed:
                if self._origins.get(tool_id, "").startswith("external:"):
                    self._tools.pop(tool_id, None)
                    self._origins.pop(tool_id, None)
            for tool_id, tool in discovered.items():
                origin = self._origins.get(tool_id, "")
                if tool_id in self._tools and tool_id not in previous and not origin.startswith("external:"):
                    errors.append(f"{tool_id}: conflicts with {origin or 'registered tool'}")
                    added.discard(tool_id)
                    continue
                self._tools[tool_id] = tool
                self._origins[tool_id] = f"external:{target}"
            self._external_ids = {
                tool_id
                for tool_id in current
                if self._origins.get(tool_id, "").startswith("external:")
            }
        return ToolReloadResult(
            tuple(sorted(added)),
            tuple(sorted(updated)),
            tuple(sorted(removed)),
            tuple(errors),
        )

    def _load_static_sources(self) -> None:
        if self._include_builtins:
            for tool in discover_builtin_tools():
                self.register(tool, origin="builtin")
        if self._include_entry_points:
            for tool in discover_entry_point_tools():
                self.register(tool, origin="entry_point")


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


def discover_entry_point_tools() -> list[ToolPlugin]:
    tools: list[ToolPlugin] = []
    try:
        discovered = entry_points(group=TOOL_ENTRY_POINT_GROUP)
    except (ImportError, TypeError):
        return []
    for entry_point in discovered:
        try:
            tools.extend(_tools_from_object(entry_point.load()))
        except Exception:
            continue
    return _deduplicate(tools)


def _load_source_module(path: Path) -> ModuleType:
    source = path.read_text(encoding="utf-8-sig")
    fingerprint = f"{path.stat().st_mtime_ns:x}_{path.stat().st_size:x}"
    module_name = f"ucrawl_external_tool_{path.stem}_{fingerprint}"
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
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
