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
    occupied_tags: tuple[str, ...] = ()
    resumable_tags: tuple[str, ...] = ()
    error: str = ""

    @classmethod
    def available(
        cls,
        version: str,
        release_revision: int = 0,
        *,
        release_tags: tuple[str, ...] = (),
        occupied_tags: tuple[str, ...] = (),
        resumable_tags: tuple[str, ...] = (),
    ) -> "RemoteReleaseInfo":
        """Build a normalized snapshot of releases and immutable Git tags.

        ``release_tags`` are backed by a public GitHub Release. ``occupied_tags``
        additionally includes bare local/remote refs left by an interrupted
        publication. Only bare tags verified against the current HEAD belong in
        ``resumable_tags``.
        """

        published: set[ReleaseIdentity] = set()
        raw_version = str(version or "").strip()
        if raw_version.startswith("v"):
            published.add(parse_release_tag(raw_version))
        else:
            published.add(ReleaseIdentity(normalize_version(raw_version), release_revision))
        published.update(parse_release_tag(tag) for tag in release_tags)
        ordered_published = tuple(sorted(published, reverse=True))
        latest = ordered_published[0]

        occupied = set(published)
        occupied.update(parse_release_tag(tag) for tag in occupied_tags)
        resumable = {parse_release_tag(tag) for tag in resumable_tags}
        # A public Release is immutable and complete from the planner's point of
        # view. Automatic resume is reserved for a definitely incomplete bare tag.
        resumable.intersection_update(occupied)
        resumable.difference_update(published)
        return cls(
            version=latest.version,
            release_revision=latest.revision,
            release_tags=tuple(identity.tag for identity in ordered_published),
            occupied_tags=tuple(
                identity.tag for identity in sorted(occupied, reverse=True)
            ),
            resumable_tags=tuple(
                identity.tag for identity in sorted(resumable, reverse=True)
            ),
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

    @property
    def occupied_identities(self) -> tuple[ReleaseIdentity, ...]:
        if self.occupied_tags:
            return tuple(parse_release_tag(tag) for tag in self.occupied_tags)
        return self.release_identities

    @property
    def resumable_identities(self) -> tuple[ReleaseIdentity, ...]:
        return tuple(parse_release_tag(tag) for tag in self.resumable_tags)

    @property
    def incomplete_identities(self) -> tuple[ReleaseIdentity, ...]:
        published = set(self.release_identities)
        return tuple(
            identity
            for identity in self.occupied_identities
            if identity not in published
        )

    def highest_revision_for(self, version: str) -> int:
        normalized = normalize_version(version)
        revisions = (
            identity.revision
            for identity in self.occupied_identities
            if identity.version == normalized
        )
        return max(revisions, default=-1)

    def next_revision_for(self, version: str) -> int:
        highest = self.highest_revision_for(version)
        return 0 if highest < 0 else highest + 1

    def target_revision_for(self, version: str) -> int:
        """Resume the newest safe bare tag, otherwise allocate the next revision."""

        normalized = normalize_version(version)
        highest = self.highest_revision_for(normalized)
        resumable = {
            identity.revision
            for identity in self.resumable_identities
            if identity.version == normalized and identity.revision > 0
        }
        # Only the newest occupied revision may be resumed. Filling an older gap
        # after a newer revision exists would make update ordering ambiguous.
        return highest if highest in resumable else self.next_revision_for(normalized)

    def is_resumable_revision(self, version: str, revision: int) -> bool:
        try:
            identity = ReleaseIdentity(normalize_version(version), revision)
        except (TypeError, ValueError):
            return False
        return identity in self.resumable_identities

    def incomplete_tags_for(self, version: str) -> tuple[str, ...]:
        normalized = normalize_version(version)
        return tuple(
            identity.tag
            for identity in self.incomplete_identities
            if identity.version == normalized
        )


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
        # 旧请求文件没有 release_revision；优先恢复同一源码的裸标签，否则
        # 分配所有已占用标签之后的下一修订，避免中断重试静默覆盖旧源码。
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
                self.remote.target_revision_for(normalized),
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
