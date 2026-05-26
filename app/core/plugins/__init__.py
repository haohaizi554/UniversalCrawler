from .base import BasePlugin
from .definitions import BilibiliPlugin, DouyinPlugin, KuaishouPlugin, MissAVPlugin
from .registry import PluginRegistry, registry

__all__ = [
    "BasePlugin",
    "DouyinPlugin",
    "KuaishouPlugin",
    "MissAVPlugin",
    "BilibiliPlugin",
    "PluginRegistry",
    "registry",
]
