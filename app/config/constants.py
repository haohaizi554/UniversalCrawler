from __future__ import annotations

from app.utils.runtime_paths import default_download_root, resolve_user_file

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

# Keep the import-time default in the same canonical form used by settings validation.
DEFAULT_DOWNLOAD_DIR = str(default_download_root().resolve(strict=False))
DEFAULT_CONFIG_FILE = str(resolve_user_file("config.json"))
DEFAULT_MISSAV_PROXY_URL = "http://127.0.0.1:7890"
SUPPORTED_THEMES = {"dark", "light"}
