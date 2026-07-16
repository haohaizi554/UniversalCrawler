"""Architecture contract for the canonical test-suite taxonomy."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

import pytest


pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
CANONICAL_SUITES = frozenset(
    {
        "unit",
        "integration",
        "contract",
        "e2e",
        "architecture",
        "performance",
        "release",
        "testkit",
    }
)
RUNTIME_MARKERS = frozenset(
    {
        "architecture",
        "benchmark",
        "browser",
        "gui",
        "network",
        "security",
        "serial",
        "slow",
        "windows",
    }
)
FORBIDDEN_TEST_NAMES = frozenset(
    {
        "test_case_1",
        "test_fix",
        "test_fix_bug",
        "test_logic",
        "test_misc",
        "test_new",
        "test_works",
    }
)


def _collected_test_modules() -> list[Path]:
    return sorted(path for path in TESTS_ROOT.rglob("test_*.py") if path.is_file())


class TestSuiteLayoutArchitecture(unittest.TestCase):
    def test_all_test_modules_live_below_a_canonical_suite_root(self):
        invalid = []
        for path in _collected_test_modules():
            relative = path.relative_to(TESTS_ROOT)
            if len(relative.parts) < 2 or relative.parts[0] not in CANONICAL_SUITES:
                invalid.append(relative.as_posix())

        self.assertEqual(
            invalid,
            [],
            "Every collected test module must live below one canonical suite root",
        )

    def test_support_modules_do_not_use_the_pytest_test_prefix(self):
        support_root = TESTS_ROOT / "support"
        invalid = (
            sorted(path.relative_to(TESTS_ROOT).as_posix() for path in support_root.rglob("test_*.py"))
            if support_root.exists()
            else []
        )
        root_support = [
            name
            for name in ("test_launcher.py", "test_registry.py", "test_runner.py")
            if (TESTS_ROOT / name).exists()
        ]
        self.assertEqual(root_support + invalid, [])

    def test_builtin_catalog_is_root_driven_without_filename_allowlists(self):
        catalog_path = TESTS_ROOT / "support" / "catalog.py"
        self.assertTrue(catalog_path.is_file(), "tests/support/catalog.py must own suite discovery")
        source = catalog_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        suite_roots = None
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id == "BUILTIN_SUITE_ROOTS":
                value = node.value
                suite_roots = ast.literal_eval(value)
                break

        self.assertEqual(set(suite_roots or {}), CANONICAL_SUITES)
        self.assertEqual(
            set((suite_roots or {}).values()),
            {f"tests/{suite}" for suite in CANONICAL_SUITES},
        )

        from tests.support import catalog

        for suite_id, root in catalog.BUILTIN_SUITE_ROOTS.items():
            category = catalog.get_category(suite_id)
            with self.subTest(suite=suite_id):
                self.assertEqual(category.source, "suite")
                self.assertEqual(category.roots, [root])
                self.assertEqual(category.files, [])
                self.assertEqual(category.include, [])
                self.assertEqual(category.exclude, [])

    def test_pytest_runtime_markers_are_registered_and_strict(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        pytest_options = pyproject.split("[tool.pytest.ini_options]", 1)[1].split("\n[", 1)[0]
        marker_names = set(re.findall(r'^\s*"([a-z][a-z0-9_-]*):', pytest_options, re.MULTILINE))
        self.assertRegex(pytest_options, r'addopts\s*=\s*\[[^\]]*"--strict-markers"')
        self.assertEqual(RUNTIME_MARKERS - marker_names, set())

    def test_scoped_agent_contract_preserves_suite_first_rules(self):
        agent_contract = (TESTS_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        naming_contract = (TESTS_ROOT / "NAMING.md").read_text(encoding="utf-8")

        for suite in CANONICAL_SUITES:
            with self.subTest(suite=suite):
                self.assertIn(f"tests/{suite}/", agent_contract)
                self.assertIn(f"tests/{suite}/", naming_contract)

        self.assertIn("Never add an exact file", agent_contract)
        self.assertIn("Built-in suites are directory-driven", agent_contract)
        self.assertIn("内置套件禁止白名单", naming_contract)
        self.assertIn("tests/<suite>/<production namespace>/test_<observable responsibility>.py", naming_contract)

    def test_test_function_names_avoid_ambiguous_placeholders(self):
        invalid: list[str] = []
        for path in _collected_test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FORBIDDEN_TEST_NAMES:
                    invalid.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}:{node.name}")
        self.assertEqual(invalid, [])
