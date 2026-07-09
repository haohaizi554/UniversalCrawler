"""Secure desktop updater primitives.

This module keeps update discovery, package verification and installer launch
out of the GUI layer.  It deliberately does not contain GitHub credentials and
never executes a downloaded asset until manifest signature, hash and platform
signature checks have succeeded.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable, Mapping

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_cache_root, user_logs_root


APP_ID = "ucrawl.universalcrawlerpro"
DEFAULT_CHANNEL = "stable"
MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MANIFEST_NAME = "latest.json"
DEFAULT_SIGNATURE_NAME = "latest.json.sig"
DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
DEFAULT_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30.0
DEFAULT_INSTALL_ATTEMPT_LIMIT = 2
DEFAULT_UPDATE_STATE_NAME = "state.json"
DEFAULT_AUTO_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


class ManifestError(RuntimeError):
    """Raised when a signed update manifest is absent, invalid or unsafe."""


class DownloadError(RuntimeError):
    """Raised for update download, GitHub API and staging failures."""

    def __init__(self, message: str, *, keep_partial: bool = False) -> None:
        super().__init__(message)
        self.keep_partial = bool(keep_partial)


class VerificationError(RuntimeError):
    """Raised when package signature verification fails."""


class InstallError(RuntimeError):
    """Raised when a verified installer cannot be launched."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: str = ""

    @classmethod
    def parse(cls, value: Any) -> "SemVer":
        raw = str(value or "").strip()
        if raw.lower().startswith("v"):
            raw = raw[1:]
        match = re.fullmatch(
            r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?",
            raw,
        )
        if not match:
            raise ValueError(f"invalid semver: {value!r}")
        prerelease = tuple(part for part in (match.group(4) or "").split(".") if part)
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
            build=match.group(5) or "",
        )


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    for left_part, right_part in zip(left, right):
        left_num = left_part.isdigit()
        right_num = right_part.isdigit()
        if left_num and right_num:
            left_value, right_value = int(left_part), int(right_part)
        else:
            if left_num:
                return -1
            if right_num:
                return 1
            left_value, right_value = left_part, right_part
        if left_value < right_value:
            return -1
        if left_value > right_value:
            return 1
    if len(left) < len(right):
        return -1
    if len(left) > len(right):
        return 1
    return 0


def compare_semver(left: Any, right: Any) -> int:
    """Compare semantic versions without string ordering shortcuts."""

    left_version = SemVer.parse(left)
    right_version = SemVer.parse(right)
    left_core = (left_version.major, left_version.minor, left_version.patch)
    right_core = (right_version.major, right_version.minor, right_version.patch)
    if left_core < right_core:
        return -1
    if left_core > right_core:
        return 1
    return _compare_prerelease(left_version.prerelease, right_version.prerelease)


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    sha256: str
    size: int
    installer_type: str
    os: str
    arch: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UpdateAsset":
        return cls(
            name=str(data.get("name") or ""),
            url=str(data.get("url") or ""),
            sha256=str(data.get("sha256") or "").lower(),
            size=int(data.get("size") or 0),
            installer_type=str(data.get("installerType") or data.get("installer_type") or ""),
            os=str(data.get("os") or "").lower(),
            arch=normalize_arch(data.get("arch") or ""),
        )


@dataclass(frozen=True)
class UpdateManifest:
    schema: int
    app_id: str
    channel: str
    version: str
    tag: str
    published_at: str
    expires_at: str
    min_client_version: str
    mandatory: bool
    notes: str
    assets: dict[str, UpdateAsset]
    trusted_hosts: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UpdateManifest":
        assets_raw = data.get("assets")
        if not isinstance(assets_raw, Mapping):
            raise ManifestError("manifest assets must be a map")
        assets = {str(key): UpdateAsset.from_dict(value) for key, value in assets_raw.items() if isinstance(value, Mapping)}
        trusted_hosts = tuple(str(host).lower() for host in data.get("trustedHosts") or () if host)
        return cls(
            schema=int(data.get("schema") or 0),
            app_id=str(data.get("appId") or data.get("app_id") or ""),
            channel=str(data.get("channel") or ""),
            version=str(data.get("version") or ""),
            tag=str(data.get("tag") or ""),
            published_at=str(data.get("publishedAt") or data.get("published_at") or ""),
            expires_at=str(data.get("expiresAt") or data.get("expires_at") or ""),
            min_client_version=str(data.get("minClientVersion") or data.get("min_client_version") or ""),
            mandatory=bool(data.get("mandatory")),
            notes=str(data.get("notes") or ""),
            assets=assets,
            trusted_hosts=trusted_hosts,
        )


