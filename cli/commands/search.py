"""通用 search 命令：ucrawl search --source douyin --keyword "测试"."""

from __future__ import annotations

import argparse
import json
import sys

import cli.runner as cli_runner_module
from cli.defaults import DEFAULT_CONFIG, build_missav_proxy_url, get_platform_defaults, get_default_save_dir, validate_config_types
from cli.runner import CLIRunner
from cli.selection import (
    AutoSelection,
    RuleSelection,
    InteractiveTTYSelection,
    PipeSelection,
)
from shared import search_command_runtime as runtime

class SelectionStrategyFactory:
    """CLI 本地选择策略工厂，保留旧 cli.selection 类的可替换性。"""

    @staticmethod
    def from_cli_args(args: argparse.Namespace, *, default_strategy: str = "rule_all"):
        if getattr(args, "interactive", False):
            return InteractiveTTYSelection()
        if getattr(args, "pipe", False):
            return PipeSelection()
        if getattr(args, "preload_choices", None):
            rounds = []
            for token in args.preload_choices.split("|"):
                indices = []
                for part in token.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        indices.append(int(part))
                    except ValueError:
                        pass
                rounds.append(indices)
            return PipeSelection(preloaded_choices=rounds)
        return RuleSelection(
            select=getattr(args, "select", None),
            exclude=getattr(args, "exclude", None),
            all_items=getattr(args, "select_all", False) or getattr(args, "select", None) is None,
            first=getattr(args, "first", False),
            last=getattr(args, "last", False),
        )

def _looks_mock(obj) -> bool:
    module_name = str(getattr(obj, "__module__", ""))
    type_module = str(getattr(type(obj), "__module__", ""))
    return module_name.startswith("unittest.mock") or type_module.startswith("unittest.mock")

def _runner_class():
    """测试可能 monkeypatch 两处 CLIRunner；这里优先返回被替换的对象。"""

    if _looks_mock(CLIRunner):
        return CLIRunner
    if _looks_mock(cli_runner_module.CLIRunner):
        return cli_runner_module.CLIRunner
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
    parser.add_argument(
        "keyword",
        help="搜索关键词 / 链接 / 用户 ID",
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
    # 下面是迁移到 shared.search_command_runtime 前的旧实现，当前不可达。
    # 保留到相关兼容测试完全迁移后再删除，避免这轮注释任务扩大行为变更。
    if getattr(args, "interactive", False):
        return InteractiveTTYSelection()
    if getattr(args, "pipe", False):
        return PipeSelection()
    if getattr(args, "preload_choices", None):
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
        select=getattr(args, "select", None),
        exclude=getattr(args, "exclude", None),
        all_items=getattr(args, "select_all", False) or getattr(args, "select", None) is None,
        first=getattr(args, "first", False),
        last=getattr(args, "last", False),
    )

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
    # 下面是迁移到 shared.search_command_runtime 前的旧实现，当前不可达。
    source = getattr(args, "source", None) or getattr(args, "_platform", "douyin")
    config = get_platform_defaults(source)

    # 步骤 2：合并 --config JSON（与 SDK config 和 REST API config 对齐）
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            user_config = json.loads(config_json)
            if isinstance(user_config, dict):
                # 与 SDK/REST API 对齐：过滤 None 值，避免覆盖默认值
                filtered = {k: v for k, v in user_config.items() if v is not None}
                config.update(filtered)
        except json.JSONDecodeError:
            pass  # 校验在 handle_search_command 中完成，这里静默跳过

    # 步骤 3：独立参数覆盖（优先级最高，与 CLI 独立参数语义一致）
    if getattr(args, "max_items", None) is not None:
        config["max_items"] = args.max_items
    if getattr(args, "max_pages", None) is not None:
        config["max_pages"] = args.max_pages
    if getattr(args, "timeout", None) is not None:
        config["timeout"] = args.timeout
    if getattr(args, "individual_only", False):
        config["individual_only"] = True
    if getattr(args, "priority", None):
        config["priority"] = args.priority
    if getattr(args, "proxy", None):
        config["proxy"] = args.proxy
    # 与 GUI spider build_download_meta 对齐：便捷参数合并到 config（优先级最高）
    if getattr(args, "cookie", None):
        config["cookie"] = args.cookie
    if getattr(args, "download_strategy", None):
        config["download_strategy"] = args.download_strategy
    if getattr(args, "referer", None):
        config["referer"] = args.referer
    if getattr(args, "ua", None):
        config["ua"] = args.ua
    # 与 GUI Bilibili spider build_download_meta 对齐：子目录结构控制
    if getattr(args, "folder_name", None):
        config["folder_name"] = args.folder_name
    if getattr(args, "use_subdir", None):
        config["use_subdir"] = True
    # 与 GUI BilibiliSpider 对齐：传入 folder_name 时自动启用 use_subdir
    # GUI BilibiliSpider 设置 "use_subdir": bool(folder_name)，
    # 即有 folder_name 就自动使用子目录。CLI 用户只传 --folder-name 不传 --use-subdir 时，
    # 应与 GUI 行为一致，自动启用子目录
    if config.get("folder_name") and not config.get("use_subdir"):
        config["use_subdir"] = True
    # 与 GUI DouyinParser 对齐：传入 author 但未传 folder_name 时，自动将 author 设为 folder_name
    # GUI DouyinParser 在解析视频时设置 "folder_name": author（parser.py:68/85），
    # CLI 用户通过 --config '{"author":"..."}' 传入 author 时，应与 GUI 行为一致
    if config.get("author") and not config.get("folder_name"):
        config["folder_name"] = config["author"]
        if not config.get("use_subdir"):
            config["use_subdir"] = True
    # 与 GUI spider build_download_meta 对齐：文件名控制
    if getattr(args, "file_name", None):
        config["file_name"] = args.file_name
    # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：内容类型控制
    if getattr(args, "content_type", None):
        config["content_type"] = args.content_type
    # 与 REST API/SDK 对齐：统一转换 missav proxy（无论来自 cfg 默认值还是 --proxy 参数）
    if source == "missav" and "proxy" in config and config["proxy"] is not None:
        config["proxy"] = build_missav_proxy_url(config["proxy"])
    return config

