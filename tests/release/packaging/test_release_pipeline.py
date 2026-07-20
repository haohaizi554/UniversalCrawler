from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from Crypto.PublicKey import ECC

from scripts.update_bootstrap import ManifestKeyResult
from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.models import BuildRequest, RemoteReleaseInfo
from release_tool.events import ReleaseEventEmitter, parse_event_line
from release_tool.proxy import PROXY_ENVIRONMENT_VARIABLES
from release_tool.runner import CancellationToken, run_release_request
from release_tool.versioning import VersionUpdatePlan, VersionUpdateResult


BUILD_RELEASE_TOOL = PROJECT_ROOT / "packaging" / "build_release.py"
UPDATE_MANIFEST_TOOL = PROJECT_ROOT / "packaging" / "update_manifest.py"


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "ucrawl_release_pipeline_tool", BUILD_RELEASE_TOOL
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_manifest_tool():
    spec = importlib.util.spec_from_file_location(
        "ucrawl_release_manifest_tool", UPDATE_MANIFEST_TOOL
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _release_payload(installer: Path, *, source_commit: str = "a" * 40) -> dict:
    return {
        "schema": 1,
        "appId": "ucrawl.universalcrawlerpro",
        "channel": "stable",
        "version": "3.6.21",
        "tag": "v3.6.21",
        "publishedAt": "2026-07-16T00:00:00Z",
        "expiresAt": "2099-07-16T00:00:00Z",
        "minClientVersion": "3.0.0",
        "mandatory": False,
        "notes": "emergency rebuild",
        "sourceCommit": source_commit,
        "assets": {
            "windows-x64": {
                "name": installer.name,
                "url": (
                    "https://github.com/haohaizi554/UniversalCrawler/releases/"
                    f"download/v3.6.21/{installer.name}"
                ),
                "sha256": _file_sha256(installer),
                "size": installer.stat().st_size,
                "installerType": "inno",
                "os": "windows",
                "arch": "x64",
            }
        },
    }


def _write_staged_release(tmp_path: Path, *, source_commit: str = "a" * 40):
    installer = tmp_path / "UniversalCrawlerPro_Setup_3.6.21.exe"
    installer.write_bytes(b"installer")
    payload = _release_payload(installer, source_commit=source_commit)
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "latest.json.sig").write_bytes(b"signature")
    return installer, payload


def _staged_validation_kwargs(installer: Path, *, source_commit: str = "a" * 40) -> dict:
    return {
        "installer_name": installer.name,
        "installer_size": installer.stat().st_size,
        "installer_sha256": _file_sha256(installer),
        "asset_url": (
            "https://github.com/haohaizi554/UniversalCrawler/releases/"
            f"download/v3.6.21/{installer.name}"
        ),
        "version": "3.6.21",
        "tag": "v3.6.21",
        "source_commit": source_commit,
        "project_root": PROJECT_ROOT,
    }


def _valid_request_payload() -> dict:
    return {
        "target_version": "3.6.21",
        "remote": {"version": "3.6.21"},
        "build_portable": False,
        "build_installer": False,
        "run_smoke_tests": False,
        "apply_version": False,
    }


def _release_events(output: str):
    events = []
    for line in output.splitlines():
        event = parse_event_line(line)
        if event is not None:
            events.append(event)
    return events


def test_python_main_empty_argv_keeps_headless_release_semantics():
    tool = _load_tool()

    with patch.object(tool, "_run_headless_legacy", return_value=17) as headless:
        assert tool.main([]) == 17

    headless.assert_called_once_with([])


def test_python_main_none_argv_keeps_headless_release_semantics():
    tool = _load_tool()

    with patch.object(tool, "_run_headless_legacy", return_value=17) as headless:
        assert tool.main() == 17

    headless.assert_called_once_with([])


def test_script_no_args_opens_panel():
    tool = _load_tool()

    with patch.object(tool, "_launch_panel", return_value=0) as launch:
        assert tool.script_main([]) == 0

    launch.assert_called_once_with()


def test_script_explicit_gui_opens_panel():
    tool = _load_tool()

    with patch.object(tool, "_launch_panel", return_value=0) as launch:
        assert tool.script_main(["--gui"]) == 0

    launch.assert_called_once_with()


def test_script_headless_request_file_runs_runner(tmp_path):
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_valid_request_payload()), encoding="utf-8")
    tool = _load_tool()

    with patch.object(tool, "_run_request_file", return_value=0) as run:
        assert tool.script_main(["--headless", "--request-file", str(request_file)]) == 0

    run.assert_called_once_with(request_file)


def test_script_headless_dry_run_builds_non_mutating_request():
    tool = _load_tool()

    with patch.object(tool, "_run_dry_run_request", return_value=0) as run:
        assert tool.script_main(
            ["--headless", "--dry-run", "--version", "3.6.21", "--build-only"]
        ) == 0

    run.assert_called_once_with(version="3.6.21", build_only=True)


def test_script_headless_legacy_routing_preserves_every_legacy_token():
    tool = _load_tool()
    legacy = [
        "--version",
        "3.6.21",
        "--tag",
        "v3.6.21",
        "--repository",
        "owner/repository",
        "--build-only",
    ]

    with patch.object(tool, "main", return_value=0) as run:
        assert tool.script_main(["--headless", *legacy]) == 0

    run.assert_called_once_with(legacy)


def test_script_dry_run_rejects_unsupported_legacy_arguments(capsys):
    tool = _load_tool()

    with (
        patch.object(tool, "_run_dry_run_request") as run,
        pytest.raises(SystemExit) as caught,
    ):
        tool.script_main(
            ["--headless", "--dry-run", "--tag", "v3.6.21-secret-value"]
        )

    assert caught.value.code == 2
    run.assert_not_called()
    captured = capsys.readouterr()
    assert "secret-value" not in captured.err


@pytest.mark.parametrize(
    "extra",
    [
        ["--repository", "owner/repository"],
        ["--version", "3.6.22"],
        ["--build-only"],
        ["--dry-run"],
    ],
)
def test_script_request_file_rejects_unsupported_routed_arguments(
    tmp_path, capsys, extra
):
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_valid_request_payload()), encoding="utf-8")
    tool = _load_tool()

    with (
        patch.object(tool, "_run_request_file") as run,
        pytest.raises(SystemExit) as caught,
    ):
        tool.script_main(
            ["--headless", "--request-file", str(request_file), *extra]
        )

    assert caught.value.code == 2
    run.assert_not_called()
    assert "unsupported arguments for --request-file" in capsys.readouterr().err


def test_request_file_is_deleted_after_loading_and_runs_the_unified_runner(tmp_path):
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_valid_request_payload()), encoding="utf-8")
    tool = _load_tool()

    with patch.object(tool, "_run_release_request", return_value=0) as run:
        assert tool._run_request_file(request_file) == 0

    request = run.call_args.args[0]
    assert request == BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        apply_version=False,
    )
    assert not request_file.exists()


@pytest.mark.parametrize(
    "payload",
    [
        '{"target_version": "3.6.21",',
        json.dumps({**_valid_request_payload(), "token": "top-secret"}),
    ],
)
def test_invalid_request_file_is_deleted_and_emits_one_redacted_terminal_result(
    tmp_path, capsys, payload
):
    request_file = tmp_path / "request.json"
    request_file.write_text(payload, encoding="utf-8")
    tool = _load_tool()

    exit_code = tool._run_request_file(request_file)

    assert exit_code != 0
    assert not request_file.exists()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert "top-secret" not in captured.out + captured.err
    assert '"token"' not in captured.out + captured.err
    events = _release_events(captured.out)
    result_events = [event for event in events if event.kind == "result"]
    assert len(result_events) == 1
    assert result_events[0].stage is tool.ReleaseStage.FAILED
    assert result_events[0].data["status"] == "failed"
    assert len([event for event in events if event.kind == "error"]) == 1


def test_dry_run_request_sets_every_dependent_action_explicitly():
    tool = _load_tool()

    with patch.object(tool, "_run_release_request", return_value=0) as run:
        assert tool._run_dry_run_request(version="3.6.21", build_only=True) == 0

    request = run.call_args.args[0]
    assert request.dry_run is True
    assert request.target_version == "3.6.21"
    assert request.build_portable is True
    assert request.build_installer is True
    assert request.remote == RemoteReleaseInfo.available("3.6.21")
    assert request.run_smoke_tests is False
    assert request.apply_version is False
    assert request.generate_manifest_key is False
    assert request.rotate_trust_anchor is False
    assert request.sign_manifest is False
    assert request.commit_version_changes is False
    assert request.push_main is False
    assert request.create_or_reuse_tag is False
    assert request.create_or_update_release is False
    assert request.upload_release_assets is False
    assert request.upload_public_key is False
    assert request.verify_remote_assets is False


