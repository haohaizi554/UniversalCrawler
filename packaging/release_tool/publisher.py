"""Idempotent, pinned GitHub CLI operations for release assets."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from shared.release_identity import parse_release_tag

from .events import redact_release_text
from .upload_transport import GitHubAssetUploadTransport, UploadTransportError


GITHUB_HOST = "github.com"
DEFAULT_METADATA_TIMEOUT_SECONDS = 60.0
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 2 * 60 * 60.0
_METADATA_RETRY_DELAYS_SECONDS = (1.0, 2.0)
_UPLOAD_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_TRANSIENT_HTTP_STATUS_PATTERN = re.compile(
    r"\bHTTP(?:/\S+)?\s+(?:408|425|500|502|503|504)\b",
    re.IGNORECASE,
)
_TRANSIENT_GITHUB_FAILURE_FRAGMENTS = (
    "connection refused",
    "connection reset by peer",
    "connection was forcibly closed",
    "context deadline exceeded",
    "error connecting to api.github.com",
    "i/o timeout",
    "proxyconnect tcp",
    "read tcp",
    "temporary failure",
    "tls handshake timeout",
    "unexpected eof",
    "wsarecv",
)


class PublishError(RuntimeError):
    """Raised when a GitHub publication operation cannot be completed safely."""


@dataclass(frozen=True)
class ReleaseAssetInfo:
    """The metadata required to identify one release asset unambiguously."""

    name: str
    size: int
    digest: str = ""

    def __post_init__(self) -> None:
        if not self.name or Path(self.name).name != self.name:
            raise ValueError("release asset name must be a file name")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("release asset size must be a non-negative integer")
        if self.digest:
            object.__setattr__(self, "digest", _normalise_digest(self.digest))

    @classmethod
    def from_path(cls, path: str | Path) -> "ReleaseAssetInfo":
        asset_path = _resolved_regular_file(path, label="release asset")
        before = _file_snapshot(asset_path)
        hasher = hashlib.sha256()
        unreadable = False
        try:
            with asset_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError:
            unreadable = True
        if unreadable:
            raise ValueError("release asset is not readable")
        if before != _file_snapshot(asset_path):
            raise ValueError("release asset changed while hashing")
        return cls(
            name=asset_path.name,
            size=before[2],
            digest=f"sha256:{hasher.hexdigest()}",
        )

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "ReleaseAssetInfo":
        name = payload.get("name")
        size = payload.get("size")
        digest = payload.get("digest", "")
        if not isinstance(name, str) or not isinstance(size, int):
            raise ValueError("release asset has invalid name or size")
        if not isinstance(digest, str):
            raise ValueError("release asset has invalid digest")
        return cls(name=name, size=size, digest=digest)

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "size": self.size, "digest": self.digest}


@dataclass(frozen=True)
class ReleaseUploadProgress:
    """Structured byte progress for one asset and the complete upload batch."""

    asset_name: str
    asset_index: int
    asset_count: int
    bytes_sent: int
    bytes_total: int
    overall_bytes_sent: int
    overall_bytes_total: int
    bytes_per_second: float
    attempt: int
    state: str
    retry_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        integer_values = (
            self.asset_index,
            self.asset_count,
            self.bytes_sent,
            self.bytes_total,
            self.overall_bytes_sent,
            self.overall_bytes_total,
            self.attempt,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_values):
            raise ValueError("upload progress counters must be integers")
        if self.asset_index < 1 or self.asset_count < self.asset_index or self.attempt < 1:
            raise ValueError("upload progress index is invalid")
        if min(self.bytes_sent, self.bytes_total, self.overall_bytes_sent, self.overall_bytes_total) < 0:
            raise ValueError("upload progress bytes must be non-negative")
        if self.bytes_sent > self.bytes_total or self.overall_bytes_sent > self.overall_bytes_total:
            raise ValueError("upload progress exceeds its total")
        if not math.isfinite(self.bytes_per_second) or self.bytes_per_second < 0:
            raise ValueError("upload speed must be finite and non-negative")
        if not math.isfinite(self.retry_delay_seconds) or self.retry_delay_seconds < 0:
            raise ValueError("upload retry delay must be finite and non-negative")
        if self.state not in {"uploading", "retrying", "completed", "recovered", "skipped"}:
            raise ValueError("upload progress state is invalid")

    def to_event_data(self) -> dict[str, object]:
        return {
            "asset_name": self.asset_name,
            "asset_index": self.asset_index,
            "asset_count": self.asset_count,
            "bytes_sent": self.bytes_sent,
            "bytes_total": self.bytes_total,
            "overall_bytes_sent": self.overall_bytes_sent,
            "overall_bytes_total": self.overall_bytes_total,
            "bytes_per_second": self.bytes_per_second,
            "attempt": self.attempt,
            "state": self.state,
            "retry_delay_seconds": self.retry_delay_seconds,
        }


@dataclass(frozen=True)
class _LocalAsset:
    path: Path
    info: ReleaseAssetInfo
    snapshot: tuple[int, int, int, int]


@dataclass(frozen=True)
class _RemoteAsset:
    info: ReleaseAssetInfo
    asset_id: int | None = None
    state: str = "uploaded"


class GitHubReleasePublisher:
    """Publish prebuilt artifacts through GitHub.com without leaking credentials."""

    def __init__(
        self,
        repository: str,
        environment: Mapping[str, str],
        output: Callable[[str], None],
        *,
        run_process: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        project_root: str | Path | None = None,
        metadata_timeout_seconds: float = DEFAULT_METADATA_TIMEOUT_SECONDS,
        upload_timeout_seconds: float = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
        upload_request: Callable[[str, Path, Callable[[int, int, float], None]], None]
        | None = None,
        upload_progress: Callable[[ReleaseUploadProgress], None] | None = None,
    ) -> None:
        owner, name = _repository_components(repository)
        metadata_timeout = _checked_timeout(metadata_timeout_seconds)
        upload_timeout = _checked_timeout(upload_timeout_seconds)
        self._repository_path = f"{owner}/{name}"
        self.repository = f"{GITHUB_HOST}/{self._repository_path}"
        self.environment = {
            str(key): str(value)
            for key, value in environment.items()
            if str(key).casefold() != "gh_host"
        }
        self.output = output
        self._run_process = run_process or subprocess.run
        self.project_root = (Path(project_root) if project_root is not None else Path.cwd()).resolve()
        self._metadata_timeout_seconds = metadata_timeout
        self._upload_timeout_seconds = upload_timeout
        self._github_token_cache = ""
        self._upload_progress = upload_progress or (lambda _progress: None)
        self._upload_request = upload_request or GitHubAssetUploadTransport(
            environment=self.environment,
            token_provider=self._github_token,
            request_timeout_seconds=upload_timeout,
        ).upload
        self.executed_uploads: list[tuple[str, ...]] = []

    def ensure_tag(self, tag: str, commit: str) -> None:
        """Create a lightweight tag once, accepting only the requested commit."""

        checked_tag = _checked_tag(tag)
        checked_commit = _checked_commit(commit)
        existing = self._read_tag(checked_tag)
        if existing is not None:
            if self._tag_commit(existing) != checked_commit:
                raise PublishError("GitHub command failed")
            return

        self._execute(
            self._api_command(
                "POST",
                f"repos/{self._repository_path}/git/refs",
                "-f",
                f"ref=refs/tags/{checked_tag}",
                "-f",
                f"sha={checked_commit}",
            ),
            timeout_seconds=self._metadata_timeout_seconds,
        )
        created = self._read_tag(checked_tag)
        if created is None or self._tag_commit(created) != checked_commit:
            raise PublishError("GitHub command failed")

    def ensure_release(self, tag: str, title: str, notes_path: str | Path, *, repair: bool) -> None:
        """Create a release once; existing metadata is immutable and reused."""

        checked_tag = _checked_tag(tag)
        resolved_notes = _resolved_regular_file(notes_path, label="release notes", reject_dash=True)
        existing = self._read_release(checked_tag)
        if existing is not None:
            return

        self._execute(
            self._release_command("create", checked_tag, title, resolved_notes),
            timeout_seconds=self._metadata_timeout_seconds,
        )
        if self._read_release(checked_tag) is None:
            raise PublishError("GitHub command failed")

    def upload_assets(
        self,
        tag: str,
        assets: Sequence[str | Path | ReleaseAssetInfo],
        *,
        repair: bool,
    ) -> None:
        """Upload assets sequentially, resuming a batch at verified file boundaries."""

        checked_tag = _checked_tag(tag)
        local_assets = _local_assets(assets)
        release = self._read_release(checked_tag)
        if release is None:
            raise PublishError("invalid release asset response")
        remote_assets = _remote_assets_by_name(_remote_assets_from_release(release))
        pending: list[tuple[int, _LocalAsset]] = []
        overall_total = sum(asset.info.size for asset in local_assets)
        completed_bytes = 0

        for index, local in enumerate(local_assets, start=1):
            remote_asset = remote_assets.get(local.info.name)
            remote = remote_asset.info if remote_asset is not None else None
            if remote is None:
                pending.append((index, local))
                continue
            if remote.size == local.info.size and remote.digest and remote.digest == local.info.digest:
                completed_bytes += local.info.size
                self._emit_upload_progress(
                    local,
                    asset_index=index,
                    asset_count=len(local_assets),
                    completed_bytes=completed_bytes - local.info.size,
                    bytes_sent=local.info.size,
                    overall_total=overall_total,
                    attempt=1,
                    state="skipped",
                )
                continue
            if remote.size == local.info.size and not remote.digest:
                raise PublishError(
                    f"remote asset {local.info.name} digest is unavailable; "
                    "immutable release requires a new revision"
                )
            raise PublishError(
                f"remote asset {local.info.name} differs; "
                "immutable release requires a new revision"
            )

        if not pending:
            return
        upload_url_value = release.get("upload_url")
        if not isinstance(upload_url_value, str) or not upload_url_value.strip():
            raise PublishError("invalid release asset response")
        upload_url = _checked_repository_upload_url(upload_url_value, self._repository_path)
        self._upload(
            checked_tag,
            upload_url,
            pending,
            asset_count=len(local_assets),
            overall_total=overall_total,
            completed_bytes=completed_bytes,
        )

    def verify_assets(
        self,
        tag: str,
        expected: Sequence[str | Path | ReleaseAssetInfo],
    ) -> tuple[ReleaseAssetInfo, ...]:
        """Read back each expected remote asset and verify size plus SHA-256 digest."""

        remote_assets = _assets_by_name(self._release_assets(_checked_tag(tag)))
        verified: list[ReleaseAssetInfo] = []
        for local in _local_assets(expected):
            remote = remote_assets.get(local.info.name)
            if remote is None:
                raise PublishError(f"remote asset {local.info.name} is missing")
            if remote.size != local.info.size:
                raise PublishError(f"remote asset {local.info.name} has an unexpected size")
            if not remote.digest:
                raise PublishError(f"remote asset {local.info.name} digest is unavailable")
            if remote.digest != local.info.digest:
                raise PublishError(f"remote asset {local.info.name} has an unexpected digest")
            verified.append(remote)
        return tuple(verified)

    def _read_tag(self, tag: str) -> Mapping[str, object] | None:
        payload = self._api_json(
            "GET",
            f"repos/{self._repository_path}/git/matching-refs/tags/{quote(tag, safe='')}",
        )
        if not isinstance(payload, list):
            raise PublishError("invalid GitHub response")
        matching = [
            item
            for item in payload
            if isinstance(item, Mapping) and item.get("ref") == f"refs/tags/{tag}"
        ]
        if len(matching) > 1:
            raise PublishError("invalid GitHub response")
        return matching[0] if matching else None

    def _tag_commit(self, reference: Mapping[str, object]) -> str:
        current: Mapping[str, object] = reference
        seen: set[str] = set()
        for _ in range(8):
            object_data = current.get("object")
            if not isinstance(object_data, Mapping):
                raise PublishError("invalid GitHub response")
            object_type = object_data.get("type")
            sha = _checked_commit_response(object_data.get("sha"))
            if object_type == "commit":
                return sha
            if object_type != "tag" or sha in seen:
                raise PublishError("invalid GitHub response")
            seen.add(sha)
            payload = self._api_json("GET", f"repos/{self._repository_path}/git/tags/{sha}")
            if not isinstance(payload, Mapping):
                raise PublishError("invalid GitHub response")
            current = payload
        raise PublishError("invalid GitHub response")

    def _read_release(self, tag: str) -> Mapping[str, object] | None:
        completed = self._execute(
            self._api_command(
                "GET",
                f"repos/{self._repository_path}/releases/tags/{quote(tag, safe='')}",
                "--include",
            ),
            timeout_seconds=self._metadata_timeout_seconds,
            emit_output=False,
            retry_transient=True,
        )
        status, body = _included_response(completed.stdout)
        if status == 404:
            return None
        if completed.returncode or status != 200:
            self._emit_streams(completed.stdout, completed.stderr)
            raise PublishError("GitHub command failed")
        payload = _json_payload(body)
        if not isinstance(payload, Mapping) or payload.get("tag_name") != tag:
            raise PublishError("invalid GitHub response")
        return payload

    def _release_assets(self, tag: str) -> tuple[ReleaseAssetInfo, ...]:
        invalid = False
        try:
            release = self._read_release(tag)
            if release is None:
                raise ValueError("release is missing")
            return tuple(asset.info for asset in _remote_assets_from_release(release))
        except (TypeError, ValueError, KeyError, PublishError):
            invalid = True
        if invalid:
            raise PublishError("invalid release asset response")
        raise AssertionError("unreachable")

    def _upload(
        self,
        tag: str,
        upload_url: str,
        assets: Sequence[tuple[int, "_LocalAsset"]],
        *,
        asset_count: int,
        overall_total: int,
        completed_bytes: int,
    ) -> None:
        if not assets:
            return
        uploaded: list[str] = []
        for asset_index, asset in assets:
            self._upload_one(
                tag,
                upload_url,
                asset,
                asset_index=asset_index,
                asset_count=asset_count,
                completed_bytes=completed_bytes,
                overall_total=overall_total,
            )
            completed_bytes += asset.info.size
            uploaded.append(str(asset.path))
        self.executed_uploads.append(tuple(uploaded))

    def _upload_one(
        self,
        tag: str,
        upload_url: str,
        asset: _LocalAsset,
        *,
        asset_index: int,
        asset_count: int,
        completed_bytes: int,
        overall_total: int,
    ) -> None:
        for attempt in range(1, len(_UPLOAD_RETRY_DELAYS_SECONDS) + 2):
            _assert_upload_snapshots((asset,), phase="before")
            last_sent = 0
            last_rate = 0.0

            def on_progress(bytes_sent: int, bytes_total: int, bytes_per_second: float) -> None:
                nonlocal last_sent, last_rate
                if bytes_total != asset.info.size:
                    raise ValueError("upload transport reported an unexpected asset size")
                last_sent = max(0, min(int(bytes_sent), bytes_total))
                last_rate = max(0.0, float(bytes_per_second))
                self._emit_upload_progress(
                    asset,
                    asset_index=asset_index,
                    asset_count=asset_count,
                    completed_bytes=completed_bytes,
                    bytes_sent=last_sent,
                    overall_total=overall_total,
                    bytes_per_second=last_rate,
                    attempt=attempt,
                    state="uploading",
                )

            transient = False
            try:
                self._upload_request(upload_url, asset.path, on_progress)
                _assert_upload_snapshots((asset,), phase="after")
            except UploadTransportError as error:
                transient = error.transient
            except OSError:
                transient = True
            else:
                self._emit_upload_progress(
                    asset,
                    asset_index=asset_index,
                    asset_count=asset_count,
                    completed_bytes=completed_bytes,
                    bytes_sent=asset.info.size,
                    overall_total=overall_total,
                    attempt=attempt,
                    state="completed",
                )
                return

            _assert_upload_snapshots((asset,), phase="after")
            reconciliation = self._reconcile_failed_upload(tag, asset)
            if reconciliation is True:
                self._emit_upload_progress(
                    asset,
                    asset_index=asset_index,
                    asset_count=asset_count,
                    completed_bytes=completed_bytes,
                    bytes_sent=asset.info.size,
                    overall_total=overall_total,
                    attempt=attempt,
                    state="recovered",
                )
                return
            if reconciliation is None:
                transient = True
            if not transient or attempt > len(_UPLOAD_RETRY_DELAYS_SECONDS):
                raise PublishError("GitHub command failed") from None

            delay = _UPLOAD_RETRY_DELAYS_SECONDS[attempt - 1]
            self._emit_upload_progress(
                asset,
                asset_index=asset_index,
                asset_count=asset_count,
                completed_bytes=completed_bytes,
                bytes_sent=last_sent,
                overall_total=overall_total,
                bytes_per_second=last_rate,
                attempt=attempt,
                state="retrying",
                retry_delay_seconds=delay,
            )
            self.output(
                f"上传 {asset.info.name} 时连接中断，{delay:g} 秒后从当前文件开头重试"
            )
            time.sleep(delay)

        raise AssertionError("unreachable")

    def _reconcile_failed_upload(self, tag: str, asset: _LocalAsset) -> bool | None:
        release = self._read_release(tag)
        if release is None:
            raise PublishError("GitHub command failed")
        remote = _remote_assets_by_name(_remote_assets_from_release(release)).get(asset.info.name)
        if remote is None:
            return False
        if (
            remote.info.size == asset.info.size
            and remote.info.digest
            and remote.info.digest == asset.info.digest
        ):
            return True
        # GitHub may leave a zero-byte "starter" asset after a broken POST. It is
        # safe to remove only that unfinished placeholder before retrying.
        if remote.state == "starter" and remote.asset_id is not None:
            self._run(
                self._api_command(
                    "DELETE",
                    f"repos/{self._repository_path}/releases/assets/{remote.asset_id}",
                )
            )
            return None
        if remote.info.size == asset.info.size and not remote.info.digest:
            raise PublishError(
                f"remote asset {asset.info.name} digest is unavailable; "
                "immutable release requires a new revision"
            )
        raise PublishError(
            f"remote asset {asset.info.name} differs; immutable release requires a new revision"
        )

    def _emit_upload_progress(
        self,
        asset: _LocalAsset,
        *,
        asset_index: int,
        asset_count: int,
        completed_bytes: int,
        bytes_sent: int,
        overall_total: int,
        attempt: int,
        state: str,
        bytes_per_second: float = 0.0,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        self._upload_progress(
            ReleaseUploadProgress(
                asset_name=asset.info.name,
                asset_index=asset_index,
                asset_count=asset_count,
                bytes_sent=bytes_sent,
                bytes_total=asset.info.size,
                overall_bytes_sent=min(overall_total, completed_bytes + bytes_sent),
                overall_bytes_total=overall_total,
                bytes_per_second=bytes_per_second,
                attempt=attempt,
                state=state,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    def _github_token(self) -> str:
        if self._github_token_cache:
            return self._github_token_cache
        values = {key.casefold(): value.strip() for key, value in self.environment.items()}
        token = values.get("gh_token", "") or values.get("github_token", "")
        if not token:
            completed = self._execute(
                ["gh", "auth", "token", "--hostname", GITHUB_HOST],
                timeout_seconds=self._metadata_timeout_seconds,
                emit_output=False,
            )
            if completed.returncode:
                raise PublishError("GitHub authentication is unavailable")
            token = completed.stdout.strip()
        if not token:
            raise PublishError("GitHub authentication is unavailable")
        self._github_token_cache = token
        return token

    def _release_command(self, command: str, tag: str, title: str, notes_path: Path) -> list[str]:
        argv = [
            "gh",
            "release",
            command,
            "--repo",
            self.repository,
            "--title",
            str(title),
            "--notes-file",
            str(notes_path),
        ]
        if command == "create":
            argv.append("--verify-tag")
        argv.extend(["--", tag])
        return argv

    def _api_json(self, method: str, endpoint: str, *extra: str) -> object:
        completed = self._run(
            self._api_command(method, endpoint, *extra),
            retry_transient=method.casefold() == "get",
        )
        return _json_payload(completed.stdout)

    def _api_command(self, method: str, endpoint: str, *extra: str) -> list[str]:
        return [
            "gh",
            "api",
            "--hostname",
            GITHUB_HOST,
            "--method",
            method,
            endpoint,
            *extra,
        ]

    def _run(
        self,
        argv: Sequence[str],
        *,
        retry_transient: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        completed = self._execute(
            argv,
            timeout_seconds=self._metadata_timeout_seconds,
            retry_transient=retry_transient,
        )
        if completed.returncode:
            raise PublishError("GitHub command failed")
        return completed

    def _execute(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        emit_output: bool = True,
        retry_transient: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        retry_delays = _METADATA_RETRY_DELAYS_SECONDS if retry_transient else ()
        for attempt in range(len(retry_delays) + 1):
            timeout_error: subprocess.TimeoutExpired | None = None
            os_error = False
            try:
                completed = self._run_process(
                    list(argv),
                    cwd=str(Path(self.project_root)),
                    env=dict(self.environment),
                    capture_output=True,
                    text=True,
                    # gh 的管道输出固定为 UTF-8；Windows 默认 GBK 会在中文
                    # Release 标题或说明处令 subprocess 的 reader 线程崩溃。
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                timeout_error = error
            except OSError:
                os_error = True

            can_retry = attempt < len(retry_delays) and (
                timeout_error is not None
                or (
                    not os_error
                    and completed.returncode != 0
                    and _is_transient_github_failure(
                        completed.stdout,
                        completed.stderr,
                    )
                )
            )
            if can_retry:
                delay = retry_delays[attempt]
                self.output(
                    f"GitHub 网络连接暂时中断，{delay:g} 秒后重试"
                    f"（{attempt + 1}/{len(retry_delays)}）"
                )
                time.sleep(delay)
                continue
            if timeout_error is not None:
                self._emit_streams(timeout_error.output, timeout_error.stderr)
                raise PublishError("GitHub command failed")
            if os_error:
                raise PublishError("GitHub command failed")
            if emit_output:
                self._emit_streams(completed.stdout, completed.stderr)
            return completed

        raise AssertionError("unreachable")

    def _emit_streams(self, *streams: object) -> None:
        for stream in streams:
            redacted = redact_release_text(str(stream or ""))
            for line in redacted.splitlines():
                self.output(line)


def _normalise_digest(value: str) -> str:
    digest = str(value).strip().casefold()
    if not _DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("release asset digest must be a sha256 digest")
    return digest


def _is_transient_github_failure(*streams: object) -> bool:
    """只识别适合自动重试的网络/服务端瞬态错误。"""

    message = "\n".join(str(stream or "") for stream in streams).casefold()
    return bool(
        _TRANSIENT_HTTP_STATUS_PATTERN.search(message)
        or any(fragment in message for fragment in _TRANSIENT_GITHUB_FAILURE_FRAGMENTS)
    )


def _local_assets(
    assets: Sequence[str | Path | ReleaseAssetInfo],
) -> tuple[_LocalAsset, ...]:
    resolved: list[_LocalAsset] = []
    names: set[str] = set()
    for asset in assets:
        if isinstance(asset, ReleaseAssetInfo):
            raise ValueError("release asset paths are required for upload and verification")
        if "#" in str(asset):
            raise ValueError("release asset path cannot contain #")
        path = _resolved_regular_file(asset, label="release asset")
        info = ReleaseAssetInfo.from_path(path)
        if info.name in names:
            raise ValueError(f"duplicate release asset name: {info.name}")
        names.add(info.name)
        resolved.append(_LocalAsset(path=path, info=info, snapshot=_file_snapshot(path)))
    return tuple(resolved)


def _assert_upload_snapshots(assets: Sequence[_LocalAsset], *, phase: str) -> None:
    for asset in assets:
        if _file_snapshot(asset.path) != asset.snapshot:
            raise ValueError(f"release asset changed {phase} upload")


def _assets_by_name(assets: Sequence[ReleaseAssetInfo]) -> dict[str, ReleaseAssetInfo]:
    result: dict[str, ReleaseAssetInfo] = {}
    for asset in assets:
        if asset.name in result:
            raise PublishError("duplicate release asset name")
        result[asset.name] = asset
    return result


def _remote_assets_from_release(release: Mapping[str, object]) -> tuple[_RemoteAsset, ...]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("assets is not a list")
    parsed: list[_RemoteAsset] = []
    for payload in assets:
        if not isinstance(payload, Mapping):
            raise ValueError("release asset is not an object")
        asset_id = payload.get("id")
        if asset_id is not None and (
            isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0
        ):
            raise ValueError("release asset id is invalid")
        state = payload.get("state", "uploaded")
        if not isinstance(state, str) or state not in {"uploaded", "starter"}:
            raise ValueError("release asset state is invalid")
        parsed.append(
            _RemoteAsset(
                info=ReleaseAssetInfo.from_json(payload),
                asset_id=asset_id,
                state=state,
            )
        )
    return tuple(parsed)


def _remote_assets_by_name(assets: Sequence[_RemoteAsset]) -> dict[str, _RemoteAsset]:
    result: dict[str, _RemoteAsset] = {}
    for asset in assets:
        if asset.info.name in result:
            raise PublishError("duplicate release asset name")
        result[asset.info.name] = asset
    return result


def _resolved_regular_file(path: str | Path, *, label: str, reject_dash: bool = False) -> Path:
    value = str(path)
    if reject_dash and value == "-":
        raise ValueError(f"{label} cannot be -")
    try:
        resolved = Path(path).resolve(strict=True)
        _file_snapshot(resolved)
        with resolved.open("rb"):
            pass
        return resolved
    except OSError:
        raise ValueError(f"{label} must be an existing readable regular file")


def _file_snapshot(path: Path) -> tuple[int, int, int, int]:
    result = path.stat()
    if not stat.S_ISREG(result.st_mode):
        raise ValueError("release asset must be a regular file")
    return result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns


def _checked_tag(tag: str) -> str:
    value = str(tag).strip()
    try:
        identity = parse_release_tag(value)
    except ValueError:
        raise ValueError("invalid release tag")
    return identity.tag


def _checked_commit(commit: str) -> str:
    value = str(commit).strip().casefold()
    if not _SHA_PATTERN.fullmatch(value):
        raise ValueError("full commit SHA is required")
    return value


def _checked_commit_response(value: object) -> str:
    if not isinstance(value, str):
        raise PublishError("invalid GitHub response")
    valid = True
    try:
        return _checked_commit(value)
    except ValueError:
        valid = False
    if not valid:
        raise PublishError("invalid GitHub response")
    raise AssertionError("unreachable")


def _checked_timeout(value: float) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    return timeout


def _json_payload(value: object) -> object:
    valid = True
    payload: object = None
    try:
        payload = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        valid = False
    if not valid:
        raise PublishError("invalid GitHub response")
    return payload


def _included_response(value: object) -> tuple[int | None, str]:
    text = str(value or "")
    header, separator, body = text.partition("\r\n\r\n")
    if not separator:
        header, separator, body = text.partition("\n\n")
    match = re.search(r"(?m)^HTTP/\S+\s+(\d{3})\b", header)
    return (int(match.group(1)) if match is not None else None), body


def _repository_components(repository: str) -> tuple[str, str]:
    parts = str(repository).split("/")
    if len(parts) != 2 or not all(_is_safe_component(part) for part in parts):
        raise ValueError("invalid GitHub repository")
    return parts[0], parts[1]


def _checked_repository_upload_url(value: str, repository_path: str) -> str:
    endpoint = str(value).split("{", 1)[0].strip()
    parsed = urlsplit(endpoint)
    parts = parsed.path.split("/")
    repository_parts = repository_path.split("/")
    valid_path = (
        len(parts) == 7
        and parts[1] == "repos"
        and len(repository_parts) == 2
        and parts[2].casefold() == repository_parts[0].casefold()
        and parts[3].casefold() == repository_parts[1].casefold()
        and parts[4] == "releases"
        and parts[5].isdigit()
        and int(parts[5]) > 0
        and parts[6] == "assets"
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "uploads.github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not valid_path
    ):
        raise PublishError("invalid release asset response")
    return value


def _is_safe_component(value: str) -> bool:
    return bool(
        _COMPONENT_PATTERN.fullmatch(value)
        and value not in {".", ".."}
        and not value.startswith("-")
        and not value.endswith(".")
    )


__all__ = [
    "GitHubReleasePublisher",
    "PublishError",
    "ReleaseAssetInfo",
    "ReleaseUploadProgress",
]
