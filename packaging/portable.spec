from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


APP_NAME = "UniversalCrawlerPro"
WEBUI_NAME = "CrawlerWebPortal"
APP_DISPLAY_NAME = "Universal CrawlerPro"
WEBUI_DISPLAY_NAME = "Crawler WebPortal"
project_root = Path(SPEC).resolve().parents[1]
main_script = project_root / "main.py"
webui_script = project_root / "web_main.py"
icon_file = project_root / "favicon.ico"
webui_icon = project_root / "Web.ico"
browser_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ms-playwright"


def optional_tree(source: Path, target_dir: str) -> list[tuple[str, str]]:
    if source.exists():
        return [(str(source), target_dir)]
    return []


datas = []
datas += optional_tree(project_root / "favicon.ico", ".")
datas += optional_tree(project_root / "Web.ico", ".")
datas += optional_tree(project_root / "ffmpeg.exe", ".")
datas += optional_tree(project_root / "N_m3u8DL-RE.exe", ".")
datas += optional_tree(project_root / "app" / "core" / "lib" / "douyin" / "js", "app/core/lib/douyin/js")
datas += optional_tree(project_root / "app" / "web" / "static", "app/web/static")

if browser_root.exists():
    datas.append((str(browser_root), "ms-playwright"))

hiddenimports = sorted(
    set(
        collect_submodules("app")
        + collect_submodules("playwright")
        + collect_submodules("pyee")
        + collect_submodules("greenlet")
        + collect_submodules("uvicorn")
        + collect_submodules("fastapi")
        + collect_submodules("starlette")
        + collect_submodules("pydantic")
        + ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on"]
    )
)

datas += copy_metadata("playwright")
datas += copy_metadata("pyee")
datas += copy_metadata("greenlet")
datas += copy_metadata("fastapi")
datas += copy_metadata("pydantic")


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

# GUI 主程序
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

# WebUI 入口程序
# 替换 scripts TOC 中的入口脚本：把 main.py 换成 webui_entry.py
webui_scripts = []
for name, path, typecode in a.scripts:
    if typecode == "PYSOURCE" and str(main_script) in str(path):
        webui_scripts.append(("web_main", str(webui_script), "PYSOURCE"))
    else:
        webui_scripts.append((name, path, typecode))

webui_exe = EXE(
    pyz,
    webui_scripts,
    [],
    exclude_binaries=True,
    name=WEBUI_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(webui_icon) if webui_icon.exists() else (str(icon_file) if icon_file.exists() else None),
)

coll = COLLECT(
    exe,
    webui_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
