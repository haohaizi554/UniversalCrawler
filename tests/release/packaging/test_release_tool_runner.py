from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool import cancellation_control as cancellation_control_module
from release_tool.models import BuildRequest, ReleaseStage, RemoteReleaseInfo
from release_tool.events import parse_event_line
from release_tool.cancellation_control import (
    CancellationControlError,
    ReleaseCancellationControl,
    WindowsReleaseProcessJob,
)
from release_tool.runner import (
    CancellationToken,
    PipelineCancelled,
    ReleasePipelineHooks,
    SigningMaterial,
    load_request_file,
    run_release_request,
)
from release_tool.versioning import VersionUpdatePlan, VersionUpdateResult


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, **event: object) -> None:
        self.events.append({"kind": kind, **event})

    @property
    def stages(self) -> list[ReleaseStage]:
        return [event["stage"] for event in self.events if event["kind"] == "stage"]

    @property
    def skipped_stages(self) -> list[ReleaseStage]:
        return [
            event["stage"]
            for event in self.events
            if event["kind"] == "stage" and (event.get("data") or {}).get("status") == "skipped"
        ]


class RecordingHooks:
    def __init__(
        self,
        *,
        on_build_portable=None,
        build_installer_error: BaseException | None = None,
        smoke_error: BaseException | None = None,
        dependency_error: BaseException | None = None,
        version_commit: str = "a" * 40,
        cleanup=None,
    ) -> None:
        self.calls: list[str] = []
        self.on_build_portable = on_build_portable
        self.build_installer_error = build_installer_error
        self.smoke_error = smoke_error
        self.dependency_error = dependency_error
        self.version_commit = version_commit
        self.on_cleanup = cleanup
        self.version_after_failure = ""
        self._version = "3.6.21"

    def plan_version(self, target: str) -> VersionUpdatePlan:
        self.calls.append("plan_version")
        return VersionUpdatePlan(Path("."), self._version, target, ())

    def validate_dependencies(self, _request: BuildRequest) -> None:
        self.calls.append("validate_dependencies")
        if self.dependency_error:
            raise self.dependency_error

    def prepare(self, _request: BuildRequest, _mode) -> None:
        self.calls.append("prepare")

    def apply_version(self, target: str) -> VersionUpdateResult:
        self.calls.append("apply_version")
        previous = self._version
        self._version = target
        return VersionUpdateResult(previous, target, ())

    def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
        self.calls.append("resolve_signing_material")
        return SigningMaterial(
            private_key_path=Path("release-secrets/private-key.pem"),
            public_key_path=Path("release-secrets/public-key.pem"),
            fingerprint="A" * 64,
            trust_anchor_changed=request.rotate_trust_anchor,
        )

    def build_portable(self) -> None:
        self.calls.append("build_portable")
        if self.on_build_portable:
            self.on_build_portable()

    def build_installer(self) -> None:
        self.calls.append("build_installer")
        self.version_after_failure = self._version
        if self.build_installer_error:
            raise self.build_installer_error

    def run_smoke_tests(self) -> None:
        self.calls.append("smoke_test")
        if self.smoke_error:
            raise self.smoke_error

    def sign_manifest(self, request: BuildRequest) -> tuple[Path, ...]:
        self.calls.append("sign_manifest")
        return (Path("latest.json"), Path("latest.json.sig"))

    def commit_version_changes(self, request: BuildRequest) -> str:
        self.calls.append("commit_version_changes")
        return self.version_commit

    def push_main(self, request: BuildRequest, commit: str) -> None:
        self.calls.append("push_main")

    def ensure_tag(self, request: BuildRequest, commit: str) -> None:
        self.calls.append("ensure_tag")

    def ensure_release(self, request: BuildRequest) -> None:
        self.calls.append("ensure_release")

    def upload_assets(self, request: BuildRequest, assets: tuple[Path, ...]) -> None:
        self.calls.append("upload_assets")

    def verify_remote_assets(self, request: BuildRequest, assets: tuple[Path, ...]) -> None:
        self.calls.append("verify_remote_assets")

    def publish_release(self, request: BuildRequest) -> None:
        self.calls.append("publish_release")

    def cleanup(self) -> None:
        if self.on_cleanup:
            self.calls.append("cleanup")
            self.on_cleanup()

    def as_pipeline_hooks(self) -> ReleasePipelineHooks:
        return ReleasePipelineHooks(
            validate_dependencies=self.validate_dependencies,
            prepare=self.prepare,
            plan_version=self.plan_version,
            apply_version=self.apply_version,
            resolve_signing_material=self.resolve_signing_material,
            build_portable=self.build_portable,
            build_installer=self.build_installer,
            run_smoke_tests=self.run_smoke_tests,
            sign_manifest=self.sign_manifest,
            commit_version_changes=self.commit_version_changes,
            push_main=self.push_main,
            ensure_tag=self.ensure_tag,
            ensure_release=self.ensure_release,
            upload_assets=self.upload_assets,
            verify_remote_assets=self.verify_remote_assets,
            publish_release=self.publish_release,
            cleanup=self.cleanup,
        )


def local_debug_request() -> BuildRequest:
    return BuildRequest(
        target_version="3.6.20",
        remote=RemoteReleaseInfo.available("3.6.21"),
    )


