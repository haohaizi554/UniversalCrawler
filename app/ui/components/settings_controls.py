from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from app.ui.components.combo_popup import ThemedComboBox, polish_combo_popup, schedule_combo_popup_repolish
from app.ui.styles.themes import theme_colors


class UiSwitch(QCheckBox):
    """Pill toggle switch without native checkbox chrome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme_colors(False)
        self.setObjectName("SettingsUiSwitch")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setText("")
        self.setFixedSize(48, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(48, 28)

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._palette = colors
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event

        if self.width() <= 0 or self.height() <= 0:
            return

        colors = self._palette
        checked = self.isChecked()
        enabled = self.isEnabled()

        track_on = QColor(colors["accent"])
        track_off = QColor("#cbd5e1" if colors["panel"].lower() == "#ffffff" else "#4b5563")
        knob = QColor("#ffffff")

        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if not enabled:
                painter.setOpacity(0.45)

            rect = QRectF(1, 3, 46, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track_on if checked else track_off)
            painter.drawRoundedRect(rect, 11, 11)

            knob_x = 25 if checked else 4
            painter.setBrush(knob)
            painter.drawEllipse(QRectF(knob_x, 5, 18, 18))
        finally:
            painter.end()


class SegmentedControl(QWidget):
    selection_changed = pyqtSignal(str)

    def __init__(
        self,
        options: list[tuple[str, str]],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._colors = theme_colors(False)
        self.setObjectName("SettingsSegmented")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for index, (value, label) in enumerate(self._options):
            button = QPushButton(label)
            button.setObjectName("SettingsSegmentButton")
            button.setCheckable(True)
            button.setProperty("segment_value", value)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(36)
            if index == 0:
                button.setProperty("segment_pos", "left")
            elif index == len(self._options) - 1:
                button.setProperty("segment_pos", "right")
            else:
                button.setProperty("segment_pos", "middle")
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button, 1)
            button.toggled.connect(lambda checked, key=value: self._on_toggled(key, checked))

        if self._options:
            self._buttons[self._options[0][0]].setChecked(True)

    def _on_toggled(self, value: str, checked: bool) -> None:
        if checked:
            self.selection_changed.emit(value)

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.update()

    def set_value(self, value: str) -> None:
        button = self._buttons.get(str(value))
        if button is not None:
            blocked = button.blockSignals(True)
            try:
                button.setChecked(True)
            finally:
                button.blockSignals(blocked)

    def value(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return self._options[0][0] if self._options else ""


class SettingsComboBox(ThemedComboBox):
    """Stable settings combo that keeps the active accent while the popup is open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The settings stylesheet owns the control chrome; the shared helper owns popup behavior.
        self.setStyleSheet("")
        self.setProperty("themedComboControlStyle", "false")
        self.setProperty("comboPopupClampToControl", "true")
        self.setProperty("popupOpen", "false")

    def _set_popup_open(self, open_: bool) -> None:
        self.setProperty("popupOpen", "true" if open_ else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def showPopup(self) -> None:  # noqa: N802
        self._set_popup_open(True)
        if self.width() > 0:
            self.setProperty("comboPopupMaxWidth", int(self.width()))
        polish_combo_popup(self, row_height=self.property("comboPopupRowHeight") or 38)
        QComboBox.showPopup(self)
        if self.width() > 0:
            self.setProperty("comboPopupMaxWidth", int(self.width()))
        polish_combo_popup(self, row_height=self.property("comboPopupRowHeight") or 38)
        schedule_combo_popup_repolish(self)

    def hidePopup(self) -> None:  # noqa: N802
        QComboBox.hidePopup(self)
        self._set_popup_open(False)
