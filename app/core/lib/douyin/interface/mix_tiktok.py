"""获取 TikTok 合辑列表及合辑内作品。"""

from typing import TYPE_CHECKING, Callable, Union
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

class MixTikTok(APITikTok):
    """分页获取指定 TikTok 合辑中的作品。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        mix_title: str = ...,
        mix_id: str = ...,
        cursor=0,
        count=30,
        *args,
        **kwargs,
    ):
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.mix_title = mix_title
        self.mix_id = mix_id
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}api/collection/item_list/"
        self.text = _("合辑作品")

    def generate_params(
        self,
    ) -> dict:
        
        return self.params | {
            "count": self.count,
            "cursor": self.cursor,
            "collectionId": self.mix_id,
            "sourceType": "113",
        }

    async def run(
        self,
        referer: str = None,
        single_page=False,
        data_key: str = "itemList",
        error_text="",
        cursor="cursor",
        has_more="hasMore",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text,
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )

class MixListTikTok(APITikTok):
    """分页列出指定 TikTok 账号公开的合辑。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        sec_user_id: str = "",
        cursor=0,
        count=20,
        *args,
        **kwargs,
    ):
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.sec_user_id = sec_user_id
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}api/user/playlist/"
        self.text = _("账号合辑数据")

    def generate_params(
        self,
    ) -> dict:
        
        return self.params | {
            "count": self.count,
            "cursor": self.cursor,
            "secUid": self.sec_user_id,
        }

    async def run(
        self,
        referer: str = None,
        single_page=False,
        data_key: str = "playList",
        error_text="",
        cursor="cursor",
        has_more="hasMore",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text,
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
