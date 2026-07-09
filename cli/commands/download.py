"""download 子命令：下载指定的视频。

ucrawl download <video_id> [--save-dir <dir>] [--url <url>] [--source <platform>] [--config <json>] [--individual-only] [--priority <str>]
"""

from __future__ import annotations

import argparse
import json
import sys

from app.core.plugin_registry import registry
from cli.defaults import build_missav_proxy_url, get_default_save_dir, validate_config_types
from cli.sdk import UcrawlSDK
from shared import download_command_runtime as runtime

def _runtime_env() -> runtime.DownloadCommandEnv:
    """装配真实依赖；共享 runtime 通过该对象与测试替身解耦。"""

    return runtime.DownloadCommandEnv(
        UcrawlSDK_cls=UcrawlSDK,
        get_default_save_dir=get_default_save_dir,
        build_missav_proxy_url=build_missav_proxy_url,
        validate_config_types=validate_config_types,
        get_plugin=registry.get_plugin,
        list_platform_ids=lambda: [plugin.id for plugin in registry.get_all_plugins()],
    )

def _build_config(args: argparse.Namespace, *, source: str) -> tuple[dict | None, str | None]:
    return runtime.build_config(args, source=source, env=_runtime_env())

def add_download_arguments(parser: argparse.ArgumentParser) -> None:
    """为 download 子命令添加参数。"""
    parser.add_argument("video_id", help="视频 ID / 标题")
    parser.add_argument(
        "--save-dir", "-d",
        default=None,
        help="保存目录 (默认: 从配置读取)",
    )
    parser.add_argument("--url", help="视频 URL (如果已有)")
    parser.add_argument("--source", "-s", default="", help="平台 ID (douyin/bilibili/kuaishou/missav)")
    # 与 SDK download_video(timeout=) 和 REST API /api/download(timeout=) 对齐
    parser.add_argument("--timeout", type=float, default=300, help="下载超时秒数 (默认: 300，与 SDK/REST API 一致)")
    # 与 SDK download_video(config=) 和 REST API /api/download(config=) 对齐
    parser.add_argument(
        "--config", type=str, default=None,
        help="平台特定配置 (JSON 字符串，如 '{\"proxy\":\"http://127.0.0.1:7890\"}')",
    )
    # 与 SDK download_video(config={"cookie": "..."}) 对齐：便捷参数，避免手写 JSON
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    # 与 GUI spider download_strategy 对齐：指定下载策略
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http，与 GUI spider build_download_meta 对齐)")
    # 与 GUI spider build_download_meta 对齐：便捷参数，避免手写 JSON
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    # 与 GUI Bilibili spider build_download_meta 对齐：子目录结构控制
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    # 与 GUI spider build_download_meta 对齐：文件名控制
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：内容类型控制
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价，影响文件扩展名和保存路径)")
    # 与 CLI search --proxy 对齐：代理便捷参数
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL (与 --config '{\"proxy\":\"http://127.0.0.1:7890\"}' 等价，MissAV 平台会自动转换)")
    # 与 CLI search --individual-only/--priority 对齐：MissAV 专属便捷参数
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品 (MissAV 专属，与 --config '{\"individual_only\":true}' 等价)")
    parser.add_argument("--priority", type=str, default=None, help="优先级 (MissAV 专属，与 --config '{\"priority\":\"中文字幕优先\"}' 等价)")

    # 输出参数（与 search 命令的 --quiet/--pretty 对齐）
    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出下载进度到 stderr")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式 (默认 JSON)")

