"""工具模块，提供 `app/utils/runtime_paths.py` 对应的通用辅助函数。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_DIR_NAME = "UniversalCrawlerPro"
USER_DATA_ROOT_ENV = "UCRAWL_USER_DATA_ROOT"
DOWNLOAD_ROOT_ENV = "UCRAWL_DOWNLOAD_ROOT"
TOOL_ROOT_ENV = "UCRAWL_TOOL_ROOT"
#运行时路径管理（核心工具）

def is_frozen() -> bool:
    
    return bool(getattr(sys, "frozen", False))

def project_root() -> Path:
    
    return Path(__file__).resolve().parents[2]

def install_root() -> Path:
    
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()

def resource_root() -> Path:
    
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return project_root()

def local_appdata_root() -> Path:
    
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"

def is_development_runtime() -> bool:
    """判断当前是否处于 IDE / 源码开发调试态。"""
    return not is_frozen()

def user_data_root() -> Path:
    """返回用户数据根目录。

    规范：
    - 开发调试态（源码 / IDE）固定落到项目目录 `user_data/`
    - 打包交付态（安装版 / 免安装 EXE）落到 `LOCALAPPDATA/UniversalCrawlerPro`
    - 若显式设置 `UCRAWL_USER_DATA_ROOT`，则优先使用该路径
    """
    override = os.environ.get(USER_DATA_ROOT_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
    elif is_development_runtime():
        path = project_root() / "user_data"
    else:
        path = local_appdata_root() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path

def user_logs_root() -> Path:
    
    path = user_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path

def user_cache_root() -> Path:
    
    path = user_data_root() / "Cache"
    path.mkdir(parents=True, exist_ok=True)
    return path

def default_download_root() -> Path:
    
    override = os.environ.get(DOWNLOAD_ROOT_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads / "UniversalCrawlerPro"
    return user_data_root() / "Downloads"

def is_temporary_path(path_value: str | os.PathLike[str] | None) -> bool:
    """判断路径是否落在系统临时目录。

    规则：
    - 优先按 `tempfile.gettempdir()` 做绝对路径前缀匹配
    - 再兼容 Windows 8.3 短路径和常见 `/tmp/` 模式
    """
    if not path_value:
        return False

    raw_path = str(path_value).strip()
    if not raw_path:
        return False

    try:
        normalized = os.path.normcase(
            os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))
        )
    except (OSError, TypeError, ValueError):
        normalized = os.path.normcase(raw_path)

    try:
        temp_root = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        if normalized == temp_root or normalized.startswith(temp_root + os.sep):
            return True
    except (OSError, TypeError, ValueError):
        pass

    def _matches_known_temp_root(candidate: str) -> bool:
        candidate = candidate.replace("\\", "/").casefold().rstrip("/")
        if candidate.endswith("/appdata/local/temp") or "/appdata/local/temp/" in candidate:
            return True
        root_relative = candidate[2:] if len(candidate) >= 3 and candidate[1:3] == ":/" else candidate
        # These are path classifiers only; no file is created from the literals.
        return root_relative == "/tmp" or root_relative.startswith("/tmp/")  # nosec B108

    return _matches_known_temp_root(raw_path) or _matches_known_temp_root(normalized)

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
    tool_root_override = os.environ.get(TOOL_ROOT_ENV, "").strip()
    search_roots: list[Path] = []
    if tool_root_override:
        search_roots.append(Path(tool_root_override).expanduser())
    search_roots.extend((install_root(), resource_root()))

    for base in search_roots:
        candidate = base / executable_name
        if candidate.exists():
            return candidate
    return Path(executable_name)
