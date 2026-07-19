"""Deterministic orchestration for release-builder requests."""

from __future__ import annotations

import json
import re
import threading
from urllib.parse import urlparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Protocol, TypeVar

from .events import redact_release_text
from .models import BuildRequest, ReleaseMode, ReleaseResult, ReleaseStage, RemoteReleaseInfo
from .modes import resolve_release_mode, validate_build_request
from .versioning import VersionUpdatePlan, VersionUpdateResult, normalize_version


class ReleaseEventSink(Protocol):
    def emit(
        self,
        kind: str,
        *,
        stage: ReleaseStage,
        progress: int,
        message: str = "",
        data: Mapping[str, object] | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class ReleasePipelineHooks:
    plan_version: Callable[[str], VersionUpdatePlan]
    apply_version: Callable[[str], VersionUpdateResult]
    generate_key: Callable[[bool, bool], object]
    build_portable: Callable[[], None]
    build_installer: Callable[[], None]
    run_smoke_tests: Callable[[], None]
    sign_manifest: Callable[[BuildRequest], tuple[Path, ...]]
    commit_version_changes: Callable[[BuildRequest], str]
    push_main: Callable[[BuildRequest], None]
    ensure_tag: Callable[[BuildRequest, str], None]
    ensure_release: Callable[[BuildRequest], None]
    upload_assets: Callable[[BuildRequest, tuple[Path, ...]], None]
    verify_remote_assets: Callable[[BuildRequest, tuple[Path, ...]], None]
    cleanup: Callable[[], None] = lambda: None


class PipelineCancelled(RuntimeError):
    """Internal cancellation marker that is never emitted as an error."""


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise PipelineCancelled("release request cancelled")


_T = TypeVar("_T")
_PROGRESS = {
    ReleaseStage.PREFLIGHT: 0,
    ReleaseStage.VERSION_SYNC: 10,
    ReleaseStage.BUILDING_PORTABLE: 30,
    ReleaseStage.BUILDING_INSTALLER: 50,
    ReleaseStage.SIGNING: 65,
    ReleaseStage.GIT: 75,
    ReleaseStage.UPLOADING: 85,
    ReleaseStage.VERIFYING: 95,
    ReleaseStage.SUCCEEDED: 100,
    ReleaseStage.FAILED: 100,
    ReleaseStage.CANCELLED: 100,
}
_SIDE_EFFECT_FIELDS = (
    "apply_version",
    "build_portable",
    "build_installer",
    "run_smoke_tests",
    "generate_manifest_key",
    "rotate_trust_anchor",
    "sign_manifest",
    "commit_version_changes",
    "push_main",
    "create_or_reuse_tag",
    "create_or_update_release",
    "upload_release_assets",
    "upload_public_key",
    "verify_remote_assets",
)
_BOOLEAN_FIELDS = frozenset(_SIDE_EFFECT_FIELDS + ("dry_run", "same_release_repair", "offline_debug"))
_STRING_FIELDS = frozenset(
    {
        "target_version",
        "repository",
        "release_notes_path",
        "output_root",
        "private_key_path",
        "proxy_label",
        "custom_proxy",
    }
)
_REFERENCE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def run_release_request(
    request: BuildRequest,
    hooks: ReleasePipelineHooks,
    emitter: ReleaseEventSink,
    cancel_token: CancellationToken,
) -> ReleaseResult:
    """Run requested stages once, emitting monotonic, redacted lifecycle events."""

    mode = _fallback_mode(request)
    current_stage = ReleaseStage.PREFLIGHT
    artifacts: tuple[Path, ...] = ()

    def emit(kind: str, stage: ReleaseStage, *, message: str = "", data: Mapping[str, object] | None = None) -> None:
        emitter.emit(kind, stage=stage, progress=_PROGRESS[stage], message=message, data=data)

    def run_stage(stage: ReleaseStage, action: Callable[[], _T]) -> _T:
        nonlocal current_stage
        cancel_token.raise_if_cancelled()
        current_stage = stage
        emit("stage", stage)
        value = action()
        cancel_token.raise_if_cancelled()
        return value

    def skip_stage(stage: ReleaseStage) -> None:
        nonlocal current_stage
        cancel_token.raise_if_cancelled()
        current_stage = stage
        emit("stage", stage, data={"status": "skipped"})
        cancel_token.raise_if_cancelled()

    try:
        mode = run_stage(ReleaseStage.PREFLIGHT, lambda: _preflight(request))
        if request.dry_run:
            run_stage(ReleaseStage.VERSION_SYNC, lambda: hooks.plan_version(request.target_version))
            for stage in (
                ReleaseStage.BUILDING_PORTABLE,
                ReleaseStage.BUILDING_INSTALLER,
                ReleaseStage.SIGNING,
                ReleaseStage.GIT,
                ReleaseStage.UPLOADING,
                ReleaseStage.VERIFYING,
            ):
                skip_stage(stage)
        else:
            if request.apply_version:
                run_stage(ReleaseStage.VERSION_SYNC, lambda: hooks.apply_version(request.target_version))
            if request.build_portable:
                run_stage(ReleaseStage.BUILDING_PORTABLE, hooks.build_portable)
            if request.build_installer:
                run_stage(ReleaseStage.BUILDING_INSTALLER, hooks.build_installer)
            if request.generate_manifest_key or request.sign_manifest:
                def sign() -> tuple[Path, ...]:
                    if request.generate_manifest_key:
                        hooks.generate_key(True, request.rotate_trust_anchor)
                    return hooks.sign_manifest(request) if request.sign_manifest else ()

                artifacts = run_stage(ReleaseStage.SIGNING, sign)
            if _needs_git_stage(request):
                commit = ""

                def publish_git() -> None:
                    nonlocal commit
                    if request.commit_version_changes:
                        commit = hooks.commit_version_changes(request)
                    if request.push_main:
                        hooks.push_main(request)
                    if request.create_or_reuse_tag:
                        hooks.ensure_tag(request, commit)
                    if request.create_or_update_release:
                        hooks.ensure_release(request)

                run_stage(ReleaseStage.GIT, publish_git)
            if request.upload_release_assets or request.upload_public_key:
                run_stage(ReleaseStage.UPLOADING, lambda: hooks.upload_assets(request, artifacts))
            if request.run_smoke_tests or request.verify_remote_assets:
                def verify() -> None:
                    if request.run_smoke_tests:
                        hooks.run_smoke_tests()
                    if request.verify_remote_assets:
                        hooks.verify_remote_assets(request, artifacts)

                run_stage(ReleaseStage.VERIFYING, verify)
    except PipelineCancelled:
        _cleanup(hooks)
        emit("stage", ReleaseStage.CANCELLED)
        emit("result", ReleaseStage.CANCELLED, data={"status": "cancelled"})
        return ReleaseResult(mode=mode, stage=ReleaseStage.CANCELLED, failed_stage=current_stage)
    except Exception as error:
        _cleanup(hooks)
        message = redact_release_text(str(error)) or "release pipeline failed"
        emit("error", current_stage, message=message)
        emit("stage", ReleaseStage.FAILED)
        emit("result", ReleaseStage.FAILED, data={"status": "failed", "error": message})
        return ReleaseResult(
            mode=mode,
            stage=ReleaseStage.FAILED,
            errors=(message,),
            artifacts=tuple(str(path) for path in artifacts),
            failed_stage=current_stage,
            error=message,
        )

    try:
        hooks.cleanup()
    except Exception as error:
        message = redact_release_text(str(error)) or "release pipeline cleanup failed"
        emit("error", current_stage, message=message)
        emit("stage", ReleaseStage.FAILED)
        emit("result", ReleaseStage.FAILED, data={"status": "failed", "error": message})
        return ReleaseResult(
            mode=mode,
            stage=ReleaseStage.FAILED,
            artifacts=tuple(str(path) for path in artifacts),
            errors=(message,),
            failed_stage=current_stage,
            error=message,
        )
    emit("stage", ReleaseStage.SUCCEEDED)
    emit("result", ReleaseStage.SUCCEEDED, data={"status": "succeeded"})
    return ReleaseResult(
        mode=mode,
        stage=ReleaseStage.SUCCEEDED,
        artifacts=tuple(str(path) for path in artifacts),
    )


def load_request_file(path: Path) -> BuildRequest:
    """Load one strict JSON request without accepting secret material."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release request file is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("release request must be a JSON object")

    allowed = {field.name for field in fields(BuildRequest)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"release request contains unknown fields: {', '.join(unknown)}")
    values: dict[str, object] = {}
    for key, value in payload.items():
        if key in _BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"release request field {key} must be a boolean")
        elif key in _STRING_FIELDS:
            if not isinstance(value, str):
                raise ValueError(f"release request field {key} must be a string")
        elif key == "remote":
            value = _load_remote(value)
        else:  # Defensive guard for future BuildRequest fields.
            raise ValueError(f"release request field {key} is not supported")
        values[key] = value

    if "target_version" not in values:
        raise ValueError("release request requires target_version")
    values["target_version"] = normalize_version(str(values["target_version"]))
    _validate_secret_reference(str(values.get("private_key_path", "")))
    _validate_proxy_reference(str(values.get("custom_proxy", "")))
    return BuildRequest(**values)


def _load_remote(value: object) -> RemoteReleaseInfo:
    if not isinstance(value, dict):
        raise ValueError("release request field remote must be an object")
    unknown = sorted(set(value) - {"version", "error"})
    if unknown:
        raise ValueError(f"release request remote contains unknown fields: {', '.join(unknown)}")
    version = value.get("version", "")
    error = value.get("error", "")
    if not isinstance(version, str) or not isinstance(error, str):
        raise ValueError("release request remote version and error must be strings")
    if version and error:
        raise ValueError("release request remote cannot include both version and error")
    if version:
        return RemoteReleaseInfo.available(version)
    if error:
        return RemoteReleaseInfo.unavailable(error)
    return RemoteReleaseInfo.unknown()


def _validate_secret_reference(value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if "-----BEGIN" in text or "\n" in text or "\r" in text:
        raise ValueError("private_key_path must be a path or reference, never key material")
    if text.startswith("env:") and not _REFERENCE_RE.fullmatch(text[4:]):
        raise ValueError("private_key_path reference is invalid")


def _validate_proxy_reference(value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if text.startswith("env:"):
        if not _REFERENCE_RE.fullmatch(text[4:]):
            raise ValueError("custom_proxy reference is invalid")
        return
    parsed = urlparse(text if "://" in text else f"//{text}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("custom_proxy credentials must use an environment reference")


def _preflight(request: BuildRequest) -> ReleaseMode:
    validation_request = request
    if request.dry_run:
        validation_request = replace(
            request,
            dry_run=False,
            **{field: False for field in _SIDE_EFFECT_FIELDS},
        )
    errors = validate_build_request(validation_request)
    if errors:
        raise ValueError("; ".join(errors))
    return resolve_release_mode(
        request.target_version,
        request.remote,
        same_release_repair=request.same_release_repair,
        offline_debug=request.offline_debug,
    )


def _fallback_mode(request: BuildRequest) -> ReleaseMode:
    try:
        return resolve_release_mode(
            request.target_version,
            request.remote,
            same_release_repair=request.same_release_repair,
            offline_debug=request.offline_debug,
        )
    except ValueError:
        return ReleaseMode.OFFLINE_DEBUG if request.offline_debug else ReleaseMode.LOCAL_DEBUG


def _needs_git_stage(request: BuildRequest) -> bool:
    return any(
        getattr(request, field)
        for field in (
            "commit_version_changes",
            "push_main",
            "create_or_reuse_tag",
            "create_or_update_release",
        )
    )


def _cleanup(hooks: ReleasePipelineHooks) -> None:
    try:
        hooks.cleanup()
    except Exception:
        pass


__all__ = [
    "CancellationToken",
    "ReleasePipelineHooks",
    "load_request_file",
    "run_release_request",
]
