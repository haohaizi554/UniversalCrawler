import sys

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.models import BuildRequest, ReleaseMode, RemoteReleaseInfo
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


def test_remote_unknown_blocks_remote_writes():
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.unavailable("timeout"),
        upload_release_assets=True,
    )

    assert "remote release state is unknown" in validate_build_request(request)


def test_dry_run_rejects_every_side_effecting_option():
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=True,
        sign_manifest=True,
        commit_version_changes=True,
        upload_release_assets=True,
    )

    errors = validate_build_request(request)

    assert "dry run cannot sign manifests" in errors
    assert "dry run cannot commit version changes" in errors
    assert "dry run cannot upload release assets" in errors
