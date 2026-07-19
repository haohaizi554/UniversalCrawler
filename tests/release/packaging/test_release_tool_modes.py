import sys
from dataclasses import FrozenInstanceError, replace

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.models import (
    BuildRequest,
    PreflightResult,
    ReleaseMode,
    ReleaseResult,
    ReleaseStage,
    RemoteReleaseInfo,
)
from release_tool.modes import resolve_release_mode, validate_build_request


@pytest.mark.parametrize(
    ("target", "remote", "repair", "offline", "expected"),
    [
        ("3.6.20", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.LOCAL_DEBUG),
        ("3.6.21", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.LOCAL_REBUILD),
        (
            "3.6.21",
            RemoteReleaseInfo.available("3.6.21"),
            True,
            False,
            ReleaseMode.SAME_RELEASE_REPAIR,
        ),
        ("3.6.22", RemoteReleaseInfo.available("3.6.21"), False, False, ReleaseMode.NEW_RELEASE),
        (
            "3.6.22",
            RemoteReleaseInfo.unavailable("timeout"),
            False,
            True,
            ReleaseMode.OFFLINE_DEBUG,
        ),
    ],
)
def test_release_mode_matrix(target, remote, repair, offline, expected):
    assert (
        resolve_release_mode(
            target,
            remote,
            same_release_repair=repair,
            offline_debug=offline,
        )
        is expected
    )


def test_remote_unknown_blocks_every_non_offline_request():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.unavailable("timeout"),
    )

    assert validate_build_request(request) == ("remote release state is unknown",)


def test_offline_debug_explicitly_allows_unknown_remote_state():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.unavailable("timeout"),
        offline_debug=True,
    )

    assert (
        resolve_release_mode(
            request.target_version,
            request.remote,
            same_release_repair=request.same_release_repair,
            offline_debug=request.offline_debug,
        )
        is ReleaseMode.OFFLINE_DEBUG
    )
    assert validate_build_request(request) == ()


@pytest.mark.parametrize("target", ("3.6.20", "3.6.22"))
def test_same_release_repair_requires_equal_target_and_remote_versions(target):
    request = BuildRequest(
        target_version=target,
        remote=RemoteReleaseInfo.available("3.6.21"),
        same_release_repair=True,
    )

    assert validate_build_request(request) == (
        "same release repair requires target version to equal remote version",
    )


@pytest.mark.parametrize(
    ("target", "remote", "offline", "mode"),
    [
        ("3.6.20", RemoteReleaseInfo.available("3.6.21"), False, ReleaseMode.LOCAL_DEBUG),
        ("3.6.21", RemoteReleaseInfo.available("3.6.21"), False, ReleaseMode.LOCAL_REBUILD),
        ("3.6.22", RemoteReleaseInfo.unavailable("timeout"), True, ReleaseMode.OFFLINE_DEBUG),
    ],
)
@pytest.mark.parametrize(
    ("option", "label"),
    [
        ("push_main", "push main"),
        ("create_or_reuse_tag", "create or reuse tags"),
        ("create_or_update_release", "create or update releases"),
        ("upload_release_assets", "upload release assets"),
        ("upload_public_key", "upload public keys"),
    ],
)
def test_local_modes_reject_each_remote_write_option(target, remote, offline, mode, option, label):
    options = {option: True}
    if option == "upload_release_assets":
        options.update(
            build_installer=True,
            sign_manifest=True,
            private_key_path="private.pem",
            create_or_update_release=True,
            verify_remote_assets=True,
        )
    request = BuildRequest(
        target_version=target,
        remote=remote,
        offline_debug=offline,
        **options,
    )

    assert f"{mode.value} mode cannot {label}" in validate_build_request(request)


def test_trust_anchor_rotation_requires_key_generation_and_installer_rebuild():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        rotate_trust_anchor=True,
        build_installer=False,
    )

    assert validate_build_request(request) == (
        "rotating the trust anchor requires generating a manifest key",
        "rotating the trust anchor requires building the installer",
    )


def test_upload_release_assets_requires_the_complete_upload_bundle():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        upload_release_assets=True,
        build_installer=False,
    )

    assert validate_build_request(request) == (
        "upload release assets requires signing the manifest",
        "upload release assets requires a private key",
        "upload release assets requires creating or updating the release",
        "upload release assets requires remote asset verification",
        "upload release assets requires building the installer",
        "new release signing requires committing applied version changes",
        "new release signing requires creating or reusing the release tag",
    )


def test_upload_release_assets_accepts_the_complete_upload_bundle():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        upload_release_assets=True,
        build_installer=True,
        sign_manifest=True,
        private_key_path="private.pem",
        release_notes_path="notes.md",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        verify_remote_assets=True,
    )

    assert validate_build_request(request) == ()


