from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.tools.contracts import (
    CancellationToken,
    ToolCancelledError,
    ToolContext,
    ToolGrantEvaluator,
    ToolManifest,
    ToolRequirements,
    ToolRunResult,
    ToolRunStatus,
)
from app.core.tools.builtin.download_residue import TOOL as DOWNLOAD_RESIDUE_TOOL
from shared.execution_profile import local_execution_profile, public_web_profile


def test_manifest_serializes_stable_frontend_contract() -> None:
    manifest = ToolManifest(
        id="media.health",
        title="媒体体检",
        summary="检查媒体流",
        category="media",
        input_schema={"path": {"type": "file", "required": True}},
        permissions=("read_file",),
        supports_cancel=True,
        icon="metadata",
        sort_order=20,
    )

    payload = manifest.to_dict()

    assert payload["id"] == "media.health"
    assert payload["input_schema"]["path"]["type"] == "file"
    assert payload["permissions"] == ["read_file"]
    assert payload["supports_cancel"] is True
    assert payload["sort_order"] == 20


def test_context_authorizes_only_paths_inside_approved_roots(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "video.mp4"
    source.write_bytes(b"media")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"media")
    context = ToolContext(parameters={}, approved_roots=(str(approved),))

    assert context.authorize_path(source) == source.resolve()
    with pytest.raises(PermissionError):
        context.authorize_path(outside)


def test_path_authorization_rejects_empty_host_roots(tmp_path: Path) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:path",
        approved_roots=(),
        tool_permissions=("read_file",),
        allow_external_plugins=False,
    )
    context = ToolContext(
        parameters={},
        execution_profile=profile,
        provenance="builtin",
    )

    with pytest.raises(PermissionError, match="approved root"):
        context.authorize_path(tmp_path / "video.mp4")


def test_cancel_token_interrupts_context() -> None:
    token = CancellationToken()
    context = ToolContext(parameters={}, cancellation=token)

    token.cancel()

    assert context.is_cancelled()
    with pytest.raises(ToolCancelledError):
        context.raise_if_cancelled()


def test_run_result_is_json_compatible() -> None:
    result = ToolRunResult.success(
        "完成",
        data={"streams": 2},
        output_paths=("D:/output.mp4",),
        warnings=("warning",),
    )

    payload = result.to_dict()

    assert payload == {
        "status": ToolRunStatus.SUCCEEDED.value,
        "message": "完成",
        "data": {"streams": 2},
        "output_paths": ["D:/output.mp4"],
        "warnings": ["warning"],
    }


def test_run_result_private_data_is_immutable_and_never_serialized() -> None:
    private_url = "https://example.com/watch?token=contract-private"
    result = ToolRunResult.success(
        "parsed",
        data={"links": [{"candidate_id": "candidate-1"}]},
        private_data={
            "candidates": [
                {"candidate_id": "candidate-1", "private_url": private_url}
            ]
        },
    )

    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert private_url not in serialized
    assert result.private_data["candidates"][0]["private_url"] == private_url
    with pytest.raises(TypeError):
        result.private_data["new"] = "mutation"
    with pytest.raises(TypeError):
        result.private_data["candidates"][0]["private_url"] = "mutation"
    with pytest.raises(TypeError):
        json.dumps(result.private_data)


def test_run_result_private_data_copies_binary_leaves_and_rejects_mutable_objects() -> None:
    source = bytearray(b"private")
    result = ToolRunResult.success(
        "parsed",
        private_data={"binary": source},
    )

    source[:] = b"mutated"

    assert result.private_data["binary"] == b"private"
    assert isinstance(result.private_data["binary"], bytes)

    class MutableLeaf:
        pass

    with pytest.raises(TypeError, match="unsupported private data value"):
        ToolRunResult.success("parsed", private_data={"leaf": MutableLeaf()})


def test_download_residue_requirements_change_with_requested_mode() -> None:
    diagnose = DOWNLOAD_RESIDUE_TOOL.requirements_for({"mode": "diagnose"})
    cleanup = DOWNLOAD_RESIDUE_TOOL.requirements_for({"mode": "cleanup"})

    assert diagnose == ToolRequirements(
        frozenset({"read_file"}),
        requires_approved_roots=True,
    )
    assert cleanup == ToolRequirements(
        frozenset({"read_file", "write_file", "destructive"}),
        requires_approved_roots=True,
    )


def test_public_web_host_grant_cannot_be_widened_by_tool_parameters() -> None:
    profile = public_web_profile(owner_id="web:test", approved_roots=())
    requirements = ToolRequirements(
        frozenset({"read_file"}),
        requires_approved_roots=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=requirements,
        declared_permissions=frozenset({"read_file"}),
        provenance="builtin",
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "tool_run_disabled"


@pytest.mark.parametrize("allow_external_plugins", [False, True])
def test_only_exact_builtin_provenance_is_trusted_without_external_plugin_access(
    allow_external_plugins: bool,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=allow_external_plugins,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance="builtin",
        execution_profile=profile,
    )

    assert grant.allowed is True
    assert grant.code == ""


@pytest.mark.parametrize(
    ("allow_external_plugins", "expected_allowed", "expected_code"),
    [
        (False, False, "external_plugins_disabled"),
        (True, True, ""),
    ],
)
def test_explicit_provenance_requires_external_plugin_access(
    allow_external_plugins: bool,
    expected_allowed: bool,
    expected_code: str,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=allow_external_plugins,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance="explicit",
        execution_profile=profile,
    )

    assert grant.allowed is expected_allowed
    assert grant.code == expected_code


@pytest.mark.parametrize(
    ("allow_external_plugins", "expected_allowed", "expected_code"),
    [
        (False, False, "external_plugins_disabled"),
        (True, True, ""),
    ],
)
def test_absolute_resolved_external_provenance_requires_external_plugin_access(
    tmp_path: Path,
    allow_external_plugins: bool,
    expected_allowed: bool,
    expected_code: str,
) -> None:
    plugin_path = (tmp_path / "plugins" / "acme-tool").resolve()
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=allow_external_plugins,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"external:{plugin_path}",
        execution_profile=profile,
    )

    assert grant.allowed is expected_allowed
    assert grant.code == expected_code


