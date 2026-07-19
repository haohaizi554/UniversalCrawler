"""Version-source validation and transactional projection updates."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


SEMVER_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_VERSION_ASSIGNMENT_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


class VersionUpdateError(RuntimeError):
    """Raised when a version projection cannot be safely planned or applied."""


@dataclass(frozen=True)
class VersionFileChange:
    path: Path
    before: str
    after: str


@dataclass(frozen=True)
class VersionUpdatePlan:
    project_root: Path
    previous_version: str
    target_version: str
    changes: tuple[VersionFileChange, ...]


@dataclass(frozen=True)
class VersionUpdateResult:
    previous_version: str
    target_version: str
    changed_files: tuple[Path, ...]


@dataclass(frozen=True)
class _VersionProjection:
    name: str
    relative_path: Path


_VERSION_PROJECTIONS = (
    _VersionProjection("canonical version", Path("shared/version.py")),
    _VersionProjection("Chinese README", Path("README.md")),
    _VersionProjection("English README", Path("README_EN.md")),
    _VersionProjection("documentation index", Path("docs/README.md")),
    _VersionProjection("CLI skill manifest", Path("cli/skill/SKILL.md")),
)


def normalize_version(value: str) -> str:
    match = SEMVER_RE.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    return ".".join(match.groups())


def read_project_version(project_root: Path) -> str:
    version_file = Path(project_root).resolve() / "shared/version.py"
    try:
        source = version_file.read_text(encoding="utf-8")
    except OSError as error:
        raise VersionUpdateError(f"cannot read canonical version file: {version_file}") from error

    matches = _VERSION_ASSIGNMENT_RE.findall(source)
    if len(matches) != 1:
        raise VersionUpdateError(
            f"canonical version file must contain exactly one __version__ assignment: {version_file}"
        )
    try:
        return normalize_version(matches[0])
    except ValueError as error:
        raise VersionUpdateError(f"canonical version is invalid: {matches[0]!r}") from error


def plan_version_update(target_version: str, project_root: Path) -> VersionUpdatePlan:
    root = Path(project_root).resolve()
    previous_version = read_project_version(root)
    target_version = normalize_version(target_version)
    changes: list[VersionFileChange] = []

    for projection in _VERSION_PROJECTIONS:
        path = root / projection.relative_path
        try:
            before = path.read_text(encoding="utf-8")
        except OSError as error:
            raise VersionUpdateError(f"cannot read {projection.name}: {path}") from error
        after, replacements = _replace_projection(
            projection, before, previous_version, target_version
        )
        if replacements != 1:
            raise VersionUpdateError(
                f"{projection.name} must contain exactly one current-version projection "
                f"for {previous_version}: {path}"
            )
        changes.append(VersionFileChange(path=path, before=before, after=after))

    return VersionUpdatePlan(
        project_root=root,
        previous_version=previous_version,
        target_version=target_version,
        changes=tuple(changes),
    )


def apply_version_update(plan: VersionUpdatePlan) -> VersionUpdateResult:
    temporary_files: list[tuple[VersionFileChange, Path]] = []
    try:
        for change in plan.changes:
            temporary_files.append((change, _write_temporary_file(change.path, change.after)))
    except OSError as error:
        _remove_temporary_files(path for _, path in temporary_files)
        raise VersionUpdateError("version update could not prepare atomic replacements") from error

    replaced: list[VersionFileChange] = []
    try:
        for change, temporary_file in temporary_files:
            os.replace(temporary_file, change.path)
            replaced.append(change)
    except OSError as error:
        _remove_temporary_files(path for _, path in temporary_files)
        rollback_errors = _restore_replaced_files(replaced)
        if rollback_errors:
            raise VersionUpdateError("version update failed and rollback failed") from error
        raise VersionUpdateError("version update failed and rolled back") from error

    return VersionUpdateResult(
        previous_version=plan.previous_version,
        target_version=plan.target_version,
        changed_files=tuple(change.path for change in plan.changes),
    )


def verify_version_contract(project_root: Path, expected_version: str) -> tuple[str, ...]:
    root = Path(project_root).resolve()
    expected_version = normalize_version(expected_version)
    issues: list[str] = []

    try:
        current_version = read_project_version(root)
    except VersionUpdateError as error:
        return (str(error),)

    if current_version != expected_version:
        issues.append(
            f"shared/version.py declares {current_version}, expected {expected_version}"
        )

    for projection in _VERSION_PROJECTIONS:
        path = root / projection.relative_path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            issues.append(f"cannot read {projection.name}: {path} ({error})")
            continue
        _, replacements = _replace_projection(
            projection, source, expected_version, expected_version
        )
        if replacements != 1:
            issues.append(
                f"{projection.relative_path.as_posix()} must contain exactly one "
                f"current-version projection for {expected_version}"
            )

    return tuple(issues)


def _replace_projection(
    projection: _VersionProjection,
    source: str,
    previous_version: str,
    target_version: str,
) -> tuple[str, int]:
    escaped_previous = re.escape(previous_version)

    if projection.relative_path == Path("shared/version.py"):
        pattern = re.compile(rf'^__version__ = "{escaped_previous}"$', re.MULTILINE)
        return pattern.subn(f'__version__ = "{target_version}"', source)

    if projection.relative_path == Path("README.md"):
        pattern = re.compile(
            rf'(?s)(<img alt="Version" src="https://img\.shields\.io/badge/Version-v)'
            rf'{escaped_previous}(-7C3AED" />.*?当前版本号为 \*\*v){escaped_previous}(\*\*。)'
        )
        replacement = rf'\g<1>{target_version}\g<2>{target_version}\g<3>'
        return pattern.subn(replacement, source)

    if projection.relative_path == Path("README_EN.md"):
        pattern = re.compile(
            rf'(?s)(<img alt="Version" src="https://img\.shields\.io/badge/Version-v)'
            rf'{escaped_previous}(-7C3AED" />.*?The current project version is \*\*v)'
            rf'{escaped_previous}(\*\*\.)'
        )
        replacement = rf'\g<1>{target_version}\g<2>{target_version}\g<3>'
        return pattern.subn(replacement, source)

    if projection.relative_path == Path("docs/README.md"):
        pattern = re.compile(rf'当前文档基线对应源码版本 `{escaped_previous}`')
        return pattern.subn(f"当前文档基线对应源码版本 `{target_version}`", source)

    if projection.relative_path == Path("cli/skill/SKILL.md"):
        pattern = re.compile(rf"^version: {escaped_previous}$", re.MULTILINE)
        return pattern.subn(f"version: {target_version}", source)

    raise AssertionError(f"unsupported version projection: {projection.relative_path}")


def _write_temporary_file(destination: Path, content: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_file = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary_file.unlink(missing_ok=True)
        raise
    return temporary_file


def _restore_replaced_files(replaced: list[VersionFileChange]) -> list[OSError]:
    errors: list[OSError] = []
    for change in reversed(replaced):
        try:
            temporary_file = _write_temporary_file(change.path, change.before)
            os.replace(temporary_file, change.path)
        except OSError as error:
            errors.append(error)
    return errors


def _remove_temporary_files(paths: object) -> None:
    for path in paths:
        Path(path).unlink(missing_ok=True)


__all__ = [
    "VersionFileChange",
    "VersionUpdateError",
    "VersionUpdatePlan",
    "VersionUpdateResult",
    "apply_version_update",
    "normalize_version",
    "plan_version_update",
    "read_project_version",
    "verify_version_contract",
]