def test_dry_run_request_canonicalizes_prefixed_version():
    tool = _load_tool()

    with patch.object(tool, "_run_release_request", return_value=0) as run:
        assert tool._run_dry_run_request(version="v3.1.1", build_only=True) == 0

    request = run.call_args.args[0]
    assert request.target_version == "3.1.1"
    assert tool.format_release_tag(request.target_version) == "v3.1.1"


@pytest.mark.parametrize("build_only", [False, True])
def test_actual_dry_run_is_a_successful_read_only_plan(capsys, build_only):
    tool = _load_tool()
    forbidden = Mock(side_effect=AssertionError("dry run attempted a side effect"))
    publisher = Mock()

    with (
        patch.object(tool, "_release_build_lock", forbidden),
        patch.object(tool, "_run_git", forbidden),
        patch.object(tool.subprocess, "run", forbidden),
        patch.object(tool, "apply_version_update", forbidden),
        patch.object(tool, "_build_binaries", forbidden),
        patch.object(tool, "_prepare_release_assets", forbidden),
        patch.object(tool, "begin_manifest_key_transaction", forbidden),
        patch.object(tool, "GitHubReleasePublisher", return_value=publisher),
    ):
        exit_code = tool._run_dry_run_request(
            version=tool.read_project_version(tool.PROJECT_ROOT),
            build_only=build_only,
        )

    assert exit_code == 0
    forbidden.assert_not_called()
    assert publisher.method_calls == []
    events = _release_events(capsys.readouterr().out)
    result_events = [event for event in events if event.kind == "result"]
    assert len(result_events) == 1
    assert result_events[0].stage is tool.ReleaseStage.SUCCEEDED
    assert result_events[0].data["status"] == "succeeded"


def test_invalid_direct_dry_run_is_a_redacted_read_only_terminal_failure(capsys):
    tool = _load_tool()
    forbidden = Mock(side_effect=AssertionError("invalid dry run attempted a side effect"))
    invalid_version = "github_pat_topsecretvalue"

    with (
        patch.object(tool, "_release_build_lock", forbidden),
        patch.object(tool, "_run_git", forbidden),
        patch.object(tool.subprocess, "run", forbidden),
        patch.object(tool, "apply_version_update", forbidden),
        patch.object(tool, "_build_binaries", forbidden),
        patch.object(tool, "_prepare_release_assets", forbidden),
        patch.object(tool, "begin_manifest_key_transaction", forbidden),
        patch.object(tool, "GitHubReleasePublisher", forbidden),
    ):
        exit_code = tool._run_dry_run_request(
            version=invalid_version,
            build_only=True,
        )

    assert exit_code != 0
    forbidden.assert_not_called()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert invalid_version not in captured.out + captured.err
    assert "topsecretvalue" not in captured.out + captured.err
    events = _release_events(captured.out)
    result_events = [event for event in events if event.kind == "result"]
    assert len(result_events) == 1
    assert result_events[0].stage is tool.ReleaseStage.FAILED
    assert result_events[0].data["status"] == "failed"
    assert len([event for event in events if event.kind == "error"]) == 1


def test_script_invalid_dry_run_version_returns_one_terminal_failure(capsys):
    tool = _load_tool()
    forbidden = Mock(side_effect=AssertionError("invalid dry run attempted a side effect"))

    with (
        patch.object(tool, "_release_build_lock", forbidden),
        patch.object(tool, "_run_git", forbidden),
        patch.object(tool.subprocess, "run", forbidden),
        patch.object(tool, "apply_version_update", forbidden),
        patch.object(tool, "_build_binaries", forbidden),
        patch.object(tool, "_prepare_release_assets", forbidden),
        patch.object(tool, "begin_manifest_key_transaction", forbidden),
        patch.object(tool, "GitHubReleasePublisher", forbidden),
    ):
        exit_code = tool.script_main(
            ["--headless", "--dry-run", "--version", "not-a-version"]
        )

    assert exit_code != 0
    forbidden.assert_not_called()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert "not-a-version" not in captured.out + captured.err
    events = _release_events(captured.out)
    result_events = [event for event in events if event.kind == "result"]
    assert len(result_events) == 1
    assert result_events[0].stage is tool.ReleaseStage.FAILED
    assert result_events[0].data["status"] == "failed"
    assert len([event for event in events if event.kind == "error"]) == 1


def test_release_mode_fails_before_build_when_manifest_key_is_missing(tmp_path):
    tool = _load_tool()
    run_build = Mock()

    with (
        patch.object(tool, "_run_build", run_build),
        patch.object(tool, "_default_private_key_path", return_value=tmp_path / "missing.pem"),
        pytest.raises(SystemExit, match="manifest.*私钥|私钥.*manifest"),
    ):
        tool.main([])

    run_build.assert_not_called()


def test_manifest_payload_records_the_full_source_commit(tmp_path):
    tool = _load_manifest_tool()
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")

    payload = tool.build_manifest_payload(
        version="3.6.21",
        tag="v3.6.21",
        source_commit="a" * 40,
        assets=[
            tool.ReleaseAssetSpec(
                key="windows-x64",
                path=installer,
                url="https://example.test/installer.exe",
                os="windows",
                arch="x64",
                installer_type="inno",
            )
        ],
    )

    assert payload["sourceCommit"] == "a" * 40


def test_build_only_is_an_explicit_escape_hatch_that_does_not_prepare_update_assets():
    tool = _load_tool()

    with (
        patch.object(tool, "_run_build") as run_build,
        patch.object(tool, "_prepare_release_assets") as prepare_assets,
        patch.dict("os.environ", {}, clear=True),
    ):
        result = tool.main(["--build-only"])

    assert result == 0
    assert [Path(call.args[0]).name for call in run_build.call_args_list] == [
        "build_portable.py",
        "build_installer.py",
    ]
    assert all(call.args[1] == PROJECT_ROOT for call in run_build.call_args_list)
    prepare_assets.assert_not_called()


def test_pipeline_hooks_use_the_existing_local_build_primitive_without_source_immutability():
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_installer=False,
        run_smoke_tests=False,
    )

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_build_binaries") as build_binaries,
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        hooks.build_portable()

    build_binaries.assert_called_once_with(
        tool.PROJECT_ROOT,
        lock_token="release-token",
        lock_root=tool.PROJECT_ROOT,
        enforce_source_immutability=False,
        build_portable=True,
        build_installer=False,
    )


