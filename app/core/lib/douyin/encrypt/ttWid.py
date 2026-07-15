"""请求并解析抖音与 TikTok 的 ttwid Cookie。"""

from asyncio import run
from http import cookies
from json import dumps
from typing import TYPE_CHECKING, Union

# 独立导入时保留最小占位，避免工具包缺失直接阻断模块加载。
try:
    from ..tools import PARAMS_HEADERS, PARAMS_HEADERS_TIKTOK, request_params
except ImportError:
    PARAMS_HEADERS = {}
    PARAMS_HEADERS_TIKTOK = {}
    
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

__all__ = ["TtWid", "TtWidTikTok"]

class TtWid:
    """从抖音注册接口的 Set-Cookie 中提取 ttwid。"""
    
    NAME = "ttwid"
    API = "https://ttwid.bytedance.com/ttwid/union/register/"
    DATA = (
        '{"region":"cn","aid":1768,"needFid":false,"service":"www.ixigua.com","migrate_info":{"ticket":"",'
        '"source":"node"},"cbUrlProtocol":"https","union":true}'
    )

    @classmethod
    async def get_tt_wid(
        cls,
        logger: Union["BaseLogger", "LoggerManager", "Logger"],
        headers: dict,
        proxy: str = None,
        **kwargs,
    ) -> dict | None:
        
        if response := await request_params(
            logger,
            cls.API,
            data=cls.DATA,
            headers=headers,
            proxy=proxy,
            **kwargs,
        ):
            return cls.extract(logger, response, cls.NAME)
        logger.error(_("获取 {name} 参数失败！").format(name=cls.NAME))

    @staticmethod
    def extract(
        logger: Union["BaseLogger", "LoggerManager", "Logger"], headers, key: str
    ) -> dict | None:
        """解析指定 Cookie 键；响应未携带该键时记录失败并返回 None。"""
        if c := headers.get("Set-Cookie"):
            cookie_jar = cookies.SimpleCookie()
            cookie_jar.load(c)
            if v := cookie_jar.get(key):
                return {key: v.value}
        logger.error(f"获取 {key} 参数失败！")

class TtWidTikTok(TtWid):
    """从 TikTok 校验接口的 Set-Cookie 中提取 ttwid。"""
    
    API = "https://www.tiktok.com/ttwid/check/"
    DATA = dumps(
        {
            "aid": 1988,
            "service": "www.tiktok.com",
            "union": False,
            "unionHost": "",
            "needFid": False,
            "fid": "",
            "migrate_priority": 0,
        },
        separators=(",", ":"),
    )

    @classmethod
    async def get_tt_wid(
        cls,
        logger: Union["BaseLogger", "LoggerManager", "Logger"],
        headers: dict,
        cookie: str = "",
        proxy: str = None,
        **kwargs,
    ) -> dict | None:
        
        if response := await request_params(
            logger,
            cls.API,
            data=cls.DATA,
            headers=headers
            | {
                "Cookie": cookie,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            proxy=proxy,
            **kwargs,
        ):
            return cls.extract(logger, response, cls.NAME)
        logger.error(_("获取 {name} 参数失败！").format(name=cls.NAME))

async def test():
    
    class Logger:
        
        def error(self, msg):
            print(msg)
        
        def info(self, msg, *args):
            print(msg)

    print("抖音", await TtWid.get_tt_wid(Logger(), PARAMS_HEADERS, proxy=None))

if __name__ == "__main__":
    run(test())
