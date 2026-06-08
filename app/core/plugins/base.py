"""插件模块，负责 `app/core/plugins/base.py` 对应的平台定义与注册契约。"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.spiders.base import BaseSpider


class BasePlugin:
    """封装 `BasePlugin` 在 `app/core/plugins/base.py` 中承担的核心逻辑。"""
    id = "base"
    name = "Base Plugin"

    def get_search_placeholder(self) -> str:
        """获取 `search_placeholder` 对应的数据或状态，供 `BasePlugin` 使用。"""
        return "请输入关键词..."

    def get_spider_class(self) -> type[BaseSpider]:
        """获取 `spider_class` 对应的数据或状态，供 `BasePlugin` 使用。"""
        raise NotImplementedError