def handle_download_command(args: argparse.Namespace) -> int:
    """执行 download 命令。"""
    exit_code, result, error_message = runtime.run_download_command(args, env=_runtime_env())
    if error_message:
        sys.stderr.write(f"{error_message}\n")
    if result is not None:
        runtime.emit_result(result, pretty=getattr(args, "pretty", False))
    return exit_code
    # 下面是迁移到 shared.download_command_runtime 前的旧实现，当前不可达。
    # 暂时保留是为了让尚未完成清理的静态断言/历史对照不丢上下文。
    # 从 cfg 读取默认保存目录（与 GUI 对齐）
    from cli.defaults import get_default_save_dir
    save_dir = getattr(args, "save_dir", None) or get_default_save_dir()

    # 与 SDK download_video 和 REST API /api/download 对齐：校验 timeout > 0
    if args.timeout <= 0:
        sys.stderr.write("❌ timeout 必须大于 0\n")
        return 1

    # 如果提供了 URL，直接下载
    if args.url:
        source = getattr(args, "source", "") or getattr(args, "_platform", "")
        if not source:
            sys.stderr.write("❌ 必须指定 --source 平台 ID (douyin/bilibili/kuaishou/missav)\n")
            return 1

        # 与 SDK search() 和 REST API /api/search 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            sys.stderr.write(f"❌ 无效平台: {source}。支持: {valid_ids}\n")
            return 1

        # 使用 SDK download_video() 统一逻辑，消除与 SDK 的代码重复
        # verbose 与 search --quiet 对齐：--quiet 时 verbose=False，否则 verbose=True
        verbose = not getattr(args, "quiet", False)
        # 与 SDK download_video(config=) 和 REST API /api/download(config=) 对齐
        user_config = None
        if getattr(args, "config", None):
            try:
                user_config = json.loads(args.config)
                if not isinstance(user_config, dict):
                    sys.stderr.write("❌ --config 必须是 JSON 对象\n")
                    return 1
            except json.JSONDecodeError as e:
                sys.stderr.write(f"❌ --config JSON 解析失败: {e}\n")
                return 1
        else:
            user_config = {}
        # 与 SDK download_video(config={"cookie": "..."}) 对齐：--cookie 便捷参数合并到 config
        if getattr(args, "cookie", None):
            user_config["cookie"] = args.cookie
        # 与 GUI spider download_strategy 对齐：--download-strategy 便捷参数合并到 config
        if getattr(args, "download_strategy", None):
            user_config["download_strategy"] = args.download_strategy
        # 与 GUI spider build_download_meta 对齐：--referer/--ua 便捷参数合并到 config
        if getattr(args, "referer", None):
            user_config["referer"] = args.referer
        if getattr(args, "ua", None):
            user_config["ua"] = args.ua
        # 与 GUI Bilibili spider build_download_meta 对齐：--folder-name/--use-subdir 便捷参数合并到 config
        if getattr(args, "folder_name", None):
            user_config["folder_name"] = args.folder_name
        if getattr(args, "use_subdir", None):
            user_config["use_subdir"] = True
        # 与 GUI BilibiliSpider 对齐：传入 folder_name 时自动启用 use_subdir
        # GUI BilibiliSpider 设置 "use_subdir": bool(folder_name)，
        # 即有 folder_name 就自动使用子目录。CLI 用户只传 --folder-name 不传 --use-subdir 时，
        # 应与 GUI 行为一致，自动启用子目录
        if user_config.get("folder_name") and not user_config.get("use_subdir"):
            user_config["use_subdir"] = True
        # 与 GUI DouyinParser 对齐：传入 author 但未传 folder_name 时，自动将 author 设为 folder_name
        # GUI DouyinParser 在解析视频时设置 "folder_name": author（parser.py:68/85），
        # CLI download 不经过 spider，需要手动设置以确保与 GUI 行为一致
        if user_config.get("author") and not user_config.get("folder_name"):
            user_config["folder_name"] = user_config["author"]
            if not user_config.get("use_subdir"):
                user_config["use_subdir"] = True
        # 与 GUI spider build_download_meta 对齐：--file-name 便捷参数合并到 config
        if getattr(args, "file_name", None):
            user_config["file_name"] = args.file_name
        # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：--content-type 便捷参数合并到 config
        if getattr(args, "content_type", None):
            user_config["content_type"] = args.content_type
        # 与 CLI search --proxy 对齐：--proxy 便捷参数合并到 config
        if getattr(args, "proxy", None):
            user_config["proxy"] = args.proxy
        # 与 CLI search --individual-only/--priority 对齐：MissAV 专属便捷参数合并到 config
        if getattr(args, "individual_only", None):
            user_config["individual_only"] = True
        if getattr(args, "priority", None):
            user_config["priority"] = args.priority
        # 与 CLI search 和 REST API/SDK 对齐：统一转换 missav proxy
        if source == "missav" and "proxy" in user_config and user_config["proxy"] is not None:
            from cli.defaults import build_missav_proxy_url
            user_config["proxy"] = build_missav_proxy_url(user_config["proxy"])
        # 与 CLI search/interactive 和 SDK _validate_config 对齐：校验已知参数类型
        if user_config:
            from cli.defaults import validate_config_types
            config_err = validate_config_types(user_config)
            if config_err:
                sys.stderr.write(f"❌ {config_err}\n")
                return 1
        sdk = UcrawlSDK(save_dir=save_dir)
        try:
            result = sdk.download_video(
                url=args.url,
                source=source,
                title=args.video_id,
                save_dir=save_dir,
                timeout=args.timeout,
                verbose=verbose,
                config=user_config or None,
            )
        except (TypeError, ValueError) as exc:
            # 与原 CLI 行为对齐：参数校验失败输出到 stderr
            sys.stderr.write(f"❌ {exc}\n")
            return 1
        finally:
            sdk.close()

        # 输出（与 search 命令的 --pretty 对齐）
        if getattr(args, "pretty", False):
            _print_pretty(result)
        else:
            sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            sys.stdout.flush()
        return 0 if result.get("status") == "ok" else 1

    # 与 SDK download_video() 返回结构完全对齐：包含 content_type、meta 和 elapsed
    sys.stderr.write("❌ 未提供 --url，无法下载。用法: ucrawl download <标题> --url <URL> --source <平台>\n")
    sys.stdout.write(json.dumps({
        "status": "error",
        "video_id": args.video_id,
        "url": "",
        "source": getattr(args, "source", "") or getattr(args, "_platform", ""),
        "title": args.video_id,
        "error": "未提供 --url，无法下载",
        "save_dir": save_dir,
        # 与 SDK download_video 错误结果对齐：始终包含 local_path
        "local_path": "",
        "content_type": "",
        "meta": {},
        "elapsed": 0,
    }, ensure_ascii=False, indent=2) + "\n")
    return 1