def test_local_pipeline_build_stages_share_one_request_lock():
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        run_smoke_tests=False,
    )
    lock_events: list[str] = []

    @contextmanager
    def fake_lock(_project_root):
        lock_events.append("enter")
        try:
            yield "release-token"
        finally:
            lock_events.append("exit")

    with (
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_build_binaries") as build_binaries,
        patch.object(tool, "_validate_git_release_state") as validate_release_state,
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.succeeded
    assert lock_events == ["enter", "exit"]
    assert [call.kwargs for call in build_binaries.call_args_list] == [
        {
            "lock_token": "release-token",
            "lock_root": tool.PROJECT_ROOT,
            "enforce_source_immutability": False,
            "build_portable": True,
            "build_installer": False,
        },
        {
            "lock_token": "release-token",
            "lock_root": tool.PROJECT_ROOT,
            "enforce_source_immutability": False,
            "build_portable": False,
            "build_installer": True,
        },
    ]
    validate_release_state.assert_not_called()


def test_new_release_persists_identity_before_snapshot_and_publishes_after_smoke(tmp_path):
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        run_smoke_tests=True,
        sign_manifest=True,
        private_key_path=str(tmp_path / "private.pem"),
        release_notes_path=str(tmp_path / "notes.md"),
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    source_commit = "b" * 40
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()
    installer = snapshot_root / "dist" / "installer" / "setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    release_dir = tmp_path / "release-assets" / "v3.6.22"
    release_dir.mkdir(parents=True)
    for name in ("setup.exe", "latest.json", "latest.json.sig"):
        (release_dir / name).write_bytes(b"asset")
    calls: list[str] = []
    git_commands: list[list[str]] = []
    identity_ready = False
    tag_ready = False
    version_staged = False

    class FakePublisher:
        def __init__(self, *_args, **_kwargs):
            pass

        def ensure_tag(self, tag, commit):
            assert tag == "v3.6.22"
            assert commit == source_commit
            calls.append("remote_tag")

        def ensure_release(self, tag, title, notes_path, *, repair):
            assert tag == "v3.6.22"
            assert title == "UniversalCrawler 3.6.22"
            assert Path(notes_path) == tmp_path / "notes.md"
            assert repair is False
            calls.append("remote_release")

        def upload_assets(self, *_args, **_kwargs):
            calls.append("upload")

        def verify_assets(self, *_args, **_kwargs):
            calls.append("remote_verify")

    def fake_git(argv):
        nonlocal identity_ready, tag_ready, version_staged
        git_commands.append(list(argv))
        command = argv[0]
        calls.append(f"git:{command}")
        if command == "commit":
            identity_ready = True
            version_staged = False
        if command == "add":
            version_staged = True
        if command == "tag":
            tag_ready = True
        if command == "rev-parse":
            if "--verify" in argv and not tag_ready:
                raise subprocess.CalledProcessError(1, ["git", *argv])
            return source_commit
        if command == "diff":
            return "shared/version.py" if version_staged or "--cached" not in argv else ""
        if command == "diff-tree":
            return "shared/version.py"
        if command == "ls-remote":
            return f"{source_commit}\trefs/heads/main"
        return ""

    def validate_identity(tag):
        assert identity_ready
        assert "git:tag" in calls
        calls.append("validate_identity")
        return source_commit

    @contextmanager
    def fake_lock(_project_root):
        calls.append("lock")
        yield "release-token"

    @contextmanager
    def fake_snapshot(commit, *, repository_root):
        assert commit == source_commit
        assert repository_root == tool.PROJECT_ROOT
        calls.append("snapshot")
        yield snapshot_root

    def fake_build(*_args, **kwargs):
        if kwargs["build_portable"]:
            portable_root = snapshot_root / "dist" / "UniversalCrawlerPro"
            portable_root.mkdir(parents=True, exist_ok=True)
            (portable_root / "UCrawlCLI.exe").write_bytes(b"MZ")
            (portable_root / "BUILD_INFO.txt").write_text("build", encoding="utf-8")
            calls.append("portable")
        if kwargs["build_installer"]:
            calls.append("installer")

    def fake_prepare(**kwargs):
        assert kwargs["source_commit"] == source_commit
        assert kwargs["project_root"] == snapshot_root
        calls.append("manifest")
        return release_dir

    def fake_smoke(*args, **_kwargs):
        calls.append("smoke")
        return subprocess.CompletedProcess(args[0], 0, stdout="usage", stderr="")

    version_plan = VersionUpdatePlan(tool.PROJECT_ROOT, "3.6.21", "3.6.22", ())
    version_result = VersionUpdateResult("3.6.21", "3.6.22", (tool.PROJECT_ROOT / "shared/version.py",))
    (tmp_path / "notes.md").write_text("notes", encoding="utf-8")
    (tmp_path / "private.pem").write_text(
        ECC.generate(curve="Ed25519").export_key(format="PEM"),
        encoding="utf-8",
    )
    with (
        patch.object(tool, "GitHubReleasePublisher", FakePublisher),
        patch.object(tool, "plan_version_update", return_value=version_plan),
        patch.object(tool, "apply_version_update", return_value=version_result),
        patch.object(tool, "_run_git", side_effect=fake_git),
        patch.object(tool, "_validate_git_release_state", side_effect=validate_identity),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_source_snapshot", side_effect=fake_snapshot),
        patch.object(tool, "_validate_windows_release_tools"),
        patch.object(tool, "_project_release_metadata", return_value=("3.6.22", installer)),
        patch.object(tool, "_build_binaries", side_effect=fake_build),
        patch.object(tool, "_prepare_release_assets", side_effect=fake_prepare),
        patch.object(
            tool.subprocess,
            "run",
            side_effect=fake_smoke,
        ) as smoke_run,
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.succeeded
    assert calls.index("git:commit") < calls.index("git:tag")
    assert calls.index("git:tag") < calls.index("validate_identity")
    assert calls.index("validate_identity") < calls.index("snapshot")
    assert calls.index("snapshot") < calls.index("manifest")
    assert calls.index("manifest") < calls.index("smoke") < calls.index("remote_release")
    assert calls.index("remote_release") < calls.index("upload") < calls.index("remote_verify")
    assert [
        "push",
        "origin",
        f"{source_commit}:refs/heads/main",
    ] in git_commands
    assert ["ls-remote", "--exit-code", "origin", "refs/heads/main"] in git_commands
    assert smoke_run.call_args.args[0][1:] == ["--mode", "cli", "--help"]


def test_portable_only_signed_build_does_not_validate_an_unbuilt_installer(tmp_path):
    tool = _load_tool()

    with (
        patch.dict("os.environ", {"UCRAWL_SIGN_WINDOWS": "1"}, clear=True),
        patch.object(tool, "_run_build") as run_build,
        patch.object(tool, "_validate_production_trust") as validate_trust,
        patch.object(tool, "_project_release_metadata") as project_metadata,
        patch.object(tool, "_extract_windows_trust") as extract_trust,
    ):
        tool._build_binaries(
            tmp_path,
            lock_token="release-token",
            lock_root=PROJECT_ROOT,
            enforce_source_immutability=False,
            build_portable=True,
            build_installer=False,
        )

    run_build.assert_called_once()
    validate_trust.assert_not_called()
    project_metadata.assert_not_called()
    extract_trust.assert_not_called()


def test_publisher_logs_follow_upload_and_verify_stage_progress(tmp_path):
    tool = _load_tool()
    public_key = tmp_path / "manifest-public.pem"
    public_key.write_text(
        ECC.generate(curve="Ed25519").public_key().export_key(format="PEM"),
        encoding="utf-8",
    )
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream)

    class FakePublisher:
        def __init__(self, _repository, _environment, output, **_kwargs):
            self.output = output
            self.uploaded: tuple[Path, ...] = ()
            self.verified: tuple[Path, ...] = ()

        def ensure_release(self, *_args, **_kwargs):
            self.output("publish output")

        def upload_assets(self, _tag, assets, **_kwargs):
            self.uploaded = tuple(assets)
            self.output("upload output")

        def verify_assets(self, _tag, assets, **_kwargs):
            self.verified = tuple(assets)
            self.output("verify output")

    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path=str(tmp_path / "notes.md"),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        same_release_repair=True,
        create_or_update_release=True,
        upload_public_key=True,
        verify_remote_assets=True,
    )
    (tmp_path / "notes.md").write_text("notes", encoding="utf-8")
    publisher: FakePublisher | None = None

    def make_publisher(*args, **kwargs):
        nonlocal publisher
        publisher = FakePublisher(*args, **kwargs)
        return publisher

    with (
        patch.object(tool, "GitHubReleasePublisher", side_effect=make_publisher),
        patch.object(tool, "_read_only_public_key_path", return_value=public_key),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter)
        result = run_release_request(request, hooks, emitter, CancellationToken())

    assert result.succeeded
    assert publisher is not None
    assert publisher.uploaded == (public_key,)
    assert publisher.verified == (public_key,)
    logs = [
        event
        for line in stream.getvalue().splitlines()
        if (event := parse_event_line(line)) is not None and event.kind == "log"
    ]
    assert [(event.stage, event.progress) for event in logs] == [
        (tool.ReleaseStage.PREFLIGHT, 0),
        (tool.ReleaseStage.PUBLISHING, 75),
        (tool.ReleaseStage.UPLOADING, 85),
        (tool.ReleaseStage.VERIFYING, 95),
    ]


def test_formal_new_release_rejects_a_pre_staged_unrelated_file_before_version_apply(tmp_path):
    tool = _load_tool()
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release-test@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repository, check=True)
    (repository / "unrelated.txt").write_text("must not be committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repository, check=True)
    notes = tmp_path / "notes.md"
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    notes.write_text("notes\n", encoding="utf-8")
    private_key.write_text("private\n", encoding="utf-8")
    public_key.write_text("public\n", encoding="utf-8")
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path=str(notes),
        private_key_path=str(private_key),
        sign_manifest=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
    )
    applied = Mock()

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "PROJECT_ROOT", repository),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_read_only_public_key_path", return_value=public_key),
        patch.object(tool, "apply_version_update", applied),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    applied.assert_not_called()