def test_local_debug_runs_only_version_and_selected_build_stages():
    hooks = RecordingHooks()
    events = RecordingEmitter()

    result = run_release_request(
        local_debug_request(), hooks.as_pipeline_hooks(), events, CancellationToken()
    )

    assert result.succeeded is True
    assert hooks.calls == [
        "validate_dependencies",
        "prepare",
        "apply_version",
        "build_portable",
        "build_installer",
        "smoke_test",
    ]
    assert events.stages == [
        ReleaseStage.PREFLIGHT,
        ReleaseStage.VERSION_SYNC,
        ReleaseStage.BUILDING_PORTABLE,
        ReleaseStage.BUILDING_INSTALLER,
        ReleaseStage.SMOKE_TESTING,
        ReleaseStage.SUCCEEDED,
    ]
    assert "sign_manifest" not in hooks.calls
    assert "upload_assets" not in hooks.calls
    assert [event["kind"] for event in events.events].count("result") == 1


def test_local_debug_never_resolves_or_mutates_signing_material():
    hooks = RecordingHooks()

    result = run_release_request(
        local_debug_request(),
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.succeeded is True
    assert "resolve_signing_material" not in hooks.calls


def test_cancelled_pipeline_never_reports_success():
    token = CancellationToken()
    hooks = RecordingHooks(on_build_portable=token.cancel)
    events = RecordingEmitter()

    result = run_release_request(local_debug_request(), hooks.as_pipeline_hooks(), events, token)

    assert result.cancelled is True
    assert result.succeeded is False
    assert ReleaseStage.SUCCEEDED not in events.stages
    assert [event["kind"] for event in events.events].count("result") == 1


def test_control_cancel_wins_when_published_before_irreversible_marker(tmp_path):
    control = ReleaseCancellationControl.create(tmp_path)
    token = CancellationToken(
        is_cancel_requested=control.is_cancel_requested,
        begin_irreversible=control.begin_irreversible,
    )
    assert control.request_cancel() is True

    with pytest.raises(PipelineCancelled):
        token.begin_irreversible()

    assert control.cancel_path.is_file()


def test_control_irreversible_marker_wins_before_late_parent_cancel(tmp_path):
    control = ReleaseCancellationControl.create(tmp_path)
    token = CancellationToken(
        is_cancel_requested=control.is_cancel_requested,
        begin_irreversible=control.begin_irreversible,
    )

    token.begin_irreversible()
    assert control.irreversible_path.is_file()
    assert control.request_cancel() is False

    token.raise_if_cancelled()
    token.mark_completed()


def test_control_close_failure_is_normalized_to_the_protocol_error(tmp_path, monkeypatch):
    control = ReleaseCancellationControl.create(tmp_path)
    monkeypatch.setattr(
        cancellation_control_module.os,
        "close",
        Mock(side_effect=OSError("close failed")),
    )

    with pytest.raises(CancellationControlError, match="could not be updated"):
        control.request_cancel()


def test_windows_job_assignment_uses_required_rights_and_keeps_close_secondary():
    class Kernel32:
        def __init__(self) -> None:
            self.access_mask = 0

        def OpenProcess(self, access_mask, _inherit, _process_id):
            self.access_mask = int(access_mask)
            return 222

        @staticmethod
        def IsProcessInJob(_process, _job, assigned):
            assigned._obj.value = False
            return True

        @staticmethod
        def AssignProcessToJobObject(_job, _process):
            return False

        @staticmethod
        def CloseHandle(_handle):
            return False

    kernel32 = Kernel32()
    job = WindowsReleaseProcessJob(
        name="Local\\UniversalCrawlerRelease-" + "a" * 32,
        handle=111,
        kernel32=kernel32,
    )

    with pytest.raises(
        CancellationControlError,
        match="could not join its process job",
    ) as caught:
        job.assign_process(4242)

    assert kernel32.access_mask == 0x1101
    notes = getattr(caught.value, "__notes__", ())
    assert notes == [
        "process handle cleanup failed: "
        "release process job handle could not be closed"
    ]


def test_windows_child_job_join_keeps_assignment_primary_when_close_also_fails(
    monkeypatch,
):
    class Kernel32:
        @staticmethod
        def OpenJobObjectW(_access, _inherit, _name):
            return 111

        @staticmethod
        def GetCurrentProcess():
            return 222

        @staticmethod
        def IsProcessInJob(_process, _job, assigned):
            assigned._obj.value = False
            return True

        @staticmethod
        def AssignProcessToJobObject(_job, _process):
            return False

        @staticmethod
        def CloseHandle(_handle):
            return False

    monkeypatch.setattr(
        cancellation_control_module,
        "_windows_kernel32",
        lambda: Kernel32(),
    )

    with pytest.raises(
        CancellationControlError,
        match="could not join its process job",
    ) as caught:
        cancellation_control_module.join_windows_process_job(
            "Local\\UniversalCrawlerRelease-" + "a" * 32
        )

    assert getattr(caught.value, "__notes__", ()) == [
        "process job cleanup failed: "
        "release process job handle could not be closed"
    ]


def test_windows_job_close_retains_handle_until_closehandle_really_succeeds():
    class Kernel32:
        def __init__(self) -> None:
            self.close_results = iter((False, True))
            self.closed_handles: list[int] = []

        def CloseHandle(self, handle):
            self.closed_handles.append(handle)
            return next(self.close_results)

    kernel32 = Kernel32()
    job = WindowsReleaseProcessJob(
        name="Local\\UniversalCrawlerRelease-" + "a" * 32,
        handle=111,
        kernel32=kernel32,
    )

    with pytest.raises(CancellationControlError, match="could not be closed"):
        job.close()

    assert job._handle == 111
    job.close()
    assert job._handle is None
    assert kernel32.closed_handles == [111, 111]


def test_windows_job_force_close_uses_close_source_contract_even_on_api_error():
    class Kernel32:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        @staticmethod
        def GetCurrentProcess():
            return 222

        def DuplicateHandle(self, *args):
            self.calls.append(args)
            return False

    kernel32 = Kernel32()
    job = WindowsReleaseProcessJob(
        name="Local\\UniversalCrawlerRelease-" + "a" * 32,
        handle=111,
        kernel32=kernel32,
    )

    job.force_close()

    assert job._handle is None
    assert len(kernel32.calls) == 1
    source_process, source_handle, target_process, target_handle, _, _, options = (
        kernel32.calls[0]
    )
    assert source_process == 222
    assert source_handle == 111
    assert target_process is None
    assert target_handle is None
    assert options == 0x1


def test_windows_bootstrap_join_failure_is_controlled_and_deletes_request(
    tmp_path,
    monkeypatch,
    capsys,
):
    request_file = tmp_path / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    control_directory = tmp_path / "control"
    control_directory.mkdir()
    target = tmp_path / "target.py"
    target.write_text("raise AssertionError('must not run')\n", encoding="utf-8")
    monkeypatch.setattr(
        cancellation_control_module,
        "join_windows_process_job",
        Mock(side_effect=CancellationControlError("join secret")),
    )

    exit_code = cancellation_control_module.run_windows_release_bootstrap(
        [
            "--release-job-bootstrap",
            "--job-name",
            "Local\\UniversalCrawlerRelease-" + "a" * 32,
            "--script",
            str(target),
            "--request-file",
            str(request_file),
            "--control-directory",
            str(control_directory),
        ]
    )

    assert exit_code == 1
    assert not request_file.exists()
    events = [
        parse_event_line(line)
        for line in capsys.readouterr().out.splitlines()
    ]
    assert all(event is not None for event in events)
    assert [event.kind for event in events if event is not None] == [
        "stage",
        "error",
        "stage",
        "result",
    ]
    assert events[-1] is not None
    assert events[-1].stage is ReleaseStage.FAILED
    assert events[-1].data["status"] == "failed"
    assert "join secret" not in repr(events)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows Job Object")
@pytest.mark.parametrize("shutdown", ["terminate", "force_close"])
def test_windows_bootstrap_contains_grandchild_before_target_script_runs(
    tmp_path,
    shutdown,
):
    job = WindowsReleaseProcessJob.create()
    pid_file = tmp_path / "grandchild.pid"
    target = tmp_path / "spawn_grandchild.py"
    target.write_text(
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"pid_file = Path({str(pid_file)!r})\n"
        "child = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(30)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL"
        ")\n"
        "pid_file.write_text(str(child.pid), encoding='utf-8')\n",
        encoding="utf-8",
    )
    request_file = tmp_path / "request.json"
    request_file.write_text("{}", encoding="utf-8")
    control_directory = tmp_path / "control"
    control_directory.mkdir()

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(Path(cancellation_control_module.__file__).resolve()),
                "--release-job-bootstrap",
                "--job-name",
                job.name,
                "--script",
                str(target),
                "--request-file",
                str(request_file),
                "--control-directory",
                str(control_directory),
            ],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert pid_file.is_file()
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        assert job.has_active_processes() is True
        if shutdown == "terminate":
            job.terminate()
            deadline = time.monotonic() + 5.0
            while job.has_active_processes() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert job.has_active_processes() is False
        else:
            job.force_close()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    os.kill(grandchild_pid, 0)
                except OSError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("KILL_ON_JOB_CLOSE did not terminate the grandchild")
    finally:
        try:
            job.terminate()
        except CancellationControlError:
            pass
        job.close()


