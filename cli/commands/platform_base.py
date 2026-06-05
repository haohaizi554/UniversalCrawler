"""平台别名命令：ucrawl douyin search "测试" 等价于 ucrawl search --source douyin "测试"。

支持的别名：
- ucrawl douyin search ...
- ucrawl bilibili search ...
- ucrawl kuaishou search ...
- ucrawl missav search ...

同样支持 download 和其他子命令：
- ucrawl douyin download <video_id>
- ucrawl bilibili scan <directory>
"""

from __future__ import annotations

import argparse


# 平台 ID 映射
PLATFORMS = {
    "douyin": {"name": "抖音", "aliases": ["dy", "douyin"]},
    "bilibili": {"name": "B站", "aliases": ["bilibili", "bili", "bl"]},
    "kuaishou": {"name": "快手", "aliases": ["kuaishou", "ks"]},
    "missav": {"name": "MissAV", "aliases": ["missav", "miss"]},
}

# 所有别名到标准 ID 的映射
ALIAS_TO_PLATFORM = {}
for platform_id, info in PLATFORMS.items():
    ALIAS_TO_PLATFORM[platform_id] = platform_id
    for alias in info.get("aliases", []):
        ALIAS_TO_PLATFORM[alias] = platform_id


def resolve_platform(name: str) -> str | None:
    """将别名解析为标准平台 ID。"""
    return ALIAS_TO_PLATFORM.get(name.lower())


def add_platform_subparsers(subparsers: argparse._SubParsersAction) -> dict[str, argparse.ArgumentParser]:
    """为每个平台添加子命令。

    Returns:
        平台名到子命令解析器的字典
    """
    parsers = {}

    for platform_id, info in PLATFORMS.items():
        # 平台主命令
        platform_parser = subparsers.add_parser(
            platform_id,
            help=f"{info['name']} 平台快捷命令",
            aliases=info.get("aliases", []),
        )

        # 子命令
        platform_subparsers = platform_parser.add_subparsers(
            dest=f"{platform_id}_subcommand",
            title="子命令",
        )

        # search 子命令
        search_parser = platform_subparsers.add_parser(
            "search",
            help=f"在 {info['name']} 平台搜索",
        )
        _add_search_args(search_parser, platform_id)
        search_parser.set_defaults(_platform=platform_id)

        # download 子命令
        download_parser = platform_subparsers.add_parser(
            "download",
            help=f"从 {info['name']} 平台下载",
        )
        _add_download_args(download_parser)
        download_parser.set_defaults(_platform=platform_id)

        # scan 子命令
        scan_parser = platform_subparsers.add_parser(
            "scan",
            help=f"扫描 {info['name']} 相关资源",
        )
        scan_parser.add_argument("keyword", help="搜索关键词 / 链接 / 用户 ID")
        scan_parser.add_argument("--max-items", type=int, default=None, help="最大视频数")
        scan_parser.set_defaults(_platform=platform_id)

        parsers[platform_id] = {
            "parser": platform_parser,
            "search": search_parser,
            "download": download_parser,
            "scan": scan_parser,
        }

    return parsers


def _add_search_args(parser: argparse.ArgumentParser, platform_id: str) -> None:
    """为 search 子命令添加参数。"""
    parser.add_argument(
        "keyword",
        help="搜索关键词 / 链接 / 用户 ID",
    )
    parser.add_argument(
        "--save-dir", "-d",
        default="downloads",
        help="保存目录 (默认: downloads)",
    )

    # 平台特定参数
    if platform_id == "douyin":
        parser.add_argument("--max-items", type=int, default=20, help="最大视频数 (默认 20)")
    elif platform_id == "bilibili":
        parser.add_argument("--max-pages", type=int, default=1, help="翻页数 (默认 1)")
        parser.add_argument("--max-items", type=int, default=30, help="最大视频数 (默认 30)")
    elif platform_id == "kuaishou":
        parser.add_argument("--max-items", type=int, default=20, help="最大视频数 (默认 20)")
    elif platform_id == "missav":
        parser.add_argument("--individual-only", action="store_true", help="只看单体作品")
        parser.add_argument(
            "--priority",
            choices=["中文字幕优先", "无码流出优先"],
            default="中文字幕优先",
            help="筛选优先级 (默认: 中文字幕优先)",
        )
        parser.add_argument("--proxy", default="http://127.0.0.1:7890", help="代理 URL")

    # 通用参数
    parser.add_argument("--timeout", type=int, default=10, help="HTTP 超时秒 (默认 10)")
    parser.add_argument("--no-download", action="store_true", help="只搜索不下载")
    parser.add_argument("--run-timeout", type=float, default=None, help="整体超时秒")

    # 二次选择
    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5 或 0,2-5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔)")
    sel_group.add_argument("--all", dest="select_all", action="store_true", help="全选 (默认)")
    sel_group.add_argument("--first", action="store_true", help="只选第一个")
    sel_group.add_argument("--last", action="store_true", help="只选最后一个")
    sel_group.add_argument("--interactive", "-i", action="store_true", help="强制 TTY 交互式选择")
    sel_group.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    sel_group.add_argument("--preload-choices", help="预加载多次选择 (用 | 分隔每轮)")


def _add_download_args(parser: argparse.ArgumentParser) -> None:
    """为 download 子命令添加参数。"""
    parser.add_argument("video_id", help="视频 ID")
    parser.add_argument("--save-dir", "-d", default="downloads", help="保存目录 (默认: downloads)")
    parser.add_argument("--url", help="视频 URL (如果已有)")
