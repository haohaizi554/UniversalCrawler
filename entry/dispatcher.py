"""UCrawl 自适应入口调度器。

设计目标（行业最佳实践 + 用户需求）：

- **无参数运行** `python main.py`：弹出 TUI 菜单让用户**手动选 4 个入口之一**
- **有参数运行** `python main.py [args]`：**自适应检测**参数意图并自动派发
  - `--mode xxx` / `-m xxx` → 强制指定
  - `UCRAWL_MODE` 环境变量 → 强制指定
  - 子命令 `search`/`scan`/`download`/`platforms`/`interactive` → CLI
  - `--port`/`--host`/`--script` → Web
  - `--no-qt` → GUI
  - `--save-dir`/`--no-download`/`--pretty` → Interactive
  - 其它位置参数 → CLI

注意：
- 这是**纯调度**模块，不写任何业务逻辑
- 每个 mode 实际逻辑在 cli_entry.py / gui_entry.py / web_entry.py / interactive_entry.py
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon

class Mode(str, Enum):
    """UCrawl 支持的所有运行模式。"""

    GUI = "gui"                  # 桌面 GUI (PyQt6)
    WEB = "web"                  # Web UI  (FastAPI + 浏览器)
    CLI = "cli"                  # 命令行 (单次执行后退出)
    INTERACTIVE = "interactive"  # 交互式引导 (逐步选择)
    TEST = "test"                # 测试套件 (GUI/TUI/CLI 三模)

class _MenuUnavailable(Exception):
    """TUI 菜单无法显示（环境非交互）。

    dispatcher.run() 捕获此异常后以 exit code 2 退出，
    区别于用户主动选 q 的退出码 0。
    """
    pass

# ---- 各 mode 的参数特征（用于有参自适应检测） ----

# CLI 子命令（ucrawl 自身的 argparse 子命令）
_CLI_SUBCOMMANDS = frozenset({
    "search", "scan", "download", "platforms",
    "douyin", "dy", "bilibili", "bili", "bl",
    "kuaishou", "ks", "missav", "miss",
})

# Web 模式专属参数
_WEB_FLAGS = frozenset({
    "--port", "--host", "--script", "--script-arg", "--script-strict",
    "--script-delay", "--no-browser",
})

# GUI 模式专属参数（仅 web 模式会带 --no-qt；裸 GUI 模式不需要参数）
_GUI_FLAGS = frozenset({
    "--no-qt",  # 仅 web_entry 接受，但若其它参数与 GUI 行为冲突，提示用户
})

# Interactive 模式专属参数
_INTERACTIVE_FLAGS = frozenset({
    "--no-download", "--pretty",
})

# ---- 模式解析（行业标准的多源配置优先级） ----

def parse_mode_arg(argv: Sequence[str]) -> Mode | None:
    """从命令行参数中提取 --mode / -m / --mode=xxx。"""
    mode_value: str | None = None
    for i, arg in enumerate(argv):
        if arg in ("--mode", "-m") and i + 1 < len(argv):
            mode_value = argv[i + 1]
            break
        if arg.startswith("--mode="):
            mode_value = arg.split("=", 1)[1]
            break
    if mode_value is None:
        return None
    try:
        return Mode(mode_value.lower())
    except ValueError:
        sys.stderr.write(
            f"⚠️  未知模式: {mode_value!r}，支持: {', '.join(m.value for m in Mode)}\n"
        )
        return None

def parse_env_mode() -> Mode | None:
    """从环境变量 UCRAWL_MODE 中提取模式。"""
    env = os.environ.get("UCRAWL_MODE", "").strip().lower()
    if not env:
        return None
    try:
        return Mode(env)
    except ValueError:
        return None

def is_gui_available() -> bool:
    """检测 GUI 所需依赖是否齐全。"""
    try:
        import PyQt6.QtWidgets  # noqa: F401
    except Exception:
        return False
    if os.name == "nt":
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

def is_tty() -> bool:
    """判断当前 stdio 是否可交互（用于决定能否弹 TUI 菜单）。

    设计原则：**宽松但准确**。行业最佳实践是尽量把用户当"可交互"对待，
    而不是粗暴拒绝；但不能把"EOF"误判为"有键盘输入"。

    判定顺序（满足任一即可返回 True）：

    1. ``stdin.isatty()`` —— 标准 TTY（如 Windows Terminal / cmd）
    2. ``stdout.isatty()`` —— 某些终端 stdout 仍是 TTY 而 stdin 被接管
    3. **UCRAWL_FORCE_MENU=1 环境变量** —— 强制弹菜单（绕过检测）
    4. **Windows 平台 msvcrt.kbhit() 探测** —— 某些 IDE 把 stdio 都接管
       了但仍能接收键盘输入（如 PyCharm Run 窗口）—— 用 msvcrt 探测
       键盘缓冲区。

    这能区分：
    - 真 TTY 终端 / cmd / PowerShell → True
    - IDE (PyCharm/VSCode) Run 窗口（能输入） → 部分支持
    - 完全 subprocess 接管（stdin closed / EOF pipe） → False
    """
    # 0: 强制覆盖（环境变量最高优先级）
    force = os.environ.get("UCRAWL_FORCE_MENU", "").strip().lower()
    if force in ("1", "true", "yes", "on"):
        return True

    # 1+2: 标准 TTY 检测
    try:
        if sys.stdin.isatty() or sys.stdout.isatty():
            return True
    except Exception:
        pass

    # 3: Windows 平台 msvcrt.kbhit() 探测
    if os.name == "nt":
        try:
            import msvcrt  # type: ignore[import-not-found]
            # msvcrt.kbhit() 不消耗输入，是安全的探测
            # 但如果 stdin 已经被消费过/EOF，它会返回 0
            if msvcrt.kbhit():
                return True
        except Exception:
            pass

    return False

def _arg_starts_with(token: str, argv: Sequence[str]) -> bool:
    """判断 argv 元素是否以 token 开头（处理 --port=8000 这种情况）。"""
    return any(t == token or t.startswith(token + "=") for t in argv)

def detect_mode_intent(argv: Sequence[str]) -> Mode:
    """按参数特征智能识别模式（用于**有参数**场景）。

    行业做法：检查参数签名匹配。
    """
    if not argv:
        # 无参数应该走 TUI 菜单路径，不应调用本函数
        return Mode.CLI

    tokens = set(argv)

    # 1. Web 专属参数命中 → web
    if (tokens & _WEB_FLAGS) or _arg_starts_with("--port", argv) \
            or _arg_starts_with("--host", argv) or _arg_starts_with("--script", argv) \
            or _arg_starts_with("--script-arg", argv):
        return Mode.WEB

    # 2. Interactive 专属参数命中 → interactive
    if (tokens & _INTERACTIVE_FLAGS) or _arg_starts_with("--save-dir", argv) \
            or _arg_starts_with("--no-download", argv):
        return Mode.INTERACTIVE

    # 3. 第一个非 --xxx 参数是 CLI 子命令 → cli
    for arg in argv:
        if arg.startswith("-"):
            continue
        if arg in _CLI_SUBCOMMANDS:
            return Mode.CLI
        break  # 第一个非选项 token 不是子命令 → 视为 CLI 自由参数

    # 4. 启发式：有 TTY + 有 GUI 依赖 → gui（裸 GUI 不接参数，但用户可能误传 --version 等）
    if is_tty() and is_gui_available():
        return Mode.GUI

    return Mode.CLI

def detect_mode(argv: Sequence[str] | None = None) -> Mode:
    """自适应检测运行模式。

    优先级（行业通用做法）：
    1. 命令行参数 --mode / -m
    2. 环境变量 UCRAWL_MODE
    3. 有参数 → 按特征识别
    4. 无参数 + TTY + 有 GUI 依赖 → gui
    5. 无参数 + 非 TTY → cli
    6. 无 GUI 依赖 → web
    """
    if argv is None:
        argv = sys.argv[1:]

    # 1. 命令行 --mode
    mode_from_arg = parse_mode_arg(argv)
    if mode_from_arg is not None:
        return mode_from_arg

    # 2. 环境变量
    mode_from_env = parse_env_mode()
    if mode_from_env is not None:
        return mode_from_env

    # 3. 有参数 → 按特征智能识别
    if argv:
        return detect_mode_intent(argv)

    # 4-6. 无参数 → 启发式（兜底，理论上应该先走 TUI 菜单）
    if not is_tty():
        return Mode.CLI
    if not is_gui_available():
        return Mode.WEB
    return Mode.GUI

# ---- 启动横幅 ----

_BANNER = r"""
+================================================+
|                                                |
|     UCrawl  通用爬虫 - 多模式自适应入口             |
|     桌面 GUI / Web UI / CLI / 交互式引导          |
|                                                |
+================================================+
"""

def print_banner(mode: Mode) -> None:
    """打印启动横幅。"""
    if not is_tty():
        return
    sys.stderr.write(_BANNER)
    sys.stderr.write(f"  🎯 模式: {mode.value}\n\n")
    sys.stderr.flush()

# ---- TUI 模式菜单（无参数时弹出） ----

# 菜单项定义: (显示标签, 描述, 模式)
_MENU_ITEMS = [
    ("1", "桌面 GUI    (PyQt6 图形界面)",            Mode.GUI),
    ("2", "Web UI     (浏览器访问，跨设备)",         Mode.WEB),
    ("3", "交互式引导  (逐步选择平台和参数)",         Mode.INTERACTIVE),
    ("4", "CLI 命令行  (单次执行后退出)",            Mode.CLI),
    ("5", "测试套件    (全量/单元/UI/浏览器 等)",     Mode.TEST),
    ("q", "退出",                                    None),
]

def _display_width(text: str) -> int:
    """计算字符串在终端的显示宽度（汉字/East Asian Wide 字符按 2 计算）。"""
    import unicodedata
    width = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width

def _pad_to_width(text: str, target: int) -> str:
    """用空格把字符串填充到目标显示宽度。"""
    cur = _display_width(text)
    if cur >= target:
        return text
    return text + " " * (target - cur)

def _has_pyqt6() -> bool:
    """检测 PyQt6 是否可用（用于 Qt 弹窗后备）。"""
    try:
        import PyQt6.QtWidgets  # noqa: F401
        return True
    except Exception:
        return False

def _load_app_icon() -> "QIcon | None":
    """加载应用图标（favicon.ico），找不到就返回 None。

    关键陷阱：**QIcon 必须在 QApplication 创建之后**才能正常构造，
    否则 PyQt6 在 Windows 上会 STATUS_STACK_BUFFER_OVERRUN 崩溃
    （0xC0000409）。所以本函数不直接 import QIcon，而是在调用方
    已有 QApplication 时再加载。

    查找顺序：
    1. 打包后的 _MEIPASS/favicon.ico（PyInstaller onefile/onedir 都覆盖）
    2. 仓库根目录的 favicon.ico
    3. fallback：Web.ico（同目录）
    """
    from PyQt6.QtGui import QIcon

    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "favicon.ico")
        candidates.append(Path(meipass) / "Web.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "favicon.ico")
    candidates.append(Path(__file__).resolve().parent.parent / "Web.ico")

    for path in candidates:
        try:
            if path.is_file():
                icon = QIcon(str(path))
                if not icon.isNull():
                    return icon
        except Exception:
            continue
    return None

def _prompt_mode_with_qt() -> Mode | None:
    """Show the shared, theme-aware Qt mode selection dialog."""
    from entry.mode_selection_ui import _prompt_mode_with_qt as show_mode_selection

    return show_mode_selection()

def prompt_mode_menu() -> Mode | None:
    """弹出菜单让用户选模式。

    选择策略（按优先级）：
    1. **TUI 菜单**（最轻量）：stdin/stdout 是 TTY 时
    2. **Qt 弹窗**（兜底）：stdin/stdout 非 TTY 但 PyQt6 可用
       —— 解决 IDE (PyCharm/VSCode) Run 按钮 / Ctrl+Shift+F10 场景
    3. **直接报错退出**：以上都不满足（无桌面环境）

    Returns:
        选中的 Mode；用户选退出则返回 None。
        非交互环境（无 TTY 也无 Qt）时返回 None 并提示用户用 --mode 显式指定。
    """
    if not is_tty():
        # 非 TTY：先尝试 Qt 弹窗（IDE 场景下的最佳体验）
        if _has_pyqt6():
            return _prompt_mode_with_qt()
        # 完全非交互：无法读键盘输入，提示用户显式指定
        sys.stderr.write(
            "❌ 无法弹出菜单：当前环境 stdin/stdout 都不是 TTY（非交互式），\n"
            "   且 PyQt6 不可用（无法弹窗）。\n"
            "\n"
            "   💡 如果你在 IDE (PyCharm/VSCode) 中点 Run 按钮跑：\n"
            "      - IDE 把 stdio 接管了，TUI 菜单无法弹\n"
            "      - 改在 IDE 内置 Terminal 里跑 `python main.py`\n"
            "      - 或显式指定模式:\n"
            "          python main.py --mode gui      # 桌面 GUI\n"
            "          python main.py --mode web      # Web UI\n"
            "          python main.py --mode cli      # CLI（默认）\n"
            "          python main.py --mode interactive  # 交互式引导\n"
            "          python main.py --mode test     # 测试套件\n"
            "      - 或设置环境变量: set UCRAWL_MODE=cli\n"
        )
        return None

    # 选最长 label 宽度做对齐
    width = max(_display_width(f"[{k}] {label}") for k, label, _ in _MENU_ITEMS) + 2

    sys.stderr.write(_BANNER)
    sys.stderr.write("  🎯 请选择启动模式 (输入数字或字母):\n\n")
    for key, label, mode in _MENU_ITEMS:
        marker = "" if mode is None else "  → "
        if mode is None:
            # 退出项用虚线分隔
            line = f"  [{key}] {label}"
            sys.stderr.write("  " + "-" * (width + 4) + "\n")
            sys.stderr.write("  " + _pad_to_width(line, width + 2) + "\n")
        else:
            line = f"[{key}] {label}"
            sys.stderr.write("  " + _pad_to_width(line, width) + marker + "\n")
    sys.stderr.write("\n")
    sys.stderr.flush()

    try:
        raw = input("请输入 [1/2/3/4/5/q]: ").strip().lower()
    except EOFError:
        sys.stderr.write("\n")
        return None
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return None

    if raw in ("q", "quit", "exit", "0"):
        return None

    # 接受数字 1-5
    if raw in ("1", "2", "3", "4", "5"):
        idx = int(raw) - 1
        if 0 <= idx < len(_MENU_ITEMS) - 1:  # 排除退出项
            return _MENU_ITEMS[idx][2]

    # 接受完整关键字
    for _key, label, mode in _MENU_ITEMS:
        if mode is not None and (raw == mode.value or raw in label.lower()):
            return mode

    sys.stderr.write(f"❌ 无效输入: {raw!r}\n")
    return None

# ---- 模式分发 ----

def run_gui(argv: Sequence[str] | None = None) -> int:
    """启动桌面 GUI。"""
    from entry.gui_entry import main as _main
    return _main(list(argv) if argv is not None else None)

def run_web(argv: Sequence[str] | None = None) -> int:
    """启动 Web UI。"""
    from entry.web_entry import main as _main
    return _main(list(argv) if argv is not None else None)

def run_cli(argv: Sequence[str] | None = None) -> int:
    """启动 CLI 单次执行。"""
    from entry.cli_entry import main as _main
    return _main(list(argv) if argv is not None else None)

def run_interactive(argv: Sequence[str] | None = None) -> int:
    """启动交互式引导。"""
    from entry.interactive_entry import main as _main
    return _main(list(argv) if argv is not None else None)

def run_test(argv: Sequence[str] | None = None) -> int:
    """启动测试套件（GUI / TUI / CLI 自适应）。"""
    from entry.test_entry import main as _main
    return _main(list(argv) if argv is not None else None)

# ---- 模式 -> 处理器映射 ----

_HANDLERS = {
    Mode.GUI: run_gui,
    Mode.WEB: run_web,
    Mode.CLI: run_cli,
    Mode.INTERACTIVE: run_interactive,
    Mode.TEST: run_test,
}

def _strip_dispatcher_args(argv: Sequence[str]) -> list[str]:
    """从 argv 中剥离 dispatcher 自己的参数（--mode / -m / --mode=xxx），
    剩余的全部透传给目标 mode handler。

    这是行业标准做法：让 dispatcher 只消费自己的参数，不截留 mode 的参数。
    """
    result = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--mode", "-m"):
            # 消耗下一个 token
            skip_next = True
            continue
        if arg.startswith("--mode="):
            continue
        # `python main.py -- xxx` 中的 `--` 是用户可选的分隔符，剥离它
        if arg == "--":
            continue
        result.append(arg)
    return result

def run(argv: Sequence[str] | None = None) -> int:
    """自适应入口主函数。

    行为：
    - **无参数** `python main.py` → 终端内弹 TUI 菜单；非 TTY 场景走原有 Qt 弹窗后备
    - **有参数** `python main.py [...]` → 按参数特征自适应派发
    - **--mode / -m** → 强制指定（最高优先级）

    透传规则：
    - dispatcher 只消费 `--mode` / `-m` 自身参数
    - 其它所有参数**原样透传**给对应 mode 的 handler
    - 因此 `python main.py --mode web -- --port 8000` 等价于 web 的 `--port 8000`
    """
    if argv is None:
        argv = sys.argv[1:]

    # 1. 显式 --mode / -m 优先
    explicit_mode = parse_mode_arg(argv) or parse_env_mode()

    # 2. 剥离 dispatcher 自己的参数，剩余透传给目标 handler
    passthrough = _strip_dispatcher_args(argv)

    if explicit_mode is not None:
        mode = explicit_mode
        print_banner(mode)
        return _dispatch(mode, passthrough)

    # 3. 无参数 → 使用原有菜单/Qt 后备选择器
    if not passthrough:
        try:
            mode = prompt_mode_menu()
        except _MenuUnavailable:
            # 非 TTY 环境：prompt_mode_menu 已写出错误信息
            return 2  # 退出码 2 = 使用错误（区别于用户取消的 0）
        if mode is None:
            # 用户主动选 q 退出
            sys.stderr.write("👋 已退出\n")
            return 0
        print_banner(mode)
        return _dispatch(mode, passthrough)

    # 4. 有参数 → 自适应检测（用透传后的 argv 判断）
    mode = detect_mode_intent(passthrough)
    print_banner(mode)
    return _dispatch(mode, passthrough)

def _dispatch(mode: Mode, argv: Sequence[str]) -> int:
    """派发到具体 handler。"""
    handler = _HANDLERS.get(mode)
    if handler is None:
        sys.stderr.write(f"❌ 没有 {mode} 模式的处理器\n")
        return 2
    return handler(argv)

if __name__ == "__main__":
    sys.exit(run())
