"""通用 search 命令：ucrawl search --source douyin "测试"."""

from __future__ import annotations

import argparse
import sys

from shared import search_command_runtime as runtime
from shared.cli_runner_runtime import CLIRunner
from shared.runtime_options import (
    build_missav_proxy_url,
    get_default_save_dir,
    get_platform_defaults,
    validate_config_types,
)
from shared.selection_runtime import SelectionStrategyFactory

def _runner_class():
    """Return the shared runner through this command-local test seam."""
    return CLIRunner

def _runtime_env() -> runtime.SearchCommandEnv:
    """装配真实依赖；共享 runtime 通过该对象与测试替身解耦。"""

    return runtime.SearchCommandEnv(
        CLIRunner_cls=_runner_class(),
        selection_factory=SelectionStrategyFactory,
        get_platform_defaults=get_platform_defaults,
        get_default_save_dir=get_default_save_dir,
        build_missav_proxy_url=build_missav_proxy_url,
        validate_config_types=validate_config_types,
    )

def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    """为通用 search 子命令添加参数。"""
    parser.add_argument(
        "--source", "-s",
        required=True,
        choices=["douyin", "xiaohongshu", "bilibili", "kuaishou", "missav"],
        help="平台 ID",
    )
    parser.add_argument("keyword", nargs="?", help="搜索关键词 / 链接 / 用户 ID")
    parser.add_argument(
        "--keyword",
        dest="keyword_option",
        help="搜索关键词 / 链接 / 用户 ID（兼容旧脚本；推荐使用位置参数）",
    )
    parser.add_argument(
        "--save-dir", "-d",
        default=None,
        help="保存目录 (默认: 从配置读取，通常为 downloads)",
    )
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="最大资源数 (各平台默认: douyin=20, xiaohongshu=20, bilibili=30, kuaishou=20, missav=全部)",
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
        help='代理 URL (与 --config \'{"proxy":"http://127.0.0.1:7890"}\' 等价，MissAV 平台会自动转换)',
    )

    # 平台特定配置（与 CLI download --config 和 SDK config 对齐）
    parser.add_argument(
        "--config", type=str, default=None,
        help="平台特定配置 (JSON 字符串，如 '{\"max_items\":50}')",
    )
    # 与 GUI spider build_download_meta 对齐：便捷参数，避免手写 JSON
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http，与 GUI spider build_download_meta 对齐)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    # 与 GUI Bilibili spider build_download_meta 对齐：子目录结构控制
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    # 与 GUI spider build_download_meta 对齐：文件名控制
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：内容类型控制
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价，影响文件扩展名和保存路径)")

    # 二次选择参数
    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5 或 0,2-5 或 0,2:5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔, 如 1,3 或 1,3-5 或 1,3:5)")
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
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式 (默认 JSON)")
    out_group.add_argument("--run-timeout", type=float, default=None, help="整体超时秒")
    out_group.add_argument("--no-download", action="store_true", help="只搜索不下载 (默认会自动下载，与 GUI 一致)")

def _build_selection_strategy(args: argparse.Namespace):
    """根据命令行参数构造选择策略。"""
    return runtime.build_selection_strategy(args, env=_runtime_env())

def _build_config(args: argparse.Namespace) -> dict:
    """根据命令行参数构造 spider config，与 GUI 默认值完全一致。

    使用 getattr 安全访问属性，兼容平台别名命令（部分属性可能不存在）。
    优先从 cfg 持久化配置读取默认值（与 GUI read_*_run_options 对齐），
    命令行参数覆盖 cfg 默认值。

    合并顺序（与 SDK search() 和 REST API /api/search 对齐）：
    1. 平台默认值 (get_platform_defaults，从 cfg 读取)
    2. --config JSON 参数（过滤 None 值，避免覆盖默认值）
    3. 独立参数 (--max-items, --timeout 等，优先级最高)
    """
    return runtime.build_config(args, env=_runtime_env())

def handle_search_command(args: argparse.Namespace) -> int:
    """执行 search 命令。"""
    exit_code, result = runtime.run_search_command(args, env=_runtime_env())
    runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return exit_code

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
        sys.stdout.write(f"      平台: {item.get('source', '?')}  URL: {item.get('url', '?')}\n")
        status = item.get('status', '?')
        # 与 GUI 表格"类型"列对齐：显示 content_type（视频/图集/图片）
        content_type = item.get('content_type', '')
        type_label = ''
        if content_type:
            type_map = {'video': '视频', 'gallery': '图集', 'image': '图片'}
            type_label = f'  类型: {type_map.get(content_type, content_type)}'
        sys.stdout.write(f"      状态: {status}  进度: {item.get('progress', 0)}%{type_label}\n")
        # 显示下载错误原因（与 GUI 日志 "❌ 下载失败 [title]: error" 对齐）
        meta = item.get('meta', {})
        if "❌" in status and meta.get("download_error"):
            sys.stdout.write(f"      错误: {meta['download_error']}\n")
        if item.get("local_path"):
            sys.stdout.write(f"      本地: {item['local_path']}\n")
        sys.stdout.write("\n")
