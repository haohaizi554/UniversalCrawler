"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/comment_tiktok.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/comment_tiktok.py
from typing import TYPE_CHECKING
from typing import Union
from .comment import Comment, Reply
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


class CommentTikTok(Comment, APITikTok):
    """封装 `CommentTikTok` 在 `app/core/lib/douyin/interface/comment_tiktok.py` 中承担的核心逻辑。"""
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
        """初始化当前实例并准备运行所需的状态，供 `CommentTikTok` 使用。"""
        super().__init__(
            params, cookie, proxy, detail_id, pages, cursor, count, count_reply
        )
        self.api = f"{self.domain}api/comment/list/"
        self.text = _("作品评论")

    def generate_params(
        self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `CommentTikTok` 使用。"""
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
    """封装 `ReplyTikTok` 在 `app/core/lib/douyin/interface/comment_tiktok.py` 中承担的核心逻辑。"""
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
        """初始化当前实例并准备运行所需的状态，供 `ReplyTikTok` 使用。"""
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
        """执行 `generate_params` 对应的业务逻辑，供 `ReplyTikTok` 使用。"""
        return self.params | {
            "comment_id": self.comment_id,
            "count": self.count,
            "cursor": self.cursor,
            "fromWeb": "1",
            "from_page": "video",
            "item_id": self.item_id,
        }


async def test():
    """执行 `test` 对应的业务逻辑。"""
    pass

if __name__ == "__main__":
    from asyncio import run
    run(test())