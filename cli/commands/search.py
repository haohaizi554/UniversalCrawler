"""通用 search 命令：ucrawl search --source douyin --keyword "测试"."""

from __future__ import annotations

import argparse
import json
import sys

from cli.runner import CLIRunner
from cli.selection import (
    AutoSelection,
    RuleSelection,
    InteractiveTTYSelection,
    PipeSelection,
)

# 与 GUI 对齐的默认值
DEFAULT_CONFIG = {
    "douyin": {"max_items": 20, "timeout": 10},
    "bilibili": {"max_pages": 1},
    "kuaishou": {"max_items": 20},
    "missav": {
        "individual_only": False,
        "priority": "中文字幕优先",
        "proxy": "http://127.0.0.1:7890"
    }
}


def build_missav_proxy_url(proxy_str: str) -> str:
    """与 GUI `build_missav_proxy_url` 完全一致的转换逻辑。"""
    normalized = proxy_str.strip()
    if normalized == "Clash (7890)":
        return "http://127.0.0.1:7890"
    if normalized == "v2rayN (10809)":
        return "http://127.0.0.1:10809"
    if ":" in normalized:
        return normalized if normalized.startswith("http") else f"http://{normalized}"
    return "http://127.0.0.1:7890"


def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    """为通用 search 子命令添加参数。"""
    parser.add_argument(
        "--source", "-s",
        required=True,
        choices=["douyin", "bilibili", "kuaishou", "missav"],
        help="平台 ID",
    )
    parser.add_argument(
        "keyword",
        help="搜索关键词 / 链接 / 用户 ID",
    )
    parser.add_argument(
        "--save-dir", "-d",
        default="downloads",
        help="保存目录 (默认: downloads)",
    )
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="最大视频数 (各平台默认: douyin=20, bilibili=30, kuaishou=20, missav=全部)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="翻页数 (仅 bilibili, 默认 1)",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="HTTP 超时秒 (默认 10)",
    )
    parser.add_argument(
        "--individual-only", action="store_true",
        help="只看单体作品 (仅 missav)",
    )
    parser.add_argument(
        "--priority",
        choices=["中文字幕优先", "无码流出优先"],
        default=None,
        help="筛选优先级 (仅 missav, 默认: 中文字幕优先)",
    )
    parser.add_argument(
        "--proxy", default=None,
        help="代理 URL (仅 missav, 默认: http://127.0.0.1:7890)",
    )

    # 二次选择参数
    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5 或 0,2-5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔)")
    sel_group.add_argument("--all", dest="select_all", action="store_true", help="全选 (默认)")
    sel_group.add_argument("--first", action="store_true", help="只选第一个")
    sel_group.add_argument("--last", action="store_true", help="只选最后一个")
    sel_group.add_argument("--interactive", "-i", action="store_true", help="强制 TTY 交互式选择")
    sel_group.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    sel_group.add_argument(
        "--preload-choices",
        help="预加载多次选择 (用 | 分隔每轮, 如 '0|1,2|3,4,5')",
    )

    # 输出参数
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--json", action="store_true", help="输出 JSON 格式 (默认)")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式")
    out_group.add_argument("--run-timeout", type=float, default=None, help="整体超时秒")
    out_group.add_argument("--no-download", action="store_true", help="只搜索不下载 (与 GUI 不同，默认会自动下载)")


def _build_selection_strategy(args: argparse.Namespace):
    """根据命令行参数构造选择策略。"""
    if args.interactive:
        return InteractiveTTYSelection()
    if args.pipe:
        return PipeSelection()
    if args.preload_choices:
        rounds = []
        for token in args.preload_choices.split("|"):
            indices = []
            for part in token.split(","):
                part = part.strip()
                if part:
                    try:
                        indices.append(int(part))
                    except ValueError:
                        pass
            rounds.append(indices)
        return PipeSelection(preloaded_choices=rounds)
    return RuleSelection(
        select=args.select,
        exclude=args.exclude,
        all_items=args.select_all or args.select is None,
        first=args.first,
        last=args.last,
    )


def _build_config(args: argparse.Namespace) -> dict:
    """根据命令行参数构造 spider config，与 GUI 默认值完全一致。"""
    config = dict(DEFAULT_CONFIG.get(args.source, {}))
    if args.max_items is not None:
        config["max_items"] = args.max_items
    if args.max_pages is not None:
        config["max_pages"] = args.max_pages
    if args.timeout is not None:
        config["timeout"] = args.timeout
    if args.individual_only:
        config["individual_only"] = True
    if args.priority:
        config["priority"] = args.priority
    if args.proxy:
        config["proxy"] = build_missav_proxy_url(args.proxy)
    return config


def handle_search_command(args: argparse.Namespace) -> int:
    """执行 search 命令。"""
    config = _build_config(args)
    strategy = _build_selection_strategy(args)

    runner = CLIRunner(
        source=args.source,
        keyword=args.keyword,
        save_dir=args.save_dir,
        selection_strategy=strategy,
        config=config,
        verbose=not args.quiet,
        log_to_stderr=not args.quiet,
        timeout=args.run_timeout,
        download=not args.no_download,
    )

    result = runner.run()

    # 输出
    if args.pretty:
        _print_pretty(result)
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()

    if result.get("status") == "ok":
        return 0
    if result.get("status") in ("error", "timeout"):
        return 1
    return 0


def _print_pretty(result: dict) -> None:
    """人类可读格式输出。"""
    if result.get("status") != "ok":
        sys.stderr.write(f"❌ {result.get('status')}: {result.get('error', '')}\n")
        return

    sys.stdout.write(f"✅ 状态: {result['status']}\n")
    sys.stdout.write(f"📂 平台: {result['source']}\n")
    sys.stdout.write(f"🔍 关键词: {result['keyword']}\n")
    sys.stdout.write(f"💾 保存目录: {result['save_dir']}\n")
    sys.stdout.write(f"📊 找到 {len(result['items'])} 个项目\n")
    sys.stdout.write(f"⏱️  耗时: {result['elapsed']}s\n")
    sys.stdout.write(f"🔄 二次选择: {result['selection_count']} 次\n")
    sys.stdout.write("\n")

    for i, item in enumerate(result["items"]):
        sys.stdout.write(f"  [{i}] {item.get('title', '?')}\n")
        sys.stdout.write(f"      URL: {item.get('url', '?')}\n")
        sys.stdout.write(f"      状态: {item.get('status', '?')}  进度: {item.get('progress', 0)}%\n")
        if item.get("local_path"):
            sys.stdout.write(f"      本地: {item['local_path']}\n")
        sys.stdout.write("\n")
