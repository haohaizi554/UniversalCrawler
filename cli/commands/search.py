"""装配 CLI 宿主与共享搜索运行时。"""

from __future__ import annotations

import argparse

from cli.exit_codes import exit_code_for_status
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
    """通过命令模块内的测试接缝返回共享执行器。"""
    return CLIRunner


def _runtime_env() -> runtime.SearchCommandEnv:
    """显式装配宿主依赖，避免命令层复制共享行为。"""
    return runtime.SearchCommandEnv(
        CLIRunner_cls=_runner_class(),
        selection_factory=SelectionStrategyFactory,
        get_platform_defaults=get_platform_defaults,
        get_default_save_dir=get_default_save_dir,
        build_missav_proxy_url=build_missav_proxy_url,
        validate_config_types=validate_config_types,
    )


def _build_selection_strategy(args: argparse.Namespace):
    return runtime.build_selection_strategy(args, env=_runtime_env())


def _build_config(args: argparse.Namespace) -> dict:
    return runtime.build_config(args, env=_runtime_env())


def handle_search_command(args: argparse.Namespace) -> int:
    outcome, result = runtime.run_search_command(args, env=_runtime_env())
    runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return int(exit_code_for_status(outcome))
