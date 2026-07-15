"""跨入口运行默认值、配置合并、校验与下载元数据工具。

CLI、SDK 和 Web 通过本模块读取配置中心中的持久化平台值，并在配置系统不可用
时采用代码兜底。模块不依赖 PyQt6 控件，可在无图形环境中使用。
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from shared.resilient_dns import install_resilient_dns

# 公网策略和实际传输必须看到同一批解析结果。这里统一安装后，GUI、Web、CLI、SDK
# 以及 requests/httpx 都能在系统 DNS 临时失效时复用经 TLS 校验的 DoH 回退地址。
install_resilient_dns()

# 配置中心不可用时使用的最小平台兜底。
_SUPPORTED_PLATFORMS = ("douyin", "xiaohongshu", "bilibili", "kuaishou", "missav")
_FALLBACK_CONFIG: dict[str, dict[str, Any]] = {
    "douyin": {
        "max_items": 20,
        "timeout": 10,
    },
    "xiaohongshu": {
        "max_items": 20,
        "search_max_pages": 5,
        "timeout": 30,
        "request_interval": 1.5,
        "detail_request_interval": 0.5,
        "sort": "general",
        "note_type": 0,
    },
    "bilibili": {
        "max_pages": 1,
        "max_items": 30,
        "timeout": 10,
        "api_workers": 8,
    },
    "kuaishou": {
        "max_items": 20,
        "timeout": 10,
    },
    "missav": {
        "individual_only": False,
        "priority": "中文字幕优先",
        "proxy": "http://127.0.0.1:7890",
    },
}

# 公开 SDK 兼容导出。必须保持直接别名而非复制，使 DEFAULT_CONFIG 与
# _FALLBACK_CONFIG 始终是同一对象，兼容依赖对象身份或原地修改的调用方。
DEFAULT_CONFIG = _FALLBACK_CONFIG

_TYPE_NAMES: dict[type[Any], str] = {
    int: "整数",
    bool: "布尔值",
    str: "字符串",
    dict: "字典",
    list: "列表",
    float: "数字",
}

_CONFIG_TYPE_RULES: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "max_items": int,
    "max_pages": int,
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
    "audio_url": str,
    "aweme_id": str,
    "bvid": str,
    "cid": str,
    "file_name": str,
    "preferred_filename": str,
    "is_gallery": bool,
    "is_mix": bool,
    "content_type": str,
    "images_data": list,
    "size_mb": (int, float),
    "media_label": str,
    "duration": (int, float),
    "mix_title": str,
    "create_time": int,
    "author": str,
    "has_live_photo": bool,
}

_CONVENIENCE_PARAM_TYPE_RULES = {
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


class DomainPolicyViolation(ValueError):
    """网络目标越过公共地址边界时抛出。"""


class DomainPolicyEngine:
    """在客户端访问前校验初始 URL 及每一次重定向。

    本引擎刻意与传输实现解耦。``validate_redirect_response`` 匹配 Requests
    响应钩子协议，因此 requests 可保留正常的 Cookie/认证重定向处理，同时
    由本策略逐跳检查下一个地址。
    """

    REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

    def __init__(self, *, resolver: Callable[..., list] | None = None) -> None:
        self._resolver = resolver

    @staticmethod
    def _is_unsafe_address(value: str) -> bool:
        address = ipaddress.ip_address(value)
        return bool(
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    def require_public_url(self, url: str) -> str:
        if not isinstance(url, str):
            raise DomainPolicyViolation("url 必须是字符串")
        normalized_url = url.strip()
        if not normalized_url:
            raise DomainPolicyViolation("url 不能为空")
        parts = urlsplit(normalized_url)
        if parts.scheme.lower() not in {"http", "https"}:
            raise DomainPolicyViolation("url 仅支持 http/https")
        if parts.username is not None or parts.password is not None:
            raise DomainPolicyViolation("url 不允许包含用户名或密码")
        host = (parts.hostname or "").strip().lower()
        if not host:
            raise DomainPolicyViolation("url 缺少主机名")
        try:
            port = parts.port
        except ValueError as exc:
            raise DomainPolicyViolation("url 端口无效") from exc

        try:
            host_address = ipaddress.ip_address(host)
        except ValueError:
            host_address = None
        if host_address is not None:
            if self._is_unsafe_address(host):
                raise DomainPolicyViolation("禁止访问本地或内网地址")
            return normalized_url

        resolver = self._resolver or socket.getaddrinfo
        try:
            addr_infos = resolver(host, port or None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise DomainPolicyViolation("url 主机名无法解析") from exc
        if not addr_infos:
            raise DomainPolicyViolation("url 主机名无法解析")
        for addr_info in addr_infos:
            resolved_host = str(addr_info[4][0])
            try:
                unsafe = self._is_unsafe_address(resolved_host)
            except ValueError as exc:
                raise DomainPolicyViolation("url 主机名解析结果无效") from exc
            if unsafe:
                raise DomainPolicyViolation("禁止访问本地或内网地址")
        return normalized_url

    def resolve_public_addresses(self, url: str) -> tuple[str, ...]:
        """返回刚完成校验的地址集合，供传输层固定 DNS 解析结果。"""
        normalized_url = self.require_public_url(url)
        parts = urlsplit(normalized_url)
        host = str(parts.hostname or "")
        try:
            host_address = ipaddress.ip_address(host)
        except ValueError:
            host_address = None
        if host_address is not None:
            return (str(host_address),)

        resolver = self._resolver or socket.getaddrinfo
        try:
            addr_infos = resolver(host, parts.port or None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise DomainPolicyViolation("url 主机名无法解析") from exc
        addresses: list[str] = []
        for addr_info in addr_infos:
            address = str(addr_info[4][0])
            try:
                unsafe = self._is_unsafe_address(address)
            except ValueError as exc:
                raise DomainPolicyViolation("url 主机名解析结果无效") from exc
            if unsafe:
                raise DomainPolicyViolation("禁止访问本地或内网地址")
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise DomainPolicyViolation("url 主机名无法解析")
        return tuple(addresses)

    def validate_redirect_response(self, response: Any, *_args: Any, **_kwargs: Any) -> Any:
        """Requests 钩子：在 resolve_redirects 发出请求前拒绝不安全的 Location。"""
        try:
            status_code = int(getattr(response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            return response
        if status_code not in self.REDIRECT_STATUS_CODES:
            return response
        headers = getattr(response, "headers", {}) or {}
        location = headers.get("Location") or headers.get("location")
        if not location:
            return response
        current_url = str(getattr(response, "url", "") or "")
        target_url = urljoin(current_url, str(location))
        self.require_public_url(target_url)
        return response


PUBLIC_DOMAIN_POLICY = DomainPolicyEngine()

def get_platform_defaults(source: str) -> dict:
    """获取平台运行默认配置。

    优先从配置中心读取持久化配置；若配置系统不可用，则回退到
    `app.config.settings` 中声明的默认配置快照，避免 CLI 层维护重复常量。

    参数：
        source: 平台 ID (douyin/xiaohongshu/bilibili/kuaishou/missav)

    返回：
        dict: 平台默认配置（新 dict，可安全修改）
    """
    if source not in _FALLBACK_CONFIG:
        return {}
    try:
        from app.config import get_platform_runtime_defaults

        return dict(get_platform_runtime_defaults(source))
    except Exception:
        return dict(_FALLBACK_CONFIG[source])

def get_default_save_dir() -> str:
    """获取共享默认保存目录。

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
    """校验 config 中已知参数的类型。

    仅校验已知参数，未知参数透传给 spider（保持前向兼容）。

    参数：
        user_config: 用户传入的 config 字典

    返回：
        str | None: 错误信息（None 表示校验通过）
    """
    if not isinstance(user_config, dict):
        return "config 必须是 JSON 对象"

    for key, expected in _CONFIG_TYPE_RULES.items():
        val = user_config.get(key)
        numeric_types = expected if isinstance(expected, tuple) else (expected,)
        if val is not None and isinstance(val, bool) and any(t in (int, float) for t in numeric_types):
            return f"config.{key} 必须是数字，收到 bool"
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