def test_version_commit_begins_irreversible_control_before_git_mutation(tmp_path):
    control = ReleaseCancellationControl.create(tmp_path)
    marker_observations: list[bool] = []
    cancellation_observations: list[bool] = []

    class CancellingCommitHooks(RecordingHooks):
        def commit_version_changes(self, request: BuildRequest) -> str:
            self.calls.append("commit_version_changes")
            marker_observations.append(control.irreversible_path.is_file())
            cancellation_observations.append(control.request_cancel())
            return self.version_commit

    hooks = CancellingCommitHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        commit_version_changes=True,
    )
    token = CancellationToken(
        is_cancel_requested=control.is_cancel_requested,
        begin_irreversible=control.begin_irreversible,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert marker_observations == [True]
    assert cancellation_observations == [False]
    assert result.succeeded is True
    assert result.cancelled is False


def test_dry_run_uses_read_only_dependency_preflight_without_preparation():
    hooks = RecordingHooks()

    result = run_release_request(
        replace(local_debug_request(), dry_run=True),
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.succeeded
    assert hooks.calls == ["validate_dependencies", "plan_version"]


def test_dependency_preflight_blocks_preparation_and_all_side_effects():
    hooks = RecordingHooks(dependency_error=ValueError("missing dependency"))

    result = run_release_request(
        local_debug_request(), hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken()
    )

    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert hooks.calls == ["validate_dependencies"]


def test_new_release_tag_rejects_an_empty_verified_version_commit_before_push():
    hooks = RecordingHooks(version_commit="")
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

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.SOURCE_IDENTITY
    assert "verified version commit" in result.error
    assert hooks.calls == [
        "validate_dependencies",
        "prepare",
        "apply_version",
        "commit_version_changes",
    ]


def test_system_exit_from_stage_is_redacted_and_emits_one_terminal_result():
    hooks = RecordingHooks(
        build_installer_error=SystemExit("Authorization: Bearer ghp_stage_secret")
    )
    events = RecordingEmitter()

    result = run_release_request(
        local_debug_request(), hooks.as_pipeline_hooks(), events, CancellationToken()
    )

    assert result.failed_stage is ReleaseStage.BUILDING_INSTALLER
    assert "ghp_stage_secret" not in result.error
    assert [event["kind"] for event in events.events].count("error") == 1
    assert [event["kind"] for event in events.events].count("result") == 1
    terminal_progress = {
        event["progress"]
        for event in events.events
        if event["stage"] is ReleaseStage.FAILED
    }
    assert terminal_progress == {50}


def test_cancellation_observed_during_cleanup_cannot_report_success():
    token = CancellationToken()
    hooks = RecordingHooks(cleanup=token.cancel)
    events = RecordingEmitter()

    result = run_release_request(local_debug_request(), hooks.as_pipeline_hooks(), events, token)

    assert result.cancelled
    assert ReleaseStage.SUCCEEDED not in events.stages
    assert [event["kind"] for event in events.events].count("result") == 1


def test_system_exit_from_cleanup_is_a_redacted_failure():
    def fail_cleanup():
        raise SystemExit("token=cleanup-secret")

    hooks = RecordingHooks(cleanup=fail_cleanup)
    events = RecordingEmitter()

    result = run_release_request(
        local_debug_request(), hooks.as_pipeline_hooks(), events, CancellationToken()
    )

    assert not result.succeeded
    assert "cleanup-secret" not in result.error
    assert [event["kind"] for event in events.events].count("error") == 1
    assert [event["kind"] for event in events.events].count("result") == 1


@pytest.mark.parametrize(
    "cleanup_failure",
    [RuntimeError, SystemExit, KeyboardInterrupt, GeneratorExit],
)
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, GeneratorExit])
def test_interruption_propagates_with_cleanup_diagnostic(
    interruption,
    cleanup_failure,
):
    primary = interruption("operator interruption")

    def cleanup_error() -> None:
        raise cleanup_failure("token=cleanup-secret")

    hooks = RecordingHooks(build_installer_error=primary, cleanup=cleanup_error)

    with pytest.raises(interruption) as caught:
        run_release_request(
            local_debug_request(), hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken()
        )

    assert caught.value is primary
    assert hooks.calls.count("cleanup") == 1
    notes = getattr(primary, "__notes__", ())
    assert len(notes) == 1
    assert notes[0].startswith("cleanup failed:")
    assert "cleanup-secret" not in notes[0]


