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
import tempfile
from pathlib import Path

from cli.defaults import get_platform_defaults, get_default_save_dir, build_missav_proxy_url
from cli.sdk import UcrawlSDK


# ============== 颜色常量 ==============

BOLD  = "\033[1m"
RESET = "\033[0m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED   = "\033[91m"
DIM   = "\033[2m"
BLUE  = "\033[94m"


# ============== Cookie 智能检测（与 GUI spider 对齐） ==============

# 平台 → auth 文件名映射（与 app/config/settings.py AuthSettings 对齐）
_AUTH_FILE_MAP = {
    "douyin":   "dy_auth.json",
    "bilibili": "bili_auth.json",
    "kuaishou": "ks_auth.json",
    "missav":   None,  # MissAV 不需要 cookie
}

# 平台 → 必需的 cookie key（与 GUI spider 对齐）
_REQUIRED_COOKIE_KEY = {
    "douyin":   "sessionid_ss",
    "bilibili": "SESSDATA",
    "kuaishou": "kuaishou.server.web_st",
}

# 平台 → 登录方式描述（与 GUI spider 实现对齐）
_LOGIN_DESC = {
    "douyin":   "抖音将自动弹出浏览器窗口，请扫码登录",
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
    try:
        from app.config.constants import USER_DATA_ROOT
        candidates.append(Path(USER_DATA_ROOT) / auth_name)
    except Exception:
        pass
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
    parser.add_argument("--folder-name", type=str, default=None, help="子目录名 (与 --config '{\"folder_name\":\"...\"}' 等价，B站合集场景)")
    parser.add_argument("--use-subdir", action="store_true", default=None, help="使用子目录保存 (与 --config '{\"use_subdir\":true}' 等价)")
    # 与 GUI spider build_download_meta 对齐：文件名控制
    parser.add_argument("--file-name", type=str, default=None, help="输出文件名 (与 --config '{\"file_name\":\"...\"}' 等价，不含扩展名)")
    # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：内容类型控制
    parser.add_argument("--content-type", type=str, default=None, help="内容类型 (video/image/gallery，与 --config '{\"content_type\":\"gallery\"}' 等价，影响文件扩展名和保存路径)")


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
    print(f"  {DIM}无效选择，使用默认{RESET}")
    return default_idx


def _is_temp_dir(path: str) -> bool:
    """检测路径是否是系统临时目录。"""
    try:
        temp_root = tempfile.gettempdir().lower()
        if path.lower().startswith(temp_root):
            return True
    except Exception:
        pass
    # 常见临时目录模式
    lower = path.lower().replace("\\", "/")
    return "/temp/tmp" in lower or "/tmp/" in lower or "appdata/local/temp" in lower


# ============== 主逻辑 ==============

def handle_interactive_command(args: argparse.Namespace) -> int:
    """交互式引导：逐步收集参数后执行搜索/下载。"""
    sdk = UcrawlSDK(verbose=True)
    try:
        platforms = sdk.list_platforms()
    except Exception as exc:
        sys.stderr.write(f"❌ 获取平台列表失败: {exc}\n")
        sdk.close()
        return 1

    # ---- 步骤 1: 选择平台 ----
    print(f"\n{BOLD}{BLUE}╔══════════════════════════════════════╗")
    print(f"║     UCrawl 交互式引导                  ║")
    print(f"╚══════════════════════════════════════╝{RESET}\n")

    print(f"{BOLD}步骤 1/5: 选择平台{RESET}\n")
    for i, p in enumerate(platforms, 1):
        placeholder = p.get("search_placeholder", "")
        hint = f"  {DIM}({placeholder}){RESET}" if placeholder else ""
        print(f"  {YELLOW}{i}{RESET}. {BOLD}{p['name']}{RESET} ({p['id']}){hint}")
    print()

    try:
        choice = input(f"{CYAN}请输入编号: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消"); sdk.close(); return 0

    try:
        idx = int(choice) - 1
        platform_info = platforms[idx]
    except (ValueError, IndexError):
        print(f"{RED}❌ 无效选择: {choice}{RESET}"); sdk.close(); return 1

    platform_id = platform_info["id"]
    platform_name = platform_info["name"]
    placeholder = platform_info.get("search_placeholder", "输入关键词或链接")
    print(f"  {GREEN}✓ 已选: {platform_name}{RESET}\n")

    # ---- 步骤 2: 输入关键词（提示沿用 GUI placeholder） ----
    print(f"{BOLD}步骤 2/5: 输入搜索内容{RESET}")
    print(f"  {DIM}{placeholder}{RESET}")

    try:
        keyword = input(f"{CYAN}搜索: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消"); sdk.close(); return 0

    if not keyword:
        print(f"{RED}❌ 搜索内容不能为空{RESET}"); sdk.close(); return 1
    print(f"  {GREEN}✓ {keyword}{RESET}\n")

    # ---- 步骤 3: 平台参数配置（与 GUI 设置面板对齐） ----
    config = get_platform_defaults(platform_id)

    print(f"{BOLD}步骤 3/5: 平台参数{RESET}")

    if platform_id == "douyin":
        current = config.get("max_items", 20)
        opts = ["1", "2", "5", "10", "20", "max (9999)"]
        opt_vals = [1, 2, 5, 10, 20, 9999]
        default_idx = min(range(len(opt_vals)), key=lambda i: abs(opt_vals[i] - current))
        idx = _choose("视频数量", opts, default_idx)
        config["max_items"] = opt_vals[idx]
        config["timeout"] = 10

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

    print()

    # ---- 步骤 4: 保存路径 ----
    print(f"{BOLD}步骤 4/5: 保存路径{RESET}")

    default_save_dir = getattr(args, "save_dir", None) or get_default_save_dir()

    # 检测临时目录
    if _is_temp_dir(default_save_dir):
        print(f"  {YELLOW}⚠ 当前配置的保存路径是临时目录，重启后可能丢失{RESET}")
        # 建议更好的默认路径
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
    print(f"  {GREEN}✓ {save_dir}{RESET}\n")

    # ---- 步骤 5: Cookie 状态 + 确认 ----
    print(f"{BOLD}步骤 5/5: 确认执行{RESET}")

    # Cookie 状态检测（与 GUI spider 对齐）
    cookie_data = _load_cookie(platform_id)
    if _AUTH_FILE_MAP.get(platform_id) is None:
        # MissAV 不需要 cookie
        print(f"  Cookie: {DIM}该平台不需要{RESET}")
    elif cookie_data is not None:
        valid = _check_cookie_valid(platform_id, cookie_data)
        cookie_path = _find_cookie_file(platform_id)
        if valid:
            cookie_str = _build_cookie_string(cookie_data)
            if cookie_str:
                config["cookie"] = cookie_str
            print(f"  Cookie: {GREEN}✓ 本地有效 ({cookie_path.name}){RESET}")
        else:
            required = _REQUIRED_COOKIE_KEY.get(platform_id, "")
            cookie_str = _build_cookie_string(cookie_data)
            if cookie_str:
                config["cookie"] = cookie_str
            print(f"  Cookie: {YELLOW}⚠ 本地 Cookie 缺少 {required}，搜索时可能需要重新登录{RESET}")
    else:
        # 没有 cookie，告知 spider 会自动弹出登录窗口
        login_desc = _LOGIN_DESC.get(platform_id, "将自动弹出浏览器窗口登录")
        print(f"  Cookie: {YELLOW}未检测到本地 Cookie{RESET}")
        print(f"          {DIM}{login_desc}{RESET}")

    # 显示确认信息
    max_items = config.get("max_items", config.get("max_pages", 20))
    print(f"\n  平台:   {platform_name}")
    print(f"  关键词: {keyword}")
    print(f"  数量:   {max_items}")
    print(f"  保存到: {save_dir}")

    if platform_id == "missav":
        print(f"  偏好:   {config.get('priority', '')}")
        print(f"  仅单体: {'是' if config.get('individual_only') else '否'}")
        print(f"  代理:   {config.get('proxy', '')}")

    print()

    try:
        confirm = input(f"{CYAN}确认执行? [Y/n]: {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消"); sdk.close(); return 0

    if confirm in ("n", "no"):
        print("已取消"); sdk.close(); return 0

    # ---- 合并 --config JSON 到 config（与 search 命令 _build_config 对齐） ----
    config_json = getattr(args, "config", None)
    if config_json:
        try:
            user_config = json.loads(config_json)
            if isinstance(user_config, dict):
                filtered = {k: v for k, v in user_config.items() if v is not None}
                config.update(filtered)
        except json.JSONDecodeError:
            pass  # 校验在下面完成
        # 校验 --config JSON 格式
        try:
            parsed = json.loads(config_json)
            if not isinstance(parsed, dict):
                sys.stderr.write("❌ --config 必须是 JSON 对象\n")
                sdk.close(); return 1
        except json.JSONDecodeError as e:
            sys.stderr.write(f"❌ --config JSON 解析失败: {e}\n")
            sdk.close(); return 1
        # 与 SDK _validate_config 对齐：校验已知参数类型
        from cli.defaults import validate_config_types
        config_err = validate_config_types(parsed)
        if config_err:
            sys.stderr.write(f"❌ {config_err}\n")
            sdk.close(); return 1

    # ---- 合并便捷参数到 config（与 search 命令 _build_config 对齐，优先级最高） ----
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
    # 与 GUI spider build_download_meta 对齐：文件名控制
    if getattr(args, "file_name", None):
        config["file_name"] = args.file_name
    # 与 GUI spider build_download_meta 和 DownloadWorker 对齐：内容类型控制
    if getattr(args, "content_type", None):
        config["content_type"] = args.content_type


    # ---- 校验 --run-timeout（与 search 命令对齐） ----
    run_timeout = getattr(args, "run_timeout", None)
    if run_timeout is not None and run_timeout <= 0:
        sys.stderr.write("❌ --run-timeout 必须大于 0\n")
        sdk.close(); return 1

    # ---- 构建二次选择策略（交互式引导默认使用 GUI 弹窗，与 GUI 体验一致） ----
    from cli.selection import RuleSelection, PipeSelection, InteractiveTTYSelection
    if getattr(args, "pipe", False):
        selection = PipeSelection()
    elif getattr(args, "preload_choices", None):
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
        selection = PipeSelection(preloaded_choices=rounds)
    elif getattr(args, "select", None) or getattr(args, "exclude", None) or getattr(args, "select_all", False) or getattr(args, "first", False) or getattr(args, "last", False):
        # 用户显式指定了选择规则，使用 RuleSelection
        selection = RuleSelection(
            select=getattr(args, "select", None),
            exclude=getattr(args, "exclude", None),
            all_items=getattr(args, "select_all", False),
            first=getattr(args, "first", False),
            last=getattr(args, "last", False),
        )
    else:
        # 交互式引导默认使用终端交互选择（CLI 环境下 GUISelection 会弹窗，不适合纯终端场景）
        selection = InteractiveTTYSelection()

    # ---- 执行搜索 ----
    download = not getattr(args, "no_download", False)
    verbose = not getattr(args, "quiet", False)

    if run_timeout:
        print(f"  {DIM}超时设置: {run_timeout}s{RESET}")

    print(f"\n{BOLD}正在搜索...{RESET}\n")
    try:
        result = sdk.search(
            source=platform_id,
            keyword=keyword,
            save_dir=save_dir,
            download=download,
            selection=selection,
            run_timeout=run_timeout,
            **config,
        )
    except Exception as exc:
        sys.stderr.write(f"❌ 搜索失败: {exc}\n")
        sdk.close(); return 1

    # ---- 处理结果 ----
    status = result.get("status", "error")
    if status != "ok":
        error = result.get("error", "未知错误")
        sys.stderr.write(f"❌ {status}: {error}\n")
        sdk.close(); return 1

    items = result.get("items", [])
    elapsed = result.get("elapsed", 0)

    if not items:
        print(f"{YELLOW}未找到结果 ({elapsed:.1f}s){RESET}")
        print(f"  {DIM}提示：检查关键词是否正确，或尝试添加 Cookie{RESET}")
        sdk.close(); return 0

    # 显示结果
    print(f"\n{GREEN}找到 {len(items)} 个结果 ({elapsed:.1f}s):{RESET}\n")
    for i, item in enumerate(items):
        if isinstance(item, dict):
            title = item.get("title", item.get("id", "未知"))
            content_type = item.get("content_type", "")
            type_label = {"video": "视频", "gallery": "图集", "image": "图片"}.get(content_type, "")
            extra = f"  [{type_label}]" if type_label else ""
            if len(title) > 60:
                title = title[:57] + "..."
            print(f"  {YELLOW}{i}{RESET}. {title}{extra}")
        else:
            print(f"  {YELLOW}{i}{RESET}. {item}")

    # --no-download + --pretty 时输出 JSON 格式的搜索结果（与 search 命令对齐）
    if not download and getattr(args, "pretty", False):
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()

    # 下载选择
    if not download:
        sdk.close(); return 0

    print()
    try:
        sel = input(
            f"{CYAN}选择下载（编号,逗号分隔 / a=全选 / q=退出）: {RESET}"
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消"); sdk.close(); return 0

    if sel in ("q", "quit", ""):
        sdk.close(); return 0

    if sel in ("a", "all"):
        indices = list(range(len(items)))
    else:
        try:
            indices = [int(x.strip()) for x in sel.split(",") if x.strip()]
        except ValueError:
            print(f"{RED}❌ 无效选择{RESET}"); sdk.close(); return 1

    # 下载（与 CLI download 命令和 REST API /api/download 对齐）
    download_timeout = run_timeout or 300
    # 从搜索 config 中提取下载相关配置（与 GUI spider meta 对齐）
    # 与 SDK download_video meta 复制列表对齐：referer/ua/content_type/cookie/cookies/proxy/download_strategy/folder_name/use_subdir/audio_url/aweme_id/bvid/cid/file_name/preferred_filename/is_gallery/is_mix/images_data/size_mb/media_label/duration/mix_title/create_time/author/has_live_photo
    download_config = {}
    for key in ("proxy", "referer", "ua", "content_type", "cookie", "cookies", "download_strategy", "folder_name", "use_subdir", "audio_url", "aweme_id", "bvid", "cid", "file_name", "preferred_filename", "is_gallery", "is_mix", "images_data", "size_mb", "media_label", "duration", "mix_title", "create_time", "author", "has_live_photo"):
        if key in config and config[key] is not None:
            download_config[key] = config[key]

    error_count = 0
    for idx in indices:
        if 0 <= idx < len(items):
            item = items[idx]
            if isinstance(item, dict):
                item_url = item.get("url", "")
                item_title = item.get("title", item.get("id", "未知"))
            else:
                item_url = str(item)
                item_title = str(item)
            print(f"  下载: {item_title}")
            try:
                dl_result = sdk.download_video(
                    url=item_url,
                    source=platform_id,
                    title=item_title,
                    save_dir=save_dir,
                    timeout=download_timeout,
                    config=download_config if download_config else None,
                    verbose=verbose,
                )
                # 检查下载结果（与 CLI download 命令对齐）
                dl_status = dl_result.get("status", "error")
                if dl_status != "ok":
                    error_msg = dl_result.get("error", "未知错误")
                    # 区分超时和其他错误（与 CLI download _print_pretty 对齐）
                    if dl_status == "timeout" or "超时" in error_msg:
                        sys.stderr.write(f"  ❌ 下载超时: {error_msg}\n")
                    else:
                        sys.stderr.write(f"  ❌ 下载失败: {error_msg}\n")
                    error_count += 1
            except (TypeError, ValueError) as exc:
                sys.stderr.write(f"  ❌ 参数错误: {exc}\n")
                error_count += 1
            except Exception as exc:
                sys.stderr.write(f"  ❌ 下载失败: {exc}\n")
                error_count += 1

    sdk.close()
    return 1 if error_count > 0 and error_count == len(indices) else 0
