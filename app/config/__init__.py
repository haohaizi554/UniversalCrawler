"""包初始化模块，为 `app/config` 提供统一导出或包级说明。"""

from .constants import DEFAULT_USER_AGENT
from .settings import (
    AppSettings,
    AuthSettings,
    BilibiliSettings,
    CommonSettings,
    ConfigManager,
    ConfigValidationError,
    DouyinSettings,
    DownloadSettings,
    KuaishouSettings,
    MissAVSettings,
    XiaohongshuSettings,
    cfg,
    get_platform_default_values,
    get_platform_runtime_defaults,
    get_setting_default,
)

__all__ = [
    "AppSettings",
    "AuthSettings",
    "BilibiliSettings",
    "CommonSettings",
    "ConfigManager",
    "ConfigValidationError",
    "DEFAULT_USER_AGENT",
    "DouyinSettings",
    "DownloadSettings",
    "KuaishouSettings",
    "MissAVSettings",
    "XiaohongshuSettings",
    "cfg",
    "get_platform_default_values",
    "get_platform_runtime_defaults",
    "get_setting_default",
]
