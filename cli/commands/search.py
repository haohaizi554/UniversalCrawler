"""CLI host wiring for the shared search command runtime."""

from __future__ import annotations

import argparse

from shared import search_command_runtime as runtime
from shared.cli_runner_runtime import CLIRunner
from shared.runtime_options import (
    build_missav_proxy_url,
    get_default_save_dir,
    get_platform_defaults,
    validate_config_types,
)
from shared.search_command_runtime import (
    add_search_arguments,
    print_pretty as _print_pretty,
)
from shared.selection_runtime import SelectionStrategyFactory

__all__ = ["_print_pretty", "add_search_arguments", "handle_search_command"]


def _runner_class():
    """Return the shared runner through this command-local test seam."""
    return CLIRunner


def _runtime_env() -> runtime.SearchCommandEnv:
    """Bind host dependencies without duplicating shared command behavior."""
    return runtime.SearchCommandEnv(
        CLIRunner_cls=_runner_class(),
        selection_factory=SelectionStrategyFactory,
        get_platform_defaults=get_platform_defaults,
        get_default_save_dir=get_default_save_dir,
        build_missav_proxy_url=build_missav_proxy_url,
        validate_config_types=validate_config_types,
    )


def _build_selection_strategy(args: argparse.Namespace):
    """Build a selection strategy through the shared runtime."""
    return runtime.build_selection_strategy(args, env=_runtime_env())


def _build_config(args: argparse.Namespace) -> dict:
    """Build platform configuration through the shared runtime."""
    return runtime.build_config(args, env=_runtime_env())


def handle_search_command(args: argparse.Namespace) -> int:
    """Execute the shared search workflow with CLI host dependencies."""
    exit_code, result = runtime.run_search_command(args, env=_runtime_env())
    runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return exit_code
