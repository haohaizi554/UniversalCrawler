"""从 ``app.core.plugins`` 统一导出稳定的插件接口。

调用方应始终从本模块导入公共符号：

    from app.core.plugin_registry import registry, BasePlugin, PluginRegistry

具体插件类通过 SPI 自动注册，可由 ``registry.get_plugin(id)`` 获取，
无需在业务代码中逐个显式导入。
"""

from .plugins import BasePlugin, PluginRegistry, registry

__all__ = [
    "BasePlugin",
    "PluginRegistry",
    "registry",
]
