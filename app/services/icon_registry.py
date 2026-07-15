"""基于 shared 图标名称契约解析开发目录、打包目录和 Web URL。"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.icon_contract import FALLBACK_ICON_FILE, ICON_ROUTE, safe_icon_file

ICON_DIR = Path("UI/icon")


def ui_icon_path(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> str:
    return str(ICON_DIR / safe_icon_file(file_name, fallback=fallback))


def ui_icon_runtime_path(file_name: str | None, fallback: str = FALLBACK_ICON_FILE) -> str:
    root = getattr(sys, "_MEIPASS", None)
    base = Path(root) if root else Path(__file__).parents[2]
    return str(base / ICON_DIR / safe_icon_file(file_name, fallback=fallback))


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