def test_non_public_new_release_rejects_dirty_checkout_before_version_apply(tmp_path):
    tool = _load_tool()
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "release-test@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=repository, check=True)
    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
    )
    applied = Mock()

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "PROJECT_ROOT", repository),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "apply_version_update", applied),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    applied.assert_not_called()


def test_source_identity_refuses_to_push_when_head_moves_after_verified_commit(tmp_path):
    tool = _load_tool()
    expected_commit = "a" * 40
    moved_head = "b" * 40
    version_staged = False
    head_reads = 0
    git_calls: list[list[str]] = []

    class FakePublisher:
        def __init__(self, *_args, **_kwargs):
            pass

        def ensure_tag(self, *_args, **_kwargs):
            pass

    def fake_git(argv):
        nonlocal version_staged, head_reads
        git_calls.append(list(argv))
        command = argv[0]
        if command == "status":
            return ""
        if command == "diff":
            return "shared/version.py" if version_staged or "--cached" not in argv else ""
        if command == "add":
            version_staged = True
            return ""
        if command == "commit":
            version_staged = False
            return ""
        if command == "diff-tree":
            return "shared/version.py"
        if command == "rev-parse" and argv[1] == "HEAD":
            head_reads += 1
            return expected_commit if head_reads == 1 else moved_head
        if command == "rev-parse":
            return expected_commit
        return ""

    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
    )
    version_plan = VersionUpdatePlan(tool.PROJECT_ROOT, "3.6.21", "3.6.22", ())
    version_result = VersionUpdateResult(
        "3.6.21",
        "3.6.22",
        (tool.PROJECT_ROOT / "shared/version.py",),
    )

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "GitHubReleasePublisher", FakePublisher),
        patch.object(tool, "plan_version_update", return_value=version_plan),
        patch.object(tool, "apply_version_update", return_value=version_result),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_run_git", side_effect=fake_git),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.SOURCE_IDENTITY
    assert not any(call[0] == "push" for call in git_calls)


def test_rotated_trust_anchor_is_included_in_exact_release_commit(tmp_path):
    tool = _load_tool()
    expected_paths = (
        "app/config/update_trust.py",
        "shared/version.py",
    )
    private_key = tmp_path / "outside" / "manifest-private.pem"
    public_key = tmp_path / "outside" / "manifest-public.pem"
    private_key.parent.mkdir()
    private_key.write_text("private", encoding="utf-8")
    public_key.write_text(
        "-----BEGIN PUBLIC KEY-----\npublic\n-----END PUBLIC KEY-----\n",
        encoding="utf-8",
    )
    key_result = ManifestKeyResult(
        private_key_path=private_key,
        public_key_path=public_key,
        public_key_fingerprint_sha256="A" * 64,
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        build_installer=True,
        run_smoke_tests=False,
        commit_version_changes=True,
    )
    version_plan = VersionUpdatePlan(tool.PROJECT_ROOT, "3.6.21", "3.6.22", ())
    version_result = VersionUpdateResult(
        "3.6.21",
        "3.6.22",
        (
            tool.UPDATE_TRUST_CONFIG,
            tool.PROJECT_ROOT / "shared/version.py",
            tool.UPDATE_TRUST_CONFIG,
        ),
    )
    staged = False
    git_calls: list[list[str]] = []

    def fake_git(argv):
        nonlocal staged
        git_calls.append(list(argv))
        if argv[0] == "status":
            return ""
        if argv[0] == "diff":
            if "--cached" in argv:
                return "\n".join(expected_paths) if staged else ""
            return "" if staged else "\n".join(expected_paths)
        if argv[0] == "add":
            staged = True
            return ""
        if argv[0] == "commit":
            return ""
        if argv[0] == "diff-tree":
            return "\n".join(expected_paths)
        if argv[:2] == ["rev-parse", "HEAD"]:
            return "a" * 40
        return ""

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "plan_version_update", return_value=version_plan),
        patch.object(tool, "apply_version_update", return_value=version_result),
        patch.object(
            tool,
            "begin_manifest_key_transaction",
            return_value=Mock(
                result=key_result,
                commit=Mock(),
                rollback=Mock(),
            ),
        ) as begin_transaction,
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_run_git", side_effect=fake_git),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        hooks.prepare(request, tool.ReleaseMode.NEW_RELEASE)
        material = hooks.resolve_signing_material(request)
        hooks.apply_version(request.target_version)
        commit = hooks.commit_version_changes(request)

    assert material.trust_anchor_changed is True
    assert commit == "a" * 40
    assert (
        begin_transaction.call_args.kwargs["config_path"]
        == tool.UPDATE_TRUST_CONFIG
    )
    add_call = next(call for call in git_calls if call[0] == "add")
    assert add_call[2:] == list(expected_paths)
    commit_call = next(call for call in git_calls if call[0] == "commit")
    assert commit_call[-2:] == list(expected_paths)


def test_normal_signing_reuses_external_key_without_rotating_trust_anchor(tmp_path):
    tool = _load_tool()
    key = ECC.generate(curve="Ed25519")
    private_key = tmp_path / "external" / "manifest-private.pem"
    private_key.parent.mkdir()
    private_key.write_text(key.export_key(format="PEM"), encoding="utf-8")
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        private_key_path=str(private_key),
        sign_manifest=True,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
    )
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream)

    with patch.object(
        tool,
        "begin_manifest_key_transaction",
        side_effect=AssertionError("normal signing must not generate a key"),
    ) as begin_transaction:
        hooks = tool._build_pipeline_hooks(request, {}, emitter=emitter)
        material = hooks.resolve_signing_material(request)

    begin_transaction.assert_not_called()
    assert material.private_key_path == private_key.resolve()
    assert material.trust_anchor_changed is False
    output = stream.getvalue()
    assert private_key.name in output
    assert str(private_key.parent) not in output
    assert "BEGIN PRIVATE KEY" not in output
    assert material.fingerprint in output


def test_private_key_validation_error_does_not_expose_workspace_path():
    tool = _load_tool()
    private_key = tool.PROJECT_ROOT / "sensitive" / "manifest-private.pem"

    with pytest.raises(SystemExit) as error:
        tool._validate_private_key_path(private_key)

    message = str(error.value)
    assert str(private_key) not in message
    assert str(private_key.parent) not in message


def test_public_key_upload_uses_external_standalone_asset(tmp_path):
    tool = _load_tool()
    key = ECC.generate(curve="Ed25519")
    public_key = tmp_path / "external" / "manifest-public.pem"
    public_key.parent.mkdir()
    public_key.write_text(
        key.public_key().export_key(format="PEM"),
        encoding="utf-8",
    )
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        same_release_repair=True,
        create_or_update_release=True,
        upload_public_key=True,
        verify_remote_assets=True,
    )
    publisher = Mock()
    manifest = tmp_path / "release-assets" / "latest.json"

    with (
        patch.object(tool, "GitHubReleasePublisher", return_value=publisher),
        patch.object(tool, "_read_only_public_key_path", return_value=public_key),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        material = hooks.resolve_signing_material(request)
        hooks.upload_assets(request, (manifest,))

    assert material.public_key_path == public_key.resolve()
    uploaded = publisher.upload_assets.call_args.args[1]
    assert uploaded == (manifest, public_key.resolve())
    with pytest.raises(ValueError):
        public_key.resolve().relative_to(tool.PROJECT_ROOT.resolve())


@pytest.mark.parametrize("public_state", ["missing", "mismatched"])
def test_public_key_upload_repairs_external_public_pem_from_private_key(
    tmp_path,
    public_state,
):
    tool = _load_tool()
    key = ECC.generate(curve="Ed25519")
    private_key = tmp_path / "external" / "manifest-private.pem"
    public_key = tmp_path / "external" / "manifest-public.pem"
    private_key.parent.mkdir()
    private_key.write_text(key.export_key(format="PEM"), encoding="utf-8")
    if public_state == "mismatched":
        public_key.write_text(
            ECC.generate(curve="Ed25519").public_key().export_key(format="PEM"),
            encoding="utf-8",
        )
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        same_release_repair=True,
        create_or_update_release=True,
        upload_public_key=True,
        verify_remote_assets=True,
        private_key_path=str(private_key),
    )

    with patch.object(tool, "_read_only_public_key_path", return_value=public_key):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        hooks.validate_dependencies(request)
        material = hooks.resolve_signing_material(request)

    expected_public = key.public_key().export_key(format="PEM")
    assert material.private_key_path == private_key.resolve()
    assert material.public_key_path == public_key.resolve()
    assert public_key.read_text(encoding="utf-8") == expected_public


