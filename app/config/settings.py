from __future__ import annotations

import json
import os
import shutil
import time as time_module
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QByteArray

from app.config.constants import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_MISSAV_PROXY_URL,
    DEFAULT_USER_AGENT,
    SUPPORTED_THEMES,
)
from app.exceptions import ConfigReadError, ConfigValidationError, ConfigWriteError
from app.utils.runtime_paths import resolve_user_file


@dataclass
class CommonSettings:
    save_directory: str = DEFAULT_DOWNLOAD_DIR
    last_source: str = "kuaishou"
    theme: str = "dark"
    dark_theme: bool = True

    def normalize(self) -> None:
        if self.theme not in SUPPORTED_THEMES:
            self.theme = "dark" if self.dark_theme else "light"
        self.dark_theme = self.theme != "light" if isinstance(self.dark_theme, bool) else True


@dataclass
class MissAVSettings:
    proxy_app: str = "Clash (7890)"
    proxy_url: str = DEFAULT_MISSAV_PROXY_URL
    priority: str = "中文字幕优先"
    individual_only: bool = False

    def normalize(self) -> None:
        if self.priority not in {"中文字幕优先", "无码流出优先"}:
            self.priority = "中文字幕优先"


@dataclass
class BilibiliSettings:
    auth_file: str = "bili_auth.json"
    user_agent: str = DEFAULT_USER_AGENT
    max_pages: int = 1
    api_workers: int = 8

    def normalize(self) -> None:
        self.auth_file = str(resolve_user_file(self.auth_file))
        self.max_pages = max(1, min(self.max_pages, 500))
        self.api_workers = max(1, min(self.api_workers, 16))


@dataclass
class DouyinSettings:
    user_agent: str = DEFAULT_USER_AGENT
    search_max_pages: int = 1
    max_items: int = 20

    def normalize(self) -> None:
        self.search_max_pages = max(1, min(self.search_max_pages, 100))
        self.max_items = max(1, min(self.max_items, 9999))


@dataclass
class KuaishouSettings:
    user_agent: str = DEFAULT_USER_AGENT
    max_items: int = 20

    def normalize(self) -> None:
        self.max_items = max(1, min(self.max_items, 9999))


@dataclass
class AuthSettings:
    bilibili_cookie_file: str = "bili_auth.json"
    kuaishou_cookie_file: str = "ks_auth.json"
    douyin_cookie_file: str = "dy_auth.json"

    def normalize(self) -> None:
        self.bilibili_cookie_file = str(resolve_user_file(self.bilibili_cookie_file))
        self.kuaishou_cookie_file = str(resolve_user_file(self.kuaishou_cookie_file))
        self.douyin_cookie_file = str(resolve_user_file(self.douyin_cookie_file))


@dataclass
class DownloadSettings:
    max_concurrent: int = 3
    local_scan_limit: int = 1000
    max_retries: int = 3
    request_timeout: int = 60
    chunk_size: int = 65536

    def normalize(self) -> None:
        self.max_concurrent = max(1, min(self.max_concurrent, 8))
        self.local_scan_limit = max(100, min(self.local_scan_limit, 5000))
        self.max_retries = max(1, min(self.max_retries, 10))
        self.request_timeout = max(10, min(self.request_timeout, 300))
        self.chunk_size = max(8192, min(self.chunk_size, 1024 * 1024))


@dataclass
class UISettings:
    geometry: str = ""
    window_state: str = ""
    splitter_state: str = ""
    main_splitter_state: str = ""
    right_splitter_state: str = ""
    is_fullscreen_mode: bool = False


@dataclass
class AppSettings:
    common: CommonSettings = field(default_factory=CommonSettings)
    missav: MissAVSettings = field(default_factory=MissAVSettings)
    bilibili: BilibiliSettings = field(default_factory=BilibiliSettings)
    douyin: DouyinSettings = field(default_factory=DouyinSettings)
    kuaishou: KuaishouSettings = field(default_factory=KuaishouSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    download: DownloadSettings = field(default_factory=DownloadSettings)
    ui: UISettings = field(default_factory=UISettings)

    def normalize(self) -> None:
        self.common.normalize()
        self.missav.normalize()
        self.bilibili.normalize()
        self.douyin.normalize()
        self.kuaishou.normalize()
        self.auth.normalize()
        self.download.normalize()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class ConfigManager:
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
        self.filename = str(resolve_user_file(filename))
        self.settings = AppSettings()
        self.last_load_error: ConfigReadError | None = None
        self._load_from_disk()
        self.settings.normalize()

    def _load_from_disk(self) -> None:
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
        section_obj = getattr(self.settings, section, None)
        normalize = getattr(section_obj, "normalize", None)
        if callable(normalize):
            normalize()

    def save(self) -> None:
        try:
            Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
            with open(self.filename, "w", encoding="utf-8") as fp:
                json.dump(self.settings.to_dict(), fp, indent=4, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            raise ConfigWriteError(str(exc)) from exc

    @property
    def data(self) -> dict[str, Any]:
        return self.settings.to_dict()

    def get(self, section: str, key: str, default: Any = None) -> Any:
        section_obj = getattr(self.settings, section, None)
        if section_obj is None:
            return default
        value = getattr(section_obj, key, default)
        return default if value is None else value

    def set(self, section: str, key: str, value: Any) -> None:
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
        geometry: QByteArray,
        state: QByteArray,
        main_splitter: QByteArray,
        right_splitter: QByteArray,
        is_fs: bool,
    ) -> None:
        self.settings.ui.geometry = geometry.toHex().data().decode()
        self.settings.ui.window_state = state.toHex().data().decode()
        self.settings.ui.main_splitter_state = main_splitter.toHex().data().decode()
        self.settings.ui.right_splitter_state = right_splitter.toHex().data().decode()
        self.settings.ui.is_fullscreen_mode = is_fs
        self.save()

    def update_missav_proxy(self, app_name: str, url: str) -> None:
        self.settings.missav.proxy_app = app_name
        self.settings.missav.proxy_url = url
        self.save()


cfg = ConfigManager()
