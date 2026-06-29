"""Base plugin contract with SPI auto-registration via __init_subclass__."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.spiders.base import BaseSpider

class BasePlugin:
    """Abstract base plugin.

    Subclasses are automatically registered via ``__init_subclass__`` and
    exposed through :func:`get_subclasses`.  A plugin declares:

    * ``id`` — unique string identifier (the **SPI key**)
    * ``name`` — human-readable label
    * ``sort_order`` — integer sort key (lower = earlier)
    * ``description`` — optional one-line summary
    * ``settings_builder`` — optional ``Callable[[], dict[str, Any]]`` that
      returns field definitions for auto-generated settings UI
    """

    id: str = "base"
    name: str = "Base Plugin"
    sort_order: int = 1000
    description: str = ""

    # SPI: auto-registry of all concrete subclasses
    _subclasses: dict[str, type[BasePlugin]] = {}

    # Optional: a callable that returns widget builder + run-option reader
    # (lazy-imported from app.ui.plugin_settings to keep core Qt-free)
    settings_builder: Callable[[], dict[str, Any]] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Automatically register every concrete (non-abstract) subclass."""
        super().__init_subclass__(**kwargs)
        pid = getattr(cls, "id", None)
        if pid and pid != "base":
            cls._subclasses[pid] = cls

    # ------------------------------------------------------------------
    # SPI methods — override in concrete plugins
    # ------------------------------------------------------------------

    def get_search_placeholder(self) -> str:
        """Placeholder text shown in the search input."""
        return "请输入关键词..."

    def get_spider_class(self) -> type[BaseSpider]:
        """Return the spider class for this platform."""
        raise NotImplementedError

    def get_downloader_class(self):
        """Return the downloader class for this platform.

        Override to associate a custom downloader.  The default returns
        ``None``, meaning the registry falls back to ``source_id`` matching.
        """
        return None

    def get_default_config(self) -> dict[str, Any]:
        """Return the default runtime config for this platform.

        Used by CLI / SDK / Web when no user config is supplied.
        """
        return {}

    def get_download_defaults(self) -> dict[str, str]:
        """Return default HTTP headers (ua, referer, …) for direct downloads."""
        return {}

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def get_subclasses(cls) -> dict[str, type[BasePlugin]]:
        """Return a copy of the SPI auto-registry."""
        return dict(cls._subclasses)

    @classmethod
    def get_subclass(cls, plugin_id: str) -> type[BasePlugin] | None:
        """Look up a plugin class by id from the SPI registry."""
        return cls._subclasses.get(plugin_id)

# Convenience exports
__all__ = [
    "BasePlugin",
]
