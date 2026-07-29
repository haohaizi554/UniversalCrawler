"""platforms 命令：列出所有可用平台。

ucrawl platforms [--json] [--describe <id>]
"""

from __future__ import annotations

import argparse
import json
import sys

from cli.exit_codes import CliExitCode
from shared.sdk_cleanup import (
    attach_sdk_cleanup_failure,
    close_sdk_once,
    is_sdk_cleanup_control_flow,
    write_sdk_cleanup_diagnostic,
    write_text_best_effort,
)
from shared.sdk_runtime import UcrawlSDK

def add_platforms_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--describe", metavar="ID", help="显示指定平台的详细参数")
    # 输出参数（与 scan/search/download 命令的 --quiet/--pretty 对齐）
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出额外信息到 stderr")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式")

def handle_platforms_command(args: argparse.Namespace) -> int:
    # 与 scan 命令 --quiet 对齐：静默模式不输出 SDK 内部日志
    verbose = not getattr(args, "quiet", False)
    sdk = UcrawlSDK(verbose=verbose)
    try:
        platforms = sdk.list_platforms()
        target = None
        exit_code = CliExitCode.OK
        if args.describe:
            target = next(
                (p for p in platforms if p["id"] == args.describe),
                None,
            )
            if not target:
                exit_code = CliExitCode.USAGE
    except BaseException as primary_error:
        cleanup_error = close_sdk_once(sdk)
        if cleanup_error is not None:
            attach_sdk_cleanup_failure(primary_error, cleanup_error)
        raise

    cleanup_error = close_sdk_once(sdk)
    if cleanup_error is not None:
        if exit_code != CliExitCode.OK:
            write_sdk_cleanup_diagnostic(cleanup_error)
        elif is_sdk_cleanup_control_flow(cleanup_error):
            raise cleanup_error
        else:
            write_sdk_cleanup_diagnostic(cleanup_error)
            return int(CliExitCode.ERROR)

    if args.describe:
        if not target:
            write_text_best_effort(
                sys.stderr,
                f"❌ 未知平台: {args.describe}\n",
            )
            return int(CliExitCode.USAGE)
        write_text_best_effort(
            sys.stdout,
            json.dumps(target, ensure_ascii=False, indent=2) + "\n",
        )
        return int(CliExitCode.OK)

    if args.pretty:
        for p in platforms:
            write_text_best_effort(
                sys.stdout,
                f"📦 {p['id']}: {p['name']}\n",
            )
            # 与 SDK list_platforms() 对齐：显示 search_placeholder（与 GUI 搜索框 placeholder 一致）
            placeholder = p.get("search_placeholder", "")
            if placeholder:
                write_text_best_effort(
                    sys.stdout,
                    f"   搜索提示: {placeholder}\n",
                )
            if p.get("description"):
                write_text_best_effort(
                    sys.stdout,
                    f"   {p['description']}\n",
                )
            n = len(p.get("settings", []))
            if n:
                write_text_best_effort(sys.stdout, f"   参数: {n} 个\n")
            write_text_best_effort(sys.stdout, "\n")
    else:
        write_text_best_effort(
            sys.stdout,
            json.dumps(platforms, ensure_ascii=False, indent=2) + "\n",
        )
    return int(CliExitCode.OK)
