"""统一第三方 HTTP 客户端的显式代理语义。"""

from __future__ import annotations

from typing import Any, TypeVar

_SessionT = TypeVar("_SessionT")


def requests_proxy_mapping(proxy: object = None) -> dict[str, str | None]:
    """返回 Requests 的显式映射；空值表示直连，而不是读取系统/环境代理。"""
    normalized = str(proxy or "").strip()
    if normalized:
        return {"http": normalized, "https": normalized, "all": normalized}
    return {"http": None, "https": None, "all": None}


def configure_requests_session(session: _SessionT) -> _SessionT:
    """关闭 Requests 对环境变量和 Windows 注册表代理的隐式发现。"""
    if session is not None:
        setattr(session, "trust_env", False)
    return session


def explicit_requests_proxies(proxies: Any) -> dict[str, str | None]:
    """保留调用方给出的代理映射；未给出时明确选择直连。"""
    if proxies:
        return dict(proxies)
    return requests_proxy_mapping()


__all__ = [
    "configure_requests_session",
    "explicit_requests_proxies",
    "requests_proxy_mapping",
]
