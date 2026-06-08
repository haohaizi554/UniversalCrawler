"""兼容层：历史导入路径转发到 UI 适配层与纯配置层。"""

from app.core.plugins.run_options import build_missav_proxy_url
from app.ui.plugin_settings import (
    MissAVSettingsWidget,
    PageLimitSettingsWidget,
    build_bilibili_settings_widget,
    build_douyin_settings_widget,
    build_kuaishou_settings_widget,
    build_missav_settings_widget,
    read_bilibili_run_options,
    read_douyin_run_options,
    read_kuaishou_run_options,
    read_missav_run_options,
)
