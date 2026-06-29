"""Package init — exports stable API symbols for plugin consumers."""

from .base import BasePlugin
from .registry import PluginRegistry, registry

# NOTE: Concrete plugin classes (DouyinPlugin, …) are NOT listed here.
# They are auto-registered via __init_subclass__ SPI when their module is
# imported and can be looked up through ``registry.get_plugin(id)``.
# Importing them explicitly is neither required nor encouraged.

__all__ = [
    "BasePlugin",
    "PluginRegistry",
    "registry",
]
