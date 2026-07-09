"""download 子命令：下载指定的视频。

ucrawl download <video_id> [--save-dir <dir>] [--url <url>] [--source <platform>] [--config <json>] [--individual-only] [--priority <str>]
"""

from __future__ import annotations

import argparse
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
