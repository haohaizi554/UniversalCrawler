"""interactive 子命令：交互式引导模式。

逐步引导用户，体验与 GUI 完全对齐：
1. 选择平台（显示搜索提示，与 GUI placeholder 一致）
2. 输入关键词（提示沿用 GUI 搜索框 placeholder）
3. 平台参数配置（与 GUI 设置面板对齐：页数/视频数/偏好/代理）
4. 保存路径（默认用配置中的路径，回车确认，也可输入新路径）
5. Cookie 状态（与 GUI 对齐：本地有则用，无则 spider 自动弹出登录窗口）
6. 确认后执行

与 entry.interactive_entry 对齐（共享同一套交互逻辑）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from shared.cli_runner_runtime import CLIRunner
from shared.interactive_selection import InteractiveTTYSelection
from shared.pipe_selection import PipeSelection
from shared.runtime_options import (
    build_missav_proxy_url,
    get_default_save_dir,
    get_platform_defaults,
    validate_config_types,
)
from shared.sdk_runtime import UcrawlSDK
from shared.selection_runtime import RuleSelection, parse_preloaded_choices
from app.config import cfg
from app.utils.runtime_paths import is_temporary_path

# ============== 颜色常量 ==============

BOLD  = "\033[1m"
RESET = "\033[0m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED   = "\033[91m"
DIM   = "\033[2m"
BLUE  = "\033[94m"

_PLATFORM_GUIDE = {
    "douyin": {
        "input_label": "主页链接、分享链接或合集链接",
        "examples": [
            "主页链接: https://www.douyin.com/user/xxx",
            "分享链接: https://v.douyin.com/xxxxx/",
            "合集链接: 带 collection / mix / modal_id 的链接",
        ],
        "limit_label": "视频数量",
        "empty_tip": "优先尝试主页链接或分享链接；纯数字 UID 当前仍不支持。",
        "result_tip": "抖音会优先按 GUI 同步流程拉起扫码、采集、选择并直接入队下载。",
    },
    "xiaohongshu": {
        "input_label": "小红书关键词、笔记链接或作者主页链接",
        "examples": [
            "关键词: 穿搭 / 探店 / 摄影",
            "笔记链接: https://www.xiaohongshu.com/explore/...",
            "作者主页: https://www.xiaohongshu.com/user/profile/...",
        ],
        "limit_label": "笔记数量",
        "empty_tip": "建议优先使用完整笔记链接或作者主页链接；关键词模式会先搜索再二次选择。",
        "result_tip": "小红书会自动准备浏览器 Cookie，会话不足时可在浏览器中手动登录后继续。",
    },
    "bilibili": {
        "input_label": "BV 号、UP 主页、合集链接或关键词",
        "examples": [
            "BV 号: BV1xx411c7mD",
            "UP 主页: https://space.bilibili.com/123456",
            "合集/视频链接: https://www.bilibili.com/video/BVxxxx",
        ],
        "limit_label": "搜索页数",
        "empty_tip": "可尝试直接输入 BV 号、UP 主页链接或合集链接，通常比模糊关键词更稳定。",
        "result_tip": "B 站会沿用 GUI 的两层选择流程：先选主项目，再按需展开分 P / 合集。",
    },
    "kuaishou": {
        "input_label": "快手主页链接、分享链接、快手号或关键词",
        "examples": [
            "主页链接: https://www.kuaishou.com/profile/xxx",
            "分享链接: https://v.kuaishou.com/xxxxx/ 或分享文案中的快手链接",
            "快手号: 直接输入纯数字快手号",
            "关键词: 先进入站内搜索，再从结果跳到主页继续扫描",
        ],
        "limit_label": "视频数量",
        "empty_tip": "快手建议优先使用主页链接或分享链接；关键词模式会先走站内搜索再进入主页。",
        "result_tip": "快手会弹浏览器并允许你在页面里手动登录；分享链接会直接解析单条作品并入队下载。",
    },
    "missav": {
        "input_label": "番号、演员名或 MissAV 链接",
        "examples": [
            "番号: SSIS-001",
            "演员名: 三上悠亚",
            "列表/详情链接: https://missav.ai/...",
        ],
        "limit_label": "筛选偏好",
        "empty_tip": "如果没有结果，先确认代理可用，再尝试直接输入番号或作品链接。",
        "result_tip": "MissAV 会先扫列表、再按 GUI 同步流程筛最佳版本并嗅探 m3u8。",
    },
}

# ============== Cookie 智能检测（与 GUI spider 对齐） ==============

# 平台 → auth 文件名映射（与 app/config/settings.py AuthSettings 对齐）
_AUTH_FILE_MAP = {
    "douyin":   "dy_auth.json",
    "xiaohongshu": "xhs_auth.json",
    "bilibili": "bili_auth.json",
    "kuaishou": "ks_auth.json",
    "missav":   None,  # MissAV 不需要 cookie
}

# 平台 → 必需的 cookie key（与 GUI spider 对齐）
_REQUIRED_COOKIE_KEY = {
    "douyin":   "sessionid_ss",
    "xiaohongshu": "a1",
    "bilibili": "SESSDATA",
    "kuaishou": "kuaishou.server.web_st",
}

# 平台 → 登录方式描述（与 GUI spider 实现对齐）
_LOGIN_DESC = {
    "douyin":   "抖音将自动弹出浏览器窗口，请扫码登录",
    "xiaohongshu": "小红书将自动拉起浏览器以获取 Cookie，必要时请在页面中手动登录",
    "bilibili": "B站将自动弹出浏览器窗口，请扫码登录",
    "kuaishou": "快手将自动弹出浏览器窗口，请手动登录",
}

def _find_cookie_file(platform_id: str) -> Path | None:
    """在多个候选路径中查找 cookie JSON 文件（与 GUI resolve_user_file 对齐）。"""
    auth_name = _AUTH_FILE_MAP.get(platform_id)
    if auth_name is None:
        return None

    candidates = [
        Path(auth_name),                    # 当前工作目录
        Path.home() / ".ucrawl" / auth_name,  # 用户目录
        Path(__file__).resolve().parent.parent.parent / auth_name,  # 项目根目录
    ]

    # 与 GUI AuthSettings.normalize 对齐：也搜索 user_data 目录
    # 与 GUI 的运行时路径规则保持一致；旧版 USER_DATA_ROOT 常量已经移除。
    try:
        from app.utils.runtime_paths import user_data_root
        candidates.append(user_data_root() / auth_name)
    except Exception:
        pass

    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None

def _load_cookie(platform_id: str) -> dict | list | None:
    """尝试加载本地 cookie JSON（与 GUI AuthService.load_json_file 对齐）。"""
    path = _find_cookie_file(platform_id)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, (dict, list)) and data:
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None

def _build_cookie_string(cookie_data) -> str:
    """构建 cookie 字符串（与 GUI AuthService.build_cookie_string 对齐）。"""
    from app.services.auth_service import AuthService
    return AuthService.build_cookie_string(cookie_data)

def _check_cookie_valid(platform_id: str, cookie_data) -> bool:
    """检查 cookie 是否包含必需的 key（与 GUI spider 启动前校验对齐）。"""
    required = _REQUIRED_COOKIE_KEY.get(platform_id)
    if not required:
        return True
    cookie_str = _build_cookie_string(cookie_data)
    return required in cookie_str

# ============== 参数解析 ==============

def add_interactive_arguments(parser: argparse.ArgumentParser) -> None:
    """为 interactive 子命令添加参数（与 search 命令对齐）。"""
    parser.add_argument("--save-dir", "-d", default=None, help="保存目录")
    parser.add_argument("--no-download", action="store_true", help="只搜索不下载")
    parser.add_argument("--pretty", action="store_true", help="人类可读格式输出")

    # 与 search 命令对齐：运行控制参数
    parser.add_argument("--run-timeout", type=float, default=None, help="整体超时秒数")
    parser.add_argument("--quiet", "-q", action="store_true", help="不输出 spider 日志")
    parser.add_argument("--config", type=str, default=None,
                        help="平台特定配置 (JSON 字符串，如 '{\"max_items\":50}')")

    # 与 search 命令对齐：二次选择参数
    sel_group = parser.add_argument_group("二次选择")
    sel_group.add_argument("--all", dest="select_all", action="store_true", help="全选")
    sel_group.add_argument("--first", action="store_true", help="只选第一个")
    sel_group.add_argument("--last", action="store_true", help="只选最后一个")
    sel_group.add_argument("--select", help="指定选中的索引 (逗号分隔, 如 0,2,5)")
    sel_group.add_argument("--exclude", help="指定排除的索引 (逗号分隔, 如 1,3)")
    sel_group.add_argument("--pipe", action="store_true", help="强制 stdin 管道选择")
    sel_group.add_argument("--preload-choices",
                            help="预加载多次选择 (用 | 分隔每轮, 如 '0|1,2|3,4,5')")

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
    # 与 CLI search/download --proxy 对齐：代理便捷参数
    parser.add_argument("--proxy", type=str, default=None, help="代理 URL (与 --config '{\"proxy\":\"http://127.0.0.1:7890\"}' 等价，MissAV 平台会自动转换)")
    # 与 CLI search/download --individual-only/--priority 对齐：MissAV 专属便捷参数
    parser.add_argument("--individual-only", action="store_true", default=None, help="只看单体作品 (MissAV 专属，与 --config '{\"individual_only\":true}' 等价)")
    parser.add_argument("--priority", type=str, default=None, help="优先级 (MissAV 专属，与 --config '{\"priority\":\"中文字幕优先\"}' 等价)")

# ============== 交互辅助 ==============

def _input(prompt: str, default: str = "") -> str:
    """带默认值的输入：直接回车使用默认值。"""
    hint = f" [{default}]" if default else ""
    try:
        raw = input(f"{CYAN}{prompt}{hint}: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return raw if raw else default

def _choose(prompt: str, options: list[str], default_idx: int = 0) -> int:
    """选择菜单：显示编号选项，回车选默认。"""
    while True:
        print(f"{BOLD}{prompt}{RESET}")
        for i, opt in enumerate(options):
            marker = ">" if i == default_idx else " "
            print(f"  {marker} {YELLOW}{i + 1}{RESET}. {opt}")
        try:
            raw = input(f"{CYAN}选择 (回车={default_idx + 1}): {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default_idx
        if not raw:
            return default_idx
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print(f"  {DIM}无效选择，请重新输入。{RESET}")

def _select_platform(platforms: list[dict], next_platform_id: str | None = None) -> dict | None:
    """选择平台；支持复用上一次平台并在输入错误时重试。"""
    cached = None
    if next_platform_id:
        cached = next((p for p in platforms if p.get("id") == next_platform_id), None)
    if cached is not None:
        print(f"{BOLD}步骤 1/5: 选择平台{RESET}")
        print(f"  {GREEN}✓ 继续使用: {cached['name']}{RESET}\n")
        return cached

    while True:
        print(f"{BOLD}步骤 1/5: 选择平台{RESET}\n")
        for i, platform in enumerate(platforms, 1):
            placeholder = platform.get("search_placeholder", "")
            hint = f"  {DIM}({placeholder}){RESET}" if placeholder else ""
            print(f"  {YELLOW}{i}{RESET}. {BOLD}{platform['name']}{RESET} ({platform['id']}){hint}")
        print()

        try:
            choice = input(f"{CYAN}请输入编号: {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(platforms):
                return platforms[idx]
        except ValueError:
            pass
        print(f"{DIM}无效选择，请重新输入。{RESET}\n")

def _is_temp_dir(path: str) -> bool:
    """检测路径是否是系统临时目录。"""
    return is_temporary_path(path)

def _persist_save_dir(save_dir: str) -> None:
    """把交互式引导里确认过的下载目录同步写回配置。"""
    if not save_dir:
        return
    if _is_temp_dir(save_dir):
        return
    try:
        cfg.set("common", "save_directory", save_dir)
    except Exception:
        pass

def _guide_for(platform_id: str) -> dict:
    return _PLATFORM_GUIDE.get(platform_id, {})

def _print_examples(platform_id: str) -> None:
    examples = _guide_for(platform_id).get("examples", [])
    if not examples:
        return
    print(f"  {DIM}示例:{RESET}")
    for example in examples:
        print(f"    - {example}")

def _build_config_summary_lines(platform_id: str, config: dict, platform_name: str, keyword: str, save_dir: str) -> list[str]:
    lines = [
        f"  平台:   {platform_name}",
        f"  关键词: {keyword}",
        f"  保存到: {save_dir}",
    ]
    if platform_id == "douyin":
        lines.append(f"  视频数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器扫码")
    elif platform_id == "xiaohongshu":
        lines.append(f"  笔记数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器 Cookie / 手动登录")
    elif platform_id == "bilibili":
        lines.append(f"  页数:   {config.get('max_pages', 1)}")
        lines.append("  登录:   浏览器扫码")
    elif platform_id == "kuaishou":
        lines.append(f"  视频数: {config.get('max_items', 20)}")
        lines.append("  登录:   浏览器手动登录")
    elif platform_id == "missav":
        lines.append(f"  偏好:   {config.get('priority', '')}")
        lines.append(f"  仅单体: {'是' if config.get('individual_only') else '否'}")
        lines.append(f"  代理:   {config.get('proxy', '')}")
    return lines

def _finalize_interactive_config(args: argparse.Namespace, platform_id: str, config: dict) -> dict:
    """Apply every non-interactive override before rendering confirmation."""
    finalized = dict(config)
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            parsed = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--config JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("--config 必须是 JSON 对象")
        config_err = validate_config_types(parsed)
        if config_err:
            raise ValueError(config_err)
        finalized.update({key: value for key, value in parsed.items() if value is not None})

    value_overrides = {
        "cookie": "cookie",
        "download_strategy": "download_strategy",
        "referer": "referer",
        "ua": "ua",
        "folder_name": "folder_name",
        "file_name": "file_name",
        "content_type": "content_type",
        "proxy": "proxy",
        "priority": "priority",
    }
    for arg_name, config_name in value_overrides.items():
        value = getattr(args, arg_name, None)
        if value:
            finalized[config_name] = value

    if getattr(args, "use_subdir", None):
        finalized["use_subdir"] = True
    if finalized.get("folder_name") and not finalized.get("use_subdir"):
        finalized["use_subdir"] = True
    if getattr(args, "individual_only", None):
        finalized["individual_only"] = True
    if platform_id == "missav" and finalized.get("proxy") is not None:
        finalized["proxy"] = build_missav_proxy_url(finalized["proxy"])
    return finalized

def _build_interactive_selection(args: argparse.Namespace):
    """Build the TUI selection strategy with the same strict CLI contract."""
    if getattr(args, "pipe", False):
        return PipeSelection()
    if getattr(args, "preload_choices", None):
        return PipeSelection(preloaded_choices=parse_preloaded_choices(args.preload_choices))
    if (
        getattr(args, "select", None)
        or getattr(args, "exclude", None)
        or getattr(args, "select_all", False)
        or getattr(args, "first", False)
        or getattr(args, "last", False)
    ):
        return RuleSelection(
            select=getattr(args, "select", None),
            exclude=getattr(args, "exclude", None),
            all_items=getattr(args, "select_all", False),
            first=getattr(args, "first", False),
            last=getattr(args, "last", False),
        )
    # GUISelection can cross a QApplication boundary from the worker thread.
    # The TUI keeps its stable one-based terminal selection instead.
    return InteractiveTTYSelection()

def _item_display_title(item: dict) -> str:
    """将平台返回的空值或非字符串标题归一化为可安全展示的文本。"""
    return str(item.get("title") or item.get("id") or "未知")


def _print_download_summary(items: list, elapsed: float, save_dir: str) -> None:
    """打印与 GUI 下载队列一致的最终结果摘要。"""
    completed = []
    failed = []
    other = []
    for item in items:
        if not isinstance(item, dict):
            other.append({"title": str(item), "status": ""})
            continue
        status = item.get("status", "")
        local_path = item.get("local_path", "")
        file_completed = False
        if local_path:
            try:
                file_completed = os.path.exists(local_path) and os.path.getsize(local_path) > 0
            except OSError:
                file_completed = False
        if status == "✅ 完成":
            completed.append(item)
        elif status == "❌ 失败":
            failed.append(item)
        elif file_completed:
            snapshot = dict(item)
            snapshot["status"] = "✅ 完成"
            completed.append(snapshot)
        else:
            other.append(item)

    print(f"\n{BOLD}执行完成{RESET}")
    print(f"  总项目: {len(items)}")
    print(f"  已完成: {len(completed)}")
    print(f"  失败:   {len(failed)}")
    print(f"  其他:   {len(other)}")
    print(f"  耗时:   {elapsed:.1f}s")
    print(f"  目录:   {save_dir}")

    if completed:
        print(f"\n{GREEN}已完成:{RESET}")
        for i, item in enumerate(completed, 1):
            title = _item_display_title(item)
            local_path = item.get("local_path", "")
            if len(title) > 60:
                title = title[:57] + "..."
            suffix = f" -> {local_path}" if local_path else ""
            print(f"  {YELLOW}{i}{RESET}. {title}{suffix}")

    if failed:
        print(f"\n{RED}失败项目:{RESET}")
        for i, item in enumerate(failed, 1):
            title = _item_display_title(item)
            meta = item.get("meta")
            error = (meta.get("download_error") if isinstance(meta, dict) else None) or item.get("error", "未知错误")
            if len(title) > 60:
                title = title[:57] + "..."
            print(f"  {YELLOW}{i}{RESET}. {title} ({error})")

    if other:
        print(f"\n{YELLOW}未完成项目:{RESET}")
        for i, item in enumerate(other, 1):
            title = _item_display_title(item) if isinstance(item, dict) else str(item)
            status = item.get("status", "") if isinstance(item, dict) else ""
            local_path = item.get("local_path", "") if isinstance(item, dict) else ""
            if len(title) > 60:
                title = title[:57] + "..."
            if local_path:
                suffix = f" [{status or '状态同步中'}] -> {local_path}"
            else:
                suffix = f" [{status}]" if status else ""
            print(f"  {YELLOW}{i}{RESET}. {title}{suffix}")

def _prompt_post_run_action(save_dir: str, *, allow_repeat: bool = True) -> str:
    """下载或搜索结束后的后续动作。

    Returns:
        "exit" | "same" | "switch"
    """
    options = "o 打开目录 / s 同平台继续 / p 切换平台 / 直接回车结束" if allow_repeat else "o 打开目录 / 直接回车结束"
    while True:
        try:
            choice = input(f"{CYAN}{options}: {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "exit"
        if not choice:
            return "exit"
        if choice in ("o", "open"):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(save_dir)
                    print(f"{GREEN}已打开目录: {save_dir}{RESET}")
                else:
                    print(f"{YELLOW}当前平台不支持自动打开目录: {save_dir}{RESET}")
            except OSError as exc:
                print(f"{RED}❌ 打开目录失败: {exc}{RESET}")
            continue
        if allow_repeat and choice in ("s", "same"):
            return "same"
        if allow_repeat and choice in ("p", "platform", "switch"):
            return "switch"
        print(f"{DIM}无效输入，请重试。{RESET}")

# ============== 主逻辑 ==============

def handle_interactive_command(args: argparse.Namespace) -> int:
    """交互式引导：逐步收集参数后执行搜索/下载。"""
    sdk = UcrawlSDK(verbose=not getattr(args, "quiet", False))
    try:
        try:
            platforms = sdk.list_platforms()
        except Exception as exc:
            sys.stderr.write(f"❌ 获取平台列表失败: {exc}\n")
            return 1

        print(f"\n{BOLD}{BLUE}╔══════════════════════════════════════╗")
        print("║         UCrawl 交互式引导              ║")
        print(f"╚══════════════════════════════════════╝{RESET}\n")

        next_platform_id = None
        default_save_dir = getattr(args, "save_dir", None) or get_default_save_dir()

        while True:
            platform_info = _select_platform(platforms, next_platform_id)
            if platform_info is None:
                return 0

            platform_id = platform_info["id"]
            platform_name = platform_info["name"]
            placeholder = platform_info.get("search_placeholder", "输入关键词或链接")
            guide = _guide_for(platform_id)
            next_platform_id = platform_id
            print(f"  {GREEN}✓ 已选: {platform_name}{RESET}\n")

            print(f"{BOLD}步骤 2/5: 输入搜索内容{RESET}")
            print(f"  {DIM}{guide.get('input_label', placeholder)}{RESET}")
            _print_examples(platform_id)

            try:
                keyword = input(f"{CYAN}搜索: {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return 0

            if not keyword:
                print(f"{RED}❌ 搜索内容不能为空{RESET}")
                return 1
            print(f"  {GREEN}✓ {keyword}{RESET}\n")

            config = get_platform_defaults(platform_id)
            # Interactive mode uses the historical 30s request timeout unless
            # the user overrides it with --config below. Platform crawlers may
            # carry longer GUI defaults, but the CLI prompt contract stays
            # snappier and stable for scripted tests.
            config["timeout"] = 30
            print(f"{BOLD}步骤 3/5: 平台参数{RESET}")

            if platform_id == "douyin":
                current = config.get("max_items", 20)
                opts = ["1", "2", "5", "10", "20", "max (9999)"]
                opt_vals = [1, 2, 5, 10, 20, 9999]
                default_idx = min(range(len(opt_vals)), key=lambda i: abs(opt_vals[i] - current))
                idx = _choose("视频数量", opts, default_idx)
                config["max_items"] = opt_vals[idx]

            elif platform_id == "xiaohongshu":
                current = config.get("max_items", 20)
                opts = ["1", "2", "5", "10", "20", "max (9999)"]
                opt_vals = [1, 2, 5, 10, 20, 9999]
                default_idx = min(range(len(opt_vals)), key=lambda i: abs(opt_vals[i] - current))
                idx = _choose("笔记数量", opts, default_idx)
                config["max_items"] = opt_vals[idx]

            elif platform_id == "bilibili":
                current = config.get("max_pages", 1)
                opts = ["1", "2", "5", "10", "20", "max (500)"]
                opt_vals = [1, 2, 5, 10, 20, 500]
                default_idx = min(range(len(opt_vals)), key=lambda i: abs(opt_vals[i] - current))
                idx = _choose("搜索页数", opts, default_idx)
                config["max_pages"] = opt_vals[idx]

            elif platform_id == "kuaishou":
                current = config.get("max_items", 20)
                opts = ["1", "2", "5", "10", "20", "max (9999)"]
                opt_vals = [1, 2, 5, 10, 20, 9999]
                default_idx = min(range(len(opt_vals)), key=lambda i: abs(opt_vals[i] - current))
                idx = _choose("视频数量", opts, default_idx)
                config["max_items"] = opt_vals[idx]

            elif platform_id == "missav":
                current_individual = config.get("individual_only", False)
                idx = _choose("仅单体作品", ["否", "是"], 0 if not current_individual else 1)
                config["individual_only"] = idx == 1

                current_priority = config.get("priority", "中文字幕优先")
                opts = ["中文字幕优先", "无码流出优先"]
                default_idx = 0 if current_priority == "中文字幕优先" else 1
                idx = _choose("排序偏好", opts, default_idx)
                config["priority"] = opts[idx]

                current_proxy = config.get("proxy", "http://127.0.0.1:7890")
                proxy_presets = ["Clash (7890)", "v2rayN (10809)", "自定义"]
                if "7890" in current_proxy:
                    default_proxy_idx = 0
                elif "10809" in current_proxy:
                    default_proxy_idx = 1
                else:
                    default_proxy_idx = 2
                idx = _choose("代理", proxy_presets, default_proxy_idx)
                if idx < 2:
                    config["proxy"] = build_missav_proxy_url(proxy_presets[idx])
                else:
                    custom = _input("代理地址", current_proxy)
                    config["proxy"] = build_missav_proxy_url(custom)

            print(f"  {DIM}{guide.get('result_tip', '')}{RESET}" if guide.get("result_tip") else "")
            print()

            print(f"{BOLD}步骤 4/5: 保存路径{RESET}")
            print(f"  {DIM}直接回车使用默认路径{RESET}")
            if _is_temp_dir(default_save_dir):
                print(f"  {YELLOW}⚠ 当前配置的保存路径是临时目录，重启后可能丢失{RESET}")
                try:
                    from app.utils.runtime_paths import default_download_root
                    suggested = str(default_download_root())
                except Exception:
                    suggested = str(Path.home() / "Downloads" / "UniversalCrawlerPro")
                print(f"  {DIM}建议使用: {suggested}{RESET}")
                default_save_dir = suggested

            save_dir = _input("保存路径", default_save_dir)
            if not save_dir:
                save_dir = default_save_dir
            default_save_dir = save_dir
            _persist_save_dir(save_dir)
            print(f"  {GREEN}✓ {save_dir}{RESET}\n")

            try:
                config = _finalize_interactive_config(args, platform_id, config)
            except (TypeError, ValueError) as exc:
                sys.stderr.write(f"❌ {exc}\n")
                return 1

            print(f"{BOLD}步骤 5/5: 确认执行{RESET}")
            cookie_data = _load_cookie(platform_id)
            if _AUTH_FILE_MAP.get(platform_id) is None:
                print(f"  Cookie: {DIM}该平台不需要{RESET}")
            elif cookie_data is not None:
                valid = _check_cookie_valid(platform_id, cookie_data)
                cookie_path = _find_cookie_file(platform_id)
                if valid:
                    cookie_name = cookie_path.name if cookie_path is not None else "本地文件"
                    print(f"  Cookie: {GREEN}✓ 本地有效 ({cookie_name}){RESET}")
                else:
                    required = _REQUIRED_COOKIE_KEY.get(platform_id, "")
                    print(f"  Cookie: {YELLOW}⚠ 本地 Cookie 缺少 {required}，搜索时可能需要重新登录{RESET}")
            else:
                login_desc = _LOGIN_DESC.get(platform_id, "将自动弹出浏览器窗口登录")
                print(f"  Cookie: {YELLOW}未检测到本地 Cookie{RESET}")
                print(f"          {DIM}{login_desc}{RESET}")

            print()
            for line in _build_config_summary_lines(platform_id, config, platform_name, keyword, save_dir):
                print(line)
            print()

            try:
                confirm = input(f"{CYAN}确认执行? [Y/n]: {RESET}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return 0

            if confirm in ("n", "no"):
                action = _prompt_post_run_action(save_dir, allow_repeat=True)
                if action == "same":
                    continue
                if action == "switch":
                    next_platform_id = None
                    continue
                return 0

            run_timeout = getattr(args, "run_timeout", None)
            if run_timeout is not None and run_timeout <= 0:
                sys.stderr.write("❌ --run-timeout 必须大于 0\n")
                return 1

            try:
                selection = _build_interactive_selection(args)
            except (TypeError, ValueError) as exc:
                sys.stderr.write(f"❌ {exc}\n")
                return 1

            download = not getattr(args, "no_download", False)
            if run_timeout:
                print(f"  {DIM}超时设置: {run_timeout}s{RESET}")

            print(f"\n{BOLD}正在搜索...{RESET}\n")
            try:
                runner = CLIRunner(
                    source=platform_id,
                    keyword=keyword,
                    save_dir=save_dir,
                    selection_strategy=selection,
                    config=config,
                    verbose=not getattr(args, "quiet", False),
                    log_to_stderr=not getattr(args, "quiet", False),
                    timeout=run_timeout,
                    download=download,
                )
                result = runner.run()
            except Exception as exc:
                sys.stderr.write(f"❌ 搜索失败: {exc}\n")
                return 1

            status = result.get("status", "error")
            if status != "ok":
                error = result.get("error", "未知错误")
                sys.stderr.write(f"❌ {status}: {error}\n")
                return 1

            items = result.get("items", [])
            elapsed = result.get("elapsed", 0)

            if not items:
                print(f"{YELLOW}未找到结果 ({elapsed:.1f}s){RESET}")
                print(f"  {DIM}{guide.get('empty_tip', '可尝试检查关键词、登录状态或平台参数配置。')}{RESET}")
                action = _prompt_post_run_action(save_dir, allow_repeat=True)
                if action == "same":
                    continue
                if action == "switch":
                    next_platform_id = None
                    continue
                return 0

            print(f"\n{GREEN}找到 {len(items)} 个结果 ({elapsed:.1f}s):{RESET}\n")
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    title = _item_display_title(item)
                    content_type = item.get("content_type", "")
                    type_label = {"video": "视频", "gallery": "图集", "image": "图片"}.get(content_type, "")
                    extra = f"  [{type_label}]" if type_label else ""
                    if len(title) > 60:
                        title = title[:57] + "..."
                    print(f"  {YELLOW}{i + 1}{RESET}. {title}{extra}")
                else:
                    print(f"  {YELLOW}{i + 1}{RESET}. {item}")

            if not download and getattr(args, "pretty", False):
                sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                sys.stdout.flush()

            if not download:
                action = _prompt_post_run_action(save_dir, allow_repeat=True)
                if action == "same":
                    continue
                if action == "switch":
                    next_platform_id = None
                    continue
                return 0

            _print_download_summary(items, elapsed, save_dir)
            action = _prompt_post_run_action(save_dir, allow_repeat=True)
            if action == "same":
                continue
            if action == "switch":
                next_platform_id = None
                continue
            return 0
    finally:
        sdk.close()
