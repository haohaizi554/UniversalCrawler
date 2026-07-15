"""描述下载停止、外部工具故障、媒体合并及流传输失败。"""

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
