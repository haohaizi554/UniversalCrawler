"""Web 入口端口冲突对话框。"""

from __future__ import annotations

import sys
from typing import Callable

from entry.qt_entry_utils import ensure_windows_app_user_model_id, load_qt_icon

def resolve_port_with_dialog(
    default_port: int,
    *,
    is_port_in_use: Callable[[str, int], bool],
    port_probe_range: int,
) -> int:
    """端口被占用时，弹 Qt 对话框让用户选择新的端口。"""
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
        QSpinBox,
        QVBoxLayout,
    )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    icon = load_qt_icon(["Web.ico"], fallback_names=["favicon.ico"])
    if icon is not None:
        app.setWindowIcon(icon)
    ensure_windows_app_user_model_id("ucrawl.universalcrawlerpro.web")

    accent = "#3b82f6"
    accent_hover = "#2563eb"
    accent_light = "#dbeafe"
    danger = "#ef4444"
    success = "#10b981"
    text_primary = "#111827"
    text_secondary = "#6b7280"
    bg_soft = "#f9fafb"

    port = default_port
    while True:
        if not is_port_in_use("0.0.0.0", port):
            return port

        dialog = QDialog()
        dialog.setWindowTitle("端口已被占用 · UCrawl")
        dialog.setModal(True)
        dialog.setMinimumSize(QSize(600, 340))
        dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if icon is not None:
            dialog.setWindowIcon(icon)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setColor(Qt.GlobalColor.gray)
        shadow.setOffset(0, 4)
        dialog.setGraphicsEffect(shadow)

        dialog.setStyleSheet(
            f"""
            QDialog {{ background: #ffffff; }}
            QLabel#title {{
                color: {text_primary};
                font-size: 20px;
                font-weight: 700;
                letter-spacing: 0.2px;
            }}
            QLabel#subtitle {{
                color: {text_secondary};
                font-size: 12px;
                margin-top: 2px;
            }}
            QLabel#labelText {{
                color: {text_primary};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#labelValue {{
                color: {text_primary};
                font-size: 15px;
                font-weight: 700;
                font-family: 'Cascadia Code', 'Consolas', monospace;
            }}
            QLabel#badge {{
                color: white;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 10px;
                border-radius: 10px;
            }}
            QFrame#statusCard {{
                background: {bg_soft};
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }}
            QLabel#statusStripeDanger {{
                background: {danger};
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#statusStripeSuccess {{
                background: {success};
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#statusStripeWarn {{
                background: #f59e0b;
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
            }}
            QLabel#inputLabel {{
                color: {text_primary};
                font-size: 13px;
                font-weight: 600;
                margin-bottom: 6px;
            }}
            QLabel#hint {{
                color: {text_secondary};
                font-size: 11px;
                margin-top: 6px;
            }}
            QSpinBox {{
                padding: 10px 14px;
                border: 1.5px solid #d1d5db;
                border-radius: 10px;
                font-size: 15px;
                font-weight: 600;
                min-height: 28px;
                background: #ffffff;
                selection-background-color: {accent_light};
            }}
            QSpinBox:hover {{
                border: 1.5px solid #9ca3af;
            }}
            QSpinBox:focus {{
                border: 2px solid {accent};
                background: #f0f7ff;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 24px;
                border: none;
                background: transparent;
            }}
            QPushButton {{
                border-radius: 10px;
                padding: 9px 24px;
                font-size: 13px;
                font-weight: 600;
                min-width: 96px;
                min-height: 36px;
            }}
            QPushButton#okBtn {{
                background: {accent};
                color: white;
                border: none;
            }}
            QPushButton#okBtn:hover {{
                background: {accent_hover};
            }}
            QPushButton#okBtn:pressed {{
                background: #1d4ed8;
            }}
            QPushButton#cancelBtn {{
                background: transparent;
                color: {text_secondary};
                border: 1px solid #d1d5db;
            }}
            QPushButton#cancelBtn:hover {{
                background: #f3f4f6;
                color: #374151;
                border: 1px solid #9ca3af;
            }}
            """
        )

        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_stripe = QFrame()
        top_stripe.setFixedHeight(4)
        top_stripe.setStyleSheet(f"background: {accent}; border: none;")
        root.addWidget(top_stripe)

        body = QVBoxLayout()
        body.setContentsMargins(32, 24, 32, 22)
        body.setSpacing(0)
        root.addLayout(body)

        header = QHBoxLayout()
        header.setSpacing(14)

        icon_circle = QFrame()
        icon_circle.setFixedSize(QSize(56, 56))
        icon_circle.setStyleSheet(
            f"""
            QFrame {{
                background: {accent_light};
                border-radius: 28px;
                border: none;
            }}
            """
        )
        icon_layout = QVBoxLayout(icon_circle)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        if icon is not None:
            pixmap = icon.pixmap(QSize(36, 36))
            if not pixmap.isNull():
                icon_label = QLabel()
                icon_label.setPixmap(pixmap)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_layout.addWidget(icon_label)
        header.addWidget(icon_circle, 0, Qt.AlignmentFlag.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("端口已被占用")
        title_label.setObjectName("title")
        title_box.addWidget(title_label)
        subtitle = QLabel("Web 服务需要切换到其他端口才能启动")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        body.addLayout(header)

        body.addSpacing(18)

        def make_status_card(stripe_obj: str, value: str, badge_text: str, badge_color: str, label_text: str) -> QFrame:
            card = QFrame()
            card.setObjectName("statusCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)

            stripe = QLabel()
            stripe.setObjectName(stripe_obj)
            stripe.setFixedSize(QSize(4, 48))
            card_layout.addWidget(stripe, 0, Qt.AlignmentFlag.AlignVCenter)

            text_box = QHBoxLayout()
            text_box.setContentsMargins(14, 10, 14, 10)
            text_box.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("labelText")
            text_box.addWidget(label)
            value_label = QLabel(value)
            value_label.setObjectName("labelValue")
            text_box.addWidget(value_label)
            text_box.addStretch(1)

            badge = QLabel(badge_text)
            badge.setObjectName("badge")
            badge.setStyleSheet(
                f"""
                QLabel {{
                    background: {badge_color};
                    color: white;
                    font-size: 11px;
                    font-weight: 700;
                    padding: 3px 10px;
                    border-radius: 10px;
                }}
                """
            )
            text_box.addWidget(badge)
            text_wrap = QFrame()
            text_wrap.setLayout(text_box)
            text_wrap.setStyleSheet("background: transparent; border: none;")
            card_layout.addWidget(text_wrap, 1)
            return card

        body.addWidget(
            make_status_card(
                stripe_obj="statusStripeDanger",
                value=str(port),
                badge_text="✗  被占用",
                badge_color=danger,
                label_text="请求端口：",
            )
        )
        body.addSpacing(8)

        suggested: int | None = None
        attempted = 0
        for offset in range(1, port_probe_range + 1):
            candidate = port + offset
            if candidate > 65535:
                break
            attempted += 1
            if not is_port_in_use("0.0.0.0", candidate):
                suggested = candidate
                break

        if suggested is not None:
            suggest_value = str(suggested)
            suggest_badge = f"✓  已验证可用 (尝试 {attempted} 个)"
            suggest_badge_color = success
            suggest_stripe = "statusStripeSuccess"
        else:
            suggest_value = "—"
            suggest_badge = "⚠  需手动指定"
            suggest_badge_color = "#f59e0b"
            suggest_stripe = "statusStripeWarn"

        body.addWidget(
            make_status_card(
                stripe_obj=suggest_stripe,
                value=suggest_value,
                badge_text=suggest_badge,
                badge_color=suggest_badge_color,
                label_text="建议端口：",
            )
        )

        body.addSpacing(20)

        input_label = QLabel("新端口号")
        input_label.setObjectName("inputLabel")
        body.addWidget(input_label)

        spin = QSpinBox()
        spin.setRange(1, 65535)
        spin.setValue(suggested if suggested is not None else port + 1)
        spin.setSingleStep(1)
        spin.selectAll()
        body.addWidget(spin)

        if suggested is not None:
            hint_text = (
                f"提示：建议端口 {suggested} 已验证可用。"
                "如需更换，范围 1 - 65535，建议使用 1024 以上的端口"
            )
        else:
            hint_text = (
                f"提示：自动搜索 {port_probe_range} 个端口都不可用，"
                "请手动指定一个端口（范围 1 - 65535）"
            )
        hint = QLabel(hint_text)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        body.addWidget(hint)

        body.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom.addWidget(cancel_btn)

        ok_btn = QPushButton("使用此端口")
        ok_btn.setObjectName("okBtn")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setDefault(True)
        bottom.addWidget(ok_btn)
        body.addLayout(bottom)

        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geo = screen.availableGeometry()
            dialog_geo = dialog.frameGeometry()
            x = (screen_geo.width() - dialog_geo.width()) // 2 + screen_geo.left()
            y = (screen_geo.height() - dialog_geo.height()) // 2 + screen_geo.top()
            dialog.move(max(0, x), max(0, y))

        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, activated=dialog.reject)
        QShortcut(QKeySequence(Qt.Key.Key_Return), dialog, activated=dialog.accept)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        port = spin.value()
