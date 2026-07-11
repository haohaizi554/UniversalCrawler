from __future__ import annotations

import ast
import warnings
from pathlib import Path

from tests.frontend_static_assets import stylesheet_names_from_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"
STATIC_DIR = PROJECT_ROOT / "app" / "web" / "static"

TEST_MODULE_MAX_LINES = 1_500
CSS_MODULE_MAX_LINES = 1_000

BROWSER_CASE_DIR = TESTS_DIR / "web_browser_cases"
TEST_SUPPORT_MODULES = (
    TESTS_DIR / "web_browser_support.py",
    TESTS_DIR / "unified_frontend_contract_support.py",
)
CSS_LOAD_ORDER = (
    "app.css",
    "log_layout.css",
    "task_pages.css",
    "task_runtime.css",
    "media_logs.css",
    "settings.css",
    "overlays_responsive.css",
)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _python_responsibility_modules() -> list[Path]:
    modules = [TESTS_DIR / "test_web_browser.py"]
    modules.extend(path for path in TEST_SUPPORT_MODULES if path.exists())
    if BROWSER_CASE_DIR.exists():
        modules.extend(sorted(BROWSER_CASE_DIR.glob("*.py")))
    modules.extend(sorted(TESTS_DIR.glob("test_unified_frontend*contract.py")))
    return list(dict.fromkeys(modules))


def _test_method_names(path: Path) -> list[str]:
    tree = _parse_python(path)
    return [
        node.name
        for parent in ast.walk(tree)
        if isinstance(parent, ast.ClassDef)
        for node in parent.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]


def _parse_python(path: Path) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def test_frontend_test_modules_stay_within_hard_line_limit() -> None:
    oversized = {
        path.relative_to(PROJECT_ROOT).as_posix(): _line_count(path)
        for path in _python_responsibility_modules()
        if _line_count(path) > TEST_MODULE_MAX_LINES
    }
    assert oversized == {}, f"frontend test responsibility modules exceed {TEST_MODULE_MAX_LINES} lines: {oversized}"


def test_frontend_css_modules_exist_and_stay_within_hard_line_limit() -> None:
    missing = [name for name in CSS_LOAD_ORDER if not (STATIC_DIR / name).is_file()]
    assert missing == [], f"missing responsibility CSS modules: {missing}"

    oversized = {
        name: _line_count(STATIC_DIR / name)
        for name in CSS_LOAD_ORDER
        if _line_count(STATIC_DIR / name) > CSS_MODULE_MAX_LINES
    }
    assert oversized == {}, f"frontend CSS responsibility modules exceed {CSS_MODULE_MAX_LINES} lines: {oversized}"


def test_index_loads_responsibility_css_once_in_contract_order() -> None:
    loaded = list(stylesheet_names_from_index())
    assert loaded == list(CSS_LOAD_ORDER)
    assert all(loaded.count(name) == 1 for name in CSS_LOAD_ORDER)


def test_browser_case_modules_are_non_collectable_mixins() -> None:
    assert BROWSER_CASE_DIR.is_dir(), "browser responsibility case package is missing"
    violations: list[str] = []
    for path in sorted(BROWSER_CASE_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.name.startswith("test_"):
            violations.append(f"{path.name}: filename is collectable")
        tree = _parse_python(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name.startswith("Test"):
                violations.append(f"{path.name}:{node.name}: class name is collectable")
            if any(
                isinstance(base, ast.Attribute) and base.attr == "TestCase"
                or isinstance(base, ast.Name) and base.id == "TestCase"
                for base in node.bases
            ):
                violations.append(f"{path.name}:{node.name}: mixin inherits TestCase")
    assert violations == []


def test_support_modules_do_not_own_tests() -> None:
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in TEST_SUPPORT_MODULES if not path.is_file()]
    assert missing == [], f"missing test support modules: {missing}"
    violations = {
        path.relative_to(PROJECT_ROOT).as_posix(): _test_method_names(path)
        for path in TEST_SUPPORT_MODULES
        if _test_method_names(path)
    }
    assert violations == {}


def test_split_contract_test_methods_are_unique() -> None:
    owners: dict[str, list[str]] = {}
    for path in _python_responsibility_modules():
        for name in _test_method_names(path):
            owners.setdefault(name, []).append(path.name)
    duplicates = {name: paths for name, paths in owners.items() if len(paths) > 1}
    assert duplicates == {}, f"duplicate frontend contract test ownership: {duplicates}"
