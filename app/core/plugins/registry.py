"""支持 SPI、Python 入口点与外部目录的插件注册表。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePlugin

class PluginRegistry:
    """线程安全的中心插件注册表。

    支持内置 SPI、``ucrawl.plugins`` 入口点和可热重载的用户外部目录三种来源。
    新平台只需提供一个启动时可导入的 ``BasePlugin`` 子类，无需修改本注册表。
    所有读写通过 ``threading.RLock`` 串行化。
    """

    def __init__(
        self,
        plugins: list[BasePlugin] | None = None,
        *,
        external_plugin_dir: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._plugins: dict[str, BasePlugin] = {}

        # 必须先设置外部目录，再执行自动发现，否则首次快照会漏掉用户插件。
        if external_plugin_dir is not None:
            from .discovery import set_external_plugin_dir

            set_external_plugin_dir(external_plugin_dir)

        # ``None`` 表示立即发现全部来源；显式列表只以给定插件初始化，空列表则不加载默认项。
        if plugins is None:
            self._ensure_loaded()
        else:
            for plugin in plugins:
                self.register(plugin)

    # 注册与注销

    def register(self, plugin: BasePlugin) -> None:
        """注册插件实例；平台 ID 重复时抛出 ``ValueError``。"""
        with self._lock:
            self._register_unlocked(plugin)

    def _register_unlocked(self, plugin: BasePlugin) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f"重复的插件 ID: {plugin.id}")
        self._plugins[plugin.id] = plugin

    def unregister(self, plugin_id: str) -> bool:
        """按 ID 移除插件，并返回是否确实移除了实例。"""
        with self._lock:
            return self._plugins.pop(plugin_id, None) is not None

    def register_from_class(self, plugin_cls: type[BasePlugin]) -> BasePlugin:
        """实例化 ``plugin_cls``、完成注册并返回该实例。"""
        instance = plugin_cls()
        self.register(instance)
        return instance

    # 查询稳定快照

    def get_all_plugins(self) -> list[BasePlugin]:
        """返回当前全部插件的稳定快照。"""
        with self._lock:
            return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """按平台 ID 查询插件实例。"""
        with self._lock:
            return self._plugins.get(plugin_id)

    def get_plugin_class(self, plugin_id: str) -> type[BasePlugin] | None:
        """按平台 ID 查询插件类；未注册时返回 ``None``。"""
        from .base import BasePlugin as _BP

        return _BP.get_subclass(plugin_id)

    # 首次查询时才执行的汇总发现

    def _ensure_loaded(self) -> None:
        """发现并登记所有来源的插件。

        未显式传入插件列表时只在首次查询执行一次；后续调用直接返回，外部目录
        的热重载由独立路径负责。
        """
        if self._plugins:
            return

        with self._lock:
            if self._plugins:  # 获取锁后再次检查，避免两个线程重复导入插件模块。
                return
            from .discovery import discover_builtin_plugin_instances as _di

            for plugin in _di():
                self._register_unlocked(plugin)

    def _hot_reload_external(self) -> None:
        """发现外部目录中新增或变化的插件并完成注册。"""
        from .discovery import discover_external_plugins as _discover_ext

        for plugin_cls in _discover_ext():
            pid = getattr(plugin_cls, "id", None)
            if pid and pid not in self._plugins:
                self._register_unlocked(plugin_cls())

    # 外部插件热重载

    def reload_plugins(self) -> list[str]:
        """热重载外部插件并返回新注册的 ID，无需重启应用即可接收文件变化。"""
        with self._lock:
            before = set(self._plugins.keys())
            self._hot_reload_external()
            after = set(self._plugins.keys())
        return list(after - before)

    # 自动触发发现的便捷查询

    def get_plugin_safe(self, plugin_id: str) -> BasePlugin | None:
        """与 ``get_plugin`` 相同，但首次调用前会自动发现插件。"""
        self._ensure_loaded()
        return self.get_plugin(plugin_id)

    def get_all_plugins_safe(self) -> list[BasePlugin]:
        """与 ``get_all_plugins`` 相同，但首次调用前会自动发现插件。"""
        self._ensure_loaded()
        return self.get_all_plugins()

    def __repr__(self) -> str:
        n = len(self._plugins)
        return f"<PluginRegistry ({n} plugins)>"

# 模块级单例故意不在导入时自动发现。需要完整插件集的调用方应使用
# ``get_plugin_safe`` / ``get_all_plugins_safe``；延迟加载可避免 Qt 设置构建器等
# 模块在导入阶段提前产生副作用。
registry = PluginRegistry()

__all__ = [
    "PluginRegistry",
    "registry",
]
