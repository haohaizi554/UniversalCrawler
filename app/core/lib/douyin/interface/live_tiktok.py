"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/live_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/live_tiktok.py
from typing import TYPE_CHECKING, Union
from .template import APITikTok

try:
    from ..translation import _
except ImportError:
    """提供 `_` 对应的内部辅助逻辑。"""
    def _(x):
        """Fallback translator that returns the original text unchanged."""

        return x

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

class LiveTikTok(APITikTok):
    
    live_api = "https://webcast.us.tiktok.com/webcast/room/enter/"

    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        room_id: str = ...,
    ):
        """初始化当前实例并准备运行所需的状态，供 `LiveTikTok` 使用。"""
        super().__init__(params, cookie, proxy)
        self.black_headers = params.headers_download
        self.room_id = room_id

    async def run(
        self,
        *args,
        **kwargs,
    ) -> dict:
        """执行当前对象或脚本的主流程，供 `LiveTikTok` 使用。"""
        response = await self.with_room_id()
        return self.check_response(response)

    async def with_room_id(self) -> dict:
        
        return await self.request_data(
            self.live_api,
            self.params,
            method="POST",
            data=self.__generate_room_id_data(),
        )

    def __generate_room_id_data(
        self,
    ) -> dict:
        """提供 `__generate_room_id_data` 对应的内部辅助逻辑，供 `LiveTikTok` 使用。"""
        return {
            "enter_source": "others-others",
            "room_id": self.room_id,
        }

    def check_response(
        self,
        data_dict: dict,
        *args,
        **kwargs,
    ):
        
        if data_dict and "prompt" in data_dict["data"]:
            self.console.warning(_("此直播可能会令部分观众感到不适，请登录后重试！"))
            return {}
        return data_dict

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())