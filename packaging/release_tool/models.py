"""Immutable data contracts for release-builder planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

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
    BUILDING_PORTABLE = "building_portable"
    BUILDING_INSTALLER = "building_installer"
    SIGNING = "signing"
    GIT = "git"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RemoteReleaseInfo:
    version: str = ""
    error: str = ""

    @classmethod
    def available(cls, version: str) -> "RemoteReleaseInfo":
        return cls(version=normalize_version(version))

    @classmethod
    def unavailable(cls, error: str) -> "RemoteReleaseInfo":
        return cls(error=str(error or "").strip())

    @classmethod
    def unknown(cls) -> "RemoteReleaseInfo":
        return cls()

    @property
    def is_available(self) -> bool:
        return bool(self.version)


@dataclass(frozen=True)
class BuildRequest:
    target_version: str
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

    @property
    def succeeded(self) -> bool:
        return self.stage is ReleaseStage.SUCCEEDED and not self.errors


__all__ = [
    "BuildRequest",
    "PreflightResult",
    "ReleaseMode",
    "ReleaseResult",
    "ReleaseStage",
    "RemoteReleaseInfo",
]
