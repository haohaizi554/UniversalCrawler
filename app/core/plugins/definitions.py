"""插件模块，负责 `app/core/plugins/definitions.py` 对应的平台定义、注册或设置构建逻辑。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from .base import BasePlugin
from .settings_builders import (
    build_bilibili_settings_widget,
    build_douyin_settings_widget,
    build_kuaishou_settings_widget,
    build_missav_settings_widget,
    read_bilibili_run_options,
    read_douyin_run_options,
    read_kuaishou_run_options,
    read_missav_run_options,
)

#实现插件，但是设置界面只是定义
class KuaishouPlugin(BasePlugin):
    """封装 `KuaishouPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "kuaishou"
    name = "快手"

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        return "输入：快手主页链接、快手号或关键词..."

    #构建该平台的设置界面（基于 PyQt6 的 QWidget 组件）
    def get_settings_widget(self, parent=None) -> QWidget:
        """获取 `settings_widget` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        return build_kuaishou_settings_widget(parent)

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        from app.spiders.kuaishou.spider import KuaishouSpider

        return KuaishouSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        """获取 `run_options` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        return read_kuaishou_run_options(settings_widget)


class MissAVPlugin(BasePlugin):
    """封装 `MissAVPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "missav"
    name = "MissAV"

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        return "输入：番号或老师名..."

    def get_settings_widget(self, parent=None) -> QWidget:
        """获取 `settings_widget` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        return build_missav_settings_widget(parent)

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        from app.spiders.missav.spider import MissAVSpider

        return MissAVSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        """获取 `run_options` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        return read_missav_run_options(settings_widget)


class BilibiliPlugin(BasePlugin):
    """封装 `BilibiliPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "bilibili"
    name = "Bilibili"

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        return "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词..."

    def get_settings_widget(self, parent=None) -> QWidget:
        """获取 `settings_widget` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        return build_bilibili_settings_widget(parent)

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        from app.spiders.bilibili.spider import BilibiliSpider

        return BilibiliSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        """获取 `run_options` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        return read_bilibili_run_options(settings_widget)


class DouyinPlugin(BasePlugin):
    """封装 `DouyinPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "douyin"
    name = "抖音"

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        return "输入：主页链接或分享链接..."

    def get_settings_widget(self, parent=None) -> QWidget:
        """获取 `settings_widget` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        return build_douyin_settings_widget(parent)

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        from app.spiders.douyin.spider import DouyinSpider

        return DouyinSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        """获取 `run_options` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        return read_douyin_run_options(settings_widget)


def get_default_plugins() -> list[BasePlugin]:
    """获取 `default_plugins` 对应的数据或状态。"""
    return [
        DouyinPlugin(),
        KuaishouPlugin(),
        MissAVPlugin(),
        BilibiliPlugin(),
    ]
