"""获取 TikTok 账号的简略资料。"""

from typing import TYPE_CHECKING
from typing import Union
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

class InfoTikTok(APITikTok):
    """按 unique_id 或 sec_user_id 查询 TikTok 账号资料。"""
    
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
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.api = f"{self.domain}api/user/detail/"
        self.unique_id = unique_id
        self.sec_user_id = sec_user_id
        self.text = _("账号简略")

    async def run(
        self,
        *args,
        **kwargs,
    ) -> dict | list[dict]:
        """返回首个 userInfo 记录；接口无数据时返回空字典。"""
        self.set_referer()
        await self.run_single()
        return self.response[0] if self.response else {}

    async def run_single(
        self,
        *args,
        **kwargs,
    ):
        
        await super().run_single(
            "",
        )

    def check_response(
        self,
        data_dict: dict,
        *args,
        **kwargs,
    ):
        
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
        
        self.response.append(data)

    def generate_params(
        self,
    ) -> dict:
        
        return self.params | {
            "abTestVersion": "[object Object]",
            "appType": "t",
            "secUid": self.sec_user_id,
            "uniqueId": self.unique_id,
            "user": "[object Object]",
        }

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
