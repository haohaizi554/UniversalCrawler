"""Reusable path picker control for settings forms."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QSizePolicy, QToolButton

from app.debug_logger import debug_logger
from app.services.icon_registry import action_icon_file, ui_icon_path
from app.ui.components.focus_state import bind_focus_property
from app.utils.qt_runtime import load_qt_icon


class SettingsPathPicker(QFrame):
    """Single-line path editor with a themed browse button."""

    path_committed = pyqtSignal(str, str)
    browse_requested = pyqtSignal(QLineEdit, str)

    def __init__(
        self,
        value: Any = "",
        *,
        setting_key: str = "",
        translate: Callable[[str], str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._setting_key = str(setting_key or "")
        self._translate = translate or (lambda text: text)
        self.setObjectName("SettingsPathField")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.setProperty("settingsControlHeight", 40)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(4)

        path_text = str(value or "")
        self.editor = QLineEdit(path_text)
        self.editor.setObjectName("SettingsLineEdit")
        self.editor.setFrame(False)
        self.editor.setMinimumHeight(36)
        self.editor.setMaximumHeight(38)
        self.editor.setTextMargins(0, 0, 0, 0)
        self.editor.setMinimumWidth(0)
        self.editor.setPlaceholderText(self._t("?????????"))
        self.editor.setToolTip(path_text)
        self.editor.setProperty("settingsOriginalText", path_text)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.editor.setCursorPosition(0)
        bind_focus_property(self.editor, self)
        QTimer.singleShot(0, lambda e=self.editor: self.scroll_editor_start(e))
        if self._setting_key:
            self.editor.editingFinished.connect(self.commit_editor)
        layout.addWidget(self.editor, 1)

        browse = QToolButton()
        browse.setObjectName("SettingsPathBrowse")
        browse.setIcon(load_qt_icon([ui_icon_path(action_icon_file("open_directory"))]))
        browse.setIconSize(QSize(18, 18))
        browse.setToolTip(self._t("??????"))
        browse.setAccessibleName(self._t("??????"))
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.setFixedSize(34, 32)
        browse.clicked.connect(lambda: self.browse_requested.emit(self.editor, self._setting_key))
        layout.addWidget(browse)

    def _t(self, text: str) -> str:
        return str(self._translate(str(text or "")) or text)

    def commit_editor(self) -> None:
        text = self.editor.text()
        self.editor.setToolTip(text)
        self.editor.setProperty("settingsOriginalText", text)
        if self._setting_key:
            self.path_committed.emit(self._setting_key, text)

    def apply_directory(self, directory: str) -> bool:
        if not directory:
            return False
        try:
            self.editor.setText(directory)
            self.editor.setToolTip(directory)
            self.editor.setProperty("settingsOriginalText", directory)
            self.scroll_editor_start(self.editor)
            return True
        except RuntimeError as exc:
            debug_logger.log_exception("SettingsPathPicker", "apply_directory", exc)
            return False

    @staticmethod
    def scroll_editor_start(editor: QLineEdit) -> None:
        editor.setCursorPosition(0)
        try:
            editor.home(False)
        except (RuntimeError, AttributeError, TypeError) as exc:
            debug_logger.log_exception("SettingsPathPicker", "scroll_editor_start", exc)
