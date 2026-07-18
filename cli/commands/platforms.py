"""platforms 命令：列出所有可用平台。

ucrawl platforms [--json] [--describe <id>]
"""

from __future__ import annotations

import argparse
import json
import sys

from cli.exit_codes import CliExitCode
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
    finally:
        sdk.close()

    if args.describe:
        target = next((p for p in platforms if p["id"] == args.describe), None)
        if not target:
            sys.stderr.write(f"❌ 未知平台: {args.describe}\n")
            return int(CliExitCode.USAGE)
        sys.stdout.write(json.dumps(target, ensure_ascii=False, indent=2) + "\n")
        return int(CliExitCode.OK)

    if args.pretty:
        for p in platforms:
            sys.stdout.write(f"📦 {p['id']}: {p['name']}\n")
            # 与 SDK list_platforms() 对齐：显示 search_placeholder（与 GUI 搜索框 placeholder 一致）
            placeholder = p.get("search_placeholder", "")
            if placeholder:
                sys.stdout.write(f"   搜索提示: {placeholder}\n")
            if p.get("description"):
                sys.stdout.write(f"   {p['description']}\n")
            n = len(p.get("settings", []))
            if n:
                sys.stdout.write(f"   参数: {n} 个\n")
            sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(platforms, ensure_ascii=False, indent=2) + "\n")
    return int(CliExitCode.OK)
