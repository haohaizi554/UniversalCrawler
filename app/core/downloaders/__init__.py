"""导出稳定的下载器公共接口。

各平台下载器由插件桥接器 ``downloader_registry.resolve()`` 在运行时发现；
本模块中的显式导入仅用于类型标注和基类引用，不承担注册职责。
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
