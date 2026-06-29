"""Application-drawn title bar for the frameless main window."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from app.ui.styles import theme_colors


class WindowTitleBar(QWidget):
    """A Qt-rendered title bar that shares the same theme frame as the app."""

    minimize_requested = pyqtSignal()
    maximize_restore_requested = pyqtSignal()
    close_requested = pyqtSignal()

    HEIGHT = 34

    def __init__(self, *, title: str, icon: QIcon | None = None, is_dark_theme: bool = False) -> None:
        super().__init__()
        self.setObjectName("WindowTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._is_maximized = False

        self.icon_label = QLabel()
        self.icon_label.setObjectName("WindowTitleIcon")
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("WindowTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.btn_minimize = self._make_button("─", "最小化", "WindowChromeButton")
        self.btn_maximize = self._make_button("□", "最大化", "WindowChromeButton")
        self.btn_close = self._make_button("×", "关闭", "WindowCloseButton")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label, stretch=1)
        layout.addWidget(self.btn_minimize)
        layout.addWidget(self.btn_maximize)
        layout.addWidget(self.btn_close)

        self.btn_minimize.clicked.connect(self.minimize_requested.emit)
        self.btn_maximize.clicked.connect(self.maximize_restore_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)

        self.set_icon(icon)
        self.apply_theme(is_dark_theme)

    def _make_button(self, text: str, tooltip: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setToolTip(tooltip)
        button.setFixedSize(46, self.HEIGHT)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        return button

    def set_title(self, title: str) -> None:
        self.title_label.setText(str(title or "Universal Crawler Pro"))

    def set_icon(self, icon: QIcon | None) -> None:
        if icon is None or icon.isNull():
            self.icon_label.clear()
            self.icon_label.hide()
            return
        self.icon_label.show()
        self.icon_label.setPixmap(icon.pixmap(18, 18))

    def set_maximized(self, maximized: bool) -> None:
        self._is_maximized = bool(maximized)
        self.btn_maximize.setText("❐" if self._is_maximized else "□")
        self.btn_maximize.setToolTip("还原" if self._is_maximized else "最大化")

    def is_interactive_at(self, pos) -> bool:
        return any(
            button.isVisible() and button.geometry().contains(pos)
            for button in (self.btn_minimize, self.btn_maximize, self.btn_close)
        )

    def apply_theme(self, is_dark: bool) -> None:
        c = theme_colors(is_dark)
        normal_hover = c["panel_soft"] if is_dark else c["accent_soft"]
        self.setStyleSheet(
            f"""
            QWidget#WindowTitleBar {{
                background: {c["bg"]};
                border-bottom: 1px solid {c["border"]};
            }}
            QLabel#WindowTitleLabel {{
                color: {c["text"]};
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton#WindowChromeButton,
            QPushButton#WindowCloseButton {{
                background: transparent;
                border: none;
                border-radius: 0px;
                color: {c["text"]};
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton#WindowChromeButton:hover {{
                background: {normal_hover};
            }}
            QPushButton#WindowChromeButton:pressed {{
                background: {c["row_selected"]};
            }}
            QPushButton#WindowCloseButton:hover {{
                background: {c["danger"]};
                color: #ffffff;
            }}
            QPushButton#WindowCloseButton:pressed {{
                background: {c["danger_hover"]};
                color: #ffffff;
            }}
            """
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.is_interactive_at(event.position().toPoint()):
            self.maximize_restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.is_interactive_at(event.position().toPoint()):
            window = self.window().windowHandle()
            if window is not None and hasattr(window, "startSystemMove"):
                if window.startSystemMove():
                    event.accept()
                    return
        super().mousePressEvent(event)
