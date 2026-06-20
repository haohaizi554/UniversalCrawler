"""Re-export stable plugin API symbols from ``app.core.plugins``.

Consumers should always import from this module:

    from app.core.plugin_registry import registry, BasePlugin, PluginRegistry

Concrete plugin classes (DouyinPlugin, …) are auto-registered via SPI
and accessible through ``registry.get_plugin(id)`` — there is no need to
import them explicitly.
"""

from .plugins import BasePlugin, PluginRegistry, registry

__all__ = [
    "BasePlugin",
    "PluginRegistry",
    "registry",
]
