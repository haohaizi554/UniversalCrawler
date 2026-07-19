"""Bounded, read-only GitHub release metadata lookups."""

from __future__ import annotations

import base64
import json
import math
import re
from collections.abc import Mapping
from urllib.parse import unquote
from urllib.request import ProxyHandler, Request, _parse_proxy, build_opener

from .events import redact_release_text
from .models import RemoteReleaseInfo


GITHUB_API_ACCEPT = "application/vnd.github+json"
GITHUB_API_USER_AGENT = "UniversalCrawlerReleaseBuilder/1.0"
MAX_RESPONSE_BYTES = 1_000_000
_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def fetch_latest_release(
    repository: str,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float = 10.0,
) -> RemoteReleaseInfo:
    """Return the newest public release version, or an explicit unknown state."""

    try:
        owner, name = _repository_components(repository)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        request = Request(
            f"https://api.github.com/repos/{owner}/{name}/releases/latest",
            headers={
                "Accept": GITHUB_API_ACCEPT,
                "User-Agent": GITHUB_API_USER_AGENT,
            },
            method="GET",
        )
        payload = _open_json(
            request,
            environment=dict(environment),
            timeout_seconds=timeout,
        )
        tag = payload.get("tag_name") if isinstance(payload, Mapping) else None
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError("latest release response has no tag_name")
        return RemoteReleaseInfo.available(tag)
    except Exception as error:
        return RemoteReleaseInfo.unavailable(redact_release_text(str(error)))


def _open_json(
    request: Request,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> object:
    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    no_proxy = values.get("no_proxy", "")
    handler = _EnvironmentProxyHandler(
        _proxy_settings(values, host=request.host or ""),
        no_proxy=no_proxy,
    )
    opener = build_opener(handler)
    with opener.open(request, timeout=timeout_seconds) as response:
        content = response.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("GitHub response exceeds the configured size limit")
    return json.loads(content.decode("utf-8"))


def _proxy_settings(environment: Mapping[str, str], *, host: str = "api.github.com") -> dict[str, str]:
    """Return only proxy settings selected from the supplied environment."""

    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    if _matches_no_proxy(host, values.get("no_proxy", "")):
        return {}
    fallback = values.get("all_proxy", "")
    return {
        scheme: values.get(f"{scheme}_proxy", fallback)
        for scheme in ("http", "https")
        if values.get(f"{scheme}_proxy", fallback)
    }


def _matches_no_proxy(host: str, entries: str) -> bool:
    hostname = str(host).split(":", 1)[0].casefold().rstrip(".")
    for raw_entry in str(entries).split(","):
        entry = raw_entry.strip().casefold().lstrip(".").rstrip(".")
        if not entry:
            continue
        if entry == "*":
            return True
        if hostname == entry or hostname.endswith(f".{entry}"):
            return True
    return False


class _EnvironmentProxyHandler(ProxyHandler):
    """A ProxyHandler that never asks urllib to consult ambient environment state."""

    def __init__(self, proxies: Mapping[str, str], *, no_proxy: str) -> None:
        super().__init__(dict(proxies))
        self._no_proxy = str(no_proxy)

    def proxy_open(self, request: Request, proxy: str, request_type: str):
        original_type = request.type
        proxy_type, user, password, hostport = _parse_proxy(proxy)
        if proxy_type is None:
            proxy_type = original_type
        if request.host and _matches_no_proxy(request.host, self._no_proxy):
            return None
        if user and password:
            user_pass = f"{unquote(user)}:{unquote(password)}"
            encoded = base64.b64encode(user_pass.encode()).decode("ascii")
            request.add_header("Proxy-authorization", f"Basic {encoded}")
        request.set_proxy(unquote(hostport), proxy_type)
        if original_type == proxy_type or original_type == "https":
            return None
        return self.parent.open(request, timeout=request.timeout)


def _repository_components(repository: str) -> tuple[str, str]:
    parts = str(repository).split("/")
    if len(parts) != 2 or not all(_is_safe_component(part) for part in parts):
        raise ValueError("invalid GitHub repository")
    return parts[0], parts[1]


def _is_safe_component(value: str) -> bool:
    return bool(
        _COMPONENT_PATTERN.fullmatch(value)
        and value not in {".", ".."}
        and not value.startswith("-")
        and not value.endswith(".")
    )


__all__ = ["GITHUB_API_ACCEPT", "GITHUB_API_USER_AGENT", "fetch_latest_release"]
