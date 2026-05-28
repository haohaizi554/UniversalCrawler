"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/detail_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/detail_tiktok.py
from typing import Callable
from typing import TYPE_CHECKING
from typing import Union

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


class DetailTikTok(APITikTok):
    """封装 `DetailTikTok` 在 `app/core/lib/douyin/interface/detail_tiktok.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        detail_id: str = ...,
    ):
        """初始化当前实例并准备运行所需的状态，供 `DetailTikTok` 使用。"""
        super().__init__(params, cookie, proxy)
        self.detail_id = detail_id
        self.api = f"{self.domain}/api/item/detail/"
        self.text = _("作品")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `DetailTikTok` 使用。"""
        return self.params | {
            "itemId": self.detail_id,
        }

    async def run(
        self,
        referer: str = None,
        single_page=True,
        data_key: str = None,
        error_text="",
        cursor=None,
        has_more=None,
        params: Callable = lambda: {},
        data: Callable = lambda: {},
        method="GET",
        headers: dict = None,
        *args,
        **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `DetailTikTok` 使用。"""
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

    def check_response(
        self,
        data_dict: dict,
        data_key: str = None,
        error_text="",
        cursor=None,
        has_more=None,
        *args,
        **kwargs,
    ):
        """执行 `check_response` 对应的业务逻辑，供 `DetailTikTok` 使用。"""
        try:
            if not (d := data_dict["itemInfo"]["itemStruct"]):
                self.log.info(error_text)
            else:
                self.response = d
        except KeyError:
            self.log.error(
                _("数据解析失败，请告知作者处理: {data}").format(data=data_dict)
            )

async def test():
    """执行 `test` 对应的业务逻辑。"""
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())