class UpdateManifestVerifier:
    """Load and validate a signed Ed25519 update manifest."""

    def __init__(
        self,
        *,
        public_key_pem: str,
        app_id: str = APP_ID,
        channel: str = DEFAULT_CHANNEL,
        schema: int = MANIFEST_SCHEMA_VERSION,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.public_key_pem = public_key_pem
        self.app_id = app_id
        self.channel = channel
        self.schema = schema
        self._now = now or (lambda: datetime.now(timezone.utc))

    def load_verified(self, manifest_path: Path, signature_path: Path) -> UpdateManifest:
        manifest_bytes = Path(manifest_path).read_bytes()
        signature = Path(signature_path).read_bytes()
        self.verify_signature(manifest_bytes, signature)
        try:
            payload = json.loads(manifest_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError("manifest is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ManifestError("manifest root must be an object")
        manifest = UpdateManifest.from_dict(payload)
        self.validate(manifest)
        return manifest

    def verify_signature(self, manifest_bytes: bytes, signature: bytes) -> None:
        try:
            key = ECC.import_key(self.public_key_pem)
            verifier = eddsa.new(key, "rfc8032")
            verifier.verify(manifest_bytes, signature)
        except Exception as exc:
            _log_update_event("update.verify.failed", "manifest signature verification failed", level="SECURITY")
            raise ManifestError("manifest signature verification failed") from exc

    def validate(self, manifest: UpdateManifest) -> None:
        if manifest.schema != self.schema:
            raise ManifestError("manifest schema is not supported")
        if manifest.app_id != self.app_id:
            raise ManifestError("manifest appId does not match this application")
        if manifest.channel != self.channel:
            raise ManifestError("manifest channel does not match this client")
        try:
            SemVer.parse(manifest.version)
            SemVer.parse(manifest.min_client_version)
        except ValueError as exc:
            raise ManifestError(str(exc)) from exc
        expires_at = _parse_rfc3339(manifest.expires_at)
        if expires_at <= self._now():
            raise ManifestError("manifest is expired")
        if not manifest.assets:
            raise ManifestError("manifest has no assets")
        for asset in manifest.assets.values():
            _validate_asset_shape(asset)


@dataclass
class PendingInstall:
    version: str
    attempts: int = 0
    installer_path: str = ""
    log_path: str = ""


@dataclass
class LocalUpdateState:
    last_seen_version: str = ""
    skipped_version: str = ""
    pending_install: PendingInstall | None = None
    last_install_error: str = ""
    install_attempt_limit: int = DEFAULT_INSTALL_ATTEMPT_LIMIT

    def record_startup_health(self, *, current_version: str, staging_dir: Path | None = None) -> None:
        pending = self.pending_install
        if pending is None:
            return
        if compare_semver(current_version, pending.version) == 0:
            self.pending_install = None
            self.last_install_error = ""
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)
            _log_update_event("update.install.succeeded", "pending update completed", version=current_version)
            return
        pending.attempts += 1
        self.last_install_error = f"installed version did not change to {pending.version}"
        _log_update_event("update.install.failed", self.last_install_error, level="ERROR")
        if pending.attempts >= self.install_attempt_limit:
            self.pending_install = None

    @classmethod
    def load(cls, path: Path) -> "LocalUpdateState":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        pending_payload = payload.get("pending_install") if isinstance(payload, Mapping) else None
        pending = PendingInstall(**pending_payload) if isinstance(pending_payload, Mapping) else None
        return cls(
            last_seen_version=str(payload.get("last_seen_version") or ""),
            skipped_version=str(payload.get("skipped_version") or ""),
            pending_install=pending,
            last_install_error=str(payload.get("last_install_error") or ""),
            install_attempt_limit=int(payload.get("install_attempt_limit") or DEFAULT_INSTALL_ATTEMPT_LIMIT),
        )

    def save(self, path: Path) -> None:
        payload = asdict(self)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_update_state_path() -> Path:
    """Return the persisted updater state path used by GUI and helper handoff."""
    return user_cache_root() / "updates" / DEFAULT_UPDATE_STATE_NAME


def load_local_update_state(path: Path | None = None) -> LocalUpdateState:
    """Load rollback/skip/pending-install state without making callers know paths."""
    return LocalUpdateState.load(path or default_update_state_path())


def save_local_update_state(state: LocalUpdateState, path: Path | None = None) -> None:
    state.save(path or default_update_state_path())


def record_pending_install(
    *,
    version: str,
    installer_path: str | Path,
    log_path: str | Path,
    path: Path | None = None,
) -> LocalUpdateState:
    """Persist a single pending installer so startup can stop retry loops."""
    state_path = path or default_update_state_path()
    state = LocalUpdateState.load(state_path)
    state.pending_install = PendingInstall(
        version=str(version or ""),
        attempts=0,
        installer_path=str(installer_path),
        log_path=str(log_path),
    )
    state.save(state_path)
    _log_update_event("update.install.pending", "pending update recorded", version=version)
    return state


def record_skipped_update(version: str, path: Path | None = None) -> LocalUpdateState:
    """Persist the version the user chose to skip for automatic checks."""
    state_path = path or default_update_state_path()
    state = LocalUpdateState.load(state_path)
    state.skipped_version = _normalize_semver_text(str(version or ""))
    state.save(state_path)
    _log_update_event("update.check.skipped", "update version skipped", version=state.skipped_version)
    return state


def record_startup_update_health(
    *,
    current_version: str,
    path: Path | None = None,
    staging_dir: Path | None = None,
) -> LocalUpdateState:
    """Update pending-install state after app startup proves which version booted."""
    state_path = path or default_update_state_path()
    state = LocalUpdateState.load(state_path)
    state.record_startup_health(current_version=current_version, staging_dir=staging_dir)
    state.save(state_path)
    return state


@dataclass(frozen=True)
class UpdatePolicy:
    allowed: bool
    reason: str = ""
    mandatory: bool = False


class VersionPolicy:
    """Policy for SemVer updates, skipped versions and rollback defense."""

    def __init__(
        self,
        *,
        channel: str = DEFAULT_CHANNEL,
        state: LocalUpdateState | None = None,
        allow_downgrade: bool = False,
    ) -> None:
        self.channel = channel
        self.state = state or LocalUpdateState()
        self.allow_downgrade = allow_downgrade

    def evaluate(
        self,
        update_version: str,
        *,
        current_version: str,
        manual: bool = False,
        mandatory: bool = False,
    ) -> UpdatePolicy:
        try:
            candidate = SemVer.parse(update_version)
            SemVer.parse(current_version)
        except ValueError as exc:
            return UpdatePolicy(False, str(exc), mandatory=mandatory)
        if self.channel == "stable" and candidate.prerelease:
            return UpdatePolicy(False, "stable channel excludes prerelease updates", mandatory=mandatory)
        if compare_semver(update_version, current_version) <= 0 and not self.allow_downgrade:
            return UpdatePolicy(False, "candidate version is not newer than current version", mandatory=mandatory)
        if self.state.last_seen_version and compare_semver(update_version, self.state.last_seen_version) < 0 and not self.allow_downgrade:
            return UpdatePolicy(False, "candidate version is lower than last seen version", mandatory=mandatory)
        if self.state.skipped_version and compare_semver(update_version, self.state.skipped_version) == 0 and not manual and not mandatory:
            return UpdatePolicy(False, "candidate version was skipped", mandatory=mandatory)
        self.state.last_seen_version = _normalize_semver_text(update_version)
        return UpdatePolicy(True, mandatory=mandatory)


@dataclass(frozen=True)
class ManifestLocations:
    manifest_url: str = ""
    signature_url: str = ""
    etag: str = ""
    last_modified: str = ""
    not_modified: bool = False
    release_url: str = ""
    tag_name: str = ""
    release_name: str = ""


class GitHubReleaseClient:
    """GitHub release metadata client with cache validators and no credentials."""

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        cache_path: Path | None = None,
        api_base: str = "https://api.github.com",
        user_agent: str = "UniversalCrawlerPro/update-check",
        timeout: float = 8.0,
        auto_check_interval_seconds: int = DEFAULT_AUTO_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.cache_path = cache_path or user_cache_root() / "updates" / "github_release_cache.json"
        self.api_base = api_base.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.auto_check_interval_seconds = int(auto_check_interval_seconds)

    def http_error(self, url: str, code: int, message: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(url, code, message, hdrs=None, fp=None)

    def fetch_manifest_locations(
        self,
        *,
        opener: Callable[[urllib.request.Request, float], Any] = urllib.request.urlopen,
        manual: bool = False,
    ) -> ManifestLocations:
        cache = self._load_cache()
        if not manual and self._is_auto_check_throttled(cache):
            _log_update_event("update.check.throttled", "automatic update check throttled")
            return ManifestLocations(
                etag=str(cache.get("etag") or ""),
                last_modified=str(cache.get("last_modified") or ""),
                not_modified=True,
                release_url=str(cache.get("release_url") or ""),
            )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if cache.get("etag"):
            headers["If-None-Match"] = str(cache["etag"])
        if cache.get("last_modified"):
            headers["If-Modified-Since"] = str(cache["last_modified"])
        url = f"{self.api_base}/repos/{self.owner}/{self.repo}/releases/latest"
        request = urllib.request.Request(url, headers=headers)
        _log_update_event("update.check.started", "checking GitHub release", manual=manual)
        try:
            with opener(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
                etag = str(getattr(response, "headers", {}).get("ETag") or "")
                last_modified = str(getattr(response, "headers", {}).get("Last-Modified") or "")
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return ManifestLocations(not_modified=True, etag=str(cache.get("etag") or ""), last_modified=str(cache.get("last_modified") or ""))
            if exc.code in {403, 429}:
                raise DownloadError("GitHub rate limit reached") from exc
            if exc.code == 404:
                raise DownloadError("GitHub release was not found") from exc
            if exc.code >= 500:
                raise DownloadError("GitHub release service is temporarily unavailable") from exc
            raise DownloadError(f"GitHub release request failed with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise DownloadError(f"GitHub release request failed: {exc}") from exc
        if not isinstance(data, Mapping):
            raise DownloadError("GitHub release response had an unexpected shape")
        locations = self._locations_from_release(data, etag=etag, last_modified=last_modified)
        self._save_cache(
            {
                "etag": locations.etag,
                "last_modified": locations.last_modified,
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "release_url": locations.release_url,
            }
        )
        return locations

    def fetch_manifest_location_candidates(
        self,
        *,
        opener: Callable[[urllib.request.Request, float], Any] = urllib.request.urlopen,
        manual: bool = False,
        per_page: int = 10,
    ) -> tuple[ManifestLocations, ...]:
        """Return signed-manifest locations from recent releases, newest first."""

        cache = self._load_cache()
        if not manual and self._is_auto_check_throttled(cache):
            _log_update_event("update.check.throttled", "automatic update check throttled")
            return (
                ManifestLocations(
                    etag=str(cache.get("etag") or ""),
                    last_modified=str(cache.get("last_modified") or ""),
                    not_modified=True,
                    release_url=str(cache.get("release_url") or ""),
                ),
            )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if cache.get("etag"):
            headers["If-None-Match"] = str(cache["etag"])
        if cache.get("last_modified"):
            headers["If-Modified-Since"] = str(cache["last_modified"])
        page_size = max(1, min(100, int(per_page)))
        url = f"{self.api_base}/repos/{self.owner}/{self.repo}/releases?per_page={page_size}"
        request = urllib.request.Request(url, headers=headers)
        _log_update_event("update.check.started", "checking GitHub release candidates", manual=manual)
        try:
            with opener(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
                etag = str(getattr(response, "headers", {}).get("ETag") or "")
                last_modified = str(getattr(response, "headers", {}).get("Last-Modified") or "")
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return (
                    ManifestLocations(
                        not_modified=True,
                        etag=str(cache.get("etag") or ""),
                        last_modified=str(cache.get("last_modified") or ""),
                    ),
                )
            if exc.code in {403, 429}:
                raise DownloadError("GitHub rate limit reached") from exc
            if exc.code == 404:
                raise DownloadError("GitHub releases were not found") from exc
            if exc.code >= 500:
                raise DownloadError("GitHub release service is temporarily unavailable") from exc
            raise DownloadError(f"GitHub release request failed with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise DownloadError(f"GitHub release request failed: {exc}") from exc
        if not isinstance(data, list):
            raise DownloadError("GitHub releases response had an unexpected shape")
        locations: list[ManifestLocations] = []
        for release in data:
            if not isinstance(release, Mapping):
                continue
            try:
                locations.append(self._locations_from_release(release, etag=etag, last_modified=last_modified))
            except DownloadError:
                continue
        if not locations:
            raise DownloadError("GitHub releases do not contain signed update manifests")
        self._save_cache(
            {
                "etag": etag,
                "last_modified": last_modified,
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "release_url": locations[0].release_url,
            }
        )
        return tuple(locations)

    def _locations_from_release(self, data: Mapping[str, Any], *, etag: str, last_modified: str) -> ManifestLocations:
        manifest_url = ""
        sig_url = ""
        for asset in data.get("assets") or ():
            if not isinstance(asset, Mapping):
                continue
            name = str(asset.get("name") or "")
            browser_url = str(asset.get("browser_download_url") or "")
            if name == DEFAULT_MANIFEST_NAME:
                manifest_url = browser_url
            elif name == DEFAULT_SIGNATURE_NAME:
                sig_url = browser_url
        if not manifest_url or not sig_url:
            raise DownloadError("GitHub release does not contain latest.json and latest.json.sig")
        return ManifestLocations(
            manifest_url=manifest_url,
            signature_url=sig_url,
            etag=etag,
            last_modified=last_modified,
            release_url=str(data.get("html_url") or ""),
            tag_name=str(data.get("tag_name") or ""),
            release_name=str(data.get("name") or ""),
        )

    def _load_cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, payload: Mapping[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_auto_check_throttled(self, cache: Mapping[str, Any]) -> bool:
        if self.auto_check_interval_seconds <= 0:
            return False
        last_check_at = str(cache.get("last_check_at") or "")
        if not last_check_at:
            return False
        try:
            checked_at = datetime.fromisoformat(last_check_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - checked_at).total_seconds() < self.auto_check_interval_seconds


class AssetSelector:
    """Select the exact update asset for this OS and CPU architecture."""

    def __init__(
        self,
        *,
        os_name: str | None = None,
        arch: str | None = None,
        installer_types: tuple[str, ...] | None = None,
        allowed_hosts: set[str] | frozenset[str] | None = None,
        development_mode: bool = False,
    ) -> None:
        self.os_name = normalize_os(os_name or sys.platform)
        self.arch = normalize_arch(arch or platform.machine())
        self.installer_types = tuple(installer_types or default_installer_types(self.os_name))
        self.allowed_hosts = frozenset(host.lower() for host in (allowed_hosts or DEFAULT_ALLOWED_HOSTS))
        self.development_mode = development_mode

    def select(self, manifest: UpdateManifest) -> UpdateAsset:
        hosts = self.allowed_hosts | frozenset(manifest.trusted_hosts)
        candidates = [
            asset
            for asset in manifest.assets.values()
            if normalize_os(asset.os) == self.os_name
            and normalize_arch(asset.arch) in {self.arch, "universal"}
            and asset.installer_type in self.installer_types
        ]
        if not candidates:
            raise ManifestError(f"no update asset for {self.os_name}-{self.arch}")
        for asset in candidates:
            validate_asset_url(asset.url, hosts, development_mode=self.development_mode)
        return candidates[0]


class Downloader:
    """Download a verified manifest asset into an update staging cache."""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        max_size_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        retries: int = 2,
        allowed_hosts: set[str] | frozenset[str] | None = None,
        development_mode: bool = False,
    ) -> None:
        self.cache_dir = cache_dir or user_cache_root() / "updates" / "staging"
        self.max_size_bytes = int(max_size_bytes)
        self.timeout_seconds = float(timeout_seconds)
        self.retries = max(0, int(retries))
        self.allowed_hosts = frozenset(host.lower() for host in (allowed_hosts or DEFAULT_ALLOWED_HOSTS))
        self.development_mode = bool(development_mode)

    def download(
        self,
        asset: UpdateAsset,
        *,
        opener: Callable[[urllib.request.Request, float], Any] = urllib.request.urlopen,
        cancel_event: Event | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> Path:
        validate_asset_url(asset.url, self.allowed_hosts, development_mode=self.development_mode)
        if asset.size <= 0:
            raise DownloadError("asset size must be positive")
        if asset.size > self.max_size_bytes:
            raise DownloadError("asset size exceeds configured maximum")
        target = self.cache_dir / sanitize_filename(asset.name)
        partial = target.with_name(target.name + ".partial")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        attempt = 0
        while True:
            try:
                return self._download_once(asset, target, partial, opener, cancel_event, progress_callback)
            except DownloadError as exc:
                if not exc.keep_partial:
                    partial.unlink(missing_ok=True)
                if cancel_event is not None and cancel_event.is_set():
                    raise
                if attempt >= self.retries:
                    raise
                attempt += 1

    def _download_once(
        self,
        asset: UpdateAsset,
        target: Path,
        partial: Path,
        opener: Callable[[urllib.request.Request, float], Any],
        cancel_event: Event | None,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> Path:
        hasher = hashlib.sha256()
        if target.exists():
            try:
                _verify_file_hash(target, asset)
                return target
            except VerificationError:
                target.unlink(missing_ok=True)

        resume_from = partial.stat().st_size if partial.exists() else 0
        if resume_from >= asset.size:
            if resume_from == asset.size:
                try:
                    _verify_file_hash(partial, asset)
                    os.replace(partial, target)
                    return target
                except VerificationError:
                    partial.unlink(missing_ok=True)
            else:
                partial.unlink(missing_ok=True)
            resume_from = 0

        downloaded = resume_from
        started = time.monotonic()
        headers = {"User-Agent": "UniversalCrawlerPro/updater"}
        if resume_from > 0:
            _hash_existing_partial(partial, hasher)
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(asset.url, headers=headers)
        _log_update_event("update.download.started", "download started", asset=asset.name, size=asset.size)
        try:
            with opener(request, timeout=self.timeout_seconds) as response, partial.open("ab" if resume_from else "wb") as handle:
                content_length = _header_int(getattr(response, "headers", {}), "Content-Length")
                if resume_from:
                    range_start = _content_range_start(getattr(response, "headers", {}))
                    if range_start != resume_from:
                        raise DownloadError("server did not honor resume range")
                    if content_length is not None and content_length != asset.size - resume_from:
                        raise DownloadError("Content-Length does not match remaining manifest size")
                elif content_length is not None and content_length != asset.size:
                    raise DownloadError("Content-Length does not match manifest size")
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadError("download was cancelled", keep_partial=True)
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > self.max_size_bytes or downloaded > asset.size:
                        raise DownloadError("download exceeded expected size")
                    hasher.update(chunk)
                    handle.write(chunk)
                    if progress_callback:
                        elapsed = max(0.001, time.monotonic() - started)
                        progress = {
                            "bytesDownloaded": downloaded,
                            "totalBytes": asset.size,
                            "percent": round(downloaded / asset.size * 100, 2),
                            "speed": downloaded / elapsed,
                            "state": "Downloading",
                        }
                        _log_update_event("update.download.progress", "download progress", **progress)
                        progress_callback(progress)
        except DownloadError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise DownloadError(f"download failed: {exc}", keep_partial=partial.exists()) from exc
        if downloaded != asset.size:
            raise DownloadError("downloaded size does not match manifest", keep_partial=True)
        digest = hasher.hexdigest()
        if digest.lower() != asset.sha256.lower():
            _log_update_event("update.verify.failed", "download hash mismatch", level="SECURITY", asset=asset.name)
            raise DownloadError("download sha256 does not match manifest")
        os.replace(partial, target)
        _log_update_event("update.download.completed", "download completed", asset=asset.name)
        return target


class PackageVerifier:
    """OS-level package signature verifier."""

    def __init__(
        self,
        *,
        os_name: str | None = None,
        trusted_publishers: list[str] | tuple[str, ...] = (),
        trusted_thumbprints: list[str] | tuple[str, ...] = (),
        verify_func: Callable[[Path, UpdateAsset], None] | None = None,
        run_func: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.os_name = normalize_os(os_name or sys.platform)
        self.trusted_publishers = tuple(trusted_publishers)
        self.trusted_thumbprints = tuple(_normalize_certificate_fingerprint(value) for value in trusted_thumbprints if str(value).strip())
        self._verify_func = verify_func
        self._run = run_func

    def verify(self, path: Path, asset: UpdateAsset) -> None:
        _verify_file_hash(path, asset)
        if self._verify_func:
            self._verify_func(path, asset)
            return
        if self.os_name == "windows":
            self._verify_windows(path)
        elif self.os_name == "macos":
            self._verify_macos(path, asset)
        else:
            return

    def _verify_windows(self, path: Path) -> None:
        if not self.trusted_thumbprints:
            raise VerificationError("Windows updater requires trusted thumbprint allowlist")
        script = (
            "$s=Get-AuthenticodeSignature -LiteralPath $args[0];"
            "$cert=$s.SignerCertificate;"
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "if ($null -eq $cert) {"
            "ConvertTo-Json @{Status=[string]$s.Status;Subject='';Thumbprint='';SHA256Fingerprint=''}; exit 0"
            "};"
            "$sha256=[System.BitConverter]::ToString("
            "[System.Security.Cryptography.SHA256]::Create().ComputeHash($cert.RawData)"
            ").Replace('-','');"
            "ConvertTo-Json @{"
            "Status=[string]$s.Status;"
            "Subject=[string]$cert.Subject;"
            "Thumbprint=[string]$cert.Thumbprint;"
            "SHA256Fingerprint=$sha256"
            "}"
        )
        result = self._run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
            capture_output=True,
            text=True,
            shell=False,
            timeout=20,
        )
        if result.returncode != 0:
            raise VerificationError("Authenticode verification command failed")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise VerificationError("Authenticode output was invalid") from exc
        if payload.get("Status") != "Valid":
            raise VerificationError("Authenticode signature is not valid")
        subject = str(payload.get("Subject") or "")
        thumbprints = {
            _normalize_certificate_fingerprint(payload.get("Thumbprint")),
            _normalize_certificate_fingerprint(payload.get("SHA256Fingerprint")),
        }
        if not any(value and value in self.trusted_thumbprints for value in thumbprints):
            raise VerificationError("Authenticode signer thumbprint is not trusted")
        if self.trusted_publishers and not any(publisher in subject for publisher in self.trusted_publishers):
            _log_update_event(
                "update.verify.publisher_unmatched",
                "Authenticode thumbprint matched but publisher allowlist did not",
                level="WARN",
            )
        return

    def _verify_macos(self, path: Path, asset: UpdateAsset) -> None:
        if not self.trusted_publishers:
            raise VerificationError("macOS updater requires trusted publisher allowlist")
        if asset.installer_type == "pkg":
            signature_result = self._run(["pkgutil", "--check-signature", str(path)], capture_output=True, text=True, shell=False, timeout=20)
            gatekeeper_result = self._run(["spctl", "-a", "-vv", "-t", "install", str(path)], capture_output=True, text=True, shell=False, timeout=20)
            results = (signature_result, gatekeeper_result)
        else:
            results = (self._run(["spctl", "-a", "-vv", "-t", "open", str(path)], capture_output=True, text=True, shell=False, timeout=20),)
        if any(result.returncode != 0 for result in results):
            raise VerificationError("macOS package signature check failed")
        output = "\n".join(f"{result.stdout}\n{result.stderr}" for result in results)
        if not any(publisher in output for publisher in self.trusted_publishers):
            raise VerificationError("macOS signer is not trusted")


@dataclass(frozen=True)
class InstallResult:
    exit_code: int
    succeeded: bool
    log_path: Path


class InstallerRunner:
    """Helper-side installer runner that only accepts verified packages."""

    def __init__(
        self,
        *,
        package_verifier: PackageVerifier,
        run_func: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.package_verifier = package_verifier
        self._run = run_func

    def run_verified_installer(self, path: Path, asset: UpdateAsset, *, version: str, log_path: Path | None = None) -> InstallResult:
        self.package_verifier.verify(path, asset)
        log_path = log_path or user_logs_root() / f"update_install_{sanitize_filename(version)}.log"
        argv = self._install_argv(path, asset, log_path)
        _log_update_event("update.install.started", "installer started", version=version, installer=asset.name)
        result = self._run(argv, shell=False, timeout=None)
        succeeded = result.returncode == 0
        _log_update_event(
            "update.install.exit",
            "installer exited",
            level="INFO" if succeeded else "ERROR",
            version=version,
            exit_code=result.returncode,
        )
        return InstallResult(exit_code=int(result.returncode), succeeded=succeeded, log_path=log_path)

    @staticmethod
    def _install_argv(path: Path, asset: UpdateAsset, log_path: Path) -> list[str]:
        os_name = normalize_os(asset.os)
        installer_type = asset.installer_type.lower()
        if os_name == "windows" and installer_type == "msi":
            return ["msiexec.exe", "/i", str(path), "/passive", "/norestart", "/L*v", str(log_path)]
        if os_name == "windows" and installer_type == "inno":
            return [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log_path}"]
        if os_name == "windows" and installer_type == "nsis":
            return [str(path), "/S"]
        if os_name == "macos" and installer_type == "pkg":
            return ["/usr/sbin/installer", "-pkg", str(path), "-target", "/"]
        if os_name == "linux" and installer_type == "appimage":
            raise InstallError("AppImage updates require the updater helper symlink switch path")
        raise InstallError(f"unsupported installer type: {asset.os}/{asset.installer_type}")


def write_update_asset_descriptor(installer_path: Path, asset: UpdateAsset) -> Path:
    """Persist the verified asset metadata passed from GUI to updater helper."""

    descriptor_path = Path(installer_path).with_name(f"{Path(installer_path).name}.asset.json")
    descriptor_path.write_text(
        json.dumps(
            {
                "name": asset.name,
                "url": asset.url,
                "sha256": asset.sha256,
                "size": asset.size,
                "installerType": asset.installer_type,
                "os": asset.os,
                "arch": asset.arch,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return descriptor_path


def _parse_rfc3339(value: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ManifestError(f"invalid datetime: {value!r}") from exc


def _validate_asset_shape(asset: UpdateAsset) -> None:
    if not asset.name or Path(asset.name).name != asset.name:
        raise ManifestError("asset name is missing or unsafe")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", asset.sha256 or ""):
        raise ManifestError("asset sha256 must be a 64-character hex digest")
    if asset.size <= 0:
        raise ManifestError("asset size must be positive")
    if normalize_os(asset.os) not in {"windows", "macos", "linux"}:
        raise ManifestError("asset os is not supported")
    if normalize_arch(asset.arch) not in {"x64", "arm64", "universal"}:
        raise ManifestError("asset arch is not supported")
    if not asset.installer_type:
        raise ManifestError("asset installerType is missing")


def _normalize_semver_text(value: str) -> str:
    version = SemVer.parse(value)
    text = f"{version.major}.{version.minor}.{version.patch}"
    if version.prerelease:
        text += "-" + ".".join(version.prerelease)
    if version.build:
        text += "+" + version.build
    return text


def normalize_os(value: Any) -> str:
    raw = str(value or "").lower()
    if raw.startswith("win") or raw == "windows":
        return "windows"
    if raw in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    return raw


def normalize_arch(value: Any) -> str:
    raw = str(value or "").lower().replace("amd64", "x64").replace("x86_64", "x64")
    if raw in {"aarch64", "arm64"}:
        return "arm64"
    if raw in {"universal", "universal2"}:
        return "universal"
    return raw


def _normalize_certificate_fingerprint(value: Any) -> str:
    """Normalize SHA1/SHA256 certificate fingerprints from Windows tooling."""
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def default_installer_types(os_name: str) -> tuple[str, ...]:
    if os_name == "windows":
        return ("msi", "inno", "nsis", "exe")
    if os_name == "macos":
        return ("pkg", "dmg")
    if os_name == "linux":
        return ("AppImage", "deb", "rpm", "appimage")
    return ()


def validate_asset_url(url: str, allowed_hosts: set[str] | frozenset[str], *, development_mode: bool = False) -> None:
    parsed = urllib.parse.urlparse(str(url or ""))
    if development_mode and parsed.scheme in {"file", "http", "https"}:
        return
    if parsed.scheme != "https":
        raise ManifestError("asset URL must use https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ManifestError("asset URL host is missing")
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ManifestError("asset URL must not point to localhost")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ManifestError("asset URL must not use a bare IP address")
    if host not in allowed_hosts:
        raise ManifestError(f"asset URL host is not trusted: {host}")


def sanitize_filename(name: str) -> str:
    value = Path(str(name or "")).name
    value = re.sub(r"[^0-9A-Za-z._() -]+", "_", value).strip(" .")
    if not value:
        raise DownloadError("asset filename is empty")
    return value


def _header_int(headers: Any, name: str) -> int | None:
    value = None
    if isinstance(headers, Mapping):
        value = headers.get(name) or headers.get(name.lower())
    else:
        getter = getattr(headers, "get", None)
        if callable(getter):
            value = getter(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _header_value(headers: Any, name: str) -> str:
    if isinstance(headers, Mapping):
        value = headers.get(name) or headers.get(name.lower())
    else:
        getter = getattr(headers, "get", None)
        value = getter(name) if callable(getter) else None
    return str(value or "")


def _content_range_start(headers: Any) -> int | None:
    value = _header_value(headers, "Content-Range")
    match = re.match(r"(?:bytes\s+(\d+)-\d+/\d+|\*)", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _hash_existing_partial(path: Path, hasher: Any) -> None:
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)


def _verify_file_hash(path: Path, asset: UpdateAsset) -> None:
    file_path = Path(path)
    if file_path.stat().st_size != asset.size:
        raise VerificationError("installer size does not match manifest")
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 512), b""):
            hasher.update(chunk)
    if hasher.hexdigest().lower() != asset.sha256.lower():
        raise VerificationError("installer hash does not match manifest")


def _log_update_event(event: str, message: str, *, level: str = "INFO", **details: Any) -> None:
    safe_details = {key: value for key, value in details.items() if "token" not in key.lower() and "secret" not in key.lower()}
    debug_logger.log(
        component="Updater",
        action=event,
        message=message,
        level=level,
        status_code=event,
        details=safe_details,
    )


def log_update_event(event: str, message: str, *, level: str = "INFO", **details: Any) -> None:
    """Record a structured updater event while reusing updater sanitization."""
    _log_update_event(event, message, level=level, **details)
