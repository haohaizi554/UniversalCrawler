"""Reusable runtime for the local-directory scan command."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from shared.sdk_cleanup import (
    append_sdk_cleanup_diagnostic,
    attach_sdk_cleanup_failure,
    close_sdk_once,
    is_sdk_cleanup_control_flow,
    safe_exception_text,
)


@dataclass(slots=True)
class ScanCommandEnv:
    """Dependencies required to execute a directory scan."""

    UcrawlSDK_cls: Any
    get_default_scan_limit: Callable[[], int]


def add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the shared scan command argument contract."""

    parser.add_argument("directory", help="要扫描的目录")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多扫描文件数 (默认: 从配置读取，通常 1000)",
    )
    output = parser.add_argument_group("输出")
    output.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="不输出扫描进度到 stderr",
    )
    output.add_argument(
        "--pretty",
        action="store_true",
        help="人类可读格式",
    )


def resolve_scan_limit(
    args: argparse.Namespace,
    *,
    env: ScanCommandEnv,
) -> int:
    """Resolve and validate the explicit or configured scan limit."""

    raw = (
        args.limit
        if getattr(args, "limit", None) is not None
        else env.get_default_scan_limit()
    )
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("--limit 必须是整数") from exc
    if value <= 0:
        raise ValueError("--limit 必须大于 0")
    return value


def run_scan_command(
    args: argparse.Namespace,
    *,
    env: ScanCommandEnv,
) -> tuple[str, dict | None, str | None]:
    """Execute one directory scan and return a semantic outcome."""

    try:
        scan_limit = resolve_scan_limit(args, env=env)
    except ValueError as exc:
        return "usage", None, f"❌ {exc}"

    sdk = env.UcrawlSDK_cls(
        verbose=not getattr(args, "quiet", False),
    )
    operation_error: TypeError | ValueError | None = None
    result: dict | None = None
    outcome = "error"
    error_message: str | None = None
    try:
        try:
            raw_result = sdk.scan_directory(
                getattr(args, "directory", None),
                scan_limit=scan_limit,
            )
        except (TypeError, ValueError) as exc:
            operation_error = exc
            error_message = f"❌ {safe_exception_text(exc)}"
            outcome = "usage"
        else:
            if not isinstance(raw_result, dict):
                error_message = "❌ SDK 返回了无效的扫描结果"
            else:
                result = raw_result
                outcome = str(
                    result.get("status", "error") or "error"
                ).lower()
                if outcome not in {"ok", "error", "timeout", "cancelled"}:
                    outcome = "error"
    except BaseException as primary_error:
        cleanup_error = close_sdk_once(sdk)
        if cleanup_error is not None:
            attach_sdk_cleanup_failure(primary_error, cleanup_error)
        raise

    cleanup_error = close_sdk_once(sdk)
    if cleanup_error is None:
        return outcome, result, error_message

    if operation_error is not None or outcome != "ok":
        return (
            outcome,
            result,
            append_sdk_cleanup_diagnostic(error_message, cleanup_error),
        )
    if is_sdk_cleanup_control_flow(cleanup_error):
        raise cleanup_error
    return "error", None, append_sdk_cleanup_diagnostic(None, cleanup_error)


def print_pretty(result: dict) -> None:
    """Render the existing human-readable scan result."""

    if result.get("status") != "ok":
        sys.stderr.write(f"❌ {result.get('error', '未知错误')}\n")
        return

    message = result.get("message", "")
    if message:
        sys.stdout.write(f"{message}\n")
    else:
        sys.stdout.write(f"📂 {result['directory']}\n")
        sys.stdout.write(
            f"📊 共 {result['total_count']} 个 "
            f"(视频 {result['video_count']}, "
            f"图片 {result['image_count']})\n"
        )
    if result.get("truncated"):
        sys.stdout.write(
            f"⚠️  截断 (原本 {result.get('original_count')} 个)\n"
        )
    type_map = {
        "video": "视频",
        "gallery": "图集",
        "image": "图片",
    }
    for index, item in enumerate(result["items"]):
        title = item.get("title", "?")
        status = item.get("status", "")
        content_type = item.get("content_type", "")
        type_label = type_map.get(content_type, content_type)
        local_path = item.get("local_path", "")
        line = f"  [{index}] {title}  {status}"
        if type_label:
            line += f"  [{type_label}]"
        if local_path:
            line += f"  → {local_path}"
        sys.stdout.write(line + "\n")


def emit_result(result: dict, *, pretty: bool) -> None:
    """Emit a structured or human-readable scan result."""

    if pretty:
        print_pretty(result)
    else:
        sys.stdout.write(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        sys.stdout.flush()
