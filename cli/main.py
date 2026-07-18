"""`python -m cli` 与 `ucrawl` 共用的命令行入口。"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from cli.exit_codes import CliExitCode
from cli.platform_catalog import CliPlatform

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def build_parser(
    platforms: Sequence[CliPlatform] | None = None,
) -> argparse.ArgumentParser:
    """从平台目录构建唯一的根解析器。"""

    from cli.commands.download import handle_download_command
    from cli.commands.interactive import (
        add_interactive_arguments,
        handle_interactive_command,
    )
    from cli.commands.platform_base import add_platform_subparsers
    from cli.commands.platforms import (
        add_platforms_arguments,
        handle_platforms_command,
    )
    from cli.commands.scan import add_scan_arguments, handle_scan_command
    from cli.commands.search import handle_search_command
    from cli.platform_catalog import load_cli_platforms, platform_ids
    from shared.download_command_runtime import add_download_arguments
    from shared.search_command_runtime import add_search_arguments

    catalog = (
        tuple(platforms)
        if platforms is not None
        else load_cli_platforms()
    )
    ids = platform_ids(catalog)

    parser = argparse.ArgumentParser(
        prog="ucrawl",
        description="UCrawl 通用爬虫命令行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-V", action="store_true", help="显示版本")
    subparsers = parser.add_subparsers(dest="main_command", title="子命令")

    search_parser = subparsers.add_parser("search", help="搜索并下载")
    add_search_arguments(search_parser, platform_ids=ids)
    search_parser.set_defaults(_handler=handle_search_command)

    scan_parser = subparsers.add_parser("scan", help="扫描本地目录")
    add_scan_arguments(scan_parser)
    scan_parser.set_defaults(_handler=handle_scan_command)

    download_parser = subparsers.add_parser("download", help="直接下载")
    add_download_arguments(download_parser, platform_ids=ids)
    download_parser.set_defaults(_handler=handle_download_command)

    platforms_parser = subparsers.add_parser(
        "platforms",
        help="列出所有可用平台",
    )
    add_platforms_arguments(platforms_parser)
    platforms_parser.set_defaults(_handler=handle_platforms_command)

    interactive_parser = subparsers.add_parser(
        "interactive",
        help="交互式引导模式",
        aliases=["i"],
    )
    add_interactive_arguments(interactive_parser)
    interactive_parser.set_defaults(_handler=handle_interactive_command)

    add_platform_subparsers(subparsers, catalog)
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析并派发命令，返回稳定进程退出码。"""

    try:
        parser = build_parser()
    except ValueError as exc:
        sys.stderr.write(f"CLI 初始化失败: {exc}\n")
        return int(CliExitCode.ERROR)

    args = parser.parse_args(argv)
    if args.version:
        from shared.version import __version__

        sys.stdout.write(f"ucrawl {__version__}\n")
        return int(CliExitCode.OK)

    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return int(CliExitCode.OK)

    try:
        return int(handler(args))
    except KeyboardInterrupt:
        sys.stderr.write("已取消\n")
        return int(CliExitCode.CANCELLED)


if __name__ == "__main__":
    sys.exit(main())