def validate_direct_download_url(url: str) -> str | None:
    """统一校验直链下载 URL，避免明显 SSRF/内网探测输入。"""
    try:
        PUBLIC_DOMAIN_POLICY.require_public_url(url)
    except DomainPolicyViolation as exc:
        return str(exc)
    return None

def build_missav_proxy_url(proxy_str: str) -> str:
    """通过纯 core 辅助函数构建 MissAV 代理 URL。

    委托可避免调用入口为字符串归一化引入 Qt UI 依赖。
    """
    from app.core.plugins.run_options import build_missav_proxy_url as _build
    return _build(proxy_str)

def _filter_non_none(mapping: dict | None) -> dict:
    if not mapping:
        return {}
    return {key: value for key, value in mapping.items() if value is not None}

def _apply_runtime_config_bridges(
    config: dict,
    *,
    source: str = "",
    proxy_normalizer: Callable[[str], str] | None = None,
) -> dict:
    """应用跨入口共享的运行参数桥接规则。"""
    proxy_normalizer = proxy_normalizer or build_missav_proxy_url

    if source == "missav" and "proxy" in config and config["proxy"] is not None:
        config["proxy"] = proxy_normalizer(config["proxy"])

    # folder_name 只有在启用子目录时才会被路径策略消费。
    if config.get("folder_name") and not config.get("use_subdir"):
        config["use_subdir"] = True

    # 解析器只提供 author 时，将其桥接为可消费的目录名。
    if config.get("author") and not config.get("folder_name"):
        config["folder_name"] = config["author"]
        if not config.get("use_subdir"):
            config["use_subdir"] = True

    return config

