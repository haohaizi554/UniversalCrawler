"""核心模块，负责 `app/core/plugin_registry.py` 对应的调度、注册或运行期能力。"""

from .plugins import BasePlugin, BilibiliPlugin, DouyinPlugin, KuaishouPlugin, MissAVPlugin, PluginRegistry, registry

__all__ = [
    "BasePlugin",
    "DouyinPlugin",
    "KuaishouPlugin",
    "MissAVPlugin",
    "BilibiliPlugin",
    "PluginRegistry",
    "registry",
]