def _print_pretty(result: dict) -> None:
    """人类可读格式输出（与 search 命令的 _print_pretty 对齐）。"""
    if result.get("status") != "ok":
        # 与 search _print_pretty 对齐：区分超时和其他错误
        status = result.get("status", "error")
        if status == "timeout" or "超时" in result.get("error", ""):
            sys.stderr.write(f"❌ 下载超时: {result.get('error', '未知错误')}\n")
        else:
            sys.stderr.write(f"❌ 下载失败: {result.get('error', '未知错误')}\n")
        # 与 search _print_pretty 对齐：失败时也显示耗时
        elapsed = result.get("elapsed")
        if elapsed is not None:
            sys.stderr.write(f"⏱️  耗时: {elapsed}s\n")
        return

    sys.stdout.write(f"✅ 状态: {result['status']}\n")
    sys.stdout.write(f"📦 平台: {result['source']}\n")
    sys.stdout.write(f"📝 标题: {result['title']}\n")
    sys.stdout.write(f"🔗 URL: {result['url']}\n")
    sys.stdout.write(f"💾 保存目录: {result['save_dir']}\n")
    if result.get("local_path"):
        sys.stdout.write(f"📂 本地路径: {result['local_path']}\n")
    # 与 search _print_pretty 对齐：显示 content_type
    content_type = result.get("content_type", "")
    if content_type:
        type_map = {"video": "视频", "gallery": "图集", "image": "图片"}
        type_label = type_map.get(content_type, content_type)
        sys.stdout.write(f"🏷️  类型: {type_label}\n")
    # 与 search _print_pretty 对齐：显示耗时
    elapsed = result.get("elapsed")
    if elapsed is not None:
        sys.stdout.write(f"⏱️  耗时: {elapsed}s\n")
    sys.stdout.write("\n")
