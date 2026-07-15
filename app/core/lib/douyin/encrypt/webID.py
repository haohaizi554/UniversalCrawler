"""向抖音 WebId 接口申请浏览器标识。"""

from asyncio import run
from typing import TYPE_CHECKING, Union

# 工具包不可用时仍允许模块被导入；占位请求不会访问网络。
try:
    from ..tools import PARAMS_HEADERS, request_params
except ImportError:
    PARAMS_HEADERS = {}

    async def request_params(*args, **kwargs):
        pass

try:
    from ..translation import _
except ImportError:
    # 翻译层不可用时保留原文，避免兼容分支影响请求流程。
    def _(x):
        return x

if TYPE_CHECKING:
    from typing import Any

    BaseLogger = Any
    LoggerManager = Any
    Logger = Any

__all__ = ["WebId"]

class WebId:
    """提交 UA 与页面来源并读取接口返回的 web_id。"""
    
    NAME = "webid"
    API = "https://mcs.zijieapi.com/webid"
    PARAMS = {"aid": "6383", "sdk_version": "5.1.18_zip", "device_platform": "web"}

    @classmethod
    async def get_web_id(
            cls,
            logger: Union["BaseLogger", "LoggerManager", "Logger"],
            headers: dict,
            proxy: str = None,
            **kwargs,
    ) -> str | None:
        
        user_agent = headers.get("User-Agent")
        data = (
            f'{{"app_id":6383,"url":"https://www.douyin.com/","user_agent":"{user_agent}","referer":"https://www'
            f'.douyin.com/","user_unique_id":""}}'
        )
        if response := await request_params(
                logger,
                cls.API,
                params=cls.PARAMS,
                data=data,
                headers=headers,
                resp="json",
                proxy=proxy,
                **kwargs,
        ):
            return response.get("web_id")
        logger.error(_("获取 {name} 参数失败！").format(name=cls.NAME))

async def test():
    
    class Logger:
        
        def error(self, msg):
            print(msg)

        
        def info(self, msg, *args):
            print(msg)

    print(await WebId.get_web_id(Logger(), PARAMS_HEADERS, proxy=None))

if __name__ == "__main__":
    run(test())
