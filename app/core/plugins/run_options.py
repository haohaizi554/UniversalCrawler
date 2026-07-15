"""GUI、CLI 与 Web 共用且不依赖宿主的运行参数工具。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PROXY_PRESET_URLS: dict[str, str] = {
    "\u7cfb\u7edf\u4ee3\u7406": "",
    "\u76f4\u8fde": "",
    "Clash (7890)": "http://127.0.0.1:7890",
    "Clash Verge (7897)": "http://127.0.0.1:7897",
    "v2rayN (10809)": "http://127.0.0.1:10809",
    "V2Ray / Qv2ray (10808)": "http://127.0.0.1:10808",
    "sing-box (2080)": "http://127.0.0.1:2080",
    "NekoRay (2080)": "socks5://127.0.0.1:2080",
}

_PROXY_LABEL_PORT_HINTS: tuple[tuple[str, str], ...] = (
    ("clash verge", "7897"),
    ("clash", "7890"),
    ("v2rayn", "10809"),
    ("v2ray", "10808"),
    ("qv2ray", "10808"),
    ("sing-box", "2080"),
    ("singbox", "2080"),
    ("nekoray", "2080"),
)


def _valid_proxy_port(value: str) -> str:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= port <= 65535:
        return str(port)
    return ""


def _proxy_port_hint(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if normalized.isdigit():
        return _valid_proxy_port(normalized)
    lowered = normalized.lower()
    has_known_label = any(label in lowered for label, _port in _PROXY_LABEL_PORT_HINTS)
    if has_known_label:
        numbers = re.findall(r"(?<!\d)(\d{1,5})(?!\d)", normalized)
        for candidate in reversed(numbers):
            port = _valid_proxy_port(candidate)
            if port:
                return port
    for label, port in _PROXY_LABEL_PORT_HINTS:
        if label in lowered:
            return port
    parenthesized = re.findall(r"\((\d{1,5})\)", normalized)
    for candidate in reversed(parenthesized):
        port = _valid_proxy_port(candidate)
        if port:
            return port
    if normalized.startswith(":"):
        return _valid_proxy_port(normalized[1:])
    if "端口" in normalized or "port" in lowered:
        numbers = re.findall(r"(?<!\d)(\d{1,5})(?!\d)", normalized)
        for candidate in reversed(numbers):
            port = _valid_proxy_port(candidate)
            if port:
                return port
    return ""


def build_missav_proxy_url(proxy_str: str) -> str:
    """把代理预设标签或自定义主机端口规范化为 URL。"""
    normalized = str(proxy_str or "").strip().strip("\"'")
    if normalized in PROXY_PRESET_URLS:
        return PROXY_PRESET_URLS[normalized]
    if not normalized or normalized == "\u81ea\u5b9a\u4e49":
        return ""
    lowered = normalized.lower()
    if lowered in {"system", "system proxy", "direct", "none", "no proxy"}:
        return ""
    if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
        parsed = urlparse(normalized)
        return normalized if parsed.hostname and parsed.port else ""
    port_hint = _proxy_port_hint(normalized)
    if port_hint:
        return f"http://127.0.0.1:{port_hint}"
    if ":" in normalized:
        if normalized.startswith(":"):
            return ""
        return f"http://{normalized}"
    return "http://127.0.0.1:7890"