@pytest.mark.parametrize(
    ("allow_external_plugins", "expected_allowed", "expected_code"),
    [
        (False, False, "external_plugins_disabled"),
        (True, True, ""),
    ],
)
@pytest.mark.parametrize(
    "distribution",
    ["a", "Acme.Tools-2_core", "acme--tools"],
)
def test_ascii_distribution_entry_point_requires_external_plugin_access(
    distribution: str,
    allow_external_plugins: bool,
    expected_allowed: bool,
    expected_code: str,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=allow_external_plugins,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"entry_point:{distribution}",
        execution_profile=profile,
    )

    assert grant.allowed is expected_allowed
    assert grant.code == expected_code


@pytest.mark.parametrize("allow_external_plugins", [False, True])
@pytest.mark.parametrize(
    "provenance",
    [
        "",
        " ",
        "unknown",
        "builtin:",
        "builtin:core",
        " builtin",
        "builtin ",
        "explicit:",
        "external",
        "external:",
        "external:   ",
        "entry_point",
        "entry_point:",
        "entry_point:\t",
        "entry_point: acme",
        "entry_point:acme ",
        "EXTERNAL:acme",
    ],
)
def test_untrusted_provenance_is_rejected_even_when_external_plugins_are_enabled(
    provenance: str,
    allow_external_plugins: bool,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=allow_external_plugins,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=provenance,
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "untrusted_tool_provenance"


@pytest.mark.parametrize(
    "suffix",
    [
        "plugins/acme-tool",
        "./plugins/acme-tool",
    ],
)
def test_external_provenance_rejects_relative_paths(
    suffix: str,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"external:{suffix}",
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "untrusted_tool_provenance"


def test_external_provenance_rejects_unresolved_absolute_path(tmp_path: Path) -> None:
    unresolved = tmp_path / "plugins" / ".." / "acme-tool"
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"external:{unresolved}",
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "untrusted_tool_provenance"


def test_external_provenance_rejects_whitespace_around_absolute_path(
    tmp_path: Path,
) -> None:
    plugin_path = (tmp_path / "plugins" / "acme-tool").resolve()
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    for suffix in (f" {plugin_path}", f"{plugin_path} "):
        grant = ToolGrantEvaluator.evaluate(
            requirements=ToolRequirements(),
            declared_permissions=frozenset(),
            provenance=f"external:{suffix}",
            execution_profile=profile,
        )

        assert grant.allowed is False, suffix
        assert grant.code == "untrusted_tool_provenance", suffix


def test_external_provenance_allows_resolved_unicode_absolute_path(
    tmp_path: Path,
) -> None:
    plugin_path = (tmp_path / "\u63d2\u4ef6" / "\u5de5\u5177").resolve()
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"external:{plugin_path}",
        execution_profile=profile,
    )

    assert grant.allowed is True
    assert grant.code == ""


@pytest.mark.parametrize(
    "distribution",
    [
        "-acme",
        "acme-",
        ".acme",
        "acme.",
        "_acme",
        "acme_",
        "acme tools",
        "acme/tools",
        "acme:tools",
        "\u5de5\u5177",
    ],
)
def test_entry_point_provenance_rejects_non_distribution_names(
    distribution: str,
) -> None:
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"entry_point:{distribution}",
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "untrusted_tool_provenance"


@pytest.mark.parametrize("prefix", ["external:", "entry_point:"])
@pytest.mark.parametrize(
    "category_c_character",
    ["\n", "\u200b", "\ud800", "\ue000", "\u0378"],
    ids=["control", "format", "surrogate", "private-use", "unassigned"],
)
def test_provenance_suffix_rejects_every_unicode_category_c_family(
    tmp_path: Path,
    prefix: str,
    category_c_character: str,
) -> None:
    suffix = f"acme{category_c_character}tools"
    if prefix == "external:":
        suffix = f"{(tmp_path / 'plugins').resolve()}{suffix}"
    profile = local_execution_profile(
        host_surface="test",
        owner_id="unit:provenance",
        approved_roots=(),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    grant = ToolGrantEvaluator.evaluate(
        requirements=ToolRequirements(),
        declared_permissions=frozenset(),
        provenance=f"{prefix}{suffix}",
        execution_profile=profile,
    )

    assert grant.allowed is False
    assert grant.code == "untrusted_tool_provenance"


def test_public_web_policy_precedes_every_provenance_class(tmp_path: Path) -> None:
    profile = public_web_profile(owner_id="web:provenance", approved_roots=())
    provenances = (
        "builtin",
        "explicit",
        f"external:{(tmp_path / 'plugins' / 'acme-tool').resolve()}",
        "entry_point:acme-tools",
        "",
        "unknown",
        "external:relative/path",
        "entry_point:-invalid",
    )

    for provenance in provenances:
        grant = ToolGrantEvaluator.evaluate(
            requirements=ToolRequirements(),
            declared_permissions=frozenset(),
            provenance=provenance,
            execution_profile=profile,
        )

        assert grant.allowed is False, provenance
        assert grant.code == "tool_run_disabled", provenance
