"""Plugin registry with SPI, entry-point, and external-directory support."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePlugin

class PluginRegistry:
    """Central plugin registry.

    Supports three discovery sources:
    1. **Builtin SPI** — ``BasePlugin.__init_subclass__`` auto-registers
       all concrete subclasses in ``app.core.plugins.definitions``.
    2. **Entry points** — packages installed with ``ucrawl.plugins`` group.
    3. **External directory** — ``.py`` files scanned from a user-configured
       directory (hot-reload capable).

    Unlike the old hardcoded-import approach, adding a new platform requires
    **zero changes** to this file — just author a ``BasePlugin`` subclass
    somewhere that gets imported at startup.

    Thread-safe (``threading.RLock``).
    """

    def __init__(
        self,
        plugins: list[BasePlugin] | None = None,
        *,
        external_plugin_dir: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._plugins: dict[str, BasePlugin] = {}

        # Set external dir BEFORE auto-discover so external plugins are found.
        if external_plugin_dir is not None:
            from .discovery import set_external_plugin_dir

            set_external_plugin_dir(external_plugin_dir)

        # None = auto-discover builtins + entry-point + external (eager).
        # Explicit list = seed with those (empty list = no defaults).
        if plugins is None:
            self._ensure_loaded()
        else:
            for plugin in plugins:
                self.register(plugin)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance.

        Raises ``ValueError`` on duplicate ``id``.
        """
        with self._lock:
            self._register_unlocked(plugin)

    def _register_unlocked(self, plugin: BasePlugin) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f"重复的插件 ID: {plugin.id}")
        self._plugins[plugin.id] = plugin

    def unregister(self, plugin_id: str) -> bool:
        """Remove a plugin by id.  Returns ``True`` if removed."""
        with self._lock:
            return self._plugins.pop(plugin_id, None) is not None

    def register_from_class(self, plugin_cls: type[BasePlugin]) -> BasePlugin:
        """Instantiate *plugin_cls* and register it.  Returns the instance."""
        instance = plugin_cls()
        self.register(instance)
        return instance

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_all_plugins(self) -> list[BasePlugin]:
        """Return a snapshot of all registered plugins."""
        with self._lock:
            return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """Look up a plugin by id."""
        with self._lock:
            return self._plugins.get(plugin_id)

    def get_plugin_class(self, plugin_id: str) -> type[BasePlugin] | None:
        """Look up a **plugin class** by id.

        Returns ``None`` if the id is not registered.
        """
        from .base import BasePlugin as _BP

        return _BP.get_subclass(plugin_id)

    # ------------------------------------------------------------------
    # Aggregate discovery  (lazy — only when first queried)
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Discover and register plugins from all sources.

        Aggregates builtin SPI + entry-point + external plugins.
        Called once on first init (unless user passed an explicit plugin
        list).  Subsequent calls are no-ops (hot-reload uses a separate path).
        """
        if self._plugins:
            return

        with self._lock:
            if self._plugins:  # double-check
                return
            from .discovery import discover_builtin_plugin_instances as _di

            for plugin in _di():
                self._register_unlocked(plugin)

    def _hot_reload_external(self) -> None:
        """Discover external-directory plugins, registering new/changed ones."""
        from .discovery import discover_external_plugins as _discover_ext

        for plugin_cls in _discover_ext():
            pid = getattr(plugin_cls, "id", None)
            if pid and pid not in self._plugins:
                self._register_unlocked(plugin_cls())

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload_plugins(self) -> list[str]:
        """Hot-reload external plugins.  Returns ids of newly registered plugins.

        Use this at runtime to pick up new ``.py`` files or changes in the
        external plugin directory without restarting the app.
        """
        with self._lock:
            before = set(self._plugins.keys())
            self._hot_reload_external()
            after = set(self._plugins.keys())
        return list(after - before)

    # ------------------------------------------------------------------
    # Convenience wrappers on get_all_plugins (auto-load)
    # ------------------------------------------------------------------

    def get_plugin_safe(self, plugin_id: str) -> BasePlugin | None:
        """Like ``get_plugin`` but triggers auto-discovery on first call."""
        self._ensure_loaded()
        return self.get_plugin(plugin_id)

    def get_all_plugins_safe(self) -> list[BasePlugin]:
        """Like ``get_all_plugins`` but triggers auto-discovery on first call."""
        self._ensure_loaded()
        return self.get_all_plugins()

    def __repr__(self) -> str:
        n = len(self._plugins)
        return f"<PluginRegistry ({n} plugins)>"

# Module-level singleton.  Created without auto-discover — callers that want
# the full set must call ``get_plugin_safe`` / ``get_all_plugins_safe`` (or
# ``_ensure_loaded``).
#
# Keeping lazy avoids import-time side effects (Qt settings builders, …).
registry = PluginRegistry()

__all__ = [
    "PluginRegistry",
    "registry",
]
