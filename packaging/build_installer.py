"""打包辅助脚本，负责 `packaging/build_installer.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    from project_meta import (
        APP_DISPLAY_NAME,
        APP_EXE_NAME,
        APP_ICON_NAME,
        APP_PUBLISHER,
        APP_USER_MODEL_ID,
        DIST_DIR_NAME,
        INSTALL_DIR_NAME,
        INSTALLER_BASENAME,
        PACKAGE_VERSION,
        UPDATER_HELPER_EXE_NAME,
        WEBUI_DISPLAY_NAME,
        WEBUI_EXE_NAME,
        WEBUI_ICON_NAME,
        WEBUI_USER_MODEL_ID,
    )
else:
    from .project_meta import (
        APP_DISPLAY_NAME,
        APP_EXE_NAME,
        APP_ICON_NAME,
        APP_PUBLISHER,
        APP_USER_MODEL_ID,
        DIST_DIR_NAME,
        INSTALL_DIR_NAME,
        INSTALLER_BASENAME,
        PACKAGE_VERSION,
        UPDATER_HELPER_EXE_NAME,
        WEBUI_DISPLAY_NAME,
        WEBUI_EXE_NAME,
        WEBUI_ICON_NAME,
        WEBUI_USER_MODEL_ID,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist" / DIST_DIR_NAME
ISS_FILE = PROJECT_ROOT / "packaging" / "installer.iss"
OUTPUT_DIR = PROJECT_ROOT / "dist" / "installer"
UPDATE_BOOTSTRAP = PROJECT_ROOT / "scripts" / "update_bootstrap.py"
WIZARD_IMAGE = PROJECT_ROOT / "packaging" / "wizard_image.bmp"
WIZARD_SMALL_IMAGE = PROJECT_ROOT / "packaging" / "wizard_small_image.bmp"
APP_ICON = PROJECT_ROOT / APP_ICON_NAME
WEBUI_ICON = PROJECT_ROOT / WEBUI_ICON_NAME
# The installer consumes the portable build; fail early if a stale dist misses shared GUI/WebUI assets.
REQUIRED_INSTALL_SOURCE_ENTRIES = (
    lambda: DIST_DIR / APP_EXE_NAME,
    lambda: DIST_DIR / WEBUI_EXE_NAME,
    lambda: DIST_DIR / UPDATER_HELPER_EXE_NAME,
    lambda: DIST_DIR / "BUILD_INFO.txt",
    lambda: DIST_DIR / "README.md",
    lambda: DIST_DIR / "README_EN.md",
    lambda: DIST_DIR / "_internal" / "_sqlite3.pyd",
    lambda: DIST_DIR / "_internal" / "sqlite3.dll",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "index.html",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "app.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_layout.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "task_pages.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "task_runtime.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "media_logs.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "settings.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "overlays_responsive.css",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "i18n.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "custom_select.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "media_display.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_display.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_query_worker.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_detail_worker.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "list_page_worker.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "platform_limits.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "settings_render.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "task_render.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "playback_state.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_i18n.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "frontend_runtime.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "list_pages.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "log_center.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "settings_controller.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "dialog_controller.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "playback_controller.js",
    lambda: DIST_DIR / "_internal" / "app" / "web" / "static" / "app.js",
    lambda: DIST_DIR / "_internal" / "UI" / "icon" / "nav_settings.png",
    lambda: APP_ICON,
    lambda: WEBUI_ICON,
)

def get_setup_exe_path() -> Path:
    """返回当前版本对应的安装包输出路径。"""
    return OUTPUT_DIR / f"{INSTALLER_BASENAME}.exe"

def _resolve_iscc_from_registry() -> str | None:
    """提供 `_resolve_iscc_from_registry` 对应的内部辅助逻辑。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )

    for root, subkey in uninstall_roots:
        try:
            with winreg.OpenKey(root, subkey) as base_key:
                subkey_count, _, _ = winreg.QueryInfoKey(base_key)
                for index in range(subkey_count):
                    entry_name = winreg.EnumKey(base_key, index)
                    with winreg.OpenKey(base_key, entry_name) as entry_key:
                        display_name = _query_registry_value(winreg, entry_key, "DisplayName")
                        if not display_name or "Inno Setup" not in display_name:
                            continue
                        for candidate in (
                            _query_registry_value(winreg, entry_key, "InstallLocation"),
                            _query_registry_value(winreg, entry_key, "DisplayIcon"),
                        ):
                            if not candidate:
                                continue
                            candidate_path = Path(str(candidate).strip('"'))
                            if candidate_path.is_file() and candidate_path.name.lower() == "iscc.exe":
                                return str(candidate_path)
                            if candidate_path.is_file():
                                sibling = candidate_path.with_name("ISCC.exe")
                                if sibling.exists():
                                    return str(sibling)
                            if candidate_path.is_dir():
                                sibling = candidate_path / "ISCC.exe"
                                if sibling.exists():
                                    return str(sibling)
        except OSError:
            continue
    return None

