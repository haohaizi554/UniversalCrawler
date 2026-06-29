"""Compatibility exports for the historical plugin settings module.

UI settings builders live in :mod:`app.ui.plugin_settings`. This module keeps
old imports working without making ``app.core`` import Qt/UI code at import
time.
"""

from importlib import import_module
from typing import Any

from app.core.plugins.run_options import build_missav_proxy_url

_UI_EXPORTS = {
    "MissAVSettingsWidget",
    "PageLimitSettingsWidget",
    "build_bilibili_settings_widget",
    "build_douyin_settings_widget",
    "build_kuaishou_settings_widget",
    "build_missav_settings_widget",
    "read_bilibili_run_options",
    "read_douyin_run_options",
    "read_kuaishou_run_options",
    "read_missav_run_options",
}

__all__ = ["build_missav_proxy_url", *_UI_EXPORTS]

def __getattr__(name: str) -> Any:
    if name not in _UI_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module("app.ui.plugin_settings")
    value = getattr(module, name)
    globals()[name] = value
    return value
