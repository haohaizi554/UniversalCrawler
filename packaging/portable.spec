from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

_packaging_dir = Path(SPEC).resolve().parent
if str(_packaging_dir) not in sys.path:
    sys.path.insert(0, str(_packaging_dir))
from project_meta import APP_DISPLAY_NAME, APP_ICON_NAME, APP_NAME, UPDATER_HELPER_NAME, WEBUI_DISPLAY_NAME, WEBUI_ICON_NAME, WEBUI_NAME

project_root = Path(SPEC).resolve().parents[1]
main_script = project_root / "main.py"
# 两个 EXE 必须使用各自的图标，避免桌面端与 WebUI 在任务栏中混用品牌资源。
# - 主程序（桌面 GUI 入口）用 favicon.ico（项目主品牌图标）
# - WebUI 入口用 Web.ico（保持 Web 品牌，与 web_entry 托盘图标一致）
icon_file = project_root / APP_ICON_NAME
webui_icon = project_root / WEBUI_ICON_NAME
browser_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ms-playwright"
python_dll_dir = Path(sys.base_prefix) / "DLLs"
python_sqlite_runtime_files = (python_dll_dir / "_sqlite3.pyd", python_dll_dir / "sqlite3.dll")


def optional_tree(source: Path, target_dir: str) -> list[tuple[str, str]]:
    if source.exists():
        return [(str(source), target_dir)]
    return []


datas = []
datas += optional_tree(project_root / APP_ICON_NAME, ".")
datas += optional_tree(project_root / WEBUI_ICON_NAME, ".")
datas += optional_tree(project_root / "ffmpeg.exe", ".")
datas += optional_tree(project_root / "ffprobe.exe", ".")
datas += optional_tree(project_root / "N_m3u8DL-RE.exe", ".")
datas += optional_tree(project_root / "app" / "core" / "lib" / "douyin" / "js", "app/core/lib/douyin/js")
datas += optional_tree(project_root / "app" / "web" / "static", "app/web/static")
datas += optional_tree(project_root / "UI" / "icon", "UI/icon")
# 包含 docs（用于 README / 帮助文档），但排除 INTERACTION_MAP.md（太大且非运行时所需）
datas += optional_tree(project_root / "README.md", ".")
datas += optional_tree(project_root / "README_EN.md", ".")
# 注意：cli/skill/ 下的 SKILL.md 不必打包（AI 工具独立读取仓库）

# entry/ 与 cli/ 是动态加载的薄入口，main.py 不会静态导入全部模块。
# collect_submodules 又要求 spec 解析时包可导入，因此还需通过 datas 把完整目录
# 放入 _internal，不能只依赖 hiddenimports。
datas += optional_tree(project_root / "entry", "entry")
datas += optional_tree(project_root / "cli", "cli")
datas += optional_tree(project_root / "shared", "shared")
datas += optional_tree(project_root / "ucrawl", "ucrawl")

if browser_root.exists():
    datas.append((str(browser_root), "ms-playwright"))

# 所有运行时导入的项目子包都需列入 hiddenimports，防止 PyInstaller 静态扫描
# 漏掉 entry/ 等动态加载模块。
hiddenimports = sorted(
    set(
        # 主项目
        collect_submodules("app")
        + collect_submodules("cli")
        + collect_submodules("cli.commands")
        + collect_submodules("entry")
        + collect_submodules("shared")
        + collect_submodules("ucrawl")
        # 第三方依赖（部分需要手动提示）
        + collect_submodules("playwright")
        + collect_submodules("pyee")
        + collect_submodules("greenlet")
        + collect_submodules("uvicorn")
        + collect_submodules("fastapi")
        + collect_submodules("starlette")
        + collect_submodules("pydantic")
# Web 托盘与 dispatcher 的 Qt 后备路径采用动态导入，PyInstaller 静态扫描
# 可能漏掉 QSystemTrayIcon、QInputDialog、QApplication、QMessageBox 和 QDialog，
# 因此必须显式列出 PyQt6 子模块。
        + collect_submodules("PyQt6")
        # entry 动态加载的具体 entry 模块（保险起见显式列）
        + ["entry.cli_entry", "entry.gui_entry", "entry.web_entry", "entry.interactive_entry", "entry.dispatcher", "entry.updater_helper"]
        # cli 动态加载的子命令模块（保险起见显式列）
        + ["cli.commands.search", "cli.commands.download", "cli.commands.scan", "cli.commands.interactive"]
        + [
            "shared.controller_session",
            "shared.spider_session_runtime",
            "shared.cli_runner_runtime",
            "shared.runtime_options",
            "shared.selection_runtime",
        ]
        + ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on"]
        + ["PyQt6"]
    )
)

