"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/mix_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/mix_tiktok.py
from typing import TYPE_CHECKING, Callable, Union
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


class MixTikTok(APITikTok):
    """封装 `MixTikTok` 在 `app/core/lib/douyin/interface/mix_tiktok.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        mix_title: str = ...,
        mix_id: str = ...,
        # detail_id: str = None,
        cursor=0,
        count=30,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `MixTikTok` 使用。"""
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.mix_title = mix_title
        self.mix_id = mix_id
        # self.detail_id = detail_id  # 未使用
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}api/collection/item_list/"
        self.text = _("合辑作品")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `MixTikTok` 使用。"""
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
        """执行当前对象或脚本的主流程，供 `MixTikTok` 使用。"""
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
    """封装 `MixListTikTok` 在 `app/core/lib/douyin/interface/mix_tiktok.py` 中承担的核心逻辑。"""
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
        """初始化当前实例并准备运行所需的状态，供 `MixListTikTok` 使用。"""
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.sec_user_id = sec_user_id
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}api/user/playlist/"
        self.text = _("账号合辑数据")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `MixListTikTok` 使用。"""
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
        """执行当前对象或脚本的主流程，供 `MixListTikTok` 使用。"""
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
    """执行 `test` 对应的业务逻辑。"""
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())