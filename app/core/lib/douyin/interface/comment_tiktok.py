"""分页获取 TikTok 作品评论及评论回复。"""

from typing import TYPE_CHECKING
from typing import Union
from .comment import Comment, Reply
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

class CommentTikTok(Comment, APITikTok):
    """使用 TikTok 字段与接口抓取作品一级评论。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        detail_id: str = ...,
        pages: int = None,
        cursor=0,
        count=20,
        count_reply=3,
    ):
        super().__init__(
            params, cookie, proxy, detail_id, pages, cursor, count, count_reply
        )
        self.api = f"{self.domain}api/comment/list/"
        self.text = _("作品评论")

    def generate_params(
        self,
    ) -> dict:
        
        return self.params | {
            "aweme_id": self.item_id,
            "count": self.count,
            "cursor": self.cursor,
            "enter_from": "tiktok_web",
            "is_non_personalized": "false",
            "fromWeb": "1",
            "from_page": "video",
        }

class ReplyTikTok(Reply, CommentTikTok, APITikTok):
    """使用 TikTok 回复接口抓取指定评论的回复。"""
    
    def __init__(
        self,
        params: Union["Parameter", "Params"],
        cookie: str = "",
        proxy: str = None,
        detail_id: str = "",
        comment_id: str = "",
        pages: int = None,
        cursor=0,
        count=3,
        progress=None,
        task_id=None,
    ):
        super().__init__(
            params,
            cookie,
            proxy,
            detail_id,
            comment_id,
            pages,
            cursor,
            count,
            progress,
            task_id,
        )
        self.api = f"{self.domain}api/comment/list/reply/"

    def generate_params(
        self,
    ) -> dict:
        
        return self.params | {
            "comment_id": self.comment_id,
            "count": self.count,
            "cursor": self.cursor,
            "fromWeb": "1",
            "from_page": "video",
            "item_id": self.item_id,
        }

async def test():
    
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())
