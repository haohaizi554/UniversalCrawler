"""Tests for idempotent, redacted GitHub CLI release publishing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool import publisher as publisher_module
from release_tool.publisher import (
    GitHubReleasePublisher,
    PublishError,
    ReleaseAssetInfo,
    ReleaseUploadProgress,
)
from release_tool.upload_transport import UploadTransportError


def write_asset(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def write_notes(path: Path) -> Path:
    path.write_text("release notes\n", encoding="utf-8")
    return path


def completed(argv, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def release_payload(
    tag="v3.6.22",
    *,
    assets=(),
    draft=True,
    prerelease=False,
    include_asset_state=True,
    release_id=1,
    name="Release",
    body="release notes\n",
):
    remote_assets = []
    for asset in assets:
        remote_asset = dict(asset)
        if include_asset_state:
            remote_asset.setdefault("state", "uploaded")
        remote_assets.append(remote_asset)
    return {
        "id": release_id,
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
        "upload_url": (
            "https://uploads.github.com/repos/haohaizi554/UniversalCrawler/"
            f"releases/{release_id}/assets{{?name,label}}"
        ),
        "assets": remote_assets,
    }


def releases_response(*releases):
    return completed([], stdout=json.dumps(list(releases)))


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


def assert_pinned_publish_command(argv, *, release_id=1):
    assert argv[:2] == ["gh", "api"]
    assert argv[argv.index("--method") + 1] == "PATCH"
    assert f"repos/haohaizi554/UniversalCrawler/releases/{release_id}" in argv
    fields = [argv[index + 1] for index, value in enumerate(argv) if value == "-F"]
    assert fields == ["draft=false", "prerelease=false"]
    assert "release" not in argv[1:3]


def test_publisher_uses_argument_arrays_and_never_shell(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload(name="v3.6.22")),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "v3.6.22", notes, repair=False)

    args, kwargs = run.call_args_list[1]
    assert args[0][:3] == ["gh", "release", "create"]
    assert kwargs["shell"] is False
    assert "--notes-file" in args[0]
    assert "--verify-tag" in args[0]
    assert "--draft" in args[0]
    assert args[0][args[0].index("--repo") + 1] == "github.com/haohaizi554/UniversalCrawler"
    assert args[0][args[0].index("--") + 1] == "v3.6.22"
    assert kwargs["env"] is not publisher.environment
    assert kwargs["cwd"] == str(PROJECT_ROOT)
    assert kwargs["timeout"] == 60.0
    lookup = run.call_args_list[0].args[0]
    assert lookup[:2] == ["gh", "api"]
    assert "repos/haohaizi554/UniversalCrawler/releases?per_page=100&page=1" in lookup
    assert not any("releases/tags/" in value for value in lookup)


def test_verified_draft_requires_an_explicit_publish_after_every_asset_matches(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    manifest = write_asset(tmp_path / "latest.json", b"manifest")
    signature = write_asset(tmp_path / "latest.json.sig", b"signature")
    remote_assets = [
        ReleaseAssetInfo.from_path(path).to_json()
        for path in (installer, manifest, signature)
    ]
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            completed([]),
            releases_response(release_payload(assets=remote_assets, draft=False)),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    verified = publisher.verify_assets(
        "v3.6.22",
        [installer, manifest, signature],
    )

    assert [asset.name for asset in verified] == [
        "installer.exe",
        "latest.json",
        "latest.json.sig",
    ]
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )

    publisher.publish_release("v3.6.22")

    publish = run.call_args_list[3].args[0]
    assert_pinned_publish_command(publish)
    assert run.call_args_list[4].args[0][:2] == ["gh", "api"]


def test_publish_reconciles_timeout_when_release_is_already_public(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_assets = [ReleaseAssetInfo.from_path(installer).to_json()]
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            subprocess.TimeoutExpired("gh release edit", 60),
            releases_response(release_payload(assets=remote_assets, draft=False)),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    verified = publisher.verify_assets("v3.6.22", [installer])
    publisher.publish_release("v3.6.22")

    assert [asset.name for asset in verified] == ["installer.exe"]
    assert_pinned_publish_command(run.call_args_list[3].args[0])
    assert run.call_args_list[4].args[0][:2] == ["gh", "api"]


def test_publish_timeout_fails_when_remote_release_is_still_a_draft(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_assets = [ReleaseAssetInfo.from_path(installer).to_json()]
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            subprocess.TimeoutExpired("gh release edit", 60),
            releases_response(release_payload(assets=remote_assets)),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="GitHub command failed"):
        publisher.publish_release("v3.6.22")


def test_upload_failure_leaves_new_release_as_draft(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload()),
        ]
    )

    def fail_upload(_upload_url, _path, _on_progress):
        raise UploadTransportError("upload rejected", transient=False)

    publisher = make_publisher(run, upload_request=fail_upload)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    with patch("time.sleep"), pytest.raises(PublishError, match="GitHub command failed"):
        publisher.upload_assets("v3.6.22", [installer], repair=False)

    create = run.call_args_list[1].args[0]
    assert "--draft" in create
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )


def test_verify_failure_leaves_new_release_as_draft(tmp_path):
    notes = write_notes(tmp_path / "notes.md")
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload()),
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "Release", notes, repair=False)
    with pytest.raises(PublishError, match="missing"):
        publisher.verify_assets("v3.6.22", [installer])

    create = run.call_args_list[1].args[0]
    assert "--draft" in create
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )


def test_preparation_reuses_only_a_draft_and_rejects_an_existing_public_release(tmp_path):
    run = Mock(return_value=releases_response(release_payload(draft=False)))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="already public"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 1
    assert run.call_args.args[0][:2] == ["gh", "api"]


def test_preparation_never_reverts_a_release_observed_public_after_create(tmp_path):
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload(draft=False)),
        ]
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="became public"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert "--draft" in run.call_args_list[1].args[0]
    assert run.call_count == 3
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )


def test_preparation_fails_closed_on_malformed_post_create_state_without_edit(tmp_path):
    malformed = release_payload()
    malformed.pop("draft")
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(malformed),
        ]
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="invalid GitHub response"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 3
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )


def test_verification_rejects_an_unexpected_remote_asset(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    expected = ReleaseAssetInfo.from_path(installer).to_json()
    unexpected = ReleaseAssetInfo(
        name="old-installer.exe",
        size=3,
        digest="sha256:" + "1" * 64,
    ).to_json()
    run = Mock(
        return_value=releases_response(
            release_payload(assets=[expected, unexpected])
        )
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="unexpected"):
        publisher.verify_assets("v3.6.22", [installer])


def test_verification_rejects_an_unfinalized_remote_asset(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote = {**ReleaseAssetInfo.from_path(installer).to_json(), "state": "starter"}
    run = Mock(return_value=releases_response(release_payload(assets=[remote])))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="not finalized"):
        publisher.verify_assets("v3.6.22", [installer])


def test_verification_rejects_a_remote_asset_without_explicit_state(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        return_value=releases_response(
            release_payload(
                assets=[remote],
                include_asset_state=False,
            )
        )
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="invalid release asset response"):
        publisher.verify_assets("v3.6.22", [installer])


def test_public_release_missing_asset_is_not_repaired_in_place(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    uploaded: list[Path] = []

    def upload_request(_upload_url, path, _on_progress):
        uploaded.append(path)

    run = Mock(return_value=releases_response(release_payload(draft=False)))
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="published release is incomplete"):
        publisher.upload_assets("v3.6.22", [installer], repair=False)

    assert uploaded == []


def test_retry_reuses_a_complete_draft_and_skips_correct_assets_before_publish(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_assets = [ReleaseAssetInfo.from_path(installer).to_json()]
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            releases_response(release_payload(assets=remote_assets)),
            completed([]),
            releases_response(release_payload(assets=remote_assets, draft=False)),
        ]
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.upload_assets("v3.6.22", [installer], repair=False)
    verified = publisher.verify_assets("v3.6.22", [installer])
    publisher.publish_release("v3.6.22")

    assert [asset.name for asset in verified] == ["installer.exe"]
    upload_request.assert_not_called()
    assert_pinned_publish_command(run.call_args_list[4].args[0])
    assert run.call_args_list[5].args[0][:2] == ["gh", "api"]


def test_concurrent_public_asset_mismatch_is_immutable_and_never_edited(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[], draft=False)),
            completed([]),
            releases_response(release_payload(assets=[])),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="missing"):
        publisher.publish_release("v3.6.22")

    assert run.call_count == 3
    assert not any(
        call.args[0][:3] == ["gh", "release", "edit"] for call in run.call_args_list
    )


def test_publish_postcondition_failure_never_compensates_back_to_draft(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            completed([]),
            releases_response(release_payload(assets=[], draft=False)),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="missing"):
        publisher.publish_release("v3.6.22")

    assert_pinned_publish_command(run.call_args_list[3].args[0])
    assert run.call_count == 5
    assert all("--draft=true" not in call.args[0] for call in run.call_args_list)


def test_publish_confirmation_failure_never_compensates_back_to_draft(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    transient_failure = completed(
        [],
        stderr="error connecting to api.github.com: connection reset by peer",
        returncode=1,
    )
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            completed([]),
            transient_failure,
            transient_failure,
            transient_failure,
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with patch("time.sleep"), pytest.raises(PublishError, match="GitHub command failed"):
        publisher.publish_release("v3.6.22")

    assert_pinned_publish_command(run.call_args_list[3].args[0])
    assert run.call_count == 7
    assert all("--draft=true" not in call.args[0] for call in run.call_args_list)


def test_publish_missing_confirmation_never_compensates_back_to_draft(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            completed([]),
            releases_response(),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="GitHub command failed"):
        publisher.publish_release("v3.6.22")

    assert_pinned_publish_command(run.call_args_list[3].args[0])
    assert run.call_count == 5
    assert all("--draft=true" not in call.args[0] for call in run.call_args_list)


def test_publish_malformed_confirmation_never_compensates_back_to_draft(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    malformed = release_payload(assets=[remote_asset], draft=False)
    malformed.pop("draft")
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
            completed([]),
            releases_response(malformed),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="invalid GitHub response"):
        publisher.publish_release("v3.6.22")

    assert run.call_count == 5
    assert all("--draft=true" not in call.args[0] for call in run.call_args_list)


def test_publish_rejects_release_identity_change_after_edit(tmp_path):
    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        side_effect=[
            releases_response(
                release_payload(assets=[remote_asset], release_id=1)
            ),
            releases_response(
                release_payload(assets=[remote_asset], release_id=1)
            ),
            releases_response(
                release_payload(assets=[remote_asset], release_id=1)
            ),
            completed([]),
            releases_response(
                release_payload(
                    assets=[remote_asset],
                    draft=False,
                    release_id=2,
                )
            ),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])

    with pytest.raises(PublishError, match="release identity changed"):
        publisher.publish_release("v3.6.22")

    assert run.call_count == 5
    assert all("--draft=true" not in call.args[0] for call in run.call_args_list)


def test_publish_confirmation_error_cannot_replace_the_edit_error(tmp_path):
    class HostilePrimary(PublishError):
        def add_note(self, _note):
            raise RuntimeError("note lookup failed")

    class HostileSecondary(PublishError):
        def __str__(self):
            raise RuntimeError("string conversion failed")

    installer = write_asset(tmp_path / "installer.exe", b"installer")
    remote_asset = ReleaseAssetInfo.from_path(installer).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(assets=[remote_asset])),
            releases_response(release_payload(assets=[remote_asset])),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [installer])
    primary = HostilePrimary("publish edit failed")
    secondary = HostileSecondary("confirmation failed")

    with (
        patch.object(
            publisher,
            "_execute",
            side_effect=[primary, completed([])],
        ),
        patch.object(
            publisher,
            "_read_release",
            side_effect=[release_payload(assets=[remote_asset]), secondary, release_payload()],
        ),
    ):
        caught = None
        try:
            publisher.publish_release("v3.6.22")
        except BaseException as error:  # noqa: BLE001 - identity is the contract under test.
            caught = error

    assert caught is primary


def test_publisher_decodes_github_cli_output_as_utf8(tmp_path):
    """GitHub CLI 始终输出 UTF-8，不能交给 Windows 本地代码页猜测。"""
    run = Mock(
        return_value=releases_response(
            release_payload(name="\u4e2d\u6587\u4fee\u8ba2")
        )
    )
    publisher = make_publisher(run)

    publisher.ensure_release("v3.6.22", "中文修订", write_notes(tmp_path / "notes.md"), repair=False)

    kwargs = run.call_args.kwargs
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


def test_expected_missing_release_probe_does_not_flood_publish_log(tmp_path):
    """创建前的 404 属于正常分支，不应把响应头和错误正文展示给用户。"""
    lines = []
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(
                release_payload(name="\u4e2d\u6587\u4fee\u8ba2")
            ),
        ]
    )
    publisher = make_publisher(run, output=lines.append)

    publisher.ensure_release("v3.6.22", "中文修订", write_notes(tmp_path / "notes.md"), repair=False)

    assert lines == []
    assert run.call_count == 3


def test_metadata_probe_retries_transient_proxy_disconnect(tmp_path):
    lines = []
    transient_failure = completed(
        [],
        stderr=(
            'Get "https://api.github.com/repos/haohaizi554/UniversalCrawler/'
            'releases?per_page=100&page=1": read tcp 127.0.0.1:64929->127.0.0.1:7890: '
            "wsarecv: An existing connection was forcibly closed by the remote host."
        ),
        returncode=1,
    )
    run = Mock(
        side_effect=[
            transient_failure,
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(run, output=lines.append)

    with patch("time.sleep") as sleep:
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 2
    sleep.assert_called_once_with(1.0)
    assert lines == ["GitHub 网络连接暂时中断，1 秒后重试（1/2）"]


def test_metadata_probe_stops_after_bounded_transient_retries(tmp_path):
    run = Mock(
        return_value=completed(
            [],
            stderr="error connecting to api.github.com: connection reset by peer",
            returncode=1,
        )
    )
    publisher = make_publisher(run)

    with patch("time.sleep") as sleep, pytest.raises(
        PublishError,
        match="^GitHub command failed$",
    ):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(1.0,), (2.0,)]


def test_successful_metadata_response_is_never_retried_for_body_text(tmp_path):
    payload = release_payload()
    payload["body"] = "Support note: connection reset by peer"
    run = Mock(return_value=releases_response(payload))
    publisher = make_publisher(run)
    notes = tmp_path / "notes.md"
    notes.write_text(str(payload["body"]), encoding="utf-8")

    with patch("time.sleep") as sleep:
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            notes,
            repair=False,
        )

    assert run.call_count == 1
    sleep.assert_not_called()


def test_metadata_probe_does_not_retry_rate_limit_response(tmp_path):
    run = Mock(
        return_value=completed(
            [],
            stdout="HTTP/2 429 Too Many Requests\r\n\r\n{}",
            returncode=1,
        )
    )
    publisher = make_publisher(run)

    with patch("time.sleep") as sleep, pytest.raises(
        PublishError,
        match="^GitHub command failed$",
    ):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 1
    sleep.assert_not_called()


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
    run = Mock(
        return_value=releases_response(
            release_payload(assets=[remote_asset.to_json()], draft=False)
        )
    )
    publisher = make_publisher(run)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert publisher.executed_uploads == []
    assert run.call_count == 1


def test_upload_reports_real_bytes_and_processes_assets_sequentially(tmp_path):
    first = write_asset(tmp_path / "portable.zip", b"123456")
    second = write_asset(tmp_path / "installer.exe", b"abcd")
    calls: list[tuple[str, Path]] = []
    progress: list[ReleaseUploadProgress] = []

    def upload_request(upload_url, path, on_progress):
        calls.append((upload_url, path))
        size = path.stat().st_size
        on_progress(size // 2, size, 2.5 * 1024 * 1024)
        on_progress(size, size, 4.0 * 1024 * 1024)

    run = Mock(return_value=releases_response(release_payload()))
    publisher = make_publisher(
        run,
        upload_request=upload_request,
        upload_progress=progress.append,
    )

    publisher.upload_assets("v3.6.22", [first, second], repair=False)

    assert [path.name for _url, path in calls] == ["portable.zip", "installer.exe"]
    uploading = [event for event in progress if event.state == "uploading"]
    assert any(
        event.asset_name == "portable.zip"
        and event.bytes_sent == 3
        and event.bytes_per_second == 2.5 * 1024 * 1024
        for event in uploading
    )
    assert progress[-1].state == "completed"
    assert progress[-1].overall_bytes_sent == 10
    assert progress[-1].overall_bytes_total == 10
    assert publisher.executed_uploads == [(str(first.resolve()), str(second.resolve()))]


def test_upload_recovers_when_server_committed_asset_before_disconnect(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    remote_asset = ReleaseAssetInfo.from_path(asset)
    progress: list[ReleaseUploadProgress] = []
    attempts = 0

    def upload_request(_upload_url, path, on_progress):
        nonlocal attempts
        attempts += 1
        on_progress(path.stat().st_size, path.stat().st_size, 1024.0)
        raise OSError("connection reset after request body")

    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote_asset.to_json()])),
        ]
    )
    publisher = make_publisher(
        run,
        upload_request=upload_request,
        upload_progress=progress.append,
    )

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert attempts == 1
    assert progress[-1].state == "recovered"
    assert progress[-1].overall_bytes_sent == asset.stat().st_size
    assert publisher.executed_uploads == [(str(asset.resolve()),)]


def test_upload_retries_current_file_after_transient_disconnect(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    progress: list[ReleaseUploadProgress] = []
    attempts = 0

    def upload_request(_upload_url, path, on_progress):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            on_progress(4, path.stat().st_size, 2048.0)
            raise OSError("connection reset")
        on_progress(path.stat().st_size, path.stat().st_size, 4096.0)

    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(
        run,
        upload_request=upload_request,
        upload_progress=progress.append,
    )

    with patch("time.sleep") as sleep:
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert attempts == 2
    sleep.assert_called_once_with(1.0)
    retrying = [event for event in progress if event.state == "retrying"]
    assert len(retrying) == 1
    assert retrying[0].attempt == 1
    assert retrying[0].retry_delay_seconds == 1.0
    assert progress[-1].state == "completed"


def test_upload_never_deletes_unfinished_starter_asset_after_failure(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    attempts = 0

    def upload_request(_upload_url, path, on_progress):
        nonlocal attempts
        attempts += 1
        on_progress(0, path.stat().st_size, 0.0)
        raise UploadTransportError("HTTP 422", transient=False)

    starter_asset = {
        "id": 42,
        "name": asset.name,
        "size": 0,
        "digest": "",
        "state": "starter",
    }
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload(assets=[starter_asset])),
        ]
    )
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="not finalized"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert attempts == 1
    assert run.call_count == 3
    assert all("DELETE" not in call.args[0] for call in run.call_args_list)


def test_upload_rejects_draft_starter_left_by_a_previous_run_without_deleting(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    starter_asset = {
        **ReleaseAssetInfo.from_path(asset).to_json(),
        "id": 42,
        "state": "starter",
    }
    run = Mock(
        return_value=releases_response(release_payload(assets=[starter_asset]))
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="not finalized"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1
    assert all("DELETE" not in call.args[0] for call in run.call_args_list)
    upload_request.assert_not_called()


def test_upload_never_deletes_a_starter_even_when_a_fresh_read_is_public(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    starter_asset = {
        **ReleaseAssetInfo.from_path(asset).to_json(),
        "id": 42,
        "state": "starter",
    }
    run = Mock(
        return_value=releases_response(
            release_payload(assets=[starter_asset], draft=False)
        )
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="published release"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1
    assert all(
        "DELETE" not in call.args[0]
        for call in run.call_args_list
    )
    upload_request.assert_not_called()


def test_upload_rechecks_release_before_each_post(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(draft=False)),
        ]
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="published release is incomplete"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 2
    upload_request.assert_not_called()


def test_upload_rejects_release_identity_change_before_post(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    run = Mock(
        side_effect=[
            releases_response(release_payload(release_id=1)),
            releases_response(release_payload(release_id=2)),
        ]
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="release identity changed"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    upload_request.assert_not_called()


def test_upload_rejects_upload_url_for_a_different_release_id(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    mismatched = release_payload(release_id=1)
    mismatched["upload_url"] = str(mismatched["upload_url"]).replace(
        "/releases/1/",
        "/releases/2/",
    )
    run = Mock(
        side_effect=[
            releases_response(release_payload(release_id=1)),
            releases_response(mismatched),
        ]
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="invalid release asset response"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    upload_request.assert_not_called()


def test_upload_places_all_local_snapshot_checks_before_the_fresh_remote_read(
    tmp_path,
    monkeypatch,
):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    operations: list[str] = []

    def run_process(*_args, **_kwargs):
        operations.append("GET")
        return releases_response(release_payload())

    def check_snapshots(*_args, **_kwargs):
        operations.append("snapshot")

    def upload_request(_upload_url, path, on_progress):
        operations.append("POST")
        on_progress(path.stat().st_size, path.stat().st_size, 4096.0)

    monkeypatch.setattr(publisher_module, "_assert_upload_snapshots", check_snapshots)
    publisher = make_publisher(run_process, upload_request=upload_request)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert operations == ["GET", "snapshot", "GET", "POST", "snapshot"]


def test_upload_rechecks_release_before_retrying_a_post(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload(draft=False)),
        ]
    )
    upload_request = Mock(side_effect=OSError("connection reset"))
    publisher = make_publisher(run, upload_request=upload_request)

    with patch("time.sleep"), pytest.raises(
        PublishError,
        match="published release is incomplete",
    ):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert upload_request.call_count == 1
    assert run.call_count == 4


def test_failed_upload_never_deletes_or_retries_a_matching_starter(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    starter_asset = {
        **ReleaseAssetInfo.from_path(asset).to_json(),
        "id": 42,
        "state": "starter",
    }
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload(assets=[starter_asset])),
        ]
    )
    upload_request = Mock(
        side_effect=UploadTransportError("connection lost", transient=False)
    )
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="not finalized"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert upload_request.call_count == 1
    assert run.call_count == 3
    assert all("DELETE" not in call.args[0] for call in run.call_args_list)


def test_failed_post_that_observes_a_public_release_never_retries_or_mutates_it(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
            releases_response(release_payload(draft=False)),
        ]
    )
    upload_request = Mock(side_effect=OSError("connection reset"))
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="published release is incomplete"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert upload_request.call_count == 1
    assert run.call_count == 3
    assert all(
        "DELETE" not in call.args[0] and "--draft=true" not in call.args[0]
        for call in run.call_args_list
    )


def test_upload_never_deletes_or_accepts_a_public_starter_asset(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"12345678")
    starter_asset = {
        **ReleaseAssetInfo.from_path(asset).to_json(),
        "id": 42,
        "state": "starter",
    }
    run = Mock(
        return_value=releases_response(
            release_payload(assets=[starter_asset], draft=False)
        )
    )
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(PublishError, match="published release is incomplete"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 1
    upload_request.assert_not_called()


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
    run = Mock(
        return_value=releases_response(
            release_payload("v3.6.22-r3", name="Release revision 3")
        )
    )
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


def test_upload_requires_regular_absolute_assets_and_uses_trusted_endpoint(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    uploaded: list[tuple[str, Path]] = []

    def upload_request(upload_url, path, _on_progress):
        uploaded.append((upload_url, path))

    run = Mock(return_value=releases_response(release_payload()))
    publisher = make_publisher(run, upload_request=upload_request)

    publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert uploaded == [
        (
            "https://uploads.github.com/repos/haohaizi554/UniversalCrawler/"
            "releases/1/assets{?name,label}",
            asset.resolve(),
        )
    ]


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


def test_upload_detects_asset_changed_during_fresh_read_after_post(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")
    reads = 0

    def release_read(*_args, **_kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            asset.write_bytes(b"mutated during fresh remote read")
        return releases_response(release_payload())

    run = Mock(side_effect=release_read)
    upload_request = Mock()
    publisher = make_publisher(run, upload_request=upload_request)

    with pytest.raises(ValueError, match="changed after upload"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    assert run.call_count == 2
    upload_request.assert_called_once()


def test_upload_rechecks_asset_snapshot_after_transport_returns(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"same")

    def upload_request(*_args, **_kwargs):
        asset.write_bytes(b"mutated after upload")

    run = Mock(return_value=releases_response(release_payload()))
    publisher = make_publisher(run, upload_request=upload_request)

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


def test_release_lookup_scans_authenticated_pages_for_an_exact_case_sensitive_tag(tmp_path):
    first_page = [
        release_payload(f"v0.0.{index}", release_id=1000 + index)
        for index in range(100)
    ]
    matching = release_payload("v3.6.22", release_id=2200)
    run = Mock(
        side_effect=[
            releases_response(*first_page),
            releases_response(
                release_payload("V3.6.22", release_id=2100),
                matching,
            ),
        ]
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    assert run.call_count == 2
    endpoints = [call.args[0][call.args[0].index("GET") + 1] for call in run.call_args_list]
    assert endpoints == [
        "repos/haohaizi554/UniversalCrawler/releases?per_page=100&page=1",
        "repos/haohaizi554/UniversalCrawler/releases?per_page=100&page=2",
    ]
    assert not any(call.args[0][:3] == ["gh", "release", "create"] for call in run.call_args_list)


def test_release_lookup_rejects_an_exact_tag_duplicated_across_pages(tmp_path):
    first_page = [release_payload("v3.6.22", release_id=1)] + [
        release_payload(f"v0.1.{index}", release_id=1000 + index)
        for index in range(99)
    ]
    run = Mock(
        side_effect=[
            releases_response(*first_page),
            releases_response(release_payload("v3.6.22", release_id=2)),
        ]
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="duplicate release tag"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 2
    assert not any(call.args[0][:3] == ["gh", "release", "create"] for call in run.call_args_list)


def test_release_lookup_fails_closed_when_the_fixed_page_limit_stays_full(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(publisher_module, "_MAX_RELEASE_PAGES", 2, raising=False)
    pages = [
        releases_response(
            *[
                release_payload(f"v{page}.{index}.0", release_id=page * 1000 + index + 1)
                for index in range(100)
            ]
        )
        for page in (1, 2)
    ]
    run = Mock(side_effect=pages)
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="release listing did not terminate"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 2
    assert not any(call.args[0][:3] == ["gh", "release", "create"] for call in run.call_args_list)


@pytest.mark.parametrize(
    "response",
    (
        release_payload(),
        [release_payload(f"v0.2.{index}", release_id=2000 + index) for index in range(101)],
    ),
)
def test_release_lookup_requires_each_page_to_be_a_bounded_list(tmp_path, response):
    run = Mock(return_value=completed([], stdout=json.dumps(response)))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="invalid GitHub response"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 1


def test_existing_draft_requires_exact_title_and_normalized_notes(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_bytes(b"first line\r\nsecond line\r")
    run = Mock(
        return_value=releases_response(
            release_payload(
                name="Exact title",
                body="first line\nsecond line\n",
            )
        )
    )
    publisher = make_publisher(run)

    publisher.ensure_release(
        "v3.6.22",
        "Exact title",
        notes,
        repair=False,
    )

    assert run.call_count == 1


@pytest.mark.parametrize(
    ("name", "body"),
    (
        ("Stale title", "release notes\n"),
        ("Release", "rewritten notes\n"),
        ("Release", "release notes\n\n"),
    ),
)
def test_existing_draft_rejects_stale_title_or_body(tmp_path, name, body):
    run = Mock(return_value=releases_response(release_payload(name=name, body=body)))
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="release metadata does not match"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 1


def test_new_release_confirmation_requires_exact_title_and_body(tmp_path):
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload(name="Concurrent rewrite")),
        ]
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="release metadata does not match"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )

    assert run.call_count == 3
    assert run.call_args_list[1].args[0][:3] == ["gh", "release", "create"]


def test_prepared_release_id_is_pinned_across_verification(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(release_id=101)),
            releases_response(release_payload(release_id=202, assets=[remote])),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    with pytest.raises(PublishError, match="release identity changed"):
        publisher.verify_assets("v3.6.22", [asset])


def test_prepared_release_metadata_is_rechecked_before_verification(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload(release_id=101)),
            releases_response(
                release_payload(
                    release_id=101,
                    body="concurrently rewritten\n",
                    assets=[remote],
                )
            ),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    with pytest.raises(PublishError, match="release metadata changed"):
        publisher.verify_assets("v3.6.22", [asset])


def test_failed_reprepare_revokes_old_authorization_before_verify_and_publish(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    old_release = release_payload(release_id=101, assets=[remote])
    run = Mock(
        side_effect=[
            releases_response(old_release),
            releases_response(old_release),
            releases_response(old_release),
            releases_response(old_release),
            completed([]),
            releases_response({**old_release, "draft": False}),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "old-notes.md"),
        repair=False,
    )
    new_notes = tmp_path / "new-notes.md"
    new_notes.write_text("new release notes\n", encoding="utf-8")

    with pytest.raises(PublishError, match="release metadata does not match"):
        publisher.ensure_release(
            "v3.6.22",
            "New title",
            new_notes,
            repair=False,
        )

    publisher.verify_assets("v3.6.22", [asset])
    with pytest.raises(PublishError, match="release assets were not verified"):
        publisher.publish_release("v3.6.22")

    assert run.call_count == 3
    assert not any(
        "PATCH" in call.args[0] or call.args[0][:3] == ["gh", "release", "edit"]
        for call in run.call_args_list
    )


def _tag_reference(commit: str) -> dict[str, object]:
    return {
        "ref": "refs/tags/v3.6.22",
        "object": {"type": "commit", "sha": commit},
    }


@pytest.mark.parametrize("state", ("missing", "true", "string"))
def test_ensure_release_requires_explicit_non_prerelease_identity(tmp_path, state):
    payload = release_payload()
    if state == "missing":
        payload.pop("prerelease")
    elif state == "true":
        payload["prerelease"] = True
    else:
        payload["prerelease"] = "false"
    publisher = make_publisher(Mock(return_value=releases_response(payload)))

    with pytest.raises(PublishError, match="prerelease|invalid GitHub response"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )


def test_ensure_release_rechecks_prerelease_identity_after_create(tmp_path):
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload(prerelease=True)),
        ]
    )
    publisher = make_publisher(run)

    with pytest.raises(PublishError, match="prerelease"):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )


def test_upload_rejects_concurrent_prerelease_flip(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(prerelease=True)),
        ]
    )
    upload = Mock()
    publisher = make_publisher(run, upload_request=upload)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    with pytest.raises(PublishError, match="prerelease"):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    upload.assert_not_called()


def test_verify_rejects_concurrent_prerelease_flip(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote], prerelease=True)),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )

    with pytest.raises(PublishError, match="prerelease"):
        publisher.verify_assets("v3.6.22", [asset])


def test_publish_rejects_prerelease_flip_before_patch(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote])),
            releases_response(release_payload(assets=[remote], prerelease=True)),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [asset])

    with pytest.raises(PublishError, match="prerelease"):
        publisher.publish_release("v3.6.22")

    assert not any("PATCH" in call.args[0] for call in run.call_args_list)


def test_publish_rejects_prerelease_flip_after_patch(tmp_path):
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote])),
            releases_response(release_payload(assets=[remote])),
            completed([]),
            releases_response(
                release_payload(assets=[remote], draft=False, prerelease=True)
            ),
        ]
    )
    publisher = make_publisher(run)
    publisher.ensure_release(
        "v3.6.22",
        "Release",
        write_notes(tmp_path / "notes.md"),
        repair=False,
    )
    publisher.verify_assets("v3.6.22", [asset])

    with pytest.raises(PublishError, match="prerelease"):
        publisher.publish_release("v3.6.22")


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_pinned_tag_mutation_is_rejected_before_release_prepare(tmp_path, mutation):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    publisher = make_publisher(Mock(return_value=releases_response(release_payload())))
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    with (
        patch.object(publisher, "_read_tag", return_value=mutated),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_pinned_tag_mutation_is_rejected_after_asset_verification(
    tmp_path,
    mutation,
):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote])),
        ]
    )
    publisher = make_publisher(run)
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )
        publisher.verify_assets("v3.6.22", [asset])

    with (
        patch.object(publisher, "_read_tag", return_value=mutated),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.publish_release("v3.6.22")


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_pinned_tag_mutation_during_publish_is_rejected_after_confirmation(
    tmp_path,
    mutation,
):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote])),
            releases_response(release_payload(assets=[remote])),
            completed([]),
            releases_response(release_payload(assets=[remote], draft=False)),
        ]
    )
    publisher = make_publisher(run)
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )
        publisher.verify_assets("v3.6.22", [asset])

    with (
        patch.object(
            publisher,
            "_read_tag",
            side_effect=[initial, initial, initial, mutated],
        ),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.publish_release("v3.6.22")


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_public_release_rechecks_tag_after_fresh_release_read(tmp_path, mutation):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    remote = ReleaseAssetInfo.from_path(asset).to_json()
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload(assets=[remote])),
            releases_response(release_payload(assets=[remote], draft=False)),
        ]
    )
    publisher = make_publisher(run)
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )
        publisher.verify_assets("v3.6.22", [asset])

    with (
        patch.object(publisher, "_read_tag", side_effect=[initial, mutated]),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.publish_release("v3.6.22")


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_ensure_release_rechecks_tag_after_existing_release_read(
    tmp_path,
    mutation,
):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    publisher = make_publisher(Mock(return_value=releases_response(release_payload())))
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    with (
        patch.object(publisher, "_read_tag", side_effect=[initial, mutated]),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )


@pytest.mark.parametrize("mutation", ("move", "delete"))
def test_ensure_release_rechecks_tag_after_created_release_confirmation(
    tmp_path,
    mutation,
):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    mutated = moved if mutation == "move" else None
    run = Mock(
        side_effect=[
            releases_response(),
            completed([]),
            releases_response(release_payload()),
        ]
    )
    publisher = make_publisher(run)
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    with (
        patch.object(
            publisher,
            "_read_tag",
            side_effect=[initial, initial, initial, mutated],
        ),
        pytest.raises(PublishError, match="tag"),
    ):
        publisher.ensure_release(
            "v3.6.22",
            "Release",
            write_notes(tmp_path / "notes.md"),
            repair=False,
        )


def test_each_asset_upload_rechecks_the_pinned_tag_before_post(tmp_path):
    initial = _tag_reference("a" * 40)
    moved = _tag_reference("b" * 40)
    asset = write_asset(tmp_path / "installer.exe", b"installer")
    run = Mock(
        side_effect=[
            releases_response(release_payload()),
            releases_response(release_payload()),
        ]
    )
    upload = Mock()
    publisher = make_publisher(run, upload_request=upload)
    with patch.object(publisher, "_read_tag", return_value=initial):
        publisher.ensure_tag("v3.6.22", "a" * 40)

    with (
        patch.object(publisher, "_read_tag", side_effect=[initial, moved]),
        pytest.raises(PublishError, match="tag.*changed|tag target"),
    ):
        publisher.upload_assets("v3.6.22", [asset], repair=False)

    upload.assert_not_called()


def _authorize_publish_for_test(
    publisher: GitHubReleasePublisher,
    asset: Path,
) -> dict[str, object]:
    tag = "v3.6.22"
    info = ReleaseAssetInfo.from_path(asset)
    publisher._prepared_release_tags.add(tag)
    publisher._prepared_release_metadata[tag] = ("Release", "release notes\n")
    publisher._verified_release_assets[tag] = (info,)
    return release_payload(assets=[info.to_json()])


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, GeneratorExit))
def test_publish_interruption_reports_success_when_exact_release_is_public(
    tmp_path,
    interruption_type,
):
    publisher = make_publisher(Mock())
    initial = _authorize_publish_for_test(
        publisher,
        write_asset(tmp_path / "installer.exe", b"installer"),
    )
    primary = interruption_type("operator interrupted")
    with (
        patch.object(
            publisher,
            "_read_release",
            side_effect=[initial, {**initial, "draft": False}],
        ),
        patch.object(publisher, "_execute", side_effect=primary),
    ):
        publisher.publish_release("v3.6.22")


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, GeneratorExit))
def test_publish_interruption_preserves_identity_when_release_is_still_draft(
    tmp_path,
    interruption_type,
):
    publisher = make_publisher(Mock())
    initial = _authorize_publish_for_test(
        publisher,
        write_asset(tmp_path / "installer.exe", b"installer"),
    )
    primary = interruption_type("operator interrupted")
    with (
        patch.object(publisher, "_read_release", side_effect=[initial, initial]),
        patch.object(publisher, "_execute", side_effect=primary),
    ):
        caught = None
        try:
            publisher.publish_release("v3.6.22")
        except BaseException as error:  # noqa: BLE001 - identity is the contract.
            caught = error

    assert caught is primary


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, GeneratorExit))
def test_publish_interruption_preserves_identity_when_confirmation_fails(
    tmp_path,
    interruption_type,
):
    lines: list[str] = []
    publisher = make_publisher(Mock(), output=lines.append)
    initial = _authorize_publish_for_test(
        publisher,
        write_asset(tmp_path / "installer.exe", b"installer"),
    )
    primary = interruption_type("operator interrupted")
    secondary = PublishError(
        "confirmation failed via https://alice:secret@proxy.example/api"
    )
    with (
        patch.object(publisher, "_read_release", side_effect=[initial, secondary]),
        patch.object(publisher, "_execute", side_effect=primary),
    ):
        caught = None
        try:
            publisher.publish_release("v3.6.22")
        except BaseException as error:  # noqa: BLE001 - identity is the contract.
            caught = error

    assert caught is primary
    diagnostics = list(getattr(primary, "__notes__", ())) + lines
    assert any("publication confirmation failed" in item for item in diagnostics)
    assert all("secret" not in item for item in diagnostics)
