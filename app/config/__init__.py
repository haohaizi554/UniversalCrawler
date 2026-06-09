"""包初始化模块，为 `app/config` 提供统一导出或包级说明。"""

from .constants import DEFAULT_USER_AGENT
from .settings import (
    AppSettings,
    AuthSettings,
    CommonSettings,
    ConfigManager,
    ConfigValidationError,
    DouyinSettings,
    DownloadSettings,
    KuaishouSettings,
    XiaohongshuSettings,
    cfg,
)

__all__ = [
    "AppSettings",
    "AuthSettings",
    "CommonSettings",
    "ConfigManager",
    "ConfigValidationError",
    "DEFAULT_USER_AGENT",
    "DouyinSettings",
    "DownloadSettings",
    "KuaishouSettings",
    "XiaohongshuSettings",
    "cfg",
]
