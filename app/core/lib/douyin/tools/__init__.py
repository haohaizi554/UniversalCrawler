"""汇总抖音抓取流程共用的网络常量、数据索引与工具函数。"""

import asyncio
from random import randint

from app.config import DEFAULT_USER_AGENT, cfg
from app.utils.user_agents import resolve_user_agent

# Rich 控制台样式
MASTER = "b #fff200"
PROMPT = "b turquoise2"
GENERAL = "b bright_white"
PROGRESS = "b bright_magenta"
ERROR = "b bright_red"
WARNING = "b bright_yellow"
INFO = "b bright_green"
DEBUG = "b dark_orange"

# 网络参数
RETRY = 5
TIMEOUT = 10
MAX_WORKERS = 4
COOKIE_UPDATE_INTERVAL = 15 * 60

# 请求头与 UA
USERAGENT = resolve_user_agent(
    "douyin",
    None,
    configured_user_agent=cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT),
    default_user_agent=DEFAULT_USER_AGENT,
)
REFERER = "https://www.douyin.com/?recommend=1"
REFERER_TIKTOK = "https://www.tiktok.com/explore"

PARAMS_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "*/*",
    "Content-Type": "text/plain;charset=UTF-8",
    "Referer": REFERER,
    "User-Agent": USERAGENT,
}
PARAMS_HEADERS_TIKTOK = PARAMS_HEADERS | {
    "Referer": REFERER_TIKTOK,
}
DATA_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "*/*",
    "Referer": REFERER,
    "User-Agent": USERAGENT,
}
DATA_HEADERS_TIKTOK = DATA_HEADERS | {
    "Referer": REFERER_TIKTOK,
}
DOWNLOAD_HEADERS = {
    "Accept": "*/*",
    "Range": "bytes=0-",
    "Referer": REFERER,
    "User-Agent": USERAGENT,
}
DOWNLOAD_HEADERS_TIKTOK = DOWNLOAD_HEADERS | {
    "Referer": REFERER_TIKTOK,
}
QRCODE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "*/*",
    "Referer": REFERER,
    "User-Agent": USERAGENT,
}
BLANK_HEADERS = {
    "User-Agent": USERAGENT,
}

# 数据提取索引
VIDEO_INDEX: int = -1
VIDEO_TIKTOK_INDEX: int = 0
IMAGE_INDEX: int = -1
IMAGE_TIKTOK_INDEX: int = -1
VIDEOS_INDEX: int = -1
DYNAMIC_COVER_INDEX: int = -1
STATIC_COVER_INDEX: int = -1
MUSIC_INDEX: int = -1
COMMENT_IMAGE_INDEX: int = -1
COMMENT_STICKER_INDEX: int = -1
LIVE_COVER_INDEX: int = -1
AUTHOR_COVER_INDEX: int = -1
HOT_WORD_COVER_INDEX: int = -1
COMMENT_IMAGE_LIST_INDEX: int = 0
BITRATE_INFO_TIKTOK_INDEX: int = 0
LIVE_DATA_INDEX: int = 0
AVATAR_LARGER_INDEX: int = 0
AUTHOR_COVER_URL_INDEX: int = 0
SEARCH_USER_INDEX: int = 0
SEARCH_AVATAR_INDEX: int = 0
MUSIC_COLLECTION_COVER_INDEX: int = 0
MUSIC_COLLECTION_DOWNLOAD_INDEX: int = 0

# 静态资源
BLANK_PREVIEW = "static/images/blank.png"

# 通用函数
async def wait() -> None:
    """随机短暂停顿，避免短链请求形成固定时间间隔。"""
    await asyncio.sleep(randint(5, 20) * 0.1)

from .cleaner import Cleaner
from .console import ColorfulConsole
from .error import CacheError, DownloaderError
from .file_folder import file_switch, remove_empty_directories
from .format import (
    cookie_dict_to_str,
    cookie_str_to_dict,
    cookie_jar_to_dict,
    cookie_str_to_str,
    format_size,
)
from .retry import Retry
from .temporary import random_string, timestamp
from .timer import run_time
from .truncate import beautify_string, trim_string, truncate_string
from .capture import capture_error_params, capture_error_request
from .session import request_params, create_client
