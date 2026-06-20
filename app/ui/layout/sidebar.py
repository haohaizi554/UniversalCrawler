from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.plugin_registry import registry
from app.services.frontend_state_service import PAGE_DEFINITIONS
from app.services.icon_registry import nav_icon_file, platform_icon_file, ui_icon_path
from app.ui.layout.island import IslandCard
from app.ui.styles.themes import theme_colors
from app.utils.qt_runtime import load_qt_icon

_PRIMARY_PAGE_IDS = ("queue", "active", "completed", "failed")
_SECONDARY_PAGE_IDS = ("logs", "settings", "toolbox")

def _badge_diameter(text: str) -> int:
    length = len(text)
    if length <= 1:
        return 30
    if length == 2:
        return 34
    return 38

class NavBadgeLabel(QLabel):
    """Soft circular count bubble for sidebar navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("NavBadge")
        self._count_text = ""
        self._filled = False
        self._colors = theme_colors(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.update()

    def set_badge(self, count: int | None, *, filled: bool) -> None:
        if count is None:
            self.hide()
            return
        self._count_text = str(count)
        self._filled = filled
        diameter = _badge_diameter(self._count_text)
        self.setFixedSize(diameter, diameter)
        self.show()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._count_text:
            return
        colors = self._colors
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            rect = self.rect().adjusted(1, 1, -1, -1)
            center = rect.center()
            radius = min(rect.width(), rect.height()) / 2.0

            if self._filled:
                accent = QColor(colors["accent"])
                glow = QColor(colors["accent_soft"])
                glow.setAlpha(90)
                painter.setBrush(glow)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(rect.adjusted(-1, -1, 1, 1))

                gradient = QRadialGradient(center.x(), center.y() - radius * 0.22, radius * 1.05)
                gradient.setColorAt(0.0, accent.lighter(145))
                gradient.setColorAt(0.45, accent.lighter(108))
                gradient.setColorAt(0.82, accent)
                gradient.setColorAt(1.0, accent.darker(108))
                painter.setBrush(gradient)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(rect)
                text_color = QColor("#ffffff")
            else:
                fill = QColor(colors["accent_soft"])
                fill.setAlpha(185)
                painter.setBrush(fill)
                pen = QPen(QColor(colors["accent"]))
                pen.setWidthF(1.0)
                accent_pen = QColor(colors["accent"])
                accent_pen.setAlpha(140)
                pen.setColor(accent_pen)
                painter.setPen(pen)
                painter.drawEllipse(rect)
                text_color = QColor(colors["accent"])

            font = QFont(painter.font())
            font.setPixelSize(13 if len(self._count_text) <= 2 else 12)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._count_text)

class NavItemWidget(QFrame):
    """Single sidebar navigation row with optional count bubble."""

    clicked = pyqtSignal()

    def __init__(self, *, page_id: str, title: str, icon_file: str) -> None:
        super().__init__()
        self.page_id = page_id
        self.setObjectName("NavItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(40)
        self._count: int | None = None
        self._hovered = False
        self._pressed = False
        self._colors = theme_colors(False)
        self.setProperty("active", "false")
        self.setProperty("pressed", "false")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("NavIcon")
        self.icon_label.setFixedSize(18, 18)
        self.icon_label.setScaledContents(True)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon = load_qt_icon([ui_icon_path(icon_file)])
        if icon is not None:
            self.icon_label.setPixmap(icon.pixmap(QSize(18, 18)))
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("NavTitle")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label, 1)

        self.badge_label = NavBadgeLabel()
        self.badge_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.badge_label, 0, Qt.AlignmentFlag.AlignRight)

    def paintEvent(self, event) -> None:  # noqa: N802
        colors = self._colors
        active = self.property("active") == "true"
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.rect().adjusted(1, 2, -1, -2)
            if active:
                fill = QColor(colors["accent_soft"])
            elif self._pressed:
                fill = QColor(colors["accent_soft"])
                fill.setAlpha(220)
            elif self._hovered:
                fill = QColor(colors["panel_soft"])
            else:
                fill = None

            if fill is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(rect, 8, 8)

            if active or self._pressed:
                accent = QColor(colors["accent"])
                if self._pressed and not active:
                    accent.setAlpha(180)
                bar = rect.adjusted(0, 5, 0, -5)
                painter.fillRect(bar.left(), bar.top(), 3, bar.height(), accent)

        super().paintEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.setProperty("pressed", "false")
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setProperty("pressed", "true")
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.setProperty("pressed", "false")
            self.update()
            if self.rect().contains(event.position().toPoint() if hasattr(event, "position") else event.pos()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.title_label.setStyleSheet(
            f"color: {self._colors['accent']}; font-weight: 700; background: transparent;"
            if active
            else f"color: {self._colors['text']}; font-weight: 600; background: transparent;"
        )
        self.update()
        self._sync_badge()

    def set_count(self, count: int | None) -> None:
        self._count = count
        self._sync_badge()

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.badge_label.set_theme_colors(colors)
        active = self.property("active") == "true"
        self.title_label.setStyleSheet(
            f"color: {colors['accent']}; font-weight: 700; background: transparent;"
            if active
            else f"color: {colors['text']}; font-weight: 600; background: transparent;"
        )
        self.update()

    def _sync_badge(self) -> None:
        filled = self.property("active") == "true"
        self.badge_label.set_badge(self._count, filled=filled)

class SidebarWidget(QWidget):
    """Left column with platform selector and navigation islands."""

    page_selected = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(212)
        self._is_dark = False
        self._colors = theme_colors(False)
        self._items: dict[str, NavItemWidget] = {}

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        self.platform_island = IslandCard(object_name="PlatformIsland")
        self.platform_island.content_layout.setContentsMargins(12, 10, 12, 10)
        self.combo_source = self._build_platform_combo()
        self.platform_island.add_widget(self.combo_source)
        column.addWidget(self.platform_island)

        self.nav_island = IslandCard(object_name="NavIsland")
        self.nav_island.content_layout.setContentsMargins(6, 8, 6, 8)
        self.nav_island.content_layout.setSpacing(4)
        nav_host = QWidget()
        nav_layout = QVBoxLayout(nav_host)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)

        pages_by_id = {page["id"]: page for page in PAGE_DEFINITIONS}
        for page_id in _PRIMARY_PAGE_IDS:
            page = pages_by_id[page_id]
            nav_layout.addWidget(self._make_nav_item(page))
        nav_layout.addWidget(self._make_separator())
        for page_id in _SECONDARY_PAGE_IDS:
            page = pages_by_id[page_id]
            nav_layout.addWidget(self._make_nav_item(page))
        nav_layout.addStretch(1)

        self.nav_island.add_widget(nav_host, stretch=1)
        column.addWidget(self.nav_island, stretch=1)
        self.set_active("queue")

    def _make_nav_item(self, page: dict[str, str]) -> NavItemWidget:
        item = NavItemWidget(
            page_id=page["id"],
            title=page["title"],
            icon_file=nav_icon_file(page["id"]),
        )
        item.set_theme_colors(self._colors)
        item.clicked.connect(lambda page_id=page["id"]: self.page_selected.emit(page_id))
        self._items[page["id"]] = item
        return item

    @staticmethod
    def _make_separator() -> QFrame:
        line = QFrame()
        line.setObjectName("NavSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    def _build_platform_combo(self) -> QComboBox:
        combo = QComboBox()
        for plugin in registry.get_all_plugins():
            icon = load_qt_icon([ui_icon_path(platform_icon_file(plugin.id))])
            if icon is None:
                combo.addItem(plugin.name, plugin.id)
            else:
                combo.addItem(icon, plugin.name, plugin.id)
        combo.setFixedHeight(40)
        combo.setMinimumWidth(160)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        return combo

    def set_active(self, page_id: str) -> None:
        for key, item in self._items.items():
            item.set_active(key == page_id)

    def set_counts(self, counts: dict[str, int]) -> None:
        for page_id, item in self._items.items():
            item.set_count(counts.get(page_id))

    def update_counts(self, counts: dict[str, int]) -> None:
        for page_id, count in counts.items():
            item = self._items.get(page_id)
            if item is not None:
                item.set_count(count)

    def refresh_theme(self, is_dark: bool | None = None) -> None:
        if is_dark is not None:
            self._is_dark = bool(is_dark)
        self._colors = theme_colors(self._is_dark)
        for item in self._items.values():
            item.set_theme_colors(self._colors)
            item._sync_badge()
