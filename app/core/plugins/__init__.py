"""包初始化模块，为 `app/core/plugins` 提供统一导出或包级说明。"""

from .base import BasePlugin
from .definitions import BilibiliPlugin, DouyinPlugin, KuaishouPlugin, MissAVPlugin, XiaohongshuPlugin
from .registry import PluginRegistry, registry

__all__ = [
    "BasePlugin",
    "DouyinPlugin",
    "XiaohongshuPlugin",
    "KuaishouPlugin",
    "MissAVPlugin",
    "BilibiliPlugin",
    "PluginRegistry",
    "registry",
]