def infer_content_type(local_path: str) -> str:
    """根据文件扩展名推断 content_type。

    直接下载（download_video）不经过 spider，content_type 由文件扩展名推断：
    - 视频文件 → "video"
    - 图片文件 → "image"
    - 无法推断 → 空字符串

    参数：
        local_path: 本地文件路径

    返回：
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
    """根据 URL 推断下载前的 content_type 提示。

    SDK download_video 不经过 spider，需要在下载前从 URL 推断 content_type，
    以便 DownloadWorker._infer_extension 能正确推断文件扩展名。
    - URL 含视频扩展名 → "video"
    - URL 含图片扩展名 → "image"
    - URL 含 m3u8 → "video"
    - 无法推断 → 空字符串（下载后再由 infer_content_type 从文件签名推断）

    参数：
        url: 视频/图片 URL

    返回：
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

# 直接下载可读取的本地认证文件名。
_AUTH_FILE_MAP = {
    "douyin":   "dy_auth.json",
    "xiaohongshu": "xhs_auth.json",
    "bilibili": "bili_auth.json",
    "kuaishou": "ks_auth.json",
    "missav":   None,  # MissAV 不需要 cookie
}

def _try_load_cookie(source: str) -> str | None:
    """尝试加载本地认证文件并构建 Cookie 字符串。

    ``download_video`` 不经过 spider 的认证准备阶段，因此在这里补充本地会话。

    参数：
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    返回：
        str | None: cookie 字符串，如果无可用 cookie 则返回 None
    """
    import json
    from pathlib import Path

    auth_name = _AUTH_FILE_MAP.get(source)
    if auth_name is None:
        return None

    # 候选顺序兼容工作目录、旧用户目录、源码目录和当前 user_data_root。
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

    # 优先使用 AuthService 支持的完整 Cookie 数据形状。
    try:
        from app.services.auth_service import AuthService
        return AuthService.build_cookie_string(data)
    except Exception:
        # AuthService 不可用时，手动构建简单 cookie 字符串
        if isinstance(data, dict):
            return "; ".join(f"{k}={v}" for k, v in data.items() if v is not None)
        return None

def _try_load_cookies_dict(source: str) -> dict | None:
    """尝试加载本地认证文件并构建 Cookie 字典。

    BilibiliDownloader 使用该字典刷新 CDN URL；直接下载没有 spider session
    可提供它，因此需从磁盘认证数据恢复。

    参数：
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    返回：
        dict | None: cookie name→value 字典，如果无可用 cookie 则返回 None
    """
    import json
    from pathlib import Path

    auth_name = _AUTH_FILE_MAP.get(source)
    if auth_name is None:
        return None

    # 与 Cookie 字符串加载器共享相同的兼容路径顺序。
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

def merge_convenience_params(
    body: dict,
    config: dict,
    source: str = "",
    *,
    proxy_normalizer: Callable[[str], str] | None = None,
) -> dict:
    """将 REST API/WebSocket 请求体中的便捷参数合并到 config 字典。

    REST API/WebSocket 接受 cookie、download_strategy、referer、ua 等顶层便捷
    字段，避免调用方手写嵌套 JSON config。

    合并优先级：
    1. 平台默认值 (get_platform_defaults)
    2. config 字典中的值
    3. 顶层便捷参数

    顶层便捷参数在合并后单独校验，防止它们绕过 config schema。

    参数：
        body: REST API/WebSocket 请求体
        config: 已合并平台默认值的 config 字典（会被就地修改）
        source: 平台 ID（用于校验平台特定参数）

    返回：
        dict: 合并后的 config 字典
    """
    # 通用爬取限制可直接覆盖已合并配置。
    if body.get("max_items") is not None:
        config["max_items"] = body["max_items"]
    if body.get("max_pages") is not None:
        config["max_pages"] = body["max_pages"]
    if body.get("timeout") is not None and isinstance(body["timeout"], int):
        # REST 顶层 timeout 也可表达整体上限；只有 int 在这里解释为 spider
        # HTTP 超时，float 留给调用层作为 run_timeout 处理。
        config["timeout"] = body["timeout"]

    # MissAV 的筛选与代理便捷字段。
    if body.get("individual_only") is not None:
        config["individual_only"] = body["individual_only"]
    if body.get("priority") is not None:
        config["priority"] = body["priority"]
    if body.get("proxy") is not None:
        config["proxy"] = body["proxy"]

    # 下载请求头、认证与策略字段。
    if body.get("cookie") is not None:
        config["cookie"] = body["cookie"]
    if body.get("download_strategy") is not None:
        config["download_strategy"] = body["download_strategy"]
    if body.get("referer") is not None:
        config["referer"] = body["referer"]
    if body.get("ua") is not None:
        config["ua"] = body["ua"]

    # 下载路径结构字段。
    if body.get("folder_name") is not None:
        config["folder_name"] = body["folder_name"]
    if body.get("use_subdir") is not None:
        config["use_subdir"] = body["use_subdir"]

    # 显式文件名字段。
    if body.get("file_name") is not None:
        config["file_name"] = body["file_name"]

    # 媒体内容类型字段。
    if body.get("content_type") is not None:
        config["content_type"] = body["content_type"]

    # 便捷字段在 config 校验之后合并，必须在此补做自身类型校验。
    _conv_err = _validate_convenience_param_types(body)
    if _conv_err:
        raise ValueError(_conv_err)

    return _apply_runtime_config_bridges(
        config,
        source=source,
        proxy_normalizer=proxy_normalizer,
    )

