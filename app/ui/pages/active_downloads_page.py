
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import action_icon_file, platform_icon_file, ui_icon_path
from app.ui.pages.common import PageFrame
from app.ui.styles.table_rows import (
    install_click_only_row_selection,
    install_stable_vertical_scrollbar,
    normalize_table_item_option,
    paint_item_selection_background,
)
from app.ui.styles.themes import theme_colors
from app.utils.qt_runtime import load_qt_icon

TEXT = {
    "page_title": "\u6b63\u5728\u4e0b\u8f7d",
    "current_download": "\u5f53\u524d\u4e0b\u8f7d",
    "queue_control": "\u961f\u5217\u63a7\u5236",
    "auto_retry": "\u5931\u8d25\u81ea\u52a8\u91cd\u8bd5",
    "max_retry": "\u6700\u5927\u91cd\u8bd5\u6b21\u6570",
    "threads": "\u5e76\u53d1\u7ebf\u7a0b\u6570",
    "running_count": "\u5f53\u524d\u8fd0\u884c\uff1a{count}\u4e2a\u4efb\u52a1",
    "event_title": "\u5f53\u524d\u4efb\u52a1\u4e8b\u4ef6",
    "trend_title": "\u901f\u5ea6\u8d8b\u52bf\uff08\u8fd160\u79d2\uff09",
    "empty_events": "",
    "no_selection": "\u6682\u65e0\u6b63\u5728\u4e0b\u8f7d\u7684\u4efb\u52a1",
    "title": "\u6807\u9898",
    "platform": "\u5e73\u53f0",
    "save_dir": "\u4fdd\u5b58\u76ee\u5f55",
    "output_filename": "\u8f93\u51fa\u6587\u4ef6\u540d",
    "chunk_progress": "\u5206\u7247\u8fdb\u5ea6",
    "thread_count": "\u7ebf\u7a0b\u6570",
    "retry_count": "\u91cd\u8bd5\u6b21\u6570",
    "write_status": "\u5199\u5165\u72b6\u6001",
    "merge_status": "\u5408\u5e76\u72b6\u6001",
    "source_url": "\u6765\u6e90\u94fe\u63a5",
    "trace_id": "Trace ID",
    "delete": "\u5220\u9664",
}

class ActiveDownloadsModel(QAbstractTableModel):
    HEADERS = ["\u6807\u9898", "\u5e73\u53f0", "\u8fdb\u5ea6", "\u901f\u5ea6", "\u5269\u4f59\u65f6\u95f4", "\u64cd\u4f5c"]
    COLUMNS = ["title", "platform", "progress", "speed", "remaining_time", "actions"]
    PROGRESS_COLUMN = 2
    ACTION_COLUMN = 5
    ROW_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._row_signatures: list[tuple] = []

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        column = self.COLUMNS[index.column()]
        if role == self.ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.TextAlignmentRole:
            align = Qt.AlignmentFlag.AlignLeft if index.column() == 0 else Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignVCenter | align
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(row.get(column, ""))
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.column() == self.PROGRESS_COLUMN:
            return int(row.get("progress") or 0)
        if index.column() == self.ACTION_COLUMN:
            return TEXT["delete"]
        return str(row.get(column, ""))

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        rows = list(rows)
        signatures = [self._row_signature(row) for row in rows]
        if signatures == self._row_signatures:
            return False
        same_shape = [signature[0] for signature in signatures] == [signature[0] for signature in self._row_signatures]
        if same_shape and len(rows) == len(self._rows):
            self._rows = rows
            changed_roles = [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, self.ROW_ROLE]
            for row_index, (old, new) in enumerate(zip(self._row_signatures, signatures)):
                if old == new:
                    continue
                start = self.index(row_index, 0)
                end = self.index(row_index, self.columnCount() - 1)
                self.dataChanged.emit(start, end, changed_roles)
        else:
            self.beginResetModel()
            self._rows = rows
            self.endResetModel()
        self._row_signatures = signatures
        return True

    def row_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def item_id_at(self, row: int) -> str:
        item = self.row_at(row)
        return str((item or {}).get("id") or "")

    def row_for_id(self, item_id: str) -> int:
        for row, item in enumerate(self._rows):
            if item.get("id") == item_id:
                return row
        return -1

    @staticmethod
    def _row_signature(row: dict[str, Any]) -> tuple:
        return (
            row.get("id", ""),
            str(row.get("title", "")),
            str(row.get("platform", "")),
            int(row.get("progress") or 0),
            str(row.get("speed", "")),
            str(row.get("remaining_time", "")),
        )