def test_new_release_tag_hook_rejects_an_empty_verified_commit_without_reading_head():
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
    )
    publisher = Mock()

    with (
        patch.object(tool, "GitHubReleasePublisher", return_value=publisher),
        patch.object(tool, "_run_git", return_value="a" * 40) as run_git,
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        with pytest.raises(SystemExit, match="verified version commit"):
            hooks.ensure_tag(request, "")

    run_git.assert_not_called()
    publisher.ensure_tag.assert_not_called()


@pytest.mark.parametrize(
    "proxy_fields",
    [
        {"proxy_label": "env:RELEASE_PROXY_URL"},
        {
            "proxy_label": "\u81ea\u5b9a\u4e49",
            "custom_proxy": "env:RELEASE_PROXY_URL",
        },
    ],
)
def test_authenticated_proxy_environment_reference_preserves_secure_provenance(
    proxy_fields,
):
    tool = _load_tool()
    credentialed_proxy = "socks5://alice:proxy-secret@127.0.0.1:1080"
    captured_environment: dict[str, str] = {}
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream)

    class FakePublisher:
        def __init__(self, _repository, environment, emit_log, **_kwargs):
            captured_environment.update(environment)
            emit_log(f"proxy={environment['HTTPS_PROXY']}")

    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        **proxy_fields,
    )

    with patch.object(tool, "GitHubReleasePublisher", FakePublisher):
        hooks = tool._build_pipeline_hooks(
            request,
            {"RELEASE_PROXY_URL": credentialed_proxy},
            emitter,
        )
        hooks.validate_dependencies(request)

    for name in PROXY_ENVIRONMENT_VARIABLES:
        assert captured_environment[name] == credentialed_proxy
    assert "alice" not in stream.getvalue()
    assert "proxy-secret" not in stream.getvalue()
    assert "[REDACTED]@127.0.0.1:1080" in stream.getvalue()


def test_direct_authenticated_custom_proxy_remains_rejected_without_echoing_credentials():
    tool = _load_tool()
    credentialed_proxy = "http://alice:direct-secret@127.0.0.1:7890"
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        proxy_label="\u81ea\u5b9a\u4e49",
        custom_proxy=credentialed_proxy,
    )

    hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
    with pytest.raises(ValueError, match="invalid custom proxy endpoint") as caught:
        hooks.validate_dependencies(request)

    assert "alice" not in str(caught.value)
    assert "direct-secret" not in str(caught.value)


@pytest.mark.parametrize("public_key", [None, "not a public key"])
def test_upload_public_key_dependency_rejects_missing_or_invalid_key_before_publish(tmp_path, public_key):
    tool = _load_tool()
    notes = tmp_path / "notes.md"
    notes.write_text("notes\n", encoding="utf-8")
    public_key_path = tmp_path / "public.pem"
    if public_key is not None:
        public_key_path.write_text(public_key, encoding="utf-8")
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path=str(notes),
        apply_version=False,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        same_release_repair=True,
        create_or_update_release=True,
        upload_public_key=True,
        verify_remote_assets=True,
    )

    missing_private_key = tmp_path / "missing-private.pem"
    with (
        patch.object(
            tool,
            "_read_only_public_key_path",
            return_value=public_key_path,
        ),
        patch.object(
            tool,
            "_read_only_secret_path",
            return_value=missing_private_key,
        ),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    assert not result.succeeded


def test_dry_run_dependency_preflight_rejects_missing_notes_without_acquiring_a_lock(tmp_path):
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path=str(tmp_path / "missing-notes.md"),
        private_key_path=str(tmp_path / "missing-private.pem"),
        dry_run=True,
        sign_manifest=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    acquire_lock = Mock()

    with patch.object(tool, "_release_build_lock", acquire_lock):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    acquire_lock.assert_not_called()


@pytest.mark.parametrize("key_case", ["missing", "empty", "malformed", "unreadable"])
def test_private_key_dependency_preflight_rejects_invalid_material_before_mutation(
    tmp_path,
    key_case,
):
    tool = _load_tool()
    private_key = tmp_path / "private.pem"
    if key_case == "empty":
        private_key.write_bytes(b"")
    elif key_case in {"malformed", "unreadable"}:
        private_key.write_text(
            "-----BEGIN PRIVATE KEY-----\nnot-ed25519-key\n-----END PRIVATE KEY-----\n",
            encoding="utf-8",
        )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        private_key_path=str(private_key),
        dry_run=True,
        sign_manifest=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
    )
    applied = Mock()

    patches = [patch.object(tool, "apply_version_update", applied)]
    if key_case == "unreadable":
        patches.append(patch.object(tool.Path, "read_text", side_effect=PermissionError("denied")))

    with patches[0]:
        if len(patches) == 2:
            with patches[1]:
                hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
                result = run_release_request(request, hooks, Mock(), CancellationToken())
        else:
            hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
            result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    applied.assert_not_called()
    assert "not-ed25519-key" not in result.error


@pytest.mark.parametrize(
    "build_request",
    [
        BuildRequest(
            target_version="3.6.20",
            remote=RemoteReleaseInfo.available("3.6.21"),
            apply_version=False,
            build_portable=False,
            build_installer=False,
            run_smoke_tests=False,
            proxy_label="自定义",
            custom_proxy="env:MISSING_RELEASE_PROXY",
        ),
        BuildRequest(
            target_version="3.6.20",
            remote=RemoteReleaseInfo.available("3.6.21"),
            repository="invalid/repository/shape",
            apply_version=False,
            build_portable=False,
            build_installer=False,
            run_smoke_tests=False,
        ),
    ],
)
def test_hook_setup_failures_are_runner_owned_terminal_failures(build_request):
    tool = _load_tool()
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream)
    acquire_lock = Mock()
    build_binaries = Mock()

    with (
        patch.object(tool, "_release_build_lock", acquire_lock),
        patch.object(tool, "_build_binaries", build_binaries),
    ):
        hooks = tool._build_pipeline_hooks(build_request, {}, emitter)
        result = run_release_request(build_request, hooks, emitter, CancellationToken())

    events = [
        event
        for line in stream.getvalue().splitlines()
        if (event := parse_event_line(line)) is not None
    ]
    assert result.failed_stage is tool.ReleaseStage.PREFLIGHT
    assert sum(event.kind == "error" for event in events) == 1
    assert sum(event.kind == "result" for event in events) == 1
    acquire_lock.assert_not_called()
    build_binaries.assert_not_called()


def test_real_pipeline_hook_system_exit_is_redacted_and_terminal(tmp_path):
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_installer=False,
        run_smoke_tests=False,
    )
    stream = io.StringIO()
    emitter = ReleaseEventEmitter(stream=stream)

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    with (
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(
            tool,
            "_build_binaries",
            side_effect=SystemExit("Authorization: Bearer ghp_real_hook_secret"),
        ),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter)
        result = run_release_request(request, hooks, emitter, CancellationToken())

    events = [
        event
        for line in stream.getvalue().splitlines()
        if (event := parse_event_line(line)) is not None
    ]
    assert result.failed_stage is tool.ReleaseStage.BUILDING_PORTABLE
    assert "ghp_real_hook_secret" not in result.error
    assert sum(event.kind == "error" for event in events) == 1
    assert sum(event.kind == "result" for event in events) == 1


