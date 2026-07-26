from __future__ import annotations

import os
from pathlib import Path

from app.core.tools.registry import ToolRegistry


def _write_external_tool(path: Path, title: str) -> None:
    path.write_text(
        "\n".join(
            [
                "from app.core.tools.contracts import ToolManifest, ToolRunResult",
                "class ExternalTool:",
                f"    manifest = ToolManifest(id='external.demo', title={title!r}, summary='demo')",
                "    def validate(self, context):",
                "        return []",
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
