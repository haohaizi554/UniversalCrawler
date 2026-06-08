"""插件模块，负责 `app/core/plugins/definitions.py` 对应的平台定义、注册或设置构建逻辑。"""

from __future__ import annotations

from .base import BasePlugin

#实现插件，但是设置界面只是定义
class KuaishouPlugin(BasePlugin):
    """封装 `KuaishouPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "kuaishou"
    name = "快手"
    sort_order = 20

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        return "输入：快手主页链接、快手号或关键词..."

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `KuaishouPlugin` 使用。"""
        from app.spiders.kuaishou.spider import KuaishouSpider

        return KuaishouSpider


class MissAVPlugin(BasePlugin):
    """封装 `MissAVPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "missav"
    name = "MissAV"
    sort_order = 30

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        return "输入：番号或老师名..."

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `MissAVPlugin` 使用。"""
        from app.spiders.missav.spider import MissAVSpider

        return MissAVSpider


class BilibiliPlugin(BasePlugin):
    """封装 `BilibiliPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "bilibili"
    name = "Bilibili"
    sort_order = 40

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        return "输入：BV号、UP主ID、合集链接、主页链接、视频链接、分享链接或关键词..."

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `BilibiliPlugin` 使用。"""
        from app.spiders.bilibili.spider import BilibiliSpider

        return BilibiliSpider


class DouyinPlugin(BasePlugin):
    """封装 `DouyinPlugin` 在 `app/core/plugins/definitions.py` 中承担的核心逻辑。"""
    id = "douyin"
    name = "抖音"
    sort_order = 10

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        return "输入：主页链接、分享链接或合集链接..."

    def get_spider_class(self):
        """获取 `spider_class` 对应的数据或状态，供 `DouyinPlugin` 使用。"""
        from app.spiders.douyin.spider import DouyinSpider

        return DouyinSpider


def get_default_plugins() -> list[BasePlugin]:
    """获取 `default_plugins` 对应的数据或状态。"""
    from .discovery import discover_builtin_plugins

    return discover_builtin_plugins()
