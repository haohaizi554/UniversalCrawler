# app/core/lib/douyin/interface/slides.py
# from typing import Callable
from typing import TYPE_CHECKING
from typing import Union

from .template import API

try:
    from ..translation import _
except ImportError:
    def _(x): return x

if TYPE_CHECKING:
    from typing import Any
    Parameter = Any
    Params = Any

__all__ = ["Slides"]


class Slides(API):
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        slides_id: str | list | tuple = ...,
    ):
        super().__init__(params, cookie, proxy)
        self.slides_id = slides_id
        self.api = f"{self.short_domain}web/api/v2/aweme/slidesinfo/"
        self.text = _("作品")

    async def run(self, *args, **kwargs):
        pass


async def test():
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())