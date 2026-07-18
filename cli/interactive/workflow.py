"""Orchestration for the interactive terminal workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cli.exit_codes import CliExitCode, exit_code_for_status
from cli.interactive import configuration, prompts
from cli.interactive.catalog import guide_for
from shared.cli_runner_runtime import CLIRunner
from shared.interactive_selection import InteractiveTTYSelection
from shared.pipe_selection import PipeSelection
from shared.runtime_options import get_default_save_dir, get_platform_defaults
from shared.sdk_runtime import UcrawlSDK
from shared.search_command_runtime import resolve_command_timeout
from shared.selection_runtime import RuleSelection, parse_preloaded_choices


def _build_interactive_selection(args: argparse.Namespace):
    """Build the terminal selection strategy from explicit CLI options."""

    if getattr(args, "pipe", False):
        return PipeSelection()
    if getattr(args, "preload_choices", None):
        return PipeSelection(
            preloaded_choices=parse_preloaded_choices(args.preload_choices)
        )
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
    return InteractiveTTYSelection()


def _resolve_runtime_options(
    args: argparse.Namespace,
) -> tuple[float | None, str | None]:
    """Validate command/HTTP timeouts before constructing the SDK."""

    try:
        command_timeout, legacy_used = resolve_command_timeout(args)
    except ValueError as exc:
        return None, str(exc)
    if command_timeout is not None and command_timeout <= 0:
        return None, "--timeout 必须大于 0"

    http_timeout = getattr(args, "http_timeout", None)
    if http_timeout is not None and http_timeout <= 0:
        return None, "--http-timeout 必须大于 0"
    if legacy_used:
        sys.stderr.write("⚠️ --run-timeout 已弃用，请使用 --timeout\n")
    return command_timeout, None


def _choice_default_index(
    choices: list[dict],
    current: Any,
) -> int:
    """Match an exact value or the closest numeric plugin choice."""

    for index, choice in enumerate(choices):
        if choice.get("value") == current:
            return index

    numeric = [
        (index, choice.get("value"))
        for index, choice in enumerate(choices)
        if isinstance(choice.get("value"), (int, float))
        and not isinstance(choice.get("value"), bool)
    ]
    if (
        numeric
        and isinstance(current, (int, float))
        and not isinstance(current, bool)
    ):
        return min(
            numeric,
            key=lambda pair: abs(pair[1] - current),
        )[0]
    return 0


def _configure_platform(guide: dict, config: dict) -> None:
    """Collect plugin-declared fields without platform-specific branches."""

    for field in guide.get("fields", []):
        if not isinstance(field, dict):
            continue
        choices = [
            choice
            for choice in field.get("choices", [])
            if isinstance(choice, dict)
            and isinstance(choice.get("label"), str)
        ]
        key = field.get("key")
        if not isinstance(key, str) or not choices:
            continue

        selected = prompts.choose(
            str(field.get("prompt") or key),
            [choice["label"] for choice in choices],
            _choice_default_index(choices, config.get(key)),
        )
        choice = choices[selected]
        if choice.get("custom"):
            config[key] = prompts.input_with_default(
                str(
                    field.get("custom_prompt")
                    or field.get("prompt")
                    or key
                ),
                str(config.get(key) or ""),
            )
        else:
            config[key] = choice.get("value")


def _show_cookie_status(auth_spec: dict) -> None:
    """Render the local Cookie preflight without any network validation."""

    mode = configuration.auth_mode(auth_spec)
    if mode == "none":
        print(f"  Cookie: {prompts.DIM}该平台不需要{prompts.RESET}")
        return
    if mode == "unspecified":
        print(
            f"  Cookie: {prompts.DIM}"
            f"插件未声明鉴权规则{prompts.RESET}"
        )
        return

    cookie_data = configuration.load_cookie(auth_spec)
    if cookie_data is None:
        print(f"  Cookie: {prompts.YELLOW}未检测到本地 Cookie{prompts.RESET}")
        print(
            f"          {prompts.DIM}"
            f"{configuration.login_description(auth_spec)}"
            f"{prompts.RESET}"
        )
        return

    cookie_path = configuration.find_cookie_file(auth_spec)
    if configuration.check_cookie_valid(auth_spec, cookie_data):
        cookie_name = cookie_path.name if cookie_path is not None else "本地文件"
        print(
            f"  Cookie: {prompts.GREEN}✓ 本地有效 "
            f"({cookie_name}){prompts.RESET}"
        )
        return

    required = " / ".join(
        configuration.required_cookie_keys(auth_spec)
    )
    print(
        f"  Cookie: {prompts.YELLOW}⚠ 本地 Cookie 缺少 {required}，"
        f"搜索时可能需要重新登录{prompts.RESET}"
    )


def _show_result_items(
    result: dict,
    *,
    guide: dict,
    save_dir: str,
    download: bool,
    pretty: bool,
) -> None:
    """Render no-result, search-only, and download result variants."""

    items = result.get("items", [])
    elapsed = result.get("elapsed", 0)
    if not items:
        print(
            f"{prompts.YELLOW}未找到结果 "
            f"({elapsed:.1f}s){prompts.RESET}"
        )
        empty_tip = guide.get(
            "empty_tip",
            "可尝试检查关键词、登录状态或平台参数配置。",
        )
        print(f"  {prompts.DIM}{empty_tip}{prompts.RESET}")
        return

    print(
        f"\n{prompts.GREEN}找到 {len(items)} 个结果 "
        f"({elapsed:.1f}s):{prompts.RESET}\n"
    )
    for index, item in enumerate(items, 1):
        if isinstance(item, dict):
            title = prompts.item_display_title(item)
            content_type = item.get("content_type", "")
            type_label = {
                "video": "视频",
                "gallery": "图集",
                "image": "图片",
            }.get(content_type, "")
            extra = f"  [{type_label}]" if type_label else ""
            if len(title) > 60:
                title = title[:57] + "..."
            print(
                f"  {prompts.YELLOW}{index}{prompts.RESET}. "
                f"{title}{extra}"
            )
        else:
            print(f"  {prompts.YELLOW}{index}{prompts.RESET}. {item}")

    if not download and pretty:
        sys.stdout.write(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        sys.stdout.flush()
    if download:
        prompts.print_download_summary(items, elapsed, save_dir)


def _suggest_persistent_save_dir(default_save_dir: str) -> str:
    """Replace a temporary default with the application's persistent root."""

    if not configuration.is_temp_dir(default_save_dir):
        return default_save_dir

    print(
        f"  {prompts.YELLOW}⚠ 当前配置的保存路径是临时目录，"
        f"重启后可能丢失{prompts.RESET}"
    )
    try:
        from app.utils.runtime_paths import default_download_root

        suggested = str(default_download_root())
    except Exception:
        suggested = str(
            Path.home() / "Downloads" / "UniversalCrawlerPro"
        )
    print(f"  {prompts.DIM}建议使用: {suggested}{prompts.RESET}")
    return suggested


