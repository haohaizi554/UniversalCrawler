"""工具模块，提供 `app/utils/runtime_paths.py` 对应的通用辅助函数。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "UniversalCrawlerPro"


def is_frozen() -> bool:
    """执行 `is_frozen` 对应的业务逻辑。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """执行 `project_root` 对应的业务逻辑。"""
    return Path(__file__).resolve().parents[2]


def install_root() -> Path:
    """执行 `install_root` 对应的业务逻辑。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_root() -> Path:
    """执行 `resource_root` 对应的业务逻辑。"""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return project_root()


def local_appdata_root() -> Path:
    """执行 `local_appdata_root` 对应的业务逻辑。"""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


def user_data_root() -> Path:
    """执行 `user_data_root` 对应的业务逻辑。"""
    path = local_appdata_root() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_logs_root() -> Path:
    """执行 `user_logs_root` 对应的业务逻辑。"""
    path = user_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cache_root() -> Path:
    """执行 `user_cache_root` 对应的业务逻辑。"""
    path = user_data_root() / "Cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_download_root() -> Path:
    """执行 `default_download_root` 对应的业务逻辑。"""
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads / "UniversalCrawlerPro"
    return user_data_root() / "Downloads"


def resolve_user_file(path_value: str | os.PathLike[str]) -> Path:
    """解析并确定 `user_file` 对应的最终结果。"""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return user_data_root() / path


def resolve_resource_file(relative_path: str | os.PathLike[str]) -> Path:
    """解析并确定 `resource_file` 对应的最终结果。"""
    return resource_root() / Path(relative_path)


def resolve_tool_file(executable_name: str) -> Path:
    """解析并确定 `tool_file` 对应的最终结果。"""
    for base in (install_root(), resource_root()):
        candidate = base / executable_name
        if candidate.exists():
            return candidate
    return Path(executable_name)
