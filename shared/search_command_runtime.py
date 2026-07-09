"""search 命令的可测试运行时。

这里集中处理参数校验、选择策略创建、平台配置合并和 CLIRunner 调用，
命令模块本身只保留 argparse/真实依赖装配，避免行为在旧入口间分叉。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from shared.runtime_options import compose_runtime_config

@dataclass(slots=True)
class SearchCommandEnv:
    """运行时依赖注入点，主要服务单元测试和平台别名命令复用。"""

    CLIRunner_cls: Any
    selection_factory: Any
    get_platform_defaults: Callable[[str], dict]
    get_default_save_dir: Callable[[], str]
    build_missav_proxy_url: Callable[[str], str]
    validate_config_types: Callable[[dict], str | None]

def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", "-s", required=True, choices=["douyin", "xiaohongshu", "bilibili", "kuaishou", "missav"], help="平台 ID")
    parser.add_argument("keyword", help="搜索关键词 / 链接 / 用户 ID")
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录 (默认: 从配置读取，通常为 downloads)")
    parser.add_argument("--max-items", type=int, default=None, help="最大资源数 (各平台默认: douyin=20, xiaohongshu=20, bilibili=30, kuaishou=20, missav=全部)")
    parser.add_argument("--max-pages", type=int, default=None, help="翻页数 (仅 bilibili, 默认 1)")
    parser.add_argument("--timeout", type=int, default=None, help="HTTP 超时秒 (默认 10)")
    parser.add_argument("--individual-only", action="store_true", help="只看单体作品 (仅 missav)")
    parser.add_argument("--priority", choices=["中文字幕优先", "无码流出优先"], default=None, help="筛选优先级 (仅 missav, 默认: 中文字幕优先)")
    parser.add_argument("--proxy", default=None, help='代理 URL (与 --config \'{"proxy":"http://127.0.0.1:7890"}\' 等价，MissAV 平台会自动转换)')
    parser.add_argument("--config", type=str, default=None, help="平台特定配置 (JSON 字符串，如 '{\"max_items\":50}')")
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http，与 GUI spider build_download_meta 对齐)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价，影响文件扩展名和保存路径)")

    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5 或 0,2-5 或 0,2:5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔, 如 1,3 或 1,3-5 或 1,3:5)")
    sel_group.add_argument("--all", dest="select_all", action="store_true", help="全选 (默认)")
    sel_group.add_argument("--first", action="store_true", help="只选第一个")
    sel_group.add_argument("--last", action="store_true", help="只选最后一个")
    sel_group.add_argument("--interactive", "-i", action="store_true", help="强制 TTY 交互式选择")
    sel_group.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    sel_group.add_argument("--preload-choices", help="预加载多次选择 (用 | 分隔每轮, 如 '0|1,2|3,4,5')")

    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式 (默认 JSON)")
    out_group.add_argument("--run-timeout", type=float, default=None, help="整体超时秒")
    out_group.add_argument("--no-download", action="store_true", help="只搜索不下载 (默认会自动下载，与 GUI 一致)")

def build_selection_strategy(args: argparse.Namespace, *, env: SearchCommandEnv):
    return env.selection_factory.from_cli_args(args, default_strategy="rule_all")

def build_config(args: argparse.Namespace, *, env: SearchCommandEnv) -> dict:
    source = getattr(args, "source", None) or getattr(args, "_platform", "douyin")
    user_config: dict = {}
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
            if isinstance(parsed, dict):
                user_config = dict(parsed)
        except json.JSONDecodeError:
            pass

    # 独立命令行参数优先级最高，统一交给 compose_runtime_config 过滤空值、
    # 应用平台默认值和 MissAV proxy 归一化。
    convenience_body: dict[str, Any] = {}
    for attr in (
        "max_items",
        "max_pages",
        "timeout",
        "priority",
        "proxy",
        "cookie",
        "download_strategy",
        "referer",
        "ua",
        "folder_name",
        "file_name",
        "content_type",
    ):
        value = getattr(args, attr, None)
        if value is not None:
            convenience_body[attr] = value
    if getattr(args, "individual_only", False):
        convenience_body["individual_only"] = True
    if getattr(args, "use_subdir", None):
        convenience_body["use_subdir"] = True

    return compose_runtime_config(
        source,
        user_config=user_config,
        convenience_body=convenience_body,
        defaults_factory=env.get_platform_defaults,
        proxy_normalizer=env.build_missav_proxy_url,
    )

def validate_args(args: argparse.Namespace, *, env: SearchCommandEnv) -> str | None:
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
            if not isinstance(parsed, dict):
                return "❌ --config 必须是 JSON 对象"
        except json.JSONDecodeError as exc:
            return f"❌ --config JSON 解析失败: {exc}"
        config_err = env.validate_config_types(parsed)
        if config_err:
            return f"❌ {config_err}"

    run_timeout = getattr(args, "run_timeout", None)
    if run_timeout is not None and run_timeout <= 0:
        return "❌ --run-timeout 必须大于 0"
    spider_timeout = getattr(args, "timeout", None)
    if spider_timeout is not None and spider_timeout <= 0:
        return "❌ --timeout 必须大于 0"
    return None

def run_search_command(args: argparse.Namespace, *, env: SearchCommandEnv) -> tuple[int, dict]:
    """执行一次搜索/下载命令并返回退出码和结构化结果。"""

    error = validate_args(args, env=env)
    if error:
        return 1, {"status": "error", "error": error.removeprefix("❌ ").strip()}

    config = build_config(args, env=env)
    strategy = build_selection_strategy(args, env=env)
    source = getattr(args, "source", None) or getattr(args, "_platform", "douyin")
    runner = env.CLIRunner_cls(
        source=source,
        keyword=args.keyword,
        save_dir=getattr(args, "save_dir", None) or env.get_default_save_dir(),
        selection_strategy=strategy,
        config=config,
        verbose=not getattr(args, "quiet", False),
        log_to_stderr=not getattr(args, "quiet", False),
        timeout=getattr(args, "run_timeout", None),
        download=not getattr(args, "no_download", False),
    )
    result = runner.run()
    if result.get("status") == "ok":
        return 0, result
    return 1, result

def print_pretty(result: dict) -> None:
    if result.get("status") != "ok":
        sys.stderr.write(f"❌ {result.get('status')}: {result.get('error', '')}\n")
        return

    sys.stdout.write(f"✅ 状态: {result['status']}\n")
    sys.stdout.write(f"📂 平台: {result['source']}\n")
    sys.stdout.write(f"🔍 关键词: {result['keyword']}\n")
    sys.stdout.write(f"💾 保存目录: {result['save_dir']}\n")
    sys.stdout.write(f"📊 找到 {len(result['items'])} 个项目\n")
    sys.stdout.write(f"⏱️  耗时: {result['elapsed']}s\n")
    sys.stdout.write(f"🔄 二次选择: {result['selection_count']} 次\n\n")

    for i, item in enumerate(result["items"]):
        sys.stdout.write(f"  [{i}] {item.get('title', '?')}\n")
        sys.stdout.write(f"      平台: {item.get('source', '?')}  URL: {item.get('url', '?')}\n")
        status = item.get("status", "?")
        content_type = item.get("content_type", "")
        type_label = ""
        if content_type:
            type_map = {"video": "视频", "gallery": "图集", "image": "图片"}
            type_label = f"  类型: {type_map.get(content_type, content_type)}"
        sys.stdout.write(f"      状态: {status}  进度: {item.get('progress', 0)}%{type_label}\n")
        meta = item.get("meta", {})
        if "❌" in status and meta.get("download_error"):
            sys.stdout.write(f"      错误: {meta['download_error']}\n")
        if item.get("local_path"):
            sys.stdout.write(f"      本地: {item['local_path']}\n")
        sys.stdout.write("\n")

def emit_result(result: dict, *, pretty: bool) -> None:
    if pretty:
        print_pretty(result)
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
