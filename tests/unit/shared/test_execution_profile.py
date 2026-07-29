from __future__ import annotations

from shared.execution_profile import (
    ExecutionProfileEscalation,
    local_execution_profile,
    public_web_profile,
)

import pytest


def _reject_execution_profile_overrides(payload):
    from shared.execution_profile import reject_execution_profile_overrides

    return reject_execution_profile_overrides(payload)


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


def test_public_factory_preserves_empty_approved_roots():
    profile = public_web_profile(owner_id="session-empty", approved_roots=())

    assert profile.approved_roots == frozenset()


@pytest.mark.parametrize(
    "payload",
    [
        {"execution_profile": {"allow_tool_execution": True}},
        {"config": {"owner_id": "attacker"}},
        {"config": {"approved_roots": ["C:/"]}},
        {"nested": [{"tool_permissions": ["admin"]}]},
        {"allow_machine_credentials": True},
        {"allow_caller_proxy": True},
        {"allow_external_plugins": True},
    ],
)
def test_payload_cannot_supply_execution_authority(payload):
    with pytest.raises(ExecutionProfileEscalation, match="payload"):
        _reject_execution_profile_overrides(payload)


def test_ordinary_payload_fields_remain_valid():
    _reject_execution_profile_overrides(
        {
            "source": "douyin",
            "keyword": "cats",
            "config": {"timeout": 30, "max_items": 20},
        }
    )


def test_payload_non_string_key_fails_closed_without_string_coercion():
    class HostileKey:
        def __str__(self):
            raise AssertionError("attacker-controlled __str__ must not run")

    with pytest.raises(ExecutionProfileEscalation, match="payload"):
        _reject_execution_profile_overrides({HostileKey(): "value"})


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


@pytest.mark.parametrize(
    "owner_id",
    ["", " ", "\t", " owner", "owner ", None, 1],
)
def test_factories_reject_empty_owner(owner_id, tmp_path):
    with pytest.raises(ValueError, match="owner_id"):
        public_web_profile(owner_id=owner_id, approved_roots=(tmp_path,))


@pytest.mark.parametrize(
    "host_surface",
    ["", " ", "\t", "CLI", "cli ", "public_web", "unknown", None, 1],
)
def test_local_factory_rejects_invalid_host_surface(host_surface, tmp_path):
    with pytest.raises(ValueError, match="host_surface"):
        local_execution_profile(
            host_surface=host_surface,
            owner_id="pid-123",
            approved_roots=(tmp_path,),
            tool_permissions=(),
            allow_external_plugins=False,
        )


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


def test_restrict_allows_approved_root_to_narrow_to_a_descendant(
    local_profile,
    tmp_path,
):
    nested = tmp_path / "downloads" / "session" / "media"

    restricted = local_profile.restrict(approved_roots=(nested,))

    assert restricted.approved_roots == frozenset({nested.resolve()})


def test_restrict_rejects_a_symlink_descendant_that_resolves_outside_root(
    local_profile,
    tmp_path,
):
    approved = tmp_path / "downloads"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    link = approved / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable on this host: {exc}")

    with pytest.raises(ExecutionProfileEscalation):
        local_profile.restrict(approved_roots=(link / "media",))


def test_restrict_returns_self_for_an_identical_profile(local_profile):
    assert local_profile.restrict() is local_profile
