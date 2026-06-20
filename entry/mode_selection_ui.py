"""模式选择 UI 组件。

从 `entry.dispatcher` 中拆出 TUI / Qt 模式选择相关实现，
让 dispatcher 保持为纯调度入口，仅保留薄接缝。
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
    """用空格把字符串填充到目标显示宽度。"""
    cur = _display_width(text)
    if cur >= target:
        return text
    return text + " " * (target - cur)

def _write_menu_item(key: str, label: str, mode: "Mode | None", width: int) -> None:
    """输出单个模式菜单项，统一处理退出项与普通项的对齐逻辑。"""
    marker = "" if mode is None else "  → "
    if mode is None:
        line = f"  [{key}] {label}"
        sys.stderr.write("  " + "-" * (width + 4) + "\n")
        sys.stderr.write("  " + _pad_to_width(line, width + 2) + "\n")
        return
    line = f"[{key}] {label}"
    sys.stderr.write("  " + _pad_to_width(line, width) + marker + "\n")

def _has_pyqt6() -> bool:
    """检测 PyQt6 是否可用（用于 Qt 弹窗后备）。"""
    try:
        import PyQt6.QtWidgets  # noqa: F401

        return True
    except Exception:
        return False

def _load_app_icon() -> "QIcon | None":
    """加载应用图标（favicon.ico），找不到就返回 None。"""
    return load_qt_icon(["favicon.ico"], fallback_names=["Web.ico"])

def _prompt_mode_with_qt() -> Mode | None:
    """当 stdin/stdout 不是 TTY 时，用 Qt 弹窗让用户选 mode。"""
    try:
        from PyQt6.QtCore import QSize, Qt
        from PyQt6.QtGui import QKeySequence, QShortcut
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

    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    if os.name == "nt" and icon is not None:
        ensure_windows_app_user_model_id(MAIN_APP_USER_MODEL_ID)

    dialog = QDialog()
    dialog.setWindowTitle("UCrawl · 选择启动模式")
    dialog.setModal(True)
    dialog.setMinimumSize(QSize(720, 720))
    dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    if icon is not None:
        dialog.setWindowIcon(icon)

    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(28)
    shadow.setColor(Qt.GlobalColor.gray)
    shadow.setOffset(0, 6)
    dialog.setGraphicsEffect(shadow)

    accent_gui = "#3b82f6"
    accent_web = "#10b981"
    accent_int = "#f59e0b"
    accent_cli = "#8b5cf6"
    accent_test = "#ef4444"
    accent_cancel = "#6b7280"
    text_primary = "#111827"
    text_secondary = "#6b7280"
    bg_soft = "#fafbfc"

    qss = f"""
        QDialog {{
            background: #ffffff;
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
        QFrame#cardGui, QFrame#cardWeb, QFrame#cardInt, QFrame#cardCli, QFrame#cardTest {{
            background: {bg_soft};
            border: 1px solid #e5e7eb;
            border-radius: 12px;
        }}
        QFrame#cardGui:hover {{ border: 1.5px solid {accent_gui}; background: #ffffff; }}
        QFrame#cardWeb:hover {{ border: 1.5px solid {accent_web}; background: #ffffff; }}
        QFrame#cardInt:hover {{ border: 1.5px solid {accent_int}; background: #ffffff; }}
        QFrame#cardCli:hover {{ border: 1.5px solid {accent_cli}; background: #ffffff; }}
        QFrame#cardTest:hover {{ border: 1.5px solid {accent_test}; background: #ffffff; }}
        QFrame#cardGui QLabel#cardAccent {{ background: {accent_gui}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardWeb QLabel#cardAccent {{ background: {accent_web}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardInt QLabel#cardAccent {{ background: {accent_int}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardCli QLabel#cardAccent {{ background: {accent_cli}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardTest QLabel#cardAccent {{ background: {accent_test}; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
        QFrame#cardGui QLabel#cardIndex {{ color: {accent_gui}; }}
        QFrame#cardWeb QLabel#cardIndex {{ color: {accent_web}; }}
        QFrame#cardInt QLabel#cardIndex {{ color: {accent_int}; }}
        QFrame#cardCli QLabel#cardIndex {{ color: {accent_cli}; }}
        QFrame#cardTest QLabel#cardIndex {{ color: {accent_test}; }}
        QPushButton#cancelBtn {{
            background: transparent;
            color: {accent_cancel};
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

    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    top_stripe = QFrame()
    top_stripe.setFixedHeight(4)
    top_stripe.setStyleSheet("background: #3b82f6; border: none;")
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
        """
        QFrame {
            background: #dbeafe;
            border-radius: 32px;
            border: none;
        }
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

    subtitle = QLabel("请选择启动模式  ·  支持数字键 1-4 快速选择")
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
        card.setMinimumHeight(78)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        accent = QLabel()
        accent.setObjectName("cardAccent")
        accent.setFixedSize(QSize(6, 78))
        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(20, 14, 20, 14)
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
            body.addSpacing(10)

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
    """弹出菜单让用户选模式。"""
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
        raw = input("请输入 [1/2/3/4/5/q]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n")
        return None

    if raw in ("q", "quit", "exit", "0"):
        return None

    if raw in ("1", "2", "3", "4", "5"):
        idx = int(raw) - 1
        if 0 <= idx < len(_MENU_ITEMS) - 1:
            return _MENU_ITEMS[idx][2]

    for _key, label, mode in _MENU_ITEMS:
        if mode is not None and (raw == mode.value or raw in label.lower()):
            return mode

    sys.stderr.write(f"❌ 无效输入: {raw!r}\n")
    return None
