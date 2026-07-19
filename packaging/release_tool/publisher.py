"""Idempotent GitHub CLI operations for release assets."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import redact_release_text


_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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
            digest = _normalise_digest(self.digest)
            object.__setattr__(self, "digest", digest)

    @classmethod
    def from_path(cls, path: str | Path) -> "ReleaseAssetInfo":
        asset_path = Path(path)
        hasher = hashlib.sha256()
        with asset_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return cls(
            name=asset_path.name,
            size=asset_path.stat().st_size,
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
    """Publish a prebuilt release through ``gh`` without exposing credentials."""

    def __init__(
        self,
        repository: str,
        environment: Mapping[str, str],
        output: Callable[[str], None],
        *,
        run_process: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        if not _REPOSITORY_PATTERN.fullmatch(str(repository)):
            raise ValueError("invalid GitHub repository")
        self.repository = str(repository)
        self.environment = dict(environment)
        self.output = output
        self._run_process = run_process or subprocess.run
        self.project_root = Path(project_root) if project_root is not None else Path.cwd()
        self.executed_uploads: list[tuple[str, ...]] = []

    def ensure_tag(self, tag: str, commit: str) -> None:
        """Create a lightweight tag once, rejecting a conflicting remote tag."""

        checked_tag = _checked_tag(tag)
        checked_commit = _checked_commit(commit)
        existing = self._execute(
            [
                "gh",
                "api",
                f"repos/{self.repository}/git/ref/tags/{checked_tag}",
                "--method",
                "GET",
                "--jq",
                ".object.sha",
            ]
        )
        if existing.returncode == 0:
            remote_commit = existing.stdout.strip()
            if remote_commit != checked_commit:
                raise PublishError("existing tag points to a different commit")
            return
        if not _is_not_found(existing):
            _raise_for_failure(existing)
        self._run(
            [
                "gh",
                "api",
                f"repos/{self.repository}/git/refs",
                "--method",
                "POST",
                "-f",
                f"ref=refs/tags/{checked_tag}",
                "-f",
                f"sha={checked_commit}",
            ]
        )

    def ensure_release(self, tag: str, title: str, notes_path: str | Path, *, repair: bool) -> None:
        """Create a release, or explicitly update its metadata during repair."""

        checked_tag = _checked_tag(tag)
        command = "edit" if repair else "create"
        completed = self._execute(
            [
                "gh",
                "release",
                command,
                checked_tag,
                "--repo",
                self.repository,
                "--title",
                str(title),
                "--notes-file",
                str(Path(notes_path)),
            ]
        )
        if completed.returncode == 0:
            return
        if not repair and _is_already_exists(completed):
            return
        if repair and _is_not_found(completed):
            self._run(
                [
                    "gh",
                    "release",
                    "create",
                    checked_tag,
                    "--repo",
                    self.repository,
                    "--title",
                    str(title),
                    "--notes-file",
                    str(Path(notes_path)),
                ]
            )
            return
        _raise_for_failure(completed)

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
        remote_assets = {asset.name: asset for asset in self._release_assets(checked_tag)}
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

        remote_assets = {asset.name: asset for asset in self._release_assets(_checked_tag(tag))}
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

    def _release_assets(self, tag: str) -> tuple[ReleaseAssetInfo, ...]:
        completed = self._run(
            [
                "gh",
                "release",
                "view",
                tag,
                "--repo",
                self.repository,
                "--json",
                "assets",
            ]
        )
        try:
            payload = json.loads(completed.stdout)
            assets = payload["assets"]
            if not isinstance(assets, list):
                raise ValueError("assets is not a list")
            parsed_assets = []
            for asset in assets:
                if not isinstance(asset, Mapping):
                    raise ValueError("release asset is not an object")
                parsed_assets.append(ReleaseAssetInfo.from_json(asset))
            return tuple(parsed_assets)
        except (TypeError, ValueError, json.JSONDecodeError, KeyError) as error:
            raise PublishError("invalid release asset response") from error

    def _upload(self, tag: str, assets: Sequence[Path], *, clobber: bool) -> None:
        if not assets:
            return
        argv = ["gh", "release", "upload", tag, *(str(path) for path in assets), "--repo", self.repository]
        if clobber:
            argv.append("--clobber")
        self._run(argv)
        self.executed_uploads.append(tuple(str(path) for path in assets))

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        completed = self._execute(argv)
        if completed.returncode:
            _raise_for_failure(completed)
        return completed

    def _execute(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        completed = self._run_process(
            list(argv),
            cwd=str(Path(self.project_root)),
            env=dict(self.environment),
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        for line in str(completed.stdout or "").splitlines():
            self.output(redact_release_text(line))
        for line in str(completed.stderr or "").splitlines():
            self.output(redact_release_text(line))
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
        path = Path(asset)
        info = ReleaseAssetInfo.from_path(path)
        if info.name in names:
            raise ValueError(f"duplicate release asset name: {info.name}")
        names.add(info.name)
        resolved.append((path, info))
    return tuple(resolved)


def _checked_tag(tag: str) -> str:
    value = str(tag).strip()
    if not value or any(character.isspace() or character in "~^:?*[\\" for character in value):
        raise ValueError("invalid release tag")
    return value


def _checked_commit(commit: str) -> str:
    value = str(commit).strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{7,64}", value):
        raise ValueError("invalid commit SHA")
    return value


def _is_not_found(completed: subprocess.CompletedProcess[str]) -> bool:
    text = f"{completed.stdout or ''}\n{completed.stderr or ''}".casefold()
    return "404" in text or "not found" in text


def _is_already_exists(completed: subprocess.CompletedProcess[str]) -> bool:
    text = f"{completed.stdout or ''}\n{completed.stderr or ''}".casefold()
    return "already exists" in text or "already_exists" in text


def _raise_for_failure(completed: subprocess.CompletedProcess[Any]) -> None:
    raise PublishError(f"command failed with exit code {completed.returncode}")


__all__ = ["GitHubReleasePublisher", "PublishError", "ReleaseAssetInfo"]
