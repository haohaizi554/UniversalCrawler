from __future__ import annotations

from shared.execution_profile import (
    ExecutionProfileEscalation,
    local_execution_profile,
    public_web_profile,
)

import pytest


def test_public_factory_is_session_owned_and_fail_closed(tmp_path):
    root = tmp_path / "downloads"

    profile = public_web_profile(owner_id="session-a", approved_roots=(root,))

    assert profile.host_surface == "public_web"
    assert profile.owner_id == "session-a"
    assert not profile.allow_machine_credentials
    assert not profile.allow_caller_proxy
    assert profile.require_public_network
    assert not profile.allow_tool_execution
    assert profile.tool_permissions == frozenset()
    assert profile.approved_roots == frozenset({root.resolve()})
    assert not profile.allow_external_plugins


def test_local_factory_requires_real_owner_and_surface(tmp_path):
    profile = local_execution_profile(
        host_surface="cli",
        owner_id="pid-123",
        approved_roots=(tmp_path,),
        tool_permissions=("diagnose", "read"),
        allow_external_plugins=False,
    )

    assert profile.host_surface == "cli"
    assert profile.owner_id == "pid-123"
    assert profile.allow_machine_credentials
    assert profile.allow_caller_proxy
    assert not profile.require_public_network
    assert profile.allow_tool_execution
    assert profile.tool_permissions == frozenset({"diagnose", "read"})
    assert profile.approved_roots == frozenset({tmp_path.resolve()})


@pytest.mark.parametrize("owner_id", ["", " ", "\t"])
def test_factories_reject_empty_owner(owner_id, tmp_path):
    with pytest.raises(ValueError, match="owner_id"):
        public_web_profile(owner_id=owner_id, approved_roots=(tmp_path,))


@pytest.fixture
def local_profile(tmp_path):
    return local_execution_profile(
        host_surface="cli",
        owner_id="pid-123",
        approved_roots=(tmp_path / "downloads",),
        tool_permissions=("diagnose", "read"),
        allow_external_plugins=True,
    )


@pytest.fixture
def public_profile(tmp_path):
    return public_web_profile(owner_id="session-a", approved_roots=(tmp_path,))


def test_restrict_can_only_remove_local_capabilities(local_profile, tmp_path):
    child = local_profile.restrict(
        allow_machine_credentials=False,
        allow_caller_proxy=False,
        allow_tool_execution=True,
        tool_permissions=("read",),
        approved_roots=(tmp_path / "downloads",),
        allow_external_plugins=False,
    )

    assert child.owner_id == local_profile.owner_id
    assert child.host_surface == local_profile.host_surface
    assert child.tool_permissions == frozenset({"read"})
    assert child.approved_roots == frozenset({(tmp_path / "downloads").resolve()})
    assert not child.allow_machine_credentials
    assert not child.allow_caller_proxy
    assert not child.allow_external_plugins


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allow_machine_credentials", True),
        ("allow_caller_proxy", True),
        ("allow_tool_execution", True),
        ("allow_external_plugins", True),
        ("require_public_network", False),
    ],
)
def test_public_profile_rejects_boolean_escalation(public_profile, field, value):
    with pytest.raises(ExecutionProfileEscalation):
        public_profile.restrict(**{field: value})


def test_restrict_rejects_permission_or_root_expansion(local_profile, tmp_path):
    with pytest.raises(ExecutionProfileEscalation):
        local_profile.restrict(tool_permissions=("read", "admin"))
    with pytest.raises(ExecutionProfileEscalation):
        local_profile.restrict(approved_roots=(tmp_path.parent,))


def test_restrict_returns_self_for_an_identical_profile(local_profile):
    assert local_profile.restrict() is local_profile
