"""配置常量模块，集中定义默认 User-Agent、配置文件路径、下载目录、代理地址和主题选项。"""

from __future__ import annotations

from app.utils.runtime_paths import default_download_root, resolve_user_file

#默认浏览器请求头里的 User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

DEFAULT_DOWNLOAD_DIR = str(default_download_root()) #默认下载目录
DEFAULT_CONFIG_FILE = str(resolve_user_file("config.json")) #配置文件
DEFAULT_MISSAV_PROXY_URL = "http://127.0.0.1:7890"  #平台默认代理
SUPPORTED_THEMES = {"dark", "light"}    #
