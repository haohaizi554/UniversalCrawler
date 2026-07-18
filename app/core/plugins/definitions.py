"""内置平台的具体插件定义。

每个类都由 ``BasePlugin.__init_subclass__`` 自动注册，无需维护额外清单。
新增平台时只需实现一个 ``*Plugin`` 类，可放在本文件或同包独立模块中。
"""

from __future__ import annotations

from typing import Any

from .base import BasePlugin

class KuaishouPlugin(BasePlugin):
    id = "kuaishou"
    name = "快手"
    aliases = ("ks",)
    sort_order = 20

    def get_search_placeholder(self) -> str:
        return "输入：快手主页链接、分享链接、快手号或关键词..."

    def get_spider_class(self):
        from app.spiders.kuaishou.spider import KuaishouSpider
        return KuaishouSpider

    def get_downloader_class(self):
        from app.core.downloaders.kuaishou import KuaishouDownloader
        return KuaishouDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_items": 20, "timeout": 10}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.kuaishou.com/",
        }

class MissAVPlugin(BasePlugin):
    id = "missav"
    name = "MissAV"
    aliases = ("miss",)
    sort_order = 30

    def get_search_placeholder(self) -> str:
        return "输入：番号或老师名..."

    def get_spider_class(self):
        from app.spiders.missav.spider import MissAVSpider
        return MissAVSpider

    def get_downloader_class(self):
        from app.core.downloaders.missav import MissAVDownloader
        return MissAVDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {
            "individual_only": False,
            "priority": "中文字幕优先",
            "proxy": "http://127.0.0.1:7890",
        }

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://missav.ai/",
        }

class BilibiliPlugin(BasePlugin):
    id = "bilibili"
    name = "Bilibili"
    aliases = ("bili", "bl")
    sort_order = 40

    def get_search_placeholder(self) -> str:
        return "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词..."

    def get_spider_class(self):
        from app.spiders.bilibili.spider import BilibiliSpider
        return BilibiliSpider

    def get_downloader_class(self):
        from app.core.downloaders.bilibili import BilibiliDownloader
        return BilibiliDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_pages": 1, "max_items": 9999, "timeout": 10, "api_workers": 8}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.bilibili.com",
        }

class DouyinPlugin(BasePlugin):
    id = "douyin"
    name = "抖音"
    aliases = ("dy",)
    sort_order = 10

    def get_search_placeholder(self) -> str:
        return "输入：主页链接、分享链接或合集链接..."

    def get_spider_class(self):
        from app.spiders.douyin.spider import DouyinSpider
        return DouyinSpider

    def get_downloader_class(self):
        from app.core.downloaders.douyin import DouyinDownloader
        return DouyinDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {"max_items": 20, "timeout": 10}

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.douyin.com/",
        }

class XiaohongshuPlugin(BasePlugin):
    id = "xiaohongshu"
    name = "小红书"
    aliases = ("xhs",)
    sort_order = 15

    def get_search_placeholder(self) -> str:
        return "输入：关键词、分享链接、视频/笔记链接、主页链接，或小红书号..."

    def get_spider_class(self):
        from app.spiders.xiaohongshu.spider import XiaohongshuSpider
        return XiaohongshuSpider

    def get_downloader_class(self):
        from app.core.downloaders.xiaohongshu import XiaohongshuDownloader
        return XiaohongshuDownloader

    def get_default_config(self) -> dict[str, Any]:
        return {
            "max_items": 20,
            "search_max_pages": 5,
            "timeout": 30,
            "request_interval": 1.5,
            "detail_request_interval": 0.5,
            "sort": "general",
            "note_type": 0,
        }

    def get_download_defaults(self) -> dict[str, str]:
        return {
            "referer": "https://www.xiaohongshu.com/",
        }

def get_default_plugins() -> list[BasePlugin]:
    """返回按 ``sort_order`` 排序的内置插件实例。"""
    from .discovery import discover_builtin_plugins
    return discover_builtin_plugins()
