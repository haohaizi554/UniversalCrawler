"""Builtin plugin discovery for the core plugin registry."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import BasePlugin

_INFRA_MODULES = {"base", "registry", "run_options", "settings_builders", "discovery"}


def iter_plugin_classes() -> list[type[BasePlugin]]:
    """Discover plugin classes from non-infrastructure modules under this package."""
    package_name = __package__ or "app.core.plugins"
    package = importlib.import_module(package_name)
    discovered: dict[str, type[BasePlugin]] = {}

    for module_info in pkgutil.iter_modules(package.__path__):
        module_name = module_info.name
        if module_name.startswith("_") or module_name in _INFRA_MODULES:
            continue
        module = importlib.import_module(f"{package_name}.{module_name}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BasePlugin) or obj is BasePlugin:
                continue
            if obj.__module__ != module.__name__:
                continue
            plugin_id = getattr(obj, "id", "")
            if not plugin_id or plugin_id == BasePlugin.id:
                continue
            discovered[plugin_id] = obj

    return sorted(
        discovered.values(),
        key=lambda cls: (getattr(cls, "sort_order", 1000), getattr(cls, "name", cls.__name__), cls.__name__),
    )


def discover_builtin_plugins() -> list[BasePlugin]:
    """Instantiate all discovered builtin plugins."""
    return [plugin_cls() for plugin_cls in iter_plugin_classes()]