class ActiveDownloadsDelegate(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action_icons = {
            "delete": load_qt_icon([ui_icon_path("action_delete_red.png")], fallback_names=[ui_icon_path(action_icon_file("delete"))]),
        }
        self._platform_icons: dict[str, Any] = {}

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        paint_item_selection_background(painter, option)
        if index.column() == 1:
            self._paint_platform(painter, option, index)
            return
        if index.column() == ActiveDownloadsModel.PROGRESS_COLUMN:
            value = max(0, min(100, int(index.data(Qt.ItemDataRole.DisplayRole) or 0)))
            colors = theme_colors(option.palette.color(QPalette.ColorRole.Base).lightness() < 128)
            painter.save()
            track_width = max(52, option.rect.width() - 48)
            track_rect = QRect(option.rect.x() + 10, option.rect.center().y() - 3, track_width, 6)
            fill_rect = QRect(track_rect)
            fill_rect.setWidth(max(3, int(track_rect.width() * value / 100)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["border"]))
            painter.drawRoundedRect(track_rect, 3, 3)
            painter.setBrush(QColor(colors["accent"]))
            painter.drawRoundedRect(fill_rect, 3, 3)
            percent_rect = QRect(track_rect.right() + 8, option.rect.y(), option.rect.right() - track_rect.right() - 8, option.rect.height())
            painter.setPen(QColor(colors["text"]))
            painter.drawText(percent_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{value}%")
            painter.restore()
            return
        if index.column() == ActiveDownloadsModel.ACTION_COLUMN:
            self._paint_actions(painter, option)
            return
        padded = QStyleOptionViewItem(option)
        left_padding = 16 if index.column() == 0 else 8
        padded.rect = option.rect.adjusted(left_padding, 0, -8, 0)
        normalize_table_item_option(padded)
        super().paint(painter, padded, index)

    def _platform_icon(self, platform_id: str):
        key = str(platform_id or "web").lower()
        if key not in self._platform_icons:
            self._platform_icons[key] = load_qt_icon([ui_icon_path(platform_icon_file(key))])
        return self._platform_icons[key]

    def _paint_platform(self, painter: QPainter, option, index: QModelIndex) -> None:
        row = index.data(ActiveDownloadsModel.ROW_ROLE) or {}
        platform_id = str(row.get("platform_id") or "web")
        platform = str(row.get("platform") or "")
        colors = theme_colors(option.palette.color(QPalette.ColorRole.Base).lightness() < 128)
        painter.save()
        icon_rect = QRect(option.rect.x() + 10, option.rect.y() + (option.rect.height() - 20) // 2, 20, 20)
        icon = self._platform_icon(platform_id)
        if icon is not None:
            icon.paint(painter, icon_rect)
        text_rect = option.rect.adjusted(36, 0, -4, 0)
        painter.setPen(QColor(colors["text"]))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, platform)
        painter.restore()

    def _paint_actions(self, painter: QPainter, option) -> None:
        painter.save()
        base = option.palette.color(QPalette.ColorRole.Base)
        colors = theme_colors(base.lightness() < 128)
        action = "delete"
        button_size = 34
        x = option.rect.x() + max(6, (option.rect.width() - button_size) // 2)
        y = option.rect.y() + (option.rect.height() - button_size) // 2
        for index, action in enumerate((action,)):
            rect = QRect(x, y, button_size, button_size)
            painter.setPen(QColor(colors["border"]))
            painter.setBrush(QColor(colors["panel_soft"]))
            painter.drawRoundedRect(rect, 6, 6)
            icon = self._action_icons.get(action)
            if icon is not None:
                icon.paint(painter, rect.adjusted(8, 8, -8, -8))
            else:
                fallback = "X"
                painter.setPen(QColor(colors["danger"]))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, fallback)
        painter.restore()

class ActiveDownloadsTable(QTableView):
    action_requested = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ActiveDownloadsTable")
        self._model = ActiveDownloadsModel(self)
        self.setModel(self._model)
        self.setItemDelegate(ActiveDownloadsDelegate(self))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(74)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        install_stable_vertical_scrollbar(self)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumHeight(470)
        self.setMaximumHeight(16777215)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 82), (2, 118), (3, 92), (4, 100), (5, 72)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)
        install_click_only_row_selection(self)

    def model(self) -> ActiveDownloadsModel:  # type: ignore[override]
        return self._model

    def mouseReleaseEvent(self, event) -> None:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(position)
        if index.isValid() and index.column() == ActiveDownloadsModel.ACTION_COLUMN and event.button() == Qt.MouseButton.LeftButton:
            item_id = self.model().item_id_at(index.row())
            if item_id:
                self.action_requested.emit("delete", item_id)
            return
        super().mouseReleaseEvent(event)

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        return self.model().set_rows(rows)

    def selected_id(self) -> str | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.model().item_id_at(indexes[0].row()) or None

    def row_for_id(self, item_id: str) -> int:
        return self.model().row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        row = self.row_for_id(item_id)
        if row < 0:
            return False
        self.selectRow(row)
        return True

