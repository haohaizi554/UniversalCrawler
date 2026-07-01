"""Local file-system actions used by frontend commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_data_root


def truncate_latest_debug_log(*, latest_file: str | Path | None = None) -> None:
    try:
        Path(latest_file or debug_logger.latest_file).write_text("", encoding="utf-8")
    except OSError:
        pass


def export_latest_debug_log(
    *,
    latest_file: str | Path | None = None,
    export_root: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    source = Path(latest_file or debug_logger.latest_file)
    export_dir = Path(export_root) if export_root is not None else user_data_root() / "Exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now)().strftime("%Y%m%d_%H%M%S")
    target = export_dir / f"latest_debug_{timestamp}.log"
    if source.exists():
        shutil.copyfile(source, target)
    else:
        target.write_text("", encoding="utf-8")
    return target


def open_file_path(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    _open_system_path(str(target))


def open_directory_with_system(directory: str | Path) -> None:
    _open_system_path(str(directory))


def current_executable_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.argv[0]


def _open_system_path(path: str) -> None:
    if os.name == "nt":
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise OSError("os.startfile is unavailable")
        startfile(path)
        return
    subprocess.Popen(["xdg-open", path])
