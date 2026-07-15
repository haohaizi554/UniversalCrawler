from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QLineEdit

from app.ui.styles.themes import resolve_is_dark_theme, theme_colors


def log_filter_input_style(*, is_dark: bool, focused: bool = False) -> str:
    colors = theme_colors(is_dark)
    border_width = "2px" if focused else "1px"
    border_color = colors["accent"] if focused else colors["border"]
    padding = "1px 9px" if focused else "2px 10px"
    return """
    QLineEdit,
    QLineEdit#LogFilterTextInput {{
        background: {input};
        border: {border_width} solid {border_color};
        border-radius: 8px;
        min-height: 32px;
        max-height: 32px;
        padding: {padding};
        font-size: 13px;
        color: {text};
        selection-background-color: {accent};
        selection-color: #ffffff;
    }}
    QLineEdit:focus,
    QLineEdit[focused="true"],
    QLineEdit#LogFilterTextInput:focus,
    QLineEdit#LogFilterTextInput[focused="true"] {{
        border: 2px solid {accent};
        padding: 1px 9px;
    }}
    """.format(border_width=border_width, border_color=border_color, padding=padding, **colors)


class LogFilterLineEdit(QLineEdit):
    """随主题更新，并在焦点变化时立即刷新边框的日志筛选框。"""

    def __init__(self, sync_focus_style: Callable[[], None]) -> None:
        super().__init__()
        self._sync_focus_style = sync_focus_style
        self.setObjectName("LogFilterTextInput")
        self.setFrame(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("focused", "false")

    def focusInEvent(self, event) -> None:  # noqa: ANN001
        super().focusInEvent(event)
        self._set_focused(True)

    def focusOutEvent(self, event) -> None:  # noqa: ANN001
        super().focusOutEvent(event)
        self._set_focused(False)
        QTimer.singleShot(0, self._sync_focus_style)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        super().keyPressEvent(event)
        self._set_focused(True)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        super().mousePressEvent(event)
        self._set_focused(True)

    def inputMethodEvent(self, event) -> None:  # noqa: ANN001
        super().inputMethodEvent(event)
        self._set_focused(True)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        super().paintEvent(event)
        if not (self.hasFocus() or self.property("focused") == "true"):
            return
        colors = theme_colors(resolve_is_dark_theme(self))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(colors["accent"]), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

    def _set_focused(self, focused: bool) -> None:
        self.setProperty("focused", "true" if focused else "false")
        self._sync_focus_style()


def sync_log_filter_input_styles(editors: Iterable[LogFilterLineEdit], *, is_dark: bool) -> None:
    current_focus = QApplication.focusWidget()
    for editor in editors:
        focused = bool(editor.hasFocus() or editor is current_focus or editor.property("focused") == "true")
        desired = "true" if focused else "false"
        if editor.property("focused") != desired:
            editor.setProperty("focused", desired)
        style = log_filter_input_style(is_dark=is_dark, focused=focused)
        if editor.styleSheet() != style:
            editor.setStyleSheet(style)
        editor.style().unpolish(editor)
        editor.style().polish(editor)
        editor.update()
