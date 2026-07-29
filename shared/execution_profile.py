from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable, Literal


HostSurface = Literal["desktop_gui", "public_web", "cli", "sdk", "test"]
LocalHostSurface = Literal["desktop_gui", "cli", "sdk", "test"]
VALID_HOST_SURFACES = frozenset(
    {"desktop_gui", "public_web", "cli", "sdk", "test"}
)
VALID_LOCAL_HOST_SURFACES = frozenset(
    {"desktop_gui", "cli", "sdk", "test"}
)

DEFAULT_LOCAL_TOOL_PERMISSIONS = frozenset(
    {"read_file", "write_file", "destructive", "process", "network"}
)
DEFAULT_GUI_TOOL_OWNER_ID = "gui:local"


class ExecutionProfileEscalation(ValueError):
    """Raised when a derived profile would gain a capability."""


PROFILE_AUTHORITY_KEYS = frozenset(
    {
        "execution_profile",
        "host_surface",
        "owner_id",
        "allow_machine_credentials",
        "allow_caller_proxy",
        "require_public_network",
        "allow_tool_execution",
        "tool_permissions",
        "approved_roots",
        "allow_external_plugins",
    }
)

_PAYLOAD_CREDENTIAL_AND_PROXY_KEYS = frozenset({"cookie", "cookies", "proxy"})


def execution_profile_identity_error(
    *, host_surface: object, owner_id: object
) -> str | None:
    """Return a stable error for malformed execution ownership identities."""
    if type(host_surface) is not str or host_surface not in VALID_HOST_SURFACES:
        return "execution profile host_surface is invalid"
    if (
        type(owner_id) is not str
        or not owner_id
        or owner_id != owner_id.strip()
    ):
        return "execution profile owner_id is invalid"
    return None


