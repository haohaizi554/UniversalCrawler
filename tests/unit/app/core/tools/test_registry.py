from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.tools.contracts import ToolRequirements
from app.core.tools import registry as registry_module
from app.core.tools.registry import ToolRegistry
from shared.execution_profile import local_execution_profile


def _write_external_tool(path: Path, title: str) -> None:
    path.write_text(
        "\n".join(
            [
                "from app.core.tools.contracts import ToolManifest, ToolRequirements, ToolRunResult",
                "class ExternalTool:",
                f"    manifest = ToolManifest(id='external.demo', title={title!r}, summary='demo')",
                "    def validate(self, context):",
                "        return []",
                "    def requirements_for(self, parameters):",
                "        return ToolRequirements()",
                "    def run(self, context):",
                "        return ToolRunResult.success('ok')",
                "TOOL = ExternalTool()",
            ]
        ),
        encoding="utf-8",
    )
    os.utime(path, None)


def test_external_tool_directory_hot_reloads_changes_and_removals(tmp_path: Path) -> None:
    plugin = tmp_path / "demo_tool.py"
    _write_external_tool(plugin, "First")
    registry = ToolRegistry(
        tools=[],
        external_dir=tmp_path,
        include_builtins=False,
        include_entry_points=False,
        enable_external=True,
        execution_profile=local_execution_profile(
            host_surface="test",
            owner_id="test:registry",
            approved_roots=(tmp_path,),
            tool_permissions=(),
            allow_external_plugins=True,
        ),
    )

    assert registry.get("external.demo").manifest.title == "First"

    _write_external_tool(plugin, "Second")
    second = registry.reload_external(force=True)
    assert second.updated == ("external.demo",)
    assert registry.get("external.demo").manifest.title == "Second"

    plugin.unlink()
    third = registry.reload_external(force=True)
    assert third.removed == ("external.demo",)
    assert registry.get("external.demo") is None


def test_registry_rejects_duplicate_ids() -> None:
    class Tool:
        from app.core.tools.contracts import ToolManifest

        manifest = ToolManifest(id="duplicate", title="One", summary="demo")

        def validate(self, context):
            return []

        def requirements_for(self, parameters):
            return ToolRequirements()

        def run(self, context):
            raise AssertionError

    registry = ToolRegistry(
        tools=[Tool()],
        include_builtins=False,
        include_entry_points=False,
    )

    try:
        registry.register(Tool())
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate tool id was accepted")


def test_registry_defaults_to_builtins_without_executing_external_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "executed"
    (tmp_path / "unsafe.py").write_text(
        f"open({str(marker)!r}, 'w').write('x')",
        encoding="utf-8",
    )
    monkeypatch.setenv("UCRAWL_TOOL_PLUGIN_ROOT", str(tmp_path))

    registry = ToolRegistry()

    assert not marker.exists()
    assert registry.manifests()
    assert all(row["provenance"] == "builtin" for row in registry.manifests())


def test_external_loading_requires_host_authorization(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    (tmp_path / "unsafe.py").write_text(
        f"open({str(marker)!r}, 'w').write('x')",
        encoding="utf-8",
    )
    denied_profile = local_execution_profile(
        host_surface="test",
        owner_id="test:denied",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=False,
    )

    registry = ToolRegistry(
        tools=[],
        external_dir=tmp_path,
        include_builtins=False,
        enable_external=True,
        execution_profile=denied_profile,
    )

    assert not marker.exists()
    assert registry.reload_external().errors == ("external plugins are disabled",)


def test_registry_rejects_tools_without_dynamic_requirements() -> None:
    class LegacyTool:
        from app.core.tools.contracts import ToolManifest

        manifest = ToolManifest(id="legacy", title="Legacy", summary="demo")

        def validate(self, context):
            return []

        def run(self, context):
            raise AssertionError

    with pytest.raises(TypeError, match="requirements_for"):
        ToolRegistry(
            tools=[LegacyTool()],
            include_builtins=False,
            include_entry_points=False,
        )


def test_registry_provenance_is_host_owned() -> None:
    class Tool:
        from app.core.tools.contracts import ToolManifest

        manifest = ToolManifest(id="explicit", title="Explicit", summary="demo")

        def requirements_for(self, parameters):
            return ToolRequirements()

        def validate(self, context):
            return []

        def run(self, context):
            raise AssertionError

    registry = ToolRegistry(
        tools=[Tool()],
        include_builtins=False,
        include_entry_points=False,
    )

    descriptor = registry.descriptor("explicit")
    assert descriptor is not None
    assert descriptor.provenance == "explicit"
    assert registry.manifests()[0]["provenance"] == "explicit"


def test_entry_point_loading_is_authorized_and_records_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Tool:
        from app.core.tools.contracts import ToolManifest

        manifest = ToolManifest(id="entry.demo", title="Entry", summary="demo")

        def requirements_for(self, parameters):
            return ToolRequirements()

        def validate(self, context):
            return []

        def run(self, context):
            raise AssertionError

    class EntryPoint:
        dist = SimpleNamespace(name="trusted-tools")
        module = "trusted_tools"

        @staticmethod
        def load():
            return Tool()

    monkeypatch.setattr(
        registry_module,
        "entry_points",
        lambda *, group: [EntryPoint()] if group == "ucrawl.tools" else [],
    )
    profile = local_execution_profile(
        host_surface="test",
        owner_id="test:entry-point",
        approved_roots=(tmp_path,),
        tool_permissions=(),
        allow_external_plugins=True,
    )

    registry = ToolRegistry(
        include_builtins=False,
        include_entry_points=True,
        enable_external=True,
        execution_profile=profile,
    )

    descriptor = registry.descriptor("entry.demo")
    assert descriptor is not None
    assert descriptor.provenance == "entry_point:trusted-tools"
