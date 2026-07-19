"""桌面端安全更新基础能力。

更新发现、安装包验证和安装器启动均与 GUI 隔离。模块不保存 GitHub 凭据；
下载产物只有通过 Ed25519 签名 manifest 约束及配置的平台签名策略后才可执行。
"""

from __future__ import annotations

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
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from threading import Event
from typing import Any, Callable, Mapping

# ``Crypto`` 来自仍在维护的 PyCryptodome，而不是已停止维护的 PyCrypto。
from Crypto.PublicKey import ECC  # nosec B413
from Crypto.Signature import eddsa  # nosec B413
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

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
DEFAULT_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_RELEASE_FEED_BYTES = 2_000_000
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30.0
DEFAULT_INSTALL_ATTEMPT_LIMIT = 2
UrlOpener = Callable[..., Any]


class TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """在 urllib 跟随 30x 之前验证目标，阻断更新链路的重定向 SSRF。"""

    def __init__(
        self,
        allowed_hosts: set[str] | frozenset[str],
        *,
        development_mode: bool = False,
    ) -> None:
        super().__init__()
        self.allowed_hosts = frozenset(str(host).lower() for host in allowed_hosts)
        self.development_mode = bool(development_mode)

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_asset_url(newurl, self.allowed_hosts, development_mode=self.development_mode)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_trusted_url(
    request: urllib.request.Request,
    *,
    timeout: float,
    allowed_hosts: set[str] | frozenset[str],
    development_mode: bool = False,
) -> Any:
    """打开受信 URL，并把同一策略应用到每一次 HTTP 重定向。"""

    validate_asset_url(request.full_url, allowed_hosts, development_mode=development_mode)
    opener = urllib.request.build_opener(
        TrustedRedirectHandler(allowed_hosts, development_mode=development_mode)
    )
    return opener.open(request, timeout=timeout)


def _response_final_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    return str(getter() if callable(getter) else fallback)


