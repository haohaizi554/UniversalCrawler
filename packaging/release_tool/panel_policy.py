"""Pure three-intent policy for the release-builder panel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import ReleaseMode, RemoteReleaseInfo
from .versioning import normalize_version


class PanelBuildIntent(str, Enum):
    """User-facing build intents exposed by the release-builder panel."""

    LOCAL = "local"
    SAME_RELEASE = "same_release"
    NEW_RELEASE = "new_release"


class VersionRelation(str, Enum):
    """Relationship between the requested and latest remote versions."""

    INVALID = "invalid"
    UNKNOWN = "unknown"
    LOWER = "lower"
    EQUAL = "equal"
    HIGHER = "higher"


@dataclass(frozen=True, slots=True)
class PanelModeResolution:
    """Existing core-mode flags produced from a panel intent."""

    release_mode: ReleaseMode
    same_release_repair: bool
    offline_debug: bool


@dataclass(frozen=True, slots=True)
class PanelOptionDefaults:
    """Complete first-entry option defaults for one panel intent."""

    apply_version: bool
    build_portable: bool
    build_installer: bool
    run_smoke_tests: bool
    generate_manifest_key: bool
    rotate_trust_anchor: bool
    sign_manifest: bool
    commit_version_changes: bool
    push_main: bool
    create_or_reuse_tag: bool
    create_or_update_release: bool
    upload_release_assets: bool
    upload_public_key: bool
    verify_remote_assets: bool


_LOCAL_DEFAULTS = PanelOptionDefaults(
    apply_version=True,
    build_portable=True,
    build_installer=True,
    run_smoke_tests=True,
    generate_manifest_key=False,
    rotate_trust_anchor=False,
    sign_manifest=False,
    commit_version_changes=False,
    push_main=False,
    create_or_reuse_tag=False,
    create_or_update_release=False,
    upload_release_assets=False,
    upload_public_key=False,
    verify_remote_assets=False,
)

_SAME_RELEASE_DEFAULTS = PanelOptionDefaults(
    apply_version=False,
    build_portable=True,
    build_installer=True,
    run_smoke_tests=True,
    generate_manifest_key=False,
    rotate_trust_anchor=False,
    sign_manifest=True,
    commit_version_changes=False,
    # 同版本修订没有版本文件提交，但先把当前干净 HEAD 推到 main，GitHub
    # 才能可靠地为该源码创建新的不可变 revision tag。
    push_main=True,
    create_or_reuse_tag=True,
    create_or_update_release=True,
    upload_release_assets=True,
    upload_public_key=True,
    verify_remote_assets=True,
)

_NEW_RELEASE_DEFAULTS = PanelOptionDefaults(
    apply_version=True,
    build_portable=True,
    build_installer=True,
    run_smoke_tests=True,
    generate_manifest_key=False,
    rotate_trust_anchor=False,
    sign_manifest=True,
    commit_version_changes=True,
    push_main=True,
    create_or_reuse_tag=True,
    create_or_update_release=True,
    upload_release_assets=True,
    upload_public_key=True,
    verify_remote_assets=True,
)


def version_relation(
    target_version: str,
    remote: RemoteReleaseInfo,
) -> VersionRelation:
    """Return a total, non-throwing relation for panel projection."""

    try:
        target = normalize_version(target_version)
    except ValueError:
        return VersionRelation.INVALID
    if not remote.is_available:
        return VersionRelation.UNKNOWN
    try:
        remote_version = normalize_version(remote.version)
    except ValueError:
        return VersionRelation.UNKNOWN

    target_parts = tuple(int(part) for part in target.split("."))
    remote_parts = tuple(int(part) for part in remote_version.split("."))
    if target_parts < remote_parts:
        return VersionRelation.LOWER
    if target_parts > remote_parts:
        return VersionRelation.HIGHER
    return VersionRelation.EQUAL


def recommended_intent(
    target_version: str,
    remote: RemoteReleaseInfo,
) -> PanelBuildIntent:
    """Choose the safe recommended intent for the current version relation."""

    relation = version_relation(target_version, remote)
    if relation is VersionRelation.EQUAL:
        return PanelBuildIntent.SAME_RELEASE
    if relation is VersionRelation.HIGHER:
        return PanelBuildIntent.NEW_RELEASE
    return PanelBuildIntent.LOCAL


def available_intents(
    target_version: str,
    remote: RemoteReleaseInfo,
) -> frozenset[PanelBuildIntent]:
    """Return intents that can be selected without violating version policy."""

    relation = version_relation(target_version, remote)
    intents = {PanelBuildIntent.LOCAL}
    if relation is VersionRelation.EQUAL:
        intents.add(PanelBuildIntent.SAME_RELEASE)
    elif relation is VersionRelation.HIGHER:
        intents.add(PanelBuildIntent.NEW_RELEASE)
    return frozenset(intents)


def resolve_panel_intent(
    intent: PanelBuildIntent,
    target_version: str,
    remote: RemoteReleaseInfo,
) -> PanelModeResolution:
    """Map one panel intent to the existing core release-mode contract."""

    normalize_version(target_version)
    relation = version_relation(target_version, remote)
    if intent is PanelBuildIntent.LOCAL:
        if relation is VersionRelation.LOWER:
            return PanelModeResolution(ReleaseMode.LOCAL_DEBUG, False, False)
        if relation is VersionRelation.EQUAL:
            return PanelModeResolution(ReleaseMode.LOCAL_REBUILD, False, False)
        return PanelModeResolution(ReleaseMode.OFFLINE_DEBUG, False, True)
    if (
        intent is PanelBuildIntent.SAME_RELEASE
        and relation is VersionRelation.EQUAL
    ):
        return PanelModeResolution(
            ReleaseMode.SAME_RELEASE_REPAIR,
            True,
            False,
        )
    if (
        intent is PanelBuildIntent.NEW_RELEASE
        and relation is VersionRelation.HIGHER
    ):
        return PanelModeResolution(ReleaseMode.NEW_RELEASE, False, False)
    raise ValueError(
        "selected panel mode is incompatible with target version"
    )


def option_defaults(intent: PanelBuildIntent) -> PanelOptionDefaults:
    """Return immutable first-entry defaults for one panel intent."""

    if intent is PanelBuildIntent.SAME_RELEASE:
        return _SAME_RELEASE_DEFAULTS
    if intent is PanelBuildIntent.NEW_RELEASE:
        return _NEW_RELEASE_DEFAULTS
    return _LOCAL_DEFAULTS


__all__ = [
    "PanelBuildIntent",
    "PanelModeResolution",
    "PanelOptionDefaults",
    "VersionRelation",
    "available_intents",
    "option_defaults",
    "recommended_intent",
    "resolve_panel_intent",
    "version_relation",
]