@pytest.mark.parametrize(
    "cleanup_failure",
    [RuntimeError, SystemExit, KeyboardInterrupt, GeneratorExit],
)
def test_stage_failure_keeps_primary_when_cleanup_raises_baseexception(
    cleanup_failure,
):
    def cleanup_error() -> None:
        raise cleanup_failure("Authorization: Bearer cleanup-secret")

    hooks = RecordingHooks(
        build_installer_error=RuntimeError("installer remains primary"),
        cleanup=cleanup_error,
    )

    result = run_release_request(
        local_debug_request(),
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.stage is ReleaseStage.FAILED
    assert result.error == "installer remains primary"
    assert result.errors[0] == "installer remains primary"
    assert len(result.errors) == 2
    assert result.errors[1].startswith("cleanup failed:")
    assert "cleanup-secret" not in result.errors[1]


def test_interruption_keeps_primary_and_attaches_rollback_diagnostic():
    primary = KeyboardInterrupt("operator interrupted")

    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=lambda: (_ for _ in ()).throw(
                    RuntimeError("rollback unavailable")
                ),
            )

    hooks = FailingRollbackHooks(build_installer_error=primary)
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        run_release_request(
            request,
            hooks.as_pipeline_hooks(),
            RecordingEmitter(),
            CancellationToken(),
        )

    assert caught.value is primary
    assert getattr(primary, "__notes__", ()) == [
        "rollback failed: rollback unavailable"
    ]


