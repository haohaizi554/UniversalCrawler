"""包初始化模块，为 `app/core/downloaders` 提供统一导出或包级说明。"""

from .base import BaseDownloader, ProgressCallback, StopCheck
from .bilibili import BilibiliDownloader
from .chunked import ChunkedDownloader
from .douyin import DouyinDownloader
from .external import FFmpegExternalTool, NM3U8DLREExternalTool
from .ffmpeg import FFmpegDownloader
from .kuaishou import KuaishouDownloader
from .m3u8 import N_m3u8DL_RE_Downloader
from .missav import MissAVDownloader
from .xiaohongshu import XiaohongshuDownloader

__all__ = [
    "BaseDownloader",
    "ProgressCallback",
    "StopCheck",
    "ChunkedDownloader",
    "FFmpegExternalTool",
    "NM3U8DLREExternalTool",
    "N_m3u8DL_RE_Downloader",
    "KuaishouDownloader",
    "MissAVDownloader",
    "BilibiliDownloader",
    "FFmpegDownloader",
    "DouyinDownloader",
    "XiaohongshuDownloader",
]