def test_pipeline_smoke_runs_cli_help_with_timeout_and_no_stdin(tmp_path):
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_installer=False,
    )
    cli = tmp_path / "dist" / "UniversalCrawlerPro" / "UCrawlCLI.exe"
    build_info = cli.parent / "BUILD_INFO.txt"

    def fake_build(*_args, **_kwargs):
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.write_bytes(b"MZ")
        build_info.write_text("build", encoding="utf-8")

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    completed = subprocess.CompletedProcess([], 0, stdout="usage", stderr="")
    with (
        patch.object(tool, "PROJECT_ROOT", tmp_path),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_build_binaries", side_effect=fake_build),
        patch.object(tool.subprocess, "run", return_value=completed) as run,
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert result.succeeded
    smoke = run.call_args
    assert smoke.args[0] == [str(cli.resolve()), "--mode", "cli", "--help"]
    assert smoke.kwargs["cwd"] == cli.parent.resolve()
    assert smoke.kwargs["stdin"] is subprocess.DEVNULL
    assert smoke.kwargs["shell"] is False
    assert 0 < smoke.kwargs["timeout"] <= 60


def test_pipeline_smoke_failure_blocks_success(tmp_path):
    tool = _load_tool()
    request = BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        build_installer=False,
    )
    cli = tmp_path / "dist" / "UniversalCrawlerPro" / "UCrawlCLI.exe"

    def fake_build(*_args, **_kwargs):
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.write_bytes(b"MZ")
        (cli.parent / "BUILD_INFO.txt").write_text("build", encoding="utf-8")

    @contextmanager
    def fake_lock(_project_root):
        yield "release-token"

    completed = subprocess.CompletedProcess([], 7, stdout="", stderr="failed")
    with (
        patch.object(tool, "PROJECT_ROOT", tmp_path),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_build_binaries", side_effect=fake_build),
        patch.object(tool.subprocess, "run", return_value=completed),
    ):
        hooks = tool._build_pipeline_hooks(request, {}, emitter=None)
        result = run_release_request(request, hooks, Mock(), CancellationToken())

    assert not result.succeeded
    assert result.failed_stage is tool.ReleaseStage.SMOKE_TESTING


