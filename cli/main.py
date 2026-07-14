"""CLI 主入口：`python -m cli` 或 `ucrawl` 命令。

新架构支持：
- 通用命令：search, scan, download, platforms
- 平台别名：douyin, xiaohongshu, bilibili, kuaishou, missav
- 交互式选择：TTY 和 stdin 管道
"""

from __future__ import annotations

import argparse
import os
import sys

# 设置 PYTHONPATH 包含项目根目录（去重，避免重复插入）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

def _ensure_search_defaults(args: argparse.Namespace, platform: str) -> None:
    """为平台别名命令补全通用 search 参数的默认值。

    平台别名命令 (platform_base.py) 只定义了部分参数，
    但 handle_search_command 需要完整的参数集。
    此函数为缺失的属性设置合理默认值。
    """
    # 设置 source（核心字段）
    args.source = platform

    # 通用 search 参数默认值
    _defaults = {
        "save_dir": None,
        "max_items": None,
        "max_pages": None,
        "timeout": None,
        "individual_only": False,
        "priority": None,
        "proxy": None,
        "config": None,
        "select": None,
        "exclude": None,
        "select_all": False,
        "first": False,
        "last": False,
        "interactive": False,
        "pipe": False,
        "preload_choices": None,
        "quiet": False,
        "pretty": False,
        "run_timeout": None,
        "no_download": False,
        # 与通用 search 命令便捷参数对齐（platform_base.py 已添加这些参数定义）
        "cookie": None,
        "download_strategy": None,
        "referer": None,
        "ua": None,
        "folder_name": None,
        "use_subdir": None,
        "file_name": None,
        "content_type": None,
    }
    for key, default in _defaults.items():
        if not hasattr(args, key):
            setattr(args, key, default)

def main(argv: list[str] | None = None) -> int:
    """CLI 主入口函数。

    Args:
        argv: 命令行参数 (None=使用 sys.argv[1:])

    Returns:
        退出码 (0=成功, 1=错误, 2=参数错误)
    """
    parser = argparse.ArgumentParser(
        prog="ucrawl",
        description="""UCrawl 通用爬虫 - 命令行/脚本/AI 工具

用法:
  ucrawl search --source <平台> <关键词> [选项]
  ucrawl <平台> search <关键词> [选项]
  ucrawl scan <目录> [选项]
  ucrawl download <video_id> [选项]
  ucrawl platforms [选项]

示例:
  # 通用命令
  ucrawl search --source douyin "测试" --max-items 10
  ucrawl search --source bilibili "BV1xxx" --select "0,2,5"

  # 平台别名
  ucrawl douyin search "测试" --max-items 10
  ucrawl xhs search "测试" --max-items 10
  ucrawl bilibili search "BV1xxx" --select "0,2,5"
  ucrawl missav search "ABC-123" --individual-only

  # 合集场景：预加载多轮选择
  ucrawl bilibili search "BV1xxx" --preload-choices "0|1,2|3,4"

  # 本地操作
  ucrawl scan "D:/downloads" --limit 500
  ucrawl platforms --pretty

二次选择:
  --all              全选 (默认)
  --first            只选第一个
  --last             只选最后一个
  --select "0,2,5"   指定索引 (逗号分隔，支持范围 0,2-5)
  --exclude "1,3"    排除索引
  --interactive / -i  强制 TTY 交互式选择
  --pipe             强制 stdin 管道选择
  --preload-choices "0|1,2|3,4"  预加载多次选择 (| 分轮，, 分索引)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-V", action="store_true", help="显示版本")

    subparsers = parser.add_subparsers(dest="main_command", title="子命令")

    # search
    from cli.commands.search import handle_search_command
    from shared.search_command_runtime import add_search_arguments
    search_parser = subparsers.add_parser("search", help="搜索并下载 (通用命令)")
    add_search_arguments(search_parser)
    search_parser.set_defaults(_handler=handle_search_command)

    # scan
    from cli.commands.scan import add_scan_arguments, handle_scan_command
    scan_parser = subparsers.add_parser("scan", help="扫描本地目录")
    add_scan_arguments(scan_parser)
    scan_parser.set_defaults(_handler=handle_scan_command)

    # download
    from cli.commands.download import handle_download_command
    from shared.download_command_runtime import add_download_arguments
    download_parser = subparsers.add_parser("download", help="下载指定视频")
    add_download_arguments(download_parser)
    download_parser.set_defaults(_handler=handle_download_command)

    # platforms
    from cli.commands.platforms import add_platforms_arguments, handle_platforms_command
    platforms_parser = subparsers.add_parser("platforms", help="列出所有可用平台")
    add_platforms_arguments(platforms_parser)
    platforms_parser.set_defaults(_handler=handle_platforms_command)

    # interactive
    from cli.commands.interactive import add_interactive_arguments, handle_interactive_command
    interactive_parser = subparsers.add_parser("interactive", help="交互式引导模式", aliases=["i"])
    add_interactive_arguments(interactive_parser)
    interactive_parser.set_defaults(_handler=handle_interactive_command)

    # 平台别名 (douyin, xiaohongshu, bilibili, kuaishou, missav)
    from cli.commands.platform_base import add_platform_subparsers
    add_platform_subparsers(subparsers)

    # 解析
    args = parser.parse_args(argv)

    if getattr(args, "main_command", None) == "search":
        from shared.search_command_runtime import resolve_keyword
        try:
            args.keyword = resolve_keyword(args)
        except ValueError as exc:
            parser.error(str(exc))

    if args.version:
        from cli import __version__
        sys.stdout.write(f"ucrawl {__version__}\n")
        return 0

    if not getattr(args, "main_command", None):
        parser.print_help()
        return 0

    # 平台别名走同一套 handler：先把缺省 argparse 字段补齐，再复用通用
    # search/download/scan 逻辑，避免平台别名和通用命令行为漂移。
    from cli.commands.platform_base import resolve_platform
    resolved_platform = resolve_platform(args.main_command)
    if resolved_platform:
        platform = resolved_platform
        platform_subcmd = getattr(args, f"{platform}_subcommand", None)

        if platform_subcmd == "search":
            # 补全通用 search 参数的默认值（平台别名命令可能缺少这些属性）
            _ensure_search_defaults(args, platform)
            return handle_search_command(args)
        elif platform_subcmd == "download":
            return handle_download_command(args)
        elif platform_subcmd == "scan":
            # scan 特殊处理
            return handle_scan_command(args)
        else:
            # 显示帮助
            subparsers.choices[platform].print_help()
            return 0

    # 通用子命令
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)

if __name__ == "__main__":
    sys.exit(main())
