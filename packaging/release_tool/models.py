"""Immutable data contracts for release-builder planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from shared.release_identity import ReleaseIdentity, parse_release_tag

from .versioning import normalize_version

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    class StrEnum(str, Enum):
        pass


class ReleaseMode(StrEnum):
    LOCAL_DEBUG = "local_debug"
    LOCAL_REBUILD = "local_rebuild"
    SAME_RELEASE_REPAIR = "same_release_repair"
    NEW_RELEASE = "new_release"
    OFFLINE_DEBUG = "offline_debug"


class ReleaseStage(StrEnum):
    IDLE = "idle"
    CHECKING_REMOTE = "checking_remote"
    PREFLIGHT = "preflight"
    VERSION_SYNC = "version_sync"
    SOURCE_IDENTITY = "source_identity"
    BUILDING_PORTABLE = "building_portable"
    BUILDING_INSTALLER = "building_installer"
    SIGNING = "signing"
    SMOKE_TESTING = "smoke_testing"
    GIT = "git"
    PUBLISHING = "publishing"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RemoteReleaseInfo:
    version: str = ""
    release_revision: int = 0
    release_tags: tuple[str, ...] = ()
    error: str = ""

    @classmethod
    def available(
        cls,
        version: str,
        release_revision: int = 0,
        *,
        release_tags: tuple[str, ...] = (),
    ) -> "RemoteReleaseInfo":
        """Build a normalized snapshot from one or more public release tags."""

        identities: set[ReleaseIdentity] = set()
        raw_version = str(version or "").strip()
        if raw_version.startswith("v"):
            identities.add(parse_release_tag(raw_version))
        else:
            identities.add(ReleaseIdentity(normalize_version(raw_version), release_revision))
        identities.update(parse_release_tag(tag) for tag in release_tags)
        ordered = tuple(sorted(identities, reverse=True))
        latest = ordered[0]
        return cls(
            version=latest.version,
            release_revision=latest.revision,
            release_tags=tuple(identity.tag for identity in ordered),
        )

    @classmethod
    def unavailable(cls, error: str) -> "RemoteReleaseInfo":
        return cls(error=str(error or "").strip())

    @classmethod
    def unknown(cls) -> "RemoteReleaseInfo":
        return cls()

    @property
    def is_available(self) -> bool:
        return bool(self.version)

    @property
    def identity(self) -> ReleaseIdentity:
        if not self.is_available:
            raise ValueError("remote release state is unknown")
        return ReleaseIdentity(self.version, self.release_revision)

    @property
    def release_identities(self) -> tuple[ReleaseIdentity, ...]:
        if self.release_tags:
            return tuple(parse_release_tag(tag) for tag in self.release_tags)
        return (self.identity,) if self.is_available else ()

    def highest_revision_for(self, version: str) -> int:
        normalized = normalize_version(version)
        revisions = (
            identity.revision
            for identity in self.release_identities
            if identity.version == normalized
        )
        return max(revisions, default=-1)

    def next_revision_for(self, version: str) -> int:
        highest = self.highest_revision_for(version)
        return 0 if highest < 0 else highest + 1


@dataclass(frozen=True)
class BuildRequest:
    target_version: str
    release_revision: int = 0
    repository: str = "haohaizi554/UniversalCrawler"
    release_notes_path: str = ""
    output_root: str = ""
    build_portable: bool = True
    build_installer: bool = True
    run_smoke_tests: bool = True
    dry_run: bool = False
    same_release_repair: bool = False
    offline_debug: bool = False
    apply_version: bool = True
    generate_manifest_key: bool = False
    rotate_trust_anchor: bool = False
    private_key_path: str = ""
    sign_manifest: bool = False
    commit_version_changes: bool = False
    push_main: bool = False
    create_or_reuse_tag: bool = False
    create_or_update_release: bool = False
    upload_release_assets: bool = False
    upload_public_key: bool = False
    verify_remote_assets: bool = False
    proxy_label: str = "系统代理"
    custom_proxy: str = ""
    remote: RemoteReleaseInfo = field(default_factory=RemoteReleaseInfo.unknown)

    def __post_init__(self) -> None:
        try:
            normalized = normalize_version(self.target_version)
        except ValueError:
            return
        object.__setattr__(self, "target_version", normalized)
        # 旧请求文件没有 release_revision；在兼容入口补成远端的下一修订，
        # 但后续校验仍会拒绝负数、bool 或跳号，避免静默覆盖既有发布。
        if (
            self.same_release_repair
            and isinstance(self.release_revision, int)
            and not isinstance(self.release_revision, bool)
            and self.release_revision == 0
            and self.remote.is_available
            and self.remote.version == normalized
        ):
            object.__setattr__(
                self,
                "release_revision",
                self.remote.next_revision_for(normalized),
            )


@dataclass(frozen=True)
class PreflightResult:
    mode: ReleaseMode
    errors: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ReleaseResult:
    mode: ReleaseMode
    stage: ReleaseStage
    errors: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    failed_stage: ReleaseStage | None = None
    error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.stage is ReleaseStage.SUCCEEDED and not self.errors and not self.error

    @property
    def cancelled(self) -> bool:
        return self.stage is ReleaseStage.CANCELLED


__all__ = [
    "BuildRequest",
    "PreflightResult",
    "ReleaseMode",
    "ReleaseResult",
    "ReleaseStage",
    "RemoteReleaseInfo",
]
