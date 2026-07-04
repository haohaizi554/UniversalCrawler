"""Shared UI icon registry for GUI and WebUI.

The files live under ``UI/icon`` and are also mounted by the WebUI at
``/ui-icon``.  Keep logical names here so widgets and web endpoints do not
guess file names independently.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping

ICON_DIR = Path("UI/icon")
ICON_ROUTE = "/ui-icon"
FALLBACK_ICON_FILE = "view_grid.png"

ACTION_ICON_FILES: dict[str, str] = {
    "delete": "action_delete.png",
    "pause": "action_pause.png",
    "play": "action_play.png",
    "open_directory": "action_open_directory.png",
    "retry": "action_refresh.png",
    "refresh": "action_refresh.png",
    "clear_all": "action_clear-all.png",
    "copy_diagnostics": "action_copy.png",
    "start": "action_play.png",
    "stop": "action_stop.png",
    "change_directory": "action_open_directory.png",
    "theme_light": "action_theme_light.png",
    "theme_dark": "action_theme_night.png",
    "help": "action_help.png",
}

NAV_ICON_FILES: dict[str, str] = {
    "queue": "nav_download_queue.png",
    "active": "nav_downloading.png",
    "completed": "nav_completed.png",
    "failed": "nav_failed.png",
    "logs": "nav_log_center.png",
    "settings": "nav_settings.png",
    "toolbox": "nav_toolbox.png",
}

PLATFORM_ICON_FILES: dict[str, str] = {
    "douyin": "platform_douyin.png",
    "bilibili": "platform_bilibili.png",
    "kuaishou": "platform_kuaishou.png",
    "missav": "platform_missav.png",
    "xiaohongshu": "platform_xiaohongshu.png",
    "web": "platform_web.png",
}

TOOL_ICON_FILES: dict[str, str] = {
    "link": "tool_link_parser.png",
    "rename": "tool_batch_rename.png",
    "image": "tool_cover_extract.png",
    "music": "tool_video_to_audio.png",
    "search": "tool_duplicate_scan.png",
    "metadata": "tool_metadata_view.png",
    "convert": "tool_format_convert.png",
    "shield": "tool_file_verify.png",
}

STATUS_ICON_FILES: dict[str, str] = {
    "pending": "status_pending.png",
    "running": "status_running.png",
    "success": "status_success.png",
    "failed": "status_failed.png",
    "warning": "status_warning.png",
    "timeout": "status_timeout.png",
    "merging": "status_merging.png",
    "locked": "status_locked.png",
    "network_warning": "status_network_warning.png",
}

LOG_LEVEL_ICON_FILES: dict[str, str] = {
    "INFO": "log_level_info.png",
    "WARN": "log_level_warn.png",
    "WARNING": "log_level_warn.png",
    "ERROR": "log_level_error.png",
}

def safe_icon_file(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> str:
    """Return a relative icon file name, blocking path traversal."""
    name = str(file_name or "").strip().replace("\\", "/")
    if not name or "/" in name or name in {".", ".."} or ".." in name:
        return fallback
    return name

def ui_icon_path(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> str:
    return str(ICON_DIR / safe_icon_file(file_name, fallback=fallback))

def ui_icon_search_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parents[2])
    roots.append(Path.cwd())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen:
            unique.append(root)
            seen.add(key)
    return unique

def resolve_ui_icon_path(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> Path | None:
    relative = ICON_DIR / safe_icon_file(file_name, fallback=fallback)
    for root in ui_icon_search_roots():
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None

def ui_icon_url(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> str:
    return f"{ICON_ROUTE}/{safe_icon_file(file_name, fallback=fallback)}"

def action_icon_file(action_id: str, fallback: str = FALLBACK_ICON_FILE) -> str:
    return ACTION_ICON_FILES.get(str(action_id), fallback)

def nav_icon_file(page_id: str, fallback: str = FALLBACK_ICON_FILE) -> str:
    return NAV_ICON_FILES.get(str(page_id), fallback)

def platform_icon_file(platform_id: str, fallback: str = "platform_web.png") -> str:
    return PLATFORM_ICON_FILES.get(str(platform_id).lower(), fallback)

QUEUE_STATUS_ICON_FILES: dict[str, str] = {
    "待下载": "status_to-be-downloaded.png",
    "排队中": "status_merging.png",
    "待解析": "status_locked.png",
    "已解析": "status_success.png",
    "失败": "status_failed.png",
}

def queue_status_icon_file(status_label: str, fallback: str = "status_pending.png") -> str:
    label = str(status_label or "").strip()
    if label in QUEUE_STATUS_ICON_FILES:
        return QUEUE_STATUS_ICON_FILES[label]
    if "失败" in label or "错误" in label:
        return STATUS_ICON_FILES.get("failed", fallback)
    if "完成" in label:
        return STATUS_ICON_FILES.get("success", fallback)
    if "下载" in label or "运行" in label:
        return STATUS_ICON_FILES.get("running", fallback)
    return fallback

def tool_icon_file(icon_id: str, fallback: str = "nav_toolbox.png") -> str:
    return TOOL_ICON_FILES.get(str(icon_id), fallback)

def icon_manifest() -> dict[str, Mapping[str, str] | str]:
    return {
        "route": ICON_ROUTE,
        "fallback": FALLBACK_ICON_FILE,
        "actions": dict(ACTION_ICON_FILES),
        "nav": dict(NAV_ICON_FILES),
        "platforms": dict(PLATFORM_ICON_FILES),
        "queue_status": dict(QUEUE_STATUS_ICON_FILES),
        "tools": dict(TOOL_ICON_FILES),
        "status": dict(STATUS_ICON_FILES),
        "log_levels": dict(LOG_LEVEL_ICON_FILES),
    }
