# app/core/lib/douyin/interface/hashtag.py
from typing import TYPE_CHECKING
from typing import Union

from .template import API

# from ..translation import _

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any


class HashTag(API):
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