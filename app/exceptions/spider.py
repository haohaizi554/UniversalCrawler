"""异常定义模块，集中声明 `app/exceptions/spider.py` 使用的异常类型。"""

from .base import AppError


class SpiderError(AppError):
    """爬虫基础异常。"""


class SpiderAuthError(SpiderError):
    """登录或认证失败。"""


class CookieLoadError(SpiderAuthError):
    """Cookie 或登录态读取失败。"""


class CookieSaveError(SpiderAuthError):
    """Cookie 或登录态保存失败。"""


class InvalidCookieStateError(SpiderAuthError):
    """本地 Cookie 或登录态结构非法、缺少关键字段。"""


class LoginTimeoutError(SpiderAuthError):
    """等待用户登录超时。"""


class LoginCancelledError(SpiderAuthError):
    """用户主动中止登录流程。"""


class LoginCheckError(SpiderAuthError):
    """远端登录状态检查失败。"""


class SpiderParseError(SpiderError):
    """页面或接口解析失败。"""


class StreamResolveError(SpiderParseError):
    """媒体流地址解析失败。"""
