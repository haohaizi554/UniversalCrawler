"""CLI、SDK 与 GUI 必须保持单向、无副作用的公共包边界。"""

from __future__ import annotations

import subprocess
import sys

import cli
import ucrawl


def test_cli_package_only_exposes_version() -> None:
    assert cli.__all__ == ["__version__"]
    assert not hasattr(cli, "GUISelection")
    assert not hasattr(cli, "UcrawlSDK")


def test_sdk_package_does_not_expose_gui_selection() -> None:
    assert not hasattr(ucrawl, "GUISelection")
    assert hasattr(ucrawl, "UcrawlSDK")


def test_fresh_cli_and_sdk_imports_do_not_load_app_ui() -> None:
    probe = (
        "import sys; import cli; import ucrawl; "
        "assert not any("
        "name == 'app.ui' or name.startswith('app.ui.') "
        "for name in sys.modules"
        ")"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
