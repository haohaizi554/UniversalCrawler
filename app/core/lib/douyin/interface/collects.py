"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/collects.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/collects.py
from typing import TYPE_CHECKING, Callable, Union
from .collection import Collection
from .template import API

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


class Collects(API):
    """封装 `Collects` 在 `app/core/lib/douyin/interface/collects.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        cursor=0,
        count=10,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `Collects` 使用。"""
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}aweme/v1/web/collects/list/"
        self.text = _("收藏夹")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `Collects` 使用。"""
        return self.params | {
            "cursor": self.cursor,
            "count": self.count,
            "version_code": "170400",
            "version_name": "17.4.0",
        }

    async def run(
        self,
        referer: str = "https://www.douyin.com/user/self?showTab=favorite_collection",
        single_page=False,
        data_key: str = "collects_list",
        error_text="",
        cursor="cursor",
        has_more="has_more",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `Collects` 使用。"""
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text or _("当前账号无收藏夹"),
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )


class CollectsDetail(Collection, API):
    """封装 `CollectsDetail` 在 `app/core/lib/douyin/interface/collects.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        collects_id: str = ...,
        pages: int = None,
        cursor=0,
        count=10,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `CollectsDetail` 使用。"""
        super().__init__(params, cookie, proxy, None, *args, **kwargs)
        self.collects_id = collects_id
        self.pages = pages or params.max_pages
        self.api = f"{self.domain}aweme/v1/web/collects/video/list/"
        self.cursor = cursor
        self.count = count
        self.text = _("收藏夹作品")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `CollectsDetail` 使用。"""
        return self.params | {
            "collects_id": self.collects_id,
            "cursor": self.cursor,
            "count": self.count,
            "version_code": "170400",
            "version_name": "17.4.0",
        }

    async def run(
        self,
        referer: str = "https://www.douyin.com/user/self?showTab=favorite_collection",
        single_page=False,
        data_key: str = "aweme_list",
        error_text="",
        cursor="cursor",
        has_more="has_more",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `CollectsDetail` 使用。"""
        await super(Collection, self).run(
            referer,
            single_page,
            data_key,
            error_text
            or _("收藏夹 {collects_id} 为空").format(collects_id=self.collects_id),
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )
        return self.response


class CollectsMix(API):
    """封装 `CollectsMix` 在 `app/core/lib/douyin/interface/collects.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        cursor=0,
        count=12,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `CollectsMix` 使用。"""
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}aweme/v1/web/mix/listcollection/"
        self.text = _("收藏合集")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `CollectsMix` 使用。"""
        return self.params | {
            "cursor": self.cursor,
            "count": self.count,
            "version_code": "170400",
            "version_name": "17.4.0",
        }

    async def run(
        self,
        referer: str = "https://www.douyin.com/user/self?showTab=favorite_collection",
        single_page=False,
        data_key: str = "mix_infos",
        error_text="",
        cursor="cursor",
        has_more="has_more",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        proxy: str = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `CollectsMix` 使用。"""
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text or _("当前账号无收藏合集"),
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            proxy,
            *args,
            **kwargs,
        )


class CollectsSeries(CollectsMix):
    """封装 `CollectsSeries` 在 `app/core/lib/douyin/interface/collects.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        cursor=0,
        count=12,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `CollectsSeries` 使用。"""
        super().__init__(
            params,
            cookie,
            proxy,
            *args,
            **kwargs,
        )
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}aweme/v1/web/series/collections/"
        self.text = _("收藏短剧")

    async def run(
        self,
        referer: str = "https://www.douyin.com/user/self?showTab=favorite_collection",
        single_page=False,
        data_key: str = "series_infos",
        error_text="",
        cursor="cursor",
        has_more="has_more",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `CollectsSeries` 使用。"""
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text or _("当前账号无收藏短剧"),
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )


class CollectsMusic(CollectsMix):
    """封装 `CollectsMusic` 在 `app/core/lib/douyin/interface/collects.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        cursor=0,
        count=20,
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `CollectsMusic` 使用。"""
        super().__init__(
            params,
            cookie,
            proxy,
            *args,
            **kwargs,
        )
        self.cursor = cursor
        self.count = count
        self.api = f"{self.domain}aweme/v1/web/music/listcollection/"
        self.text = _("收藏音乐")

    async def run(
        self,
        referer: str = "https://www.douyin.com/user/self?showTab=favorite_collection",
        single_page=False,
        data_key: str = "mc_list",
        error_text="",
        cursor="cursor",
        has_more="has_more",
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `CollectsMusic` 使用。"""
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text or _("当前账号无收藏音乐"),
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