"""scan 命令：扫描本地目录。

ucrawl scan <directory> [--limit N] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from cli.sdk import UcrawlSDK


def add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("directory", help="要扫描的目录")
    parser.add_argument("--limit", type=int, default=1000, help="最多扫描文件数 (默认 1000)")
    parser.add_argument("--pretty", action="store_true", help="人类可读格式")


def handle_scan_command(args: argparse.Namespace) -> int:
    sdk = UcrawlSDK()
    result = sdk.scan_directory(args.directory, scan_limit=args.limit)
    if args.pretty:
        if result.get("status") == "ok":
            sys.stdout.write(f"📂 {result['directory']}\n")
            sys.stdout.write(f"📊 共 {result['total_count']} 个 (视频 {result['video_count']}, 图片 {result['image_count']})\n")
            if result.get("truncated"):
                sys.stdout.write(f"⚠️  截断 (原本 {result.get('original_count')} 个)\n")
            for i, item in enumerate(result["items"]):
                sys.stdout.write(f"  [{i}] {item.get('title', '?')}\n")
        else:
            sys.stderr.write(f"❌ {result.get('error', '未知错误')}\n")
            return 1
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("status") == "ok" else 1
