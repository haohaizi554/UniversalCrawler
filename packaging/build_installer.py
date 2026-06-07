"""打包辅助脚本，负责 `packaging/build_installer.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations
import shutil
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist" / "UniversalCrawlerPro"
ISS_FILE = PROJECT_ROOT / "packaging" / "installer.iss"
OUTPUT_DIR = PROJECT_ROOT / "dist" / "installer"
SETUP_EXE = OUTPUT_DIR / "UniversalCrawlerPro_Setup.exe"


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


def ensure_prerequisites() -> str:
    """执行 `ensure_prerequisites` 对应的业务逻辑。"""
    if not DIST_DIR.exists():
        raise SystemExit(
            "未找到绿色版输出目录，请先运行 `python packaging/build_portable.py`。\n"
            f"期望路径: {DIST_DIR}"
        )
    if not ISS_FILE.exists():
        raise SystemExit(f"未找到安装脚本: {ISS_FILE}")
    iscc = resolve_iscc()
    if not iscc:
        raise SystemExit(
            "未检测到 Inno Setup 编译器 ISCC.exe。\n"
            "请先安装 Inno Setup 6，然后重新运行此脚本。"
        )
    return iscc


def main() -> None:
    """作为脚本入口组织整体执行流程。"""
    iscc = ensure_prerequisites()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if SETUP_EXE.exists():
        SETUP_EXE.unlink()
    build_started_at = time.time()
    command = [iscc, str(ISS_FILE)]
    subprocess.run(command, cwd=PROJECT_ROOT / "packaging", check=True)
    if not SETUP_EXE.exists():
        raise SystemExit(f"安装包构建失败，未找到输出文件: {SETUP_EXE}")
    if SETUP_EXE.stat().st_mtime < build_started_at:
        raise SystemExit(f"安装包未被重新生成，输出文件时间异常: {SETUP_EXE}")
    print(f"安装包构建完成: {SETUP_EXE}")


if __name__ == "__main__":
    main()
