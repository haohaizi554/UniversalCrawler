"""Stable contracts shared by built-in and externally loaded tools."""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from shared.execution_profile import ExecutionProfile

_TOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_DISTRIBUTION_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)


class ToolRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class ToolCancelledError(RuntimeError):
    """Raised by cooperative tools after cancellation was requested."""


@dataclass(frozen=True, slots=True)
class ToolRequirements:
    """Capabilities one invocation needs after its parameters are normalized."""

    permissions: frozenset[str] = frozenset()
    requires_approved_roots: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permissions",
            frozenset(str(item).strip() for item in self.permissions if str(item).strip()),
        )


@dataclass(frozen=True, slots=True)
class ToolGrant:
    """Host-owned admission decision made before plugin code is called."""

    allowed: bool
    code: str = ""
    message: str = ""


class ToolGrantEvaluator:
    """Compare tool requirements with an immutable host execution profile."""

    @staticmethod
    def evaluate(
        *,
        requirements: ToolRequirements,
        declared_permissions: frozenset[str],
        provenance: str,
        execution_profile: ExecutionProfile,
    ) -> ToolGrant:
        if not execution_profile.allow_tool_execution:
            return ToolGrant(
                False,
                "tool_run_disabled",
                "tool execution is disabled for this host",
            )
        provenance_class = _classify_tool_provenance(str(provenance or ""))
        if provenance_class is None:
            return ToolGrant(
                False,
                "untrusted_tool_provenance",
                "tool provenance is not trusted",
            )
        if provenance_class == "external" and not execution_profile.allow_external_plugins:
            return ToolGrant(
                False,
                "external_plugins_disabled",
                "external tools are disabled for this host",
            )
        if not requirements.permissions <= declared_permissions:
            return ToolGrant(
                False,
                "undeclared_tool_permission",
                "tool requested an undeclared permission",
            )
        if not requirements.permissions <= execution_profile.tool_permissions:
            return ToolGrant(
                False,
                "tool_permission_denied",
                "tool permissions are not granted",
            )
        if requirements.requires_approved_roots and not execution_profile.approved_roots:
            return ToolGrant(
                False,
                "approved_roots_required",
                "at least one approved root is required",
            )
        return ToolGrant(True)


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self.is_cancelled()

    def cancelled(self) -> bool:
        return self.is_cancelled()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise ToolCancelledError("tool run cancelled")


@dataclass(frozen=True, slots=True)
class ToolManifest:
    """Declarative metadata used by every frontend to render one tool."""

    id: str
    title: str
    summary: str
    category: str = "general"
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()
    supports_cancel: bool = True
    icon: str = "toolbox"
    icon_file: str = ""
    input_example: str = ""
    output_example: str = ""
    version: str = "1"
    sort_order: int = 1000
    safety_level: str = "standard"
    read_only: bool = False
    destructive: bool = False
    execution_mode: str = "worker"
    run_in_worker: bool = True
    background: bool = True
    cancellable: bool = True
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_id = str(self.id or "").strip().lower()
        if not _TOOL_ID_PATTERN.fullmatch(normalized_id):
            raise ValueError(f"invalid tool id: {self.id!r}")
        if not str(self.title or "").strip():
            raise ValueError("tool title is required")
        if not str(self.summary or "").strip():
            raise ValueError("tool summary is required")
        object.__setattr__(self, "id", normalized_id)
        object.__setattr__(self, "permissions", tuple(str(item) for item in self.permissions))
        object.__setattr__(self, "requires", tuple(str(item) for item in self.requires))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "input_schema": _plain_value(self.input_schema),
            "permissions": list(self.permissions),
            "supports_cancel": bool(self.supports_cancel),
            "icon": self.icon,
            "icon_file": self.icon_file,
            "input_example": self.input_example,
            "output_example": self.output_example,
            "version": self.version,
            "sort_order": int(self.sort_order),
            "safety_level": self.safety_level,
            "read_only": bool(self.read_only),
            "destructive": bool(self.destructive),
            "execution_mode": self.execution_mode,
            "run_in_worker": bool(self.run_in_worker),
            "background": bool(self.background),
            "cancellable": bool(self.cancellable and self.supports_cancel),
            "requires": list(self.requires),
        }


@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    valid: bool = True
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        *,
        parameters: Mapping[str, Any] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> ToolValidationResult:
        return cls(True, (), warnings, dict(parameters or {}))

    @classmethod
    def rejected(cls, *errors: str) -> ToolValidationResult:
        normalized = tuple(str(item) for item in errors if str(item).strip())
        return cls(False, normalized or ("tool input is invalid",))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.valid else "error",
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "parameters": _plain_value(self.parameters),
        }


ProgressCallback = Callable[[int, str, Mapping[str, Any]], None]
PathAuthorizer = Callable[[str | os.PathLike[str]], str | os.PathLike[str]]


