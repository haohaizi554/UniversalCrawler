from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app.ui.styles.themes import theme_colors

class ThemeCheckBox(QWidget):
    """Painted toggle box; can be display-only when embedded inside QTableWidget cells."""

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        *,
        checked: bool = False,
        colors: dict[str, str] | None = None,
        interactive: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = dict(colors or theme_colors(False))
        self._checked = bool(checked)
        self._pressed = False
        self._interactive = bool(interactive)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._interactive else Qt.CursorShape.ArrowCursor)
        self.setFixedSize(20, 20)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if not self._interactive:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, notify: bool = True) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()
        if notify:
            self.toggled.emit(checked)

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._colors = dict(colors)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        colors = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)
        hovered = self._interactive and self.underMouse()

        if self._checked:
            fill = QColor(colors["accent_hover"] if (self._pressed or hovered) else colors["accent"])
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 4, 4)
            self._paint_checkmark(painter, rect)
        else:
            fill = QColor(colors["accent_soft"] if self._pressed else colors["input"])
            if hovered and not self._pressed:
                fill = QColor(colors["panel_soft"])
            border = QColor(colors["accent"] if (hovered or self._pressed) else colors["border_strong"])
            painter.setBrush(fill)
            pen = QPen(border)
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 4, 4)

        painter.end()

    @staticmethod
    def _paint_checkmark(painter: QPainter, rect) -> None:
        pen = QPen(QColor("#ffffff"))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        x = rect.x()
        y = rect.y()
        w = rect.width()
        h = rect.height()
        painter.drawLine(QPointF(x + w * 0.22, y + h * 0.54), QPointF(x + w * 0.42, y + h * 0.74))
        painter.drawLine(QPointF(x + w * 0.42, y + h * 0.74), QPointF(x + w * 0.80, y + h * 0.28))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._interactive:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._interactive:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            point = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if self.rect().contains(point):
                self.setChecked(not self._checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().leaveEvent(event)