def _run_interactive_loop(
    args: argparse.Namespace,
    *,
    sdk: Any,
    runner_cls: Any,
    command_timeout: float | None,
) -> int:
    """Run the reusable multi-platform interaction loop."""

    try:
        platforms = sdk.list_platforms()
    except Exception as exc:
        sys.stderr.write(f"❌ 获取平台列表失败: {exc}\n")
        return int(CliExitCode.ERROR)
    if not platforms:
        sys.stderr.write("❌ 没有可用平台\n")
        return int(CliExitCode.ERROR)

    print(
        f"\n{prompts.BOLD}{prompts.BLUE}"
        "╔══════════════════════════════════════╗"
    )
    print("║         UCrawl 交互式引导              ║")
    print(
        "╚══════════════════════════════════════╝"
        f"{prompts.RESET}\n"
    )

    next_platform_id = None
    default_save_dir = (
        getattr(args, "save_dir", None) or get_default_save_dir()
    )

    while True:
        platform_info = prompts.select_platform(
            platforms,
            next_platform_id,
        )
        platform_id = platform_info["id"]
        platform_name = platform_info["name"]
        guide = guide_for(platform_id, platform_info)
        next_platform_id = platform_id
        print(
            f"  {prompts.GREEN}✓ 已选: "
            f"{platform_name}{prompts.RESET}\n"
        )

        print(f"{prompts.BOLD}步骤 2/5: 输入搜索内容{prompts.RESET}")
        print(
            f"  {prompts.DIM}{guide['input_label']}{prompts.RESET}"
        )
        prompts.print_examples(guide)
        keyword = input(f"{prompts.CYAN}搜索: {prompts.RESET}").strip()
        if not keyword:
            sys.stderr.write("❌ 搜索内容不能为空\n")
            return int(CliExitCode.USAGE)
        print(f"  {prompts.GREEN}✓ {keyword}{prompts.RESET}\n")

        config = dict(get_platform_defaults(platform_id))
        config["timeout"] = 30
        print(f"{prompts.BOLD}步骤 3/5: 平台参数{prompts.RESET}")
        _configure_platform(guide, config)
        if guide.get("result_tip"):
            print(
                f"  {prompts.DIM}{guide['result_tip']}"
                f"{prompts.RESET}"
            )
        print()

        print(f"{prompts.BOLD}步骤 4/5: 保存路径{prompts.RESET}")
        print(f"  {prompts.DIM}直接回车使用默认路径{prompts.RESET}")
        default_save_dir = _suggest_persistent_save_dir(default_save_dir)
        save_dir = prompts.input_with_default(
            "保存路径",
            default_save_dir,
        )
        default_save_dir = save_dir

        try:
            config = configuration.finalize_interactive_config(
                args,
                platform_id,
                config,
            )
        except (TypeError, ValueError) as exc:
            sys.stderr.write(f"❌ {exc}\n")
            return int(CliExitCode.USAGE)
        http_timeout = getattr(args, "http_timeout", None)
        if http_timeout is not None:
            config["timeout"] = http_timeout

        configuration.persist_save_dir(save_dir)
        print(f"  {prompts.GREEN}✓ {save_dir}{prompts.RESET}\n")

        print(f"{prompts.BOLD}步骤 5/5: 确认执行{prompts.RESET}")
        _show_cookie_status(guide.get("auth", {}))
        print()
        for line in configuration.build_config_summary_lines(
            guide,
            config,
            platform_name,
            keyword,
            save_dir,
        ):
            print(line)
        print()

        confirm = input(
            f"{prompts.CYAN}确认执行? [Y/n]: {prompts.RESET}"
        ).strip().lower()
        if confirm in ("n", "no"):
            action = prompts.prompt_post_run_action(
                save_dir,
                allow_repeat=True,
            )
            if action == "same":
                continue
            if action == "switch":
                next_platform_id = None
                continue
            return int(CliExitCode.OK)

        try:
            selection = _build_interactive_selection(args)
        except (TypeError, ValueError) as exc:
            sys.stderr.write(f"❌ {exc}\n")
            return int(CliExitCode.USAGE)

        download = not getattr(args, "no_download", False)
        if command_timeout:
            print(
                f"  {prompts.DIM}超时设置: "
                f"{command_timeout}s{prompts.RESET}"
            )
        print(f"\n{prompts.BOLD}正在搜索...{prompts.RESET}\n")
        try:
            runner = runner_cls(
                source=platform_id,
                keyword=keyword,
                save_dir=save_dir,
                selection_strategy=selection,
                config=config,
                verbose=not getattr(args, "quiet", False),
                log_to_stderr=not getattr(args, "quiet", False),
                timeout=command_timeout,
                download=download,
            )
            result = runner.run()
        except Exception as exc:
            sys.stderr.write(f"❌ 搜索失败: {exc}\n")
            return int(CliExitCode.ERROR)

        if not isinstance(result, dict):
            sys.stderr.write("❌ 运行器返回了无效结果\n")
            return int(CliExitCode.ERROR)
        status = str(result.get("status", "error") or "error").lower()
        if status != "ok":
            error = result.get("error", "未知错误")
            sys.stderr.write(f"❌ {status}: {error}\n")
            return int(exit_code_for_status(status))

        _show_result_items(
            result,
            guide=guide,
            save_dir=save_dir,
            download=download,
            pretty=getattr(args, "pretty", False),
        )
        action = prompts.prompt_post_run_action(
            save_dir,
            allow_repeat=True,
        )
        if action == "same":
            continue
        if action == "switch":
            next_platform_id = None
            continue
        return int(CliExitCode.OK)


def run_interactive(
    args: argparse.Namespace,
    *,
    sdk_cls=UcrawlSDK,
    runner_cls=CLIRunner,
) -> int:
    """Run interactive mode with explicit SDK/runner seams for testing."""

    command_timeout, error = _resolve_runtime_options(args)
    if error:
        sys.stderr.write(f"❌ {error}\n")
        return int(CliExitCode.USAGE)

    sdk = sdk_cls(verbose=not getattr(args, "quiet", False))
    try:
        try:
            return _run_interactive_loop(
                args,
                sdk=sdk,
                runner_cls=runner_cls,
                command_timeout=command_timeout,
            )
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return int(CliExitCode.CANCELLED)
    finally:
        sdk.close()
