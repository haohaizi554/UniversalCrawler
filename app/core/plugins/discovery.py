"""Plugin auto-discovery via __init_subclass__ SPI, entry_points, and external directory scanning."""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePlugin

# ---------------------------------------------------------------------------
# Builtin plugins (SPI — __init_subclass__)
# ---------------------------------------------------------------------------

def discover_builtin_plugins() -> list[type[BasePlugin]]:
    """Discover builtin plugin classes via SPI.

    Imports ``app.core.plugins.definitions`` which triggers
    ``BasePlugin.__init_subclass__``, auto-registering every concrete
    ``BasePlugin`` subclass.  Returns sorted classes.
    """
    from .base import BasePlugin

    # Trigger SPI auto-registration
    from . import definitions  # noqa: F401

    classes = list(BasePlugin.get_subclasses().values())
    return _sort_classes(classes)

# ---------------------------------------------------------------------------
# Entry-point plugins (pip-installed packages)
# ---------------------------------------------------------------------------

DISCOVERY_ENTRY_POINT_GROUP = "ucrawl.plugins"

def discover_entry_point_plugins() -> list[type[BasePlugin]]:
    """Discover plugins registered via ``ucrawl.plugins`` entry points."""
    from .base import BasePlugin

    classes: list[type[BasePlugin]] = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=DISCOVERY_ENTRY_POINT_GROUP)
    except (ImportError, TypeError):
        return classes

    for ep in eps:
        try:
            plugin_cls = ep.load()
            if (
                inspect.isclass(plugin_cls)
                and issubclass(plugin_cls, BasePlugin)
                and plugin_cls is not BasePlugin
            ):
                classes.append(plugin_cls)
        except Exception:
            continue

    return _sort_classes(classes)

# ---------------------------------------------------------------------------
# External-directory plugins
# ---------------------------------------------------------------------------

_EXTERNAL_PLUGIN_DIR: str | None = None
_EXTERNAL_MTIME: dict[str, float] = {}  # path → last mtime

def set_external_plugin_dir(path: str | None) -> None:
    """Set the external plugin directory.

    Pass ``None`` to disable external plugin discovery.
    """
    global _EXTERNAL_PLUGIN_DIR
    _EXTERNAL_PLUGIN_DIR = path

def get_external_plugin_dir() -> str | None:
    """Return the configured external plugin directory, or ``None``."""
    return _EXTERNAL_PLUGIN_DIR

def discover_external_plugins(
    plugin_dir: str | None = None,
    *,
    force: bool = False,
) -> list[type[BasePlugin]]:
    """Discover plugin classes from a directory of ``.py`` files.

    Each ``.py`` file in *plugin_dir* is imported via
    ``importlib.import_module`` (using a temporary sys.path entry).  Any
    concrete ``BasePlugin`` subclass defined **in that file** is collected.

    File modification times are cached so that repeated calls only re-import
    changed files (hot-reload).  Pass ``force=True`` to re-import everything.
    """
    from .base import BasePlugin

    target_dir = plugin_dir or _EXTERNAL_PLUGIN_DIR
    if not target_dir or not os.path.isdir(target_dir):
        return []

    target_dir = os.path.abspath(target_dir)
    old_mtimes = dict(_EXTERNAL_MTIME)

    classes: list[type[BasePlugin]] = []

    py_files = sorted(
        f for f in os.listdir(target_dir)
        if f.endswith(".py") and not f.startswith("_")
    )

    for fname in py_files:
        fpath = os.path.join(target_dir, fname)
        try:
            mtime = os.path.getmtime(fpath)
        except OSError:
            continue

        mod_name = f"ucrawl_ext_plugin_{fname[:-3]}"

        # Skip if unchanged
        if not force and old_mtimes.get(fpath) == mtime and mod_name in sys.modules:
            _EXTERNAL_MTIME[fpath] = mtime
            # Still collect already-loaded classes from this module
            module = sys.modules[mod_name]
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BasePlugin)
                    and obj is not BasePlugin
                    and obj.__module__ == module.__name__
                ):
                    classes.append(obj)
            continue

        # (Re-)import
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        if target_dir not in sys.path:
            sys.path.insert(0, target_dir)

        try:
            module = importlib.import_module(mod_name)
            _EXTERNAL_MTIME[fpath] = mtime
        except Exception:
            _EXTERNAL_MTIME.pop(fpath, None)
            continue

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and obj.__module__ == module.__name__
            ):
                classes.append(obj)

    return _sort_classes(classes)

# ---------------------------------------------------------------------------
# Aggregate discovery
# ---------------------------------------------------------------------------

def iter_plugin_classes() -> list[type[BasePlugin]]:
    """Discover plugin classes from all sources.

    1. Builtin SPI (``app.core.plugins.definitions``)
    2. Entry points (``ucrawl.plugins``)
    3. External directory (if configured)

    Returns classes sorted by ``(sort_order, name, class_name)``.
    """
    seen: set[str] = set()
    all_classes: list[type[BasePlugin]] = []

    for discover_fn in (
        discover_builtin_plugins,
        discover_entry_point_plugins,
        discover_external_plugins,
    ):
        for cls in discover_fn():
            pid = getattr(cls, "id", None)
            if pid and pid not in seen:
                seen.add(pid)
                all_classes.append(cls)

    return _sort_classes(all_classes)

def discover_builtin_plugin_instances() -> list:
    """Instantiate all discovered plugin classes."""
    return [cls() for cls in iter_plugin_classes()]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sort_classes(
    classes: list[type["BasePlugin"]],
) -> list[type["BasePlugin"]]:
    """Sort plugin classes by sort_order, then name, then class name."""
    return sorted(
        classes,
        key=lambda cls: (
            getattr(cls, "sort_order", 1000),
            getattr(cls, "name", cls.__name__),
            cls.__name__,
        ),
    )