def test_unclassified_baseexception_preserves_primary_and_finalizes_resources():
    primary = asyncio.CancelledError("external cancellation remains primary")
    finalized: list[str] = []

    class FinalizingHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_rollback() -> None:
                finalized.append("rollback")
                raise GeneratorExit("Authorization: Bearer rollback-secret")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=fail_rollback,
            )

    def fail_cleanup() -> None:
        finalized.append("cleanup")
        raise KeyboardInterrupt("Authorization: Bearer cleanup-secret")

    hooks = FinalizingHooks(
        build_installer_error=primary,
        cleanup=fail_cleanup,
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        run_release_request(
            request,
            hooks.as_pipeline_hooks(),
            RecordingEmitter(),
            CancellationToken(),
        )

    assert caught.value is primary
    assert finalized == ["rollback", "cleanup"]
    assert getattr(primary, "__notes__", ()) == [
        "rollback failed: Authorization: [REDACTED]",
        "cleanup failed: Authorization: [REDACTED]",
    ]


def test_new_release_defers_remote_release_until_after_signed_smoke():
    hooks = RecordingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    events = RecordingEmitter()

    result = run_release_request(request, hooks.as_pipeline_hooks(), events, CancellationToken())

    assert result.succeeded
    assert hooks.calls == [
        "validate_dependencies",
        "prepare",
        "resolve_signing_material",
        "apply_version",
        "commit_version_changes",
        "push_main",
        "ensure_tag",
        "build_portable",
        "build_installer",
        "sign_manifest",
        "smoke_test",
        "ensure_release",
        "upload_assets",
        "verify_remote_assets",
        "publish_release",
    ]
    assert [stage.value for stage in events.stages] == [
        "preflight",
        "version_sync",
        "source_identity",
        "building_portable",
        "building_installer",
        "signing",
        "smoke_testing",
        "preparing_release",
        "uploading",
        "verifying",
        "publishing",
        "succeeded",
    ]


def test_new_release_upload_failure_never_reaches_verification_or_success():
    class UploadFailingHooks(RecordingHooks):
        def upload_assets(self, request: BuildRequest, assets: tuple[Path, ...]) -> None:
            self.calls.append("upload_assets")
            raise RuntimeError("upload failed")

    hooks = UploadFailingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    events = RecordingEmitter()

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        events,
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.UPLOADING
    assert "verify_remote_assets" not in hooks.calls
    assert ReleaseStage.SUCCEEDED not in events.stages


def test_new_release_verification_failure_never_reports_success():
    class VerifyFailingHooks(RecordingHooks):
        def verify_remote_assets(
            self,
            request: BuildRequest,
            assets: tuple[Path, ...],
        ) -> None:
            self.calls.append("verify_remote_assets")
            raise RuntimeError("verification failed")

    hooks = VerifyFailingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    events = RecordingEmitter()

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        events,
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.VERIFYING
    assert ReleaseStage.SUCCEEDED not in events.stages


def test_new_release_publication_failure_is_reported_as_publishing():
    class PublishFailingHooks(RecordingHooks):
        def publish_release(self, request: BuildRequest) -> None:
            self.calls.append("publish_release")
            raise RuntimeError("publication failed")

    hooks = PublishFailingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    events = RecordingEmitter()

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        events,
        CancellationToken(),
    )

    assert result.failed_stage is not None
    assert result.failed_stage.value == "publishing"
    assert events.stages[-1] is ReleaseStage.FAILED


def test_new_release_cleanup_failure_happens_before_irreversible_publication():
    def fail_cleanup() -> None:
        raise RuntimeError("cleanup failed")

    hooks = RecordingHooks(cleanup=fail_cleanup)
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.PUBLISHING
    assert "cleanup" in hooks.calls
    assert "publish_release" not in hooks.calls


def test_new_release_signing_commit_failure_happens_before_publication():
    transaction_calls: list[str] = []

    class CommitFailingHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_commit() -> None:
                transaction_calls.append("commit")
                raise RuntimeError("signing transaction commit failed")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                commit_transaction=fail_commit,
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    hooks = CommitFailingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.PUBLISHING
    assert transaction_calls == ["commit", "rollback"]
    assert "publish_release" not in hooks.calls


def test_cancellation_during_cleanup_is_ignored_after_remote_identity_linearizes():
    token = CancellationToken()
    hooks = RecordingHooks(cleanup=token.cancel)
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert result.succeeded
    assert "cleanup" in hooks.calls
    assert "publish_release" in hooks.calls


def test_cancellation_during_signing_commit_is_ignored_after_linearization():
    commit_started = Event()
    allow_commit = Event()
    token = CancellationToken()
    transaction_calls: list[str] = []

    class BlockingCommitHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def commit() -> None:
                transaction_calls.append("commit")
                commit_started.set()
                if not allow_commit.wait(timeout=5):
                    raise RuntimeError("timed out waiting to finish signing commit")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                commit_transaction=commit,
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    hooks = BlockingCommitHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    results = []
    worker = Thread(
        target=lambda: results.append(
            run_release_request(
                request,
                hooks.as_pipeline_hooks(),
                RecordingEmitter(),
                token,
            )
        ),
        daemon=True,
    )

    worker.start()
    assert commit_started.wait(timeout=5)
    token.cancel()
    allow_commit.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].succeeded
    assert transaction_calls == ["commit"]
    assert "publish_release" in hooks.calls


def test_trust_anchor_commit_and_remote_identity_are_after_linearization():
    token = CancellationToken()
    transaction_calls: list[str] = []

    class CancellingTransactionHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def commit() -> None:
                transaction_calls.append("commit")
                token.cancel()

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=True,
                commit_transaction=commit,
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    hooks = CancellingTransactionHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert result.succeeded
    assert transaction_calls == ["commit"]
    assert hooks.calls.index("commit_version_changes") < hooks.calls.index("push_main")
    assert hooks.calls.index("push_main") < hooks.calls.index("ensure_tag")


def test_no_release_signing_commit_is_after_linearization():
    token = CancellationToken()
    transaction_calls: list[str] = []

    class CancellingTransactionHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def commit() -> None:
                transaction_calls.append("commit")
                token.cancel()

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                commit_transaction=commit,
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    hooks = CancellingTransactionHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert result.succeeded
    assert transaction_calls == ["commit"]


def test_cancellation_after_publication_linearizes_as_success():
    token = CancellationToken()

    class CancellingPublishHooks(RecordingHooks):
        def publish_release(self, request: BuildRequest) -> None:
            self.calls.append("publish_release")
            token.cancel()

    hooks = CancellingPublishHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )
    events = RecordingEmitter()

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        events,
        token,
    )

    assert result.succeeded
    assert events.stages[-2:] == [ReleaseStage.PUBLISHING, ReleaseStage.SUCCEEDED]


