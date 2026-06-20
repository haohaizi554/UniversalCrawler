"""Downloader registry backed by the plugin system.

Bridge: populates itself from ``BasePlugin.get_downloader_class()`` so one
``get_downloader_class()`` override per plugin eliminates all hardcoded
import lists in download dispatch code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import VideoItem
    from .base import BaseDownloader


class DownloaderRegistry:
    """Lazily-built index of plugin-provided downloader classes."""

    def __init__(self) -> None:
        self._downloaders: dict[str, type[BaseDownloader]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        from app.core.plugin_registry import registry

        for plugin in registry.get_all_plugins():
            downloader_cls = plugin.get_downloader_class()
            if downloader_cls is not None:
                sid = getattr(downloader_cls, "source_id", None) or plugin.id
                existing = self._downloaders.get(sid)
                if existing and existing is not downloader_cls:
                    raise ValueError(f"重复的下载器 source_id: {sid}")
                self._downloaders[sid] = downloader_cls
        self._loaded = True

    def register(self, downloader_cls: type[BaseDownloader]) -> None:
        sid = getattr(downloader_cls, "source_id", None)
        if not sid:
            return
        existing = self._downloaders.get(sid)
        if existing and existing is not downloader_cls:
            raise ValueError(f"重复的下载器 source_id: {sid}")
        self._downloaders[sid] = downloader_cls

    def get(self, source_id: str) -> type[BaseDownloader] | None:
        self._ensure_loaded()
        return self._downloaders.get(source_id)

    def all(self) -> list[type[BaseDownloader]]:
        self._ensure_loaded()
        return list(self._downloaders.values())

    def resolve(self, video_item: VideoItem) -> type[BaseDownloader] | None:
        """Find a downloader whose ``can_handle()`` matches *video_item*."""
        self._ensure_loaded()
        for downloader_cls in self._downloaders.values():
            if downloader_cls.can_handle(video_item):
                return downloader_cls
        return None


downloader_registry = DownloaderRegistry()