def reject_execution_profile_overrides(payload: Mapping[str, Any]) -> None:
    """Reject untrusted payload fields that can widen execution authority."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")

    pending: list[Any] = [payload]
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            marker = id(value)
            if marker in visited:
                continue
            visited.add(marker)

            forbidden: set[str] = set()
            nested_values: list[Any] = []
            for key, nested in value.items():
                if type(key) is not str:
                    raise ExecutionProfileEscalation(
                        "payload cannot contain non-string authority keys"
                    )
                if (
                    key in PROFILE_AUTHORITY_KEYS
                    or key in _PAYLOAD_CREDENTIAL_AND_PROXY_KEYS
                    or key == "cookie_file"
                    or key.endswith("_cookie_file")
                ):
                    forbidden.add(key)
                nested_values.append(nested)
            if forbidden:
                raise ExecutionProfileEscalation(
                    "payload cannot set execution authority: "
                    + ", ".join(sorted(forbidden))
                )
            pending.extend(nested_values)
        elif isinstance(value, (list, tuple)):
            marker = id(value)
            if marker in visited:
                continue
            visited.add(marker)
            pending.extend(value)


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionProfile:
    host_surface: HostSurface
    owner_id: str
    allow_machine_credentials: bool
    allow_caller_proxy: bool
    require_public_network: bool
    allow_tool_execution: bool
    tool_permissions: frozenset[str]
    approved_roots: frozenset[Path]
    allow_external_plugins: bool

    def __post_init__(self) -> None:
        identity_error = execution_profile_identity_error(
            host_surface=self.host_surface,
            owner_id=self.owner_id,
        )
        if identity_error is not None:
            raise ValueError(identity_error)

        object.__setattr__(self, "tool_permissions", frozenset(self.tool_permissions))
        object.__setattr__(
            self,
            "approved_roots",
            frozenset(Path(root).resolve() for root in self.approved_roots),
        )

    def restrict(
        self,
        *,
        allow_machine_credentials: bool | None = None,
        allow_caller_proxy: bool | None = None,
        require_public_network: bool | None = None,
        allow_tool_execution: bool | None = None,
        tool_permissions: Iterable[str] | None = None,
        approved_roots: Iterable[Path] | None = None,
        allow_external_plugins: bool | None = None,
    ) -> "ExecutionProfile":
        return _restrict_profile(
            self,
            allow_machine_credentials=allow_machine_credentials,
            allow_caller_proxy=allow_caller_proxy,
            require_public_network=require_public_network,
            allow_tool_execution=allow_tool_execution,
            tool_permissions=tool_permissions,
            approved_roots=approved_roots,
            allow_external_plugins=allow_external_plugins,
        )


def public_web_profile(
    *, owner_id: str, approved_roots: Iterable[Path]
) -> ExecutionProfile:
    return ExecutionProfile(
        host_surface="public_web",
        owner_id=owner_id,
        allow_machine_credentials=False,
        allow_caller_proxy=False,
        require_public_network=True,
        allow_tool_execution=False,
        tool_permissions=frozenset(),
        approved_roots=frozenset(approved_roots),
        allow_external_plugins=False,
    )


def local_execution_profile(
    *,
    host_surface: LocalHostSurface,
    owner_id: str,
    approved_roots: Iterable[Path],
    tool_permissions: Iterable[str],
    allow_external_plugins: bool,
) -> ExecutionProfile:
    if (
        type(host_surface) is not str
        or host_surface not in VALID_LOCAL_HOST_SURFACES
    ):
        raise ValueError("execution profile host_surface is invalid")
    return ExecutionProfile(
        host_surface=host_surface,
        owner_id=owner_id,
        allow_machine_credentials=True,
        allow_caller_proxy=True,
        require_public_network=False,
        allow_tool_execution=True,
        tool_permissions=frozenset(tool_permissions),
        approved_roots=frozenset(approved_roots),
        allow_external_plugins=allow_external_plugins,
    )


def _restrict_profile(
    profile: ExecutionProfile,
    *,
    allow_machine_credentials: bool | None,
    allow_caller_proxy: bool | None,
    require_public_network: bool | None,
    allow_tool_execution: bool | None,
    tool_permissions: Iterable[str] | None,
    approved_roots: Iterable[Path] | None,
    allow_external_plugins: bool | None,
) -> ExecutionProfile:
    machine_credentials = _restrict_capability(
        profile.allow_machine_credentials,
        allow_machine_credentials,
        "allow_machine_credentials",
    )
    caller_proxy = _restrict_capability(
        profile.allow_caller_proxy,
        allow_caller_proxy,
        "allow_caller_proxy",
    )
    tool_execution = _restrict_capability(
        profile.allow_tool_execution,
        allow_tool_execution,
        "allow_tool_execution",
    )
    external_plugins = _restrict_capability(
        profile.allow_external_plugins,
        allow_external_plugins,
        "allow_external_plugins",
    )
    public_network = (
        profile.require_public_network
        if require_public_network is None
        else require_public_network
    )
    if profile.require_public_network and not public_network:
        raise ExecutionProfileEscalation("require_public_network cannot be weakened")

    permissions = (
        profile.tool_permissions
        if tool_permissions is None
        else frozenset(tool_permissions)
    )
    if not permissions.issubset(profile.tool_permissions):
        raise ExecutionProfileEscalation("tool_permissions cannot be expanded")

    roots = (
        profile.approved_roots
        if approved_roots is None
        else frozenset(Path(root).resolve() for root in approved_roots)
    )
    if not all(
        any(
            requested_root == current_root
            or current_root in requested_root.parents
            for current_root in profile.approved_roots
        )
        for requested_root in roots
    ):
        raise ExecutionProfileEscalation("approved_roots cannot be expanded")

    if (
        machine_credentials == profile.allow_machine_credentials
        and caller_proxy == profile.allow_caller_proxy
        and public_network == profile.require_public_network
        and tool_execution == profile.allow_tool_execution
        and permissions == profile.tool_permissions
        and roots == profile.approved_roots
        and external_plugins == profile.allow_external_plugins
    ):
        return profile

    return dataclasses.replace(
        profile,
        allow_machine_credentials=machine_credentials,
        allow_caller_proxy=caller_proxy,
        require_public_network=public_network,
        allow_tool_execution=tool_execution,
        tool_permissions=permissions,
        approved_roots=roots,
        allow_external_plugins=external_plugins,
    )


def _restrict_capability(
    current: bool, requested: bool | None, field_name: str
) -> bool:
    value = current if requested is None else requested
    if value and not current:
        raise ExecutionProfileEscalation(f"{field_name} cannot be enabled")
    return value
