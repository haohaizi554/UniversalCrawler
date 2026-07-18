"""向插件调用方导出稳定的公共接口。"""

from .base import BasePlugin
from .metadata import (
    InteractiveChoice,
    InteractiveField,
    PlatformAuthSpec,
    PlatformInteractiveSpec,
)
from .registry import PluginRegistry, registry

# 具体插件类不在这里逐项导出。模块导入时，插件会通过 ``__init_subclass__``
# 自动注册到 SPI，调用方应使用 ``registry.get_plugin(id)`` 查询，避免形成硬编码依赖。

__all__ = [
    "BasePlugin",
    "InteractiveChoice",
    "InteractiveField",
    "PlatformAuthSpec",
    "PlatformInteractiveSpec",
    "PluginRegistry",
    "registry",
]
