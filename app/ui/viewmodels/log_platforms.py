"""GUI-specific platform option loading and runtime icon resolution."""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Any, Mapping

from app.debug_logger import debug_logger
from app.services.icon_registry import ui_icon_runtime_path
from shared.icon_contract import platform_icon_file
from shared.log_platforms import BUILTIN_PLATFORM_ORDER, PlatformUiMeta, builtin_platform_metas


def resolve_platform_icon_path(platform_id: str) -> str | None:
    return _resolve_platform_icon_path_cached(str(platform_id).lower(), _runtime_root_signature())


def _runtime_root_signature() -> str:
    return str(getattr(sys, "_MEIPASS", "") or "")


@lru_cache(maxsize=64)
def _resolve_platform_icon_path_cached(platform_id: str, _runtime_root: str) -> str | None:
    return ui_icon_runtime_path(platform_icon_file(platform_id))


@lru_cache(maxsize=128)
def _trusted_icon_path(icon_path: str, platform_id: str) -> str | None:
    if icon_path:
        return icon_path
    return _resolve_platform_icon_path_cached(platform_id, _runtime_root_signature())


def load_builtin_platform_metas() -> dict[str, PlatformUiMeta]:
    return builtin_platform_metas(resolve_platform_icon_path)


def load_platform_options(
    snapshot: Mapping[str, Any] | None = None,
    *,
    allow_registry_fallback: bool = False,
) -> list[PlatformUiMeta]:
    builtins = load_builtin_platform_metas()
    options: list[PlatformUiMeta] = [builtins["all"]]
    seen: set[str] = {"all"}
    entries: list[dict[str, Any]] = []

    snapshot = snapshot or {}
    for key in ("platforms", "plugins", "available_platforms"):
        value = snapshot.get(key)
        if isinstance(value, list) and value:
            for item in value:
                if isinstance(item, dict):
                    entries.append(item)
                elif isinstance(item, str) and item.strip():
                    entries.append({"id": item.strip()})
            break

    if not entries:
        settings = snapshot.get("settings_snapshot")
        if isinstance(settings, dict):
            platform_settings = settings.get("平台设置")
            if isinstance(platform_settings, list):
                entries.extend(item for item in platform_settings if isinstance(item, dict))

    if not entries and allow_registry_fallback:
        try:
            from app.core.plugin_registry import registry

            for plugin in registry.get_all_plugins():
                entries.append({"id": plugin.id, "name": plugin.name})
        except (ImportError, RuntimeError, AttributeError) as exc:
            debug_logger.log_exception("log_platforms", "load_plugin_entries", exc)

    for entry in entries:
        platform_id = str(entry.get("id") or entry.get("platform_id") or "").strip().lower()
        if not platform_id or platform_id in seen or platform_id == "all":
            continue
        default = builtins.get(platform_id)
        label = str(entry.get("name") or entry.get("label") or (default.label if default else platform_id))
        icon_path = str(entry.get("icon_path") or entry.get("icon") or "").strip() or None
        if icon_path:
            icon_path = _trusted_icon_path(icon_path, platform_id)
        elif default:
            icon_path = default.icon_path
        options.append(
            PlatformUiMeta(
                id=platform_id,
                label=label,
                icon_path=icon_path,
                emoji=default.emoji if default else None,
                aliases=default.aliases if default else (platform_id,),
            )
        )
        seen.add(platform_id)

    for platform_id in BUILTIN_PLATFORM_ORDER:
        if platform_id not in seen:
            options.append(builtins[platform_id])
            seen.add(platform_id)

    if "system" not in seen:
        options.append(builtins["system"])
    return options
