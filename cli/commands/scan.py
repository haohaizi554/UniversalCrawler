"""Thin CLI host for local-directory scanning."""

from __future__ import annotations

import argparse
import sys

from app.config import cfg
from cli.exit_codes import exit_code_for_status
from shared import scan_command_runtime as runtime
from shared.scan_command_runtime import add_scan_arguments
from shared.sdk_runtime import UcrawlSDK

__all__ = ["add_scan_arguments", "handle_scan_command"]


def _default_scan_limit() -> int:
    return cfg.get("download", "local_scan_limit", 1000)


def _runtime_env() -> runtime.ScanCommandEnv:
    return runtime.ScanCommandEnv(
        UcrawlSDK_cls=UcrawlSDK,
        get_default_scan_limit=_default_scan_limit,
    )


def handle_scan_command(args: argparse.Namespace) -> int:
    outcome, result, error = runtime.run_scan_command(
        args,
        env=_runtime_env(),
    )
    if error:
        sys.stderr.write(f"{error}\n")
    if result is not None:
        runtime.emit_result(
            result,
            pretty=getattr(args, "pretty", False),
        )
    return int(exit_code_for_status(outcome))
