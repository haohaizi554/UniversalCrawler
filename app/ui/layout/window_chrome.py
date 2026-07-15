"""为应用窗口与对话框提供可复用的无边框 chrome。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from app.ui.layout.window_title_bar import WindowTitleBar
from app.ui.styles import build_palette, theme_colors


class WindowChromeFrame(QWidget):
    """组合共享 Qt 自绘标题栏与主题化内容宿主。"""

    def __init__(
        self,
        *,
        title: str,
        icon: QIcon | None = None,
        is_dark_theme: bool = False,
        show_minimize: bool = True,
        show_maximize: bool = True,
        show_close: bool = True,
        body_margins: tuple[int, int, int, int] = (0, 0, 0, 0),
        body_spacing: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("WindowChromeFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.title_bar = WindowTitleBar(
            title=title,
            icon=icon,
            is_dark_theme=is_dark_theme,
            show_minimize=show_minimize,
            show_maximize=show_maximize,
            show_close=show_close,
        )
        self.body = QWidget(self)
        self.body.setObjectName("WindowChromeBody")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body.setAutoFillBackground(True)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(*body_margins)
        self.body_layout.setSpacing(body_spacing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addWidget(self.body, stretch=1)
        self.apply_theme(is_dark_theme)

    def apply_theme(self, is_dark: bool) -> None:
        colors = theme_colors(is_dark)
        palette = build_palette(is_dark)
        self.setPalette(palette)
        self.body.setPalette(palette)
        self.title_bar.apply_theme(is_dark)
        self.setStyleSheet(
            f"""
            QWidget#WindowChromeFrame {{
                background-color: {colors["bg"]};
            }}
            QWidget#WindowChromeBody {{
                background-color: {colors["bg"]};
            }}
            """
        )

    def set_title(self, title: str) -> None:
        self.title_bar.set_title(title)

    def set_icon(self, icon: QIcon | None) -> None:
        self.title_bar.set_icon(icon)

    def set_maximized(self, maximized: bool) -> None:
        self.title_bar.set_maximized(maximized)
