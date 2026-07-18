"""从插件目录生成平台快捷命令。"""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from cli.platform_catalog import CliPlatform


def add_platform_subparsers(
    subparsers: argparse._SubParsersAction,
    platforms: Iterable[CliPlatform],
) -> dict[str, dict[str, argparse.ArgumentParser]]:
    """注册与通用命令共享参数和 handler 的平台快捷入口。"""

    from cli.commands.download import handle_download_command
    from cli.commands.search import handle_search_command
    from shared.download_command_runtime import add_download_arguments
    from shared.search_command_runtime import add_search_arguments

    catalog = tuple(platforms)
    ids = tuple(platform.id for platform in catalog)
    parsers: dict[str, dict[str, argparse.ArgumentParser]] = {}

    for platform in catalog:
        platform_parser = subparsers.add_parser(
            platform.id,
            help=f"{platform.name} 平台快捷命令",
            aliases=list(platform.aliases),
        )
        platform_subparsers = platform_parser.add_subparsers(
            dest="platform_command",
            title="子命令",
            required=True,
        )

        search_parser = platform_subparsers.add_parser(
            "search",
            help=f"在 {platform.name} 平台搜索",
        )
        add_search_arguments(
            search_parser,
            platform_ids=ids,
            fixed_source=platform.id,
        )
        search_parser.set_defaults(_handler=handle_search_command)

        download_parser = platform_subparsers.add_parser(
            "download",
            help=f"从 {platform.name} 平台下载",
        )
        add_download_arguments(download_parser)
        download_parser.set_defaults(
            _platform=platform.id,
            _handler=handle_download_command,
        )

        parsers[platform.id] = {
            "parser": platform_parser,
            "search": search_parser,
            "download": download_parser,
        }

    return parsers
