# app/core/lib/douyin/interface/__init__.py
from .account import Account
from .account_tiktok import AccountTikTok
from .collection import Collection
from .collects import (
    Collects,
    CollectsDetail,
    CollectsMix,
    CollectsMusic,
    CollectsSeries,
)
from .comment import Comment, Reply
from .comment_tiktok import CommentTikTok, ReplyTikTok
from .detail import Detail
from .detail_tiktok import DetailTikTok
from .hashtag import HashTag
from .hot import Hot
from .info import Info
from .info_tiktok import InfoTikTok
from .live import Live
from .live_tiktok import LiveTikTok
from .mix import Mix
from .mix_tiktok import MixListTikTok
from .mix_tiktok import MixTikTok
from .search import Search
from .template import API
from .template import APITikTok
from .user import User