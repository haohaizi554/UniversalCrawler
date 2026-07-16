"""构建双入口 PyInstaller 便携版，并校验冻结目录的运行时完整性。"""

from __future__ import annotations

import os
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    from project_meta import (
        APP_DISPLAY_NAME,
        APP_EXE_NAME,
        APP_ICON_NAME,
        APP_NAME,
        REPORT_ICON_NAME,
        UPDATER_HELPER_EXE_NAME,
        FORBIDDEN_USER_DATA_BASENAMES,
        PACKAGE_VERSION,
        WEBUI_DISPLAY_NAME,
        WEBUI_EXE_NAME,
        WEBUI_ICON_NAME,
    )
    from playwright_bundle import resolve_playwright_browser_directories
else:
    from .project_meta import (
        APP_DISPLAY_NAME,
        APP_EXE_NAME,
        APP_ICON_NAME,
        APP_NAME,
        REPORT_ICON_NAME,
        UPDATER_HELPER_EXE_NAME,
        FORBIDDEN_USER_DATA_BASENAMES,
        PACKAGE_VERSION,
        WEBUI_DISPLAY_NAME,
        WEBUI_EXE_NAME,
        WEBUI_ICON_NAME,
    )
    from .playwright_bundle import resolve_playwright_browser_directories

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "packaging" / "portable.spec"
DIST_ROOT = PROJECT_ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME
BUILD_DIR = PROJECT_ROOT / "build"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
BROWSER_DIR = LOCALAPPDATA / "ms-playwright"
PORTABLE_ROOT_DOCS = ("README.md", "README_EN.md")
PYTHON_DLL_DIR = Path(sys.base_prefix) / "DLLs"
PYTHON_SQLITE_RUNTIME_FILES = ("_sqlite3.pyd", "sqlite3.dll")
# 打包产物为双 EXE 直启：UniversalCrawlerPro.exe -> gui_entry，CrawlerWebPortal.exe -> web_entry。
# 自适应 dispatcher 仅用于源码 python main.py / ucrawl-auto，不用于冻结 EXE。
REQUIRED_FILES = [
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / APP_ICON_NAME,  # 主图标（桌面 EXE 用）
    PROJECT_ROOT / WEBUI_ICON_NAME,  # Web 专用图标（Web EXE 用）
    PROJECT_ROOT / REPORT_ICON_NAME,  # 代码统计报告的浏览器标签页图标
    *(PROJECT_ROOT / doc_name for doc_name in PORTABLE_ROOT_DOCS),
    PROJECT_ROOT / "ffmpeg.exe",
    PROJECT_ROOT / "ffprobe.exe",
    PROJECT_ROOT / "N_m3u8DL-RE.exe",
    *(PYTHON_DLL_DIR / file_name for file_name in PYTHON_SQLITE_RUNTIME_FILES),
    SPEC_FILE,
    PROJECT_ROOT / "shared" / "__init__.py",
    # 入口子包必须存在，否则打包后 EXE 启动崩溃
    PROJECT_ROOT / "entry" / "__init__.py",
    PROJECT_ROOT / "entry" / "dispatcher.py",
    PROJECT_ROOT / "entry" / "gui_entry.py",
    PROJECT_ROOT / "entry" / "web_entry.py",
    PROJECT_ROOT / "entry" / "cli_entry.py",
    PROJECT_ROOT / "entry" / "interactive_entry.py",
    PROJECT_ROOT / "entry" / "updater_helper.py",
    PROJECT_ROOT / "entry" / "mode_selection_ui.py",
    PROJECT_ROOT / "entry" / "web_tray_ui.py",
    PROJECT_ROOT / "entry" / "web_launch_runtime.py",
    PROJECT_ROOT / "entry" / "qt_entry_utils.py",
    PROJECT_ROOT / "entry" / "web_port_dialog.py",
]
FORBIDDEN_BASENAMES = set(FORBIDDEN_USER_DATA_BASENAMES)
# 可能占用 dist 目录的进程名
LOCKING_PROCESSES = [
    APP_EXE_NAME,
    WEBUI_EXE_NAME,
    UPDATER_HELPER_EXE_NAME,
    "ffmpeg.exe",  # ffmpeg 子进程也可能锁住 _internal 下的 dll
]

