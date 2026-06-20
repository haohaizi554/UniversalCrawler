"""Re-export stable downloader API symbols.

Concrete platform downloaders are discovered at runtime via the plugin
bridge ``downloader_registry.resolve()``.  Explicit imports from this
module are only needed for type-hinting / base-class references.
"""

from .base import BaseDownloader, ProgressCallback, StopCheck
from .chunked import ChunkedDownloader
from .external import FFmpegExternalTool, NM3U8DLREExternalTool
from .ffmpeg import FFmpegDownloader
from .m3u8 import N_m3u8DL_RE_Downloader

__all__ = [
    "BaseDownloader",
    "ProgressCallback",
    "StopCheck",
    "ChunkedDownloader",
    "FFmpegExternalTool",
    "NM3U8DLREExternalTool",
    "N_m3u8DL_RE_Downloader",
    "FFmpegDownloader",
]
