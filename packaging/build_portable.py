"""打包辅助脚本，负责 `packaging/build_portable.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "UniversalCrawlerPro"
WEBUI_NAME = "CrawlerWebPortal"
APP_DISPLAY_NAME = "Universal CrawlerPro"
WEBUI_DISPLAY_NAME = "Crawler WebPortal"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "packaging" / "portable.spec"
DIST_DIR = PROJECT_ROOT / "dist" / APP_NAME
BUILD_DIR = PROJECT_ROOT / "build"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
BROWSER_DIR = LOCALAPPDATA / "ms-playwright"
REQUIRED_FILES = [
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "web_main.py",
    PROJECT_ROOT / "favicon.ico",
    PROJECT_ROOT / "Web.ico",
    PROJECT_ROOT / "ffmpeg.exe",
    PROJECT_ROOT / "N_m3u8DL-RE.exe",
    SPEC_FILE,
]
FORBIDDEN_BASENAMES = {
    "config.json",
    "bili_auth.json",
    "ks_auth.json",
    "dy_auth.json",
}


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
    """执行 `clean_previous_outputs` 对应的业务逻辑。"""
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    shutil.rmtree(DIST_DIR, ignore_errors=True)


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
    """执行 `verify_output` 对应的业务逻辑。"""
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

    for path in DIST_DIR.glob("**/*"):
        if path.is_file() and path.name.lower() in FORBIDDEN_BASENAMES:
            raise SystemExit(f"发现不应打包的用户数据文件: {path}")


def write_manifest() -> None:
    """执行 `write_manifest` 对应的业务逻辑。"""
    manifest = DIST_DIR / "BUILD_INFO.txt"
    lines = [
        f"{APP_DISPLAY_NAME} Portable Build",
        f"Executable: {APP_NAME}.exe",
        f"WebUI: {WEBUI_NAME}.exe",
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