def compose_runtime_config(
    source: str,
    *,
    base_config: dict | None = None,
    user_config: dict | None = None,
    convenience_body: dict | None = None,
    explicit_none_keys: set[str] | None = None,
    defaults_factory: Callable[[str], dict] | None = None,
    proxy_normalizer: Callable[[str], str] | None = None,
) -> dict:
    """统一组装跨入口运行配置。

    合并顺序：
    1. 平台默认值
    2. 调用方提供的基础配置
    3. 用户配置
    4. 顶层便捷参数

    显式传入的 `None` 键会在最终结果中移除，避免 SDK/CLI/Web 对
    “显式清空字段”的语义出现漂移。
    """
    defaults_factory = defaults_factory or get_platform_defaults
    merged = dict(defaults_factory(source) or {})
    merged.update(_filter_non_none(base_config))
    merged.update(_filter_non_none(user_config))

    for key in explicit_none_keys or ():
        merged.pop(key, None)

    if convenience_body is not None:
        return merge_convenience_params(
            convenience_body,
            merged,
            source,
            proxy_normalizer=proxy_normalizer,
        )

    return _apply_runtime_config_bridges(
        merged,
        source=source,
        proxy_normalizer=proxy_normalizer,
    )

def _validate_convenience_param_types(body: dict) -> str | None:
    """校验 REST API/WebSocket 请求体中便捷参数的类型。

    Web 请求不经过 argparse，因此需要显式拒绝绕过 config schema 的错误类型。

    参数：
        body: REST API/WebSocket 请求体

    返回：
        str | None: 错误信息（None 表示校验通过）
    """
    for key, expected in _CONVENIENCE_PARAM_TYPE_RULES.items():
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
    """获取直接下载所需的平台默认元数据。

    ``download_video`` 不经过 spider 的任务构造阶段，需要在这里提供 ua、
    referer 和可用的本地认证数据，让下载器能够构建请求并刷新受保护 URL。

    参数：
        source: 平台 ID (douyin/bilibili/kuaishou/missav)

    返回：
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

    # 请求头来源与各平台下载器的服务端要求一致：
    # - DouyinDownloader 默认 ua=cfg.get("douyin","user_agent",DEFAULT_USER_AGENT), referer="https://www.douyin.com/"
    # - BilibiliDownloader 默认 ua=cfg.get("bilibili","user_agent",DEFAULT_USER_AGENT), referer="https://www.bilibili.com"
    # - KuaishouDownloader 默认 ua=cfg.get("kuaishou","user_agent",DEFAULT_USER_AGENT), referer="https://www.kuaishou.com/"
    # - MissAVDownloader 默认 referer="https://missav.ai/"
    #
    # 直接下载没有登录交互；本地无认证文件时不注入 cookie，由下载器返回实际
    # 鉴权结果。
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

    # 这里返回的是低优先级默认值；调用配置在上层合并后仍可覆盖本地 cookie。
    _cookie = _try_load_cookie(source)
    if _cookie:
        result["cookie"] = _cookie

    # BilibiliDownloader 刷新 CDN URL 时优先消费 cookies 字典，故除字符串外再
    # 提供结构化认证数据。
    if source == "bilibili":
        _cookies_dict = _try_load_cookies_dict(source)
        if _cookies_dict:
            result["cookies"] = _cookies_dict

    return result
