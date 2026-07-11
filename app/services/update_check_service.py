"""Check published release versions for application updates."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Callable

from app.config.update_trust import (
    UPDATE_PUBLIC_KEY_PEM,
    UPDATE_TRUSTED_PUBLISHERS,  # noqa: F401 - compatibility re-export for GUI callers
    UPDATE_TRUSTED_THUMBPRINTS,  # noqa: F401 - compatibility re-export for GUI callers
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
    ManifestLocations,
    MetadataNotFoundError,
    UpdateManifestVerifier,
    VersionPolicy,
    compare_semver,
    load_local_update_state,
    log_update_event,
    open_trusted_url,
    sanitize_filename,
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
UPDATE_STATUS_UNTRUSTED = "untrusted"


class UpdateCheckError(RuntimeError):
    """Raised when the remote release version cannot be resolved."""


class SignedMetadataUnavailableError(UpdateCheckError):
    """Raised when releases exist but omit latest.json or its signature."""


@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    tag_name: str
    release_name: str
    html_url: str
    notes: str = ""
    mandatory: bool = False
    asset_name: str = ""
    installer_type: str = ""
    manifest_path: str = ""
    signature_path: str = ""


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
    candidates: tuple[UpdateCandidate, ...] = ()

    def for_version(self, version: str) -> "UpdateCheckResult":
        """Return a copy pinned to one verified update candidate."""
        normalized = normalize_version(version)
        for candidate in self.candidates:
            if normalize_version(candidate.version) == normalized:
                return replace(
                    self,
                    latest_version=candidate.version,
                    tag_name=candidate.tag_name,
                    release_name=candidate.release_name,
                    html_url=candidate.html_url,
                    notes=candidate.notes,
                    mandatory=candidate.mandatory,
                    asset_name=candidate.asset_name,
                    installer_type=candidate.installer_type,
                    manifest_path=candidate.manifest_path,
                    signature_path=candidate.signature_path,
                )
        raise ValueError(f"unknown update candidate version: {version}")


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
    try:
        validate_asset_url(api_url, {"api.github.com"})
    except ManifestError as exc:
        raise UpdateCheckError(f"GitHub release API must use trusted HTTPS: {exc}") from exc
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "UniversalCrawlerPro/update-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with open_trusted_url(request, timeout=timeout, allowed_hosts={"api.github.com"}) as response:
            final_url = _response_final_url(response, api_url)
            try:
                validate_asset_url(final_url, {"api.github.com"})
            except ManifestError as exc:
                raise UpdateCheckError(f"GitHub release API must use trusted HTTPS: {exc}") from exc
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
    try:
        validate_asset_url(page_url, {"github.com"})
    except ManifestError as exc:
        raise UpdateCheckError(f"GitHub release page must use trusted HTTPS: {exc}") from exc
    request = urllib.request.Request(
        page_url,
        headers={"User-Agent": "UniversalCrawlerPro/update-check"},
    )
    try:
        # GitHub uses a redirect from /latest to /tag/<version>; the handler validates it before following.
        with open_trusted_url(request, timeout=timeout, allowed_hosts={"github.com"}) as response:
            final_url = _response_final_url(response, page_url)
            try:
                validate_asset_url(final_url, {"github.com"})
            except ManifestError as exc:
                raise UpdateCheckError(f"GitHub release page must use trusted HTTPS: {exc}") from exc
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


def _response_final_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    return str(getter() if callable(getter) else fallback)


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
    selected_version: str | None = None,
    max_candidates: int = 10,
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

    verifier = UpdateManifestVerifier(public_key_pem=configured_public_key, app_id=app_id, channel=channel)
    selector = AssetSelector(os_name=os_name, arch=arch)
    managed_state = state if state is not None else load_local_update_state()
    verified_candidates: tuple[UpdateCandidate, ...]

    if manifest_path is not None and signature_path is not None:
        try:
            verified_candidates = (
                _candidate_from_verified_metadata(
                    verifier=verifier,
                    selector=selector,
                    local_version=normalized_local,
                    manifest_path=Path(manifest_path),
                    signature_path=Path(signature_path),
                    release_url=release_url,
                ),
            )
        except (ManifestError, ValueError) as exc:
            raise UpdateCheckError(str(exc)) from exc
    else:
        try:
            verified_candidates = _fetch_verified_update_candidates(
                release_client=release_client or GitHubReleaseClient(owner=owner, repo=repo),
                verifier=verifier,
                selector=selector,
                metadata_dir=metadata_dir,
                local_version=normalized_local,
                manual=manual,
                max_candidates=max_candidates,
            )
        except SignedMetadataUnavailableError:
            # A normal GitHub Release is useful for version comparison but is
            # never sufficient authorization for automatic installation.
            readonly_result = check_for_update(
                normalized_local,
                fetcher=fetch_latest_release_payload,
            )
            if readonly_result.status == UPDATE_STATUS_AVAILABLE:
                log_update_event(
                    "update.check.untrusted_release",
                    "newer release lacks signed update metadata",
                    level="WARN",
                    version=readonly_result.latest_version,
                )
                return replace(readonly_result, status=UPDATE_STATUS_UNTRUSTED)
            return readonly_result

    ranked_candidates = _sort_candidates_desc(verified_candidates)
    if (
        ranked_candidates
        and managed_state.last_seen_version
        and compare_versions(ranked_candidates[0].version, managed_state.last_seen_version) < 0
    ):
        raise UpdateCheckError(
            "Latest verified update candidate is older than last seen version "
            f"{managed_state.last_seen_version}"
        )
    available_candidates = tuple(
        candidate
        for candidate in ranked_candidates
        if _candidate_is_available(
            candidate,
            current_version=normalized_local,
            channel=channel,
            manual=manual,
            state=managed_state,
        )
    )
    if state is None:
        if ranked_candidates and (
            not managed_state.last_seen_version
            or compare_versions(ranked_candidates[0].version, managed_state.last_seen_version) > 0
        ):
            managed_state.last_seen_version = normalize_version(ranked_candidates[0].version)
        save_local_update_state(managed_state)

    selected_candidate = _select_update_candidate(available_candidates, selected_version=selected_version)
    if selected_candidate is not None:
        log_update_event(
            "update.check.available",
            "signed update is available",
            version=selected_candidate.version,
            mandatory=selected_candidate.mandatory,
        )
        return _result_from_candidate(
            selected_candidate,
            status=UPDATE_STATUS_AVAILABLE,
            local_version=normalized_local,
            candidates=available_candidates,
        )

    if not ranked_candidates:
        raise UpdateCheckError("No signed update candidates were available")
    latest_candidate = ranked_candidates[0]
    if compare_versions(normalized_local, latest_candidate.version) > 0:
        status = UPDATE_STATUS_LOCAL_NEWER
    else:
        status = UPDATE_STATUS_CURRENT
    log_update_event(
        "update.check.no_update",
        "no signed update is available",
        version=latest_candidate.version,
        reason="no candidate passed update policy",
    )
    return _result_from_candidate(
        latest_candidate,
        status=status,
        local_version=normalized_local,
        candidates=available_candidates,
    )


def _candidate_from_verified_metadata(
    *,
    verifier: UpdateManifestVerifier,
    selector: AssetSelector,
    local_version: str,
    manifest_path: Path,
    signature_path: Path,
    release_url: str = "",
    tag_name: str = "",
    release_name: str = "",
) -> UpdateCandidate:
    manifest = verifier.load_verified(Path(manifest_path), Path(signature_path))
    asset = selector.select(manifest)
    if compare_versions(local_version, manifest.min_client_version) < 0:
        raise UpdateCheckError(
            f"当前客户端版本 {local_version} 低于此更新要求的最低版本 {manifest.min_client_version}"
        )
    version = normalize_version(manifest.version)
    return UpdateCandidate(
        version=version,
        tag_name=tag_name or manifest.tag,
        release_name=release_name or manifest.tag or manifest.version,
        html_url=release_url,
        notes=manifest.notes,
        mandatory=manifest.mandatory,
        asset_name=asset.name,
        installer_type=asset.installer_type,
        manifest_path=str(manifest_path),
        signature_path=str(signature_path),
    )


def _fetch_verified_update_candidates(
    *,
    release_client: Any,
    verifier: UpdateManifestVerifier,
    selector: AssetSelector,
    metadata_dir: Path,
    local_version: str,
    manual: bool,
    max_candidates: int,
) -> tuple[UpdateCandidate, ...]:
    try:
        if hasattr(release_client, "fetch_manifest_location_candidates"):
            locations = tuple(
                release_client.fetch_manifest_location_candidates(
                    manual=manual,
                    per_page=max_candidates,
                )
            )
        else:
            locations = (release_client.fetch_manifest_locations(manual=manual),)
    except DownloadError as exc:
        cached = _load_cached_update_candidates(
            verifier=verifier,
            selector=selector,
            metadata_dir=metadata_dir,
            local_version=local_version,
        )
        if cached:
            log_update_event(
                "update.check.cache_fallback",
                "release discovery failed; using verified cached manifests",
                level="WARN",
                reason=str(exc),
            )
            return cached
        if isinstance(exc, MetadataNotFoundError):
            raise SignedMetadataUnavailableError(str(exc)) from exc
        raise UpdateCheckError(str(exc)) from exc
    if not locations or all(location.not_modified for location in locations):
        cached = _load_cached_update_candidates(
            verifier=verifier,
            selector=selector,
            metadata_dir=metadata_dir,
            local_version=local_version,
        )
        if cached:
            return cached
        raise UpdateCheckError("GitHub release manifest was not modified and no cached manifest was provided")

    candidates: list[UpdateCandidate] = []
    errors: list[str] = []
    attempted_candidates = 0
    missing_metadata_candidates = 0
    for index, location in enumerate(locations, start=1):
        if location.not_modified:
            continue
        attempted_candidates += 1
        try:
            with tempfile.TemporaryDirectory(prefix=".candidate-", dir=metadata_dir) as temp_dir:
                temp_root = Path(temp_dir)
                temp_manifest = _download_metadata_file(
                    location.manifest_url,
                    temp_root / DEFAULT_MANIFEST_NAME,
                )
                temp_signature = _download_metadata_file(
                    location.signature_url,
                    temp_root / DEFAULT_SIGNATURE_NAME,
                )
                # Verify before touching the last known-good cache. A tag may be
                # republished, so the content digest also makes generations immutable.
                _candidate_from_verified_metadata(
                    verifier=verifier,
                    selector=selector,
                    local_version=local_version,
                    manifest_path=temp_manifest,
                    signature_path=temp_signature,
                    release_url=location.release_url,
                    tag_name=location.tag_name,
                    release_name=location.release_name,
                )
                digest = hashlib.sha256(temp_manifest.read_bytes()).hexdigest()
                manifest_path, signature_path = _metadata_targets(
                    metadata_dir,
                    location,
                    index,
                    content_digest=digest,
                )
                temp_manifest.replace(manifest_path)
                temp_signature.replace(signature_path)
            candidates.append(
                _candidate_from_verified_metadata(
                    verifier=verifier,
                    selector=selector,
                    local_version=local_version,
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    release_url=location.release_url,
                    tag_name=location.tag_name,
                    release_name=location.release_name,
                )
            )
        except MetadataNotFoundError as exc:
            missing_metadata_candidates += 1
            errors.append(str(exc))
            log_update_event("update.check.candidate_skipped", str(exc), level="WARN")
        except (ManifestError, DownloadError, UpdateCheckError, ValueError) as exc:
            errors.append(str(exc))
            log_update_event("update.check.candidate_skipped", str(exc), level="WARN")
    if not candidates:
        cached = _load_cached_update_candidates(
            verifier=verifier,
            selector=selector,
            metadata_dir=metadata_dir,
            local_version=local_version,
        )
        if cached:
            log_update_event(
                "update.check.cache_fallback",
                "fresh update metadata failed; using verified cached manifests",
                level="WARN",
            )
            return cached
        if attempted_candidates and missing_metadata_candidates == attempted_candidates:
            detail = "; ".join(error for error in errors if error)
            raise SignedMetadataUnavailableError(detail or "Signed update metadata is not published")
        detail = "; ".join(error for error in errors if error)
        raise UpdateCheckError(detail or "No signed update candidates were available")
    return tuple(candidates)


def _load_cached_update_candidates(
    *,
    verifier: UpdateManifestVerifier,
    selector: AssetSelector,
    metadata_dir: Path,
    local_version: str,
) -> tuple[UpdateCandidate, ...]:
    pairs: list[tuple[Path, Path]] = []
    legacy_manifest = metadata_dir / DEFAULT_MANIFEST_NAME
    legacy_signature = metadata_dir / DEFAULT_SIGNATURE_NAME
    if legacy_manifest.exists() and legacy_signature.exists():
        pairs.append((legacy_manifest, legacy_signature))
    for manifest_path in metadata_dir.glob(f"*.{DEFAULT_MANIFEST_NAME}"):
        signature_path = manifest_path.with_name(f"{manifest_path.name}.sig")
        if signature_path.exists():
            pairs.append((manifest_path, signature_path))

    candidates: list[UpdateCandidate] = []
    for manifest_path, signature_path in pairs:
        try:
            candidates.append(
                _candidate_from_verified_metadata(
                    verifier=verifier,
                    selector=selector,
                    local_version=local_version,
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                )
            )
        except (ManifestError, UpdateCheckError, ValueError) as exc:
            log_update_event("update.check.cached_candidate_skipped", str(exc), level="WARN")
    return tuple(candidates)


def _metadata_targets(
    metadata_dir: Path,
    location: ManifestLocations,
    index: int,
    *,
    content_digest: str = "",
) -> tuple[Path, Path]:
    label = normalize_version(location.tag_name or location.release_name or "") or f"candidate-{index}"
    safe_label = sanitize_filename(label)
    generation = f"-{content_digest[:16]}" if content_digest else ""
    return (
        metadata_dir / f"{safe_label}{generation}.{DEFAULT_MANIFEST_NAME}",
        metadata_dir / f"{safe_label}{generation}.{DEFAULT_SIGNATURE_NAME}",
    )


def _sort_candidates_desc(candidates: tuple[UpdateCandidate, ...]) -> tuple[UpdateCandidate, ...]:
    def compare_candidates(left: UpdateCandidate, right: UpdateCandidate) -> int:
        return -compare_versions(left.version, right.version)

    return tuple(
        sorted(
            candidates,
            key=cmp_to_key(compare_candidates),
        )
    )


def _candidate_is_available(
    candidate: UpdateCandidate,
    *,
    current_version: str,
    channel: str,
    manual: bool,
    state: LocalUpdateState,
) -> bool:
    policy_state = LocalUpdateState(
        skipped_version=state.skipped_version,
        install_attempt_limit=state.install_attempt_limit,
    )
    policy = VersionPolicy(channel=channel, state=policy_state).evaluate(
        candidate.version,
        current_version=current_version,
        manual=manual,
        mandatory=candidate.mandatory,
    )
    return policy.allowed


def _select_update_candidate(
    candidates: tuple[UpdateCandidate, ...],
    *,
    selected_version: str | None,
) -> UpdateCandidate | None:
    if not candidates:
        return None
    if not selected_version:
        return candidates[0]
    normalized = normalize_version(selected_version)
    for candidate in candidates:
        if normalize_version(candidate.version) == normalized:
            return candidate
    raise UpdateCheckError(f"Selected update version is not available: {selected_version}")


def _result_from_candidate(
    candidate: UpdateCandidate,
    *,
    status: str,
    local_version: str,
    candidates: tuple[UpdateCandidate, ...],
) -> UpdateCheckResult:
    return UpdateCheckResult(
        status=status,
        local_version=local_version,
        latest_version=candidate.version,
        tag_name=candidate.tag_name,
        release_name=candidate.release_name,
        html_url=candidate.html_url,
        notes=candidate.notes,
        mandatory=candidate.mandatory,
        asset_name=candidate.asset_name,
        installer_type=candidate.installer_type,
        manifest_path=candidate.manifest_path,
        signature_path=candidate.signature_path,
        candidates=candidates,
    )


def _download_metadata_file(url: str, target: Path, *, timeout: float = 8.0, max_bytes: int = 2_000_000) -> Path:
    allowed_hosts = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
    try:
        validate_asset_url(url, allowed_hosts)
    except ManifestError as exc:
        raise DownloadError(f"metadata URL must use trusted HTTPS: {exc}") from exc
    request = urllib.request.Request(url, headers={"User-Agent": "UniversalCrawlerPro/update-check"})
    try:
        # Signed metadata may redirect to GitHub's asset CDN, but nowhere else.
        with open_trusted_url(request, timeout=timeout, allowed_hosts=allowed_hosts) as response:
            final_url = _response_final_url(response, url)
            try:
                validate_asset_url(final_url, allowed_hosts)
            except ManifestError as exc:
                raise DownloadError(f"metadata URL must use trusted HTTPS: {exc}") from exc
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MetadataNotFoundError("metadata download failed with HTTP 404") from exc
        raise DownloadError(f"metadata download failed with HTTP {exc.code}") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise DownloadError(f"metadata download failed: {exc}") from exc
    if len(data) > max_bytes:
        raise DownloadError("metadata file exceeds size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
