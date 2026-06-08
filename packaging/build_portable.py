"""打包辅助脚本，负责 `packaging/build_portable.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    from project_meta import APP_DISPLAY_NAME, APP_NAME, PACKAGE_VERSION, WEBUI_NAME
else:
    from .project_meta import APP_DISPLAY_NAME, APP_NAME, PACKAGE_VERSION, WEBUI_NAME


WEBUI_DISPLAY_NAME = "Crawler WebPortal"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "packaging" / "portable.spec"
DIST_ROOT = PROJECT_ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME
BUILD_DIR = PROJECT_ROOT / "build"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
BROWSER_DIR = LOCALAPPDATA / "ms-playwright"
# 关键修复：原版本检查 web_main.py，但项目已重构（统一通过 main.py 自适应派发）
# 现在只需一个入口 main.py，CrawlerWebPortal.exe 启动时自动 --mode web
REQUIRED_FILES = [
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "favicon.ico",  # 主图标（桌面 EXE 用）
    PROJECT_ROOT / "Web.ico",      # Web 专用图标（Web EXE 用）
    PROJECT_ROOT / "ffmpeg.exe",
    PROJECT_ROOT / "N_m3u8DL-RE.exe",
    SPEC_FILE,
    # 自适应入口子包必须存在，否则打包后 EXE 启动崩溃
    PROJECT_ROOT / "entry" / "__init__.py",
    PROJECT_ROOT / "entry" / "dispatcher.py",
    PROJECT_ROOT / "entry" / "gui_entry.py",
    PROJECT_ROOT / "entry" / "web_entry.py",
    PROJECT_ROOT / "entry" / "cli_entry.py",
    PROJECT_ROOT / "entry" / "interactive_entry.py",
]
FORBIDDEN_BASENAMES = {
    "config.json",
    "bili_auth.json",
    "ks_auth.json",
    "dy_auth.json",
}
# 可能占用 dist 目录的进程名
LOCKING_PROCESSES = [
    f"{APP_NAME}.exe",
    f"{WEBUI_NAME}.exe",
    "ffmpeg.exe",  # ffmpeg 子进程也可能锁住 _internal 下的 dll
]


def kill_locking_processes() -> None:
    """尝试终止可能占用 dist 目录的旧进程。

    修复: 之前 build 时若 CrawlerWebPortal.exe 还在运行，会锁住
    dist/UniversalCrawlerPro/_internal/charset_normalizer/md.cp313-win_amd64.pyd
    等 .pyd 文件，导致 PyInstaller 清理失败。
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
    """执行 `ensure_prerequisites` 对应的业务逻辑。"""
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise SystemExit("缺少必要文件:\n- " + "\n- ".join(missing))
    if not BROWSER_DIR.exists():
        raise SystemExit(
            "未检测到 Playwright 浏览器目录，请先执行 `playwright install chromium`。\n"
            f"期望路径: {BROWSER_DIR}"
        )


def clean_previous_outputs() -> None:
    """执行 `clean_previous_outputs` 对应的业务逻辑。

    修复: 改为先 kill 占用进程，再清理整个 dist 根目录（不只是 APP_NAME 子目录），
    避免 dist/portable/ 或 dist/installer/ 等残留干扰新构建。
    """
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
    for launcher_name in ("_webui_launcher.py", "_gui_launcher.py"):
        launcher = PROJECT_ROOT / "packaging" / launcher_name
        launcher.unlink(missing_ok=True)


def run_pyinstaller() -> None:
    """执行 `run_pyinstaller` 对应的业务逻辑。"""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_FILE),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def verify_output() -> None:
    """执行 `verify_output` 对应的业务逻辑。

    关键修复：增加 entry/cli 子包在 _internal 中存在的检查，
    否则 EXE 启动会因 ImportError 崩溃。
    """
    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    if not exe_path.exists():
        raise SystemExit(f"未找到绿色版主程序: {exe_path}")

    webui_path = DIST_DIR / f"{WEBUI_NAME}.exe"
    if not webui_path.exists():
        raise SystemExit(f"未找到 WebUI 入口程序: {webui_path}")

    for required_name in ("ffmpeg.exe", "N_m3u8DL-RE.exe"):
        matches = list(DIST_DIR.glob(f"**/{required_name}"))
        if not matches:
            raise SystemExit(f"缺少运行依赖: {required_name}")

    chrome_candidates = list(DIST_DIR.glob("**/chrome.exe"))
    if not chrome_candidates:
        raise SystemExit("未在输出目录中找到 Chromium 内核，绿色版无法做到即开即用。")

    # 关键：验证自适应入口子包被正确打包
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

    for path in DIST_DIR.glob("**/*"):
        if path.is_file() and path.name.lower() in FORBIDDEN_BASENAMES:
            raise SystemExit(f"发现不应打包的用户数据文件: {path}")


def write_manifest() -> None:
    """执行 `write_manifest` 对应的业务逻辑。"""
    manifest = DIST_DIR / "BUILD_INFO.txt"
    lines = [
        f"{APP_DISPLAY_NAME} Portable Build v{PACKAGE_VERSION}",
        f"Package Version: {PACKAGE_VERSION}",
        f"Executable: {APP_NAME}.exe",
        f"WebUI: {WEBUI_NAME}.exe",
        "",
        "启动模式（自适应入口）：",
        f"- 双击 {APP_NAME}.exe        → 默认进入 GUI 模式（无参数自适应）",
        f"- 双击 {WEBUI_NAME}.exe  → 直接进入 Web 模式",
        f"- 命令行 {APP_NAME}.exe --mode cli  search  → CLI 模式",
        f"- 命令行 {APP_NAME}.exe --mode interactive → 交互式引导",
        "",
        "Bundled tools:",
        "- ffmpeg.exe",
        "- N_m3u8DL-RE.exe",
        "- Playwright Chromium (ms-playwright)",
        "",
        "Excluded user data:",
        "- config.json",
        "- bili_auth.json",
        "- ks_auth.json",
        "- dy_auth.json",
        "",
        "Runtime user data directory:",
        rf"- %LOCALAPPDATA%\{APP_NAME}",
    ]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """作为脚本入口组织整体执行流程。"""
    ensure_prerequisites()
    clean_previous_outputs()
    run_pyinstaller()
    verify_output()
    write_manifest()
    print(f"绿色版构建完成: {DIST_DIR}")


if __name__ == "__main__":
    main()