def _atomic_write_text(path: Path, content: str) -> None:
    """在目标目录写入并 fsync 临时文件，再原子替换，避免暴露半写 JSON。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
DEFAULT_UPDATE_STATE_NAME = "state.json"
DEFAULT_AUTO_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


class ManifestError(RuntimeError):
    """签名 manifest 缺失、无效或违反安全约束。"""


class DownloadError(RuntimeError):
    """更新下载、GitHub API 或 staging 失败。"""

    def __init__(self, message: str, *, keep_partial: bool = False) -> None:
        super().__init__(message)
        self.keep_partial = bool(keep_partial)


class MetadataNotFoundError(DownloadError):
    """Release 未发布 latest.json 或对应签名。"""


class VerificationError(RuntimeError):
    """安装包完整性或平台签名验证失败。"""


class InstallError(RuntimeError):
    """已验证安装包无法按当前平台策略启动。"""


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
    for left_part, right_part in zip(left, right, strict=False):
        left_num = left_part.isdigit()
        right_num = right_part.isdigit()
        if left_num and right_num:
            left_number, right_number = int(left_part), int(right_part)
            if left_number < right_number:
                return -1
            if left_number > right_number:
                return 1
            continue
        if left_num:
            return -1
        if right_num:
            return 1
        if left_part < right_part:
            return -1
        if left_part > right_part:
            return 1
    if len(left) < len(right):
        return -1
    if len(left) > len(right):
        return 1
    return 0


def compare_semver(left: Any, right: Any) -> int:
    """按 SemVer 数值和预发布规则比较，避免字符串字典序误判。"""

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
    """先验 Ed25519 原文签名，再约束 manifest 的 schema、应用、通道和有效期。"""

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
        # 必须对原始 bytes 验签后再解析 JSON，解析或重编码结果不能替代签名原文。
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


def _state_semver(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return _normalize_semver_text(raw)
    except ValueError:
        return ""


def _state_int(value: Any, *, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


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
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

    @classmethod
    def load(cls, path: Path) -> "LocalUpdateState":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(payload, Mapping):
            return cls()
        pending_payload = payload.get("pending_install")
        pending = None
        if isinstance(pending_payload, Mapping):
            pending_version = _state_semver(pending_payload.get("version"))
            if pending_version:
                pending = PendingInstall(
                    version=pending_version,
                    attempts=_state_int(pending_payload.get("attempts"), default=0),
                    installer_path=str(pending_payload.get("installer_path") or ""),
                    log_path=str(pending_payload.get("log_path") or ""),
                )
        return cls(
            last_seen_version=_state_semver(payload.get("last_seen_version")),
            skipped_version=_state_semver(payload.get("skipped_version")),
            pending_install=pending,
            last_install_error=str(payload.get("last_install_error") or ""),
            install_attempt_limit=_state_int(
                payload.get("install_attempt_limit"),
                default=DEFAULT_INSTALL_ATTEMPT_LIMIT,
                minimum=1,
            ),
        )

    def save(self, path: Path) -> None:
        payload = asdict(self)
        _atomic_write_text(Path(path), json.dumps(payload, ensure_ascii=False, indent=2))


def default_update_state_path() -> Path:
    """返回 GUI 与 updater helper 交接时共用的持久化状态路径。"""
    return user_cache_root() / "updates" / DEFAULT_UPDATE_STATE_NAME


def default_update_staging_dir() -> Path:
    """返回断点文件和已验证更新包共用的 staging 缓存目录。"""
    return user_cache_root() / "updates" / "staging"


def load_local_update_state(path: Path | None = None) -> LocalUpdateState:
    """加载回滚防护、跳过版本和待安装状态，并隐藏默认路径约定。"""
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
    """只持久化一个待安装版本，使启动健康检查能限制失败重试次数。"""
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
    """记录用户跳过的版本；手动检查和 mandatory 更新仍由 VersionPolicy 决定。"""
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
    """启动后以实际运行版本确认安装结果；未切换版本会累计尝试并最终停止重试。"""
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
    """统一处理 SemVer 通道、跳过版本和低于 last_seen_version 的回滚防护。"""

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
    """无凭据读取 GitHub release 元数据，并用 ETag/Last-Modified 控制缓存请求。"""

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
        return urllib.error.HTTPError(url, code, message, hdrs=Message(), fp=None)

    def fetch_manifest_locations(
        self,
        *,
        opener: UrlOpener | None = None,
        manual: bool = False,
    ) -> ManifestLocations:
        effective_opener = opener or self._trusted_opener()
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
            with effective_opener(request, timeout=self.timeout) as response:
                validate_asset_url(_response_final_url(response, url), {"api.github.com"})
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
                etag = str(getattr(response, "headers", {}).get("ETag") or "")
                last_modified = str(getattr(response, "headers", {}).get("Last-Modified") or "")
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return ManifestLocations(not_modified=True, etag=str(cache.get("etag") or ""), last_modified=str(cache.get("last_modified") or ""))
            if exc.code in {403, 429}:
                _log_update_event(
                    "update.check.api_rate_limited",
                    "GitHub API rate limited; falling back to the public release feed",
                    level="WARN",
                )
                return self._fetch_manifest_locations_from_atom(opener=effective_opener, per_page=1)[0]
            if exc.code == 404:
                raise DownloadError("GitHub release was not found") from exc
            if exc.code >= 500:
                raise DownloadError("GitHub release service is temporarily unavailable") from exc
            raise DownloadError(f"GitHub release request failed with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ManifestError) as exc:
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
        opener: UrlOpener | None = None,
        manual: bool = False,
        per_page: int = 10,
    ) -> tuple[ManifestLocations, ...]:
        """按新到旧返回近期 Release 中的签名 manifest 地址。"""

        effective_opener = opener or self._trusted_opener()
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
            with effective_opener(request, timeout=self.timeout) as response:
                validate_asset_url(_response_final_url(response, url), {"api.github.com"})
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
                _log_update_event(
                    "update.check.api_rate_limited",
                    "GitHub API rate limited; falling back to the public release feed",
                    level="WARN",
                )
                return self._fetch_manifest_locations_from_atom(opener=effective_opener, per_page=page_size)
            if exc.code == 404:
                raise DownloadError("GitHub releases were not found") from exc
            if exc.code >= 500:
                raise DownloadError("GitHub release service is temporarily unavailable") from exc
            raise DownloadError(f"GitHub release request failed with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ManifestError) as exc:
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
            raise MetadataNotFoundError("GitHub releases do not contain signed update manifests")
        self._save_cache(
            {
                "etag": etag,
                "last_modified": last_modified,
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "release_url": locations[0].release_url,
            }
        )
        return tuple(locations)

    @staticmethod
    def _trusted_opener() -> UrlOpener:
        allowed_hosts = frozenset({"api.github.com", "github.com"})

        def opener(request: urllib.request.Request, *, timeout: float) -> Any:
            return open_trusted_url(request, timeout=timeout, allowed_hosts=allowed_hosts)

        return opener

    def _fetch_manifest_locations_from_atom(
        self,
        *,
        opener: Callable[..., Any],
        per_page: int,
    ) -> tuple[ManifestLocations, ...]:
        """通过 Atom 发现 release tag，避免消耗 GitHub REST API 限额。

        Atom 只提供 release 身份；下载后的 manifest 仍走正常 Ed25519 验证，
        因而该降级路径不会扩大安装信任边界。
        """

        feed_url = f"https://github.com/{self.owner}/{self.repo}/releases.atom"
        request = urllib.request.Request(feed_url, headers={"User-Agent": self.user_agent})
        try:
            with opener(request, timeout=self.timeout) as response:
                validate_asset_url(_response_final_url(response, feed_url), {"github.com"})
                payload = response.read(DEFAULT_MAX_RELEASE_FEED_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"GitHub release feed failed with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError, ManifestError) as exc:
            raise DownloadError(f"GitHub release feed failed: {exc}") from exc
        if len(payload) > DEFAULT_MAX_RELEASE_FEED_BYTES:
            raise DownloadError("GitHub release feed is too large")
        try:
            # Atom 只承载 release tag，不需要 DTD/实体；拒绝这些特性可避免实体扩展攻击。
            root = DefusedET.fromstring(payload)
        except DefusedXmlException as exc:
            raise DownloadError(f"GitHub release feed contains unsafe XML: {exc}") from exc
        except ET.ParseError as exc:
            raise DownloadError(f"GitHub release feed failed: {exc}") from exc

        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        expected_prefix = f"/{self.owner}/{self.repo}/releases/tag/"
        locations: list[ManifestLocations] = []
        for entry in root.findall("atom:entry", namespace):
            release_url = ""
            for link in entry.findall("atom:link", namespace):
                if str(link.attrib.get("rel") or "alternate") == "alternate":
                    release_url = str(link.attrib.get("href") or "")
                    break
            parsed = urllib.parse.urlparse(release_url)
            if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith(expected_prefix):
                continue
            tag_name = urllib.parse.unquote(parsed.path[len(expected_prefix) :]).strip("/")
            if not tag_name:
                continue
            encoded_tag = urllib.parse.quote(tag_name, safe="")
            download_base = f"https://github.com/{self.owner}/{self.repo}/releases/download/{encoded_tag}"
            locations.append(
                ManifestLocations(
                    manifest_url=f"{download_base}/{DEFAULT_MANIFEST_NAME}",
                    signature_url=f"{download_base}/{DEFAULT_SIGNATURE_NAME}",
                    release_url=release_url,
                    tag_name=tag_name,
                    release_name=str(entry.findtext("atom:title", default="", namespaces=namespace) or ""),
                )
            )
            if len(locations) >= per_page:
                break
        if not locations:
            raise DownloadError("GitHub release feed did not contain release tags")
        self._save_cache(
            {
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
            raise MetadataNotFoundError("GitHub release does not contain latest.json and latest.json.sig")
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
        _atomic_write_text(
            self.cache_path,
            json.dumps(dict(payload), ensure_ascii=False, indent=2),
        )

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
    """只选择与当前 OS、CPU 架构和安装器类型完全匹配的 manifest 资产。"""

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
    """按已验签 manifest 的 URL、size 和 SHA-256 下载到 staging 缓存。"""

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
        self.cache_dir = cache_dir or default_update_staging_dir()
        self.max_size_bytes = int(max_size_bytes)
        self.timeout_seconds = float(timeout_seconds)
        self.retries = max(0, int(retries))
        self.allowed_hosts = frozenset(host.lower() for host in (allowed_hosts or DEFAULT_ALLOWED_HOSTS))
        self.development_mode = bool(development_mode)

    def download(
        self,
        asset: UpdateAsset,
        *,
        opener: UrlOpener | None = None,
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
        effective_opener = opener or self._trusted_opener()
        attempt = 0
        while True:
            try:
                return self._download_once(asset, target, partial, effective_opener, cancel_event, progress_callback)
            except ManifestError as exc:
                partial.unlink(missing_ok=True)
                raise DownloadError(f"download redirect was rejected: {exc}") from exc
            except DownloadError as exc:
                if not exc.keep_partial:
                    partial.unlink(missing_ok=True)
                if cancel_event is not None and cancel_event.is_set():
                    raise
                if attempt >= self.retries:
                    raise
                attempt += 1

    def _trusted_opener(self) -> UrlOpener:
        def opener(request: urllib.request.Request, *, timeout: float) -> Any:
            return open_trusted_url(
                request,
                timeout=timeout,
                allowed_hosts=self.allowed_hosts,
                development_mode=self.development_mode,
            )

        return opener

    def _download_once(
        self,
        asset: UpdateAsset,
        target: Path,
        partial: Path,
        opener: UrlOpener,
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
                        progress: dict[str, Any] = {
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
        # 只有大小和 SHA-256 都与已验签 manifest 一致，partial 才能晋升为可复用安装包。
        os.replace(partial, target)
        _log_update_event("update.download.completed", "download completed", asset=asset.name)
        return target


class PackageVerifier:
    """校验安装包完整性，并按发布策略追加操作系统签名校验。"""

    def __init__(
        self,
        *,
        os_name: str | None = None,
        trusted_publishers: list[str] | tuple[str, ...] = (),
        trusted_thumbprints: list[str] | tuple[str, ...] = (),
        require_os_signature: bool = True,
        verify_func: Callable[[Path, UpdateAsset], None] | None = None,
        run_func: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.os_name = normalize_os(os_name or sys.platform)
        self.trusted_publishers = tuple(trusted_publishers)
        self.trusted_thumbprints = tuple(
            _normalize_certificate_fingerprint(value)
            for value in trusted_thumbprints
            if str(value).strip()
        )
        self.require_os_signature = bool(require_os_signature)
        self._verify_func = verify_func
        self._run = run_func

    def verify(self, path: Path, asset: UpdateAsset) -> None:
        # 哈希来自 Ed25519 签名清单。暂缓 Authenticode 时也必须先证明文件未被替换。
        _verify_file_hash(path, asset)
        if not self.require_os_signature:
            return
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
            raise VerificationError("Authenticode signer publisher is not trusted")
        return

    def _verify_macos(self, path: Path, asset: UpdateAsset) -> None:
        if not self.trusted_publishers:
            raise VerificationError("macOS updater requires trusted publisher allowlist")
        results: tuple[subprocess.CompletedProcess[Any], ...]
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
    """updater helper 侧的安装器入口；每次启动前都重新执行 PackageVerifier。"""

    def __init__(
        self,
        *,
        package_verifier: PackageVerifier,
        run_func: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen_func: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.package_verifier = package_verifier
        self._run = run_func
        self._popen = popen_func

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

    def launch_verified_installer(
        self,
        path: Path,
        asset: UpdateAsset,
        *,
        version: str,
        log_path: Path,
        install_dir: Path,
        restart_handoff_path: Path | None,
    ) -> subprocess.Popen:
        """验证后异步启动会覆盖当前安装目录的 Inno 安装器。

        updater helper 本身也位于安装目录。若在 helper 内同步等待安装器，
        Windows Restart Manager 会要求 helper 退出，而 helper 又在等待安装器，
        最终形成死锁。这里仅完成最后一次校验与进程交接，让 helper 随即退出；
        安装成功后的重启由 Inno 调用新版本 helper 完成。
        """

        if normalize_os(asset.os) != "windows" or asset.installer_type.lower() != "inno":
            raise InstallError("detached self-update currently requires a Windows Inno installer")
        self.package_verifier.verify(path, asset)
        argv = self._install_argv(
            path,
            asset,
            log_path,
            install_dir=install_dir,
            restart_handoff_path=restart_handoff_path,
        )
        _log_update_event(
            "update.install.started",
            "installer started",
            version=version,
            installer=asset.name,
            detached=True,
        )
        process_kwargs: dict[str, Any] = {"shell": False, "close_fds": True}
        if os.name == "nt":
            process_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = self._popen(argv, **process_kwargs)
        _log_update_event(
            "update.install.handoff",
            "installer process detached from updater helper",
            version=version,
            installer_pid=getattr(process, "pid", 0),
        )
        return process

    @staticmethod
    def _install_argv(
        path: Path,
        asset: UpdateAsset,
        log_path: Path,
        *,
        install_dir: Path | None = None,
        restart_handoff_path: Path | None = None,
    ) -> list[str]:
        os_name = normalize_os(asset.os)
        installer_type = asset.installer_type.lower()
        if os_name == "windows" and installer_type == "msi":
            return ["msiexec.exe", "/i", str(path), "/passive", "/norestart", "/L*v", str(log_path)]
        if os_name == "windows" and installer_type == "inno":
            argv = [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log_path}"]
            if install_dir is not None:
                argv.append(f"/DIR={install_dir}")
            if restart_handoff_path is not None:
                argv.append(f"/UCrawlRestartHandoff={restart_handoff_path}")
            return argv
        if os_name == "windows" and installer_type == "nsis":
            return [str(path), "/S"]
        if os_name == "macos" and installer_type == "pkg":
            return ["/usr/sbin/installer", "-pkg", str(path), "-target", "/"]
        if os_name == "linux" and installer_type == "appimage":
            raise InstallError("AppImage updates require the updater helper symlink switch path")
        raise InstallError(f"unsupported installer type: {asset.os}/{asset.installer_type}")


def write_update_asset_descriptor(installer_path: Path, asset: UpdateAsset) -> Path:
    """原子保存 GUI 交给 updater helper 的已验证资产描述。"""

    descriptor_path = Path(installer_path).with_name(f"{Path(installer_path).name}.asset.json")
    _atomic_write_text(
        descriptor_path,
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
    """去掉 Windows 工具输出中的分隔符，统一 SHA1/SHA256 证书指纹格式。"""
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def default_installer_types(os_name: str) -> tuple[str, ...]:
    if os_name == "windows":
        return ("msi", "inno", "nsis", "exe")
    if os_name == "macos":
        return ("pkg", "dmg")
    if os_name == "linux":
        return ("AppImage", "deb", "rpm", "appimage")
    return ()


def _is_local_development_asset_url(parsed: urllib.parse.ParseResult) -> bool:
    """开发模式只放行 file 或 loopback 资源，不能借该开关绕过 SSRF 边界。"""
    if parsed.scheme == "file":
        return (parsed.netloc or "").lower() in {"", "localhost"} and bool(parsed.path)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_asset_url(url: str, allowed_hosts: set[str] | frozenset[str], *, development_mode: bool = False) -> None:
    """生产 URL 必须使用 HTTPS 且命中 host 白名单；裸 IP 与 localhost 一律拒绝。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    if development_mode and _is_local_development_asset_url(parsed):
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


_SENSITIVE_UPDATE_DETAIL_MARKERS = (
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "sessionkey",
    "token",
)


def _is_sensitive_update_detail_key(key: Any) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", str(key or "").lower())
    return any(marker in compact for marker in _SENSITIVE_UPDATE_DETAIL_MARKERS)


def _log_update_event(event: str, message: str, *, level: str = "INFO", **details: Any) -> None:
    safe_details = {
        key: value
        for key, value in details.items()
        if not _is_sensitive_update_detail_key(key)
    }
    debug_logger.log(
        component="Updater",
        action=event,
        message=message,
        level=level,
        status_code=event,
        details=safe_details,
    )


def log_update_event(event: str, message: str, *, level: str = "INFO", **details: Any) -> None:
    """复用更新日志脱敏规则记录结构化事件，避免凭据字段进入调试日志。"""
    _log_update_event(event, message, level=level, **details)
