from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from .base import BasePlugin
from .settings_builders import (
    build_bilibili_settings_widget,
    build_douyin_settings_widget,
    build_missav_settings_widget,
    read_bilibili_run_options,
    read_douyin_run_options,
    read_missav_run_options,
)


class KuaishouPlugin(BasePlugin):
    id = "kuaishou"
    name = "快手"

    def get_search_placeholder(self) -> str:
        return "输入快手主页链接、快手号或关键词..."

    def get_spider_class(self):
        from app.spiders.kuaishou.spider import KuaishouSpider

        return KuaishouSpider


class MissAVPlugin(BasePlugin):
    id = "missav"
    name = "MissAV"

    def get_search_placeholder(self) -> str:
        return "输入番号 (如 IPX-906) 或女优名..."

    def get_settings_widget(self, parent=None) -> QWidget:
        return build_missav_settings_widget(parent)

    def get_spider_class(self):
        from app.spiders.missav.spider import MissAVSpider

        return MissAVSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        return read_missav_run_options(settings_widget)


class BilibiliPlugin(BasePlugin):
    id = "bilibili"
    name = "Bilibili"

    def get_search_placeholder(self) -> str:
        return "输入 BV号、UP主ID、搜索关键词或 B站链接..."

    def get_settings_widget(self, parent=None) -> QWidget:
        return build_bilibili_settings_widget(parent)

    def get_spider_class(self):
        from app.spiders.bilibili.spider import BilibiliSpider

        return BilibiliSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        return read_bilibili_run_options(settings_widget)


class DouyinPlugin(BasePlugin):
    id = "douyin"
    name = "抖音"

    def get_search_placeholder(self) -> str:
        return "输入抖音主页链接、分享链接、作品链接或关键词..."

    def get_settings_widget(self, parent=None) -> QWidget:
        return build_douyin_settings_widget(parent)

    def get_spider_class(self):
        from app.spiders.douyin.spider import DouyinSpider

        return DouyinSpider

    def get_run_options(self, settings_widget: QWidget | None) -> dict:
        return read_douyin_run_options(settings_widget)


def get_default_plugins() -> list[BasePlugin]:
    return [
        DouyinPlugin(),
        KuaishouPlugin(),
        MissAVPlugin(),
        BilibiliPlugin(),
    ]
