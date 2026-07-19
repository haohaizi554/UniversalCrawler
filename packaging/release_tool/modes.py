"""Pure release-mode resolution and request validation."""

from __future__ import annotations

from .models import BuildRequest, ReleaseMode, RemoteReleaseInfo
from .versioning import normalize_version


_REMOTE_WRITE_OPTIONS = (
    ("push main", "push_main"),
    ("create or reuse tags", "create_or_reuse_tag"),
    ("create or update releases", "create_or_update_release"),
    ("upload release assets", "upload_release_assets"),
    ("upload public keys", "upload_public_key"),
)

_DRY_RUN_OPTIONS = (
    ("apply version changes", "apply_version"),
    ("build portable artifacts", "build_portable"),
    ("build installer artifacts", "build_installer"),
    ("run smoke tests", "run_smoke_tests"),
    ("generate manifest keys", "generate_manifest_key"),
    ("rotate trust anchors", "rotate_trust_anchor"),
    ("sign manifests", "sign_manifest"),
    ("commit version changes", "commit_version_changes"),
    ("push main", "push_main"),
    ("create or reuse tags", "create_or_reuse_tag"),
    ("create or update releases", "create_or_update_release"),
    ("upload release assets", "upload_release_assets"),
    ("upload public keys", "upload_public_key"),
)


def resolve_release_mode(
    target_version: str,
    remote: RemoteReleaseInfo,
    *,
    same_release_repair: bool,
    offline_debug: bool,
) -> ReleaseMode:
    """Resolve the release policy without performing network or file-system work."""
    target = normalize_version(target_version)

    if offline_debug:
        return ReleaseMode.OFFLINE_DEBUG
    if not remote.is_available:
        raise ValueError("remote release state is unknown")

    remote_version = normalize_version(remote.version)
    comparison = _compare_versions(target, remote_version)
    if comparison < 0:
        return ReleaseMode.LOCAL_DEBUG
    if comparison == 0:
        if same_release_repair:
            return ReleaseMode.SAME_RELEASE_REPAIR
        return ReleaseMode.LOCAL_REBUILD
    return ReleaseMode.NEW_RELEASE


def validate_build_request(request: BuildRequest) -> tuple[str, ...]:
    """Return all request violations in a deterministic, user-facing order."""
    errors: list[str] = []
    mode: ReleaseMode | None = None

    try:
        mode = resolve_release_mode(
            request.target_version,
            request.remote,
            same_release_repair=request.same_release_repair,
            offline_debug=request.offline_debug,
        )
    except ValueError as error:
        if str(error) == "remote release state is unknown":
            if _has_remote_writes(request):
                errors.append("remote release state is unknown")
        else:
            errors.append(str(error))

    if request.upload_release_assets:
        if not request.sign_manifest:
            errors.append("upload release assets requires signing the manifest")
        if not request.private_key_path.strip():
            errors.append("upload release assets requires a private key")
        if not request.create_or_update_release:
            errors.append("upload release assets requires creating or updating the release")
        if not request.verify_remote_assets:
            errors.append("upload release assets requires remote asset verification")

    if mode in {
        ReleaseMode.LOCAL_DEBUG,
        ReleaseMode.LOCAL_REBUILD,
        ReleaseMode.OFFLINE_DEBUG,
    }:
        for label, attribute in _REMOTE_WRITE_OPTIONS:
            if getattr(request, attribute):
                errors.append(f"{mode.value} mode cannot {label}")

    if request.rotate_trust_anchor:
        if not request.generate_manifest_key:
            errors.append("rotating the trust anchor requires generating a manifest key")
        if not request.build_installer:
            errors.append("rotating the trust anchor requires building the installer")

    if request.dry_run:
        for label, attribute in _DRY_RUN_OPTIONS:
            if getattr(request, attribute):
                errors.append(f"dry run cannot {label}")

    return tuple(errors)


def _compare_versions(left: str, right: str) -> int:
    left_parts = tuple(int(part) for part in left.split("."))
    right_parts = tuple(int(part) for part in right.split("."))
    return (left_parts > right_parts) - (left_parts < right_parts)


def _has_remote_writes(request: BuildRequest) -> bool:
    return any(getattr(request, attribute) for _, attribute in _REMOTE_WRITE_OPTIONS)


__all__ = ["resolve_release_mode", "validate_build_request"]