@dataclass(slots=True)
class ToolContext:
    """Per-run context. Tools receive services, permissions and cancellation here."""

    parameters: Mapping[str, Any]
    run_id: str = ""
    approved_roots: tuple[str, ...] = ()
    execution_profile: ExecutionProfile | None = None
    provenance: str = "explicit"
    settings: Mapping[str, Any] = field(default_factory=dict)
    services: Mapping[str, Any] = field(default_factory=dict)
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    progress_callback: ProgressCallback | None = None
    path_authorizer: PathAuthorizer | None = None

    @property
    def inputs(self) -> Mapping[str, Any]:
        return self.parameters

    @property
    def params(self) -> Mapping[str, Any]:
        return self.parameters

    @property
    def cancel_event(self) -> CancellationToken:
        return self.cancellation

    @property
    def cancellation_token(self) -> CancellationToken:
        return self.cancellation

    @property
    def owner_id(self) -> str:
        profile = self.execution_profile
        return profile.owner_id if profile is not None else ""

    def is_cancelled(self) -> bool:
        return self.cancellation.is_cancelled()

    def raise_if_cancelled(self) -> None:
        self.cancellation.raise_if_cancelled()

    def report_progress(
        self,
        percent: int | float,
        message: str = "",
        **details: Any,
    ) -> None:
        self.raise_if_cancelled()
        callback = self.progress_callback
        if callback is None:
            return
        normalized = max(0, min(100, int(percent)))
        callback(normalized, str(message or ""), details)

    def authorize_path(self, path: str | os.PathLike[str]) -> Path:
        """Resolve a path and enforce the approved-root boundary."""

        profile = self.execution_profile
        source_roots = profile.approved_roots if profile is not None else self.approved_roots
        roots = tuple(Path(root).expanduser().resolve() for root in source_roots if str(root).strip())
        if not roots:
            raise PermissionError("at least one approved root is required")
        candidate = self.path_authorizer(path) if self.path_authorizer is not None else path
        resolved = Path(candidate).expanduser().resolve()
        if not any(_is_relative_to(resolved, root) for root in roots):
            raise PermissionError("path is outside approved roots")
        return resolved


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    status: ToolRunStatus
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    output_paths: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    private_data: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_paths", tuple(str(path) for path in self.output_paths))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "private_data", freeze_private_data(self.private_data))

    @classmethod
    def success(
        cls,
        message: str = "",
        *,
        data: Mapping[str, Any] | None = None,
        output_paths: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        private_data: Mapping[str, Any] | None = None,
    ) -> ToolRunResult:
        return cls(
            ToolRunStatus.SUCCEEDED,
            str(message or ""),
            dict(data or {}),
            tuple(str(path) for path in output_paths),
            tuple(str(item) for item in warnings),
            dict(private_data or {}),
        )

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
        warnings: tuple[str, ...] = (),
        private_data: Mapping[str, Any] | None = None,
    ) -> ToolRunResult:
        return cls(
            ToolRunStatus.FAILED,
            str(message or "tool run failed"),
            dict(data or {}),
            (),
            tuple(str(item) for item in warnings),
            dict(private_data or {}),
        )

    @classmethod
    def cancelled(cls, message: str = "tool run cancelled") -> ToolRunResult:
        return cls(ToolRunStatus.CANCELLED, str(message or "tool run cancelled"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, ToolRunStatus) else str(self.status),
            "message": self.message,
            "data": _plain_value(self.data),
            "output_paths": list(self.output_paths),
            "warnings": list(self.warnings),
        }


@runtime_checkable
class ToolPlugin(Protocol):
    manifest: ToolManifest

    def requirements_for(
        self,
        parameters: Mapping[str, Any],
    ) -> ToolRequirements: ...

    def validate(self, context: ToolContext) -> Any: ...

    def run(self, context: ToolContext) -> ToolRunResult: ...


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """One tool paired with provenance assigned only by its host registry."""

    tool: ToolPlugin
    provenance: str


def _classify_tool_provenance(provenance: str) -> str | None:
    if provenance == "builtin":
        return "builtin"
    if provenance == "explicit":
        return "external"
    if provenance.startswith("external:"):
        suffix = provenance.removeprefix("external:")
        return "external" if _is_resolved_absolute_path(suffix) else None
    if provenance.startswith("entry_point:"):
        suffix = provenance.removeprefix("entry_point:")
        if _is_safe_provenance_suffix(suffix) and _DISTRIBUTION_NAME_PATTERN.fullmatch(
            suffix
        ):
            return "external"
    return None


def _is_resolved_absolute_path(value: str) -> bool:
    if not _is_safe_provenance_suffix(value):
        return False
    try:
        path = Path(value)
        return path.is_absolute() and path == path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _is_safe_provenance_suffix(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and not any(unicodedata.category(character).startswith("C") for character in value)
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def freeze_private_data(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a fresh recursively immutable mapping excluded from serialization."""

    source = value if isinstance(value, Mapping) else {}
    return MappingProxyType(
        {str(key): _freeze_private_value(item) for key, item in source.items()}
    )


def _freeze_private_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_private_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_private_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_private_value(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _freeze_private_value(value.value)
    if value is None or type(value) in {str, int, float, bool, bytes}:
        return value
    raise TypeError(
        f"unsupported private data value: {type(value).__name__}"
    )


__all__ = [
    "CancellationToken",
    "PathAuthorizer",
    "ProgressCallback",
    "ToolCancelledError",
    "ToolContext",
    "ToolDescriptor",
    "ToolGrant",
    "ToolGrantEvaluator",
    "ToolManifest",
    "ToolPlugin",
    "ToolRequirements",
    "ToolRunResult",
    "ToolRunStatus",
    "ToolValidationResult",
    "freeze_private_data",
]
