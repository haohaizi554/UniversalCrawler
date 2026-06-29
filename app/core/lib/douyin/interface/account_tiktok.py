"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/account_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/account_tiktok.py
from typing import TYPE_CHECKING, Callable, Coroutine, Type, Union
from .account import Account
from .template import APITikTok

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

class AccountTikTok(
    Account,
    APITikTok,
):
    
    post_api = f"{APITikTok.domain}api/post/item_list/"
    favorite_api = f"{APITikTok.domain}api/favorite/item_list/"

    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        sec_user_id: str = ...,
        tab="post",
        earliest: str | float | int = "",
        latest: str | float | int = "",
        pages: int = None,
        cursor=0,
        count=16,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `AccountTikTok` 使用。"""
        super().__init__(
            params,
            cookie,
            proxy,
            sec_user_id,
            tab,
            earliest,
            latest,
            pages,
            cursor,
            count,
            *args,
            **kwargs,
        )

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
        """执行当前对象或脚本的主流程，供 `AccountTikTok` 使用。"""
        self.set_referer(referer)
        match single_page:
            case True:
                await self.run_single(
                    data_key,
                    error_text=error_text,
                    cursor=cursor,
                    has_more=has_more,
                    params=params,
                    data=data,
                    method=method,
                    headers=headers,
                    *args,
                    **kwargs,
                )
                return self.response
            case False:
                await self.run_batch(
                    data_key,
                    error_text=error_text,
                    cursor=cursor,
                    has_more=has_more,
                    params=params,
                    data=data,
                    method=method,
                    headers=headers,
                    *args,
                    **kwargs,
                )
                return self.response, self.earliest, self.latest
        raise ValueError

    async def run_batch(
        self,
        data_key: str = "itemList",
        error_text="",
        cursor="cursor",
        has_more="hasMore",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        callback: Type[Coroutine] = None,
        *args,
        **kwargs,
    ):
        
        await super().run_batch(
            data_key=data_key,
            error_text=error_text,
            cursor=cursor,
            has_more=has_more,
            params=params,
            data=data,
            method=method,
            headers=headers,
            callback=callback,
            *args,
            **kwargs,
        )

    def generate_favorite_params(self) -> dict:
        
        return self.generate_post_params()

    def generate_post_params(self) -> dict:
        
        return self.params | {
            "secUid": self.sec_user_id,
            "count": self.count,
            "cursor": self.cursor,
            "coverFormat": "2",
            "post_item_list_request_type": "0",
            "needPinnedItemIds": "true",
            "video_encoding": "mp4",
        }

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())