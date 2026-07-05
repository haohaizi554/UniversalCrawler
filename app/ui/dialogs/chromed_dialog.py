"""Base dialog with the shared app-drawn titlebar chrome."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.ui.dialogs.dialog_styles import apply_themed_dialog_styles
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
from app.ui.styles import apply_dialog_theme, theme_colors


class ChromedDialog(QDialog):
    """QDialog base that reuses the app titlebar instead of native chrome."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str,
        object_name: str,
        body_margins: tuple[int, int, int, int] = (18, 18, 18, 18),
        body_spacing: int = 12,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName(object_name)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        self._is_dark = apply_dialog_theme(self, parent=parent)
        self._colors = theme_colors(self._is_dark)
        self.chrome_frame = WindowChromeFrame(
            title=title,
            icon=self._resolve_window_icon(parent),
            is_dark_theme=self._is_dark,
            show_minimize=False,
            show_maximize=False,
            show_close=True,
            body_margins=body_margins,
            body_spacing=body_spacing,
            parent=self,
        )
        self.window_title_bar = self.chrome_frame.title_bar
        self.content_layout = self.chrome_frame.body_layout
        self.window_title_bar.close_requested.connect(self.reject)
        self._window_chrome_controller = FramelessWindowChromeController(
            self,
            title_bar_getter=lambda: self.window_title_bar,
            resizable=True,
            minimizable=False,
            maximizable=False,
        )
        self._window_chrome_controller.set_window_flags()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.chrome_frame)
        self.apply_chrome_theme(self._is_dark)

    def apply_chrome_theme(self, is_dark: bool) -> None:
        self._is_dark = bool(is_dark)
        self._colors = theme_colors(self._is_dark)
        apply_dialog_theme(self, is_dark=self._is_dark)
        self.chrome_frame.apply_theme(self._is_dark)
        apply_themed_dialog_styles(self, self._colors)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._window_chrome_controller.install()
        self._window_chrome_controller.on_show_event()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._window_chrome_controller.uninstall()
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802
        hit_test = self._window_chrome_controller.handle_native_event(event_type, message)
        if hit_test is not None:
            return True, hit_test
        return False, 0

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._window_chrome_controller.mouse_press_event(event):
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if self._window_chrome_controller.event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _resolve_window_icon(parent: QWidget | None) -> QIcon | None:
        if parent is not None:
            icon = parent.windowIcon()
            if icon is not None and not icon.isNull():
                return icon
        app = QApplication.instance()
        if app is None:
            return None
        icon = app.windowIcon()
        return icon if icon is not None and not icon.isNull() else None
