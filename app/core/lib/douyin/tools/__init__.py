import asyncio
from random import randint

# --- Colors (Rich Console Styles) ---
MASTER = "b #fff200"
PROMPT = "b turquoise2"
GENERAL = "b bright_white"
PROGRESS = "b bright_magenta"
ERROR = "b bright_red"
WARNING = "b bright_yellow"
INFO = "b bright_green"
DEBUG = "b dark_orange"
# --- Network Constants ---
RETRY = 5
TIMEOUT = 10
MAX_WORKERS = 4
COOKIE_UPDATE_INTERVAL = 15 * 60
# --- Headers & UserAgent ---
USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
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
# --- Indices (用于提取数据的索引) ---
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
# --- Assets ---
BLANK_PREVIEW = "static/images/blank.png"
# --- Functions ---
async def wait() -> None:
    await asyncio.sleep(randint(5, 20) * 0.1)

try:
    from .cleaner import Cleaner
except ImportError:
    Cleaner = None

try:
    from .console import ColorfulConsole
except ImportError:
    ColorfulConsole = None

try:
    from .error import CacheError, DownloaderError
except ImportError:
    CacheError = None
    DownloaderError = None

try:
    from .file_folder import file_switch, remove_empty_directories
except ImportError:
    file_switch = None
    remove_empty_directories = None

try:
    from .format import (
        cookie_dict_to_str,
        cookie_str_to_dict,
        cookie_jar_to_dict,
        cookie_str_to_str,
        format_size,
    )
except ImportError:
    pass

try:
    from .retry import Retry
except ImportError:
    Retry = None

try:
    from .temporary import random_string, timestamp
except ImportError:
    pass

try:
    from .timer import run_time
except ImportError:
    pass

try:
    from .truncate import beautify_string, trim_string, truncate_string
except ImportError:
    pass

try:
    from .capture import capture_error_params, capture_error_request
except ImportError:
    pass

try:
    from .browser import Browser
except ImportError:
    pass
try:
    from .choose import choose
except ImportError:
    pass

try:
    from .list_pop import safe_pop
except ImportError:
    pass

try:
    from .session import request_params, create_client
except ImportError:
    pass

try:
    from .rename_compatible import RenameCompatible
except ImportError:
    pass

try:
    from .progress import FakeProgress
except ImportError:
    pass