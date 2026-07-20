"""Shared proxy selection and child-process environment helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse
from urllib.request import getproxies

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
_ENVIRONMENT_REFERENCE_RE = re.compile(r"^env:[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ProxySelection:
    """The requested proxy mode for one release-builder child process."""

    label: str = "系统代理"
    endpoint: str = ""
    label_from_environment: bool = False
    endpoint_from_environment: bool = False

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
        _merge_discovered_system_proxy(environment)
        return environment
    if label in _DIRECT_PROXY_LABELS or lowered_label in _DIRECT_PROXY_LABELS:
        for variable in PROXY_ENVIRONMENT_VARIABLES:
            environment.pop(variable, None)
        return environment

    if label == _CUSTOM_PROXY_LABEL:
        proxy_url = _normalize_explicit_proxy_endpoint(
            selection.endpoint,
            allow_credentials=selection.endpoint_from_environment,
        )
    else:
        if label in _project_proxy_values():
            proxy_url = normalize_proxy_url(label)
        elif selection.label_from_environment:
            proxy_url = _normalize_explicit_proxy_endpoint(
                label,
                allow_credentials=True,
            )
        else:
            raise ValueError("invalid proxy selection")
        if not proxy_url:
            raise ValueError("invalid proxy selection")
    for variable in PROXY_ENVIRONMENT_VARIABLES:
        environment[variable] = proxy_url
    return environment


def _merge_discovered_system_proxy(environment: dict[str, str]) -> None:
    """Populate missing proxy variables from the operating-system settings."""

    if any(str(environment.get(name) or "").strip() for name in PROXY_ENVIRONMENT_VARIABLES):
        return
    try:
        discovered = {
            str(key).casefold(): str(value).strip()
            for key, value in getproxies().items()
            if str(value).strip()
        }
    except (OSError, RuntimeError, TypeError, ValueError):
        return

    http_proxy = _normalize_discovered_proxy(discovered.get("http", ""))
    https_proxy = _normalize_discovered_proxy(discovered.get("https", ""))
    all_proxy = _normalize_discovered_proxy(discovered.get("all", ""))
    if http_proxy:
        environment["HTTP_PROXY"] = http_proxy
        environment["http_proxy"] = http_proxy
    if https_proxy:
        environment["HTTPS_PROXY"] = https_proxy
        environment["https_proxy"] = https_proxy
    if all_proxy:
        environment["ALL_PROXY"] = all_proxy
        environment["all_proxy"] = all_proxy

    no_proxy = discovered.get("no", "")
    if no_proxy and not (environment.get("NO_PROXY") or environment.get("no_proxy")):
        environment["NO_PROXY"] = no_proxy
        environment["no_proxy"] = no_proxy


def _normalize_discovered_proxy(value: str) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return _normalize_explicit_proxy_endpoint(value, allow_credentials=True)
    except ValueError:
        return ""


def validate_proxy_label_reference(value: str) -> str:
    """Accept only a named project choice or an environment reference to one."""

    label = str(value or "").strip()
    lowered = label.lower()
    if _ENVIRONMENT_REFERENCE_RE.fullmatch(label):
        return label
    if (
        label in _SYSTEM_PROXY_LABELS
        or lowered in _SYSTEM_PROXY_LABELS
        or label in _DIRECT_PROXY_LABELS
        or lowered in _DIRECT_PROXY_LABELS
        or label == _CUSTOM_PROXY_LABEL
        or label in _project_proxy_values()
    ):
        return label
    raise ValueError("invalid proxy selection")


def _project_proxy_values() -> frozenset[str]:
    return frozenset(
        str(option.get("value") or "").strip()
        for option in project_proxy_options()
        if str(option.get("value") or "").strip()
    )


def _normalize_explicit_proxy_endpoint(
    endpoint: str,
    *,
    allow_credentials: bool = False,
) -> str:
    text = str(endpoint or "").strip().strip("\"'")
    if not _is_valid_explicit_proxy_endpoint(
        text,
        allow_credentials=allow_credentials,
    ):
        raise ValueError("invalid custom proxy endpoint")
    proxy_url = normalize_proxy_url(text)
    if not proxy_url:
        raise ValueError("invalid custom proxy endpoint")
    return proxy_url


def _is_valid_explicit_proxy_endpoint(
    value: str,
    *,
    allow_credentials: bool,
) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
        parsed = urlparse(value)
    else:
        parsed = urlparse(f"http://{value}")
    try:
        return bool(
            parsed.hostname
            and parsed.port
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and (
                allow_credentials
                or (parsed.username is None and parsed.password is None)
            )
        )
    except ValueError:
        return False


__all__ = [
    "PROXY_ENVIRONMENT_VARIABLES",
    "ProxySelection",
    "build_proxy_environment",
    "normalize_proxy_url",
    "project_proxy_options",
    "validate_proxy_label_reference",
]
