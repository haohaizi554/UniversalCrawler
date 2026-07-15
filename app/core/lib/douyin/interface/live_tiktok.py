"""按 room_id 获取 TikTok 直播间数据。"""

from typing import TYPE_CHECKING, Union
from .template import APITikTok

try:
    from ..translation import _
except ImportError:
    def _(x):
        return x

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

class LiveTikTok(APITikTok):
    """提交直播间标识，并过滤需要登录确认的受限响应。"""
    
    live_api = "https://webcast.us.tiktok.com/webcast/room/enter/"

    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        room_id: str = ...,
    ):
        super().__init__(params, cookie, proxy)
        self.black_headers = params.headers_download
        self.room_id = room_id

    async def run(
        self,
        *args,
        **kwargs,
    ) -> dict:
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
        """生成直播入口接口要求的最小表单字段。"""
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
