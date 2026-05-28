from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


APP_NAME = "UniversalCrawlerPro"
project_root = Path(SPEC).resolve().parents[1]
main_script = project_root / "main.py"
icon_file = project_root / "favicon.ico"
browser_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ms-playwright"


def optional_tree(source: Path, target_dir: str) -> list[tuple[str, str]]:
    if source.exists():
        return [(str(source), target_dir)]
    return []


datas = []
datas += optional_tree(project_root / "favicon.ico", ".")
datas += optional_tree(project_root / "ffmpeg.exe", ".")
datas += optional_tree(project_root / "N_m3u8DL-RE.exe", ".")
datas += optional_tree(project_root / "app" / "core" / "lib" / "douyin" / "js", "app/core/lib/douyin/js")

if browser_root.exists():
    datas.append((str(browser_root), "ms-playwright"))

hiddenimports = sorted(
    set(
        collect_submodules("app")
        + collect_submodules("playwright")
        + collect_submodules("pyee")
        + collect_submodules("greenlet")
    )
)

datas += copy_metadata("playwright")
datas += copy_metadata("pyee")
datas += copy_metadata("greenlet")


a = Analysis(
    [str(main_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging" / "runtime_hook.py")],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
