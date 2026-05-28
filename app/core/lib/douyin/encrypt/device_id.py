"""抖音底层能力模块，负责 `app/core/lib/douyin/encrypt/device_id.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/encrypt/device_id.py
from asyncio import run
from re import compile
from typing import TYPE_CHECKING, Union

# 调整引用路径
try:
    from ..tools import PARAMS_HEADERS_TIKTOK, request_params
except ImportError:
    PARAMS_HEADERS_TIKTOK = {}
    """执行 `request_params` 对应的业务逻辑。"""
    async def request_params(*args, **kwargs):
        """Fallback async request stub used when the real helper is unavailable."""

        pass

if TYPE_CHECKING:
    from typing import Any
    BaseLogger = Any
    LoggerManager = Any
    Logger = Any

__all__ = ["DeviceId"]


class DeviceId:
    """封装 `DeviceId` 在 `app/core/lib/douyin/encrypt/device_id.py` 中承担的核心逻辑。"""
    NAME = "device_id"
    URL = "https://www.tiktok.com/explore"
    DEVICE_ID = compile(r'"wid":"(\d{19})"')

    @classmethod
    async def get_device_id(
        cls,
        logger: Union["BaseLogger", "LoggerManager", "Logger"],
        headers: dict,
        **kwargs,
    ) -> [str, str]:
        """获取 `device_id` 对应的数据或状态，供 `DeviceId` 使用。"""
        response = await request_params(
            logger,
            cls.URL,
            "GET",
            headers=headers,
            resp="response",
            **kwargs,
        )
        response.raise_for_status()
        device_id = d.group(1) if (d := cls.DEVICE_ID.search(response.text)) else ""
        cookie = "; ".join(
            [f"{key}={value}" for key, value in response.cookies.items()]
        )
        return device_id, cookie

    @classmethod
    async def get_device_ids(
        cls,
        logger: Union["BaseLogger", "LoggerManager", "Logger"],
        headers: dict,
        number: int,
        **kwargs,
    ) -> [[str, str]]:
        """获取 `device_ids` 对应的数据或状态，供 `DeviceId` 使用。"""
        return [
            await cls.get_device_id(
                logger,
                headers,
                **kwargs,
            )
            for _ in range(number)
        ]


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

    print(
        await DeviceId.get_device_id(
            Logger(),
            PARAMS_HEADERS_TIKTOK,
            proxy="http://127.0.0.1:7890",
        )
    )
    # print(await DeviceId.get_device_ids(
    #     Logger(),
    #     PARAMS_HEADERS_TIKTOK,
    #     5,
    #     proxy="http://127.0.0.1:7890",
    # ))

if __name__ == "__main__":
    run(test())