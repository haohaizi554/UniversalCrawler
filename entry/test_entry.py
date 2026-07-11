"""UCrawl 测试套件入口（薄适配层）。

设计目标（用户原话）：
- 测试入口**不能以 test_ 开头**（pytest 会把它当 test 跑，循环依赖），
  所以入口在 ``entry/`` 下，命名 ``test_entry.py``
- **三模自适应**：GUI / TUI / CLI，按 `tests/test_launcher.py` 的同一份
  逻辑复用，避免代码分散
- 与其他入口对齐：与 ``gui_entry`` / ``web_entry`` / ``cli_entry`` 一样，
  在 ``pyproject.toml`` 的 ``[project.scripts]`` 注册为 ``ucrawl-test``
- 同时通过 ``entry.dispatcher`` 暴露为 ``Mode.TEST``，主 GUI 可一键调用
- **进度条**：GUI 自带 QProgressBar，TUI 用文本进度字符，CLI 用 verbose 模式

调用链：

    ucrawl-test (console_script)
        -> entry.test_entry:main()
        -> tests.test_launcher:run()   # 内部自动选 GUI/TUI/CLI
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Sequence

# 关键：把项目根目录加进 sys.path，使 `from tests.xxx import yyy` 始终可用
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 关键：让 tests/ 下的 test_registry / test_runner / test_launcher 可被 import
_TESTS_DIR = _ROOT / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# 检测 PyQt6 是否可用（模块级）
try:
    import PyQt6.QtWidgets  # noqa: F401
    _PYQT6_AVAILABLE = True
except ImportError:
    _PYQT6_AVAILABLE = False

def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    设计：所有参数都 **可选**，无参数时进入 GUI 模式（让 launcher 自适应）。
    """
    parser = argparse.ArgumentParser(
        prog="ucrawl-test",
        description="UCrawl 测试套件入口（GUI / TUI / CLI 自适应）",
    )
    parser.add_argument(
        "--category", "-c",
        help="测试类别 ID（如 cli_sdk / web_api / app_flows / all / browser_e2e）",
        default=None,
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用测试类别并退出",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="强制 GUI 模式（无显示器时自动回退到 TUI）",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="强制 TUI 模式（input() 菜单）",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="强制 CLI 模式（无界面，直接跑指定类别）",
    )
    parser.add_argument(
        "--no-failfast",
        action="store_true",
        help="遇失败不停止（用于收集所有错误）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )
    parser.add_argument(
        "--plugin-dir",
        action="append",
        default=[],
        help="追加一个测试插件目录（可多次指定，格式: id:name:path）",
    )
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        help="追加一个测试插件类别（格式: id:name:file1,file2,...）",
    )
    return parser.parse_args(argv)

def _apply_plugin_args(plugin_dirs: list[str], plugins: list[str]) -> None:
    """把 --plugin-dir / --plugin 转换为注册表调用。"""
    from tests.test_registry import register_plugin_directory, register_category

    for spec in plugin_dirs:
        # 格式: id:name:path
        parts = spec.split(":", 2)
        if len(parts) != 3:
            sys.stderr.write(f"⚠️  --plugin-dir 格式错误: {spec!r}（应为 id:name:path）\n")
            continue
        cid, name, path = parts
        try:
            register_plugin_directory(
                category_id=cid.strip(),
                name=name.strip(),
                directory=path.strip(),
            )
        except Exception as exc:
            sys.stderr.write(f"⚠️  --plugin-dir 失败: {spec!r}: {exc}\n")

    for spec in plugins:
        # 格式: id:name:file1,file2
        parts = spec.split(":", 2)
        if len(parts) != 3:
            sys.stderr.write(f"⚠️  --plugin 格式错误: {spec!r}（应为 id:name:file1,file2）\n")
            continue
        cid, name, files_str = parts
        files = [f.strip() for f in files_str.split(",") if f.strip()]
        try:
            register_category(
                id=cid.strip(),
                name=name.strip(),
                description=f"命令行注册: {', '.join(files)}",
                files=files,
            )
        except Exception as exc:
            sys.stderr.write(f"⚠️  --plugin 失败: {spec!r}: {exc}\n")

