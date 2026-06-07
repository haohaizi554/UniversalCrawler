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
from typing import Sequence


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
    """当 stdin/stdout 不是 TTY 时，用 Qt 弹窗让用户选 mode。

    场景：用户用 IDE (PyCharm/VSCode) Run 按钮 / Ctrl+Shift+F10 跑
    `python main.py`，IDE 把 stdio 接管了，TUI 菜单无法弹。
    但 PyQt6 能正常显示窗口（与 stdio 无关），所以用弹窗兜底。

    Returns:
        选中的 Mode；用户关掉弹窗则返回 None。

    设计要点：
    - 居中显示在主屏中央，宽度 720px（更宽不挤）
    - 顶部 64x64 图标 + 大标题
    - 4 个**彩色边条卡片**（每个 mode 一种颜色：蓝/绿/橙/紫）
    - 卡片更大、字体更大、悬停高亮带阴影
    - 取消按钮放右下角（不被遮）
    - 任务栏图标：app.setWindowIcon(icon) + dialog.setWindowIcon(icon)
    """
    try:
        from PyQt6.QtCore import QSize, Qt
        from PyQt6.QtGui import QFont, QIcon, QKeySequence, QShortcut
        from PyQt6.QtWidgets import (
            QApplication,
            QDialog,
            QFrame,
            QGraphicsDropShadowEffect,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )
    except Exception:
        return None

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # ---- 加载应用图标 + 设置到 QApplication（任务栏图标）----
    icon = _load_app_icon()
    if icon is not None:
        # 只设置 windowIcon，不设置 setApplicationDisplayName
        # 避免 Windows 标题栏变成 "Title - DisplayName" 重复
        app.setWindowIcon(icon)

    # ---- Windows 任务栏图标关键修复 ----
    # Windows 任务栏图标 = EXE 资源图标。开发模式下 `python.exe` 自带图标，
    # 即便 setWindowIcon 设置了 favicon，任务栏仍会显示 python.exe 的图标。
    # 解法：调用 Win32 API `SetCurrentProcessExplicitAppUserModelID`，
    # 让 Windows 把当前进程当作独立应用，任务栏就会用 setWindowIcon 的图标。
    # 参考：https://learn.microsoft.com/windows/win32/api/shobjidl_core/nf-shobjidl_core-setcurrentprocessexplicitappusermodelid
    if os.name == "nt" and icon is not None:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ucrawl.universalcrawlerpro.main"
            )
        except Exception:
            pass  # API 在旧版 Windows 上不可用，忽略

    # ---- 自定义 QDialog ----
    dialog = QDialog()
    dialog.setWindowTitle("UCrawl · 选择启动模式")
    dialog.setModal(True)
    dialog.setMinimumSize(QSize(720, 720))
    dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    if icon is not None:
        dialog.setWindowIcon(icon)
    # 阴影效果
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(28)
    shadow.setColor(Qt.GlobalColor.gray)
    shadow.setOffset(0, 6)
    dialog.setGraphicsEffect(shadow)

    # ---- 全局 QSS（圆角、配色、按钮、标签样式）----
    # ---- 5 个 mode 各自的强调色 ----
    ACCENT_GUI = "#3b82f6"  # 蓝
    ACCENT_WEB = "#10b981"  # 绿
    ACCENT_INT = "#f59e0b"  # 橙
    ACCENT_CLI = "#8b5cf6"  # 紫
    ACCENT_TEST = "#ef4444"  # 红（测试套件，醒目）
    ACCENT_CANCEL = "#6b7280"  # 灰
    TEXT_PRIMARY = "#111827"
    TEXT_SECONDARY = "#6b7280"
    BG_SOFT = "#fafbfc"

    qss = f"""
        QDialog {{
            background: #ffffff;
        }}
        QLabel#heroTitle {{
            color: {TEXT_PRIMARY};
            font-size: 24px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }}
        QLabel#heroSubtitle {{
            color: {TEXT_SECONDARY};
            font-size: 13px;
            margin-top: 4px;
        }}
        QLabel#cardTitle {{
            color: {TEXT_PRIMARY};
            font-size: 16px;
            font-weight: 600;
        }}
        QLabel#cardDesc {{
            color: {TEXT_SECONDARY};
            font-size: 12px;
        }}
        QLabel#cardIndex {{
            font-size: 28px;
            font-weight: 700;
            min-width: 36px;
        }}
        QLabel#cardTag {{
            color: white;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 8px;
        }}
        QLabel#cardTagGui {{ background: {ACCENT_GUI}; }}
        QLabel#cardTagWeb {{ background: {ACCENT_WEB}; }}
        QLabel#cardTagInt {{ background: {ACCENT_INT}; }}
        QLabel#cardTagCli {{ background: {ACCENT_CLI}; }}
        QLabel#cardTagTest {{ background: {ACCENT_TEST}; }}
        /* 5 张卡片共享基样式：背景、圆角、内边距 */
        QFrame#cardGui, QFrame#cardWeb, QFrame#cardInt, QFrame#cardCli, QFrame#cardTest {{
            background: {BG_SOFT};
            border: 1px solid #e5e7eb;
            border-radius: 12px;
        }}
        /* 悬停时换边框色 + 背景变白 */
        QFrame#cardGui:hover {{ border: 1.5px solid {ACCENT_GUI}; background: #ffffff; }}
        QFrame#cardWeb:hover {{ border: 1.5px solid {ACCENT_WEB}; background: #ffffff; }}
        QFrame#cardInt:hover {{ border: 1.5px solid {ACCENT_INT}; background: #ffffff; }}
        QFrame#cardCli:hover {{ border: 1.5px solid {ACCENT_CLI}; background: #ffffff; }}
        QFrame#cardTest:hover {{ border: 1.5px solid {ACCENT_TEST}; background: #ffffff; }}
        /* 边条 */
        QFrame#cardGui QLabel#cardAccent {{ background: {ACCENT_GUI}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardWeb QLabel#cardAccent {{ background: {ACCENT_WEB}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardInt QLabel#cardAccent {{ background: {ACCENT_INT}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardCli QLabel#cardAccent {{ background: {ACCENT_CLI}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardTest QLabel#cardAccent {{ background: {ACCENT_TEST}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        /* 数字颜色 */
        QFrame#cardGui QLabel#cardIndex {{ color: {ACCENT_GUI}; }}
        QFrame#cardWeb QLabel#cardIndex {{ color: {ACCENT_WEB}; }}
        QFrame#cardInt QLabel#cardIndex {{ color: {ACCENT_INT}; }}
        QFrame#cardCli QLabel#cardIndex {{ color: {ACCENT_CLI}; }}
        QFrame#cardTest QLabel#cardIndex {{ color: {ACCENT_TEST}; }}
        QPushButton#cancelBtn {{
            background: transparent;
            color: {ACCENT_CANCEL};
            border: 1px solid #d1d5db;
            border-radius: 10px;
            padding: 9px 24px;
            font-size: 13px;
            font-weight: 600;
            min-width: 120px;
            min-height: 36px;
        }}
        QPushButton#cancelBtn:hover {{
            background: #f3f4f6;
            color: #374151;
            border: 1px solid #9ca3af;
        }}
    """
    dialog.setStyleSheet(qss)

    # ---- 根布局 ----
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # 顶部 4px 装饰条（蓝色主品牌色）
    top_stripe = QFrame()
    top_stripe.setFixedHeight(4)
    top_stripe.setStyleSheet("background: #3b82f6; border: none;")
    root.addWidget(top_stripe)

    # 主内容容器
    body = QVBoxLayout()
    body.setContentsMargins(36, 30, 36, 24)
    body.setSpacing(0)
    root.addLayout(body)

    # ---- 顶部 Header：圆形图标 + 标题 ----
    header = QHBoxLayout()
    header.setSpacing(16)

    # 64x64 圆形图标背景（淡蓝渐变感用单色 + 圆角）
    icon_circle = QFrame()
    icon_circle.setFixedSize(QSize(64, 64))
    icon_circle.setStyleSheet("""
        QFrame {
            background: #dbeafe;
            border-radius: 32px;
            border: none;
        }
    """)
    icon_circle_layout = QVBoxLayout(icon_circle)
    icon_circle_layout.setContentsMargins(0, 0, 0, 0)
    if icon is not None:
        pixmap = icon.pixmap(QSize(42, 42))
        if not pixmap.isNull():
            il = QLabel()
            il.setPixmap(pixmap)
            il.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_circle_layout.addWidget(il)
    header.addWidget(icon_circle, 0, Qt.AlignmentFlag.AlignVCenter)

    title_box = QVBoxLayout()
    title_box.setSpacing(2)
    title_label = QLabel("UCrawl  通用爬虫")
    title_label.setObjectName("heroTitle")
    title_box.addWidget(title_label)

    subtitle = QLabel("请选择启动模式  ·  支持数字键 1-4 快速选择")
    subtitle.setObjectName("heroSubtitle")
    title_box.addWidget(subtitle)
    header.addLayout(title_box)
    header.addStretch(1)
    body.addLayout(header)

    # 间距
    body.addSpacing(22)

    # ---- 5 个模式卡片 ----
    btn_specs = [
        ("cardGui", Mode.GUI, "1", "桌面 GUI", "PyQt6 图形界面，支持完整可视化操作", "推荐", "cardTagGui"),
        ("cardWeb", Mode.WEB, "2", "Web UI", "浏览器访问，跨设备，FastAPI 后端", "", "cardTagWeb"),
        ("cardInt", Mode.INTERACTIVE, "3", "交互式引导", "逐步选择平台和参数，适合新手", "", "cardTagInt"),
        ("cardCli", Mode.CLI, "4", "CLI 命令行", "单次执行后退出，适合脚本 / AI 工具", "", "cardTagCli"),
        ("cardTest", Mode.TEST, "5", "测试套件", "全量/单元/UI/浏览器，多类别可勾选", "工程", "cardTagTest"),
    ]

    cards: list[tuple[Mode, QFrame]] = []

    def make_card(css_class: str, mode: Mode, idx: str, name: str, desc: str,
                  tag: str = "", tag_obj: str = "") -> QFrame:
        card = QFrame()
        # objectName 用具体类名（cardGui / cardWeb / cardInt / cardCli）
        # QSS 选择器 #cardGui 等能直接命中
        card.setObjectName(css_class)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(78)

        # 卡片内布局：左侧 6px 彩色边条 + 内容
        layout = QHBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 彩色边条
        accent = QLabel()
        accent.setObjectName("cardAccent")
        accent.setFixedSize(QSize(6, 78))
        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

        # 右侧内容（数字 + 标题/描述 + 标签）
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(20, 14, 20, 14)
        content_layout.setSpacing(18)

        # 数字
        num = QLabel(idx)
        num.setObjectName("cardIndex")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setFixedWidth(40)
        content_layout.addWidget(num, 0, Qt.AlignmentFlag.AlignVCenter)

        # 标题 + 描述
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        # 标题行（标题 + 标签）
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(name)
        title.setObjectName("cardTitle")
        title_row.addWidget(title)
        if tag:
            tag_label = QLabel(tag)
            tag_label.setObjectName("cardTag")
            # 用 inline style 强制设置背景色（PyQt6 的 [class=...] 动态属性选择器不可靠）
            tag_bg = {
                "cardTagGui": ACCENT_GUI,
                "cardTagWeb": ACCENT_WEB,
                "cardTagInt": ACCENT_INT,
                "cardTagCli": ACCENT_CLI,
                "cardTagTest": ACCENT_TEST,
            }.get(tag_obj, ACCENT_GUI)
            tag_label.setStyleSheet(f"""
                QLabel {{
                    background: {tag_bg};
                    color: white;
                    font-size: 10px;
                    font-weight: 700;
                    padding: 3px 9px;
                    border-radius: 8px;
                }}
            """)
            title_row.addWidget(tag_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        text_box.addLayout(title_row)
        desc_label = QLabel(desc)
        desc_label.setObjectName("cardDesc")
        text_box.addWidget(desc_label)
        text_box.addStretch(1)
        content_layout.addLayout(text_box, 1)

        # 右侧箭头
        arrow = QLabel("›")
        arrow.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_SECONDARY};
                font-size: 28px;
                font-weight: 300;
            }}
        """)
        arrow.setFixedWidth(24)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)

        content_wrapper = QWidget()
        content_wrapper.setLayout(content_layout)
        content_wrapper.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(content_wrapper, 1)

        return card

    for spec in btn_specs:
        card = make_card(*spec)
        cards.append((spec[1], card))
        body.addWidget(card)
        # 卡片之间留 10px 间距
        if spec is not btn_specs[-1]:
            body.addSpacing(10)

    # ---- 弹性间距（撑开底部空间）----
    body.addSpacing(16)
    body.addStretch(1)

    # ---- 底部取消按钮：放右下角 ----
    bottom = QHBoxLayout()
    bottom.addStretch(1)
    cancel_btn = QPushButton("取消 (Esc)")
    cancel_btn.setObjectName("cancelBtn")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    bottom.addWidget(cancel_btn)
    body.addLayout(bottom)

    # ---- 居中显示 ----
    from PyQt6.QtWidgets import QApplication as _QA
    screen = _QA.primaryScreen()
    if screen is not None:
        screen_geo = screen.availableGeometry()
        dlg_geo = dialog.frameGeometry()
        x = (screen_geo.width() - dlg_geo.width()) // 2 + screen_geo.left()
        y = (screen_geo.height() - dlg_geo.height()) // 2 + screen_geo.top()
        dialog.move(max(0, x), max(0, y))

    # ---- 事件绑定 ----
    result: dict[str, Mode | None] = {"mode": None}

    def choose(mode: Mode):
        result["mode"] = mode
        dialog.accept()

    def cancel():
        result["mode"] = None
        dialog.reject()

    for mode, card in cards:
        # 整个卡片可点击
        def make_press_handler(m: Mode):
            def handler(_e):
                choose(m)
            return handler
        card.mousePressEvent = make_press_handler(mode)
        # 卡片内部所有子控件点击也触发
        for child in card.findChildren(QLabel):
            child.mousePressEvent = make_press_handler(mode)
        # 内部 wrapper widget 也需要
        from PyQt6.QtWidgets import QWidget as _QW
        for w in card.findChildren(_QW):
            w.mousePressEvent = make_press_handler(mode)

    cancel_btn.clicked.connect(cancel)

    # 快捷键：数字 1-4 + Esc + Q
    for i, (mode, _card) in enumerate(cards, start=1):
        QShortcut(QKeySequence(str(i)), dialog, activated=lambda m=mode: choose(m))
    QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, activated=cancel)
    QShortcut(QKeySequence("Q"), dialog, activated=cancel)

    dialog.exec()
    return result["mode"]


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
    except (EOFError, KeyboardInterrupt):
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
    for key, label, mode in _MENU_ITEMS:
        if mode is not None and (raw == mode.value or raw in label.lower()):
            return mode

    sys.stderr.write(f"❌ 无效输入: {raw!r}\n")
    return None


# ---- 模式分发 ----

def run_gui(argv: Sequence[str] | None = None) -> int:
    """启动桌面 GUI。"""
    from entry.gui_entry import main as _main
    return _main(list(argv) if argv else None)


def run_web(argv: Sequence[str] | None = None) -> int:
    """启动 Web UI。"""
    from entry.web_entry import main as _main
    return _main(list(argv) if argv else None)


def run_cli(argv: Sequence[str] | None = None) -> int:
    """启动 CLI 单次执行。"""
    from entry.cli_entry import main as _main
    return _main(list(argv) if argv else None)


def run_interactive(argv: Sequence[str] | None = None) -> int:
    """启动交互式引导。"""
    from entry.interactive_entry import main as _main
    return _main(list(argv) if argv else None)


def run_test(argv: Sequence[str] | None = None) -> int:
    """启动测试套件（GUI / TUI / CLI 自适应）。"""
    from entry.test_entry import main as _main
    return _main(list(argv) if argv else None)


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
    for i, arg in enumerate(argv):
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
    - **无参数** `python main.py` → 弹 TUI 菜单让用户选
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

    # 3. 无参数 → TUI 菜单
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
