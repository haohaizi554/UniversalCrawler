"""异常定义模块，集中声明 `app/exceptions/downloader.py` 使用的异常类型。"""

from .base import AppError


class DownloaderError(AppError):
    """下载器基础异常。"""


class DownloaderStoppedError(DownloaderError):
    """用户主动停止下载。"""


class ExternalToolError(DownloaderError):
    """外部工具调用失败。"""


class ExternalToolNotFoundError(ExternalToolError):
    """外部工具不存在。"""


class MergeError(DownloaderError):
    """音视频合并失败。"""


class StreamDownloadError(DownloaderError):
    """流下载失败。"""
