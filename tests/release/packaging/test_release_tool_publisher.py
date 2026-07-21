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


def write_notes(path: Path) -> Path:
    path.write_text("release notes\n", encoding="utf-8")
    return path


def completed(argv, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def release_payload(tag="v3.6.22", *, assets=()):
    return {"tag_name": tag, "assets": list(assets)}


def releases_response(*releases):
    if not releases:
        return completed([], stdout="HTTP/2 404 Not Found\r\n\r\n{}", returncode=1)
    assert len(releases) == 1
    return completed([], stdout=f"HTTP/2 200 OK\r\n\r\n{json.dumps(releases[0])}")


def tags_response(*refs):
    return completed([], stdout=json.dumps(list(refs)))


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
    notes = write_notes(tmp_path / "notes.md")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "v3.6.22", notes, repair=False)

    args, kwargs = run.call_args_list[1]
    assert args[0][:3] == ["gh", "release", "create"]
    assert kwargs["shell"] is False
    assert "--notes-file" in args[0]
    assert "--verify-tag" in args[0]
    assert args[0][args[0].index("--repo") + 1] == "github.com/haohaizi554/UniversalCrawler"
    assert args[0][args[0].index("--") + 1] == "v3.6.22"
    assert kwargs["env"] is not publisher.environment
    assert kwargs["cwd"] == str(PROJECT_ROOT)
    assert kwargs["timeout"] == 60.0
    assert any("releases/tags/v3.6.22" in value for value in run.call_args_list[0].args[0])


def test_publisher_redacts_subprocess_output_and_raises_for_nonzero_exit(tmp_path):
    lines = []
    run = Mock(
        return_value=completed(
            [],
            stderr=(
                "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----\n"
                "Authorization: Bearer ghp_supersecret\n"
                "HTTPS_PROXY=http://alice:secret@proxy.example"
            ),
            returncode=23,
        )
    )
    publisher = make_publisher(run, output=lines.append)

    with pytest.raises(PublishError, match="^GitHub command failed$"):
        publisher.ensure_release(
            "v3.6.22",
            "v3.6.22",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert "supersecret" not in "\n".join(lines)
    assert "alice:secret" not in "\n".join(lines)
    assert "private-material" not in "\n".join(lines)
    assert "[REDACTED]" in "\n".join(lines)


def test_publisher_converts_subprocess_timeout_to_generic_publish_error(tmp_path):
    lines = []
    run = Mock(
        side_effect=subprocess.TimeoutExpired(
            "gh",
            30,
            output=b"-----BEGIN PRIVATE KEY-----\nsecret-key\n-----END PRIVATE KEY-----",
            stderr=b"Authorization: Bearer ghp_timeoutsecret",
        )
    )
    publisher = make_publisher(run, output=lines.append)

    with pytest.raises(PublishError, match="^GitHub command failed$") as caught:
        publisher.ensure_release("v3.6.22", "Release", write_notes(tmp_path / "notes.md"), repair=False)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "secret-key" not in "\n".join(lines)
    assert "timeoutsecret" not in "\n".join(lines)


def test_invalid_json_does_not_retain_raw_response_exception():
    lines = []
    run = Mock(return_value=completed([], stdout='HTTP/2 200 OK\r\n\r\n{"token":"ghp_jsonsecret"'))
    publisher = make_publisher(run, output=lines.append)

    with pytest.raises(PublishError) as caught:
        publisher.verify_assets("v3.6.22", [])

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "jsonsecret" not in "\n".join(lines)


def test_upload_skips_remote_asset_with_same_name_size_and_hash(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo.from_path(asset)
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset.to_json()])))
    publisher = make_publisher(run)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert publisher.executed_uploads == []
    assert run.call_count == 1


def test_upload_rejects_mismatched_asset_without_repair(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"local")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size, digest="sha256:" + "0" * 64)
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset.to_json()])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="immutable release requires a new revision"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1


def test_upload_never_clobbers_mismatched_asset_even_with_legacy_repair_flag(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"local")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size, digest="sha256:" + "0" * 64)
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset.to_json()])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="immutable release requires a new revision"):
        publisher.upload_assets("v3.6.22", [asset], repair=True)

    assert run.call_count == 1
    assert "--clobber" not in " ".join(run.call_args.args[0])


