"""Terminal input and presentation helpers for interactive mode."""

from __future__ import annotations

import os

BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BLUE = "\033[94m"


def input_with_default(prompt: str, default: str = "") -> str:
    """Read terminal input, using the supplied default for an empty line."""

    hint = f" [{default}]" if default else ""
    raw = input(f"{CYAN}{prompt}{hint}: {RESET}").strip()
    return raw if raw else default


def choose(prompt: str, options: list[str], default_idx: int = 0) -> int:
    """Render a numbered menu and retry until the choice is valid."""

    while True:
        print(f"{BOLD}{prompt}{RESET}")
        for index, option in enumerate(options):
            marker = ">" if index == default_idx else " "
            print(f"  {marker} {YELLOW}{index + 1}{RESET}. {option}")
        raw = input(f"{CYAN}选择 (回车={default_idx + 1}): {RESET}").strip()
        if not raw:
            return default_idx
        try:
            index = int(raw) - 1
            if 0 <= index < len(options):
                return index
        except ValueError:
            pass
        print(f"  {DIM}无效选择，请重新输入。{RESET}")


def select_platform(
    platforms: list[dict],
    next_platform_id: str | None = None,
) -> dict:
    """Select a platform, optionally reusing the previous one."""

    cached = None
    if next_platform_id:
        cached = next(
            (item for item in platforms if item.get("id") == next_platform_id),
            None,
        )
    if cached is not None:
        print(f"{BOLD}步骤 1/5: 选择平台{RESET}")
        print(f"  {GREEN}✓ 继续使用: {cached['name']}{RESET}\n")
        return cached

    while True:
        print(f"{BOLD}步骤 1/5: 选择平台{RESET}\n")
        for index, platform in enumerate(platforms, 1):
            placeholder = platform.get("search_placeholder", "")
            hint = f"  {DIM}({placeholder}){RESET}" if placeholder else ""
            print(
                f"  {YELLOW}{index}{RESET}. "
                f"{BOLD}{platform['name']}{RESET} ({platform['id']}){hint}"
            )
        print()

        choice = input(f"{CYAN}请输入编号: {RESET}").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(platforms):
                return platforms[index]
        except ValueError:
            pass
        print(f"{DIM}无效选择，请重新输入。{RESET}\n")


def print_examples(guide: dict) -> None:
    """Print any examples carried by a catalog guide."""

    examples = list(guide.get("examples", ()))
    if not examples:
        return
    print("  \u793a\u4f8b:")
    for example in examples:
        print(f"    {DIM}{example}{RESET}")


def item_display_title(item: dict) -> str:
    """Normalize empty or non-string result titles for display."""

    return str(item.get("title") or item.get("id") or "未知")


def print_download_summary(items: list, elapsed: float, save_dir: str) -> None:
    """Render completed, failed, and unfinished download groups."""

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
                file_completed = (
                    os.path.exists(local_path) and os.path.getsize(local_path) > 0
                )
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
        for index, item in enumerate(completed, 1):
            title = item_display_title(item)
            local_path = item.get("local_path", "")
            if len(title) > 60:
                title = title[:57] + "..."
            suffix = f" -> {local_path}" if local_path else ""
            print(f"  {YELLOW}{index}{RESET}. {title}{suffix}")

    if failed:
        print(f"\n{RED}失败项目:{RESET}")
        for index, item in enumerate(failed, 1):
            title = item_display_title(item)
            meta = item.get("meta")
            error = (
                meta.get("download_error") if isinstance(meta, dict) else None
            ) or item.get("error", "未知错误")
            if len(title) > 60:
                title = title[:57] + "..."
            print(f"  {YELLOW}{index}{RESET}. {title} ({error})")

    if other:
        print(f"\n{YELLOW}未完成项目:{RESET}")
        for index, item in enumerate(other, 1):
            title = item_display_title(item)
            status = item.get("status", "")
            local_path = item.get("local_path", "")
            if len(title) > 60:
                title = title[:57] + "..."
            if local_path:
                suffix = f" [{status or '状态同步中'}] -> {local_path}"
            else:
                suffix = f" [{status}]" if status else ""
            print(f"  {YELLOW}{index}{RESET}. {title}{suffix}")


def prompt_post_run_action(
    save_dir: str,
    *,
    allow_repeat: bool = True,
) -> str:
    """Return ``exit``, ``same``, or ``switch`` after a completed run."""

    options = (
        "o 打开目录 / s 同平台继续 / p 切换平台 / 直接回车结束"
        if allow_repeat
        else "o 打开目录 / 直接回车结束"
    )
    while True:
        choice = input(f"{CYAN}{options}: {RESET}").strip().lower()
        if not choice:
            return "exit"
        if choice in ("o", "open"):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(save_dir)
                    print(f"{GREEN}已打开目录: {save_dir}{RESET}")
                else:
                    print(
                        f"{YELLOW}当前平台不支持自动打开目录: "
                        f"{save_dir}{RESET}"
                    )
            except OSError as exc:
                print(f"{RED}❌ 打开目录失败: {exc}{RESET}")
            continue
        if allow_repeat and choice in ("s", "same"):
            return "same"
        if allow_repeat and choice in ("p", "platform", "switch"):
            return "switch"
        print(f"{DIM}无效输入，请重试。{RESET}")
