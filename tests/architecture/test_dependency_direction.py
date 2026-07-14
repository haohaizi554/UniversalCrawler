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
            "cli.interactive",
            "cli.pipe",
            "cli.sdk",
            "cli.selection",
            "cli.selection_base",
        )
        violations: list[tuple[str, str]] = []
        for root in ("app/web", "cli", "entry", "ucrawl"):
            for forbidden in forbidden_modules:
                violations.extend(_imports_under(root, forbidden))

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
