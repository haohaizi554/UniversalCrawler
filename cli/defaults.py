"""CLI 默认配置与校验工具。

与 GUI read_*_run_options 对齐：从 cfg 持久化配置读取平台默认值。
CLI/SDK/REST API 三层共用，确保默认值来源一致。

本模块不依赖 PyQt6 控件，仅依赖 cfg（ConfigManager），
因此可在无 GUI 环境下安全使用。
"""

from __future__ import annotations

from app.config import get_platform_default_values, get_platform_runtime_defaults

# 兜底配置：当 cfg 不可用时使用（与 GUI AppSettings 默认值对齐）
_SUPPORTED_PLATFORMS = ("douyin", "xiaohongshu", "bilibili", "kuaishou", "missav")
_FALLBACK_CONFIG = {platform: get_platform_default_values(platform) for platform in _SUPPORTED_PLATFORMS}

# 向后兼容别名
DEFAULT_CONFIG = _FALLBACK_CONFIG

def get_platform_defaults(source: str) -> dict:
    """获取平台默认配置（与 GUI read_*_run_options 对齐）。

    优先从配置中心读取持久化配置；若配置系统不可用，则回退到
    `app.config.settings` 中声明的默认配置快照，避免 CLI 层维护重复常量。

    Args:
        source: 平台 ID (douyin/xiaohongshu/bilibili/kuaishou/missav)

    Returns:
        dict: 平台默认配置（新 dict，可安全修改）
    """
    if source not in _FALLBACK_CONFIG:
        return {}
    return dict(get_platform_runtime_defaults(source))

def get_default_save_dir() -> str:
    """获取默认保存目录（与 GUI MainWindow.current_save_dir 对齐）。

    优先从 cfg 读取，兜底使用 DEFAULT_DOWNLOAD_DIR。
    """
    try:
        from app.config import cfg
        save_dir = cfg.get("common", "save_directory", "")
        if save_dir:
            return save_dir
    except Exception:
        pass

    try:
        from app.config.constants import DEFAULT_DOWNLOAD_DIR
        return DEFAULT_DOWNLOAD_DIR
    except Exception:
        return "downloads"

def validate_config_types(user_config: dict) -> str | None:
    """校验 config 中已知参数的类型（与 CLI argparse type 和 SDK _validate_config 对齐）。

    仅校验已知参数，未知参数透传给 spider（保持前向兼容）。
    与 REST API _validate_config_types 逻辑完全一致。

    Args:
        user_config: 用户传入的 config 字典

    Returns:
        str | None: 错误信息（None 表示校验通过）
    """
    if not isinstance(user_config, dict):
        return "config 必须是 JSON 对象"

    type_rules = {
        "max_items": int,
        "max_pages": int,
        # 与 CLI download --timeout (float) 和 SDK download_video(timeout=float) 对齐：
        # timeout 既可以是 int 也可以是 float，统一用 (int, float) 接受
        "timeout": (int, float),
        "request_interval": (int, float),
        "detail_request_interval": (int, float),
        "individual_only": bool,
        "priority": str,
        "proxy": str,
        "cookies": dict,
        "cookie": str,
        "download_strategy": str,
        "referer": str,
        "ua": str,
        "folder_name": str,
        "use_subdir": bool,
        # 与 GUI spider build_download_meta 和 DownloadWorker 对齐的平台特定字段
        "audio_url": str,
        "aweme_id": str,
        "bvid": str,
        "cid": str,
        "file_name": str,
        "preferred_filename": str,
        "is_gallery": bool,
        "is_mix": bool,
        # 与 GUI spider 和下载器对齐的额外字段
        "content_type": str,   # 内容类型 video/image/gallery（DownloadWorker._infer_extension 和 _resolve_save_dir 读取）
        "images_data": list,   # 抖音图集数据（DouyinDownloader._download_gallery 读取）
        "size_mb": (int, float),  # 文件大小 MB（BaseDownloader 分块下载策略）
        "media_label": str,    # 媒体类型标签（GUI spider build_download_meta 设置）
        "duration": (int, float),  # 视频时长秒数（ChunkedDownloader/FFmpegDownloader 读取，与 GUI spider DouyinParser 对齐）
        "mix_title": str,      # 合集标题（与 GUI spider DouyinSpider._process_mix 对齐）
        "create_time": int,    # 创建时间戳（与 GUI spider DouyinParser 对齐）
        "author": str,         # 作者名（与 GUI spider DouyinParser 对齐，用作 folder_name）
        "has_live_photo": bool,  # 是否包含实况照片（与 GUI spider DouyinParser 对齐）
    }

    # 中文类型名称映射（与 REST API _validate_config_types 和测试对齐）
    _TYPE_NAMES = {int: "整数", bool: "布尔值", str: "字符串", dict: "字典", list: "列表", float: "数字"}

    for key, expected in type_rules.items():
        val = user_config.get(key)
        if val is not None and not isinstance(val, expected):
            # 元组类型（如 (int, float)）由 isinstance 直接支持，无需特殊处理
            # bool 是 int 的子类，需要排除
            if expected is int and isinstance(val, bool):
                return f"config.{key} 必须是整数，收到 bool"
            if expected is bool and isinstance(val, int) and not isinstance(val, bool):
                return f"config.{key} 必须是布尔值，收到 int"
            if not (expected is int and isinstance(val, int) and not isinstance(val, bool)):
                # 元组类型取第一个类型的名称
                if isinstance(expected, tuple):
                    type_name = "或".join(_TYPE_NAMES.get(t, t.__name__) for t in expected)
                else:
                    type_name = _TYPE_NAMES.get(expected, expected.__name__)
                return f"config.{key} 必须是{type_name}，收到 {type(val).__name__}"

    return None

