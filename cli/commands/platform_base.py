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

        # scan 子命令（与通用 scan 命令对齐：扫描本地目录）
        scan_parser = platform_subparsers.add_parser(
            "scan",
            help=f"扫描本地目录",
        )
        scan_parser.add_argument("directory", help="要扫描的目录")
        scan_parser.add_argument("--limit", type=int, default=None, help="最多扫描文件数 (默认: 从配置读取，通常 1000)")
        scan_parser.add_argument("--pretty", action="store_true", help="人类可读格式")
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
        default=None,
        help="保存目录 (默认: 从配置读取，通常为 downloads)",
    )

    # 平台特定参数（默认值由 DEFAULT_CONFIG 统一管理，此处 default=None）
    if platform_id == "douyin":
        parser.add_argument("--max-items", type=int, default=None, help="最大视频数 (默认 20)")
    elif platform_id == "bilibili":
        parser.add_argument("--max-pages", type=int, default=None, help="翻页数 (默认 1)")
        parser.add_argument("--max-items", type=int, default=None, help="最大视频数 (默认 30)")
    elif platform_id == "kuaishou":
        parser.add_argument("--max-items", type=int, default=None, help="最大视频数 (默认 20)")
    elif platform_id == "missav":
        parser.add_argument("--individual-only", action="store_true", help="只看单体作品")
        parser.add_argument(
            "--priority",
            choices=["中文字幕优先", "无码流出优先"],
            default=None,
            help="筛选优先级 (默认: 中文字幕优先)",
        )
        # --proxy 由下方便捷参数统一提供（与通用 search 命令对齐），不再重复定义

    # 通用参数
    parser.add_argument("--timeout", type=int, default=None, help="HTTP 超时秒 (默认 10)")
    parser.add_argument("--no-download", action="store_true", help="只搜索不下载")
    parser.add_argument("--run-timeout", type=float, default=None, help="整体超时秒")
    # 与通用 search 命令 --config 对齐：支持平台特定配置
    parser.add_argument(
        "--config", type=str, default=None,
        help="平台特定配置 (JSON 字符串，如 '{\"max_items\":50}')",
    )
    # 与通用 search 命令便捷参数对齐（与 GUI spider build_download_meta 对齐）
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价)")
    # 与通用 search 命令 --proxy 对齐：代理便捷参数（MissAV 平台会自动转换）
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL (与 --config '{\"proxy\":\"http://127.0.0.1:7890\"}' 等价，MissAV 平台会自动转换)")

    # 二次选择
    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5 或 0,2-5 或 0,2:5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔, 如 1,3 或 1,3-5 或 1,3:5)")
    sel_group.add_argument("--all", dest="select_all", action="store_true", help="全选 (默认)")
    sel_group.add_argument("--first", action="store_true", help="只选第一个")
    sel_group.add_argument("--last", action="store_true", help="只选最后一个")
    sel_group.add_argument("--interactive", "-i", action="store_true", help="强制 TTY 交互式选择")
    sel_group.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    sel_group.add_argument("--preload-choices", help="预加载多次选择 (用 | 分隔每轮, 如 '0|1,2|3,4,5')")

    # 输出控制
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式")


def _add_download_args(parser: argparse.ArgumentParser) -> None:
    """为 download 子命令添加参数（与通用 download 命令对齐）。"""
    parser.add_argument("video_id", help="视频 ID")
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录 (默认: 从配置读取)")
    parser.add_argument("--url", help="视频 URL (如果已有)")
    parser.add_argument("--source", "-s", default="", help="平台 ID (默认使用当前平台别名)")
    # 与通用 download 命令 --timeout 对齐
    parser.add_argument("--timeout", type=float, default=300, help="下载超时秒数 (默认: 300，与 SDK/REST API 一致)")
    # 与通用 download 命令 --config 对齐：支持平台特定配置（如 missav proxy）
    parser.add_argument(
        "--config", type=str, default=None,
        help="平台特定配置 (JSON 字符串，如 '{\"proxy\":\"http://127.0.0.1:7890\"}')",
    )
    # 与通用 download 命令便捷参数对齐（与 GUI spider build_download_meta 对齐）
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价)")
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL (与 --config '{\"proxy\":\"http://127.0.0.1:7890\"}' 等价，MissAV 平台会自动转换)")
    # 与通用 download 命令 --individual-only/--priority 对齐：MissAV 专属便捷参数
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品 (MissAV 专属，与 --config '{\"individual_only\":true}' 等价)")
    parser.add_argument("--priority", type=str, default=None, help="优先级 (MissAV 专属，与 --config '{\"priority\":\"中文字幕优先\"}' 等价)")

    # 输出参数（与通用 download 命令和 search 命令的 --quiet/--pretty 对齐）
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出下载进度到 stderr")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式 (默认 JSON)")
