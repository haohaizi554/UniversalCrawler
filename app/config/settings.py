"""配置模块，负责 `app/config/settings.py` 对应的配置常量、读取或校验逻辑。"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time as time_module
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config.constants import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_MISSAV_PROXY_URL,
    DEFAULT_USER_AGENT,
    SUPPORTED_THEMES,
)
from app.core.event_bus import EventBus
from app.exceptions import ConfigReadError, ConfigValidationError, ConfigWriteError
from app.utils.runtime_paths import is_temporary_path, resolve_user_file

CURRENT_FILENAME_TEMPLATE = "current"   #当前命名格式
DEFAULT_OPEN_MODE = "builtin_player"    #默认打开方式
LOCK_WARN_SECONDS = 1.0

FILENAME_TEMPLATE_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": CURRENT_FILENAME_TEMPLATE, "label": "\u9ed8\u8ba4"},
    {"value": "{title}", "label": "\u6807\u9898"},
    {"value": "{platform}_{title}", "label": "\u5e73\u53f0_\u6807\u9898"},
    {"value": "{platform}_{title}_{date}", "label": "\u5e73\u53f0_\u6807\u9898_\u65e5\u671f"},
    {"value": "{platform}_{title}_{index}", "label": "\u5e73\u53f0_\u6807\u9898_\u5e8f\u53f7"},
)
OPEN_MODE_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": DEFAULT_OPEN_MODE, "label": "\u5185\u7f6e\u64ad\u653e\u5668"},
    {"value": "system_default", "label": "\u7cfb\u7edf\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f"},
)
PLAYBACK_PLAYER_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": DEFAULT_OPEN_MODE, "label": "\u5185\u7f6e\u64ad\u653e\u5668"},
    {"value": "system_default", "label": "\u7cfb\u7edf\u9ed8\u8ba4\u64ad\u653e\u5668"},
)
IMAGE_AUTO_ADVANCE_INTERVAL_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "1", "label": "1 \u79d2"},
    {"value": "3", "label": "3 \u79d2"},
    {"value": "5", "label": "5 \u79d2\uff08\u63a8\u8350\uff09"},
    {"value": "10", "label": "10 \u79d2"},
)
LOG_LEVEL_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "debug", "label": "\u8c03\u8bd5"},
    {"value": "info", "label": "\u4fe1\u606f"},
    {"value": "warning", "label": "\u8b66\u544a"},
    {"value": "error", "label": "\u9519\u8bef"},
)
ACCENT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "blue", "label": "\u84dd\u8272"},
    {"value": "green", "label": "\u7eff\u8272"},
    {"value": "purple", "label": "\u7d2b\u8272"},
    {"value": "orange", "label": "\u6a59\u8272"},
    {"value": "red", "label": "\u7ea2\u8272"},
)
SCALE_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "90%", "label": "90%"},
    {"value": "100%", "label": "100%\uff08\u63a8\u8350\uff09"},
    {"value": "110%", "label": "110%"},
    {"value": "125%", "label": "125%"},
)
FONT_SIZE_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "small", "label": "\u5c0f"},
    {"value": "medium", "label": "\u4e2d\uff08\u63a8\u8350\uff09"},
    {"value": "large", "label": "\u5927"},
)
LANGUAGE_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "zh-CN", "label": "\u7b80\u4f53\u4e2d\u6587\uff08\u63a8\u8350\uff09"},
    {"value": "en-US", "label": "English"},
    {"value": "zh-TW", "label": "\u7e41\u9ad4\u4e2d\u6587"},
)
DOWNLOAD_CONCURRENCY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "1", "label": "1"},
    {"value": "3", "label": "3\uff08\u63a8\u8350\uff09"},
    {"value": "5", "label": "5"},
)
REQUEST_TIMEOUT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "30", "label": "30 \u79d2"},
    {"value": "60", "label": "60 \u79d2\uff08\u63a8\u8350\uff09"},
    {"value": "90", "label": "90 \u79d2"},
    {"value": "120", "label": "120 \u79d2"},
    {"value": "180", "label": "180 \u79d2"},
    {"value": "300", "label": "300 \u79d2"},
)
RETRY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "0", "label": "0\uff08\u4e0d\u91cd\u8bd5\uff09"},
    {"value": "1", "label": "1"},
    {"value": "2", "label": "2"},
    {"value": "3", "label": "3\uff08\u63a8\u8350\uff09"},
    {"value": "5", "label": "5"},
    {"value": "10", "label": "10"},
)
SPEED_LIMIT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "0", "label": "\u65e0\u9650\u5236"},
    {"value": "512", "label": "512 KB/s"},
    {"value": "1024", "label": "1 MB/s"},
    {"value": "2048", "label": "2 MB/s"},
    {"value": "5120", "label": "5 MB/s"},
    {"value": "10240", "label": "10 MB/s"},
    {"value": "20480", "label": "20 MB/s"},
)
PLATFORM_COUNT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "10", "label": "10 \u4e2a\u89c6\u9891"},
    {"value": "20", "label": "20 \u4e2a\u89c6\u9891\uff08\u63a8\u8350\uff09"},
    {"value": "30", "label": "30 \u4e2a\u89c6\u9891"},
    {"value": "50", "label": "50 \u4e2a\u89c6\u9891"},
    {"value": "9999", "label": "max"},
)
PLATFORM_NOTE_COUNT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "10", "label": "10 \u7bc7\u7b14\u8bb0"},
    {"value": "20", "label": "20 \u7bc7\u7b14\u8bb0\uff08\u63a8\u8350\uff09"},
    {"value": "30", "label": "30 \u7bc7\u7b14\u8bb0"},
    {"value": "50", "label": "50 \u7bc7\u7b14\u8bb0"},
    {"value": "9999", "label": "max"},
)
PLATFORM_PAGE_COUNT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "1", "label": "1 \u9875\uff08\u63a8\u8350\uff09"},
    {"value": "2", "label": "2 \u9875"},
    {"value": "3", "label": "3 \u9875"},
    {"value": "5", "label": "5 \u9875"},
    {"value": "9999", "label": "max"},
)
LOG_RETENTION_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "1", "label": "1 \u5929\uff08\u63a8\u8350\uff09"},
    {"value": "3", "label": "3 \u5929"},
    {"value": "5", "label": "5 \u5929"},
    {"value": "7", "label": "7 \u5929"},
)
FAILED_RECORD_RETENTION_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "3", "label": "3 \u5929"},
    {"value": "7", "label": "7 \u5929\uff08\u63a8\u8350\uff09"},
    {"value": "14", "label": "14 \u5929"},
    {"value": "30", "label": "30 \u5929"},
)
UI_LOG_MAX_DISPLAY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "100", "label": "100 \u6761"},
    {"value": "300", "label": "300 \u6761\uff08\u63a8\u8350\uff09"},
    {"value": "500", "label": "500 \u6761"},
)
UI_LOG_MAX_DISPLAY_DEFAULT = 300
PROXY_APP_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "\u7cfb\u7edf\u4ee3\u7406", "label": "\u7cfb\u7edf\u4ee3\u7406"},
    {"value": "\u76f4\u8fde", "label": "\u76f4\u8fde\uff08\u4e0d\u4f7f\u7528\u4ee3\u7406\uff09"},
    {"value": "Clash (7890)", "label": "Clash (7890)"},
    {"value": "Clash Verge (7897)", "label": "Clash Verge (7897)"},
    {"value": "v2rayN (10809)", "label": "v2rayN (10809)"},
    {"value": "V2Ray / Qv2ray (10808)", "label": "V2Ray / Qv2ray (10808)"},
    {"value": "sing-box (2080)", "label": "sing-box (2080)"},
    {"value": "NekoRay (2080)", "label": "NekoRay (2080)"},
    {"value": "\u81ea\u5b9a\u4e49", "label": "\u81ea\u5b9a\u4e49 HTTP/SOCKS5 \u7aef\u70b9"},
)
_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_QUOTE_CHARS = "\"'`\u201c\u201d\u2018\u2019"   #字符串里的双引号

#获取选项
def filename_template_options() -> list[dict[str, str]]:
    return [dict(option) for option in FILENAME_TEMPLATE_OPTIONS]


def open_mode_options() -> list[dict[str, str]]:
    return [dict(option) for option in OPEN_MODE_OPTIONS]

def playback_player_options() -> list[dict[str, str]]:
    return [dict(option) for option in PLAYBACK_PLAYER_OPTIONS]


def image_auto_advance_interval_options() -> list[dict[str, str]]:
    return [dict(option) for option in IMAGE_AUTO_ADVANCE_INTERVAL_OPTIONS]


def log_level_options() -> list[dict[str, str]]:
    return [dict(option) for option in LOG_LEVEL_OPTIONS]


def accent_options() -> list[dict[str, str]]:
    return [dict(option) for option in ACCENT_OPTIONS]


def scale_options() -> list[dict[str, str]]:
    return [dict(option) for option in SCALE_OPTIONS]


def font_size_options() -> list[dict[str, str]]:
    return [dict(option) for option in FONT_SIZE_OPTIONS]


def language_options() -> list[dict[str, str]]:
    return [dict(option) for option in LANGUAGE_OPTIONS]


def download_concurrency_options() -> list[dict[str, str]]:
    return [dict(option) for option in DOWNLOAD_CONCURRENCY_OPTIONS]


def normalize_download_concurrency(value: int | str | None, default: int = 3) -> int:
    """Normalize regular download concurrency to the supported production choices."""
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = int(default)
    if numeric <= 1:
        return 1
    if numeric <= 3:
        return 3
    return 5


def request_timeout_options() -> list[dict[str, str]]:
    return [dict(option) for option in REQUEST_TIMEOUT_OPTIONS]


def retry_options() -> list[dict[str, str]]:
    return [dict(option) for option in RETRY_OPTIONS]


def speed_limit_options() -> list[dict[str, str]]:
    return [dict(option) for option in SPEED_LIMIT_OPTIONS]


def platform_count_options() -> list[dict[str, str]]:
    return [dict(option) for option in PLATFORM_COUNT_OPTIONS]


def platform_note_count_options() -> list[dict[str, str]]:
    return [dict(option) for option in PLATFORM_NOTE_COUNT_OPTIONS]


def platform_page_count_options() -> list[dict[str, str]]:
    return [dict(option) for option in PLATFORM_PAGE_COUNT_OPTIONS]


def log_retention_options() -> list[dict[str, str]]:
    return [dict(option) for option in LOG_RETENTION_OPTIONS]


def failed_record_retention_options() -> list[dict[str, str]]:
    return [dict(option) for option in FAILED_RECORD_RETENTION_OPTIONS]


def ui_log_max_display_options() -> list[dict[str, str]]:
    return [dict(option) for option in UI_LOG_MAX_DISPLAY_OPTIONS]


def normalize_ui_log_max_display_count(value: Any, default: int = UI_LOG_MAX_DISPLAY_DEFAULT) -> int:
    """Normalize UI log display count to the supported lightweight choices."""
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = int(default)
    allowed = {int(option["value"]) for option in UI_LOG_MAX_DISPLAY_OPTIONS}
    return numeric if numeric in allowed else int(default)


def proxy_app_options() -> list[dict[str, str]]:
    return [dict(option) for option in PROXY_APP_OPTIONS]


def _option_values(options: tuple[dict[str, str], ...]) -> set[str]:
    return {str(option["value"]) for option in options}


def _option_label(options: tuple[dict[str, str], ...], value: Any, fallback: str = "") -> str:
    value_text = str(value or fallback)
    for option in options:
        if option["value"] == value_text:
            return option["label"]
    return value_text


def filename_template_label(value: Any) -> str: #获取显示标签，校验一下
    return _option_label(FILENAME_TEMPLATE_OPTIONS, value, CURRENT_FILENAME_TEMPLATE)


def open_mode_label(value: Any) -> str:
    value_text = str(value or DEFAULT_OPEN_MODE)
    if value_text not in _option_values(OPEN_MODE_OPTIONS):
        value_text = DEFAULT_OPEN_MODE
    return _option_label(OPEN_MODE_OPTIONS, value_text, DEFAULT_OPEN_MODE)


def playback_player_label(value: Any) -> str:
    return _option_label(PLAYBACK_PLAYER_OPTIONS, value, DEFAULT_OPEN_MODE)


def log_level_label(value: Any) -> str:
    return _option_label(LOG_LEVEL_OPTIONS, value, "info")


def accent_label(value: Any) -> str:
    return _option_label(ACCENT_OPTIONS, value, "blue")


def font_size_label(value: Any) -> str:
    return _option_label(FONT_SIZE_OPTIONS, value, "medium")


def language_label(value: Any) -> str:
    return _option_label(LANGUAGE_OPTIONS, value, "zh-CN")


def _strip_path_quotes(value: Any) -> str:  #清洗用户输入的路径：去掉路径首尾的引号和空格
    text = str(value or "").strip() #""是空字符串    #.strip()去掉首尾换行制表符
    while len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:  #text[-1]最后一个字符
        text = text[1:-1].strip()   #左闭右开
    return text


def _file_url_to_path(value: str) -> str:
    parsed = urlparse(value)    #解析 URL
    if parsed.scheme.lower() != "file":
        return value
    path_text = unquote(parsed.path or "")  #解析%编码
    if parsed.netloc:   #拼回去netloc
        path_text = f"//{parsed.netloc}{path_text}"
    if os.name == "nt" and path_text.startswith("/") and len(path_text) > 3 and path_text[2] == ":":
        path_text = path_text[1:]
    return path_text


def _path_has_invalid_segment(path: Path) -> bool:  #检查是否包含非法字符
    for index, part in enumerate(path.parts):
        if not part or part in {os.sep, os.altsep, path.anchor, path.drive}:
            continue
        if index == 0 and part.endswith(":"):   #C:
            continue
        if _INVALID_PATH_CHARS_RE.search(part):
            return True
    return False


def normalize_download_directory_input(value: Any, *, create: bool = False) -> str: #*表示后面一个必须关键字传参
    text = _strip_path_quotes(value)
    if not text:
        raise ConfigValidationError("\u4e0b\u8f7d\u76ee\u5f55\u4e0d\u80fd\u4e3a\u7a7a")
    text = _file_url_to_path(text)
    text = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(text)
    raw_text = text.rstrip()
    trailing_separator = raw_text.endswith(("/", "\\"))
    if not trailing_separator and candidate.suffix and not (candidate.exists() and candidate.is_dir()):
        candidate = candidate.parent
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate  #cwd:current working directory，当前工作目录
    try:
        normalized = candidate.resolve(strict=False)    #规范化路径
    except (OSError, RuntimeError) as exc:
        raise ConfigValidationError(f"\u4e0b\u8f7d\u76ee\u5f55\u8def\u5f84\u65e0\u6cd5\u89e3\u6790: {value}") from exc
    if _path_has_invalid_segment(normalized):
        raise ConfigValidationError(f"\u4e0b\u8f7d\u76ee\u5f55\u8def\u5f84\u5305\u542b\u975e\u6cd5\u5b57\u7b26: {value}")
    if normalized.exists() and not normalized.is_dir():
        raise ConfigValidationError(f"\u4e0b\u8f7d\u76ee\u5f55\u4e0d\u662f\u6587\u4ef6\u5939: {normalized}")
    if create:
        try:
            normalized.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigValidationError(f"\u65e0\u6cd5\u521b\u5efa\u4e0b\u8f7d\u76ee\u5f55: {normalized}") from exc
    return str(normalized)


def normalize_platform_timeout(value: Any, *, default: int = 60) -> int:
    """Normalize crawler API/http timeout and migrate the historical 10s default."""
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = default
    if timeout <= 10:
        timeout = default
    return max(30, min(timeout, 300))


@dataclass
class CommonSettings:   #默认设置
    """封装 `CommonSettings` 对应的配置数据与访问逻辑。"""
    save_directory: str = DEFAULT_DOWNLOAD_DIR
    last_source: str = "kuaishou"
    filename_template: str = CURRENT_FILENAME_TEMPLATE
    open_after_download: bool = False
    default_open_mode: str = DEFAULT_OPEN_MODE
    show_browser_window: bool = True
    theme: str = "light"
    dark_theme: bool = False
    theme_schema_version: int = 2

    def normalize(self) -> None:

        try:
            self.save_directory = normalize_download_directory_input(self.save_directory)
        except ConfigValidationError:
            self.save_directory = normalize_download_directory_input(DEFAULT_DOWNLOAD_DIR)
        if not str(self.filename_template or "").strip():
            self.filename_template = CURRENT_FILENAME_TEMPLATE
        if self.filename_template not in _option_values(FILENAME_TEMPLATE_OPTIONS):
            self.filename_template = CURRENT_FILENAME_TEMPLATE
        if not str(self.default_open_mode or "").strip():
            self.default_open_mode = DEFAULT_OPEN_MODE
        valid_open_modes = {option["value"] for option in OPEN_MODE_OPTIONS}
        if self.default_open_mode not in valid_open_modes:
            self.default_open_mode = DEFAULT_OPEN_MODE
        self.show_browser_window = bool(self.show_browser_window)
        if self.theme not in SUPPORTED_THEMES:
            self.theme = "dark" if self.dark_theme else "light"
        self.dark_theme = self.theme != "light" if isinstance(self.dark_theme, bool) else False

@dataclass
class MissAVSettings:
    """封装 `MissAVSettings` 对应的配置数据与访问逻辑。"""
    proxy_type: str = "clash"          # clash / v2ray / custom
    proxy_app: str = "Clash (7890)"
    proxy_port: int = 7890
    proxy_url: str = DEFAULT_MISSAV_PROXY_URL
    max_items: int = 20
    search_max_pages: int = 1
    timeout: int = 60
    priority: str = "中文字幕优先"    #筛选优先级
    individual_only: bool = False

    def normalize(self) -> None:

        if self.priority not in {"中文字幕优先", "无码流出优先"}:
            self.priority = "中文字幕优先"
        self.max_items = max(1, min(int(self.max_items or 20), 9999))
        self.search_max_pages = max(1, min(int(self.search_max_pages or 1), 100))
        self.timeout = normalize_platform_timeout(self.timeout, default=60)

@dataclass
class BilibiliSettings:
    """封装 `BilibiliSettings` 对应的配置数据与访问逻辑。"""
    auth_file: str = "bili_auth.json"
    user_agent: str = DEFAULT_USER_AGENT
    max_pages: int = 1
    max_items: int = 9999
    timeout: int = 60
    api_workers: int = 8    #请求并发数

    def normalize(self) -> None:

        self.auth_file = str(resolve_user_file(self.auth_file))
        self.max_pages = max(1, min(self.max_pages, 9999))
        self.max_items = max(1, min(self.max_items, 9999))
        self.timeout = normalize_platform_timeout(self.timeout, default=60)
        self.api_workers = max(1, min(self.api_workers, 16))

@dataclass
class DouyinSettings:
    """封装 `DouyinSettings` 对应的配置数据与访问逻辑。"""
    user_agent: str = DEFAULT_USER_AGENT
    search_max_pages: int = 1
    max_items: int = 20
    timeout: int = 60

    def normalize(self) -> None:

        self.search_max_pages = max(1, min(self.search_max_pages, 100))
        self.max_items = max(1, min(self.max_items, 9999))
        self.timeout = normalize_platform_timeout(self.timeout, default=60)

@dataclass
class XiaohongshuSettings:
    """封装 `XiaohongshuSettings` 对应的配置数据与访问逻辑。"""

    user_agent: str = DEFAULT_USER_AGENT
    max_items: int = 20
    search_max_pages: int = 5
    timeout: int = 30
    request_interval: float = 0.15
    detail_request_interval: float = 0.0   #解析间隔基数
    sort: str = "general"
    note_type: int = 0  #0全部，1图文，2视频

    def normalize(self) -> None:

        self.max_items = max(1, min(self.max_items, 9999))
        self.search_max_pages = max(1, min(self.search_max_pages, 100))
        self.timeout = normalize_platform_timeout(self.timeout, default=30)
        self.request_interval = max(0.0, min(float(self.request_interval), 10.0))
        if self.request_interval == 1.5:
            self.request_interval = 0.15
        self.detail_request_interval = max(0.0, min(float(self.detail_request_interval), 5.0))
        if self.detail_request_interval == 0.5:
            self.detail_request_interval = 0.0
        if self.sort not in {"general", "popularity_descending", "time_descending"}:
            self.sort = "general"
        try:
            note_type = int(self.note_type)
        except (TypeError, ValueError):
            note_type = 0
        self.note_type = note_type if note_type in {0, 1, 2} else 0

@dataclass
class KuaishouSettings:
    """封装 `KuaishouSettings` 对应的配置数据与访问逻辑。"""
    user_agent: str = DEFAULT_USER_AGENT
    max_items: int = 20
    timeout: int = 60

    def normalize(self) -> None:

        self.max_items = max(1, min(self.max_items, 9999))
        self.timeout = normalize_platform_timeout(self.timeout, default=60)

@dataclass
class AuthSettings:
    """封装 `AuthSettings` 对应的配置数据与访问逻辑。"""
    bilibili_cookie_file: str = "bili_auth.json"
    kuaishou_cookie_file: str = "ks_auth.json"
    douyin_cookie_file: str = "dy_auth.json"
    xiaohongshu_cookie_file: str = "xhs_auth.json"

    def normalize(self) -> None:

        self.bilibili_cookie_file = str(resolve_user_file(self.bilibili_cookie_file))
        self.kuaishou_cookie_file = str(resolve_user_file(self.kuaishou_cookie_file))
        self.douyin_cookie_file = str(resolve_user_file(self.douyin_cookie_file))
        self.xiaohongshu_cookie_file = str(resolve_user_file(self.xiaohongshu_cookie_file))

@dataclass
class DownloadSettings:
    """封装 `DownloadSettings` 对应的配置数据与访问逻辑。"""
    max_concurrent: int = 3
    local_scan_limit: int = 1000
    max_retries: int = 3
    request_timeout: int = 60
    chunk_size: int = 65536
    resume_enabled: bool = True
    speed_limit_kb: int = 0
    video_only: bool = False
    image_respects_concurrency: bool = False
    image_fast_lane_limit: int = 10

    def normalize(self) -> None:

        self.max_concurrent = normalize_download_concurrency(self.max_concurrent)
        self.local_scan_limit = max(100, min(self.local_scan_limit, 5000))
        self.max_retries = max(0, min(self.max_retries, 10))
        self.request_timeout = max(10, min(self.request_timeout, 300))
        self.chunk_size = max(8192, min(self.chunk_size, 1024 * 1024))
        self.speed_limit_kb = max(0, min(self.speed_limit_kb, 999999))
        self.image_respects_concurrency = bool(self.image_respects_concurrency)
        try:
            image_limit = int(self.image_fast_lane_limit or 10)
        except (TypeError, ValueError):
            image_limit = 10
        self.image_fast_lane_limit = max(1, min(image_limit, 10))

@dataclass
class PlaybackSettings:
    """封装本地播放体验设置，供 GUI 与 WebUI 共用。"""
    default_player: str = DEFAULT_OPEN_MODE
    builtin_player_enabled: bool = True
    remember_position: bool = True
    hardware_acceleration: bool = True
    autoplay_next: bool = True
    manual_image_switch: bool = False
    image_auto_advance_interval_seconds: int = 5

    def normalize(self) -> None:

        if self.default_player not in _option_values(PLAYBACK_PLAYER_OPTIONS):
            self.default_player = DEFAULT_OPEN_MODE
        if self.builtin_player_enabled is False and self.default_player == DEFAULT_OPEN_MODE:
            self.default_player = "system_default"
        self.builtin_player_enabled = bool(self.builtin_player_enabled)
        if str(self.image_auto_advance_interval_seconds) not in _option_values(IMAGE_AUTO_ADVANCE_INTERVAL_OPTIONS):
            self.image_auto_advance_interval_seconds = 5

@dataclass
class LogSettings:
    """封装日志中心展示与清理策略。"""
    retention_days: int = 1
    failed_record_retention_days: int = 7
    level: str = "info"
    ui_log_max_display_count: int = 300
    auto_copy_trace_on_error: bool = True
    cleanup_old_logs_on_start: bool = False

    def normalize(self) -> None:

        if str(self.retention_days) not in _option_values(LOG_RETENTION_OPTIONS):
            self.retention_days = 1
        if str(self.failed_record_retention_days) not in _option_values(FAILED_RECORD_RETENTION_OPTIONS):
            self.failed_record_retention_days = 7
        self.ui_log_max_display_count = normalize_ui_log_max_display_count(self.ui_log_max_display_count)
        if self.level not in _option_values(LOG_LEVEL_OPTIONS):
            self.level = "info"

@dataclass
class AppearanceSettings:
    """封装主题之外的界面偏好；主题本身保留在 common 以兼容旧入口。"""
    follow_system: bool = False
    accent: str = "blue"
    scale: str = "100%"
    font_size: str = "medium"
    language: str = "zh-CN"

    def normalize(self) -> None:

        if self.accent not in _option_values(ACCENT_OPTIONS):
            self.accent = "blue"
        if self.scale not in _option_values(SCALE_OPTIONS):
            self.scale = "100%"
        if self.font_size not in _option_values(FONT_SIZE_OPTIONS):
            self.font_size = "medium"
        if self.language not in _option_values(LANGUAGE_OPTIONS):
            self.language = "zh-CN"

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
class AppSettings:  #变量名: 类型 = 默认值规则
    """封装 `AppSettings` 对应的配置数据与访问逻辑。"""
    common: CommonSettings = field(default_factory=CommonSettings)
    missav: MissAVSettings = field(default_factory=MissAVSettings)
    bilibili: BilibiliSettings = field(default_factory=BilibiliSettings)
    douyin: DouyinSettings = field(default_factory=DouyinSettings)
    xiaohongshu: XiaohongshuSettings = field(default_factory=XiaohongshuSettings)
    kuaishou: KuaishouSettings = field(default_factory=KuaishouSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    download: DownloadSettings = field(default_factory=DownloadSettings)
    playback: PlaybackSettings = field(default_factory=PlaybackSettings)
    logging: LogSettings = field(default_factory=LogSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    ui: UISettings = field(default_factory=UISettings)

    def normalize(self) -> None:

        self.common.normalize()
        self.missav.normalize()
        self.bilibili.normalize()
        self.douyin.normalize()
        self.xiaohongshu.normalize()
        self.kuaishou.normalize()
        self.auth.normalize()
        self.download.normalize()
        self.playback.normalize()
        self.logging.normalize()
        self.appearance.normalize()

    def to_dict(self) -> dict[str, Any]:

        return asdict(self)

class _InstrumentedRLock:
    def __init__(self, name: str, *, warn_seconds: float = LOCK_WARN_SECONDS) -> None:
        self._lock = threading.RLock()
        self._name = name
        self._warn_seconds = warn_seconds
        self._logger = logging.getLogger(__name__)
        self._local = threading.local()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        wait_started = time_module.monotonic()
        acquired = self._lock.acquire(blocking, timeout)
        acquired_at = time_module.monotonic()
        if acquired:
            waited = acquired_at - wait_started
            if waited > self._warn_seconds:
                self._logger.warning("%s lock wait %.3fs", self._name, waited)
            stack = getattr(self._local, "acquired_at", None)
            if stack is None:
                stack = []
                self._local.acquired_at = stack
            stack.append(acquired_at)
        return acquired

    def release(self) -> None:
        stack = getattr(self._local, "acquired_at", None)
        acquired_at = stack.pop() if stack else time_module.monotonic()
        held = time_module.monotonic() - acquired_at
        try:
            self._lock.release()
        finally:
            if not stack:
                self._local.acquired_at = None
        if held > self._warn_seconds:
            self._logger.warning("%s lock held %.3fs", self._name, held)

    def __enter__(self) -> "_InstrumentedRLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

class ConfigManager:
    """管理 `ConfigManager` 对应的对象生命周期、状态或调度流程。"""
    SECTION_MODELS = {  #映射表
        "common": CommonSettings,
        "missav": MissAVSettings,
        "bilibili": BilibiliSettings,
        "douyin": DouyinSettings,
        "xiaohongshu": XiaohongshuSettings,
        "kuaishou": KuaishouSettings,
        "auth": AuthSettings,
        "download": DownloadSettings,
        "playback": PlaybackSettings,
        "logging": LogSettings,
        "appearance": AppearanceSettings,
        "ui": UISettings,
    }

    def __init__(self, filename: str = DEFAULT_CONFIG_FILE, event_bus: EventBus | None = None):    #python不需要提前声明字段
        """初始化当前实例并准备运行所需的状态，供 `ConfigManager` 使用。"""
        self._lock = _InstrumentedRLock("ConfigManager")  #线程锁
        self.event_bus = event_bus or EventBus()
        self.filename = str(resolve_user_file(filename))
        # 确保用户数据目录存在（项目目录下的 user_data/），没有文件夹就创建
        Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
        self.settings = AppSettings()
        self.last_load_error: ConfigReadError | None = None
        self._load_from_disk()
        self.settings.normalize()

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        return self.event_bus.subscribe(topic, handler)

    def subscribe_async(self, topic: str, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        """Subscribe a config listener without running it on the config writer thread."""
        return self.event_bus.subscribe_async(topic, handler)

    def unsubscribe(self, topic: str, handler: Callable[[Any], None] | None = None) -> None:
        self.event_bus.unsubscribe(topic, handler)

    def _load_from_disk(self) -> None:
        with self._lock:    #加锁
            self._load_from_disk_unlocked() #执行完自动解锁

    def _load_from_disk_unlocked(self) -> None:
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
            if section_name == "common":
                raw_section = self._migrate_common_section(raw_section) #旧配置格式转换成新配置格式
                if is_temporary_path(raw_section.get("save_directory", "")):
                    raw_section["save_directory"] = DEFAULT_DOWNLOAD_DIR

            current = getattr(self.settings, section_name)
            defaults = asdict(section_model())
            normalized: dict[str, Any] = {}
            for key, default_value in defaults.items():
                value = raw_section.get(key, getattr(current, key))
                normalized[key] = self._coerce_value(key, value, default_value)
            setattr(self.settings, section_name, section_model(**normalized))
            self._normalize_section(section_name)

    @staticmethod
    def _migrate_common_section(raw_section: dict[str, Any]) -> dict[str, Any]:
        migrated = dict(raw_section)
        if "theme_schema_version" not in migrated:
            if migrated.get("theme") == "dark" and migrated.get("dark_theme") is True:
                migrated["theme"] = "light"
                migrated["dark_theme"] = False
            migrated["theme_schema_version"] = 2
        return migrated

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
        if expected_type is float:
            if isinstance(value, bool):
                raise ConfigValidationError(f"{key} 类型非法")
            try:
                return float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ConfigValidationError(f"{key} 必须是数字") from exc
        if expected_type is str:
            return str(value)
        return value

    def _normalize_field_value(self, section: str, key: str, value: Any) -> Any:
        if section == "common" and key == "save_directory":
            return normalize_download_directory_input(value, create=True)
        if section == "common" and key == "filename_template":
            template = str(value or "").strip() or CURRENT_FILENAME_TEMPLATE
            if template not in _option_values(FILENAME_TEMPLATE_OPTIONS):
                raise ConfigValidationError(f"未知文件命名规则: {value}")
            return template
        if section == "common" and key == "default_open_mode":
            mode = str(value or "").strip()
            if mode not in _option_values(OPEN_MODE_OPTIONS):
                raise ConfigValidationError(f"未知默认打开方式: {value}")
            return mode
        if section == "common" and key == "theme":
            theme = str(value or "light").strip().lower()
            if theme not in SUPPORTED_THEMES:
                raise ConfigValidationError(f"未知主题: {value}")
            return theme
        if section == "playback" and key == "default_player":
            player = str(value or DEFAULT_OPEN_MODE).strip()
            if player not in _option_values(PLAYBACK_PLAYER_OPTIONS):
                raise ConfigValidationError(f"未知播放器: {value}")
            return player
        if section == "playback" and key == "image_auto_advance_interval_seconds":
            seconds = int(value)
            if str(seconds) not in _option_values(IMAGE_AUTO_ADVANCE_INTERVAL_OPTIONS):
                raise ConfigValidationError(f"unknown image auto advance interval: {value}")
            return seconds
        if section == "logging" and key == "level":
            level = str(value or "info").strip().lower()
            if level not in _option_values(LOG_LEVEL_OPTIONS):
                raise ConfigValidationError(f"未知日志级别: {value}")
            return level
        if section == "logging" and key == "retention_days":
            days = int(value)
            if str(days) not in _option_values(LOG_RETENTION_OPTIONS):
                raise ConfigValidationError(f"未知日志保留天数: {value}")
            return days
        if section == "logging" and key == "failed_record_retention_days":
            days = int(value)
            if str(days) not in _option_values(FAILED_RECORD_RETENTION_OPTIONS):
                raise ConfigValidationError(f"未知失败记录保留天数: {value}")
            return days
        if section == "appearance" and key == "accent":
            accent = str(value or "blue").strip().lower()
            if accent not in _option_values(ACCENT_OPTIONS):
                raise ConfigValidationError(f"未知主题色: {value}")
            return accent
        if section == "appearance" and key == "scale":
            scale = str(value or "100%").strip()
            if scale not in _option_values(SCALE_OPTIONS):
                raise ConfigValidationError(f"未知界面缩放: {value}")
            return scale
        if section == "appearance" and key == "font_size":
            font_size = str(value or "medium").strip().lower()
            if font_size not in _option_values(FONT_SIZE_OPTIONS):
                raise ConfigValidationError(f"未知字体大小: {value}")
            return font_size
        if section == "appearance" and key == "language":
            language = str(value or "zh-CN").strip()
            if language not in _option_values(LANGUAGE_OPTIONS):
                raise ConfigValidationError(f"未知界面语言: {value}")
            return language
        if section == "logging" and key == "ui_log_max_display_count":
            return normalize_ui_log_max_display_count(value)
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
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:

        import logging
        logger = logging.getLogger(__name__)
        target_file = Path(self.filename)
        temp_file = Path(self.filename + ".tmp")
        parent = target_file.parent
        parent.mkdir(parents=True, exist_ok=True)
        last_permission_error: PermissionError | None = None

        for attempt in range(4):
            try:
                # Windows can briefly deny replace() while another GUI/Web process
                # or security scanner observes config.json, so write a fresh temp
                # file and retry the atomic swap before giving up.
                with open(temp_file, "w", encoding="utf-8") as fp:
                    json.dump(self.settings.to_dict(), fp, indent=4, ensure_ascii=False)
                temp_file.replace(target_file)
                return
            except PermissionError as exc:
                last_permission_error = exc
                try:
                    temp_file.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < 3:
                    time_module.sleep(0.05 * (attempt + 1))
                    continue
                break
            except (OSError, TypeError, ValueError) as exc:
                raise ConfigWriteError(str(exc)) from exc

        if last_permission_error is not None:
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            logger.warning(f"[ConfigManager] 保存配置失败 (Permission denied): {last_permission_error}")

    @property
    def data(self) -> dict[str, Any]:

        with self._lock:
            return self.settings.to_dict()

    def get(self, section: str, key: str, default: Any = None) -> Any:

        with self._lock:
            section_obj = getattr(self.settings, section, None)
            if section_obj is None:
                return default
            value = getattr(section_obj, key, default)
            return default if value is None else value

    def set(self, section: str, key: str, value: Any) -> None:
        payload = None
        with self._lock:
            payload = self._set_unlocked(section, key, value)
        if payload is not None:
            self.event_bus.publish("config.changed", payload)

    def set_many(self, section: str, values: dict[str, Any]) -> None:
        payloads: list[dict[str, Any]] = []
        with self._lock:
            original_data = self.settings.to_dict()
            try:
                for key, value in (values or {}).items():
                    payload = self._set_unlocked(section, str(key), value, persist=False)
                    if payload is not None:
                        payloads.append(payload)
                if payloads:
                    self.save()
            except Exception:
                self._apply_data(original_data)
                raise
        if payloads:
            combined = dict(payloads[-1])
            combined["changes"] = payloads
            self.event_bus.publish("config.changed", combined)

    def _set_unlocked(self, section: str, key: str, value: Any, *, persist: bool = True) -> dict[str, Any] | None:

        section_obj = getattr(self.settings, section, None)
        if section_obj is None:
            raise ConfigValidationError(f"未知配置分组: {section}")
        defaults = asdict(self.SECTION_MODELS[section]())
        if key not in defaults:
            raise ConfigValidationError(f"未知配置字段: {section}.{key}")
        old_value = getattr(section_obj, key)
        coerced = self._coerce_value(key, value, defaults[key])
        coerced = self._normalize_field_value(section, key, coerced)
        if old_value == coerced:
            return None
        setattr(section_obj, key, coerced)
        self._normalize_section(section)
        if persist:
            self.save()
        return {
            "section": section,
            "key": key,
            "value": getattr(section_obj, key),
            "old_value": old_value,
        }

    def save_ui_state(
        self,
        geometry: Any,
        state: Any,
        main_splitter: Any,
        right_splitter: Any,
        is_fs: bool,
    ) -> None:
        """保存 `ui_state` 对应的数据、配置或文件，供 `ConfigManager` 使用。"""
        with self._lock:
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

    def update_missav_proxy(self, proxy_app: str = "", port: int | str = 0, url: str = "") -> None:
        """Update MissAV proxy fields while keeping old two-argument callers safe."""
        if isinstance(port, str) and not url:
            url = port
            port = 0
        proxy_app = str(proxy_app or "").strip()
        proxy_url = str(url or "").strip()

        def _infer_proxy_type(label: str, resolved_url: str) -> str:
            text = f"{label} {resolved_url}".strip().lower()
            if "\u76f4\u8fde" in text:
                return "direct"
            if "\u7cfb\u7edf\u4ee3\u7406" in text:
                return "system"
            if "v2ray" in text:
                return "v2ray"
            if "sing-box" in text:
                return "sing-box"
            if "nekoray" in text:
                return "nekoray"
            if "\u81ea\u5b9a\u4e49" in text or ":" in resolved_url:
                return "custom"
            return "clash"

        def _infer_port(resolved_url: str, fallback: int) -> int:
            try:
                parsed = urlparse(resolved_url)
                if parsed.port:
                    return int(parsed.port)
            except ValueError:
                pass
            try:
                return int(port or fallback)
            except (TypeError, ValueError):
                return fallback

        with self._lock:
            if proxy_app:
                self.settings.missav.proxy_app = proxy_app
                self.settings.missav.proxy_type = _infer_proxy_type(proxy_app, proxy_url)
            if proxy_url or proxy_app in {"\u76f4\u8fde", "\u7cfb\u7edf\u4ee3\u7406"}:
                self.settings.missav.proxy_url = proxy_url
            resolved_port = _infer_port(proxy_url, self.settings.missav.proxy_port)
            if resolved_port:
                self.settings.missav.proxy_port = resolved_port
            self._save_unlocked()

def _build_default_settings() -> AppSettings:
    """构建一份已标准化的默认配置快照，供无状态读取场景复用。"""
    settings = AppSettings()
    settings.normalize()
    return settings

DEFAULT_APP_SETTINGS = _build_default_settings()

_PLATFORM_SECTION_MAP = {
    "douyin": "douyin",
    "xiaohongshu": "xiaohongshu",
    "bilibili": "bilibili",
    "kuaishou": "kuaishou",
    "missav": "missav",
}

_PLATFORM_RUNTIME_FIELDS = {
    "douyin": ("max_items", "timeout"),
    "xiaohongshu": (
        "max_items",
        "search_max_pages",
        "timeout",
        "request_interval",
        "detail_request_interval",
        "sort",
        "note_type",
    ),
    "bilibili": ("max_pages", "max_items", "timeout", "api_workers"),
    "kuaishou": ("max_items", "timeout"),
    "missav": ("max_items", "search_max_pages", "timeout", "individual_only", "priority"),
}

def get_setting_default(section: str, key: str) -> Any:
    """读取配置模型中的默认值，避免调用方散落硬编码。"""
    section_obj = getattr(DEFAULT_APP_SETTINGS, section, None)
    if section_obj is None:
        raise ConfigValidationError(f"未知配置分组: {section}")
    if not hasattr(section_obj, key):
        raise ConfigValidationError(f"未知配置字段: {section}.{key}")
    return getattr(section_obj, key)

def get_platform_default_values(source: str) -> dict[str, Any]:
    """返回平台默认运行参数快照，不读取持久化配置。"""
    section_name = _PLATFORM_SECTION_MAP.get(source)
    if not section_name:
        return {}

    section_obj = getattr(DEFAULT_APP_SETTINGS, section_name)
    result = {field: getattr(section_obj, field) for field in _PLATFORM_RUNTIME_FIELDS.get(source, ())}
    if source == "missav":
        result["proxy"] = getattr(section_obj, "proxy_url")
    return result

def get_platform_runtime_defaults(source: str, manager: ConfigManager | None = None) -> dict[str, Any]:
    """返回平台运行配置快照，优先读取持久化配置，兜底配置模型默认值。"""
    if source not in _PLATFORM_SECTION_MAP:
        return {}

    active_manager = manager or globals().get("cfg")
    if active_manager is None:
        return get_platform_default_values(source)

    def _snapshot() -> dict[str, Any]:
        section_name = _PLATFORM_SECTION_MAP[source]
        section_obj = getattr(active_manager.settings, section_name, None)
        if section_obj is None:
            return get_platform_default_values(source)
        result = {field: getattr(section_obj, field) for field in _PLATFORM_RUNTIME_FIELDS.get(source, ())}
        if source == "missav":
            result["proxy"] = getattr(section_obj, "proxy_url")
        return result

    lock = getattr(active_manager, "_lock", None)
    if lock is None:
        return _snapshot()
    with lock:
        return _snapshot()

cfg = ConfigManager()
