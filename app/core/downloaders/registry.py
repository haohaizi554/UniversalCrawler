"""Downloader registry with lazy builtin discovery."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import VideoItem
    from .base import BaseDownloader


BUILTIN_DOWNLOADER_MODULES = (
    "app.core.downloaders.douyin",
    "app.core.downloaders.xiaohongshu",
    "app.core.downloaders.kuaishou",
    "app.core.downloaders.missav",
    "app.core.downloaders.bilibili",
)


class DownloaderRegistry:
    """Registry that mirrors PluginRegistry semantics for downloaders."""

    def __init__(self) -> None:
        self._downloaders: dict[str, type["BaseDownloader"]] = {}
        self._builtin_loaded = False

    def _ensure_builtin_loaded(self) -> None:
        if self._builtin_loaded:
            return
        for module_name in BUILTIN_DOWNLOADER_MODULES:
            import_module(module_name)
        self._builtin_loaded = True

    def register(self, downloader_cls: type["BaseDownloader"]) -> None:
        source_id = getattr(downloader_cls, "source_id", None)
        if not source_id:
            return
        existing = self._downloaders.get(source_id)
        if existing and existing is not downloader_cls:
            raise ValueError(f"重复的下载器 source_id: {source_id}")
        self._downloaders[source_id] = downloader_cls

    def get(self, source_id: str) -> type["BaseDownloader"] | None:
        self._ensure_builtin_loaded()
        return self._downloaders.get(source_id)

    def all(self) -> list[type["BaseDownloader"]]:
        self._ensure_builtin_loaded()
        return list(self._downloaders.values())

    def resolve(self, video_item: "VideoItem") -> type["BaseDownloader"] | None:
        self._ensure_builtin_loaded()
        for downloader_cls in self._downloaders.values():
            if downloader_cls.can_handle(video_item):
                return downloader_cls
        return None


downloader_registry = DownloaderRegistry()

