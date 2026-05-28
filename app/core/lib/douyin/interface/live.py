"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/live.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/live.py
from typing import TYPE_CHECKING, Union
from .template import API, CHROME_VERSION

try:
    from ..tools import DownloaderError
except ImportError:
    """定义 `DownloaderError` 异常类型，用于表达特定失败场景。"""
    class DownloaderError(Exception):
        """Fallback error type used when the real downloader exception cannot be imported."""

        pass

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any


class Live(API):
    """封装 `Live` 在 `app/core/lib/douyin/interface/live.py` 中承担的核心逻辑。"""
    live_api = "https://live.douyin.com/webcast/room/web/enter/"
    live_api_share = "https://webcast.amemv.com/webcast/room/reflow/info/"

    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        web_rid: str = ...,
        room_id: str = ...,
        sec_user_id: str = "",
    ):
        """初始化当前实例并准备运行所需的状态，供 `Live` 使用。"""
        super().__init__(params, cookie, proxy)
        self.black_headers = params.headers_download
        self.web_rid = web_rid
        self.room_id = room_id
        self.sec_user_id = sec_user_id

    async def run(
        self,
        *args,
        **kwargs,
    ) -> dict:
        """执行当前对象或脚本的主流程，供 `Live` 使用。"""
        if isinstance(self.web_rid, str):
            return await self.with_web_rid()
        elif self.room_id:
            return await self.with_room_id()
        else:
            raise DownloaderError

    async def with_web_rid(self) -> dict:
        """执行 `with_web_rid` 对应的业务逻辑，供 `Live` 使用。"""
        self.set_referer("https://live.douyin.com/")
        # 直播页请求参数基本固定，只有房间标识会随入口变化。
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "web_share_link",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Edge",
            "browser_version": CHROME_VERSION,
            "web_rid": self.web_rid,
            # "room_id_str": "",
            "enter_source": "",
            "is_need_double_stream": "false",
            "insert_task_id": "",
            "live_reason": "",
        }
        return await self.request_data(
            self.live_api,
            params,
        )

    async def with_room_id(self) -> dict:
        """执行 `with_room_id` 对应的业务逻辑，供 `Live` 使用。"""
        params = {
            "type_id": "0",
            "live_id": "1",
            "room_id": self.room_id,
            "sec_user_id": self.sec_user_id,
            "app_id": "1128",
        }
        return await self.request_data(
            self.live_api_share,
            params,
            headers=self.black_headers,
        )


async def test():
    """执行 `test` 对应的业务逻辑。"""
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
