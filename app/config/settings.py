"""配置模块，负责 `app/config/settings.py` 对应的配置常量、读取或校验逻辑。"""

from __future__ import annotations

import json
import os
import shutil
import time as time_module
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config.constants import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_MISSAV_PROXY_URL,
    DEFAULT_USER_AGENT,
    SUPPORTED_THEMES,
)
from app.exceptions import ConfigReadError, ConfigValidationError, ConfigWriteError
from app.utils.runtime_paths import is_temporary_path, resolve_user_file


@dataclass
class CommonSettings:
    """封装 `CommonSettings` 对应的配置数据与访问逻辑。"""
    save_directory: str = DEFAULT_DOWNLOAD_DIR
    last_source: str = "kuaishou"
    theme: str = "dark"
    dark_theme: bool = True

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `CommonSettings` 使用。"""
        if self.theme not in SUPPORTED_THEMES:
            self.theme = "dark" if self.dark_theme else "light"
        self.dark_theme = self.theme != "light" if isinstance(self.dark_theme, bool) else True
        if is_temporary_path(self.save_directory):
            self.save_directory = DEFAULT_DOWNLOAD_DIR


@dataclass
class MissAVSettings:
    """封装 `MissAVSettings` 对应的配置数据与访问逻辑。"""
    proxy_type: str = "clash"          # clash / v2ray / custom
    proxy_port: int = 7890
    proxy_url: str = DEFAULT_MISSAV_PROXY_URL
    priority: str = "中文字幕优先"
    individual_only: bool = False

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `MissAVSettings` 使用。"""
        if self.priority not in {"中文字幕优先", "无码流出优先"}:
            self.priority = "中文字幕优先"


@dataclass
class BilibiliSettings:
    """封装 `BilibiliSettings` 对应的配置数据与访问逻辑。"""
    auth_file: str = "bili_auth.json"
    user_agent: str = DEFAULT_USER_AGENT
    max_pages: int = 1
    api_workers: int = 8

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `BilibiliSettings` 使用。"""
        self.auth_file = str(resolve_user_file(self.auth_file))
        self.max_pages = max(1, min(self.max_pages, 500))
        self.api_workers = max(1, min(self.api_workers, 16))


@dataclass
class DouyinSettings:
    """封装 `DouyinSettings` 对应的配置数据与访问逻辑。"""
    user_agent: str = DEFAULT_USER_AGENT
    search_max_pages: int = 1
    max_items: int = 20

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `DouyinSettings` 使用。"""
        self.search_max_pages = max(1, min(self.search_max_pages, 100))
        self.max_items = max(1, min(self.max_items, 9999))


@dataclass
class KuaishouSettings:
    """封装 `KuaishouSettings` 对应的配置数据与访问逻辑。"""
    user_agent: str = DEFAULT_USER_AGENT
    max_items: int = 20

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `KuaishouSettings` 使用。"""
        self.max_items = max(1, min(self.max_items, 9999))


@dataclass
class AuthSettings:
    """封装 `AuthSettings` 对应的配置数据与访问逻辑。"""
    bilibili_cookie_file: str = "bili_auth.json"
    kuaishou_cookie_file: str = "ks_auth.json"
    douyin_cookie_file: str = "dy_auth.json"

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `AuthSettings` 使用。"""
        self.bilibili_cookie_file = str(resolve_user_file(self.bilibili_cookie_file))
        self.kuaishou_cookie_file = str(resolve_user_file(self.kuaishou_cookie_file))
        self.douyin_cookie_file = str(resolve_user_file(self.douyin_cookie_file))