def kill_locking_processes() -> None:
    """尝试终止可能占用 dist 目录的旧进程。

    CrawlerWebPortal.exe 仍在运行时会锁住
    dist/UniversalCrawlerPro/_internal/charset_normalizer/md.cp313-win_amd64.pyd
    等 .pyd 文件，因此必须在 PyInstaller 清理前释放占用。
    """
    for proc_name in LOCKING_PROCESSES:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                check=False,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass  # 进程不存在时 taskkill 会报错，忽略

def ensure_prerequisites() -> None:
    
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise SystemExit("缺少必要文件:\n- " + "\n- ".join(missing))
    try:
        resolve_playwright_browser_directories(BROWSER_DIR)
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

def clean_previous_outputs() -> None:
    """清理 dist 根目录（不只是 APP_NAME 子目录），避免残留干扰新构建。"""
    # 1. 先杀掉占用 dist 目录的进程
    kill_locking_processes()

    # 2. 清理 build 目录
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    # 3. 清理 dist 根目录下的所有构建产物
    if DIST_ROOT.exists():
        for child in DIST_ROOT.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception as e:
                print(f"警告: 清理 {child} 失败: {e}")

    # 4. 清理 spec 生成的临时 launcher
    for launcher_name in ("_webui_launcher.py", "_gui_launcher.py", "_updater_helper_launcher.py"):
        launcher = PROJECT_ROOT / "packaging" / launcher_name
        launcher.unlink(missing_ok=True)

def run_pyinstaller() -> None:
    
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_FILE),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

def copy_python_sqlite_runtime_files() -> None:
    """强制使用当前 Python 自带的 SQLite 运行时，避免同名 DLL 被其它组件抢先收集。"""
    internal_dir = DIST_DIR / "_internal"
    if not internal_dir.exists():
        raise SystemExit(f"未找到打包内部目录: {internal_dir}")
    for file_name in PYTHON_SQLITE_RUNTIME_FILES:
        source = PYTHON_DLL_DIR / file_name
        if not source.exists():
            raise SystemExit(f"缺少 Python SQLite 运行时文件: {source}")
        shutil.copy2(source, internal_dir / file_name)

def copy_portable_root_docs() -> None:
    """把发布说明复制到便携包根目录，方便用户解压后直接阅读。"""
    if not DIST_DIR.exists():
        raise SystemExit(f"未找到绿色版输出目录: {DIST_DIR}")
    for doc_name in PORTABLE_ROOT_DOCS:
        source = PROJECT_ROOT / doc_name
        if not source.exists():
            raise SystemExit(f"缺少随包说明源文件: {source}")
        shutil.copy2(source, DIST_DIR / doc_name)