def test_run_build_passes_the_snapshot_project_root_to_each_build_script(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    script = snapshot_root / "packaging" / "build_portable.py"
    script.parent.mkdir(parents=True)
    script.write_text("# snapshot build script\n", encoding="utf-8")

    with patch.object(tool.subprocess, "run") as run:
        tool._run_build(
            "build_portable.py",
            snapshot_root,
            lock_token="release-token",
            lock_root=PROJECT_ROOT,
        )

    run.assert_called_once_with(
        [
            sys.executable,
            str(script),
            "--project-root",
            str(snapshot_root.resolve()),
        ],
        cwd=snapshot_root.resolve(),
        check=True,
        shell=False,
        env=run.call_args.kwargs["env"],
    )


def test_run_build_passes_the_parent_release_lock_token_to_snapshot_script(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    script = snapshot_root / "packaging" / "build_portable.py"
    script.parent.mkdir(parents=True)
    script.write_text("# snapshot build script\n", encoding="utf-8")
    lock_root = tmp_path / "checkout"
    lock_root.mkdir()

    with patch.object(tool.subprocess, "run") as run:
        tool._run_build(
            "build_portable.py",
            snapshot_root,
            lock_token="release-token",
            lock_root=lock_root,
        )

    environment = run.call_args.kwargs["env"]
    assert environment["UCRAWL_RELEASE_LOCK_TOKEN"] == "release-token"
    assert environment["UCRAWL_RELEASE_LOCK_ROOT"] == str(lock_root.resolve())
    assert environment["UCRAWL_USER_DATA_ROOT"] == str(
        snapshot_root.resolve() / "build" / "runtime-user-data"
    )


@pytest.mark.parametrize("script_name", ["build_portable.py", "build_installer.py"])
def test_build_scripts_accept_and_validate_the_snapshot_project_root(tmp_path, script_name):
    script = PROJECT_ROOT / "packaging" / script_name
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--project-root" in help_result.stdout

    mismatched = subprocess.run(
        [sys.executable, str(script), "--project-root", str(tmp_path / "other-root")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatched.returncode != 0
    assert "project root" in (mismatched.stderr + mismatched.stdout)


def test_source_snapshot_is_immutable_during_build_and_removed_on_failure(
    tmp_path,
    monkeypatch,
):
    tool = _load_tool()
    repository = tmp_path / "repository"
    repository.mkdir()
    short_root = tmp_path / "release-tmp"
    monkeypatch.setenv(tool.RELEASE_TEMP_ROOT_ENV, str(short_root))
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Test"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("committed bytes\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "snapshot"], cwd=repository, check=True)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    snapshot_root: Path | None = None

    with pytest.raises(RuntimeError, match="build failed"):
        with tool._source_snapshot(source_commit, repository_root=repository) as snapshot:
            snapshot_root = snapshot
            assert snapshot.name == "p"
            assert snapshot.parent.parent == short_root.resolve()
            tracked.write_text("mutable worktree bytes\n", encoding="utf-8")
            assert (snapshot / "tracked.txt").read_text(encoding="utf-8") == "committed bytes\n"
            assert not (snapshot / ".git").exists()
            raise RuntimeError("build failed")

    assert snapshot_root is not None
    assert not snapshot_root.exists()


def test_release_snapshot_temp_root_defaults_to_repository_sibling(tmp_path, monkeypatch):
    tool = _load_tool()
    repository = tmp_path / "workspace" / "repository"
    repository.mkdir(parents=True)
    monkeypatch.delenv(tool.RELEASE_TEMP_ROOT_ENV, raising=False)

    root = tool._release_snapshot_temp_root(repository)

    assert root == (repository.parent / ".ucrawl-release-tmp").resolve()
    assert root.is_dir()


def test_source_snapshot_materializes_lfs_files_when_smudge_is_disabled(monkeypatch):
    tool = _load_tool()
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    lfs_payload = json.loads(
        subprocess.run(
            ["git", "lfs", "ls-files", "--json", source_commit],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    expected = {entry["name"]: entry for entry in lfs_payload["files"]}
    assert {"N_m3u8DL-RE.exe", "ffprobe.exe"} <= set(expected)
    monkeypatch.setenv("GIT_LFS_SKIP_SMUDGE", "1")

    with tool._source_snapshot(source_commit, repository_root=PROJECT_ROOT) as snapshot:
        for name, entry in expected.items():
            materialized = snapshot / name
            assert materialized.stat().st_size == entry["size"]
            assert _file_sha256(materialized) == entry["oid"]
        for name in ("N_m3u8DL-RE.exe", "ffmpeg.exe", "ffprobe.exe"):
            windows_tool = snapshot / name
            assert windows_tool.stat().st_size >= 1024 * 1024
            with windows_tool.open("rb") as handle:
                assert handle.read(2) == b"MZ"


@pytest.mark.parametrize(
    ("expected_oid", "expected_size", "message"),
    [
        (hashlib.sha256(b"MZpayload").hexdigest(), 99, "size|大小"),
        ("0" * 64, len(b"MZpayload"), "SHA-256|OID|哈希"),
    ],
)
def test_lfs_materialization_rejects_size_or_oid_mismatch(
    tmp_path,
    expected_oid,
    expected_size,
    message,
):
    tool = _load_tool()
    materialized = tmp_path / "tool.exe"
    materialized.write_bytes(b"MZpayload")

    with pytest.raises(SystemExit, match=message):
        tool._validate_materialized_lfs_file(
            materialized,
            expected_oid=expected_oid,
            expected_size=expected_size,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-a-pe" + b"x" * (1024 * 1024), "PE|MZ"),
        (b"MZtiny", "size|大小|过小"),
    ],
    ids=("bad-magic", "too-small"),
)
def test_windows_release_tool_validation_rejects_invalid_pe_or_tiny_file(
    tmp_path,
    payload,
    message,
):
    tool = _load_tool()
    for name in ("N_m3u8DL-RE.exe", "ffmpeg.exe", "ffprobe.exe"):
        (tmp_path / name).write_bytes(b"MZ" + b"x" * (1024 * 1024))
    (tmp_path / "ffprobe.exe").write_bytes(payload)

    with pytest.raises(SystemExit, match=message):
        tool._validate_windows_release_tools(tmp_path)


def test_release_build_and_publish_use_the_same_snapshot_under_one_lock(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    snapshot_installer = (
        snapshot_root / "dist" / "installer" / "UniversalCrawlerPro_Setup_3.6.21.exe"
    )
    private_key = tmp_path / "manifest-private.pem"
    private_key.write_text("private", encoding="utf-8")
    lock_held = False
    calls: list[tuple[str, Path]] = []

    def fake_metadata(project_root: Path = tool.PROJECT_ROOT):
        root = Path(project_root)
        return "3.6.21", (
            root / "dist" / "installer" / "UniversalCrawlerPro_Setup_3.6.21.exe"
        )

    @contextmanager
    def fake_lock(_project_root: Path):
        nonlocal lock_held
        assert not lock_held
        lock_held = True
        try:
            yield "release-token"
        finally:
            lock_held = False

    @contextmanager
    def fake_snapshot(source_commit: str, *, repository_root: Path):
        assert source_commit == "a" * 40
        assert repository_root == tool.PROJECT_ROOT
        yield snapshot_root

    def fake_build(project_root: Path, **kwargs):
        assert lock_held
        assert kwargs["lock_token"] == "release-token"
        assert kwargs["lock_root"] == tool.PROJECT_ROOT
        calls.append(("build", project_root))

    def fake_prepare(**kwargs):
        assert lock_held
        assert kwargs["project_root"] == snapshot_root
        calls.append(("publish", kwargs["installer"]))
        release_dir = tmp_path / "release-assets" / "v3.6.21"
        release_dir.mkdir(parents=True)
        return release_dir

    with (
        patch.object(tool, "_project_release_metadata", side_effect=fake_metadata),
        patch.object(tool, "_validate_private_key_path", return_value=private_key),
        patch.object(tool, "_validate_git_release_state", return_value="a" * 40),
        patch.object(tool, "_release_build_lock", side_effect=fake_lock),
        patch.object(tool, "_source_snapshot", side_effect=fake_snapshot),
        patch.object(tool, "_validate_windows_release_tools"),
        patch.object(tool, "_build_binaries", side_effect=fake_build),
        patch.object(tool, "_prepare_release_assets", side_effect=fake_prepare),
    ):
        result = tool.main(
            [
                "--private-key",
                str(private_key),
                "--output-root",
                str(tmp_path / "release-assets"),
            ]
        )

    assert result == 0
    assert calls == [("build", snapshot_root), ("publish", snapshot_installer)]
    assert not lock_held


def test_build_rejects_mutation_of_original_snapshot_files(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    tracked = snapshot_root / "app" / "config" / "update_trust.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed trust\n", encoding="utf-8")
    build_count = 0

    def mutate_source(_script_name, _project_root, **_kwargs):
        nonlocal build_count
        build_count += 1
        if build_count == 1:
            tracked.write_text("mutated trust\n", encoding="utf-8")

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(tool, "_run_build", side_effect=mutate_source),
        pytest.raises(SystemExit, match="sourceCommit|snapshot|快照|源码"),
    ):
        tool._build_binaries(
            snapshot_root,
            lock_token="release-token",
            lock_root=PROJECT_ROOT,
        )


def test_build_rejects_new_source_files_added_during_snapshot_build(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    tracked = snapshot_root / "app" / "config" / "update_trust.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed trust\n", encoding="utf-8")
    generated = snapshot_root / "app" / "config" / "generated_trust.py"
    build_count = 0

    def add_source(_script_name, _project_root, **_kwargs):
        nonlocal build_count
        build_count += 1
        if build_count == 1:
            generated.write_text("injected trust\n", encoding="utf-8")

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(tool, "_run_build", side_effect=add_source),
        pytest.raises(SystemExit, match="sourceCommit|snapshot|快照|源码"),
    ):
        tool._build_binaries(
            snapshot_root,
            lock_token="release-token",
            lock_root=PROJECT_ROOT,
        )


def test_build_lock_rejects_a_second_instance_before_any_build(tmp_path):
    tool = _load_tool()
    lock_path = tmp_path / "release.lock"
    run_build = Mock()

    with (
        patch.object(tool, "_release_lock_path", return_value=lock_path),
        tool._release_build_lock(tool.PROJECT_ROOT),
        patch.object(tool, "_run_build", run_build),
        pytest.raises(SystemExit, match="release.*lock|another.*build|发布.*构建|构建.*占用"),
    ):
        tool.main(["--build-only"])

    run_build.assert_not_called()


def test_build_lock_is_released_when_the_owner_fails(tmp_path):
    tool = _load_tool()
    lock_path = tmp_path / "release.lock"

    with patch.object(tool, "_release_lock_path", return_value=lock_path):
        with pytest.raises(RuntimeError, match="boom"):
            with tool._release_build_lock(tool.PROJECT_ROOT):
                raise RuntimeError("boom")
        with tool._release_build_lock(tool.PROJECT_ROOT):
            pass


def test_build_lock_is_exclusive_across_processes(tmp_path):
    tool = _load_tool()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    child_code = """
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("ucrawl_release_lock_child", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with module._release_build_lock(Path(sys.argv[2])):
    print("locked", flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(BUILD_RELEASE_TOOL), str(checkout)],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        ready = child.stdout.readline().strip()
        if ready != "locked":
            assert child.stderr is not None
            pytest.fail(child.stderr.read() or f"lock child exited with {child.returncode}")
        with pytest.raises(SystemExit, match="release.*lock|发布.*构建|构建.*占用"):
            with tool._release_build_lock(checkout):
                pass
    finally:
        if child.stdin is not None:
            child.stdin.write("release\n")
            child.stdin.flush()
            child.stdin.close()
        child.wait(timeout=10)

    assert child.returncode == 0


@pytest.mark.parametrize("script_name", ["build_portable.py", "build_installer.py"])
def test_direct_leaf_build_cannot_bypass_parent_release_lock(tmp_path, script_name):
    tool = _load_tool()
    child_code = r'''
import importlib.util
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("ucrawl_leaf_lock_probe", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if script.name == "build_portable.py":
    module.ensure_prerequisites = lambda: None
    module.clean_previous_outputs = lambda: None
    module.run_pyinstaller = lambda: None
    module.copy_python_sqlite_runtime_files = lambda: None
    module.copy_portable_root_docs = lambda: None
    module.verify_output = lambda: None
    module.write_manifest = lambda: None
else:
    output = Path(sys.argv[2])
    module.ensure_prerequisites = lambda: "iscc"
    module.get_setup_exe_path = lambda: output
    def fake_run(*_args, **_kwargs):
        output.write_bytes(b"MZ" + b"x" * 1024)
    module.subprocess.run = fake_run
    module.maybe_sign_windows_installer = lambda _path: None
module.main([])
'''
    script = PROJECT_ROOT / "packaging" / script_name
    output = tmp_path / "setup.exe"

    with tool._release_build_lock(PROJECT_ROOT):
        child = subprocess.run(
            [sys.executable, "-c", child_code, str(script), str(output)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    assert child.returncode != 0
    assert "lock" in (child.stdout + child.stderr).lower() or "构建" in (
        child.stdout + child.stderr
    )


def test_prepare_release_assets_atomically_publishes_exact_required_triplet(tmp_path):
    tool = _load_tool()
    installer = tmp_path / "installer" / "UniversalCrawlerPro_Setup_3.6.21.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"signed-installer")
    private_key = tmp_path / "outside-repo" / "manifest-private.pem"
    private_key.parent.mkdir()
    private_key.write_text("private", encoding="utf-8")
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()

    def fake_manifest(argv: list[str], **_kwargs) -> None:
        output_dir = Path(argv[argv.index("--output-dir") + 1])
        asset_spec = Path(argv[argv.index("--asset-spec") + 1])
        source_commit = argv[argv.index("--source-commit") + 1]
        specs = json.loads(asset_spec.read_text(encoding="utf-8"))
        assert specs[0]["path"] == str(output_dir / installer.name)
        (output_dir / "latest.json").write_text(
            json.dumps(_release_payload(output_dir / installer.name, source_commit=source_commit)),
            encoding="utf-8",
        )
        (output_dir / "latest.json.sig").write_bytes(b"signature")

    with (
        patch.object(tool, "_run_manifest_tool", side_effect=fake_manifest),
        patch.object(tool, "_validate_private_key_path", return_value=private_key),
        patch.object(tool, "_verify_staged_manifest") as verify_manifest,
        patch.object(tool, "_validate_git_release_state", return_value="a" * 40),
    ):
        release_dir = tool._prepare_release_assets(
            installer=installer,
            private_key=private_key,
            version="3.6.21",
            tag="v3.6.21",
            source_commit="a" * 40,
            repository="haohaizi554/UniversalCrawler",
            output_root=tmp_path / "release-assets",
            notes="emergency rebuild",
            project_root=snapshot_root,
        )

    assert release_dir == tmp_path / "release-assets" / "v3.6.21"
    assert {path.name for path in release_dir.iterdir()} == {
        installer.name,
        "latest.json",
        "latest.json.sig",
    }
    verify_manifest.assert_called_once()


def test_prepare_release_assets_revalidates_live_tag_head_before_atomic_publish(tmp_path):
    tool = _load_tool()
    installer = tmp_path / "installer" / "UniversalCrawlerPro_Setup_3.6.21.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"signed-installer")
    private_key = tmp_path / "outside-repo" / "manifest-private.pem"
    private_key.parent.mkdir()
    private_key.write_text("private", encoding="utf-8")
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()
    source_commits: list[str] = []

    def fake_manifest(argv: list[str], **_kwargs) -> None:
        output_dir = Path(argv[argv.index("--output-dir") + 1])
        source_commit = argv[argv.index("--source-commit") + 1]
        source_commits.append(source_commit)
        staged_installer = output_dir / installer.name
        (output_dir / "latest.json").write_text(
            json.dumps(_release_payload(staged_installer, source_commit=source_commit)),
            encoding="utf-8",
        )
        (output_dir / "latest.json.sig").write_bytes(b"signature")

    output_root = tmp_path / "release-assets"
    with (
        patch.object(tool, "_run_manifest_tool", side_effect=fake_manifest),
        patch.object(tool, "_validate_private_key_path", return_value=private_key),
        patch.object(tool, "_verify_staged_manifest"),
        patch.object(tool, "_validate_git_release_state", return_value="b" * 40),
        pytest.raises(SystemExit, match="HEAD|tag|source commit|源提交|提交"),
    ):
        tool._prepare_release_assets(
            installer=installer,
            private_key=private_key,
            version="3.6.21",
            tag="v3.6.21",
            source_commit="a" * 40,
            repository="haohaizi554/UniversalCrawler",
            output_root=output_root,
            notes="emergency rebuild",
            project_root=snapshot_root,
        )

    assert source_commits == ["a" * 40]
    assert not (output_root / "v3.6.21").exists()


def test_manifest_generation_and_verification_use_snapshot_tools(tmp_path):
    tool = _load_tool()
    snapshot_root = tmp_path / "snapshot"
    manifest_tool = snapshot_root / "packaging" / "update_manifest.py"
    manifest_tool.parent.mkdir(parents=True)
    manifest_tool.write_text("# snapshot manifest tool\n", encoding="utf-8")
    manifest = tmp_path / "latest.json"
    signature = tmp_path / "latest.json.sig"
    manifest.write_text("{}", encoding="utf-8")
    signature.write_bytes(b"signature")

    with patch.object(tool.subprocess, "run") as run:
        tool._run_manifest_tool(["--probe"], project_root=snapshot_root)

    assert run.call_args.args[0][1] == str(manifest_tool)
    assert run.call_args.kwargs["cwd"] == snapshot_root.resolve()

    with patch.object(tool.subprocess, "run") as run:
        tool._verify_staged_manifest(
            manifest,
            signature,
            project_root=snapshot_root,
        )

    verify_argv = run.call_args.args[0]
    assert verify_argv[0] == sys.executable
    assert "-I" in verify_argv
    assert str(snapshot_root.resolve()) in verify_argv
    assert run.call_args.kwargs["cwd"] == snapshot_root.resolve()


def test_manifest_tool_failure_does_not_expose_private_key_path(tmp_path):
    tool = _load_tool()
    private_key = tmp_path / "release-secrets" / "manifest-private.pem"
    command = [
        sys.executable,
        str(tool.UPDATE_MANIFEST_TOOL),
        "--private-key",
        str(private_key),
    ]

    with (
        patch.object(
            tool.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, command),
        ),
        pytest.raises(RuntimeError) as caught,
    ):
        tool._run_manifest_tool(
            ["--private-key", str(private_key)],
            project_root=tool.PROJECT_ROOT,
        )

    message = str(caught.value)
    assert str(private_key) not in message
    assert str(private_key.parent) not in message


def test_release_identity_must_match_the_built_package_version():
    tool = _load_tool()

    with pytest.raises(SystemExit, match="3.6.17.*3.6.21|3.6.21.*3.6.17"):
        tool._validate_release_identity(
            package_version="3.6.17",
            version="3.6.21",
            tag="v3.6.21",
        )


def test_release_identity_requires_tag_to_match_version():
    tool = _load_tool()

    with pytest.raises(SystemExit, match="tag"):
        tool._validate_release_identity(
            package_version="3.6.21",
            version="3.6.21",
            tag="v3.6.20",
        )


def test_release_identity_rejects_a_prefixed_package_version():
    tool = _load_tool()

    with pytest.raises(SystemExit, match="must not include a v prefix"):
        tool._validate_release_identity(
            package_version="v3.6.21",
            version="3.6.21",
            tag="v3.6.21",
        )


def test_git_release_state_rejects_dirty_source_tree():
    tool = _load_tool()

    with (
        patch.object(tool, "_run_git", return_value=" M app/core.py\n"),
        pytest.raises(SystemExit, match="工作树|dirty|未提交"),
    ):
        tool._validate_git_release_state("v3.6.21")


def test_git_release_state_rejects_tag_that_does_not_point_to_head():
    tool = _load_tool()
    outputs = iter(["", "a" * 40, "b" * 40])

    with (
        patch.object(tool, "_run_git", side_effect=lambda _args: next(outputs)),
        pytest.raises(SystemExit, match="tag.*HEAD|HEAD.*tag"),
    ):
        tool._validate_git_release_state("v3.6.21")


def test_final_asset_validation_rejects_non_exact_triplet(tmp_path):
    tool = _load_tool()
    installer, _payload = _write_staged_release(tmp_path)
    (tmp_path / "unexpected").mkdir()

    with (
        patch.object(tool, "_verify_staged_manifest"),
        pytest.raises(RuntimeError, match="只能包含"),
    ):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_tampered_installer_hash(tmp_path):
    tool = _load_tool()
    installer, _payload = _write_staged_release(tmp_path)
    kwargs = _staged_validation_kwargs(installer)
    installer.write_bytes(b"tampered-installer")

    with patch.object(tool, "_verify_staged_manifest"), pytest.raises(RuntimeError, match="SHA-256"):
        tool._validate_staged_assets(tmp_path, **kwargs)


def test_final_asset_validation_rejects_manifest_size_mismatch(tmp_path):
    tool = _load_tool()
    installer, payload = _write_staged_release(tmp_path)
    payload["assets"]["windows-x64"]["size"] += 1
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(tool, "_verify_staged_manifest"), pytest.raises(RuntimeError, match="元数据"):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_manifest_url_mismatch(tmp_path):
    tool = _load_tool()
    installer, payload = _write_staged_release(tmp_path)
    payload["assets"]["windows-x64"]["url"] = "https://example.invalid/tampered.exe"
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(tool, "_verify_staged_manifest"), pytest.raises(RuntimeError, match="元数据"):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_tag_version_mismatch(tmp_path):
    tool = _load_tool()
    installer, payload = _write_staged_release(tmp_path)
    payload["version"] = "3.6.20"
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(tool, "_verify_staged_manifest"), pytest.raises(RuntimeError, match="version/tag"):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_source_commit_mismatch(tmp_path):
    tool = _load_tool()
    installer, payload = _write_staged_release(tmp_path)
    payload["sourceCommit"] = "b" * 40
    (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(tool, "_verify_staged_manifest"), pytest.raises(RuntimeError, match="sourceCommit"):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_empty_signature(tmp_path):
    tool = _load_tool()
    installer, _payload = _write_staged_release(tmp_path)
    (tmp_path / "latest.json.sig").write_bytes(b"")

    with pytest.raises(RuntimeError, match="sig.*空|为空"):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))


def test_final_asset_validation_rejects_invalid_signature(tmp_path):
    tool = _load_tool()
    installer, _payload = _write_staged_release(tmp_path)

    with (
        patch.object(tool, "_verify_staged_manifest", side_effect=RuntimeError("invalid signature")),
        pytest.raises(RuntimeError, match="invalid signature"),
    ):
        tool._validate_staged_assets(tmp_path, **_staged_validation_kwargs(installer))
