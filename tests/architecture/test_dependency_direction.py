from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
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
    def test_ui_does_not_import_core_downloaders(self) -> None:
        self.assertEqual(_imports_under("app/ui", "app.core.downloaders"), [])

    def test_web_does_not_add_new_gui_dependencies(self) -> None:
        known_violations = {
            ("app/web/rest_router.py", "app.ui.localization"),
            ("app/web/server.py", "app.ui.localization"),
        }

        violations = _imports_under("app/web", "app.ui")

        self.assertEqual(_unexpected(violations, known_violations), [])

    def test_services_do_not_add_new_presentation_dependencies(self) -> None:
        known_ui_violations = {
            ("app/services/frontend_log_adapter.py", "app.ui.viewmodels.log_display"),
            ("app/services/frontend_log_adapter.py", "app.ui.viewmodels.log_platforms"),
            ("app/services/frontend_state_service.py", "app.ui.viewmodels.settings_catalog"),
        }

        ui_violations = _imports_under("app/services", "app.ui")
        web_violations = _imports_under("app/services", "app.web")

        self.assertEqual(_unexpected(ui_violations, known_ui_violations), [])
        self.assertEqual(web_violations, [])

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
            ("cli/gui_selection.py", "app.ui.gui_selection_strategy"),
        }

        violations = _imports_under("cli", "app.ui")

        self.assertEqual(_unexpected(violations, known_violations), [])


if __name__ == "__main__":
    unittest.main()
