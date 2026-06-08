"""插件模块，负责 `app/core/plugins/registry.py` 对应的平台定义、注册或设置构建逻辑。"""
from __future__ import annotations
from .base import BasePlugin
from .definitions import BilibiliPlugin, DouyinPlugin, KuaishouPlugin, MissAVPlugin
from .discovery import discover_builtin_plugins

class PluginRegistry:
    """封装 `PluginRegistry` 在 `app/core/plugins/registry.py` 中承担的核心逻辑。"""
    def __init__(self, plugins: list[BasePlugin] | None = None):
        """初始化当前实例并准备运行所需的状态，供 `PluginRegistry` 使用。"""
        self._plugins: dict[str, BasePlugin] = {}
        # 只有显式传入 None 时才执行内建插件自动发现；空列表表示“不要任何默认插件”。
        initial_plugins = discover_builtin_plugins() if plugins is None else plugins
        for plugin in initial_plugins:
            self.register(plugin)

    #注册插件
    def register(self, plugin: BasePlugin) -> None:
        """执行 `register` 对应的业务逻辑，供 `PluginRegistry` 使用。"""
        if plugin.id in self._plugins:
            raise ValueError(f"重复的插件 ID: {plugin.id}")
        self._plugins[plugin.id] = plugin

    def get_all_plugins(self) -> list[BasePlugin]:
        """获取 `all_plugins` 对应的数据或状态，供 `PluginRegistry` 使用。"""
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """获取 `plugin` 对应的数据或状态，供 `PluginRegistry` 使用。"""
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