class SpeedTrendWidget(QWidget):
    HEIGHT = 138

    def __init__(self) -> None:
        super().__init__()
        self._values: list[float] = []
        self._speed_label = "0 B/s"
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: list[int | float], speed_label: str = "") -> None:
        raw = [max(0.0, float(value or 0)) for value in values[-60:]]
        if raw and max(raw) > 1024:
            raw = [value / 1048576 for value in raw]
        resolved_speed = str(speed_label or "0 B/s")
        if raw == self._values and resolved_speed == self._speed_label:
            return
        self._values = raw
        self._speed_label = resolved_speed
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().palette().color(QPalette.ColorRole.Window).lightness() < 128)
        rect = self.rect().adjusted(8, 26, -8, -24)
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.topLeft())
        max_value = max(max(self._values, default=0), 6.0)
        for value in (0, max_value / 3, max_value * 2 / 3, max_value):
            y = rect.bottom() - int(rect.height() * value / max_value)
            grid_color = QColor(colors["border"])
            grid_color.setAlpha(90)
            painter.setPen(QPen(grid_color, 1))
            painter.drawLine(rect.left(), y, rect.right(), y)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(rect.left() + 3, y - 2, f"{value:.0f}")
        if self._values:
            points: list[tuple[int, int]] = []
            count = max(len(self._values) - 1, 1)
            for index, value in enumerate(self._values):
                x = rect.left() + int(rect.width() * index / count)
                y = rect.bottom() - int(rect.height() * value / max_value)
                points.append((x, y))
            painter.setPen(QPen(QColor(colors["accent"]), 2))
            for first, second in zip(points, points[1:]):
                painter.drawLine(first[0], first[1], second[0], second[1])
            painter.setBrush(QColor(colors["accent"]))
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y in points[-10:]:
                painter.drawEllipse(x - 2, y - 2, 4, 4)
        muted = QColor(colors["muted"])
        painter.setPen(muted)
        metrics = painter.fontMetrics()
        speed_text = metrics.elidedText(self._speed_label, Qt.TextElideMode.ElideLeft, max(80, rect.width() // 2))
        painter.drawText(QRect(rect.left(), 2, rect.width(), 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, speed_text)
        painter.drawText(rect.left(), self.height() - 6, "\u0036\u0030\u79d2")
        painter.drawText(rect.left() + rect.width() // 4, self.height() - 6, "\u0034\u0035\u79d2")
        painter.drawText(rect.left() + rect.width() // 2, self.height() - 6, "\u0033\u0030\u79d2")
        painter.drawText(rect.left() + rect.width() * 3 // 4, self.height() - 6, "\u0031\u0035\u79d2")
        painter.drawText(rect.right() - 28, self.height() - 6, "\u73b0\u5728")
        painter.end()


class EventTimelineWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self.setMinimumHeight(150)
        self.setMaximumHeight(190)

    def set_events(self, events: list[dict[str, Any]]) -> None:
        normalized = [dict(event) for event in events[-6:]]
        if normalized == self._events:
            return
        self._events = normalized
        self.update()

    def setPlainText(self, text: str) -> None:
        events = []
        for line in str(text or "").splitlines():
            time, _, message = line.partition("  ")
            events.append({"time": time, "message": message or time})
        self.set_events(events)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().palette().color(QPalette.ColorRole.Window).lightness() < 128)
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        if not self._events:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(self.rect().adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "\u6682\u65e0\u4e8b\u4ef6")
            return
        x = 14
        top = 16
        row_h = 25
        line_color = QColor(colors["accent"])
        line_color.setAlpha(80)
        painter.setPen(QPen(line_color, 1))
        painter.drawLine(x, top + 4, x, top + row_h * (len(self._events) - 1) + 4)
        metrics = painter.fontMetrics()
        for index, event in enumerate(self._events):
            y = top + row_h * index
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["accent"]))
            painter.drawEllipse(x - 4, y, 8, 8)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRect(x + 18, y - 5, 64, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(event.get("time", "")))
            painter.setPen(QColor(colors["text"]))
            message = metrics.elidedText(str(event.get("message", "")), Qt.TextElideMode.ElideRight, max(80, self.width() - 102))
            painter.drawText(QRect(x + 86, y - 5, self.width() - 104, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, message)
        painter.end()

class WideHitCheckBox(QCheckBox):
    """Checkbox whose whole visual rectangle toggles the checked state."""

    def hitButton(self, pos) -> bool:  # type: ignore[override]
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        del event
        is_dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        colors = theme_colors(is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        enabled = self.isEnabled()
        hover = self.underMouse() and enabled
        outer = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(colors["accent"] if hover else colors["border"]), 1))
        painter.setBrush(QColor(colors["accent_soft"] if hover else colors["panel_soft"]))
        painter.drawRoundedRect(outer, 7, 7)

        indicator = QRect(10, (self.height() - 20) // 2, 20, 20)
        if self.isChecked():
            fill = QColor(colors["accent"] if enabled else colors["border_strong"])
            border = fill
        else:
            fill = QColor(colors["input"] if enabled else colors["panel_soft"])
            border = QColor(colors["border_strong"] if enabled else colors["border"])
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(indicator, 6, 6)

        if self.isChecked():
            painter.setPen(
                QPen(
                    QColor("#ffffff"),
                    2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawLine(indicator.left() + 5, indicator.center().y(), indicator.left() + 9, indicator.bottom() - 6)
            painter.drawLine(indicator.left() + 9, indicator.bottom() - 6, indicator.right() - 5, indicator.top() + 6)

        text_rect = self.rect().adjusted(40, 0, 10, 0)
        painter.setPen(QColor(colors["text"] if enabled else colors["muted"]))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

class SmartWrapLabel(QLabel):
    """Selectable label that prefers wrapping paths and URLs at separators."""

    BREAK = "\u200b"

    def __init__(self, value: Any = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw_text = ""
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setText(value)

    @staticmethod
    def wrap_text(value: Any) -> str:
        text = str(value or "")
        return text.replace("\\", "\\" + SmartWrapLabel.BREAK).replace("/", "/" + SmartWrapLabel.BREAK)

    def setText(self, value: Any) -> None:  # type: ignore[override]
        self._raw_text = str(value or "")
        super().setText(self.wrap_text(self._raw_text))
        self.setToolTip(self._raw_text)

    def raw_text(self) -> str:
        return self._raw_text

class ActiveDownloadsPage(PageFrame):
    delete_requested = pyqtSignal(str)
    options_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.table_card = QFrame()
        self.table_card.setObjectName("ActiveTableCard")
        table_card_layout = QVBoxLayout(self.table_card)
        table_card_layout.setContentsMargins(12, 10, 12, 10)
        table_card_layout.setSpacing(0)
        self.table = ActiveDownloadsTable()
        table_card_layout.addWidget(self.table, 1)
        left_layout.addWidget(self.table_card, 1)
        self._build_queue_controls(left_layout)
        splitter.addWidget(left)

        self.detail = QWidget()
        self.detail.setMinimumWidth(360)
        self.detail.setMaximumWidth(500)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("ActiveDetailCard")
        self.detail_card_layout = QVBoxLayout(self.detail_card)
        self.detail_card_layout.setContentsMargins(12, 10, 12, 10)
        self.detail_card_layout.setSpacing(6)
        self.detail_title = QLabel(TEXT["current_download"])
        self.detail_title.setObjectName("SectionTitle")
        self.detail_card_layout.addWidget(self.detail_title)
        self.detail_body = QWidget()
        self.detail_card_layout.addWidget(self.detail_body)
        self.detail_layout.addWidget(self.detail_card, 0)

        self.events_card = QFrame()
        self.events_card.setObjectName("ActiveEventsCard")
        self.events_card_layout = QVBoxLayout(self.events_card)
        self.events_card_layout.setContentsMargins(12, 10, 12, 10)
        self.events_card_layout.setSpacing(6)
        self.detail_events_title = QLabel(TEXT["event_title"])
        self.detail_events_title.setObjectName("SectionTitle")
        self.events_card_layout.addWidget(self.detail_events_title)
        self.events = EventTimelineWidget()
        self.events_card_layout.addWidget(self.events, 0, Qt.AlignmentFlag.AlignTop)
        self.events_card_layout.addStretch(1)
        self.detail_layout.addWidget(self.events_card, 1)
        splitter.addWidget(self.detail)
        splitter.setSizes([760, 400])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict[str, Any]] = []
        self._detail_signature: tuple | None = None
        self._selected_detail_id: str | None = None
        self._detail_value_labels: dict[str, QLabel] = {}
        self._chunk_bar: QProgressBar | None = None
        self._trend_widget: SpeedTrendWidget | None = None
        self.table.selectionModel().currentChanged.connect(self._on_table_selection_changed)
        self.table.action_requested.connect(self._on_table_action)

    def _build_queue_controls(self, parent_layout: QVBoxLayout) -> None:
        panel = QFrame()
        panel.setObjectName("QueueControlPanel")
        panel.setFixedHeight(96)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(7)
        title = QLabel(TEXT["queue_control"])
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)
        self.auto_retry = WideHitCheckBox(TEXT["auto_retry"])
        self.auto_retry.setObjectName("ActiveAutoRetryCheck")
        self.auto_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_retry.setMinimumHeight(34)
        self.auto_retry.setChecked(True)
        self.auto_retry.stateChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.auto_retry)
        settings_row.addWidget(QLabel(TEXT["max_retry"]))
        self.retry_combo = QComboBox()
        self.retry_combo.addItem("1次", 1)
        self.retry_combo.addItem("2次", 2)
        self.retry_combo.addItem("3次", 3)
        self.retry_combo.addItem("5次", 5)
        self.retry_combo.setCurrentIndex(2)
        self.retry_combo.currentIndexChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.retry_combo)
        settings_row.addWidget(QLabel(TEXT["threads"]))
        self.thread_combo = QComboBox()
        for value in (2, 3, 5):
            self.thread_combo.addItem(str(value), value)
        self.thread_combo.setCurrentIndex(1)
        self.thread_combo.currentIndexChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.thread_combo)
        self.running_count_label = QLabel(TEXT["running_count"].format(count=0))
        settings_row.addStretch(1)
        settings_row.addWidget(self.running_count_label)
        layout.addLayout(settings_row)
        parent_layout.addWidget(panel)

    def _emit_options_changed(self) -> None:
        self.options_changed.emit(
            {
                "auto_retry": self.auto_retry.isChecked(),
                "max_retries": int(self.retry_combo.currentData() or 3),
                "max_concurrent": int(self.thread_combo.currentData() or 3),
            }
        )

    def _on_table_selection_changed(self, current, _previous) -> None:
        if not current.isValid():
            return
        item_id = self.table.model().item_id_at(current.row())
        if item_id and item_id != self._selected_detail_id:
            self._selected_detail_id = item_id
            self._render_selected_detail(force=True)

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("active_downloads") or [])
        self.running_count_label.setText(TEXT["running_count"].format(count=len(self.items)))
        selected_id = self.table.selected_id()
        table_changed = self.table.set_rows(self.items)
        if selected_id:
            self.table.select_id(selected_id)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
            self._selected_detail_id = self.table.selected_id()
        self._render_selected_detail(force=table_changed and self._detail_value_labels == {})

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "delete":
            self.delete_requested.emit(item_id)

    def _selected_item(self) -> dict[str, Any] | None:
        selected = self.table.selected_id()
        if not selected and self.items:
            selected = self.items[0].get("id")
        return next((item for item in self.items if item.get("id") == selected), None)

    def _render_selected_detail(self, *, force: bool = False) -> None:
        item = self._selected_item()
        signature = self._detail_signature_for(item)
        if not force and signature == self._detail_signature:
            return
        item_id = str((item or {}).get("id") or "")
        rebuild = force or item_id != self._selected_detail_id or not self._detail_value_labels
        self._detail_signature = signature
        self._selected_detail_id = item_id or None
        if not item:
            self.detail_title.setText(TEXT["current_download"])
            if rebuild:
                self._rebuild_detail_body([])
            self.events.set_events([])
            return
        self.detail_title.setText(TEXT["current_download"])
        pairs = self._detail_pairs(item)
        if rebuild:
            self._rebuild_detail_body(pairs)
        else:
            self._update_detail_labels(pairs, item)
        events = item.get("events", [])
        self.events.set_events(list(events))

    def _detail_pairs(self, item: dict[str, Any]) -> list[tuple[str, Any]]:
        chunk = item.get("chunk_progress") or {}
        percent = int(chunk.get("percent") or item.get("progress") or 0)
        completed = int(chunk.get("completed") or 0)
        total = int(chunk.get("total") or 0)
        chunk_label = f"{percent}% ({completed}/{total})" if total else f"{percent}%"
        return [
            (TEXT["title"], item.get("title", "")),
            (TEXT["platform"], item.get("platform", "")),
            (TEXT["save_dir"], item.get("save_dir", "")),
            (TEXT["output_filename"], item.get("output_filename", "")),
            (TEXT["chunk_progress"], chunk_label),
            (TEXT["thread_count"], item.get("thread_count", 0)),
            (TEXT["retry_count"], item.get("retry_count", 0)),
            (TEXT["write_status"], item.get("write_status", "")),
            (TEXT["merge_status"], item.get("merge_status", "")),
            (TEXT["source_url"], item.get("source_url", "")),
            (TEXT["trace_id"], item.get("trace_id", "")),
            (TEXT["trend_title"], {"values": item.get("speed_trend", []), "speed": item.get("speed", "0 B/s")}),
        ]

    def _rebuild_detail_body(self, pairs: list[tuple[str, Any]]) -> None:
        self.detail_card_layout.removeWidget(self.detail_body)
        self.detail_body.deleteLater()
        self._detail_value_labels = {}
        self._chunk_bar = None
        self._trend_widget = None
        self.detail_body = QWidget()
        body_layout = QVBoxLayout(self.detail_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        if not pairs:
            body_layout.addWidget(QLabel(TEXT["no_selection"]))
            self.detail_card_layout.insertWidget(1, self.detail_body)
            return
        for label, value in pairs:
            if label == TEXT["chunk_progress"]:
                self._add_chunk_row(body_layout, label, str(value))
            elif label == TEXT["trend_title"]:
                self._add_trend_row(body_layout, list((value or {}).get("values") or []), str((value or {}).get("speed") or "0 B/s"))
            else:
                self._add_value_row(body_layout, str(label), value)
        self.detail_card_layout.insertWidget(1, self.detail_body)

    def _add_value_row(self, body_layout: QVBoxLayout, label: str, value: Any) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QLabel(label)
        label_widget.setMinimumWidth(88)
        row_layout.addWidget(label_widget)
        if label in {TEXT["save_dir"], TEXT["output_filename"], TEXT["source_url"]}:
            value_label = SmartWrapLabel(value)
            value_label.setObjectName("LinkValueLabel" if label == TEXT["source_url"] else "SmartWrapLabel")
        else:
            value_label = QLabel(str(value))
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(value_label, 1)
        self._detail_value_labels[label] = value_label
        body_layout.addWidget(row)

    def _add_chunk_row(self, body_layout: QVBoxLayout, label: str, value: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QLabel(label)
        label_widget.setMinimumWidth(88)
        row_layout.addWidget(label_widget)
        self._chunk_bar = QProgressBar()
        self._chunk_bar.setRange(0, 100)
        self._chunk_bar.setValue(self._parse_percent(value))
        row_layout.addWidget(self._chunk_bar, 1)
        value_label = QLabel(value)
        value_label.setMinimumWidth(74)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(value_label)
        self._detail_value_labels[label] = value_label
        body_layout.addWidget(row)

    def _add_trend_row(self, body_layout: QVBoxLayout, values: list[int], speed_label: str) -> None:
        trend_title = QLabel(TEXT["trend_title"])
        trend_title.setObjectName("SectionTitle")
        body_layout.addWidget(trend_title)
        self._trend_widget = SpeedTrendWidget()
        self._trend_widget.set_values(values, speed_label)
        body_layout.addWidget(self._trend_widget)

    def _update_detail_labels(self, pairs: list[tuple[str, Any]], item: dict[str, Any]) -> None:
        for label, value in pairs:
            if label == TEXT["trend_title"]:
                if self._trend_widget is not None:
                    self._trend_widget.set_values(
                        list((value or {}).get("values") or []),
                        str((value or {}).get("speed") or "0 B/s"),
                    )
                continue
            widget = self._detail_value_labels.get(str(label))
            if widget is not None:
                widget.setText(str(value))
            if label == TEXT["chunk_progress"] and self._chunk_bar is not None:
                self._chunk_bar.setValue(self._parse_percent(str(value)))

    @staticmethod
    def _parse_percent(value: str) -> int:
        try:
            return max(0, min(100, int(value.split("%", 1)[0])))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _detail_signature_for(item: dict[str, Any] | None) -> tuple | None:
        if not item:
            return None
        chunk = item.get("chunk_progress") or {}
        return (
            item.get("id", ""),
            item.get("title", ""),
            item.get("platform", ""),
            item.get("save_dir", ""),
            item.get("output_filename", ""),
            chunk.get("percent", 0),
            chunk.get("completed", 0),
            chunk.get("total", 0),
            item.get("thread_count", 0),
            item.get("retry_count", 0),
            item.get("write_status", ""),
            item.get("merge_status", ""),
            item.get("source_url", ""),
            item.get("trace_id", ""),
            item.get("speed", ""),
            tuple(item.get("speed_trend", [])[-60:]),
            tuple((event.get("time", ""), event.get("message", "")) for event in item.get("events", [])),
        )

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        return self.table.select_id(item_id)
