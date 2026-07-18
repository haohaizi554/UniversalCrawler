"""通过 ``__init_subclass__`` 自动注册的插件基础契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.spiders.base import BaseSpider

class BasePlugin:
    """插件抽象基类。

    子类由 ``__init_subclass__`` 自动注册，并通过 :func:`get_subclasses`
    暴露。每个插件需要声明唯一 ``id``（SPI 键）、显示名称与排序值；还可提供
    简介及 ``settings_builder``，用于生成平台设置界面。
    """

    id: str = "base"
    name: str = "Base Plugin"
    aliases: tuple[str, ...] = ()
    sort_order: int = 1000
    description: str = ""

    # SPI 只登记可实例化的具体子类，抽象中间类不会进入运行时平台列表。
    _subclasses: dict[str, type[BasePlugin]] = {}

    # 设置控件构建器和运行参数读取器按需导入，避免核心插件层反向依赖 Qt。
    settings_builder: Callable[[], dict[str, Any]] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """自动登记每个非抽象插件子类。"""
        super().__init_subclass__(**kwargs)
        pid = getattr(cls, "id", None)
        if pid and pid != "base":
            cls._subclasses[pid] = cls

    # 具体插件可覆盖的 SPI 接口

    def get_search_placeholder(self) -> str:
        """返回搜索输入框占位文本。"""
        return "请输入关键词..."

    def get_spider_class(self) -> type[BaseSpider]:
        """返回当前平台使用的爬虫类。"""
        raise NotImplementedError

    def get_downloader_class(self):
        """返回当前平台使用的下载器类。

        未覆盖时返回 ``None``，注册表随后按 ``source_id`` 匹配通用下载器。
        """
        return None

    def get_default_config(self) -> dict[str, Any]:
        """返回平台默认运行配置，供 CLI、SDK 和 Web 在用户未配置时使用。"""
        return {}

    def get_download_defaults(self) -> dict[str, str]:
        """返回直链下载所需的默认 HTTP 请求头。"""
        return {}

    # 类级注册表查询

    @classmethod
    def get_subclasses(cls) -> dict[str, type[BasePlugin]]:
        """返回 SPI 自动注册表的副本，防止调用方直接修改内部状态。"""
        return dict(cls._subclasses)

    @classmethod
    def get_subclass(cls, plugin_id: str) -> type[BasePlugin] | None:
        """按平台 ID 查询已登记的插件类。"""
        return cls._subclasses.get(plugin_id)

# 兼容旧调用路径的便捷导出
__all__ = [
    "BasePlugin",
]
