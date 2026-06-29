"""Start-task control with fixed geometry and a running-state marquee."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionButton

from app.ui.styles.themes import theme_colors

class StartTaskButton(QPushButton):
    """Primary crawl trigger; keeps size stable and shows a border marquee while running."""

    _BUTTON_HEIGHT = 40
    _H_PADDING = 14
    _ICON_SIZE = 18
    _ICON_GAP = 6
    _RADIUS = 7

    def __init__(self, parent=None) -> None:
        super().__init__("启动任务", parent)
        self.setObjectName("StartTaskBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._is_dark_theme = False
        self._crawl_running = False
        self._marquee_angle = 0.0
        self._fixed_size = self._measure_size()
        self.setFixedSize(self._fixed_size)
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(45)
        self._marquee_timer.timeout.connect(self._tick_marquee)

    def _measure_size(self) -> QSize:
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        icon_width = self._ICON_SIZE if not self.icon().isNull() else 0
        gap = self._ICON_GAP if icon_width else 0
        width = self._H_PADDING * 2 + icon_width + gap + text_width
        return QSize(max(108, width), self._BUTTON_HEIGHT)

    def setIcon(self, icon) -> None:  # noqa: N802
        super().setIcon(icon)
        self._fixed_size = self._measure_size()
        self.setFixedSize(self._fixed_size)

    def set_label(self, text: str) -> None:
        if self.text() == text:
            return
        self.setText(text)
        self._fixed_size = self._measure_size()
        self.setFixedSize(self._fixed_size)

    def set_crawl_running(self, running: bool, *, is_dark_theme: bool | None = None) -> None:
        if is_dark_theme is not None:
            self._is_dark_theme = bool(is_dark_theme)
        running = bool(running)
        if self._crawl_running == running:
            if running:
                self.update()
            return
        self._crawl_running = running
        self.setProperty("running", "true" if running else "false")
        self.setEnabled(not running)
        if running:
            self._marquee_timer.start()
        else:
            self._marquee_timer.stop()
            self._marquee_angle = 0.0
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _tick_marquee(self) -> None:
        if not self._crawl_running:
            return
        self._marquee_angle = (self._marquee_angle + 4.5) % 360.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._crawl_running:
            super().paintEvent(event)
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -2, -2)
        colors = theme_colors(self._is_dark_theme)
        accent = QColor(colors["accent"])
        accent_hover = QColor(colors["accent_hover"])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(rect, self._RADIUS, self._RADIUS)

        shine_width = max(28, rect.width() // 3)
        travel = rect.width() + shine_width
        shine_x = (self._marquee_angle / 360.0) * travel - shine_width
        shine = QLinearGradient(shine_x, 0, shine_x + shine_width, 0)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.45, QColor(255, 255, 255, 55))
        shine.setColorAt(0.55, QColor(255, 255, 255, 55))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(rect, shine)

        center_x = rect.center().x()
        center_y = rect.center().y()
        ring = QConicalGradient(center_x, center_y, self._marquee_angle)
        ring.setColorAt(0.0, QColor(255, 255, 255, 220))
        ring.setColorAt(0.08, accent_hover)
        ring.setColorAt(0.22, QColor(255, 255, 255, 0))
        ring.setColorAt(1.0, QColor(255, 255, 255, 0))
        border_pen = QPen(QBrush(ring), 2.2)
        border_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._RADIUS - 1, self._RADIUS - 1)

        painter.setPen(QColor("#ffffff"))
        label = self.text()
        text_rect = rect.adjusted(self._H_PADDING, 0, -self._H_PADDING, 0)
        if not self.icon().isNull():
            icon_rect = rect
            icon_rect.setWidth(self._ICON_SIZE + self._H_PADDING)
            self.style().drawItemPixmap(
                painter,
                icon_rect,
                Qt.AlignmentFlag.AlignCenter,
                self.icon().pixmap(self._ICON_SIZE, self._ICON_SIZE),
            )
            text_rect.adjust(self._ICON_SIZE + self._ICON_GAP, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
