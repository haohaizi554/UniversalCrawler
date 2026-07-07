from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from app.debug_logger import debug_logger
from app.services.icon_registry import platform_icon_file, ui_icon_runtime_path


@dataclass(frozen=True)
class PlatformUiMeta:
    id: str
    label: str
    icon_path: str | None = None
    emoji: str | None = None
    aliases: tuple[str, ...] = ()


BUILTIN_PLATFORM_ORDER = ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu")


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


def platform_icon_file_for_id(platform_id: str, meta: PlatformUiMeta | None) -> str:
    del meta
    if platform_id == "system":
        return ""
    if not platform_id:
        return ""
    icon_file = platform_icon_file(platform_id)
    if platform_id not in builtin_platform_metas() and icon_file == "platform_web.png":
        return ""
    return icon_file


def builtin_platform_metas() -> dict[str, PlatformUiMeta]:
    return {
        "all": PlatformUiMeta("all", "全部", emoji="🌐"),
        "system": PlatformUiMeta(
            "system",
            "系统",
            icon_path=None,
            emoji="⚙️",
            aliases=("系统", "system", "gui", "applicationcontroller"),
        ),
        "douyin": PlatformUiMeta(
            "douyin",
            "抖音",
            icon_path=resolve_platform_icon_path("douyin"),
            emoji="🎵",
            aliases=("抖音", "douyin", "dy_", "aweme", "douyinspider", "douyindownloader"),
        ),
        "bilibili": PlatformUiMeta(
            "bilibili",
            "Bilibili",
            icon_path=resolve_platform_icon_path("bilibili"),
            emoji="📺",
            aliases=(
                "Bilibili",
                "bilibili",
                "bili",
                "biliapi",
                "bilibilispider",
                "bilibilidownloader",
                "bv",
                "bvid",
            ),
        ),
        "kuaishou": PlatformUiMeta(
            "kuaishou",
            "快手",
            icon_path=resolve_platform_icon_path("kuaishou"),
            emoji="⚡",
            aliases=("快手", "kuaishou", "ks_", "kuaishouspider", "kuaishoudownloader"),
        ),
        "missav": PlatformUiMeta(
            "missav",
            "MissAV",
            icon_path=resolve_platform_icon_path("missav"),
            emoji="🎬",
            aliases=("MissAV", "missav", "missavspider", "missavdownloader", "surrit"),
        ),
        "xiaohongshu": PlatformUiMeta(
            "xiaohongshu",
            "小红书",
            icon_path=resolve_platform_icon_path("xiaohongshu"),
            emoji="📕",
            aliases=("小红书", "xiaohongshu", "xhs", "redbook", "xiaohongshuspider", "xiaohongshudownloader"),
        ),
    }


def load_platform_options(
    snapshot: Mapping[str, Any] | None = None,
    *,
    allow_registry_fallback: bool = False,
) -> list[PlatformUiMeta]:
    builtins = builtin_platform_metas()
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
        elif not icon_path and default:
            icon_path = default.icon_path
        emoji = default.emoji if default else None
        aliases = default.aliases if default else (platform_id,)
        options.append(
            PlatformUiMeta(
                id=platform_id,
                label=label,
                icon_path=icon_path,
                emoji=emoji,
                aliases=aliases,
            )
        )
        seen.add(platform_id)

    for platform_id in BUILTIN_PLATFORM_ORDER:
        if platform_id in seen:
            continue
        options.append(builtins[platform_id])
        seen.add(platform_id)

    if "system" not in seen:
        options.append(builtins["system"])
    return options