@dataclass
class DownloadSettings:
    """封装 `DownloadSettings` 对应的配置数据与访问逻辑。"""
    max_concurrent: int = 3
    local_scan_limit: int = 1000
    max_retries: int = 3
    request_timeout: int = 60
    chunk_size: int = 65536

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `DownloadSettings` 使用。"""
        self.max_concurrent = max(1, min(self.max_concurrent, 8))
        self.local_scan_limit = max(100, min(self.local_scan_limit, 5000))
        self.max_retries = max(1, min(self.max_retries, 10))
        self.request_timeout = max(10, min(self.request_timeout, 300))
        self.chunk_size = max(8192, min(self.chunk_size, 1024 * 1024))


@dataclass
class UISettings:
    """封装 `UISettings` 对应的配置数据与访问逻辑。"""
    geometry: str = ""
    window_state: str = ""
    splitter_state: str = ""
    main_splitter_state: str = ""
    right_splitter_state: str = ""
    is_fullscreen_mode: bool = False


@dataclass
class AppSettings:
    """封装 `AppSettings` 对应的配置数据与访问逻辑。"""
    common: CommonSettings = field(default_factory=CommonSettings)
    missav: MissAVSettings = field(default_factory=MissAVSettings)
    bilibili: BilibiliSettings = field(default_factory=BilibiliSettings)
    douyin: DouyinSettings = field(default_factory=DouyinSettings)
    kuaishou: KuaishouSettings = field(default_factory=KuaishouSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    download: DownloadSettings = field(default_factory=DownloadSettings)
    ui: UISettings = field(default_factory=UISettings)

    def normalize(self) -> None:
        """执行 `normalize` 对应的业务逻辑，供 `AppSettings` 使用。"""
        self.common.normalize()
        self.missav.normalize()
        self.bilibili.normalize()
        self.douyin.normalize()
        self.kuaishou.normalize()
        self.auth.normalize()
        self.download.normalize()

    def to_dict(self) -> dict[str, Any]:
        """执行 `to_dict` 对应的业务逻辑，供 `AppSettings` 使用。"""
        return asdict(self)

class ConfigManager:
    """管理 `ConfigManager` 对应的对象生命周期、状态或调度流程。"""
    SECTION_MODELS = {
        "common": CommonSettings,
        "missav": MissAVSettings,
        "bilibili": BilibiliSettings,
        "douyin": DouyinSettings,
        "kuaishou": KuaishouSettings,
        "auth": AuthSettings,
        "download": DownloadSettings,
        "ui": UISettings,
    }

    def __init__(self, filename: str = DEFAULT_CONFIG_FILE):
        """初始化当前实例并准备运行所需的状态，供 `ConfigManager` 使用。"""
        self.filename = str(resolve_user_file(filename))
        # 确保用户数据目录存在（项目目录下的 user_data/）
        Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
        self.settings = AppSettings()
        self.last_load_error: ConfigReadError | None = None
        self._load_from_disk()
        self.settings.normalize()

    def _load_from_disk(self) -> None:
        """提供 `_load_from_disk` 对应的内部辅助逻辑，供 `ConfigManager` 使用。"""
        try:
            with open(self.filename, "r", encoding="utf-8") as fp:
                saved_data = json.load(fp)
        except FileNotFoundError:
            self.save()
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.last_load_error = ConfigReadError(str(exc))
            self._reset_config()
            return

        if not isinstance(saved_data, dict):
            self._reset_config()
            return

        try:
            self._apply_data(saved_data)
        except ConfigValidationError:
            self._reset_config()

    def _apply_data(self, saved_data: dict[str, Any]) -> None:
        """提供 `_apply_data` 对应的内部辅助逻辑，供 `ConfigManager` 使用。"""
        for section_name, section_model in self.SECTION_MODELS.items():
            raw_section = saved_data.get(section_name, {})
            if raw_section is None:
                continue
            if not isinstance(raw_section, dict):
                raise ConfigValidationError(f"{section_name} 必须是对象")

            current = getattr(self.settings, section_name)
            defaults = asdict(section_model())
            normalized: dict[str, Any] = {}
            for key, default_value in defaults.items():
                value = raw_section.get(key, getattr(current, key))
                normalized[key] = self._coerce_value(key, value, default_value)
            setattr(self.settings, section_name, section_model(**normalized))
            self._normalize_section(section_name)

    def _coerce_value(self, key: str, value: Any, default_value: Any) -> Any:
        """提供 `_coerce_value` 对应的内部辅助逻辑，供 `ConfigManager` 使用。"""
        if value is None:
            return default_value
        expected_type = type(default_value)
        if expected_type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"1", "true", "yes", "on", "dark"}
            return bool(value)
        if expected_type is int:
            if isinstance(value, bool):
                raise ConfigValidationError(f"{key} 类型非法")
            try:
                return int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ConfigValidationError(f"{key} 必须是整数") from exc
        if expected_type is str:
            return str(value)
        return value

    def _reset_config(self) -> None:
        """提供 `_reset_config` 对应的内部辅助逻辑，供 `ConfigManager` 使用。"""
        backup_name = f"{self.filename}.bak.{int(time_module.time())}"
        if os.path.exists(self.filename):
            try:
                shutil.move(self.filename, backup_name)
            except OSError as exc:
                raise ConfigWriteError(f"备份损坏配置失败: {exc}") from exc
        self.settings = AppSettings()
        self.settings.normalize()
        self.save()

    def _normalize_section(self, section: str) -> None:
        """提供 `_normalize_section` 对应的内部辅助逻辑，供 `ConfigManager` 使用。"""
        section_obj = getattr(self.settings, section, None)
        normalize = getattr(section_obj, "normalize", None)
        if callable(normalize):
            normalize()

    def save(self) -> None:
        """执行 `save` 对应的业务逻辑，供 `ConfigManager` 使用。"""
        import logging
        logger = logging.getLogger(__name__)
        try:
            parent = Path(self.filename).parent
            parent.mkdir(parents=True, exist_ok=True)
            # 处理 Permission denied: 尝试临时文件写入后重命名
            temp_file = Path(self.filename + ".tmp")
            with open(temp_file, "w", encoding="utf-8") as fp:
                json.dump(self.settings.to_dict(), fp, indent=4, ensure_ascii=False)
            # 原子替换
            temp_file.replace(self.filename)
        except PermissionError as exc:
            logger.warning(f"[ConfigManager] 保存配置失败 (Permission denied): {exc}")
            # 静默处理权限错误，不中断用户操作
        except (OSError, TypeError, ValueError) as exc:
            raise ConfigWriteError(str(exc)) from exc

    @property
    def data(self) -> dict[str, Any]:
        """执行 `data` 对应的业务逻辑，供 `ConfigManager` 使用。"""
        return self.settings.to_dict()

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """执行 `get` 对应的业务逻辑，供 `ConfigManager` 使用。"""
        section_obj = getattr(self.settings, section, None)
        if section_obj is None:
            return default
        value = getattr(section_obj, key, default)
        return default if value is None else value

    def set(self, section: str, key: str, value: Any) -> None:
        """执行 `set` 对应的业务逻辑，供 `ConfigManager` 使用。"""
        section_obj = getattr(self.settings, section, None)
        if section_obj is None:
            raise ConfigValidationError(f"未知配置分组: {section}")
        defaults = asdict(self.SECTION_MODELS[section]())
        if key not in defaults:
            raise ConfigValidationError(f"未知配置字段: {section}.{key}")
        coerced = self._coerce_value(key, value, defaults[key])
        setattr(section_obj, key, coerced)
        self._normalize_section(section)
        self.save()

    def save_ui_state(
        self,
        geometry: Any,
        state: Any,
        main_splitter: Any,
        right_splitter: Any,
        is_fs: bool,
    ) -> None:
        """保存 `ui_state` 对应的数据、配置或文件，供 `ConfigManager` 使用。"""
        self.settings.ui.geometry = self._encode_ui_state(geometry)
        self.settings.ui.window_state = self._encode_ui_state(state)
        self.settings.ui.main_splitter_state = self._encode_ui_state(main_splitter)
        self.settings.ui.right_splitter_state = self._encode_ui_state(right_splitter)
        self.settings.ui.is_fullscreen_mode = is_fs
        self.save()

    @staticmethod
    def _encode_ui_state(value: Any) -> str:
        """把 UI 状态编码成十六进制字符串，不依赖 Qt 类型。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, memoryview):
            return value.tobytes().hex()
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).hex()
        to_hex = getattr(value, "toHex", None)
        if callable(to_hex):
            hex_value = to_hex()
            if isinstance(hex_value, memoryview):
                return hex_value.tobytes().decode()
            if isinstance(hex_value, (bytes, bytearray)):
                return bytes(hex_value).decode()
            data = getattr(hex_value, "data", None)
            if callable(data):
                raw = data()
                if isinstance(raw, memoryview):
                    raw = raw.tobytes()
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw).decode()
                if isinstance(raw, str):
                    return raw
            return str(hex_value)
        data = getattr(value, "data", None)
        if callable(data):
            raw = data()
            if isinstance(raw, memoryview):
                raw = raw.tobytes()
            if isinstance(raw, (bytes, bytearray)):
                try:
                    return bytes(raw).decode()
                except UnicodeDecodeError:
                    return bytes(raw).hex()
            if isinstance(raw, str):
                return raw
        return str(value)

    def update_missav_proxy(self, proxy_type: str = "", port: int = 0, url: str = "") -> None:
        """更新 missav 代理配置。"""
        if proxy_type:
            self.settings.missav.proxy_type = proxy_type
        if port:
            self.settings.missav.proxy_port = port
        if url:
            self.settings.missav.proxy_url = url
        self.save()


cfg = ConfigManager()
