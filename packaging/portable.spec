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
# 关键：两个 EXE 用各自的图标
# - 主程序（桌面 GUI 入口）用 favicon.ico（项目主品牌图标）
# - WebUI 入口用 Web.ico（保持 Web 品牌，与 web_entry 托盘图标一致）
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
# 包含 docs（用于 README / 帮助文档），但排除 INTERACTION_MAP.md（太大且非运行时所需）
datas += optional_tree(project_root / "README.md", ".")
# 注意：cli/skill/ 下的 SKILL.md 不必打包（AI 工具独立读取仓库）

# 关键修复：把 entry/ 和 cli/ 整个子包作为 data 文件直接打进 _internal
# 仅靠 hiddenimports 还不够——PyInstaller 的 collect_submodules 必须在 spec
# 解析时能 import 这些包；用户把 entry/ 设计成动态加载的薄入口层，
# 主脚本 main.py 不会静态 import 它，所以必须用 datas 方式把整个目录复制过去
datas += optional_tree(project_root / "entry", "entry")
datas += optional_tree(project_root / "cli", "cli")
datas += optional_tree(project_root / "ucrawl", "ucrawl")

if browser_root.exists():
    datas.append((str(browser_root), "ms-playwright"))

# 关键修复：把项目内所有需要 import 的子包都列进 hiddenimports
# 否则 PyInstaller 静态扫描可能漏掉（特别是 entry/ 这种动态加载）
hiddenimports = sorted(
    set(
        # 主项目
        collect_submodules("app")
        + collect_submodules("cli")
        + collect_submodules("cli.commands")
        + collect_submodules("entry")
        + collect_submodules("ucrawl")
        # 第三方依赖（部分需要手动提示）
        + collect_submodules("playwright")
        + collect_submodules("pyee")
        + collect_submodules("greenlet")
        + collect_submodules("uvicorn")
        + collect_submodules("fastapi")
        + collect_submodules("starlette")
        + collect_submodules("pydantic")
        # 关键修复：PyQt6 必须显式列出（修复 web 打包后没反应 + dispatcher Qt 弹窗）
        # entry.web_entry 用了 QSystemTrayIcon / QInputDialog / QApplication
        # entry.dispatcher 在 IDE 场景下用 QMessageBox / QDialog
        # PyInstaller 静态扫描可能漏掉（动态 import）
        + collect_submodules("PyQt6")
        # entry 动态加载的具体 entry 模块（保险起见显式列）
        + ["entry.cli_entry", "entry.gui_entry", "entry.web_entry", "entry.interactive_entry", "entry.dispatcher"]
        # cli 动态加载的子命令模块（保险起见显式列）
        + ["cli.commands.search", "cli.commands.download", "cli.commands.scan", "cli.commands.interactive"]
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

# 关键修复：两个 EXE 各自用**直接启动器**，完全绕过 dispatcher。
# 之前版本让 EXE 走 dispatcher（注入 --mode web/gui），但 dispatcher 透传
# 参数时把空 list [] 误转成 None，导致 web_entry.main(None) 回退到
# sys.argv[1:]，里面残留的 --mode 被 web_entry 的 argparse 拒绝
# （错误：unrecognized arguments: --mode web）。
# 现在的做法：每个 EXE 直接 import 对应 entry 模块，调用其 main(argv)。
#
# - UniversalCrawlerPro.exe -> entry.gui_entry.main()  (PyQt6 桌面 GUI)
# - CrawlerWebPortal.exe    -> entry.web_entry.main()  (FastAPI + Qt 托盘)

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

# 桌面 GUI 主程序 EXE：把 main.py 入口替换为 GUI 启动器
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

# WebUI 入口程序 EXE：把 main.py 入口替换为 WebUI 启动器
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
