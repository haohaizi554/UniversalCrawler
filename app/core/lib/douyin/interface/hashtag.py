"""保留抖音话题抓取接口的兼容占位。"""

from typing import TYPE_CHECKING
from typing import Union

from .template import API

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

class HashTag(API):
    """话题抓取占位类，当前 run 不发起请求。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        *args,
        **kwargs,
    ):
        super().__init__(params, cookie, proxy, *args, **kwargs)

    async def run(self, *args, **kwargs):
        pass

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
