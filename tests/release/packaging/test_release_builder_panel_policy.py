from __future__ import annotations

import sys

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))

from release_tool.models import ReleaseMode, RemoteReleaseInfo
from release_tool.panel_policy import (
    PanelBuildIntent,
    VersionRelation,
    available_intents,
    option_defaults,
    recommended_intent,
    resolve_panel_intent,
    version_relation,
)


@pytest.mark.parametrize(
    ("target", "remote", "expected"),
    (
        (
            "3.6.20",
            RemoteReleaseInfo.available("3.6.21"),
            VersionRelation.LOWER,
        ),
        (
            "3.6.21",
            RemoteReleaseInfo.available("3.6.21"),
            VersionRelation.EQUAL,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.available("3.6.21"),
            VersionRelation.HIGHER,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.unknown(),
            VersionRelation.UNKNOWN,
        ),
    ),
)
def test_version_relation_compares_normalized_versions(target, remote, expected):
    assert version_relation(target, remote) is expected


@pytest.mark.parametrize(
    ("target", "remote", "expected"),
    (
        (
            "3.6.20",
            RemoteReleaseInfo.available("3.6.21"),
            PanelBuildIntent.LOCAL,
        ),
        (
            "3.6.21",
            RemoteReleaseInfo.available("3.6.21"),
            PanelBuildIntent.SAME_RELEASE,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.available("3.6.21"),
            PanelBuildIntent.NEW_RELEASE,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.unknown(),
            PanelBuildIntent.LOCAL,
        ),
    ),
)
def test_recommended_intent_follows_version_relation(target, remote, expected):
    assert recommended_intent(target, remote) is expected


def test_available_intents_always_include_local_and_gate_publication():
    remote = RemoteReleaseInfo.available("3.6.21")

    assert available_intents("3.6.20", remote) == frozenset(
        {PanelBuildIntent.LOCAL}
    )
    assert available_intents("3.6.21", remote) == frozenset(
        {
            PanelBuildIntent.LOCAL,
            PanelBuildIntent.SAME_RELEASE,
        }
    )
    assert available_intents("3.6.22", remote) == frozenset(
        {
            PanelBuildIntent.LOCAL,
            PanelBuildIntent.NEW_RELEASE,
        }
    )


@pytest.mark.parametrize(
    ("target", "remote", "release_mode", "offline"),
    (
        (
            "3.6.20",
            RemoteReleaseInfo.available("3.6.21"),
            ReleaseMode.LOCAL_DEBUG,
            False,
        ),
        (
            "3.6.21",
            RemoteReleaseInfo.available("3.6.21"),
            ReleaseMode.LOCAL_REBUILD,
            False,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.available("3.6.21"),
            ReleaseMode.OFFLINE_DEBUG,
            True,
        ),
        (
            "3.6.22",
            RemoteReleaseInfo.unknown(),
            ReleaseMode.OFFLINE_DEBUG,
            True,
        ),
    ),
)
def test_local_intent_maps_to_a_non_publishing_core_mode(
    target,
    remote,
    release_mode,
    offline,
):
    resolution = resolve_panel_intent(
        PanelBuildIntent.LOCAL,
        target,
        remote,
    )

    assert resolution.release_mode is release_mode
    assert resolution.same_release_repair is False
    assert resolution.offline_debug is offline


def test_same_release_and_new_release_map_to_existing_core_modes():
    same_release = resolve_panel_intent(
        PanelBuildIntent.SAME_RELEASE,
        "3.6.21",
        RemoteReleaseInfo.available("3.6.21"),
    )
    new_release = resolve_panel_intent(
        PanelBuildIntent.NEW_RELEASE,
        "3.6.22",
        RemoteReleaseInfo.available("3.6.21"),
    )

    assert same_release.release_mode is ReleaseMode.SAME_RELEASE_REPAIR
    assert same_release.same_release_repair is True
    assert same_release.offline_debug is False
    assert new_release.release_mode is ReleaseMode.NEW_RELEASE
    assert new_release.same_release_repair is False
    assert new_release.offline_debug is False


@pytest.mark.parametrize(
    ("intent", "target"),
    (
        (PanelBuildIntent.SAME_RELEASE, "3.6.20"),
        (PanelBuildIntent.SAME_RELEASE, "3.6.22"),
        (PanelBuildIntent.NEW_RELEASE, "3.6.20"),
        (PanelBuildIntent.NEW_RELEASE, "3.6.21"),
    ),
)
def test_incompatible_publication_intent_is_rejected(intent, target):
    with pytest.raises(ValueError, match="incompatible"):
        resolve_panel_intent(
            intent,
            target,
            RemoteReleaseInfo.available("3.6.21"),
        )


def test_local_defaults_never_enable_signing_or_remote_writes():
    defaults = option_defaults(PanelBuildIntent.LOCAL)

    assert defaults.apply_version is True
    assert defaults.build_portable is True
    assert defaults.build_installer is True
    assert defaults.run_smoke_tests is True
    assert defaults.sign_manifest is False
    assert defaults.commit_version_changes is False
    assert defaults.push_main is False
    assert defaults.create_or_reuse_tag is False
    assert defaults.create_or_update_release is False
    assert defaults.upload_release_assets is False
    assert defaults.upload_public_key is False
    assert defaults.verify_remote_assets is False
    assert defaults.generate_manifest_key is False
    assert defaults.rotate_trust_anchor is False


def test_same_release_defaults_publish_without_source_version_commit():
    defaults = option_defaults(PanelBuildIntent.SAME_RELEASE)

    assert defaults.apply_version is False
    assert defaults.sign_manifest is True
    assert defaults.commit_version_changes is False
    assert defaults.push_main is True
    assert defaults.create_or_reuse_tag is True
    assert defaults.create_or_update_release is True
    assert defaults.upload_release_assets is True
    assert defaults.upload_public_key is True
    assert defaults.verify_remote_assets is True
    assert defaults.generate_manifest_key is False
    assert defaults.rotate_trust_anchor is False


def test_new_release_defaults_enable_complete_publication_chain():
    defaults = option_defaults(PanelBuildIntent.NEW_RELEASE)

    assert defaults.sign_manifest is True
    assert defaults.commit_version_changes is True
    assert defaults.push_main is True
    assert defaults.create_or_reuse_tag is True
    assert defaults.create_or_update_release is True
    assert defaults.upload_release_assets is True
    assert defaults.upload_public_key is True
    assert defaults.verify_remote_assets is True
    assert defaults.generate_manifest_key is False
    assert defaults.rotate_trust_anchor is False
