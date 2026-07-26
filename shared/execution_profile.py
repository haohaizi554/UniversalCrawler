from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Iterable, Literal


HostSurface = Literal["desktop_gui", "public_web", "cli", "sdk", "test"]
LocalHostSurface = Literal["desktop_gui", "cli", "sdk", "test"]


class ExecutionProfileEscalation(ValueError):
    """Raised when a derived profile would gain a capability."""


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
        if not self.owner_id.strip():
            raise ValueError("owner_id must not be empty")

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
    if not roots.issubset(profile.approved_roots):
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
