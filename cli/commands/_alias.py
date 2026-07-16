"""平台子命令别名：ucrawl douyin search "测试" 等价于 ucrawl search -s douyin "测试"。

支持的别名：
- ucrawl douyin search ...
- ucrawl bilibili search ...
- ucrawl kuaishou search ...
- ucrawl missav search ...
"""

from __future__ import annotations

import argparse

from cli.commands.search import handle_search_command
from shared.search_command_runtime import add_search_arguments

def add_platform_alias_subparser(subparsers: argparse._SubParsersAction) -> None:
    for source in ["douyin", "bilibili", "kuaishou", "missav"]:
        platform_parser = subparsers.add_parser(
            source,
            help=f"{source} 平台快捷命令 (等价于 ucrawl search --source {source})",
        )
        platform_subparsers = platform_parser.add_subparsers(
            dest=f"{source}_command",
            required=False,
        )
        # search 子命令
        search_parser = platform_subparsers.add_parser(
            "search",
            help=f"在 {source} 平台搜索",
        )
        search_parser.set_defaults(_platform_source=source)
        add_search_arguments(search_parser, source_required=False)
        # 别名入口不要求重复传入 --source，而是通过默认值固定当前平台。
        search_parser.set_defaults(source=source)

def handle_platform_alias(args: argparse.Namespace) -> int:
    # 如果用户没指定子命令 (比如 `ucrawl douyin "测试"`)，当作 search
    if not hasattr(args, "_platform_source") or getattr(args, "source", None) is None:
        return 2  # argparse 会显示帮助
    # 把 platform 命令转成 search 命令
    return handle_search_command(args)