@pytest.mark.parametrize("repair", (False, True))
def test_upload_rejects_remote_asset_when_digest_is_unavailable(tmp_path, repair):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size)
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset.to_json()])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="digest is unavailable.*new revision"):
        publisher.upload_assets("v3.6.22", [asset], repair=repair)


@pytest.mark.parametrize("repair", (False, True))
def test_ensure_release_create_paths_verify_existing_tag_and_re_read_structured_state(tmp_path, repair):
    notes = write_notes(tmp_path / "notes.md")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([], stderr="unstructured race output", returncode=1),
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=repair)

    create = run.call_args_list[1].args[0]
    assert create[:3] == ["gh", "release", "create"]
    assert "--verify-tag" in create
    assert "--notes-file" in create
    assert run.call_args_list[2].args[0][:2] == ["gh", "api"]


def test_ensure_release_treats_an_existing_release_as_idempotent(tmp_path):
    run = Mock(return_value=releases_response(release_payload()))
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", write_notes(tmp_path / "notes.md"), repair=False)

    assert run.call_args.args[0][:2] == ["gh", "api"]
    assert run.call_count == 1


def test_ensure_release_never_edits_existing_release_with_legacy_repair_flag(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    run = Mock(return_value=releases_response(release_payload()))
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=True)

    assert run.call_count == 1
    assert "edit" not in run.call_args.args[0]


def test_publisher_accepts_canonical_same_version_revision_tag(tmp_path):
    run = Mock(return_value=releases_response(release_payload("v3.6.22-r3")))
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22-r3",
        "Release revision 3",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    assert run.call_count == 1


def test_ensure_tag_is_idempotent_and_rejects_conflicting_commit():
    run = Mock(
        side_effect=[
            tags_response({"ref": "refs/tags/v3.6.22", "object": {"type": "commit", "sha": "a" * 40}}),
            tags_response({"ref": "refs/tags/v3.6.22", "object": {"type": "commit", "sha": "b" * 40}}),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_tag("v3.6.22", "a" * 40)
    with pytest.raises(PublishError, match="^GitHub command failed$"):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    assert run.call_count == 2


def test_ensure_tag_creates_missing_tag():
    tag = {"ref": "refs/tags/v3.6.22", "object": {"type": "commit", "sha": "a" * 40}}
    run = Mock(side_effect=[tags_response(), completed([], returncode=1), tags_response(tag)])
    publisher = make_publisher(run)

    publisher.ensure_tag("v3.6.22", "a" * 40)

    create = run.call_args_list[1].args[0]
    assert create[:2] == ["gh", "api"]
    assert "--hostname" in create
    assert create[create.index("--hostname") + 1] == "github.com"


def test_ensure_tag_requires_a_canonical_full_commit_sha():
    run = Mock()
    publisher = make_publisher(run)

    with pytest.raises(ValueError, match="full commit SHA"):
        publisher.ensure_tag("v3.6.22", "a" * 12)

    run.assert_not_called()


@pytest.mark.parametrize(
    "tag",
    ("-v3", "v..3", "v@{3", "v\\3", "v3.", "v3.lock", "v/3", "v3.6.22#x", "v3.6.22%2f", "v{3}"),
)
def test_ensure_tag_rejects_unsafe_refs(tag):
    run = Mock()
    publisher = make_publisher(run)

    with pytest.raises(ValueError, match="invalid release tag"):
        publisher.ensure_tag(tag, "a" * 40)

    run.assert_not_called()


def test_version_tag_is_normalized_and_percent_encoded_in_api_paths():
    tag = {"ref": "refs/tags/v3.6.22", "object": {"type": "commit", "sha": "a" * 40}}
    run = Mock(return_value=tags_response(tag))
    publisher = make_publisher(run)

    publisher.ensure_tag("v3.6.22", "a" * 40)

    endpoint = run.call_args.args[0][run.call_args.args[0].index("GET") + 1]
    assert endpoint.endswith("tags/v3.6.22")


@pytest.mark.parametrize("repository", ("owner", "owner/repo/extra", "./repo", "owner/..", "-owner/repo"))
def test_publisher_rejects_unsafe_repository_components(repository):
    with pytest.raises(ValueError, match="invalid GitHub repository"):
        GitHubReleasePublisher(repository, environment={}, output=lambda _line: None)


def test_publisher_pins_commands_to_github_and_removes_gh_host(tmp_path):
    run = Mock(return_value=releases_response(release_payload()))
    publisher = GitHubReleasePublisher(
        "haohaizi554/UniversalCrawler",
        environment={"GH_HOST": "attacker.example", "gh_host": "also-attacker.example"},
        output=lambda _line: None,
        run_process=run,
        project_root=PROJECT_ROOT,
    )

    publisher.ensure_release("v3.6.22", "Release", write_notes(tmp_path / "notes.md"), repair=False)

    (argv,), kwargs = run.call_args
    assert "--hostname" in argv
    assert argv[argv.index("--hostname") + 1] == "github.com"
    assert "GH_HOST" not in kwargs["env"]
    assert "gh_host" not in kwargs["env"]


def test_verify_assets_rejects_missing_or_unverifiable_digest(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo(name="installer.exe", size=asset.stat().st_size)
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset.to_json()])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="digest is unavailable"):
        publisher.verify_assets("v3.6.22", [asset])


