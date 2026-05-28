"""异常定义模块，集中声明 `app/exceptions/service.py` 使用的异常类型。"""

from .base import AppError


class ServiceError(AppError):
    """服务层异常。"""


class MediaScanError(ServiceError):
    """媒体目录扫描失败。"""


class FileOperationError(ServiceError):
    """文件重命名、删除等操作失败。"""


class DebugActionError(ServiceError):
    """调试入口执行失败。"""
