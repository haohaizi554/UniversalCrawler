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
    parser.add_argument("--limit", type=int, default=None,
                        help="最多扫描文件数 (默认: 从配置读取，通常 1000)")
    # 输出参数（与 search/download 命令的 --quiet/--pretty 对齐）
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出扫描进度到 stderr")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式")

def handle_scan_command(args: argparse.Namespace) -> int:
    # 与 SDK scan_directory() 和 REST API /api/scan 对齐：limit 从配置读取
    from app.config import cfg
    scan_limit = args.limit if args.limit is not None else cfg.get("download", "local_scan_limit", 1000)
    try:
        scan_limit = int(scan_limit)
    except (ValueError, TypeError):
        scan_limit = 1000
    # 与 SDK 和 REST API 对齐：scan_limit 必须大于 0
    if scan_limit <= 0:
        sys.stderr.write("❌ --limit 必须大于 0\n")
        return 1

    # 与 search/download 命令 --quiet 对齐：静默模式不输出 SDK 内部日志
    verbose = not getattr(args, "quiet", False)
    sdk = UcrawlSDK(verbose=verbose)
    try:
        result = sdk.scan_directory(args.directory, scan_limit=scan_limit)
    except (TypeError, ValueError) as exc:
        # 与 SDK search()/download_video() 对齐：参数校验异常直接输出友好信息
        sys.stderr.write(f"❌ {exc}\n")
        return 1
    finally:
        sdk.close()

    if args.pretty:
        if result.get("status") == "ok":
            # 与 SDK/REST API 返回的 message 字段对齐：显示人类可读摘要
            msg = result.get("message", "")
            if msg:
                sys.stdout.write(f"{msg}\n")
            else:
                sys.stdout.write(f"📂 {result['directory']}\n")
                sys.stdout.write(f"📊 共 {result['total_count']} 个 (视频 {result['video_count']}, 图片 {result['image_count']})\n")
            if result.get("truncated"):
                sys.stdout.write(f"⚠️  截断 (原本 {result.get('original_count')} 个)\n")
            for i, item in enumerate(result["items"]):
                title = item.get('title', '?')
                status = item.get('status', '')
                # 与 GUI 表格对齐：显示 content_type 和 local_path
                content_type = item.get('content_type', '')
                type_map = {'video': '视频', 'gallery': '图集', 'image': '图片'}
                type_label = type_map.get(content_type, content_type) if content_type else ''
                local_path = item.get('local_path', '')
                line = f"  [{i}] {title}  {status}"
                if type_label:
                    line += f"  [{type_label}]"
                if local_path:
                    line += f"  → {local_path}"
                sys.stdout.write(line + "\n")
        else:
            sys.stderr.write(f"❌ {result.get('error', '未知错误')}\n")
            return 1
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("status") == "ok" else 1
