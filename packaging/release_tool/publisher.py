"""Idempotent, pinned GitHub CLI operations for release assets."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from shared.release_identity import parse_release_tag

from .events import redact_release_text


GITHUB_HOST = "github.com"
DEFAULT_METADATA_TIMEOUT_SECONDS = 60.0
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 2 * 60 * 60.0
_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


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
class _LocalAsset:
    path: Path
    info: ReleaseAssetInfo
    snapshot: tuple[int, int, int, int]


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
        """Upload assets in batches, skipping only digest-verified matches."""

        checked_tag = _checked_tag(tag)
        local_assets = _local_assets(assets)
        remote_assets = _assets_by_name(self._release_assets(checked_tag))
        normal_uploads: list[_LocalAsset] = []

        for local in local_assets:
            remote = remote_assets.get(local.info.name)
            if remote is None:
                normal_uploads.append(local)
                continue
            if remote.size == local.info.size and remote.digest and remote.digest == local.info.digest:
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

        self._upload(checked_tag, normal_uploads)

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
            assets = release.get("assets")
            if not isinstance(assets, list):
                raise ValueError("assets is not a list")
            parsed = []
            for asset in assets:
                if not isinstance(asset, Mapping):
                    raise ValueError("release asset is not an object")
                parsed.append(ReleaseAssetInfo.from_json(asset))
            return tuple(parsed)
        except (TypeError, ValueError, KeyError, PublishError):
            invalid = True
        if invalid:
            raise PublishError("invalid release asset response")

    def _upload(self, tag: str, assets: Sequence["_LocalAsset"]) -> None:
        if not assets:
            return
        _assert_upload_snapshots(assets, phase="before")
        argv = ["gh", "release", "upload", "--repo", self.repository]
        argv.extend(["--", tag, *(str(asset.path) for asset in assets)])
        completed = self._execute(argv, timeout_seconds=self._upload_timeout_seconds)
        _assert_upload_snapshots(assets, phase="after")
        if completed.returncode:
            raise PublishError("GitHub command failed")
        self.executed_uploads.append(tuple(str(asset.path) for asset in assets))

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
        completed = self._run(self._api_command(method, endpoint, *extra))
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

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        completed = self._execute(argv, timeout_seconds=self._metadata_timeout_seconds)
        if completed.returncode:
            raise PublishError("GitHub command failed")
        return completed

    def _execute(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        emit_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
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
        if timeout_error is not None:
            self._emit_streams(timeout_error.output, timeout_error.stderr)
            raise PublishError("GitHub command failed")
        if os_error:
            raise PublishError("GitHub command failed")
        if emit_output:
            self._emit_streams(completed.stdout, completed.stderr)
        return completed

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


def _is_safe_component(value: str) -> bool:
    return bool(
        _COMPONENT_PATTERN.fullmatch(value)
        and value not in {".", ".."}
        and not value.startswith("-")
        and not value.endswith(".")
    )


__all__ = ["GitHubReleasePublisher", "PublishError", "ReleaseAssetInfo"]
