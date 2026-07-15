"""批量获取抖音账号的简略资料。"""

from typing import TYPE_CHECKING
from typing import Union
from .template import API

try:
    from ..translation import _
except ImportError:
    def _(x):
        return x

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

class Info(API):
    """通过一个或多个 sec_user_id 查询抖音账号简略资料。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        sec_user_id: Union[str, list[str], tuple[str]] = ...,
        *args,
        **kwargs,
    ):
        super().__init__(params, cookie, proxy, *args, **kwargs)
        self.api = f"{self.domain}aweme/v1/web/im/user/info/"
        self.sec_user_id = sec_user_id
        self.static_params = self.params | {
            "version_code": "170400",
            "version_name": "17.4.0",
        }
        self.text = _("账号简略")

    async def run(
        self,
        first=True,
        *args,
        **kwargs,
    ) -> dict | list[dict]:
        """默认返回首个账号；first=False 时返回接口产生的全部记录。"""
        self.set_referer()
        await self.run_single()
        if first:
            return self.response[0] if self.response else {}
        return self.response

    async def run_single(
        self,
        *args,
        **kwargs,
    ):
        
        await super().run_single(
            "",
            params=lambda: self.static_params,
            data=self.__generate_data,
            method="POST",
        )

    def check_response(
        self,
        data_dict: dict,
        *args,
        **kwargs,
    ):
        
        if d := data_dict.get("data"):
            self.append_response(d)
        else:
            self.log.warning(_("获取{text}失败").format(text=self.text))

    def __generate_data(
        self,
    ) -> dict:
        """把 sec_user_id 列表编码为接口要求的 JSON 数组字符串。"""
        if isinstance(self.sec_user_id, str):
            self.sec_user_id = [self.sec_user_id]
        value = "[" + ",".join(f'"{item}"' for item in self.sec_user_id) + "]"
        return {
            "sec_user_ids": value,
        }

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
