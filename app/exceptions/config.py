"""异常定义模块，集中声明 `app/exceptions/config.py` 使用的异常类型。"""

from .base import AppError

class ConfigError(AppError):
    """配置相关异常。"""

class ConfigReadError(ConfigError):
    """配置文件读取失败。"""

class ConfigWriteError(ConfigError):
    """配置文件写入失败。"""

class ConfigValidationError(ConfigError):
    """配置校验失败。"""
