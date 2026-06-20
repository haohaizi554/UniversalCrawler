"""Qt runtime helpers shared by GUI, Web tray, and entry adapters."""

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
    roots.append(Path(__file__).resolve().parents[2])
    return roots

def resolve_icon_path(
    preferred_names: Iterable[str],
    *,
    fallback_names: Iterable[str] = (),
) -> Path | None:
    """Resolve the first existing icon path in bundle/project roots."""
    preferred = list(preferred_names)
    names = preferred + [name for name in fallback_names if name not in preferred]
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
    """Load a QIcon after QApplication has been created."""
    from PyQt6.QtGui import QIcon

    path = resolve_icon_path(preferred_names, fallback_names=fallback_names)
    if path is None:
        return None
    try:
        return QIcon(str(path))
    except Exception:
        return None

def ensure_windows_app_user_model_id(app_id: str) -> None:
    """Set Windows AppUserModelID so taskbar grouping/icon resolution is stable."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (ImportError, AttributeError, OSError):
        pass
