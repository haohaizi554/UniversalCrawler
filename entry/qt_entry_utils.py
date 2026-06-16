"""Qt 入口共享工具。

集中放置多个入口模块都会复用的 Qt 图标与 Windows AppUserModelID 逻辑，
避免 `dispatcher` / `web_entry` / `gui_entry` 各自维护一份近似实现。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon


MAIN_APP_USER_MODEL_ID = "ucrawl.universalcrawlerpro.main"
WEB_APP_USER_MODEL_ID = "ucrawl.universalcrawlerpro.web"


def _icon_search_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parent.parent)
    return roots


def resolve_icon_path(
    preferred_names: Iterable[str],
    *,
    fallback_names: Iterable[str] = (),
) -> Path | None:
    """按优先级解析入口图标文件路径。"""
    names = list(preferred_names) + [name for name in fallback_names if name not in preferred_names]
    for root in _icon_search_roots():
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def load_qt_icon(
    preferred_names: Iterable[str],
    *,
    fallback_names: Iterable[str] = (),
) -> "QIcon | None":
    """在 QApplication 创建之后加载入口图标。"""
    from PyQt6.QtGui import QIcon

    names = list(preferred_names)
    path = resolve_icon_path(names, fallback_names=fallback_names)
    if path is None:
        return None
    try:
        return QIcon(str(path))
    except Exception:
        return None


def ensure_windows_app_user_model_id(app_id: str) -> None:
    """尽早设置 Windows AppUserModelID，避免任务栏图标分组取错。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (ImportError, AttributeError, OSError):
        pass
