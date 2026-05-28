from __future__ import annotations

import os

from app.utils.runtime_paths import default_download_root, resolve_user_file

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

DEFAULT_DOWNLOAD_DIR = str(default_download_root())
DEFAULT_CONFIG_FILE = str(resolve_user_file("config.json"))
DEFAULT_MISSAV_PROXY_URL = "http://127.0.0.1:7890"
SUPPORTED_THEMES = {"dark", "light"}
