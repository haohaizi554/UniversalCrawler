"""抖音底层能力模块，负责 `app/core/lib/douyin/encrypt/ttWid.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/encrypt/ttWid.py
from asyncio import run
from http import cookies
from json import dumps
from typing import TYPE_CHECKING, Union

try:
    from ..tools import PARAMS_HEADERS, PARAMS_HEADERS_TIKTOK, request_params
except ImportError:
    PARAMS_HEADERS = {}
    PARAMS_HEADERS_TIKTOK = {}
    """执行 `request_params` 对应的业务逻辑。"""
    async def request_params(*args, **kwargs):
        """Fallback async request stub used when the real helper is unavailable."""

        pass

try:
    from ..translation import _
except ImportError:
    """提供 `_` 对应的内部辅助逻辑。"""
    def _(x):
        """Fallback translator that returns the original text unchanged."""

        return x

if TYPE_CHECKING:
    from typing import Any
    BaseLogger = Any
    LoggerManager = Any
    Logger = Any

__all__ = ["TtWid", "TtWidTikTok"]


class TtWid:
    """封装 `TtWid` 在 `app/core/lib/douyin/encrypt/ttWid.py` 中承担的核心逻辑。"""
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
        """获取 `tt_wid` 对应的数据或状态，供 `TtWid` 使用。"""
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
        """执行 `extract` 对应的业务逻辑，供 `TtWid` 使用。"""
        if c := headers.get("Set-Cookie"):
            cookie_jar = cookies.SimpleCookie()
            cookie_jar.load(c)
            if v := cookie_jar.get(key):
                return {key: v.value}
        logger.error(f"获取 {key} 参数失败！")


class TtWidTikTok(TtWid):
    """封装 `TtWidTikTok` 在 `app/core/lib/douyin/encrypt/ttWid.py` 中承担的核心逻辑。"""
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
        """获取 `tt_wid` 对应的数据或状态，供 `TtWidTikTok` 使用。"""
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
    """执行 `test` 对应的业务逻辑。"""
    class Logger:
        """执行 `error` 对应的业务逻辑，供 `Logger` 使用。"""
        """封装 `Logger` 的日志记录、格式化或输出逻辑。"""
        def error(self, msg):
            """Print an error message to the console."""

            print(msg)
        """执行 `info` 对应的业务逻辑，供 `Logger` 使用。"""
        def info(self, msg, *args):
            """Print an informational message to the console."""

            print(msg)

    print("抖音", await TtWid.get_tt_wid(Logger(), PARAMS_HEADERS, proxy=None))
    # print(
    #     "TikTok",
    #     await TtWidTikTok.get_tt_wid(
    #         Logger(),
    #         PARAMS_HEADERS_TIKTOK,
    #         cookie="ttwid=",
    #         proxy="http://localhost:10809",
    #     ),
    # )

if __name__ == "__main__":
    run(test())