def test_rollback_failure_is_secondary_to_the_primary_stage_failure():
    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_rollback() -> None:
                raise RuntimeError("rollback unavailable")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=fail_rollback,
            )

    hooks = FailingRollbackHooks(
        build_installer_error=RuntimeError("installer is primary")
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.stage is ReleaseStage.FAILED
    assert result.error == "installer is primary"
    assert result.errors[0] == "installer is primary"
    assert any("rollback failed: rollback unavailable" in item for item in result.errors[1:])


def test_rollback_failure_does_not_reclassify_cancellation():
    token = CancellationToken()

    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=lambda: (_ for _ in ()).throw(
                    RuntimeError("rollback unavailable")
                ),
            )

    hooks = FailingRollbackHooks(on_build_portable=token.cancel)
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=True,
        build_installer=False,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert result.stage is ReleaseStage.CANCELLED
    assert any("rollback failed: rollback unavailable" in item for item in result.errors)


def test_hostile_diagnostic_hooks_cannot_replace_or_hide_the_primary_failure():
    class PrimaryFailure(RuntimeError):
        def add_note(self, _note: str) -> None:
            raise RuntimeError("note storage unavailable")

    class HostileRollbackFailure(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("secondary string unavailable")

    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=lambda: (_ for _ in ()).throw(
                    HostileRollbackFailure()
                ),
            )

    hooks = FailingRollbackHooks(
        build_installer_error=PrimaryFailure("installer remains primary")
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.error == "installer remains primary"
    assert result.errors == (
        "installer remains primary",
        "rollback failed: release pipeline failed",
    )


@pytest.mark.parametrize("rollback_failure", (KeyboardInterrupt, GeneratorExit))
def test_stage_failure_keeps_classification_when_rollback_raises_baseexception(
    rollback_failure,
):
    cleanup_calls: list[str] = []

    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_rollback() -> None:
                raise rollback_failure("Authorization: Bearer rollback-secret")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=fail_rollback,
            )

    hooks = FailingRollbackHooks(
        build_installer_error=RuntimeError("installer remains primary"),
        cleanup=lambda: cleanup_calls.append("cleanup"),
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.stage is ReleaseStage.FAILED
    assert result.failed_stage is ReleaseStage.BUILDING_INSTALLER
    assert result.error == "installer remains primary"
    assert cleanup_calls == ["cleanup"]
    assert any(item.startswith("rollback failed:") for item in result.errors[1:])
    assert "rollback-secret" not in repr(result)


@pytest.mark.parametrize("rollback_failure", (KeyboardInterrupt, GeneratorExit))
def test_cancellation_keeps_classification_when_rollback_raises_baseexception(
    rollback_failure,
):
    token = CancellationToken()
    cleanup_calls: list[str] = []

    class FailingRollbackHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_rollback() -> None:
                raise rollback_failure("Authorization: Bearer rollback-secret")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=fail_rollback,
            )

    hooks = FailingRollbackHooks(
        on_build_portable=token.cancel,
        cleanup=lambda: cleanup_calls.append("cleanup"),
    )
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=True,
        build_installer=False,
        run_smoke_tests=False,
        generate_manifest_key=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        token,
    )

    assert result.stage is ReleaseStage.CANCELLED
    assert result.failed_stage is ReleaseStage.BUILDING_PORTABLE
    assert cleanup_calls == ["cleanup"]
    assert any(item.startswith("rollback failed:") for item in result.errors)
    assert "rollback-secret" not in repr(result)


@pytest.mark.parametrize("rollback_failure", (KeyboardInterrupt, GeneratorExit))
def test_signing_validation_keeps_primary_when_rollback_raises_baseexception(
    rollback_failure,
):
    cleanup_calls: list[str] = []

    class InvalidSigningHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")

            def fail_rollback() -> None:
                raise rollback_failure("Authorization: Bearer rollback-secret")

            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                rollback_transaction=fail_rollback,
            )

    hooks = InvalidSigningHooks(cleanup=lambda: cleanup_calls.append("cleanup"))
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        build_portable=False,
        build_installer=True,
        run_smoke_tests=False,
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.stage is ReleaseStage.FAILED
    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert result.error == (
        "trust anchor rotation did not update the production trust anchor"
    )
    assert cleanup_calls == ["cleanup"]
    assert any(item.startswith("rollback failed:") for item in result.errors[1:])
    assert "rollback-secret" not in repr(result)


def test_rotated_signing_material_is_resolved_before_commit_and_build():
    hooks = RecordingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.succeeded
    assert hooks.calls.index("resolve_signing_material") < hooks.calls.index(
        "commit_version_changes"
    )
    assert hooks.calls.index("resolve_signing_material") < hooks.calls.index(
        "build_portable"
    )
    assert hooks.calls.index("resolve_signing_material") < hooks.calls.index(
        "build_installer"
    )
    assert hooks.calls.index("commit_version_changes") < hooks.calls.index(
        "build_portable"
    )
    assert hooks.calls.index("push_main") < hooks.calls.index("build_portable")
    assert hooks.calls.index("ensure_tag") < hooks.calls.index("build_portable")


def test_rotated_signing_material_rolls_back_when_version_application_fails():
    transaction_calls: list[str] = []

    class FailingVersionHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=request.rotate_trust_anchor,
                commit_transaction=lambda: transaction_calls.append("commit"),
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

        def apply_version(self, target: str) -> VersionUpdateResult:
            self.calls.append("apply_version")
            raise RuntimeError(f"cannot apply {target}")

    hooks = FailingVersionHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.VERSION_SYNC
    assert transaction_calls == ["rollback"]


