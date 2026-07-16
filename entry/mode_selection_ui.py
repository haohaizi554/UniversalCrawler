"""终端与 Qt 模式选择 UI。

本模块提供独立的 TUI 选择器和共享 Qt 对话框；当前
``entry.dispatcher`` 仍保留自己的终端菜单兼容实现，并只委托这里的 Qt
对话框，因此两处实现的所有权尚未完全合并。
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from entry.dispatcher import Mode, _BANNER, _MenuUnavailable, is_tty
from entry.qt_entry_utils import MAIN_APP_USER_MODEL_ID, ensure_windows_app_user_model_id, load_qt_icon

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon

# 菜单项定义: (显示标签, 描述, 模式)
_MENU_ITEMS = [
    ("1", "桌面 GUI    (PyQt6 图形界面)", Mode.GUI),
    ("2", "Web UI     (浏览器访问，跨设备)", Mode.WEB),
    ("3", "交互式引导  (逐步选择平台和参数)", Mode.INTERACTIVE),
    ("4", "CLI 命令行  (单次执行后退出)", Mode.CLI),
    ("5", "测试套件    (全量/单元/UI/浏览器 等)", Mode.TEST),
    ("6", "代码量统计  (生成并打开 HTML 报告)", Mode.REPORT),
    ("q", "退出", None),
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
    cur = _display_width(text)
    if cur >= target:
        return text
    return text + " " * (target - cur)

def _write_menu_item(key: str, label: str, mode: "Mode | None", width: int) -> None:
    """输出单个模式菜单项，并统一普通项与退出项的终端排版。"""
    marker = "" if mode is None else "  → "
    if mode is None:
        line = f"  [{key}] {label}"
        sys.stderr.write("  " + "-" * (width + 4) + "\n")
        sys.stderr.write("  " + _pad_to_width(line, width + 2) + "\n")
        return
    line = f"[{key}] {label}"
    sys.stderr.write("  " + _pad_to_width(line, width) + marker + "\n")

def _has_pyqt6() -> bool:
    try:
        import PyQt6.QtWidgets  # noqa: F401

        return True
    except Exception:
        return False

def _load_app_icon() -> "QIcon | None":
    return load_qt_icon(["favicon.ico"], fallback_names=["Web.ico"])

def _prompt_mode_with_qt() -> Mode | None:
    """显示 Qt 模式对话框；取消、关闭或依赖导入失败时返回 None。"""
    try:
        from PyQt6.QtCore import QSize, Qt
        from PyQt6.QtGui import QKeySequence, QShortcut
        from PyQt6.QtWidgets import (
            QApplication,
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )
        from app.ui.dialogs.chromed_dialog import ChromedDialog
        from app.ui.styles import resolve_is_dark_theme, theme_colors
    except Exception:
        return None

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    if os.name == "nt" and icon is not None:
        ensure_windows_app_user_model_id(MAIN_APP_USER_MODEL_ID)

    is_dark = resolve_is_dark_theme()
    dialog = ChromedDialog(
        title="UCrawl · 选择启动模式",
        object_name="ModeSelectionDialog",
        body_margins=(0, 0, 0, 0),
        body_spacing=0,
    )
    dialog.apply_chrome_theme(is_dark)
    dialog.setMinimumSize(QSize(720, 720))
    dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    if icon is not None:
        dialog.setWindowIcon(icon)
        dialog.chrome_frame.set_icon(icon)

    accent_gui = "#3b82f6"
    accent_web = "#10b981"
    accent_int = "#f59e0b"
    accent_cli = "#8b5cf6"
    accent_test = "#ef4444"
    accent_report = "#06b6d4"
    colors = theme_colors(is_dark)
    accent_cancel = colors["muted"]
    text_primary = colors["text"]
    text_secondary = colors["muted"]
    bg_soft = colors["panel_soft"]
    panel = colors["panel"]
    border = colors["border"]
    border_strong = colors["border_strong"]

    qss = f"""
        QDialog#ModeSelectionDialog {{
            background: {colors["bg"]};
        }}
        QLabel#heroTitle {{
            color: {text_primary};
            font-size: 24px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }}
        QLabel#heroSubtitle {{
            color: {text_secondary};
            font-size: 13px;
            margin-top: 4px;
        }}
        QLabel#cardTitle {{
            color: {text_primary};
            font-size: 16px;
            font-weight: 600;
        }}
        QLabel#cardDesc {{
            color: {text_secondary};
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
        QLabel#cardTagGui {{ background: {accent_gui}; }}
        QLabel#cardTagWeb {{ background: {accent_web}; }}
        QLabel#cardTagInt {{ background: {accent_int}; }}
        QLabel#cardTagCli {{ background: {accent_cli}; }}
        QLabel#cardTagTest {{ background: {accent_test}; }}
        QLabel#cardTagReport {{ background: {accent_report}; }}
        QFrame#cardGui, QFrame#cardWeb, QFrame#cardInt, QFrame#cardCli, QFrame#cardTest, QFrame#cardReport {{
            background: {bg_soft};
            border: 1px solid {border};
            border-radius: 12px;
        }}
        QFrame#cardGui:hover {{ border: 1.5px solid {accent_gui}; background: {panel}; }}
        QFrame#cardWeb:hover {{ border: 1.5px solid {accent_web}; background: {panel}; }}
        QFrame#cardInt:hover {{ border: 1.5px solid {accent_int}; background: {panel}; }}
        QFrame#cardCli:hover {{ border: 1.5px solid {accent_cli}; background: {panel}; }}
        QFrame#cardTest:hover {{ border: 1.5px solid {accent_test}; background: {panel}; }}
        QFrame#cardReport:hover {{ border: 1.5px solid {accent_report}; background: {panel}; }}
        QFrame#cardGui QLabel#cardAccent {{ background: {accent_gui}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardWeb QLabel#cardAccent {{ background: {accent_web}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardInt QLabel#cardAccent {{ background: {accent_int}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardCli QLabel#cardAccent {{ background: {accent_cli}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardTest QLabel#cardAccent {{ background: {accent_test}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardReport QLabel#cardAccent {{ background: {accent_report}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardGui QLabel#cardIndex {{ color: {accent_gui}; }}
        QFrame#cardWeb QLabel#cardIndex {{ color: {accent_web}; }}
        QFrame#cardInt QLabel#cardIndex {{ color: {accent_int}; }}
        QFrame#cardCli QLabel#cardIndex {{ color: {accent_cli}; }}
        QFrame#cardTest QLabel#cardIndex {{ color: {accent_test}; }}
        QFrame#cardReport QLabel#cardIndex {{ color: {accent_report}; }}
        QPushButton#cancelBtn {{
            background: transparent;
            color: {accent_cancel};
            border: 1px solid {border_strong};
            border-radius: 10px;
            padding: 9px 24px;
            font-size: 13px;
            font-weight: 600;
            min-width: 120px;
            min-height: 36px;
        }}
        QPushButton#cancelBtn:hover {{
            background: {bg_soft};
            color: {text_primary};
            border: 1px solid {text_secondary};
        }}
    """
    dialog.setStyleSheet(f"{dialog.styleSheet()}\n{qss}")

    root = dialog.content_layout
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    top_stripe = QFrame()
    top_stripe.setFixedHeight(4)
    top_stripe.setStyleSheet(f"background: {colors['accent']}; border: none;")
    root.addWidget(top_stripe)

    body = QVBoxLayout()
    body.setContentsMargins(36, 30, 36, 24)
    body.setSpacing(0)
    root.addLayout(body)

    header = QHBoxLayout()
    header.setSpacing(16)

    icon_circle = QFrame()
    icon_circle.setFixedSize(QSize(64, 64))
    icon_circle.setStyleSheet(
        f"""
        QFrame {{
            background: {colors["accent_soft"]};
            border-radius: 32px;
            border: none;
        }}
        """
    )
    icon_circle_layout = QVBoxLayout(icon_circle)
    icon_circle_layout.setContentsMargins(0, 0, 0, 0)
    if icon is not None:
        pixmap = icon.pixmap(QSize(42, 42))
        if not pixmap.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(pixmap)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_circle_layout.addWidget(icon_label)
    header.addWidget(icon_circle, 0, Qt.AlignmentFlag.AlignVCenter)

    title_box = QVBoxLayout()
    title_box.setSpacing(2)
    title_label = QLabel("UCrawl  通用爬虫")
    title_label.setObjectName("heroTitle")
    title_box.addWidget(title_label)

    subtitle = QLabel("请选择启动模式  ·  支持数字键 1-6 快速选择")
    subtitle.setObjectName("heroSubtitle")
    title_box.addWidget(subtitle)
    header.addLayout(title_box)
    header.addStretch(1)
    body.addLayout(header)
    body.addSpacing(22)

    btn_specs = [
        ("cardGui", Mode.GUI, "1", "桌面 GUI", "PyQt6 图形界面，支持完整可视化操作", "推荐", "cardTagGui"),
        ("cardWeb", Mode.WEB, "2", "Web UI", "浏览器访问，跨设备，FastAPI 后端", "", "cardTagWeb"),
        ("cardInt", Mode.INTERACTIVE, "3", "交互式引导", "逐步选择平台和参数，适合新手", "", "cardTagInt"),
        ("cardCli", Mode.CLI, "4", "CLI 命令行", "单次执行后退出，适合脚本 / AI 工具", "", "cardTagCli"),
        ("cardTest", Mode.TEST, "5", "测试套件", "全量/单元/UI/浏览器，多类别可勾选", "工程", "cardTagTest"),
        ("cardReport", Mode.REPORT, "6", "代码量统计", "扫描项目代码，生成并直接打开 HTML 报告", "报告", "cardTagReport"),
    ]

    cards: list[tuple[Mode, QFrame]] = []

    def make_card(
        css_class: str,
        mode: Mode,
        idx: str,
        name: str,
        desc: str,
        tag: str = "",
        tag_obj: str = "",
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(css_class)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(70)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        accent = QLabel()
        accent.setObjectName("cardAccent")
        accent.setFixedSize(QSize(6, 70))
        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(20, 10, 20, 10)
        content_layout.setSpacing(18)

        num = QLabel(idx)
        num.setObjectName("cardIndex")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setFixedWidth(40)
        content_layout.addWidget(num, 0, Qt.AlignmentFlag.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(name)
        title.setObjectName("cardTitle")
        title_row.addWidget(title)
        if tag:
            tag_label = QLabel(tag)
            tag_label.setObjectName("cardTag")
            tag_bg = {
                "cardTagGui": accent_gui,
                "cardTagWeb": accent_web,
                "cardTagInt": accent_int,
                "cardTagCli": accent_cli,
                "cardTagTest": accent_test,
                "cardTagReport": accent_report,
            }.get(tag_obj, accent_gui)
            tag_label.setStyleSheet(
                f"""
                QLabel {{
                    background: {tag_bg};
                    color: white;
                    font-size: 10px;
                    font-weight: 700;
                    padding: 3px 9px;
                    border-radius: 8px;
                }}
                """
            )
            title_row.addWidget(tag_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        text_box.addLayout(title_row)

        desc_label = QLabel(desc)
        desc_label.setObjectName("cardDesc")
        text_box.addWidget(desc_label)
        text_box.addStretch(1)
        content_layout.addLayout(text_box, 1)

        arrow = QLabel("›")
        arrow.setStyleSheet(
            f"""
            QLabel {{
                color: {text_secondary};
                font-size: 28px;
                font-weight: 300;
            }}
            """
        )
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
        if spec is not btn_specs[-1]:
            body.addSpacing(8)

    body.addSpacing(16)
    body.addStretch(1)

    bottom = QHBoxLayout()
    bottom.addStretch(1)
    cancel_btn = QPushButton("取消 (Esc)")
    cancel_btn.setObjectName("cancelBtn")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    bottom.addWidget(cancel_btn)
    body.addLayout(bottom)

    screen = QApplication.primaryScreen()
    if screen is not None:
        screen_geo = screen.availableGeometry()
        dlg_geo = dialog.frameGeometry()
        x = (screen_geo.width() - dlg_geo.width()) // 2 + screen_geo.left()
        y = (screen_geo.height() - dlg_geo.height()) // 2 + screen_geo.top()
        dialog.move(max(0, x), max(0, y))

    result: dict[str, Mode | None] = {"mode": None}

    def choose(mode: Mode) -> None:
        result["mode"] = mode
        dialog.accept()

    def cancel() -> None:
        result["mode"] = None
        dialog.reject()

    def make_press_handler(selected_mode: Mode):
        def handler(_event):
            choose(selected_mode)

        return handler

    for mode, card in cards:
        handler = make_press_handler(mode)
        card.mousePressEvent = handler
        for child in card.findChildren(QLabel):
            child.mousePressEvent = handler
        for widget in card.findChildren(QWidget):
            widget.mousePressEvent = handler

    cancel_btn.clicked.connect(cancel)

    for i, (mode, _card) in enumerate(cards, start=1):
        QShortcut(QKeySequence(str(i)), dialog, activated=lambda m=mode: choose(m))
    QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, activated=cancel)
    QShortcut(QKeySequence("Q"), dialog, activated=cancel)

    dialog.exec()
    return result["mode"]

def prompt_mode_menu() -> Mode | None:
    """返回用户选择的模式，或报告当前没有可用的交互通道。

    ``None`` 表示选择流程没有产生模式，例如取消、关闭、EOF、无效终端输入，
    或 Qt 辅助函数未能创建对话框。仅当预检确认既无 TTY、也无 PyQt6 时才抛出
    ``_MenuUnavailable``，且会先向 stderr 写出显式 ``--mode`` 的使用提示。
    调用方应把该异常与普通的无选择结果分开处理。
    """
    if not is_tty():
        if _has_pyqt6():
            return _prompt_mode_with_qt()
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
            "          python main.py --mode report   # 代码量统计报告\n"
            "      - 或设置环境变量: set UCRAWL_MODE=cli\n"
        )
        raise _MenuUnavailable()

    width = max(_display_width(f"[{key}] {label}") for key, label, _ in _MENU_ITEMS) + 2

    sys.stderr.write(_BANNER)
    sys.stderr.write("  🎯 请选择启动模式 (输入数字或字母):\n\n")
    for key, label, mode in _MENU_ITEMS:
        _write_menu_item(key, label, mode, width)
    sys.stderr.write("\n")
    sys.stderr.flush()

    try:
        raw = input("请输入 [1/2/3/4/5/6/q]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n")
        return None

    if raw in ("q", "quit", "exit", "0"):
        return None

    if raw in ("1", "2", "3", "4", "5", "6"):
        idx = int(raw) - 1
        if 0 <= idx < len(_MENU_ITEMS) - 1:
            return _MENU_ITEMS[idx][2]

    for _key, label, mode in _MENU_ITEMS:
        if mode is not None and (raw == mode.value or raw in label.lower()):
            return mode

    sys.stderr.write(f"❌ 无效输入: {raw!r}\n")
    return None