def build_missav_proxy_url(proxy_str: str) -> str:
    """构建 MissAV 代理 URL（与 GUI build_missav_proxy_url 完全一致）。

    委托给纯 core 辅助函数，避免 CLI 为了一个字符串归一化引入 Qt UI 依赖。
    """
    from app.core.plugins.run_options import build_missav_proxy_url as _build
    return _build(proxy_str)

def infer_content_type(local_path: str) -> str:
    """根据文件扩展名推断 content_type（与 GUI spider 设置对齐）。

    直接下载（download_video）不经过 spider，content_type 由文件扩展名推断：
    - 视频文件 → "video"
    - 图片文件 → "image"
    - 无法推断 → 空字符串

    Args:
        local_path: 本地文件路径

    Returns:
        str: content_type ("video" / "image" / "")
    """
    if not local_path:
        return ""

    video_exts = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    ext = ""
    if "." in local_path:
        ext = local_path.rsplit(".", 1)[-1].lower()
        ext = f".{ext}"

    if ext in video_exts:
        return "video"
    if ext in image_exts:
        return "image"
    return ""

def infer_content_type_from_url(url: str) -> str:
    """根据 URL 推断 content_type（与 GUI spider 下载前设置对齐）。

    SDK download_video 不经过 spider，需要在下载前从 URL 推断 content_type，
    以便 DownloadWorker._infer_extension 能正确推断文件扩展名。
    - URL 含视频扩展名 → "video"
    - URL 含图片扩展名 → "image"
    - URL 含 m3u8 → "video"
    - 无法推断 → 空字符串（下载后再由 infer_content_type 从文件签名推断）

    Args:
        url: 视频/图片 URL

    Returns:
        str: content_type ("video" / "image" / "")
    """
    if not url:
        return ""

    url_lower = url.lower().split("?")[0]  # 去掉查询参数

    video_exts = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

    for ext in video_exts:
        if ext in url_lower:
            return "video"
    for ext in image_exts:
        if ext in url_lower:
            return "image"
    return ""

# 平台 → auth 文件名映射（与 app/config/settings.py AuthSettings 对齐）
_AUTH_FILE_MAP = {
    "douyin":   "dy_auth.json",
    "xiaohongshu": "xhs_auth.json",
    "bilibili": "bili_auth.json",
    "kuaishou": "ks_auth.json",
    "missav":   None,  # MissAV 不需要 cookie
}