datas += copy_metadata("playwright")
datas += copy_metadata("pyee")
datas += copy_metadata("greenlet")
datas += copy_metadata("fastapi")
datas += copy_metadata("pydantic")

binaries = []
for runtime_file in python_sqlite_runtime_files:
    if runtime_file.exists():
        binaries.append((str(runtime_file), "."))


a = Analysis(
    [str(main_script)],
    pathex=[str(project_root)],
    binaries=binaries,
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

# 三个冻结 EXE 必须使用直接启动器并绕过 dispatcher，避免空 argv 在多层转发时
# 回退到 sys.argv[1:]，把打包器参数误交给目标入口的 argparse。
# - UniversalCrawlerPro.exe -> entry.gui_entry.main()      (PyQt6 桌面 GUI)
# - CrawlerWebPortal.exe    -> entry.web_entry.main()      (FastAPI + Qt 托盘)
# - updater_helper.exe      -> entry.updater_helper.main() (独立更新辅助进程)

gui_launcher_script = project_root / "packaging" / "_gui_launcher.py"
gui_launcher_script.write_text(
    '''#!/usr/bin/env python3
"""UniversalCrawlerPro.exe 入口：直接启动 GUI 模式。
由 packaging/portable.spec 在打包时自动生成。

设计要点：
- 直接调用 entry.gui_entry.main()，完全绕过 dispatcher。
- 双击 EXE 时**直接进入 GUI**，不再弹"模式选择菜单"（TUI 或 Qt 弹窗）。
- 用户从命令行传入的参数原样透传给 gui_entry（虽然 GUI 模式不消费参数，
  但保持与其它 entry 一致的 argv 转发语义）。
"""
import sys

from entry.gui_entry import main as _main
sys.exit(_main(sys.argv[1:] if len(sys.argv) > 1 else None))
''',
    encoding="utf-8",
)

webui_entry_script = project_root / "packaging" / "_webui_launcher.py"
webui_entry_script.write_text(
    '''#!/usr/bin/env python3
"""CrawlerWebPortal.exe 入口：直接启动 Web 模式。
由 packaging/portable.spec 在打包时自动生成。

设计要点：
- 直接调用 entry.web_entry.main()，完全绕过 dispatcher。
  避免 dispatcher 透传 [] 时误转 None，导致 web_entry 误读 sys.argv 的 --mode。
- 用户传入的 CLI 参数（--port / --host / --no-qt / --no-browser 等）
  全部原样转发给 web_entry。
- console=False：Qt 托盘 + 端口弹窗仍可见。
"""
import sys

from entry.web_entry import main as _main
sys.exit(_main(sys.argv[1:] if len(sys.argv) > 1 else None))
''',
    encoding="utf-8",
)

updater_helper_script = project_root / "packaging" / "_updater_helper_launcher.py"
updater_helper_script.write_text(
    '''#!/usr/bin/env python3
"""updater_helper.exe 入口：独立安装 helper。
由 packaging/portable.spec 在打包时自动生成。
"""
import sys

from entry.updater_helper import main as _main
sys.exit(_main(sys.argv[1:]))
''',
    encoding="utf-8",
)

# 桌面 GUI 主程序 EXE 使用专用 GUI 启动器。
gui_scripts = []
for name, path, typecode in a.scripts:
    if typecode == "PYSOURCE" and str(main_script) in str(path):
        gui_scripts.append((APP_NAME, str(gui_launcher_script), "PYSOURCE"))
    else:
        gui_scripts.append((name, path, typecode))

exe = EXE(
    pyz,
    gui_scripts,
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

# WebUI 入口程序 EXE 使用专用 WebUI 启动器。
webui_scripts = []
for name, path, typecode in a.scripts:
    if typecode == "PYSOURCE" and str(main_script) in str(path):
        webui_scripts.append((WEBUI_NAME, str(webui_entry_script), "PYSOURCE"))
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
    console=False,  # 同样不弹黑窗
    disable_windowed_traceback=False,
    icon=str(webui_icon) if webui_icon.exists() else (str(icon_file) if icon_file.exists() else None),
)

updater_helper_exe = EXE(
    pyz,
    [(UPDATER_HELPER_NAME, str(updater_helper_script), "PYSOURCE")],
    [],
    exclude_binaries=True,
    name=UPDATER_HELPER_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    webui_exe,
    updater_helper_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
