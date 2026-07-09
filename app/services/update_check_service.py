"""Check published release versions for application updates."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config.update_trust import (
    UPDATE_PUBLIC_KEY_PEM,
    UPDATE_TRUSTED_PUBLISHERS,
    UPDATE_TRUSTED_THUMBPRINTS,
)
from app.services.secure_updater import (
    APP_ID,
    DEFAULT_CHANNEL,
    DEFAULT_MANIFEST_NAME,
    DEFAULT_SIGNATURE_NAME,
    AssetSelector,
    DownloadError,
    GitHubReleaseClient,
    LocalUpdateState,
    ManifestError,
    UpdateManifestVerifier,
    VersionPolicy,
    compare_semver,
    load_local_update_state,
    log_update_event,
    save_local_update_state,
    validate_asset_url,
)
from app.utils.runtime_paths import user_cache_root

LATEST_RELEASE_API_URL = "https://api.github.com/repos/haohaizi554/UniversalCrawler/releases/latest"
LATEST_RELEASE_PAGE_URL = "https://github.com/haohaizi554/UniversalCrawler/releases/latest"
UPDATE_OWNER = "haohaizi554"
UPDATE_REPO = "UniversalCrawler"
UPDATE_APP_ID = APP_ID
UPDATE_CHANNEL = DEFAULT_CHANNEL
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
    notes: str = ""
    mandatory: bool = False
    asset_name: str = ""
    installer_type: str = ""
    manifest_path: str = ""
    signature_path: str = ""


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
    try:
        return compare_semver(normalize_version(local_version), normalize_version(latest_version))
    except ValueError:
        pass
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


def check_secure_update(
    local_version: Any,
    *,
    public_key_pem: str | None = None,
    manifest_path: str | Path | None = None,
    signature_path: str | Path | None = None,
    release_url: str = "",
    owner: str = UPDATE_OWNER,
    repo: str = UPDATE_REPO,
    channel: str = UPDATE_CHANNEL,
    app_id: str = UPDATE_APP_ID,
    os_name: str | None = None,
    arch: str | None = None,
    manual: bool = True,
    state: LocalUpdateState | None = None,
    release_client: GitHubReleaseClient | None = None,
) -> UpdateCheckResult:
    """Check for a signed-manifest update and select the current platform asset.

    This is the production update path.  The older ``check_for_update`` remains
    available for read-only release-tag checks, but it is not sufficient for
    download/install decisions because it has no signed manifest.
    """

    configured_public_key = UPDATE_PUBLIC_KEY_PEM if public_key_pem is None else public_key_pem
    if not str(configured_public_key or "").strip():
        raise UpdateCheckError("安全更新公钥未配置，无法验证 latest.json 签名")
    normalized_local = normalize_version(local_version)
    if not normalized_local:
        raise UpdateCheckError("Local version is empty")

    metadata_dir = user_cache_root() / "updates" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if manifest_path is None or signature_path is None:
        client = release_client or GitHubReleaseClient(owner=owner, repo=repo)
        try:
            locations = client.fetch_manifest_locations(manual=manual)
        except DownloadError as exc:
            raise UpdateCheckError(str(exc)) from exc
        if locations.not_modified:
            raise UpdateCheckError("GitHub release manifest was not modified and no cached manifest was provided")
        release_url = release_url or locations.release_url
        try:
            manifest_path = _download_metadata_file(
                locations.manifest_url,
                metadata_dir / DEFAULT_MANIFEST_NAME,
            )
            signature_path = _download_metadata_file(
                locations.signature_url,
                metadata_dir / DEFAULT_SIGNATURE_NAME,
            )
        except (ManifestError, DownloadError) as exc:
            raise UpdateCheckError(str(exc)) from exc

    verifier = UpdateManifestVerifier(public_key_pem=configured_public_key, app_id=app_id, channel=channel)
    try:
        manifest = verifier.load_verified(Path(manifest_path), Path(signature_path))
        asset = AssetSelector(os_name=os_name, arch=arch).select(manifest)
    except (ManifestError, ValueError) as exc:
        raise UpdateCheckError(str(exc)) from exc
    if compare_versions(normalized_local, manifest.min_client_version) < 0:
        raise UpdateCheckError(
            f"当前客户端版本 {normalized_local} 低于此更新要求的最低版本 {manifest.min_client_version}"
        )

    managed_state = state if state is not None else load_local_update_state()
    policy = VersionPolicy(channel=channel, state=managed_state).evaluate(
        manifest.version,
        current_version=normalized_local,
        manual=manual,
        mandatory=manifest.mandatory,
    )
    if state is None:
        save_local_update_state(managed_state)
    latest_version = normalize_version(manifest.version)
    if not policy.allowed:
        if compare_versions(normalized_local, latest_version) > 0:
            status = UPDATE_STATUS_LOCAL_NEWER
        else:
            status = UPDATE_STATUS_CURRENT
    else:
        status = UPDATE_STATUS_AVAILABLE
    if status == UPDATE_STATUS_AVAILABLE:
        log_update_event("update.check.available", "signed update is available", version=latest_version, mandatory=manifest.mandatory)
    else:
        log_update_event("update.check.no_update", "no signed update is available", version=latest_version, reason=policy.reason)

    return UpdateCheckResult(
        status=status,
        local_version=normalized_local,
        latest_version=latest_version,
        tag_name=manifest.tag,
        release_name=manifest.tag or manifest.version,
        html_url=release_url,
        notes=manifest.notes,
        mandatory=manifest.mandatory,
        asset_name=asset.name,
        installer_type=asset.installer_type,
        manifest_path=str(manifest_path),
        signature_path=str(signature_path),
    )


def _download_metadata_file(url: str, target: Path, *, timeout: float = 8.0, max_bytes: int = 2_000_000) -> Path:
    validate_asset_url(url, {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})
    request = urllib.request.Request(url, headers={"User-Agent": "UniversalCrawlerPro/update-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"metadata download failed with HTTP {exc.code}") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise DownloadError(f"metadata download failed: {exc}") from exc
    if len(data) > max_bytes:
        raise DownloadError("metadata file exceeds size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
