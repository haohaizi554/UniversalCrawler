from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.tools.contracts import ToolManifest, ToolPlugin, ToolRequirements
from app.core.tools import registry as registry_module
from app.core.tools.registry import ToolRegistry
from shared.execution_profile import local_execution_profile


def _write_external_tool(path: Path, title: str) -> None:
    _write_external_tool_with_id(path, "external.demo", title)


def _write_external_tool_with_id(path: Path, tool_id: str, title: str) -> None:
    path.write_text(
        "\n".join(
            [
                "from app.core.tools.contracts import ToolManifest, ToolRequirements, ToolRunResult",
                "class ExternalTool:",
                f"    manifest = ToolManifest(id={tool_id!r}, title={title!r}, summary='demo')",
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


def _write_external_tool_bundle(path: Path, first_title: str, second_title: str) -> None:
    path.write_text(
        "\n".join(
            [
                "from app.core.tools.contracts import ToolManifest, ToolRequirements, ToolRunResult",
                "class FirstTool:",
                f"    manifest = ToolManifest(id='external.one', title={first_title!r}, summary='demo')",
                "    def validate(self, context):",
                "        return []",
                "    def requirements_for(self, parameters):",
                "        return ToolRequirements()",
                "    def run(self, context):",
                "        return ToolRunResult.success('one')",
                "class SecondTool:",
                f"    manifest = ToolManifest(id='external.two', title={second_title!r}, summary='demo')",
                "    def validate(self, context):",
                "        return []",
                "    def requirements_for(self, parameters):",
                "        return ToolRequirements()",
                "    def run(self, context):",
                "        return ToolRunResult.success('two')",
                "TOOLS = [FirstTool(), SecondTool()]",
            ]
        ),
        encoding="utf-8",
    )
    os.utime(path, None)


def _write_class_only_constructor_plugin(
    path: Path,
    *,
    marker: Path,
    constructor_lines: list[str],
) -> None:
    path.write_text(
        "\n".join(
            [
                "import sys",
                "from pathlib import Path",
                "from types import ModuleType",
                "from app.core.tools.contracts import ToolManifest, ToolRequirements, ToolRunResult",
                f"Path({str(marker)!r}).write_text(__name__, encoding='utf-8')",
                "class ConstructorOwnedTool:",
                "    manifest = ToolManifest(id='external.constructor', title='Constructor', summary='demo')",
                "    def __init__(self):",
                *(f"        {line}" for line in constructor_lines),
                "    def validate(self, context):",
                "        return []",
                "    def requirements_for(self, parameters):",
                "        return ToolRequirements()",
                "    def run(self, context):",
                "        return ToolRunResult.success('ok')",
            ]
        ),
        encoding="utf-8",
    )
    os.utime(path, None)


def _external_registry(
    tmp_path: Path,
    *,
    owner_id: str,
    tools: list[ToolPlugin] | None = None,
) -> ToolRegistry:
    return ToolRegistry(
        tools=list(tools or ()),
        external_dir=tmp_path,
        include_builtins=False,
        include_entry_points=False,
        enable_external=True,
        execution_profile=local_execution_profile(
            host_surface="test",
            owner_id=owner_id,
            approved_roots=(tmp_path,),
            tool_permissions=(),
            allow_external_plugins=True,
        ),
    )


def _new_external_modules(before: set[str]) -> set[str]:
    return {
        name
        for name in set(sys.modules) - before
        if name.startswith("ucrawl_external_tool_")
    }


class _ExplicitTool:
    def __init__(self, tool_id: str, title: str) -> None:
        self.manifest = ToolManifest(id=tool_id, title=title, summary="demo")

    def validate(self, context):
        return []

    def requirements_for(self, parameters):
        return ToolRequirements()

    def run(self, context):
        raise AssertionError


def test_external_tool_directory_hot_reloads_changes_and_removals(tmp_path: Path) -> None:
    plugin = tmp_path / "demo_tool.py"
    _write_external_tool(plugin, "First")
    registry = _external_registry(tmp_path, owner_id="test:registry")

    assert registry.get("external.demo").manifest.title == "First"

    _write_external_tool(plugin, "Second")
    second = registry.reload_external(force=True)
    assert second.updated == ("external.demo",)
    assert registry.get("external.demo").manifest.title == "Second"

    plugin.unlink()
    third = registry.reload_external(force=True)
    assert third.removed == ("external.demo",)
    assert registry.get("external.demo") is None


def test_external_reload_keeps_only_the_current_owned_module(tmp_path: Path) -> None:
    plugin = tmp_path / "owned_versions_tool.py"
    _write_external_tool(plugin, "Version 0")
    registry = _external_registry(tmp_path, owner_id="test:registry-modules")

    loaded_names = [registry.get("external.demo").__class__.__module__]
    for version in range(1, 6):
        _write_external_tool(plugin, f"Version {version}{'x' * version}")

        result = registry.reload_external(force=True)

        assert result.updated == ("external.demo",)
        current = registry.get("external.demo")
        assert current is not None
        current_name = current.__class__.__module__
        assert sys.modules.get(current_name) is not None
        assert all(name not in sys.modules for name in loaded_names)
        loaded_names.append(current_name)

    plugin.unlink()
    registry.reload_external(force=True)


def test_external_reload_deduplicates_paths_before_loading_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-deduplicate-paths",
    )
    plugin = tmp_path / "aliased_source_tool.py"
    _write_external_tool(plugin, "One source")
    original_glob = Path.glob

    def duplicate_glob(path: Path, pattern: str):
        discovered = list(original_glob(path, pattern))
        if path == tmp_path:
            return iter((*discovered, *discovered))
        return iter(discovered)

    monkeypatch.setattr(Path, "glob", duplicate_glob)
    before = set(sys.modules)

    result = registry.reload_external(force=True)

    assert result.added == ("external.demo",)
    tool = registry.get("external.demo")
    assert tool is not None
    module_name = tool.__class__.__module__
    assert _new_external_modules(before) == {module_name}

    plugin.unlink()
    registry.reload_external(force=True)


@pytest.mark.parametrize(
    ("receiver_name", "releaser_name"),
    [
        ("a_receiver.py", "b_releaser.py"),
        ("b_receiver.py", "a_releaser.py"),
    ],
)
def test_cross_file_tool_id_migration_converges_in_one_reload_regardless_of_order(
    tmp_path: Path,
    receiver_name: str,
    releaser_name: str,
) -> None:
    receiver = tmp_path / receiver_name
    releaser = tmp_path / releaser_name
    _write_external_tool_with_id(receiver, "external.receiver", "Old receiver")
    _write_external_tool_with_id(releaser, "external.moved", "Old owner")
    registry = _external_registry(tmp_path, owner_id="test:registry-id-migration")
    _write_external_tool_with_id(receiver, "external.moved", "New owner")
    _write_external_tool_with_id(releaser, "external.releaser", "Released owner")

    result = registry.reload_external(force=True)

    assert result.errors == ()
    assert result.added == ("external.releaser",)
    assert result.updated == ("external.moved",)
    assert result.removed == ("external.receiver",)
    assert registry.get("external.receiver") is None
    assert registry.get("external.moved").manifest.title == "New owner"
    assert registry.get("external.releaser").manifest.title == "Released owner"

    receiver.unlink()
    releaser.unlink()
    registry.reload_external(force=True)


def test_duplicate_final_declarations_fail_closed_and_keep_previous_sources(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "a_duplicate_candidate.py"
    second_path = tmp_path / "b_duplicate_candidate.py"
    _write_external_tool_with_id(first_path, "external.one", "Old one")
    _write_external_tool_with_id(second_path, "external.two", "Old two")
    registry = _external_registry(tmp_path, owner_id="test:registry-duplicate-graph")
    first = registry.get("external.one")
    second = registry.get("external.two")
    assert first is not None
    assert second is not None
    before = set(sys.modules)
    _write_external_tool_with_id(first_path, "external.duplicate", "Duplicate one")
    _write_external_tool_with_id(second_path, "external.duplicate", "Duplicate two")

    result = registry.reload_external(force=True)

    assert any(
        "declared by multiple external sources" in error for error in result.errors
    )
    assert registry.get("external.one") is first
    assert registry.get("external.two") is second
    assert registry.get("external.duplicate") is None
    assert _new_external_modules(before) == set()

    first_path.unlink()
    second_path.unlink()
    registry.reload_external(force=True)


def test_failed_source_fallback_rejects_conflicts_to_a_fixed_point(
    tmp_path: Path,
) -> None:
    failed_path = tmp_path / "a_failed.py"
    first_path = tmp_path / "b_first_candidate.py"
    second_path = tmp_path / "c_second_candidate.py"
    _write_external_tool_with_id(failed_path, "external.one", "Old one")
    _write_external_tool_with_id(first_path, "external.two", "Old two")
    _write_external_tool_with_id(second_path, "external.three", "Old three")
    registry = _external_registry(tmp_path, owner_id="test:registry-fallback-closure")
    previous = {
        tool_id: registry.get(tool_id)
        for tool_id in ("external.one", "external.two", "external.three")
    }
    failed_path.write_text("raise RuntimeError('broken source')\n", encoding="utf-8")
    _write_external_tool_with_id(first_path, "external.one", "Claims one")
    _write_external_tool_with_id(second_path, "external.two", "Claims two")
    before = set(sys.modules)

    result = registry.reload_external(force=True)

    assert len(result.errors) == 3
    assert any("broken source" in error for error in result.errors)
    assert registry.get("external.one") is previous["external.one"]
    assert registry.get("external.two") is previous["external.two"]
    assert registry.get("external.three") is previous["external.three"]
    assert _new_external_modules(before) == set()

    failed_path.unlink()
    first_path.unlink()
    second_path.unlink()
    registry.reload_external(force=True)


def test_external_reload_serializes_writers_without_blocking_snapshot_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = tmp_path / "slow_reload_tool.py"
    _write_external_tool(plugin, "Current")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-snapshot-read",
    )
    current = registry.get("external.demo")
    assert current is not None
    _write_external_tool(plugin, "Next version")
    import_started = threading.Event()
    second_reload_invoked = threading.Event()
    second_import_started = threading.Event()
    release_import = threading.Event()
    load_count = 0
    count_lock = threading.Lock()
    original_load = registry_module._load_source_module

    def delayed_load(path: Path, *, module_name: str):
        nonlocal load_count
        with count_lock:
            load_count += 1
            if load_count == 2:
                second_import_started.set()
        import_started.set()
        if not release_import.wait(timeout=5):
            raise TimeoutError("test did not release external import")
        return original_load(path, module_name=module_name)

    def read_snapshot():
        return (
            registry.get("external.demo"),
            registry.list(),
            registry.manifests(),
        )

    def run_second_reload():
        second_reload_invoked.set()
        return registry.reload_external(force=True)

    monkeypatch.setattr(registry_module, "_load_source_module", delayed_load)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first_reload = pool.submit(registry.reload_external, force=True)
        assert import_started.wait(timeout=2)
        second_reload = pool.submit(run_second_reload)
        assert second_reload_invoked.wait(timeout=2)
        assert not second_import_started.wait(timeout=0.2)
        read_future = pool.submit(read_snapshot)
        try:
            observed = read_future.result(timeout=2)
        except FutureTimeoutError:
            pytest.fail("external reload blocked reads of the previous snapshot")
        finally:
            release_import.set()

        assert observed[0] is current
        assert observed[1] == [current]
        assert observed[2][0]["title"] == "Current"
        assert first_reload.result(timeout=5).updated == ("external.demo",)
        assert second_reload.result(timeout=5).updated == ("external.demo",)

    plugin.unlink()
    registry.reload_external(force=True)


def test_unregister_during_reload_is_not_resurrected_by_staged_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = tmp_path / "interleaved_unregister_tool.py"
    _write_external_tool_bundle(plugin, "Current one", "Current two")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-interleaved-unregister",
    )
    second = registry.get("external.two")
    assert second is not None
    current_module_name = second.__class__.__module__
    _write_external_tool_bundle(plugin, "Next one", "Next two")
    import_started = threading.Event()
    release_import = threading.Event()
    original_load = registry_module._load_source_module

    def delayed_load(path: Path, *, module_name: str):
        import_started.set()
        if not release_import.wait(timeout=5):
            raise TimeoutError("test did not release external import")
        return original_load(path, module_name=module_name)

    monkeypatch.setattr(registry_module, "_load_source_module", delayed_load)
    before = set(sys.modules)
    with ThreadPoolExecutor(max_workers=1) as pool:
        reload_future = pool.submit(registry.reload_external, force=True)
        assert import_started.wait(timeout=2)

        assert registry.unregister("external.one") is True
        assert registry.get("external.one") is None
        assert registry.get("external.two") is second
        release_import.set()
        result = reload_future.result(timeout=5)

    assert any("changed during external reload" in error for error in result.errors)
    assert registry.get("external.one") is None
    assert registry.get("external.two") is second
    assert sys.modules.get(current_module_name) is not None
    assert _new_external_modules(before) == set()

    plugin.unlink()
    registry.unregister("external.two")


def test_external_reload_removes_module_when_source_is_deleted(tmp_path: Path) -> None:
    plugin = tmp_path / "deleted_source_tool.py"
    _write_external_tool(plugin, "Delete me")
    registry = _external_registry(tmp_path, owner_id="test:registry-delete")
    tool = registry.get("external.demo")
    assert tool is not None
    module_name = tool.__class__.__module__

    plugin.unlink()
    result = registry.reload_external(force=True)

    assert result.removed == ("external.demo",)
    assert module_name not in sys.modules


def test_external_module_removal_uses_stable_key_after_module_renames_itself(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "renamed_module_tool.py"
    _write_external_tool(plugin, "Renamed module")
    with plugin.open("a", encoding="utf-8") as source:
        source.write("\n__name__ = 'plugin_mutated_name'\n")
    before = set(sys.modules)
    registry = _external_registry(tmp_path, owner_id="test:registry-stable-key")
    generated_names = _new_external_modules(before)
    assert len(generated_names) == 1

    plugin.unlink()
    registry.reload_external(force=True)

    assert generated_names.isdisjoint(sys.modules)


def test_failed_reload_cleans_generated_key_after_module_name_mutation(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "failed_renamed_module_tool.py"
    _write_external_tool(plugin, "Working")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-failed-stable-key",
    )
    working = registry.get("external.demo")
    assert working is not None
    plugin.write_text(
        "__name__ = 'failed_plugin_mutated_name'\nraise RuntimeError('broken')\n",
        encoding="utf-8",
    )
    before = set(sys.modules)

    result = registry.reload_external(force=True)

    assert result.errors
    assert registry.get("external.demo") is working
    assert _new_external_modules(before) == set()

    plugin.unlink()
    registry.reload_external(force=True)


def test_unhashable_module_name_does_not_mask_base_exception_or_leak(
    tmp_path: Path,
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-unhashable-module-name",
    )
    plugin = tmp_path / "unhashable_module_name.py"
    plugin.write_text(
        "__name__ = []\nraise KeyboardInterrupt('primary interrupt')\n",
        encoding="utf-8",
    )
    before = set(sys.modules)

    with pytest.raises(KeyboardInterrupt, match="primary interrupt"):
        registry.reload_external(force=True)

    assert _new_external_modules(before) == set()


def test_unhashable_module_object_does_not_break_commit_or_cleanup(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "unhashable_module_object.py"
    _write_external_tool(plugin, "Unhashable module")
    with plugin.open("a", encoding="utf-8") as source:
        source.write(
            "\nimport sys\n"
            "from types import ModuleType\n"
            "class UnhashableModule(ModuleType):\n"
            "    __hash__ = None\n"
            "sys.modules[__name__].__class__ = UnhashableModule\n"
        )
    before = set(sys.modules)

    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-unhashable-module-object",
    )

    assert registry.get("external.demo") is not None
    plugin.unlink()
    assert registry.reload_external(force=True).removed == ("external.demo",)
    assert _new_external_modules(before) == set()


def test_external_reload_rejects_module_without_valid_tools_without_leaking(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "empty_external_module.py"
    plugin.write_text("VALUE = 1\n", encoding="utf-8")
    before = set(sys.modules)
    registry = _external_registry(tmp_path, owner_id="test:registry-empty")

    result = registry.reload_external(force=True)

    assert result.errors
    assert registry.list() == []
    assert _new_external_modules(before) == set()


def test_external_reload_cleans_module_rejected_by_registered_tool_conflict(
    tmp_path: Path,
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-conflict",
        tools=[_ExplicitTool("external.demo", "Explicit")],
    )
    plugin = tmp_path / "conflicting_external_tool.py"
    _write_external_tool(plugin, "Conflicting")
    before = set(sys.modules)

    result = registry.reload_external(force=True)

    assert any("conflicts with explicit" in error for error in result.errors)
    assert registry.get("external.demo").manifest.title == "Explicit"
    assert _new_external_modules(before) == set()


def test_external_reload_does_not_restore_source_over_explicit_replacement(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "host_replaced_external_tool.py"
    _write_external_tool(plugin, "External")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-host-replacement",
    )
    external = registry.get("external.demo")
    assert external is not None
    external_module_name = external.__class__.__module__
    registry.register(_ExplicitTool("external.demo", "Host"), replace=True)

    assert registry.get("external.demo").manifest.title == "Host"
    assert registry.descriptor("external.demo").provenance == "explicit"
    assert external_module_name not in sys.modules

    result = registry.reload_external(force=True)

    assert any("conflicts with explicit" in error for error in result.errors)
    assert registry.get("external.demo").manifest.title == "Host"
    assert registry.descriptor("external.demo").provenance == "explicit"
    assert external_module_name not in sys.modules


def test_unregister_external_tool_removes_owned_module_immediately(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "unregistered_external_tool.py"
    _write_external_tool(plugin, "External")
    registry = _external_registry(tmp_path, owner_id="test:registry-unregister")
    external = registry.get("external.demo")
    assert external is not None
    module_name = external.__class__.__module__

    assert registry.unregister("external.demo") is True

    assert registry.descriptor("external.demo") is None
    assert module_name not in sys.modules
    plugin.unlink()
    assert registry.reload_external(force=True).removed == ()


def test_unregister_keeps_module_until_last_tool_from_source_is_removed(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "multi_unregister_tool.py"
    _write_external_tool_bundle(plugin, "One", "Two")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-multi-unregister",
    )
    first = registry.get("external.one")
    second = registry.get("external.two")
    assert first is not None
    assert second is not None
    module_name = first.__class__.__module__
    assert second.__class__.__module__ == module_name

    assert registry.unregister("external.one") is True

    assert registry.get("external.one") is None
    assert registry.get("external.two") is second
    assert sys.modules.get(module_name) is not None

    assert registry.unregister("external.two") is True
    assert module_name not in sys.modules


def test_host_replacement_keeps_other_tools_owned_by_the_same_module(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "multi_replace_tool.py"
    _write_external_tool_bundle(plugin, "One", "Two")
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-multi-replace",
    )
    second = registry.get("external.two")
    assert second is not None
    module_name = second.__class__.__module__

    registry.register(_ExplicitTool("external.one", "Host one"), replace=True)

    assert registry.descriptor("external.one").provenance == "explicit"
    assert registry.get("external.two") is second
    assert sys.modules.get(module_name) is not None

    result = registry.reload_external(force=True)

    assert any("external.one: conflicts with explicit" in error for error in result.errors)
    assert registry.get("external.one").manifest.title == "Host one"
    assert registry.get("external.two") is second
    assert sys.modules.get(module_name) is not None

    plugin.unlink()
    registry.reload_external(force=True)


def test_failed_external_update_preserves_last_working_tool_and_module(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "atomic_update_tool.py"
    _write_external_tool(plugin, "Working")
    before = set(sys.modules)
    registry = _external_registry(tmp_path, owner_id="test:registry-atomic")
    working = registry.get("external.demo")
    assert working is not None
    working_module_name = working.__class__.__module__
    working_module = sys.modules[working_module_name]

    plugin.write_text("raise RuntimeError('broken update')\n", encoding="utf-8")
    failed = registry.reload_external(force=True)

    assert failed.errors
    assert failed.updated == ()
    assert failed.removed == ()
    assert registry.get("external.demo") is working
    assert sys.modules.get(working_module_name) is working_module
    assert _new_external_modules(before) == {working_module_name}

    _write_external_tool(plugin, "Recovered version")
    recovered = registry.reload_external(force=True)

    assert recovered.updated == ("external.demo",)
    assert registry.get("external.demo").manifest.title == "Recovered version"
    assert working_module_name not in sys.modules

    plugin.unlink()
    registry.reload_external(force=True)


def test_failed_import_does_not_delete_replacement_module_with_the_same_name(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "attempted-module-name.txt"
    plugin = tmp_path / "concurrent_replacement_tool.py"
    plugin.write_text(
        "\n".join(
            [
                "import sys",
                "from pathlib import Path",
                "from types import ModuleType",
                f"Path({str(marker)!r}).write_text(__name__, encoding='utf-8')",
                "replacement = ModuleType(__name__)",
                "replacement.concurrent_owner = True",
                "sys.modules[__name__] = replacement",
                "raise RuntimeError('import failed after replacement')",
            ]
        ),
        encoding="utf-8",
    )
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-concurrent-module",
    )
    module_name = marker.read_text(encoding="utf-8")

    try:
        replacement = sys.modules.get(module_name)
        assert replacement is not None
        assert getattr(replacement, "concurrent_owner", False) is True
        assert registry.list() == []
    finally:
        sys.modules.pop(module_name, None)


def test_class_only_constructor_module_hijack_is_rejected_without_foreign_cleanup(
    tmp_path: Path,
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-constructor-module-hijack",
    )
    marker = tmp_path / "constructor-module-name.txt"
    plugin = tmp_path / "constructor_module_hijack.py"
    _write_class_only_constructor_plugin(
        plugin,
        marker=marker,
        constructor_lines=[
            "replacement = ModuleType(__name__)",
            "replacement.concurrent_owner = True",
            "sys.modules[__name__] = replacement",
        ],
    )
    before = set(sys.modules)

    result = registry.reload_external(force=True)
    module_name = marker.read_text(encoding="utf-8")
    replacement = sys.modules.get(module_name)

    try:
        assert result.added == ()
        assert any("ownership changed during discovery" in error for error in result.errors)
        assert registry.get("external.constructor") is None
        assert replacement is not None
        assert getattr(replacement, "concurrent_owner", False) is True

        plugin.unlink()
        assert registry.reload_external(force=True).removed == ()
        assert sys.modules.get(module_name) is replacement
        assert _new_external_modules(before) == {module_name}
    finally:
        sys.modules.pop(module_name, None)

    assert _new_external_modules(before) == set()


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_constructor_hijack_preserves_base_exception_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[BaseException],
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id=f"test:registry-constructor-{exception_type.__name__}",
    )
    primary = exception_type("primary constructor interruption")
    helper_name = f"_ucrawl_registry_primary_{id(primary):x}"
    helper = registry_module.ModuleType(helper_name)
    helper.primary = primary
    monkeypatch.setitem(sys.modules, helper_name, helper)
    marker = tmp_path / f"{exception_type.__name__}-module-name.txt"
    plugin = tmp_path / f"constructor_{exception_type.__name__.lower()}.py"
    _write_class_only_constructor_plugin(
        plugin,
        marker=marker,
        constructor_lines=[
            f"from {helper_name} import primary",
            "replacement = ModuleType(__name__)",
            "replacement.concurrent_owner = True",
            "sys.modules[__name__] = replacement",
            "raise primary",
        ],
    )

    def fail_cleanup(module_key: str, module: registry_module.ModuleType) -> None:
        assert sys.modules.get(module_key) is not module
        raise RuntimeError("secondary cleanup failure")

    monkeypatch.setattr(registry_module, "_remove_module_if_owned", fail_cleanup)

    captured: BaseException | None = None
    try:
        result = registry.reload_external(force=True)
    except BaseException as raised:
        captured = raised
    else:
        pytest.fail(f"primary exception was swallowed: {result.errors!r}")

    module_name = marker.read_text(encoding="utf-8")
    try:
        assert captured is primary
        replacement = sys.modules.get(module_name)
        assert replacement is not None
        assert getattr(replacement, "concurrent_owner", False) is True
        assert registry.get("external.constructor") is None
    finally:
        sys.modules.pop(module_name, None)


def test_plugin_reload_reentry_fails_without_deadlock_or_snapshot_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = tmp_path / "reentrant_reload_tool.py"
    _write_external_tool(plugin, "Working")
    registry = _external_registry(tmp_path, owner_id="test:registry-reentry")
    working = registry.get("external.demo")
    assert working is not None
    working_module_name = working.__class__.__module__
    helper_name = f"_ucrawl_registry_reentry_{id(registry):x}"
    helper = registry_module.ModuleType(helper_name)
    helper.registry = registry
    helper.nested_results = []
    monkeypatch.setitem(sys.modules, helper_name, helper)
    plugin.write_text(
        "\n".join(
            [
                f"from {helper_name} import registry, nested_results",
                "nested_results.append(registry.reload_external(force=True))",
                "raise RuntimeError('outer reload rejected')",
            ]
        ),
        encoding="utf-8",
    )
    before = set(sys.modules)
    outcomes = []

    def run_reload() -> None:
        outcomes.append(registry.reload_external(force=True))

    reload_thread = threading.Thread(target=run_reload, daemon=True)
    reload_thread.start()
    reload_thread.join(timeout=2)

    assert not reload_thread.is_alive(), "plugin reload reentry deadlocked"
    assert len(helper.nested_results) == 1
    assert any("not reentrant" in error for error in helper.nested_results[0].errors)
    assert len(outcomes) == 1
    assert outcomes[0].errors
    assert registry.get("external.demo") is working
    assert sys.modules.get(working_module_name) is not None
    assert _new_external_modules(before) == set()

    plugin.unlink()
    registry.reload_external(force=True)


def test_base_exception_during_reload_cleans_all_uncommitted_modules(
    tmp_path: Path,
) -> None:
    registry = _external_registry(
        tmp_path,
        owner_id="test:registry-base-exception",
    )
    _write_external_tool(tmp_path / "a_staged_tool.py", "Staged")
    (tmp_path / "z_interrupt.py").write_text(
        "raise KeyboardInterrupt('stop reload')\n",
        encoding="utf-8",
    )
    before = set(sys.modules)

    with pytest.raises(KeyboardInterrupt, match="stop reload"):
        registry.reload_external(force=True)

    assert registry.list() == []
    assert _new_external_modules(before) == set()


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