def _run_list() -> int:
    """列出所有可用测试类别并退出。"""
    from tests.test_registry import (
        get_enabled_categories,
        summary,
        list_plugin_directories,
    )
    s = summary()
    print("=" * 70)
    print(" UCrawl 测试套件 - 注册表")
    print("=" * 70)
    print(f" 类别总数:   {s['total_categories']}")
    print(f" 启用类别:   {s['enabled_categories']}")
    print(f" 测试文件:   {s['total_files']}")
    print(f" 插件目录:   {len(s['plugin_directories'])}")
    print()
    print(f"{'ID':<14} {'名称':<14} {'文件':<6} {'GUI':<5} {'网络':<5} 描述")
    print("-" * 90)
    for c in get_enabled_categories():
        gui = "✓" if c.requires_gui else " "
        net = "✓" if c.requires_network else " "
        print(
            f"{c.id:<14} {c.name:<14} "
            f"{c.file_count():<6} {gui:<5} {net:<5} {c.description}"
        )
    if s["plugin_directories"]:
        print()
        print("插件目录:")
        for cid, path in list_plugin_directories().items():
            print(f"  - {cid}: {path}")
    return 0

def _run_gui(category: str | None, no_failfast: bool, verbose: bool) -> int:
    """弹 Qt 测试启动器。

    关键修复（2026-06-06 / 二轮）：
    - 先用 ``QApplication.instance()`` 强引用，避免被 GC 后元类型错位
    - 捕获具体异常类型，分层回退（PyQt6 缺失 → 其它错误 → 全部 TUI）
    - 不在 QApplication 上 setStyleSheet（移到 LauncherWindow 构造函数内）
    """
    if not _PYQT6_AVAILABLE:
        sys.stderr.write("⚠️  PyQt6 未安装，回退到 TUI 模式\n")
        return _run_tui(category, no_failfast, verbose)

    try:
        from tests.test_launcher import _build_gui, LauncherWindow  # noqa
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        sys.stderr.write(f"⚠️  导入 PyQt6 失败: {exc}，回退到 TUI 模式\n")
        return _run_tui(category, no_failfast, verbose)

    # 关键：先确保 QApplication 存在（强引用保存到 test_launcher._APP_REF）
    app = QApplication.instance()
    if app is None:
        # 必须先创建 QApplication 再创建 QWidget
        try:
            app = QApplication(sys.argv)
        except Exception as exc:
            sys.stderr.write(f"⚠️  创建 QApplication 失败: {exc}，回退到 TUI 模式\n")
            return _run_tui(category, no_failfast, verbose)

    # 调 _build_gui
    try:
        window = _build_gui()
    except Exception as exc:
        sys.stderr.write(f"⚠️  GUI 模式不可用（_build_gui）: {exc}\n")
        sys.stderr.write("   回退到 TUI 模式\n")
        traceback.print_exc(file=sys.stderr)
        return _run_tui(category, no_failfast, verbose)

    # 调 window.show
    try:
        window.show()
    except (RuntimeError, Exception) as exc:
        # 关键：捕获 sip "wrapped C/C++ object has been deleted" 错误
        err_str = str(exc)
        if "deleted" in err_str.lower() or "wrapped" in err_str.lower():
            sys.stderr.write(f"⚠️  GUI 模式不可用（C++ 对象已被删除）: {exc}\n")
        else:
            sys.stderr.write(f"⚠️  GUI 模式不可用: {exc}\n")
        sys.stderr.write("   回退到 TUI 模式\n")
        traceback.print_exc(file=sys.stderr)
        return _run_tui(category, no_failfast, verbose)

    # 进入事件循环
    try:
        return app.exec()
    except Exception as exc:
        sys.stderr.write(f"⚠️  GUI 事件循环异常: {exc}\n")
        traceback.print_exc(file=sys.stderr)
        return _run_tui(category, no_failfast, verbose)