@pytest.mark.parametrize("dry_run", [False, True])
def test_creating_or_updating_a_release_requires_notes_in_every_execution_mode(dry_run):
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=dry_run,
        create_or_update_release=True,
    )

    assert "creating or updating a release requires release notes" in validate_build_request(request)


def test_new_release_tag_for_an_applied_version_commit_requires_pushing_main():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=True,
        commit_version_changes=True,
        create_or_reuse_tag=True,
    )

    assert validate_build_request(request) == (
        "new release tag for an applied version commit requires pushing main",
    )


def test_new_release_publication_requires_the_complete_formal_chain():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        create_or_update_release=True,
    )

    errors = validate_build_request(request)

    assert {
        "new release publication requires applying version changes",
        "new release publication requires committing version changes",
        "new release publication requires pushing main",
        "new release publication requires creating or reusing the release tag",
        "new release publication requires building portable artifacts",
        "new release publication requires building installer artifacts",
        "new release publication requires signing the manifest",
        "new release publication requires smoke testing",
        "new release publication requires uploading release assets",
        "new release publication requires remote asset verification",
    }.issubset(errors)


@pytest.mark.parametrize(
    ("omitted", "message"),
    [
        ("upload_release_assets", "new release publication requires uploading release assets"),
        ("verify_remote_assets", "new release publication requires remote asset verification"),
    ],
)
def test_new_release_publication_rejects_omitted_upload_or_verification(omitted, message):
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        private_key_path="private.pem",
        sign_manifest=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    assert message in validate_build_request(replace(request, **{omitted: False}))


def test_upload_public_key_requires_a_release_and_remote_verification():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        upload_public_key=True,
    )

    assert validate_build_request(request) == (
        "upload public key requires creating or updating the release",
        "upload public key requires remote asset verification",
    )


def test_models_normalize_versions_and_are_frozen():
    remote = RemoteReleaseInfo.available(" v3.6.22 ")
    request = BuildRequest(target_version="3.6.22", remote=remote)
    preflight = PreflightResult(mode=ReleaseMode.NEW_RELEASE)
    result = ReleaseResult(mode=ReleaseMode.NEW_RELEASE, stage=ReleaseStage.SUCCEEDED)

    assert remote.version == "3.6.22"
    assert request.remote.version == "3.6.22"
    assert preflight.is_ready
    assert result.succeeded
    with pytest.raises(FrozenInstanceError):
        request.target_version = "3.6.23"
    with pytest.raises(FrozenInstanceError):
        remote.version = "3.6.23"
    with pytest.raises(FrozenInstanceError):
        preflight.errors = ("failed",)
    with pytest.raises(FrozenInstanceError):
        result.stage = ReleaseStage.FAILED


def test_dry_run_rejects_every_side_effecting_option():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=True,
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        sign_manifest=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        upload_public_key=True,
        private_key_path="private.pem",
        release_notes_path="notes.md",
        verify_remote_assets=True,
    )

    assert validate_build_request(request) == (
        "dry run cannot apply version changes",
        "dry run cannot build portable artifacts",
        "dry run cannot build installer artifacts",
        "dry run cannot run smoke tests",
        "dry run cannot generate manifest keys",
        "dry run cannot rotate trust anchors",
        "dry run cannot sign manifests",
        "dry run cannot commit version changes",
        "dry run cannot push main",
        "dry run cannot create or reuse tags",
        "dry run cannot create or update releases",
        "dry run cannot upload release assets",
        "dry run cannot upload public keys",
    )


def test_validation_errors_have_deterministic_cross_rule_precedence():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.unavailable("timeout"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        dry_run=True,
        apply_version=False,
        rotate_trust_anchor=True,
        sign_manifest=True,
        upload_release_assets=True,
    )

    assert validate_build_request(request) == (
        "remote release state is unknown",
        "upload release assets requires a private key",
        "upload release assets requires creating or updating the release",
        "upload release assets requires remote asset verification",
        "upload release assets requires building the installer",
        "rotating the trust anchor requires generating a manifest key",
        "rotating the trust anchor requires building the installer",
        "dry run cannot rotate trust anchors",
        "dry run cannot sign manifests",
        "dry run cannot upload release assets",
    )


def test_smoke_tests_require_a_portable_build_in_the_same_request():
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=True,
    )

    assert "smoke tests require building portable artifacts" in validate_build_request(request)


def test_new_release_signing_requires_a_persistent_version_commit_and_tag():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        run_smoke_tests=False,
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
    )

    errors = validate_build_request(request)

    assert "new release signing requires committing applied version changes" in errors
    assert "new release signing requires creating or reusing the release tag" in errors