def test_rotated_signing_material_commits_before_later_build_failure():
    transaction_calls: list[str] = []

    class TransactionHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=request.rotate_trust_anchor,
                commit_transaction=lambda: transaction_calls.append("commit"),
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    def fail_build() -> None:
        raise RuntimeError("portable build failed")

    hooks = TransactionHooks(on_build_portable=fail_build)
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.BUILDING_PORTABLE
    assert transaction_calls == ["commit"]


def test_rotated_signing_material_rolls_back_when_version_commit_fails():
    transaction_calls: list[str] = []

    class FailingCommitHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=request.rotate_trust_anchor,
                commit_transaction=lambda: transaction_calls.append("commit"),
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

        def commit_version_changes(self, request: BuildRequest) -> str:
            self.calls.append("commit_version_changes")
            raise RuntimeError(
                f"cannot commit release {request.target_version}"
            )

    hooks = FailingCommitHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.SOURCE_IDENTITY
    assert transaction_calls == ["rollback"]


def test_rotated_signing_material_rolls_back_when_version_commit_is_empty():
    transaction_calls: list[str] = []

    class EmptyCommitHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=request.rotate_trust_anchor,
                commit_transaction=lambda: transaction_calls.append("commit"),
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

        def commit_version_changes(self, request: BuildRequest) -> str:
            self.calls.append("commit_version_changes")
            return ""

    hooks = EmptyCommitHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.SOURCE_IDENTITY
    assert transaction_calls == ["rollback"]


def test_invalid_signing_material_contract_rolls_back_resolver_side_effects():
    transaction_calls: list[str] = []

    class InvalidMaterialHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets/private-key.pem"),
                public_key_path=Path("release-secrets/public-key.pem"),
                fingerprint="A" * 64,
                trust_anchor_changed=False,
                commit_transaction=lambda: transaction_calls.append("commit"),
                rollback_transaction=lambda: transaction_calls.append("rollback"),
            )

    hooks = InvalidMaterialHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        generate_manifest_key=True,
        rotate_trust_anchor=True,
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        build_portable=True,
        build_installer=True,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert transaction_calls == ["rollback"]


def test_signing_material_paths_are_never_emitted():
    secret_name = "private-ghp_super-secret.pem"

    class SecretNamedHooks(RecordingHooks):
        def resolve_signing_material(self, request: BuildRequest) -> SigningMaterial:
            self.calls.append("resolve_signing_material")
            return SigningMaterial(
                private_key_path=Path("release-secrets") / secret_name,
                public_key_path=Path("release-secrets/public.pem"),
                fingerprint="B" * 64,
                trust_anchor_changed=False,
            )

    hooks = SecretNamedHooks()
    events = RecordingEmitter()
    request = BuildRequest(
        target_version="3.6.21",
        remote=RemoteReleaseInfo.available("3.6.21"),
        apply_version=False,
        same_release_repair=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        sign_manifest=True,
        build_portable=False,
        build_installer=False,
        run_smoke_tests=False,
    )

    result = run_release_request(
        request,
        hooks.as_pipeline_hooks(),
        events,
        CancellationToken(),
    )

    assert result.succeeded
    assert secret_name not in repr(events.events)


def test_new_release_smoke_failure_does_not_create_a_remote_release():
    hooks = RecordingHooks(smoke_error=RuntimeError("smoke failed"))
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        release_notes_path="notes.md",
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    result = run_release_request(request, hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken())

    assert result.failed_stage is ReleaseStage.SMOKE_TESTING
    assert "ensure_release" not in hooks.calls


def test_dry_run_plans_version_and_skips_every_side_effect():
    hooks = RecordingHooks()
    events = RecordingEmitter()
    request = replace(local_debug_request(), dry_run=True)

    result = run_release_request(request, hooks.as_pipeline_hooks(), events, CancellationToken())

    assert result.succeeded is True
    assert hooks.calls == ["validate_dependencies", "plan_version"]
    assert ReleaseStage.VERSION_SYNC in events.stages
    assert [stage.value for stage in events.skipped_stages] == [
        "source_identity",
        "building_portable",
        "building_installer",
        "signing",
        "smoke_testing",
        "preparing_release",
        "uploading",
        "verifying",
        "publishing",
    ]
    progress = [event["progress"] for event in events.events]
    assert progress == sorted(progress)


def test_dry_run_rejects_an_invalid_planned_upload_before_plan_hook():
    hooks = RecordingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=True,
        upload_release_assets=True,
    )

    result = run_release_request(
        request, hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken()
    )

    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert "requires signing the manifest" in result.error
    assert hooks.calls == []


def test_valid_full_dry_run_still_calls_only_plan_hook():
    hooks = RecordingHooks()
    request = BuildRequest(
        target_version="3.6.22",
        remote=RemoteReleaseInfo.available("3.6.21"),
        dry_run=True,
        sign_manifest=True,
        private_key_path="env:RELEASE_PRIVATE_KEY_PATH",
        release_notes_path="notes.md",
        commit_version_changes=True,
        push_main=True,
        create_or_reuse_tag=True,
        create_or_update_release=True,
        upload_release_assets=True,
        verify_remote_assets=True,
    )

    result = run_release_request(
        request, hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken()
    )

    assert result.succeeded
    assert hooks.calls == ["validate_dependencies", "plan_version"]


def test_build_failure_does_not_rollback_an_applied_version():
    hooks = RecordingHooks(build_installer_error=RuntimeError("inno failed"))

    result = run_release_request(
        replace(local_debug_request(), target_version="3.6.22", remote=RemoteReleaseInfo.available("3.6.21")),
        hooks.as_pipeline_hooks(),
        RecordingEmitter(),
        CancellationToken(),
    )

    assert hooks.version_after_failure == "3.6.22"
    assert result.failed_stage is ReleaseStage.BUILDING_INSTALLER