def _run_tui(category: str | None, no_failfast: bool, verbose: bool) -> int:
    """TUI 菜单模式。"""
    from tests.test_registry import get_enabled_categories, get_resolved_files
    from tests.test_runner import run_category, format_summary, TestResult

    if category:
        # 直接跑指定类别
        cats = get_enabled_categories()
        cat_map = {c.id: c for c in cats}
        if category not in cat_map:
            sys.stderr.write(f"❌ 未知类别: {category!r}\n")
            sys.stderr.write(f"   可用: {', '.join(cat_map.keys())}\n")
            return 2
        cat = cat_map[category]
        files = get_resolved_files(category)
        print(f"\n[类别] {cat.name} ({len(files)} 文件)")
        res = run_category(
            category_id=cat.id,
            category_name=cat.name,
            files=files,
            verbose=verbose,
            no_failfast=no_failfast,
        )
        print(format_summary([res]))
        return 0 if res.success else 1

    # 多选菜单
    cats = get_enabled_categories()
    print()
    print("=" * 70)
    print(" UCrawl 测试套件 - TUI 菜单")
    print("=" * 70)
    for i, c in enumerate(cats, 1):
        marker = " ⭐" if c.id == "all" else ""
        print(
            f"  [{i:>2}] {c.name:<14} ({c.file_count():>2} 文件)  "
            f"{c.description[:50]}{marker}"
        )
    print()
    print("  [a ]  全量（运行全部测试）")
    print("  [r ]  推荐（cli_sdk + web_api + app_flows + pipeline + core_services）")
    print("  [q ]  退出")
    print()

    try:
        raw = input("请选择 [1-N / a / r / q]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if raw in ("q", "quit", "exit", "0"):
        return 0
    if raw == "a":
        selected = ["all"]
    elif raw == "r":
        selected = ["cli_sdk", "web_api", "app_flows", "pipeline", "core_services"]
    else:
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(cats):
                selected = [cats[idx].id]
            else:
                print(f"❌ 超出范围: {raw}")
                return 1
        except ValueError:
            print(f"❌ 无效输入: {raw!r}")
            return 1

    print(f"\n将运行: {', '.join(selected)}")
    print()

    results: list[TestResult] = []
    for cid in selected:
        cat_map = {c.id: c for c in cats}
        cat = cat_map[cid]
        files = get_resolved_files(cid)
        print(f"\n[类别] {cat.name} ({len(files)} 文件)")
        res = run_category(
            category_id=cid,
            category_name=cat.name,
            files=files,
            verbose=verbose,
            no_failfast=no_failfast,
        )
        results.append(res)
        if not no_failfast and not res.success:
            print("❌ 遇失败停止")
            break

    print()
    print(format_summary(results))
    return 0 if all(r.success for r in results) else 1

def _run_cli(category: str, no_failfast: bool, verbose: bool) -> int:
    """CLI 模式：直接跑指定类别。"""
    from tests.test_registry import get_enabled_categories, get_resolved_files
    from tests.test_runner import run_category, format_summary

    cats = get_enabled_categories()
    cat_map = {c.id: c for c in cats}
    if category not in cat_map:
        sys.stderr.write(f"❌ 未知类别: {category!r}\n")
        sys.stderr.write(f"   可用: {', '.join(cat_map.keys())}\n")
        return 2

    cat = cat_map[category]
    files = get_resolved_files(category)
    print(f"[类别] {cat.name} ({len(files)} 文件)")
    res = run_category(
        category_id=cat.id,
        category_name=cat.name,
        files=files,
        verbose=verbose,
        no_failfast=no_failfast,
    )
    print(format_summary([res]))
    return 0 if res.success else 1

def _detect_mode(args: argparse.Namespace) -> str:
    """根据参数和上下文选择运行模式：gui / tui / cli。"""
    if args.gui:
        return "gui"
    if args.tui:
        return "tui"
    if args.cli:
        return "cli"
    # 自适应：有 category → cli（无交互），否则按环境选 gui / tui
    if args.category:
        return "cli"
    # 检查 Qt 是否可用
    try:
        import PyQt6.QtWidgets  # noqa: F401
        has_qt = True
    except Exception:
        has_qt = False
    if not has_qt:
        return "tui"
    # 检查 TTY（与 dispatcher.is_tty() 逻辑一致）
    try:
        if sys.stdin.isatty() or sys.stdout.isatty():
            return "gui"  # TTY 时直接弹 GUI（与 dispatcher 不同的策略）
    except Exception:
        pass
    return "gui"

def main(argv: Sequence[str] | None = None) -> int:
    """测试入口主函数。

    三模自适应：GUI / TUI / CLI。

    退出码：
        0 = 全部通过 / 用户主动退出
        1 = 有测试失败
        2 = 参数错误 / 不可恢复
    """
    args = _parse_args(argv)

    # 处理 --plugin-dir / --plugin（在导入 launcher 前注册）
    if args.plugin_dir or args.plugin:
        _apply_plugin_args(args.plugin_dir, args.plugin)

    # --list 优先
    if args.list:
        return _run_list()

    # 决定模式
    mode = _detect_mode(args)

    if mode == "gui":
        # GUI 模式：用 test_launcher 弹窗（如果指定 category，则先预选）
        return _run_gui(args.category, args.no_failfast, args.verbose)
    elif mode == "tui":
        return _run_tui(args.category, args.no_failfast, args.verbose)
    elif mode == "cli":
        if not args.category:
            sys.stderr.write("❌ CLI 模式需要 --category\n")
            return 2
        return _run_cli(args.category, args.no_failfast, args.verbose)
    else:
        sys.stderr.write(f"❌ 未知模式: {mode}\n")
        return 2

# 暴露给 dispatcher 用的别名
run = main

if __name__ == "__main__":
    sys.exit(main())
