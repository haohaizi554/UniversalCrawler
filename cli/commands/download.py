"""CLI host wiring for the shared direct-download command runtime."""

from __future__ import annotations

import argparse
import sys

from app.core.plugin_registry import registry
from shared import download_command_runtime as runtime
from shared.download_command_runtime import (
    add_download_arguments,
    print_pretty as _print_pretty,
)
from shared.runtime_options import (
    build_missav_proxy_url,
    get_default_save_dir,
    validate_config_types,
)
from shared.sdk_runtime import UcrawlSDK

__all__ = ["_print_pretty", "add_download_arguments", "handle_download_command"]


def _runtime_env() -> runtime.DownloadCommandEnv:
    """Bind host dependencies without duplicating shared command behavior."""
    return runtime.DownloadCommandEnv(
        UcrawlSDK_cls=UcrawlSDK,
        get_default_save_dir=get_default_save_dir,
        build_missav_proxy_url=build_missav_proxy_url,
        validate_config_types=validate_config_types,
        get_plugin=registry.get_plugin,
        list_platform_ids=lambda: [plugin.id for plugin in registry.get_all_plugins()],
    )


def _build_config(
    args: argparse.Namespace,
    *,
    source: str,
) -> tuple[dict | None, str | None]:
    """Build platform configuration through the shared runtime."""
    return runtime.build_config(args, source=source, env=_runtime_env())


def handle_download_command(args: argparse.Namespace) -> int:
    """Execute the shared download workflow with CLI host dependencies."""
    exit_code, result, error_message = runtime.run_download_command(
        args,
        env=_runtime_env(),
    )
    if error_message:
        sys.stderr.write(f"{error_message}\n")
    if result is not None:
        runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return exit_code
