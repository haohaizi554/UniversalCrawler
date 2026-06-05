"""platforms 命令：列出所有可用平台。

ucrawl platforms [--json] [--describe <id>]
"""

from __future__ import annotations

import argparse
import json
import sys

from cli.sdk import UcrawlSDK


def add_platforms_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--describe", metavar="ID", help="显示指定平台的详细参数")
    parser.add_argument("--pretty", action="store_true", help="人类可读格式")


def handle_platforms_command(args: argparse.Namespace) -> int:
    sdk = UcrawlSDK()
    platforms = sdk.list_platforms()

    if args.describe:
        target = next((p for p in platforms if p["id"] == args.describe), None)
        if not target:
            sys.stderr.write(f"❌ 未知平台: {args.describe}\n")
            return 1
        sys.stdout.write(json.dumps(target, ensure_ascii=False, indent=2) + "\n")
        return 0

    if args.pretty:
        for p in platforms:
            sys.stdout.write(f"📦 {p['id']}: {p['name']}\n")
            if p.get("description"):
                sys.stdout.write(f"   {p['description']}\n")
            n = len(p.get("settings", []))
            if n:
                sys.stdout.write(f"   参数: {n} 个\n")
            sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(platforms, ensure_ascii=False, indent=2) + "\n")
    return 0
