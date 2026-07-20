from __future__ import annotations

import ast
from pathlib import Path

from tests.support.paths import PROJECT_ROOT


PRODUCTION_ROOTS = (
    PROJECT_ROOT / "app",
    PROJECT_ROOT / "entry",
    PROJECT_ROOT / "packaging",
)
EXPLICIT_CHROME_HOSTS = (
    PROJECT_ROOT / "tests" / "launcher.py",
)
CHROME_COMPONENT_DEFINITIONS = {
    PROJECT_ROOT / "app" / "ui" / "layout" / "window_chrome.py",
}
REQUIRED_HOST_CONTRACT = (
    "FramelessWindowChromeController(",
    ".bind_title_bar_controls(",
    ".install(",
    ".on_show_event(",
    ".uninstall(",
    ".handle_native_event(",
    ".mouse_press_event(",
    ".event_filter(",
)
FORBIDDEN_DIRECT_CONNECTIONS = (
    "minimize_requested.connect",
    "maximize_restore_requested.connect",
    "close_requested.connect",
)


def _production_python_files() -> list[Path]:
    paths = [
        path
        for root in PRODUCTION_ROOTS
        for path in root.rglob("*.py")
    ]
    paths.extend(EXPLICIT_CHROME_HOSTS)
    return sorted(dict.fromkeys(paths))


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def test_every_shared_chrome_host_uses_the_complete_controller_contract() -> None:
    violations: dict[str, list[str]] = {}
    hosts = []
    for path in _production_python_files():
        if path in CHROME_COMPONENT_DEFINITIONS:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "WindowChromeFrame(" not in source:
            continue
        hosts.append(_relative(path))
        missing = [
            contract
            for contract in REQUIRED_HOST_CONTRACT
            if contract not in source
        ]
        if missing:
            violations[_relative(path)] = missing

    assert hosts, "no shared window chrome hosts were discovered"
    assert violations == {}, (
        "Every top-level WindowChromeFrame host must delegate title-bar actions, "
        f"native events, and lifecycle cleanup to the shared controller: {violations}"
    )


def test_window_hosts_do_not_bind_shared_title_bar_actions_directly() -> None:
    violations: dict[str, list[str]] = {}
    for path in _production_python_files():
        if path.name == "window_chrome_controller.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        direct_connections = [
            marker
            for marker in FORBIDDEN_DIRECT_CONNECTIONS
            if marker in source
        ]
        if direct_connections:
            violations[_relative(path)] = direct_connections

    assert violations == {}, (
        "Top-level windows must call bind_title_bar_controls(); direct signal "
        f"connections bypass native maximize truth and are forbidden: {violations}"
    )


def test_application_code_does_not_construct_bare_qdialogs() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(
            path.read_text(encoding="utf-8-sig"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "QDialog":
                violations.append(f"{_relative(path)}:{node.lineno}")

    assert violations == [], (
        "Application-owned dialogs must inherit ChromedDialog so current and "
        f"future windows share the same chrome contract: {violations}"
    )
