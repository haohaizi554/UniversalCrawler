from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.models import BuildRequest, ReleaseStage, RemoteReleaseInfo
from release_tool.runner import (
    CancellationToken,
    ReleasePipelineHooks,
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

    def generate_key(self, generate: bool, rotate: bool) -> None:
        self.calls.append("generate_key")

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
            generate_key=self.generate_key,
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


def test_cancelled_pipeline_never_reports_success():
    token = CancellationToken()
    hooks = RecordingHooks(on_build_portable=token.cancel)
    events = RecordingEmitter()

    result = run_release_request(local_debug_request(), hooks.as_pipeline_hooks(), events, token)

    assert result.cancelled is True
    assert result.succeeded is False
    assert ReleaseStage.SUCCEEDED not in events.stages
    assert [event["kind"] for event in events.events].count("result") == 1


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


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, GeneratorExit])
def test_interruption_propagates_after_cleanup_without_cleanup_override(interruption):
    def cleanup_error() -> None:
        raise RuntimeError("cleanup must not replace interruption")

    hooks = RecordingHooks(build_installer_error=interruption(), cleanup=cleanup_error)

    with pytest.raises(interruption):
        run_release_request(
            local_debug_request(), hooks.as_pipeline_hooks(), RecordingEmitter(), CancellationToken()
        )

    assert hooks.calls.count("cleanup") == 1


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
    ]
    assert events.stages == [
        ReleaseStage.PREFLIGHT,
        ReleaseStage.VERSION_SYNC,
        ReleaseStage.SOURCE_IDENTITY,
        ReleaseStage.BUILDING_PORTABLE,
        ReleaseStage.BUILDING_INSTALLER,
        ReleaseStage.SIGNING,
        ReleaseStage.SMOKE_TESTING,
        ReleaseStage.PUBLISHING,
        ReleaseStage.UPLOADING,
        ReleaseStage.VERIFYING,
        ReleaseStage.SUCCEEDED,
    ]


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
    assert events.skipped_stages == [
        ReleaseStage.SOURCE_IDENTITY,
        ReleaseStage.BUILDING_PORTABLE,
        ReleaseStage.BUILDING_INSTALLER,
        ReleaseStage.SIGNING,
        ReleaseStage.SMOKE_TESTING,
        ReleaseStage.PUBLISHING,
        ReleaseStage.UPLOADING,
        ReleaseStage.VERIFYING,
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
