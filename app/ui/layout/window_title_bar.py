"""Application-drawn title bar for the frameless main window."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QWidget

from app.ui.styles import theme_colors


class WindowChromeButton(QAbstractButton):
    """Window control button painted by Qt instead of a font glyph."""

    WIDTH = 38

    def __init__(self, kind: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._colors = theme_colors(False)
        self._maximized = False
        self.setObjectName("WindowCloseButton" if kind == "close" else "WindowChromeButton")
        self.setToolTip(tooltip)
        self.setFixedSize(self.WIDTH, WindowTitleBar.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._colors = dict(colors)
        self.update()

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = bool(maximized)
        self.update()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self._colors
        hovered = self.underMouse()
        pressed = self.isDown()
        background = colors["bg"]

        if hovered or pressed:
            if self.kind == "close":
                background = colors["danger_hover"] if pressed else colors["danger"]
            else:
                background = colors["border"] if pressed else colors["panel_soft"]
            painter.fillRect(self.rect(), QColor(background))

        foreground = "#ffffff" if self.kind == "close" and hovered else colors["text"]
        pen = QPen(QColor(foreground), 1.35)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        center = self.rect().center()

        if self.kind == "minimize":
            y = center.y() + 4
            painter.drawLine(center.x() - 5, y, center.x() + 5, y)
        elif self.kind == "maximize":
            if self._maximized:
                painter.drawRect(center.x() - 3, center.y() - 6, 9, 9)
                painter.fillRect(center.x() - 6, center.y() - 3, 9, 9, QColor(background))
                painter.drawRect(center.x() - 6, center.y() - 3, 9, 9)
            else:
                painter.drawRect(center.x() - 5, center.y() - 5, 10, 10)
        elif self.kind == "close":
            painter.drawLine(center.x() - 5, center.y() - 5, center.x() + 5, center.y() + 5)
            painter.drawLine(center.x() + 5, center.y() - 5, center.x() - 5, center.y() + 5)


class WindowTitleBar(QWidget):
    """A Qt-rendered title bar that shares the same theme frame as the app."""

    minimize_requested = pyqtSignal()
    maximize_restore_requested = pyqtSignal()
    close_requested = pyqtSignal()

    HEIGHT = 28

    def __init__(self, *, title: str, icon: QIcon | None = None, is_dark_theme: bool = False) -> None:
        super().__init__()
        self.setObjectName("WindowTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._is_maximized = False

        self.icon_label = QLabel()
        self.icon_label.setObjectName("WindowTitleIcon")
        self.icon_label.setFixedSize(18, 18)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("WindowTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.btn_minimize = self._make_button("minimize", "最小化")
        self.btn_maximize = self._make_button("maximize", "最大化")
        self.btn_close = self._make_button("close", "关闭")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 0, 0)
        layout.setSpacing(5)
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

    def _make_button(self, kind: str, tooltip: str) -> WindowChromeButton:
        return WindowChromeButton(kind, tooltip, self)

    def set_title(self, title: str) -> None:
        self.title_label.setText(str(title or "Universal Crawler Pro"))

    def set_icon(self, icon: QIcon | None) -> None:
        if icon is None or icon.isNull():
            self.icon_label.clear()
            self.icon_label.hide()
            return
        self.icon_label.show()
        self.icon_label.setPixmap(icon.pixmap(16, 16))

    def set_maximized(self, maximized: bool) -> None:
        self._is_maximized = bool(maximized)
        self.btn_maximize.set_maximized(self._is_maximized)
        self.btn_maximize.setToolTip("还原" if self._is_maximized else "最大化")

    def is_interactive_at(self, pos) -> bool:
        return any(
            button.isVisible() and button.geometry().contains(pos)
            for button in (self.btn_minimize, self.btn_maximize, self.btn_close)
        )

    def apply_theme(self, is_dark: bool) -> None:
        c = theme_colors(is_dark)
        for button in (self.btn_minimize, self.btn_maximize, self.btn_close):
            button.set_theme_colors(c)
        self.setStyleSheet(
            f"""
            QWidget#WindowTitleBar {{
                background: {c["bg"]};
                border-bottom: 1px solid {c["border"]};
            }}
            QLabel#WindowTitleLabel {{
                color: {c["text"]};
                font-size: 12px;
                font-weight: 500;
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
