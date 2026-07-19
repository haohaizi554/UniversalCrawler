"""Tests for idempotent, redacted GitHub CLI release publishing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.publisher import (
    GitHubReleasePublisher,
    PublishError,
    ReleaseAssetInfo,
)


def write_asset(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def completed(argv, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def make_publisher(run_process, output=None, **kwargs):
    return GitHubReleasePublisher(
        "haohaizi554/UniversalCrawler",
        environment={"HTTPS_PROXY": "http://alice:secret@proxy.example:8080"},
        output=output or (lambda _line: None),
        run_process=run_process,
        project_root=PROJECT_ROOT,
        **kwargs,
    )


def test_publisher_uses_argument_arrays_and_never_shell(tmp_path):
    run = Mock(return_value=completed([], stdout=""))
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "v3.6.22", tmp_path / "notes.md", repair=False)

    args, kwargs = run.call_args
    assert args[0][:3] == ["gh", "release", "create"]
    assert kwargs["shell"] is False
    assert "--notes-file" in args[0]
    assert kwargs["env"] is not publisher.environment
    assert kwargs["cwd"] == str(PROJECT_ROOT)


def test_publisher_redacts_subprocess_output_and_raises_for_nonzero_exit():
    lines = []
    run = Mock(
        return_value=completed(
            [],
            stderr="Authorization: Bearer ghp_supersecret\nHTTPS_PROXY=http://alice:secret@proxy.example",
            returncode=23,
        )
    )
    publisher = make_publisher(run, output=lines.append)

    with pytest.raises(PublishError, match="exit code 23"):
        publisher.ensure_release("v3.6.22", "v3.6.22", Path("notes.md"), repair=False)

    assert "supersecret" not in "\n".join(lines)
    assert "alice:secret" not in "\n".join(lines)
    assert all("[REDACTED]" in line for line in lines)


def test_upload_skips_remote_asset_with_same_name_size_and_hash(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo.from_path(asset)
    run = Mock(return_value=completed([], stdout=json.dumps({"assets": [remote_asset.to_json()]})))
    publisher = make_publisher(run)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert publisher.executed_uploads == []
    assert run.call_count == 1


def test_upload_rejects_mismatched_asset_without_repair(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"local")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size, digest="sha256:" + "0" * 64)
    run = Mock(return_value=completed([], stdout=json.dumps({"assets": [remote_asset.to_json()]})))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="requires repair"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1


def test_upload_repairs_mismatched_asset_with_explicit_clobber(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"local")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size, digest="sha256:" + "0" * 64)
    run = Mock(
        side_effect=[
            completed([], stdout=json.dumps({"assets": [remote_asset.to_json()]})),
            completed([]),
        ]
    )
    publisher = make_publisher(run)

    publisher.upload_assets("v3.6.22", [asset], repair=True)

    assert run.call_args_list[1].args[0][-1] == "--clobber"


def test_upload_requires_repair_when_remote_digest_is_unavailable(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size)
    run = Mock(return_value=completed([], stdout=json.dumps({"assets": [remote_asset.to_json()]})))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="digest is unavailable.*repair"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)


def test_ensure_release_creates_normally_and_repairs_with_an_explicit_edit(tmp_path):
    notes = tmp_path / "notes.md"
    run = Mock(side_effect=[completed([]), completed([])])
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    publisher.ensure_release("v3.6.22", "Release", notes, repair=True)

    assert run.call_args_list[0].args[0][:3] == ["gh", "release", "create"]
    assert run.call_args_list[1].args[0][:3] == ["gh", "release", "edit"]
    assert "--notes-file" in run.call_args_list[1].args[0]


def test_ensure_release_treats_an_existing_release_as_idempotent(tmp_path):
    run = Mock(return_value=completed([], stderr="release already exists", returncode=1))
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", tmp_path / "notes.md", repair=False)

    assert run.call_args.args[0][:3] == ["gh", "release", "create"]


def test_ensure_tag_is_idempotent_and_rejects_conflicting_commit():
    run = Mock(side_effect=[completed([], stdout="a" * 40), completed([], stdout="b" * 40)])
    publisher = make_publisher(run)

    publisher.ensure_tag("v3.6.22", "a" * 40)
    with pytest.raises(PublishError, match="different commit"):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    assert run.call_count == 2


def test_ensure_tag_creates_missing_tag():
    run = Mock(side_effect=[completed([], stderr="HTTP 404", returncode=1), completed([])])
    publisher = make_publisher(run)

    publisher.ensure_tag("v3.6.22", "a" * 40)

    assert run.call_args_list[1].args[0][:3] == ["gh", "api", "repos/haohaizi554/UniversalCrawler/git/refs"]


def test_verify_assets_rejects_missing_or_unverifiable_digest(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size)
    run = Mock(return_value=completed([], stdout=json.dumps({"assets": [remote_asset.to_json()]})))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="digest is unavailable"):
        publisher.verify_assets("v3.6.22", [asset])


def test_remote_asset_parse_failure_is_not_treated_as_an_empty_release():
    run = Mock(return_value=completed([], stdout="not-json"))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="invalid release asset response"):
        publisher.verify_assets("v3.6.22", [])