def test_preflight_failure_runs_before_side_effects_and_redacts_errors():
    hooks = RecordingHooks()
    events = RecordingEmitter()
    request = replace(local_debug_request(), remote=RemoteReleaseInfo.unavailable("token=top-secret"))

    result = run_release_request(request, hooks.as_pipeline_hooks(), events, CancellationToken())

    assert hooks.calls == []
    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert result.error == result.errors[0]
    assert "top-secret" not in result.errors[0]
    assert [event["kind"] for event in events.events].count("error") == 1
    assert [event["kind"] for event in events.events].count("result") == 1


@pytest.mark.parametrize("option", ["generate_manifest_key", "sign_manifest"])
def test_local_debug_rejects_manifest_side_effects_before_build(option):
    hooks = RecordingHooks()
    request = replace(local_debug_request(), **{option: True})

    result = run_release_request(request, hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken())

    assert result.failed_stage is ReleaseStage.PREFLIGHT
    assert hooks.calls == []


def test_request_file_rejects_unknown_invalid_and_inline_secret_fields(tmp_path):
    request_path = tmp_path / "request.json"
    request_path.write_text(
        '{"target_version":"3.6.22","remote":{"version":"3.6.21"},"token":"secret"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown") as unknown_error:
        load_request_file(request_path)
    assert "token" not in str(unknown_error.value).casefold()
    assert "secret" not in str(unknown_error.value).casefold()

    request_path.write_text(
        '{"target_version":"3.6.22","remote":{"version":"3.6.21"},"build_portable":"yes"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="boolean"):
        load_request_file(request_path)

    request_path.write_text(
        '{"target_version":"3.6.22","remote":{"version":"3.6.21"},"private_key_path":"-----BEGIN PRIVATE KEY-----\\nsecret"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="path or reference"):
        load_request_file(request_path)

    request_path.write_text(
        '{"target_version":"3.6.22","remote":{"version":"3.6.21"},"custom_proxy":"http://user:password@127.0.0.1:7890"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reference"):
        load_request_file(request_path)


def test_request_file_preserves_remote_revision_inventory(tmp_path):
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "target_version": "3.6.21",
                "release_revision": 3,
                "same_release_repair": True,
                "remote": {
                    "version": "3.6.21",
                    "release_revision": 2,
                    "release_tags": ["v3.6.21-r2", "v3.6.21-r1", "v3.6.21"],
                    "occupied_tags": [
                        "v3.6.21-r3",
                        "v3.6.21-r2",
                        "v3.6.21-r1",
                        "v3.6.21",
                    ],
                    "resumable_tags": ["v3.6.21-r3"],
                    "error": "",
                },
            }
        ),
        encoding="utf-8",
    )

    request = load_request_file(request_path)

    assert request.release_revision == 3
    assert request.remote.identity.tag == "v3.6.21-r2"
    assert request.remote.next_revision_for("3.6.21") == 4
    assert request.remote.target_revision_for("3.6.21") == 3


def test_same_version_request_file_requires_explicit_release_revision(tmp_path):
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "target_version": "3.6.21",
                "same_release_repair": True,
                "remote": {
                    "version": "3.6.21",
                    "release_revision": 2,
                    "release_tags": ["v3.6.21-r2", "v3.6.21-r1", "v3.6.21"],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit release_revision"):
        load_request_file(request_path)


@pytest.mark.parametrize(
    "proxy",
    [
        "http://127.0.0.1:7890/path",
        "http://127.0.0.1:7890?token=query-secret",
        "http://127.0.0.1:7890#fragment-secret",
        "ftp://127.0.0.1:7890",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
    ],
)
def test_request_file_rejects_non_endpoint_proxy_values_without_echoing_them(tmp_path, proxy):
    request_path = tmp_path / "request.json"
    request_path.write_text(
        (
            '{"target_version":"3.6.22","remote":{"version":"3.6.21"},'
            f'"custom_proxy":"{proxy}"}}'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="custom proxy endpoint") as caught:
        load_request_file(request_path)

    assert proxy not in str(caught.value)
    assert "query-secret" not in str(caught.value)
    assert "fragment-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "proxy",
    [
        "127.0.0.1:7890",
        "http://127.0.0.1:7890",
        "socks5://localhost:1080",
        "env:RELEASE_PROXY_URL",
    ],
)
def test_request_file_accepts_proxy_endpoints_and_environment_references(tmp_path, proxy):
    request_path = tmp_path / "request.json"
    request_path.write_text(
        (
            '{"target_version":"3.6.22","remote":{"version":"3.6.21"},'
            f'"custom_proxy":"{proxy}"}}'
        ),
        encoding="utf-8",
    )

    assert load_request_file(request_path).custom_proxy == proxy


def test_request_file_rejects_endpoint_or_credentials_in_proxy_label_without_echo(tmp_path):
    request_path = tmp_path / "request.json"
    secret_label = "http://alice:label-secret@127.0.0.1:7890"
    request_path.write_text(
        (
            '{"target_version":"3.6.22","remote":{"version":"3.6.21"},'
            f'"proxy_label":"{secret_label}"}}'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="proxy selection") as caught:
        load_request_file(request_path)

    assert secret_label not in str(caught.value)
    assert "label-secret" not in str(caught.value)
