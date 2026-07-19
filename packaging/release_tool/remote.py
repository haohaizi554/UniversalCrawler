"""Bounded, read-only GitHub release metadata lookups."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.request import ProxyHandler, Request, build_opener

from .events import redact_release_text
from .models import RemoteReleaseInfo


GITHUB_API_ACCEPT = "application/vnd.github+json"
GITHUB_API_USER_AGENT = "UniversalCrawlerReleaseBuilder/1.0"
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def fetch_latest_release(
    repository: str,
    *,
    environment: Mapping[str, str],
    timeout_seconds: float = 10.0,
) -> RemoteReleaseInfo:
    """Return the newest public release version, or an explicit unknown state."""

    try:
        if not _REPOSITORY_PATTERN.fullmatch(str(repository)):
            raise ValueError("invalid GitHub repository")
        timeout = float(timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        request = Request(
            f"https://api.github.com/repos/{repository}/releases/latest",
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
    proxies = _proxy_settings(environment)
    opener = build_opener(ProxyHandler(proxies))
    with opener.open(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _proxy_settings(environment: Mapping[str, str]) -> dict[str, str]:
    values = {str(key).casefold(): str(value) for key, value in environment.items()}
    fallback = values.get("all_proxy", "")
    return {
        scheme: values.get(f"{scheme}_proxy", fallback)
        for scheme in ("http", "https")
        if values.get(f"{scheme}_proxy", fallback)
    }


__all__ = ["GITHUB_API_ACCEPT", "GITHUB_API_USER_AGENT", "fetch_latest_release"]