def _try_load_cookie(source: str) -> str | None:
    """尝试加载本地 cookie 文件并构建 cookie 字符串（与 GUI spider 对齐）。

    GUI spider 启动时会通过 AuthService 自动加载本地 cookie 文件，
    SDK download_video 不经过 spider，需要手动加载以确保需要登录的平台能正常下载。

    Args:
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    Returns:
        str | None: cookie 字符串，如果无可用 cookie 则返回 None
    """
    import json
    from pathlib import Path

    auth_name = _AUTH_FILE_MAP.get(source)
    if auth_name is None:
        return None

    # 查找 cookie 文件（与 interactive 命令 _find_cookie_file 对齐）
    candidates = [
        Path(auth_name),                    # 当前工作目录
        Path.home() / ".ucrawl" / auth_name,  # 用户目录
        Path(__file__).resolve().parent.parent / auth_name,  # 项目根目录
    ]
    # 运行时路径会区分源码运行、安装包和显式环境变量覆盖。
    try:
        from app.utils.runtime_paths import user_data_root
        candidates.append(user_data_root() / auth_name)
    except Exception:
        pass

    cookie_path = None
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            cookie_path = p
            break

    if cookie_path is None:
        return None

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, (dict, list)) or not data:
            return None
    except (json.JSONDecodeError, OSError):
        return None

    # 构建 cookie 字符串（与 GUI AuthService.build_cookie_string 对齐）
    try:
        from app.services.auth_service import AuthService
        return AuthService.build_cookie_string(data)
    except Exception:
        # AuthService 不可用时，手动构建简单 cookie 字符串
        if isinstance(data, dict):
            return "; ".join(f"{k}={v}" for k, v in data.items() if v is not None)
        return None

def _try_load_cookies_dict(source: str) -> dict | None:
    """尝试加载本地 cookie 文件并构建 cookie dict（与 GUI BilibiliSpider 对齐）。

    BilibiliSpider 通过 self.api.sess.cookies 获取 cookie dict，
    SDK download_video 不经过 spider，需要手动加载以确保 BilibiliDownloader
    能使用 cookies dict 刷新 CDN URL。

    Args:
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    Returns:
        dict | None: cookie name→value 字典，如果无可用 cookie 则返回 None
    """
    import json
    from pathlib import Path

    auth_name = _AUTH_FILE_MAP.get(source)
    if auth_name is None:
        return None

    # 查找 cookie 文件（与 _try_load_cookie 对齐）
    candidates = [
        Path(auth_name),
        Path.home() / ".ucrawl" / auth_name,
        Path(__file__).resolve().parent.parent / auth_name,
    ]
    # 与字符串 Cookie 加载使用同一套用户数据目录解析规则。
    try:
        from app.utils.runtime_paths import user_data_root
        candidates.append(user_data_root() / auth_name)
    except Exception:
        pass

    cookie_path = None
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            cookie_path = p
            break

    if cookie_path is None:
        return None

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            # auth JSON 直接是 cookie name→value dict
            return {k: v for k, v in data.items() if v is not None}
        if isinstance(data, list) and data:
            # auth JSON 是 cookie 列表（每个元素含 name/value 字段）
            result = {}
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("Name")
                    value = item.get("value") or item.get("Value")
                    if name and value is not None:
                        result[name] = value
            return result if result else None
    except (json.JSONDecodeError, OSError):
        pass

    return None