def verify_output() -> None:
    """验证构建产物中入口模块必需的子包都存在，避免 EXE 启动时 ImportError。"""
    exe_path = DIST_DIR / APP_EXE_NAME
    if not exe_path.exists():
        raise SystemExit(f"未找到绿色版主程序: {exe_path}")

    webui_path = DIST_DIR / WEBUI_EXE_NAME
    if not webui_path.exists():
        raise SystemExit(f"未找到 WebUI 入口程序: {webui_path}")

    updater_helper_path = DIST_DIR / UPDATER_HELPER_EXE_NAME
    if not updater_helper_path.exists():
        raise SystemExit(f"未找到更新 helper: {updater_helper_path}")

    for readme_name in PORTABLE_ROOT_DOCS:
        if not (DIST_DIR / readme_name).exists():
            raise SystemExit(f"缺少随包说明文件: {readme_name}")

    for required_name in ("ffmpeg.exe", "ffprobe.exe", "N_m3u8DL-RE.exe"):
        matches = list(DIST_DIR.glob(f"**/{required_name}"))
        if not matches:
            raise SystemExit(f"缺少运行依赖: {required_name}")

    chrome_candidates = list(DIST_DIR.glob("**/chrome.exe"))
    if not chrome_candidates:
        raise SystemExit("未在输出目录中找到 Chromium 内核，绿色版无法做到即开即用。")

    # 冻结程序仍会动态导入入口、CLI 和共享协议，因此构建后必须逐项校验这些子包。
    internal = DIST_DIR / "_internal"
    # entry 子包需要 entry/__init__.py 和 entry/dispatcher.py
    entry_pkg = internal / "entry"
    if not entry_pkg.exists():
        raise SystemExit(
            "未找到打包后的子包: entry\n"
            "EXE 启动将因 ImportError 崩溃，请检查 portable.spec 的 datas。"
        )
    for required_module in ("__init__.py", "dispatcher.py"):
        if not (entry_pkg / required_module).exists():
            raise SystemExit(
                f"子包 entry 缺少关键模块: {required_module}"
            )
    # cli 子包需要 cli/__init__.py（其它子命令模块不是必须的，按需 lazy import）
    cli_pkg = internal / "cli"
    if not cli_pkg.exists():
        raise SystemExit(
            "未找到打包后的子包: cli\n"
            "EXE 启动后调用 ucrawl 命令时会崩溃。"
        )
    if not (cli_pkg / "__init__.py").exists():
        raise SystemExit("子包 cli 缺少关键模块: __init__.py")

    shared_pkg = internal / "shared"
    if not shared_pkg.exists():
        raise SystemExit(
            "未找到打包后的子包: shared\n"
            "EXE 启动将因 ImportError 崩溃，请检查 portable.spec 的 datas。"
        )
    if not (shared_pkg / "__init__.py").exists():
        raise SystemExit("子包 shared 缺少关键模块: __init__.py")

    for file_name in PYTHON_SQLITE_RUNTIME_FILES:
        source = PYTHON_DLL_DIR / file_name
        target = internal / file_name
        if not target.exists():
            raise SystemExit(f"缺少 Python SQLite 运行时文件: {file_name}")
        if not filecmp.cmp(source, target, shallow=False):
            raise SystemExit(
                f"Python SQLite 运行时文件不匹配: {target}\n"
                f"请重新运行 `python packaging/build_portable.py`。"
            )

    for path in DIST_DIR.glob("**/*"):
        if path.is_file() and path.name.lower() in FORBIDDEN_BASENAMES:
            raise SystemExit(f"发现不应打包的用户数据文件: {path}")

def write_manifest() -> None:
    
    manifest = DIST_DIR / "BUILD_INFO.txt"
    lines = [
        f"{APP_DISPLAY_NAME} Portable Build v{PACKAGE_VERSION}",
        f"Package Version: {PACKAGE_VERSION}",
        f"Executable: {APP_EXE_NAME}",
        f"WebUI: {WEBUI_EXE_NAME}",
        f"Updater Helper: {UPDATER_HELPER_EXE_NAME}",
        "",
        "启动方式（双 EXE 直启）：",
        f"- 双击 {APP_EXE_NAME}       → {APP_DISPLAY_NAME} 桌面 GUI",
        f"- 双击 {WEBUI_EXE_NAME} → {WEBUI_DISPLAY_NAME}（FastAPI + 托盘）",
        f"- {UPDATER_HELPER_EXE_NAME} 由 GUI 更新流程自动调用，请勿手动运行",
        "- CLI / 交互式模式请使用源码环境：ucrawl / ucrawl-i，或 python main.py --mode cli",
        "",
        "Bundled tools:",
        "- ffmpeg.exe",
        "- ffprobe.exe",
        "- N_m3u8DL-RE.exe",
        "- Playwright Chromium (ms-playwright)",
        "",
        "Excluded user data:",
        *(f"- {name}" for name in FORBIDDEN_USER_DATA_BASENAMES),
        "",
        "Runtime user data directory:",
        rf"- %LOCALAPPDATA%\{APP_NAME}",
    ]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

def main() -> None:
    ensure_prerequisites()
    clean_previous_outputs()
    run_pyinstaller()
    copy_python_sqlite_runtime_files()
    copy_portable_root_docs()
    verify_output()
    write_manifest()
    print(f"绿色版构建完成: {DIST_DIR}")

if __name__ == "__main__":
    main()