def handle_search_command(args: argparse.Namespace) -> int:
    """执行 search 命令。"""
    exit_code, result = runtime.run_search_command(args, env=_runtime_env())
    runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return exit_code
    # 下面是迁移到 shared.search_command_runtime 前的旧实现，当前不可达。
    # 与 CLI download --config 和 SDK config 对齐：校验 --config JSON 格式
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
            if not isinstance(parsed, dict):
                sys.stderr.write("❌ --config 必须是 JSON 对象\n")
                return 1
        except json.JSONDecodeError as e:
            sys.stderr.write(f"❌ --config JSON 解析失败: {e}\n")
            return 1
        # 与 SDK _validate_config 和 REST API _validate_config_types 对齐：校验已知参数类型
        config_err = validate_config_types(parsed)
        if config_err:
            sys.stderr.write(f"❌ {config_err}\n")
            return 1

    config = _build_config(args)
    strategy = _build_selection_strategy(args)

    # 兼容平台别名命令：source 可能来自 _platform 或直接设置
    source = getattr(args, "source", None) or getattr(args, "_platform", "douyin")

    # 与 SDK search() 和 REST API /api/search 对齐：校验 run-timeout > 0
    run_timeout = getattr(args, "run_timeout", None)
    if run_timeout is not None and run_timeout <= 0:
        sys.stderr.write("❌ --run-timeout 必须大于 0\n")
        return 1
    # 与 GUI/WebUI/SDK 参数契约对齐：校验 --timeout (spider HTTP 超时) > 0
    spider_timeout = getattr(args, "timeout", None)
    if spider_timeout is not None and spider_timeout <= 0:
        sys.stderr.write("❌ --timeout 必须大于 0\n")
        return 1

    runner = CLIRunner(
        source=source,
        keyword=args.keyword,
        save_dir=getattr(args, "save_dir", None) or get_default_save_dir(),
        selection_strategy=strategy,
        config=config,
        verbose=not getattr(args, "quiet", False),
        log_to_stderr=not getattr(args, "quiet", False),
        timeout=run_timeout,
        download=not getattr(args, "no_download", False),
    )

    result = runner.run()

    # 输出
    if getattr(args, "pretty", False):
        _print_pretty(result)
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()

    if result.get("status") == "ok":
        return 0
    if result.get("status") in ("error", "timeout", "cancelled"):
        return 1
    return 1

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
