from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEGACY_SHARED_ADAPTERS = (
    "app/controllers/session_mixin.py",
    "app/services/frontend_page_definitions.py",
    "app/ui/components/top_bar.py",
    "app/ui/i18n_catalogs.py",
    "app/ui/localization.py",
    "app/ui/viewmodels/failed_page_projection.py",
    "app/ui/viewmodels/log_classification.py",
    "app/ui/viewmodels/log_detail_payloads.py",
    "app/ui/viewmodels/log_display.py",
    "app/ui/viewmodels/log_i18n.py",
    "app/ui/viewmodels/log_pipeline_rules.py",
    "app/ui/viewmodels/settings_catalog.py",
    "cli/defaults.py",
    "cli/gui_selection.py",
    "cli/interactive.py",
    "cli/pipe.py",
    "cli/runner.py",
    "cli/sdk.py",
    "cli/selection.py",
    "cli/selection_base.py",
)

SHARED_FRONTEND_CONTRACTS = (
    "shared/failed_page_projection.py",
    "shared/frontend_page_definitions.py",
    "shared/i18n_catalogs.py",
    "shared/icon_contract.py",
    "shared/localization.py",
    "shared/log_classification.py",
    "shared/log_contract.py",
    "shared/log_detail_payloads.py",
    "shared/log_display.py",
    "shared/log_i18n.py",
    "shared/log_pipeline_rules.py",
    "shared/log_platforms.py",
    "shared/settings_metadata.py",
)


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> list[str]:
    if node.level <= 0:
        return [node.module or ""]

    relative_parts = path.relative_to(PROJECT_ROOT).with_suffix("").parts
    package_parts = list(relative_parts if path.name == "__init__.py" else relative_parts[:-1])
    parent_hops = node.level - 1
    if parent_hops > len(package_parts):
        return [node.module or ""]
    base_parts = package_parts[: len(package_parts) - parent_hops]
    if node.module:
        return [".".join((*base_parts, *node.module.split(".")))]
    return [".".join((*base_parts, alias.name)) for alias in node.names]


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_resolve_import_from(path, node))
    return imports


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _direct_imports(path: Path) -> set[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        imports.update(
            (node.module, alias.name, alias.asname or alias.name)
            for alias in node.names
        )
    return imports


def _imports_under(root: str, forbidden: str) -> list[tuple[str, str]]:
    root_path = PROJECT_ROOT / root
    if not root_path.exists():
        return []
    violations: list[tuple[str, str]] = []
    for path in sorted(root_path.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for module in _module_imports(path):
            if module == forbidden or module.startswith(f"{forbidden}."):
                violations.append((rel, module))
    return violations


def _unexpected(
    violations: list[tuple[str, str]],
    allowlist: set[tuple[str, str]],
) -> list[tuple[str, str]]:
    return [item for item in violations if item not in allowlist]


class DependencyDirectionArchitectureTests(unittest.TestCase):
    def test_relative_imports_are_resolved_to_absolute_modules(self) -> None:
        path = PROJECT_ROOT / "app" / "ui" / "pages" / "probe.py"
        node = ast.parse("from ...core.downloaders import ChunkedDownloader").body[0]

        self.assertEqual(
            _resolve_import_from(path, node),
            ["app.core.downloaders"],
        )

    def test_web_server_uses_shared_cli_search_adapter(self) -> None:
        path = PROJECT_ROOT / "app" / "web" / "server.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        local_definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertNotIn("run_cli_search", local_definitions)
        self.assertIn("shared.runtime_adapters", _module_imports(path))

    def test_cli_command_contracts_have_one_shared_implementation(self) -> None:
        search_path = PROJECT_ROOT / "cli" / "commands" / "search.py"
        download_path = PROJECT_ROOT / "cli" / "commands" / "download.py"
        scan_path = PROJECT_ROOT / "cli" / "commands" / "scan.py"

        self.assertTrue(
            {"add_search_arguments", "_print_pretty"}.isdisjoint(
                _top_level_definitions(search_path),
            )
        )
        self.assertTrue(
            {"add_download_arguments", "_print_pretty"}.isdisjoint(
                _top_level_definitions(download_path),
            )
        )
        self.assertNotIn(
            "add_scan_arguments",
            _top_level_definitions(scan_path),
        )
        self.assertIn(
            ("shared.search_command_runtime", "add_search_arguments", "add_search_arguments"),
            _direct_imports(search_path),
        )
        self.assertIn(
            ("shared.search_command_runtime", "print_pretty", "_print_pretty"),
            _direct_imports(search_path),
        )
        self.assertIn(
            ("shared.download_command_runtime", "add_download_arguments", "add_download_arguments"),
            _direct_imports(download_path),
        )
        self.assertIn(
            ("shared.download_command_runtime", "print_pretty", "_print_pretty"),
            _direct_imports(download_path),
        )
        self.assertIn(
            (
                "shared.scan_command_runtime",
                "add_scan_arguments",
                "add_scan_arguments",
            ),
            _direct_imports(scan_path),
        )
        self.assertLess(len(scan_path.read_text(encoding="utf-8").splitlines()), 55)

    def test_hosts_import_shared_command_and_sdk_contracts_directly(self) -> None:
        main_imports = _direct_imports(PROJECT_ROOT / "cli" / "main.py")
        alias_path = PROJECT_ROOT / "cli" / "commands" / "_alias.py"
        workflow_path = PROJECT_ROOT / "app" / "web" / "workflows.py"

        self.assertIn(
            ("shared.search_command_runtime", "add_search_arguments", "add_search_arguments"),
            main_imports,
        )
        self.assertIn(
            ("shared.download_command_runtime", "add_download_arguments", "add_download_arguments"),
            main_imports,
        )
        self.assertIn(
            ("shared.scan_command_runtime", "add_scan_arguments", "add_scan_arguments"),
            main_imports,
        )
        self.assertFalse(alias_path.exists())
        self.assertNotIn("build_sdk", _top_level_definitions(workflow_path))
        self.assertIn(
            ("shared.runtime_adapters", "build_sdk", "build_sdk"),
            _direct_imports(workflow_path),
        )

    def test_dead_interactive_command_runtime_is_removed(self) -> None:
        self.assertFalse((PROJECT_ROOT / "shared" / "interactive_command_runtime.py").exists())

    def test_web_script_injection_has_no_cli_duplicate(self) -> None:
        self.assertFalse(
            (PROJECT_ROOT / "cli" / "script_runner.py").exists()
        )
        self.assertTrue(
            (PROJECT_ROOT / "app" / "web" / "script_api.py").exists()
        )

    def test_shared_runtime_tests_mirror_their_production_namespace(self) -> None:
        stale = (
            "test_defaults.py",
            "test_pipe.py",
            "test_runner.py",
            "test_sdk.py",
            "test_selection.py",
            "test_script_runner.py",
        )
        remaining = [
            name
            for name in stale
            if (
                PROJECT_ROOT
                / "tests"
                / "unit"
                / "cli"
                / name
            ).exists()
        ]

        self.assertEqual(remaining, [])

    def test_active_cli_runtime_diagram_tracks_current_boundaries(self) -> None:
        diagram = (
            PROJECT_ROOT / "mermaid" / "07-cli-sdk-runtime.md"
        ).read_text(encoding="utf-8")

        self.assertIn("shared.scan_command_runtime", diagram)
        self.assertIn("ucrawl/__init__.py", diagram)
        self.assertIn("plugin manifest", diagram.lower())
        self.assertNotIn("公开再导出 + 历史别名", diagram)
        self.assertNotIn("PackageInit --> SDKRt", diagram)

    def test_active_testing_guide_uses_shared_runtime_test_paths(self) -> None:
        guide = (
            PROJECT_ROOT / "docs" / "guides" / "testing.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "tests/unit/shared/test_sdk_runtime.py",
            guide,
        )
        self.assertIn(
            "tests/unit/shared/test_cli_runner_runtime.py",
            guide,
        )
        self.assertNotIn("tests/unit/cli/test_sdk.py", guide)
        self.assertNotIn("历史模块路径兼容别名", guide)

    def test_ui_does_not_import_core_downloaders(self) -> None:
        self.assertEqual(_imports_under("app/ui", "app.core.downloaders"), [])

    def test_web_does_not_add_new_gui_dependencies(self) -> None:
        violations = _imports_under("app/web", "app.ui")
        self.assertEqual(violations, [])

    def test_web_does_not_import_controller_mixins(self) -> None:
        self.assertEqual(_imports_under("app/web", "app.controllers"), [])

    def test_services_do_not_add_new_presentation_dependencies(self) -> None:
        ui_violations = _imports_under("app/services", "app.ui")
        web_violations = _imports_under("app/services", "app.web")

        self.assertEqual(ui_violations, [])
        self.assertEqual(web_violations, [])

    def test_shared_does_not_depend_on_application_layers(self) -> None:
        violations: list[tuple[str, str]] = []
        missing: list[str] = []
        for relative_path in SHARED_FRONTEND_CONTRACTS:
            path = PROJECT_ROOT / relative_path
            if not path.exists():
                missing.append(relative_path)
                continue
            for module in _module_imports(path):
                if module == "app" or module.startswith("app.") or module == "cli" or module.startswith("cli."):
                    violations.append((relative_path, module))

        self.assertEqual(missing, [])
        self.assertEqual(violations, [])

    def test_legacy_shared_adapters_are_removed(self) -> None:
        remaining = [path for path in LEGACY_SHARED_ADAPTERS if (PROJECT_ROOT / path).exists()]
        self.assertEqual(remaining, [])

    def test_hosts_import_shared_runtime_implementations_directly(self) -> None:
        forbidden_modules = (
            "cli.defaults",
            "cli.gui_selection",
            "cli.pipe",
            "cli.sdk",
            "cli.selection",
            "cli.selection_base",
        )
        violations: list[tuple[str, str]] = []
        for root in ("app/web", "cli", "entry", "ucrawl"):
            for forbidden in forbidden_modules:
                violations.extend(_imports_under(root, forbidden))

        for root in ("app/web", "entry", "ucrawl"):
            violations.extend(_imports_under(root, "cli.interactive"))

        self.assertEqual(violations, [])

    def test_spiders_core_imports_stay_in_known_runtime_whitelist(self) -> None:
        allowed_modules = {
            "app.core.events",
            "app.core.anti_detection",
            "app.core.guardrails",
            "app.core.media_filter",
            "app.core.plugins.run_options",
        }
        allowed_prefixes = {
            "app.core.anti_detection.",
            "app.core.guardrails.",
            "app.core.lib.douyin.",
        }
        violations: list[tuple[str, str]] = []
        for path in sorted((PROJECT_ROOT / "app/spiders").rglob("*.py")):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for module in _module_imports(path):
                if not module.startswith("app.core"):
                    continue
                if module in allowed_modules or any(module.startswith(prefix) for prefix in allowed_prefixes):
                    continue
                violations.append((rel, module))

        self.assertEqual(violations, [])

    def test_cli_does_not_add_new_gui_dependencies(self) -> None:
        known_violations = {
            ("cli/__init__.py", "app.ui.gui_selection_strategy"),
        }

        violations = _imports_under("cli", "app.ui")

        self.assertEqual(_unexpected(violations, known_violations), [])


if __name__ == "__main__":
    unittest.main()