def merge_convenience_params(body: dict, config: dict, source: str = "") -> dict:
    """将 REST API/WebSocket 请求体中的便捷参数合并到 config 字典。

    与 CLI search/download 命令的便捷参数对齐：
    CLI 有 --cookie/--download-strategy/--referer/--ua 等便捷参数，
    REST API/WebSocket 也应支持这些参数作为顶层字段，避免用户手写 JSON config。

    合并优先级（与 CLI 对齐）：
    1. 平台默认值 (get_platform_defaults)
    2. config 字典中的值
    3. 便捷参数（优先级最高，与 CLI 独立参数语义一致）

    合并后会对便捷参数进行类型校验（与 CLI argparse type 和 _validate_config_types 对齐），
    防止 REST API/WebSocket 便捷参数绕过类型校验。

    Args:
        body: REST API/WebSocket 请求体
        config: 已合并平台默认值的 config 字典（会被就地修改）
        source: 平台 ID（用于校验平台特定参数）

    Returns:
        dict: 合并后的 config 字典
    """
    # 与 CLI search --max-items/--max-pages/--timeout 对齐
    if body.get("max_items") is not None:
        config["max_items"] = body["max_items"]
    if body.get("max_pages") is not None:
        config["max_pages"] = body["max_pages"]
    if body.get("timeout") is not None and isinstance(body["timeout"], int):
        # 注意：REST API 顶层 timeout 是整体超时（run_timeout），
        # 这里的 timeout 是 spider HTTP 超时（与 CLI --timeout 对齐）
        # 仅在明确为 int 类型时才视为 spider HTTP 超时（float 视为 run_timeout）
        config["timeout"] = body["timeout"]

    # 与 CLI search --individual-only/--priority/--proxy 对齐（MissAV 专属）
    if body.get("individual_only") is not None:
        config["individual_only"] = body["individual_only"]
    if body.get("priority") is not None:
        config["priority"] = body["priority"]
    if body.get("proxy") is not None:
        config["proxy"] = body["proxy"]
        # MissAV 代理转换（与 CLI _build_config 对齐）
        if source == "missav" and config["proxy"] is not None:
            config["proxy"] = build_missav_proxy_url(config["proxy"])

    # 与 CLI search/download --cookie/--download-strategy/--referer/--ua 对齐
    if body.get("cookie") is not None:
        config["cookie"] = body["cookie"]
    if body.get("download_strategy") is not None:
        config["download_strategy"] = body["download_strategy"]
    if body.get("referer") is not None:
        config["referer"] = body["referer"]
    if body.get("ua") is not None:
        config["ua"] = body["ua"]

    # 与 CLI search/download --folder-name/--use-subdir 对齐
    if body.get("folder_name") is not None:
        config["folder_name"] = body["folder_name"]
    if body.get("use_subdir") is not None:
        config["use_subdir"] = body["use_subdir"]
    # 与 GUI BilibiliSpider 对齐：传入 folder_name 时自动启用 use_subdir
    # GUI BilibiliSpider 设置 "use_subdir": bool(folder_name)，
    # 即有 folder_name 就自动使用子目录。REST API/WebSocket 用户只传 folder_name 不传 use_subdir 时，
    # 应与 GUI 行为一致，自动启用子目录
    if config.get("folder_name") and not config.get("use_subdir"):
        config["use_subdir"] = True
    # 与 GUI DouyinParser 对齐：传入 author 但未传 folder_name 时，自动将 author 设为 folder_name
    # GUI DouyinParser 在解析视频时设置 "folder_name": author（parser.py:68/85），
    # REST API/WebSocket download 不经过 spider，需要手动设置以确保与 GUI 行为一致
    if config.get("author") and not config.get("folder_name"):
        config["folder_name"] = config["author"]
        # 与 GUI BilibiliSpider 对齐：folder_name 存在时自动启用 use_subdir
        if not config.get("use_subdir"):
            config["use_subdir"] = True

    # 与 CLI search/download --file-name 对齐
    if body.get("file_name") is not None:
        config["file_name"] = body["file_name"]

    # 与 CLI search/download --content-type 对齐
    if body.get("content_type") is not None:
        config["content_type"] = body["content_type"]

    # 与 CLI argparse type 和 _validate_config_types 对齐：
    # 合并后校验便捷参数类型，防止 REST API/WebSocket 便捷参数绕过类型校验。
    # CLI 通过 argparse 自动校验参数类型（如 type=int, action="store_true"），
    # REST API/WebSocket 的 _validate_config_types 只校验 config 字典，
    # 便捷参数在 _validate_config_types 之后通过本函数合并，需要额外校验。
    _conv_err = _validate_convenience_param_types(body)
    if _conv_err:
        raise ValueError(_conv_err)

    return config

def _validate_convenience_param_types(body: dict) -> str | None:
    """校验 REST API/WebSocket 请求体中便捷参数的类型。

    与 CLI argparse type 和 validate_config_types 对齐：
    CLI 通过 argparse 自动校验参数类型，REST API/WebSocket 需要显式校验，
    防止便捷参数绕过 _validate_config_types 的类型校验。

    Args:
        body: REST API/WebSocket 请求体

    Returns:
        str | None: 错误信息（None 表示校验通过）
    """
    # 便捷参数类型规则（与 validate_config_types 的 type_rules 对齐）
    _CONV_TYPE_RULES = {
        "max_items": int,
        "max_pages": int,
        "individual_only": bool,
        "priority": str,
        "proxy": str,
        "cookie": str,
        "download_strategy": str,
        "referer": str,
        "ua": str,
        "folder_name": str,
        "use_subdir": bool,
        "file_name": str,
        "content_type": str,
    }
    # 中文类型名称映射（与 validate_config_types 对齐）
    _TYPE_NAMES = {int: "整数", bool: "布尔值", str: "字符串"}

    for key, expected in _CONV_TYPE_RULES.items():
        val = body.get(key)
        if val is None:
            continue
        # bool 是 int 的子类，需要排除
        if expected is int and isinstance(val, bool):
            return f"{key} 必须是整数，收到 bool"
        if expected is bool and isinstance(val, int) and not isinstance(val, bool):
            return f"{key} 必须是布尔值，收到 int"
        if not isinstance(val, expected):
            type_name = _TYPE_NAMES.get(expected, expected.__name__)
            return f"{key} 必须是{type_name}，收到 {type(val).__name__}"

    return None

