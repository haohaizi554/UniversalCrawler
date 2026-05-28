"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/capture.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/capture.py
from json.decoder import JSONDecodeError
from ssl import SSLError
from typing import TYPE_CHECKING, Union
from httpx import HTTPStatusError, NetworkError, RequestError, TimeoutException
try:
    from ..translation import _
except ImportError:
    """提供 `_` 对应的内部辅助逻辑。"""
    def _(x):
        """Fallback translator that returns the original text unchanged."""

        return x
if TYPE_CHECKING:
    # 这里我们只引用 logger 的类型，具体的实现类可能暂时不存在
    # 为了避免类型检查报错，我们可以暂时使用 Any 或占位
    from typing import Any
    BaseLogger = Any
    LoggerManager = Any

__all__ = [
    "capture_error_params",
    "capture_error_request",
]

def capture_error_params(function):
    """执行 `capture_error_params` 对应的业务逻辑。"""
    async def inner(logger: Union["BaseLogger", "LoggerManager"], *args, **kwargs):
        """执行 `inner` 对应的业务逻辑。"""
        try:
            return await function(logger, *args, **kwargs)
        except (
            JSONDecodeError,
            UnicodeDecodeError,
        ):
            logger.error(_("响应内容不是有效的 JSON 数据"))
        except HTTPStatusError as e:
            logger.error(_("响应码异常：{error}").format(error=e))
        except NetworkError as e:
            logger.error(_("网络异常：{error}").format(error=e))
        except TimeoutException as e:
            logger.error(_("请求超时：{error}").format(error=e))
        except (
            RequestError,
            SSLError,
        ) as e:
            logger.error(_("网络异常：{error}").format(error=e))
        return None
    return inner

def capture_error_request(function):
    """执行 `capture_error_request` 对应的业务逻辑。"""
    async def inner(self, *args, **kwargs):
        """执行 `inner` 对应的业务逻辑。"""
        try:
            return await function(self, *args, **kwargs)
        except (JSONDecodeError, UnicodeDecodeError):
            self.log.error(_("响应内容不是有效的 JSON 数据，请尝试更新 Cookie！"))
        except HTTPStatusError as e:
            self.log.error(_("响应码异常：{error}").format(error=e))
        except NetworkError as e:
            self.log.error(_("网络异常：{error}").format(error=e))
        except TimeoutException as e:
            self.log.error(_("请求超时：{error}").format(error=e))
        except (
            RequestError,
            SSLError,
        ) as e:
            self.log.error(_("网络异常：{error}").format(error=e))
        return None
    return inner