def _query_registry_value(winreg_module, key, value_name: str) -> str | None:
    """提供 `_query_registry_value` 对应的内部辅助逻辑。"""
    try:
        value, _ = winreg_module.QueryValueEx(key, value_name)
    except OSError:
        return None
    return value if isinstance(value, str) and value.strip() else None

def resolve_iscc() -> str | None:
    """解析并确定 `iscc` 对应的最终结果。"""
    common_candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in common_candidates:
        if candidate.exists():
            return str(candidate)
    if registry_match := _resolve_iscc_from_registry():
        return registry_match
    return shutil.which("ISCC.exe") or shutil.which("iscc")

def _missing_install_source_entries() -> list[str]:
    """Return required portable-build entries missing from the installer source."""
    missing: list[str] = []
    for resolver in REQUIRED_INSTALL_SOURCE_ENTRIES:
        path = resolver()
        if not path.exists():
            missing.append(str(path))
    return missing


def ensure_prerequisites() -> str:
    if not DIST_DIR.exists():
        raise SystemExit(
            "未找到绿色版输出目录，请先运行 `python packaging/build_portable.py`。\n"
            f"期望路径: {DIST_DIR}"
        )
    missing_install_sources = _missing_install_source_entries()
    if missing_install_sources:
        raise SystemExit(
            "安装源目录不完整，请重新运行 `python packaging/build_portable.py`。\n- "
            + "\n- ".join(missing_install_sources)
        )
    if not ISS_FILE.exists():
        raise SystemExit(f"未找到安装脚本: {ISS_FILE}")
    missing_wizard_assets = [
        str(path)
        for path in (WIZARD_IMAGE, WIZARD_SMALL_IMAGE)
        if not path.exists()
    ]
    if missing_wizard_assets:
        raise SystemExit(
            "缺少 Inno Setup 向导图资源，请确认以下文件存在:\n- "
            + "\n- ".join(missing_wizard_assets)
        )
    iscc = resolve_iscc()
    if not iscc:
        raise SystemExit(
            "未检测到 Inno Setup 编译器 ISCC.exe。\n"
            "请先安装 Inno Setup 6，然后重新运行此脚本。"
        )
    return iscc


def maybe_sign_windows_installer(setup_exe: Path) -> None:
    """Optionally run production signing after Inno emits the installer."""

    if os.environ.get("UCRAWL_SIGN_WINDOWS") != "1":
        print("未设置 UCRAWL_SIGN_WINDOWS=1，跳过生产签名。")
        return
    subprocess.run(
        [sys.executable, str(UPDATE_BOOTSTRAP), "sign-windows-installer", "--installer", str(setup_exe)],
        cwd=PROJECT_ROOT,
        check=True,
        shell=False,
    )
    subprocess.run(
        [sys.executable, str(UPDATE_BOOTSTRAP), "inject-windows-trust", "--installer", str(setup_exe)],
        cwd=PROJECT_ROOT,
        check=True,
        shell=False,
    )


def main() -> None:
    """作为脚本入口组织整体执行流程。"""
    iscc = ensure_prerequisites()
    setup_exe = get_setup_exe_path()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if setup_exe.exists():
        setup_exe.unlink()
    build_started_at = time.time()
    command = [
        iscc,
        f"/DAppName={APP_DISPLAY_NAME}",
        f"/DAppVersion={PACKAGE_VERSION}",
        f"/DAppPublisher={APP_PUBLISHER}",
        f"/DAppComments={APP_DISPLAY_NAME} Windows 安装程序",
        f"/DAppExeName={APP_EXE_NAME}",
        f"/DWebUIDisplayName={WEBUI_DISPLAY_NAME}",
        f"/DWebUIExeName={WEBUI_EXE_NAME}",
        f"/DAppIconName={APP_ICON_NAME}",
        f"/DWebUIIconName={WEBUI_ICON_NAME}",
        f"/DAppUserModelID={APP_USER_MODEL_ID}",
        f"/DWebUIUserModelID={WEBUI_USER_MODEL_ID}",
        f"/DDistDir=..\\dist\\{DIST_DIR_NAME}",
        f"/DInstallDirName={INSTALL_DIR_NAME}",
        f"/DOutputBaseFilename={INSTALLER_BASENAME}",
        str(ISS_FILE),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT / "packaging", check=True)
    if not setup_exe.exists():
        raise SystemExit(f"安装包构建失败，未找到输出文件: {setup_exe}")
    if setup_exe.stat().st_mtime < build_started_at:
        raise SystemExit(f"安装包未被重新生成，输出文件时间异常: {setup_exe}")
    maybe_sign_windows_installer(setup_exe)
    print(f"安装包构建完成: {setup_exe}")

if __name__ == "__main__":
    main()