def get_platform_download_defaults(source: str) -> dict:
    """获取平台下载默认 meta 字段（与 GUI spider build_download_meta 对齐）。

    GUI spider 在 emit_video 时通过 build_download_meta 设置平台特定的
    ua、referer 等字段。SDK download_video 不经过 spider，需要手动设置
    这些默认值，确保下载器能正确构建 HTTP 请求头。

    Args:
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    Returns:
        dict: 平台下载默认 meta 字段（新 dict，可安全修改）
    """
    try:
        from app.config import DEFAULT_USER_AGENT, cfg
    except ImportError:
        DEFAULT_USER_AGENT = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        )
        cfg = None

    # 与各 spider 的 HEADERS 和 build_download_meta 对齐：
    # - DouyinDownloader 默认 ua=cfg.get("douyin","user_agent",DEFAULT_USER_AGENT), referer="https://www.douyin.com/"
    # - BilibiliDownloader 默认 ua=cfg.get("bilibili","user_agent",DEFAULT_USER_AGENT), referer="https://www.bilibili.com"
    # - KuaishouDownloader 默认 ua=cfg.get("kuaishou","user_agent",DEFAULT_USER_AGENT), referer="https://www.kuaishou.com/"
    # - MissAVDownloader 默认 referer="https://missav.ai/"
    #
    # cookie 字段：GUI spider 在搜索阶段通过 AuthService 自动加载本地 cookie，
    # SDK download_video 不经过 spider，需要从本地 cookie 文件加载（与 GUI 对齐）。
    # 如果本地无 cookie 文件则不设置（spider 会自动弹出登录窗口，SDK 无法弹出窗口）。
    _PLATFORM_DEFAULTS = {
        "douyin": {
            "ua": cfg.get("douyin", "user_agent", DEFAULT_USER_AGENT) if cfg else DEFAULT_USER_AGENT,
            "referer": "https://www.douyin.com/",
        },
        "xiaohongshu": {
            "ua": cfg.get("xiaohongshu", "user_agent", DEFAULT_USER_AGENT) if cfg else DEFAULT_USER_AGENT,
            "referer": "https://www.xiaohongshu.com/",
        },
        "bilibili": {
            "ua": cfg.get("bilibili", "user_agent", DEFAULT_USER_AGENT) if cfg else DEFAULT_USER_AGENT,
            "referer": "https://www.bilibili.com",
        },
        "kuaishou": {
            "ua": cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT) if cfg else DEFAULT_USER_AGENT,
            "referer": "https://www.kuaishou.com/",
        },
        "missav": {
            "referer": "https://missav.ai/",
        },
    }

    result = dict(_PLATFORM_DEFAULTS.get(source, {}))

    # 与 GUI spider 对齐：自动加载本地 cookie（与 interactive 命令 _load_cookie 对齐）
    # GUI spider 启动时会自动加载本地 cookie 文件，SDK download_video 也应如此，
    # 确保需要登录的平台（douyin/bilibili/kuaishou）能正常下载。
    # 仅在用户未通过 config 显式传入 cookie 时才自动加载（用户 config 优先级最高）。
    _cookie = _try_load_cookie(source)
    if _cookie:
        result["cookie"] = _cookie

    # 与 GUI BilibiliSpider 对齐：bilibili 平台额外加载 cookies dict
    # BilibiliSpider 通过 self.api.sess.cookies 获取 cookie dict，
    # BilibiliDownloader 优先读取 cookies dict 用于刷新 CDN URL。
    # SDK download_video 不经过 spider，需要手动加载以确保 CDN 刷新可用。
    if source == "bilibili":
        _cookies_dict = _try_load_cookies_dict(source)
        if _cookies_dict:
            result["cookies"] = _cookies_dict

    return result
