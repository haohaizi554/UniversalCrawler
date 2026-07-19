"""Shared proxy selection and child-process environment helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse

from app.config.settings import proxy_app_options
from app.core.plugins.run_options import normalize_proxy_url


PROXY_ENVIRONMENT_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_SYSTEM_PROXY_LABELS = {"系统代理", "system", "system proxy"}
_DIRECT_PROXY_LABELS = {"直连", "direct", "none", "no proxy"}
_CUSTOM_PROXY_LABEL = "自定义"


@dataclass(frozen=True)
class ProxySelection:
    """The requested proxy mode for one release-builder child process."""

    label: str = "系统代理"
    endpoint: str = ""

    @classmethod
    def system(cls) -> "ProxySelection":
        return cls()

    @classmethod
    def direct(cls) -> "ProxySelection":
        return cls(label="直连")


def project_proxy_options() -> tuple[Mapping[str, str], ...]:
    """Return immutable copies of the application's proxy option contract."""
    return tuple(MappingProxyType(dict(option)) for option in proxy_app_options())


def build_proxy_environment(
    selection: ProxySelection,
    base_env: Mapping[str, str],
) -> dict[str, str]:
    """Build an isolated environment for a release-builder child process."""
    environment = dict(base_env)
    label = str(selection.label or "").strip()
    lowered_label = label.lower()

    if label in _SYSTEM_PROXY_LABELS or lowered_label in _SYSTEM_PROXY_LABELS:
        return environment
    if label in _DIRECT_PROXY_LABELS or lowered_label in _DIRECT_PROXY_LABELS:
        for variable in PROXY_ENVIRONMENT_VARIABLES:
            environment.pop(variable, None)
        return environment

    if label == _CUSTOM_PROXY_LABEL:
        proxy_url = _normalize_explicit_proxy_endpoint(selection.endpoint)
    else:
        proxy_url = normalize_proxy_url(label)
        if not proxy_url:
            raise ValueError("invalid proxy selection")
    for variable in PROXY_ENVIRONMENT_VARIABLES:
        environment[variable] = proxy_url
    return environment


def _normalize_explicit_proxy_endpoint(endpoint: str) -> str:
    text = str(endpoint or "").strip().strip("\"'")
    if not _is_valid_explicit_proxy_endpoint(text):
        raise ValueError("invalid custom proxy endpoint")
    proxy_url = normalize_proxy_url(text)
    if not proxy_url:
        raise ValueError("invalid custom proxy endpoint")
    return proxy_url


def _is_valid_explicit_proxy_endpoint(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
        parsed = urlparse(value)
    else:
        parsed = urlparse(f"http://{value}")
    try:
        return bool(parsed.hostname and parsed.port)
    except ValueError:
        return False


__all__ = [
    "PROXY_ENVIRONMENT_VARIABLES",
    "ProxySelection",
    "build_proxy_environment",
    "normalize_proxy_url",
    "project_proxy_options",
]
