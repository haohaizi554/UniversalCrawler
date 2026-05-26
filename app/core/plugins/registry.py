from __future__ import annotations

from .base import BasePlugin
from .definitions import BilibiliPlugin, DouyinPlugin, KuaishouPlugin, MissAVPlugin, get_default_plugins


class PluginRegistry:
    def __init__(self, plugins: list[BasePlugin] | None = None):
        self._plugins: dict[str, BasePlugin] = {}
        # 只有显式传入 None 时才加载默认插件；空列表表示“不要任何默认插件”。
        initial_plugins = get_default_plugins() if plugins is None else plugins
        for plugin in initial_plugins:
            self.register(plugin)

    def register(self, plugin: BasePlugin) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f"重复的插件 ID: {plugin.id}")
        self._plugins[plugin.id] = plugin

    def get_all_plugins(self) -> list[BasePlugin]:
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        return self._plugins.get(plugin_id)


registry = PluginRegistry()

__all__ = [
    "BasePlugin",
    "DouyinPlugin",
    "KuaishouPlugin",
    "MissAVPlugin",
    "BilibiliPlugin",
    "PluginRegistry",
    "registry",
]
