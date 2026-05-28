"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/info_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/info_tiktok.py
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


class InfoTikTok(APITikTok):
    """封装 `InfoTikTok` 在 `app/core/lib/douyin/interface/info_tiktok.py` 中承担的核心逻辑。"""
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        unique_id: Union[str] = "",
        sec_user_id: Union[str] = "",
        *args,
        **kwargs,
    ):
        """初始化当前实例并准备运行所需的状态，供 `InfoTikTok` 使用。"""
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.api = f"{self.domain}api/user/detail/"
        self.unique_id = unique_id
        self.sec_user_id = sec_user_id
        self.text = _("账号简略")

    async def run(
        self,
        # first=True,
        *args,
        **kwargs,
    ) -> dict | list[dict]:
        """执行当前对象或脚本的主流程，供 `InfoTikTok` 使用。"""
        self.set_referer()
        await self.run_single()
        return self.response[0] if self.response else {}

    async def run_single(
        self,
        *args,
        **kwargs,
    ):
        """执行 `run_single` 对应的业务逻辑，供 `InfoTikTok` 使用。"""
        await super().run_single(
            "",
        )

    def check_response(
        self,
        data_dict: dict,
        *args,
        **kwargs,
    ):
        """执行 `check_response` 对应的业务逻辑，供 `InfoTikTok` 使用。"""
        if d := data_dict.get("userInfo"):
            self.append_response(d)
        else:
            self.log.warning(_("获取{text}失败").format(text=self.text))

    def append_response(
        self,
        data: dict,
        *args,
        **kwargs,
    ) -> None:
        """执行 `append_response` 对应的业务逻辑，供 `InfoTikTok` 使用。"""
        self.response.append(data)

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `InfoTikTok` 使用。"""
        return self.params | {
            "abTestVersion": "[object Object]",
            "appType": "t",
            "secUid": self.sec_user_id,
            "uniqueId": self.unique_id,
            "user": "[object Object]",
        }


async def test():
    """执行 `test` 对应的业务逻辑。"""
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())