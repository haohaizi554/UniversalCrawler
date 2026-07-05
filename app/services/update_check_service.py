"""Check published release versions for application updates."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

LATEST_RELEASE_API_URL = "https://api.github.com/repos/haohaizi554/UniversalCrawler/releases/latest"
LATEST_RELEASE_PAGE_URL = "https://github.com/haohaizi554/UniversalCrawler/releases/latest"
UPDATE_STATUS_CURRENT = "current"
UPDATE_STATUS_AVAILABLE = "available"
UPDATE_STATUS_LOCAL_NEWER = "local_newer"


class UpdateCheckError(RuntimeError):
    """Raised when the remote release version cannot be resolved."""


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    local_version: str
    latest_version: str
    tag_name: str
    release_name: str
    html_url: str


def normalize_version(value: Any) -> str:
    """Return a comparable version string without display prefixes."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.search(r"\d+(?:\.\d+)*(?:[-+][0-9A-Za-z._-]+)?", raw)
    if match:
        return match.group(0)
    return raw.removeprefix("v").removeprefix("V").strip()


def _version_parts(value: Any) -> tuple[int, ...]:
    version = normalize_version(value)
    core = version.split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for item in core.split("."):
        if not item.isdigit():
            break
        parts.append(int(item))
    if not parts:
        raise ValueError(f"invalid version: {value!r}")
    return tuple(parts)


def compare_versions(local_version: Any, latest_version: Any) -> int:
    """Compare versions numerically: -1 local older, 0 equal, 1 local newer."""
    local = _version_parts(local_version)
    latest = _version_parts(latest_version)
    width = max(len(local), len(latest))
    local_padded = local + (0,) * (width - len(local))
    latest_padded = latest + (0,) * (width - len(latest))
    if local_padded < latest_padded:
        return -1
    if local_padded > latest_padded:
        return 1
    return 0


def fetch_latest_release_payload(
    *,
    api_url: str = LATEST_RELEASE_API_URL,
    timeout: float = 8.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "UniversalCrawlerPro/update-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429} and api_url == LATEST_RELEASE_API_URL:
            return fetch_latest_release_page_payload(timeout=timeout)
        raise UpdateCheckError(f"GitHub release request failed with HTTP {exc.code}") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise UpdateCheckError(f"GitHub release request failed: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UpdateCheckError("GitHub release response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise UpdateCheckError("GitHub release response had an unexpected shape")
    return data


def fetch_latest_release_page_payload(
    *,
    page_url: str = LATEST_RELEASE_PAGE_URL,
    timeout: float = 8.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        page_url,
        headers={"User-Agent": "UniversalCrawlerPro/update-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            body = response.read(256_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(f"GitHub release page request failed with HTTP {exc.code}") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise UpdateCheckError(f"GitHub release page request failed: {exc}") from exc

    tag_name = _release_tag_from_url(final_url) or _release_tag_from_html(body)
    if not tag_name:
        raise UpdateCheckError("Latest release page did not expose a release tag")
    html_url = _release_html_url(tag_name, page_url)
    return {
        "tag_name": tag_name,
        "name": tag_name,
        "html_url": html_url,
    }


def _release_tag_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/releases/tag/([^/?#]+)", parsed.path)
    if not match:
        return ""
    return urllib.parse.unquote(match.group(1))


def _release_tag_from_html(html: str) -> str:
    match = re.search(r'href="[^"]*/releases/tag/([^"/?#]+)', html)
    if not match:
        return ""
    return urllib.parse.unquote(match.group(1))


def _release_html_url(tag_name: str, page_url: str) -> str:
    parsed = urllib.parse.urlparse(page_url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, repo = parts[0], parts[1]
    else:
        owner, repo = "haohaizi554", "UniversalCrawler"
    return f"{parsed.scheme or 'https'}://{parsed.netloc or 'github.com'}/{owner}/{repo}/releases/tag/{urllib.parse.quote(tag_name)}"


def check_for_update(
    local_version: Any,
    *,
    fetcher: Callable[[], dict[str, Any]] = fetch_latest_release_payload,
) -> UpdateCheckResult:
    payload = fetcher()
    tag_name = str(payload.get("tag_name") or "").strip()
    release_name = str(payload.get("name") or "").strip()
    latest_version = normalize_version(tag_name or release_name)
    normalized_local = normalize_version(local_version)
    if not normalized_local:
        raise UpdateCheckError("Local version is empty")
    if not latest_version:
        raise UpdateCheckError("Latest release did not include a version tag")

    comparison = compare_versions(normalized_local, latest_version)
    if comparison < 0:
        status = UPDATE_STATUS_AVAILABLE
    elif comparison > 0:
        status = UPDATE_STATUS_LOCAL_NEWER
    else:
        status = UPDATE_STATUS_CURRENT

    return UpdateCheckResult(
        status=status,
        local_version=normalized_local,
        latest_version=latest_version,
        tag_name=tag_name,
        release_name=release_name,
        html_url=str(payload.get("html_url") or "").strip(),
    )
