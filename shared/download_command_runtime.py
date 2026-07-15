"""download 命令的可测试运行时。

命令层只负责 argparse 和真实依赖装配；这里承载参数校验、配置合并和
SDK 调用流程，便于 CLI、平台别名命令和单元测试复用同一套行为。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from shared.runtime_options import compose_runtime_config

@dataclass(slots=True)
class DownloadCommandEnv:
    """把外部依赖显式注入运行时，避免测试导入完整 GUI/SDK 栈。"""

    UcrawlSDK_cls: Any
    get_default_save_dir: Callable[[], str]
    build_missav_proxy_url: Callable[[str], str]
    validate_config_types: Callable[[dict], str | None]
    get_plugin: Callable[[str], Any]
    list_platform_ids: Callable[[], list[str]]

def add_download_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("video_id", help="视频 ID / 标题")
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录 (默认: 从配置读取)")
    parser.add_argument("--url", help="视频 URL (如果已有)")
    parser.add_argument("--source", "-s", default="", help="平台 ID (douyin/bilibili/kuaishou/missav)")
    parser.add_argument("--timeout", type=float, default=300, help="下载超时秒数 (默认: 300，与 SDK/REST API 一致)")
    parser.add_argument("--config", type=str, default=None, help="平台特定配置 (JSON 字符串，如 '{\"proxy\":\"http://127.0.0.1:7890\"}')")
    parser.add_argument("--cookie", type=str, default=None, help="Cookie 字符串 (与 --config '{\"cookie\":\"...\"}' 等价)")
    parser.add_argument("--download-strategy", type=str, default=None, help="下载策略 (m3u8/http，与 GUI spider build_download_meta 对齐)")
    parser.add_argument("--referer", type=str, default=None, help="Referer 请求头 (与 --config '{\"referer\":\"...\"}' 等价)")
    parser.add_argument("--ua", type=str, default=None, help="User-Agent 请求头 (与 --config '{\"ua\":\"...\"}' 等价)")
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，传入时自动启用 --use-subdir，与 GUI 对齐)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价，影响文件扩展名和保存路径)")
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL (与 --config '{\"proxy\":\"http://127.0.0.1:7890\"}' 等价，MissAV 平台会自动转换)")
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品 (MissAV 专属，与 --config '{\"individual_only\":true}' 等价)")
    parser.add_argument("--priority", type=str, default=None, help="优先级 (MissAV 专属，与 --config '{\"priority\":\"中文字幕优先\"}' 等价)")

    out_group = parser.add_argument_group("输出")
    out_group.add_argument("--quiet", "-q", action="store_true", help="不输出下载进度到 stderr")
    out_group.add_argument("--pretty", action="store_true", help="人类可读格式 (默认 JSON)")

def resolve_source(args: argparse.Namespace) -> str:
    return getattr(args, "source", "") or getattr(args, "_platform", "")

def build_missing_url_result(args: argparse.Namespace, *, save_dir: str) -> dict:
    return {
        "status": "error",
        "video_id": args.video_id,
        "url": "",
        "source": resolve_source(args),
        "title": args.video_id,
        "error": "未提供 --url，无法下载",
        "save_dir": save_dir,
        "local_path": "",
        "content_type": "",
        "meta": {},
        "elapsed": 0,
    }

def parse_user_config(args: argparse.Namespace, *, env: DownloadCommandEnv) -> tuple[dict | None, str | None]:
    config_json = getattr(args, "config", None)
    if not config_json:
        return {}, None

    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError as exc:
        return None, f"❌ --config JSON 解析失败: {exc}"

    if not isinstance(parsed, dict):
        return None, "❌ --config 必须是 JSON 对象"

    config_err = env.validate_config_types(parsed)
    if config_err:
        return None, f"❌ {config_err}"
    return dict(parsed), None

def build_config(args: argparse.Namespace, *, source: str, env: DownloadCommandEnv) -> tuple[dict | None, str | None]:
    user_config, error = parse_user_config(args, env=env)
    if error:
        return None, error

    # argparse 里的便捷参数统一归并为 config，保证 CLI download、SDK
    # download_video 和 GUI spider 产出的 download_meta 使用同一套字段。
    convenience_body: dict[str, Any] = {}
    for attr in (
        "cookie",
        "download_strategy",
        "referer",
        "ua",
        "folder_name",
        "file_name",
        "content_type",
        "proxy",
        "priority",
    ):
        value = getattr(args, attr, None)
        if value is not None:
            convenience_body[attr] = value
    if getattr(args, "use_subdir", None):
        convenience_body["use_subdir"] = True
    if getattr(args, "individual_only", None):
        convenience_body["individual_only"] = True

    config = compose_runtime_config(
        source,
        user_config=user_config,
        convenience_body=convenience_body,
        defaults_factory=lambda _source: {},
        proxy_normalizer=env.build_missav_proxy_url,
    )

    if config:
        config_err = env.validate_config_types(config)
        if config_err:
            return None, f"❌ {config_err}"
    return config, None

def run_download_command(
    args: argparse.Namespace,
    *,
    env: DownloadCommandEnv,
) -> tuple[int, dict | None, str | None]:
    """执行一次直接下载命令。

    返回 `(exit_code, result, error_message)`，让 CLI 薄包装层自行决定
    写 stdout/stderr；这样测试可以直接断言结构化结果，不依赖终端输出。
    """
    save_dir = getattr(args, "save_dir", None) or env.get_default_save_dir()

    if args.timeout <= 0:
        return 1, None, "❌ timeout 必须大于 0"

    if not args.url:
        return 1, build_missing_url_result(args, save_dir=save_dir), "❌ 未提供 --url，无法下载。用法: ucrawl download <标题> --url <URL> --source <平台>"

    source = resolve_source(args)
    if not source:
        return 1, None, "❌ 必须指定 --source 平台 ID (douyin/bilibili/kuaishou/missav)"

    if not env.get_plugin(source):
        valid_ids = env.list_platform_ids()
        return 1, None, f"❌ 无效平台: {source}。支持: {valid_ids}"

    config, config_error = build_config(args, source=source, env=env)
    if config_error:
        return 1, None, config_error

    sdk = env.UcrawlSDK_cls(save_dir=save_dir)
    try:
        result = sdk.download_video(
            url=args.url,
            source=source,
            title=args.video_id,
            save_dir=save_dir,
            timeout=args.timeout,
            verbose=not getattr(args, "quiet", False),
            config=config or None,
        )
    except (TypeError, ValueError) as exc:
        return 1, None, f"❌ {exc}"
    finally:
        sdk.close()

    return (0 if result.get("status") == "ok" else 1), result, None

def print_pretty(result: dict) -> None:
    if result.get("status") != "ok":
        status = result.get("status", "error")
        if status == "timeout" or "超时" in result.get("error", ""):
            sys.stderr.write(f"❌ 下载超时: {result.get('error', '未知错误')}\n")
        else:
            sys.stderr.write(f"❌ 下载失败: {result.get('error', '未知错误')}\n")
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
    content_type = result.get("content_type", "")
    if content_type:
        type_map = {"video": "视频", "gallery": "图集", "image": "图片"}
        type_label = type_map.get(content_type, content_type)
        sys.stdout.write(f"🏷️  类型: {type_label}\n")
    elapsed = result.get("elapsed")
    if elapsed is not None:
        sys.stdout.write(f"⏱️  耗时: {elapsed}s\n")
    sys.stdout.write("\n")

def emit_result(result: dict, *, pretty: bool) -> None:
    if pretty:
        print_pretty(result)
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