def test_remote_asset_parse_failure_is_not_treated_as_an_empty_release():
    run = Mock(return_value=completed([], stdout="not-json"))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="invalid release asset response"):
        publisher.verify_assets("v3.6.22", [])


def test_remote_asset_duplicate_names_are_rejected_before_lookup_collapse(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(return_value=releases_response(release_payload(assets=[remote_asset, remote_asset])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="duplicate release asset"):
        publisher.verify_assets("v3.6.22", [asset])


def test_upload_requires_regular_absolute_assets_and_uses_boundary(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    run = Mock(side_effect=[releases_response(release_payload()), completed([])])
    publisher = make_publisher(run)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    upload = run.call_args_list[1].args[0]
    assert upload[upload.index("--") + 2] == str(asset.resolve())
    assert "--repo" in upload


def test_upload_rechecks_asset_snapshot_before_invoking_cli(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")

    def release_read(*_args, **_kwargs):
        asset.write_bytes(b"mutated before upload")
        return releases_response(release_payload())

    run = Mock(side_effect=release_read)
    publisher = make_publisher(run)

    with pytest.raises(ValueError, match="changed before upload"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1


def test_upload_rechecks_asset_snapshot_after_cli_returns(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")

    def upload(*_args, **_kwargs):
        asset.write_bytes(b"mutated after upload")
        return completed([])

    calls = 0

    def run_process(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return releases_response(release_payload())
        return upload(*args, **kwargs)

    run = Mock(side_effect=run_process)
    publisher = make_publisher(run)

    with pytest.raises(ValueError, match="changed after upload"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)


@pytest.mark.parametrize("keyword", ("metadata_timeout_seconds", "upload_timeout_seconds"))
def test_publisher_rejects_invalid_operation_timeout(keyword):
    with pytest.raises(ValueError, match="timeout"):
        make_publisher(Mock(), **{keyword: float("inf")})


@pytest.mark.parametrize("name", ("installer#label.exe", "directory"))
def test_upload_rejects_ambiguous_or_non_regular_assets(tmp_path, name):
    path = tmp_path / name
    if name == "directory":
        path.mkdir()
    else:
        write_asset(path, b"same")
    run = Mock()
    publisher = make_publisher(run)

    with pytest.raises(ValueError, match="release asset"):
        publisher.upload_assets("v3.6.22", [path], repair=False)

    run.assert_not_called()


def test_asset_hash_rejects_file_mutation_during_streaming(tmp_path, monkeypatch):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    original_sha256 = __import__("release_tool.publisher", fromlist=["hashlib"]).hashlib.sha256

    class MutatingHasher:
        def __init__(self):
            self._inner = original_sha256()

        def update(self, chunk):
            asset.write_bytes(b"changed after snapshot")
            self._inner.update(chunk)

        def hexdigest(self):
            return self._inner.hexdigest()

    monkeypatch.setattr("release_tool.publisher.hashlib.sha256", MutatingHasher)

    with pytest.raises(ValueError, match="changed while hashing"):
        ReleaseAssetInfo.from_path(asset)


@pytest.mark.parametrize("notes", ("-", "missing.md"))
def test_ensure_release_rejects_unreadable_or_stream_release_notes(tmp_path, notes):
    run = Mock()
    publisher = make_publisher(run)
    path = notes if notes == "-" else tmp_path / notes

    with pytest.raises(ValueError, match="release notes"):
        publisher.ensure_release("v3.6.22", "Release", path, repair=False)

    run.assert_not_called()
