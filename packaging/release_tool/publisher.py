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

from .events import redact_release_text


GITHUB_HOST = "github.com"
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 60.0
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
        try:
            with asset_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError as error:
            raise ValueError("release asset is not readable") from error
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
        subprocess_timeout_seconds: float = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    ) -> None:
        owner, name = _repository_components(repository)
        timeout = float(subprocess_timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("subprocess timeout must be finite and positive")
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
        self._timeout_seconds = timeout
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
            )
        )
        created = self._read_tag(checked_tag)
        if created is None or self._tag_commit(created) != checked_commit:
            raise PublishError("GitHub command failed")

    def ensure_release(self, tag: str, title: str, notes_path: str | Path, *, repair: bool) -> None:
        """Create a release only for an existing tag, or repair existing metadata."""

        checked_tag = _checked_tag(tag)
        resolved_notes = _resolved_regular_file(notes_path, label="release notes", reject_dash=True)
        existing = self._read_release(checked_tag)
        if existing is not None:
            if not repair:
                return
            completed = self._execute(self._release_command("edit", checked_tag, title, resolved_notes))
            if completed.returncode:
                raise PublishError("GitHub command failed")
            if self._read_release(checked_tag) is None:
                raise PublishError("GitHub command failed")
            return

        self._execute(self._release_command("create", checked_tag, title, resolved_notes))
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
        normal_uploads: list[Path] = []
        repair_uploads: list[Path] = []

        for path, local in local_assets:
            remote = remote_assets.get(local.name)
            if remote is None:
                normal_uploads.append(path)
                continue
            if remote.size == local.size and remote.digest and remote.digest == local.digest:
                continue
            if not repair:
                if remote.size == local.size and not remote.digest:
                    raise PublishError(
                        f"remote asset {local.name} digest is unavailable; repair is required"
                    )
                raise PublishError(f"remote asset {local.name} differs; requires repair")
            repair_uploads.append(path)

        self._upload(checked_tag, normal_uploads, clobber=False)
        self._upload(checked_tag, repair_uploads, clobber=True)

    def verify_assets(
        self,
        tag: str,
        expected: Sequence[str | Path | ReleaseAssetInfo],
    ) -> tuple[ReleaseAssetInfo, ...]:
        """Read back each expected remote asset and verify size plus SHA-256 digest."""

        remote_assets = _assets_by_name(self._release_assets(_checked_tag(tag)))
        verified: list[ReleaseAssetInfo] = []
        for _, local in _local_assets(expected):
            remote = remote_assets.get(local.name)
            if remote is None:
                raise PublishError(f"remote asset {local.name} is missing")
            if remote.size != local.size:
                raise PublishError(f"remote asset {local.name} has an unexpected size")
            if not remote.digest:
                raise PublishError(f"remote asset {local.name} digest is unavailable")
            if remote.digest != local.digest:
                raise PublishError(f"remote asset {local.name} has an unexpected digest")
            verified.append(remote)
        return tuple(verified)

    def _read_tag(self, tag: str) -> Mapping[str, object] | None:
        payload = self._api_json(
            "GET",
            f"repos/{self._repository_path}/git/matching-refs/tags/{tag}",
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
        payload = self._api_json(
            "GET",
            f"repos/{self._repository_path}/releases?per_page=100",
            "--paginate",
            "--slurp",
        )
        releases = _flatten_release_pages(payload)
        matching = [release for release in releases if release.get("tag_name") == tag]
        if len(matching) > 1:
            raise PublishError("invalid GitHub response")
        return matching[0] if matching else None

    def _release_assets(self, tag: str) -> tuple[ReleaseAssetInfo, ...]:
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
        except (TypeError, ValueError, json.JSONDecodeError, KeyError, PublishError) as error:
            raise PublishError("invalid release asset response") from error

    def _upload(self, tag: str, assets: Sequence[Path], *, clobber: bool) -> None:
        if not assets:
            return
        argv = ["gh", "release", "upload", "--repo", self.repository]
        if clobber:
            argv.append("--clobber")
        argv.extend(["--", tag, *(str(path) for path in assets)])
        self._run(argv)
        self.executed_uploads.append(tuple(str(path) for path in assets))

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
        try:
            return json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise PublishError("invalid GitHub response") from error

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
        completed = self._execute(argv)
        if completed.returncode:
            raise PublishError("GitHub command failed")
        return completed

    def _execute(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._run_process(
                list(argv),
                cwd=str(Path(self.project_root)),
                env=dict(self.environment),
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PublishError("GitHub command failed") from error
        for stream in (completed.stdout, completed.stderr):
            redacted = redact_release_text(str(stream or ""))
            for line in redacted.splitlines():
                self.output(line)
        return completed


def _normalise_digest(value: str) -> str:
    digest = str(value).strip().casefold()
    if not _DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("release asset digest must be a sha256 digest")
    return digest


def _local_assets(
    assets: Sequence[str | Path | ReleaseAssetInfo],
) -> tuple[tuple[Path, ReleaseAssetInfo], ...]:
    resolved: list[tuple[Path, ReleaseAssetInfo]] = []
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
        resolved.append((path, info))
    return tuple(resolved)


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
    except OSError as error:
        raise ValueError(f"{label} must be an existing readable regular file") from error


def _file_snapshot(path: Path) -> tuple[int, int, int, int]:
    result = path.stat()
    if not stat.S_ISREG(result.st_mode):
        raise ValueError("release asset must be a regular file")
    return result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns


def _checked_tag(tag: str) -> str:
    value = str(tag).strip()
    invalid = (
        not value
        or value.startswith("-")
        or value.startswith(".")
        or "/" in value
        or ".." in value
        or "@{" in value
        or value == "@"
        or value.endswith((".", ".lock"))
        or any(ord(character) < 32 or character in " \\~^:?*[" for character in value)
    )
    if invalid:
        raise ValueError("invalid release tag")
    return value


def _checked_commit(commit: str) -> str:
    value = str(commit).strip().casefold()
    if not _SHA_PATTERN.fullmatch(value):
        raise ValueError("full commit SHA is required")
    return value


def _checked_commit_response(value: object) -> str:
    if not isinstance(value, str):
        raise PublishError("invalid GitHub response")
    try:
        return _checked_commit(value)
    except ValueError as error:
        raise PublishError("invalid GitHub response") from error


def _flatten_release_pages(payload: object) -> tuple[Mapping[str, object], ...]:
    pages = payload if isinstance(payload, list) else None
    if pages is None:
        raise PublishError("invalid GitHub response")
    if pages and all(isinstance(page, list) for page in pages):
        entries = [entry for page in pages for entry in page]
    else:
        entries = pages
    if not all(isinstance(entry, Mapping) for entry in entries):
        raise PublishError("invalid GitHub response")
    return tuple(entries)


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
