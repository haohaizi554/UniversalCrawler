"""Argparse adapter for the interactive terminal workflow."""

from __future__ import annotations

import argparse

from cli.interactive.workflow import run_interactive


def add_interactive_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the interactive mode's stable command-line contract."""

    parser.add_argument("--save-dir", "-d", default=None, help="默认保存目录")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="平台特定配置 JSON 对象",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=None,
        help="HTTP 请求超时秒",
    )
    parser.add_argument(
        "--timeout",
        dest="command_timeout",
        type=float,
        default=None,
        help="整次命令超时秒",
    )
    parser.add_argument(
        "--run-timeout",
        dest="legacy_run_timeout",
        type=float,
        default=None,
        help="已弃用；使用 --timeout",
    )

    selection = parser.add_argument_group("二次选择")
    selection.add_argument("--select", help="指定选中的索引")
    selection.add_argument("--exclude", help="指定排除的索引")
    selection.add_argument(
        "--all",
        dest="select_all",
        action="store_true",
        help="全选",
    )
    selection.add_argument(
        "--first",
        action="store_true",
        help="只选第一个",
    )
    selection.add_argument(
        "--last",
        action="store_true",
        help="只选最后一个",
    )
    selection.add_argument(
        "--pipe",
        action="store_true",
        help="使用 stdin 管道选择",
    )
    selection.add_argument(
        "--preload-choices",
        help="预加载多次选择",
    )

    parser.add_argument(
        "--no-download",
        action="store_true",
        help="只搜索不下载",
    )
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串")
    parser.add_argument(
        "--download-strategy",
        type=str,
        default=None,
        help="下载策略",
    )
    parser.add_argument(
        "--referer",
        type=str,
        default=None,
        help="Referer 请求头",
    )
    parser.add_argument(
        "--ua",
        type=str,
        default=None,
        help="User-Agent 请求头",
    )
    parser.add_argument(
        "--folder-name",
        type=str,
        default=None,
        help="子目录名",
    )
    parser.add_argument(
        "--use-subdir",
        action="store_true",
        default=None,
        help="使用子目录保存",
    )
    parser.add_argument(
        "--file-name",
        type=str,
        default=None,
        help="输出文件名",
    )
    parser.add_argument(
        "--content-type",
        type=str,
        default=None,
        help="内容类型",
    )
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL")
    parser.add_argument(
        "--individual-only",
        action="store_true",
        default=None,
        help="只看单体作品",
    )
    parser.add_argument("--priority", type=str, default=None, help="优先级")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="不输出运行日志",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="人类可读格式",
    )


def handle_interactive_command(args: argparse.Namespace) -> int:
    """Delegate to the interactive workflow."""

    return int(run_interactive(args))
