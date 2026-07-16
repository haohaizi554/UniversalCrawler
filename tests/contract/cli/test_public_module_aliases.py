from __future__ import annotations

import importlib
import subprocess
import sys

import cli
from app.ui.gui_selection_strategy import GUISelection
from shared.cli_runner_runtime import CLIRunner
from shared.interactive_selection import InteractiveTTYSelection
from shared.pipe_selection import PipeSelection
from shared.runtime_options import get_platform_defaults
from shared.sdk_runtime import UcrawlSDK
from shared.selection_base import SelectionStrategy
from shared.selection_runtime import RuleSelection


def test_legacy_cli_module_paths_resolve_to_canonical_implementations() -> None:
    assert importlib.import_module("cli.sdk").UcrawlSDK is UcrawlSDK
    assert importlib.import_module("cli.defaults").get_platform_defaults is get_platform_defaults
    assert importlib.import_module("cli.runner").CLIRunner is CLIRunner
    assert importlib.import_module("cli.pipe").PipeSelection is PipeSelection
    assert importlib.import_module("cli.interactive").InteractiveTTYSelection is InteractiveTTYSelection
    assert importlib.import_module("cli.gui_selection").GUISelection is GUISelection
    assert importlib.import_module("cli.selection").RuleSelection is RuleSelection
    assert importlib.import_module("cli.selection_base").SelectionStrategy is SelectionStrategy


def test_top_level_cli_exports_remain_identical_to_shared_contracts() -> None:
    assert cli.UcrawlSDK is UcrawlSDK
    assert cli.CLIRunner is CLIRunner
    assert cli.RuleSelection is RuleSelection
    assert cli.PipeSelection is PipeSelection


def test_legacy_module_path_imports_in_a_fresh_interpreter() -> None:
    probe = (
        "from cli.sdk import UcrawlSDK; "
        "from cli.defaults import get_platform_defaults; "
        "from cli.runner import CLIRunner; "
        "assert UcrawlSDK.__module__ == 'shared.sdk_runtime'; "
        "assert get_platform_defaults.__module__ == 'shared.runtime_options'; "
        "assert CLIRunner.__module__ == 'shared.cli_runner_runtime'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
