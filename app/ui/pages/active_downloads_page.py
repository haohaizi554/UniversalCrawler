from __future__ import annotations

import re
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import download_concurrency_options, normalize_download_concurrency
from app.services.icon_registry import action_icon_file, platform_icon_file, ui_icon_path
from app.ui.components.combo_popup import ThemedComboBox
from app.ui.localization import is_translation_of, normalize_language, platform_display_name, source_text_for_translation, tr
from app.ui.components.smart_wrap_label import SmartWrapLabel
from app.ui.pages.common import PageFrame
from app.ui.styles.table_rows import (
    install_click_only_row_selection,
    install_stable_vertical_scrollbar,
    normalize_table_item_option,
    paint_item_interaction_background,
)
from app.ui.styles.themes import resolve_is_dark_theme, theme_colors
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
        self._language = "zh-CN"
        self._headers = list(self.HEADERS)

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self._headers[section], self._language)
        return super().headerData(section, orientation, role)

    def set_headers(self, headers: list[str]) -> None:
        if len(headers) != len(self._headers):
            return
        headers = self._source_headers_from_display(headers)
        if headers == self._headers:
            return
        self._headers = headers
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._headers) - 1)

    def _source_headers_from_display(self, headers: list[str]) -> list[str]:
        normalized: list[str] = []
        for index, header in enumerate(headers):
            text = str(header or "")
            current_source = self._headers[index] if index < len(self._headers) else ""
            if current_source and is_translation_of(text, current_source):
                normalized.append(current_source)
            else:
                normalized.append(source_text_for_translation(text))
        return normalized

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
            return tr(TEXT["delete"], self._language)
        if column == "platform":
            return platform_display_name(row.get("platform_id"), self._language, fallback=row.get(column, ""))
        return str(row.get(column, ""))

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        if self._headers:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._headers) - 1)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, max(0, self.columnCount() - 1)),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
            )

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        rows = list(rows)
        signatures = [self._row_signature(row) for row in rows]
        if signatures == self._row_signatures:
            return False
        new_ids = [signature[0] for signature in signatures]
        old_ids = [signature[0] for signature in self._row_signatures]
        same_shape = new_ids == old_ids
        if same_shape and len(rows) == len(self._rows):
            self._replace_existing_rows(rows, signatures)
        elif len(rows) > len(self._rows) and new_ids[: len(old_ids)] == old_ids:
            self._replace_existing_rows(rows[: len(self._rows)], signatures[: len(self._rows)])
            first = len(self._rows)
            last = len(rows) - 1
            self.beginInsertRows(QModelIndex(), first, last)
            self._rows.extend(rows[first:])
            self._row_signatures.extend(signatures[first:])
            self.endInsertRows()
            return True
        elif len(rows) < len(self._rows) and old_ids[: len(new_ids)] == new_ids:
            self._replace_existing_rows(rows, signatures)
            first = len(rows)
            last = len(self._rows) - 1
            self.beginRemoveRows(QModelIndex(), first, last)
            del self._rows[first:]
            del self._row_signatures[first:]
            self.endRemoveRows()
            return True
        else:
            self.beginResetModel()
            self._rows = rows
            self._row_signatures = signatures
            self.endResetModel()
        return True

    def _replace_existing_rows(self, rows: list[dict[str, Any]], signatures: list[tuple]) -> None:
        changed_roles = [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, self.ROW_ROLE]
        for row_index, (row, signature) in enumerate(zip(rows, signatures, strict=False)):
            if row_index >= len(self._rows):
                return
            old = self._row_signatures[row_index]
            self._rows[row_index] = row
            self._row_signatures[row_index] = signature
            if old == signature:
                continue
            start = self.index(row_index, 0)
            end = self.index(row_index, self.columnCount() - 1)
            self.dataChanged.emit(start, end, changed_roles)

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
        paint_item_interaction_background(painter, option)
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
        model = index.model()
        language = getattr(model, "_language", "zh-CN")
        platform = platform_display_name(platform_id, language, fallback=row.get("platform") or "")
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
        self.setMinimumHeight(240)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
    HEIGHT = 148

    def __init__(self) -> None:
        super().__init__()
        self._values: list[float] = []
        self._speed_label = "0 B/s"
        self._language = "zh-CN"
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.update()

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

    @staticmethod
    def _smooth_curve_path(points: list[tuple[int, int]]) -> QPainterPath:
        path = QPainterPath()
        if not points:
            return path
        path.moveTo(points[0][0], points[0][1])
        if len(points) == 1:
            return path

        tension = 1 / 6
        top = min(y for _, y in points)
        bottom = max(y for _, y in points)
        for index in range(len(points) - 1):
            p0 = points[index - 1] if index > 0 else points[index]
            p1 = points[index]
            p2 = points[index + 1]
            p3 = points[index + 2] if index + 2 < len(points) else p2

            c1x = p1[0] + (p2[0] - p0[0]) * tension
            c1y = p1[1] + (p2[1] - p0[1]) * tension
            c2x = p2[0] - (p3[0] - p1[0]) * tension
            c2y = p2[1] - (p3[1] - p1[1]) * tension
            path.cubicTo(
                c1x,
                max(top, min(bottom, c1y)),
                c2x,
                max(top, min(bottom, c2y)),
                p2[0],
                p2[1],
            )
        return path

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(resolve_is_dark_theme(self))
        rect = self.rect().adjusted(10, 26, -10, -30)
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
            painter.drawText(QRect(rect.left() + 3, y - 9, 40, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{value:.0f}")
        if self._values:
            points: list[tuple[int, int]] = []
            count = max(len(self._values) - 1, 1)
            for index, value in enumerate(self._values):
                x = rect.left() + int(rect.width() * index / count)
                y = rect.bottom() - int(rect.height() * value / max_value)
                points.append((x, y))
            line_pen = QPen(QColor(colors["accent"]), 2)
            line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(line_pen)
            painter.drawPath(self._smooth_curve_path(points))
            painter.setBrush(QColor(colors["accent"]))
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y in points[-10:]:
                painter.drawEllipse(x - 2, y - 2, 4, 4)
        muted = QColor(colors["muted"])
        painter.setPen(muted)
        metrics = painter.fontMetrics()
        speed_text = metrics.elidedText(self._speed_label, Qt.TextElideMode.ElideLeft, max(80, rect.width() // 2))
        painter.drawText(QRect(rect.left(), 4, rect.width(), 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, speed_text)
        label_top = self.height() - 27
        label_height = 22
        painter.drawText(QRect(rect.left(), label_top, 42, label_height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._time_label(60))
        painter.drawText(QRect(rect.left() + rect.width() // 4 - 12, label_top, 42, label_height), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self._time_label(45))
        painter.drawText(QRect(rect.left() + rect.width() // 2 - 12, label_top, 42, label_height), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self._time_label(30))
        painter.drawText(QRect(rect.left() + rect.width() * 3 // 4 - 12, label_top, 42, label_height), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self._time_label(15))
        painter.drawText(QRect(rect.right() - 42, label_top, 42, label_height), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._now_label())
        painter.end()

    def _time_label(self, seconds: int) -> str:
        if self._language == "en-US":
            return f"{seconds}s"
        return f"{seconds}秒"

    def _now_label(self) -> str:
        return tr("现在", self._language)


class EventTimelineWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self._language = "zh-CN"
        self.setMinimumHeight(214)
        self.setMaximumHeight(260)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.update()

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

    def _localized_message(self, message: object) -> str:
        text = str(message or "")
        language = self._language
        if language == "en-US":
            replacements = (
                (r"^\u4efb\u52a1\u8fdb\u5165\s*(.*?)\s*\u4e0b\u8f7d\u5668$", "Task entered {value} downloader"),
                (r"^\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668[:\uff1a]\s*(.*)$", "Task entered downloader: {value}"),
                (r"^\u8fdb\u5ea6[:\uff1a]\s*(.*)$", "Progress: {value}"),
                (
                    r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*?)\s*[\uff0c,]\s*\u5269\u4f59[:\uff1a]\s*(.*)$",
                    "Current speed: {value}, remaining: {extra}",
                ),
                (r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*)$", "Current speed: {value}"),
                (r"^\u5199\u5165\u72b6\u6001[:\uff1a]\s*(.*)$", "Write status: {value}"),
                (r"^\u5408\u5e76\u72b6\u6001[:\uff1a]\s*(.*)$", "Merge status: {value}"),
            )
            for pattern, template in replacements:
                match = re.match(pattern, text)
                if match:
                    value = platform_display_name("", language, fallback=match.group(1))
                    if len(match.groups()) > 1:
                        return template.format(value=value, extra=tr(match.group(2), language))
                    return template.format(value=value)
            exact = {
                "\u97f3\u89c6\u9891\u6d41\u4e0b\u8f7d\u4e2d": "Audio/video stream downloading",
                "\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55": "Source link recorded",
                "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6": "Waiting for downloader events",
            }
            return exact.get(text, tr(text, language))
        if language == "zh-TW":
            replacements = (
                (r"^\u4efb\u52a1\u8fdb\u5165\s*(.*?)\s*\u4e0b\u8f7d\u5668$", "\u4efb\u52d9\u9032\u5165 {value} \u4e0b\u8f09\u5668"),
                (r"^\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668[:\uff1a]\s*(.*)$", "\u4efb\u52d9\u9032\u5165\u4e0b\u8f09\u5668\uff1a{value}"),
                (r"^\u8fdb\u5ea6[:\uff1a]\s*(.*)$", "\u9032\u5ea6\uff1a{value}"),
                (
                    r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*?)\s*[\uff0c,]\s*\u5269\u4f59[:\uff1a]\s*(.*)$",
                    "\u76ee\u524d\u901f\u5ea6\uff1a{value}\uff0c\u5269\u9918\uff1a{extra}",
                ),
                (r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*)$", "\u76ee\u524d\u901f\u5ea6\uff1a{value}"),
                (r"^\u5199\u5165\u72b6\u6001[:\uff1a]\s*(.*)$", "\u5beb\u5165\u72c0\u614b\uff1a{value}"),
                (r"^\u5408\u5e76\u72b6\u6001[:\uff1a]\s*(.*)$", "\u5408\u4f75\u72c0\u614b\uff1a{value}"),
            )
            for pattern, template in replacements:
                match = re.match(pattern, text)
                if match:
                    value = platform_display_name("", language, fallback=match.group(1))
                    if len(match.groups()) > 1:
                        return template.format(value=value, extra=tr(match.group(2), language))
                    return template.format(value=value)
            exact = {
                "\u97f3\u89c6\u9891\u6d41\u4e0b\u8f7d\u4e2d": "\u97f3\u8996\u983b\u6d41\u4e0b\u8f09\u4e2d",
                "\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55": "\u4f86\u6e90\u9023\u7d50\u5df2\u8a18\u9304",
                "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6": "\u7b49\u5f85\u4e0b\u8f09\u5668\u56de\u5831\u8a73\u7d30\u4e8b\u4ef6",
            }
            return exact.get(text, tr(text, language))
        return tr(text, language)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(resolve_is_dark_theme(self))
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        if not self._events:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(self.rect().adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, tr("\u6682\u65e0\u4e8b\u4ef6", self._language))
            return
        x = 14
        top = 20
        metrics = painter.fontMetrics()
        line_height = max(24, metrics.height() + 6)
        row_h = line_height + 6
        time_width = 82
        message_x = x + 18 + time_width + 12
        line_color = QColor(colors["accent"])
        line_color.setAlpha(80)
        painter.setPen(QPen(line_color, 1))
        painter.drawLine(x, top + 4, x, top + row_h * (len(self._events) - 1) + 4)
        for index, event in enumerate(self._events):
            y = top + row_h * index
            text_top = y + 4 - line_height // 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["accent"]))
            painter.drawEllipse(x - 4, y, 8, 8)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRect(x + 18, text_top, time_width, line_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(event.get("time", "")))
            painter.setPen(QColor(colors["text"]))
            message_width = max(80, self.width() - message_x - 8)
            message = metrics.elidedText(self._localized_message(event.get("message", "")), Qt.TextElideMode.ElideRight, message_width)
            painter.drawText(QRect(message_x, text_top, message_width, line_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, message)
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

class ActiveDownloadsPage(PageFrame):
    delete_requested = pyqtSignal(str)
    options_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        self._language = "zh-CN"
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("ActivePageSplitter")
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left = QWidget()
        left.setObjectName("ActiveLeftColumn")
        left.setMinimumHeight(0)
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self.detail.setObjectName("ActiveRightColumn")
        self.detail.setMinimumWidth(360)
        self.detail.setMaximumWidth(500)
        self.detail.setMinimumHeight(0)
        self.detail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("ActiveDetailCard")
        self.detail_card.setMinimumHeight(0)
        self.detail_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_card_layout = QVBoxLayout(self.detail_card)
        self.detail_card_layout.setContentsMargins(12, 10, 12, 10)
        self.detail_card_layout.setSpacing(6)
        self.detail_title = QLabel(self._t(TEXT["current_download"]))
        self.detail_title.setObjectName("SectionTitle")
        self.detail_card_layout.addWidget(self.detail_title)

        self.detail_fields_scroll = QScrollArea()
        self.detail_fields_scroll.setObjectName("ActiveDetailFieldsScroll")
        self.detail_fields_scroll.setWidgetResizable(True)
        self.detail_fields_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_fields_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_fields_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.detail_fields_scroll.setMinimumHeight(0)
        self.detail_fields_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_body = QWidget()
        self.detail_body.setObjectName("ActiveDetailFieldsBody")
        self.detail_fields_scroll.setWidget(self.detail_body)
        self.detail_card_layout.addWidget(self.detail_fields_scroll, 1)

        self.detail_fixed = QWidget()
        self.detail_fixed.setObjectName("ActiveDetailFixedMetrics")
        self.detail_fixed_layout = QVBoxLayout(self.detail_fixed)
        self.detail_fixed_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_fixed_layout.setSpacing(8)
        self.detail_fixed.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.detail_card_layout.addWidget(self.detail_fixed, 0)
        self.detail_layout.addWidget(self.detail_card, 3)

        self.events_card = QFrame()
        self.events_card.setObjectName("ActiveEventsCard")
        self.events_card.setMinimumHeight(0)
        self.events_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.events_card_layout = QVBoxLayout(self.events_card)
        self.events_card_layout.setContentsMargins(12, 10, 12, 10)
        self.events_card_layout.setSpacing(6)
        self.detail_events_title = QLabel(self._t(TEXT["event_title"]))
        self.detail_events_title.setObjectName("SectionTitle")
        self.events_card_layout.addWidget(self.detail_events_title)
        self.events_scroll = QScrollArea()
        self.events_scroll.setObjectName("ActiveEventsScroll")
        self.events_scroll.setWidgetResizable(True)
        self.events_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.events_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.events_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.events_scroll.setMinimumHeight(0)
        self.events_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.events = EventTimelineWidget()
        self.events_scroll.setWidget(self.events)
        self.events_card_layout.addWidget(self.events_scroll, 1)
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
        self._syncing_download_options = False
        self._translation_dirty = True
        self._running_count_value: int | None = None
        self.table.selectionModel().currentChanged.connect(self._on_table_selection_changed)
        self.table.action_requested.connect(self._on_table_action)

    def consume_translation_dirty(self) -> bool:
        dirty = self._translation_dirty
        self._translation_dirty = False
        return dirty

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        changed = normalized != self._language
        self._language = normalized
        self.table.model().set_language(normalized)
        self.events.set_language(normalized)
        if self._trend_widget is not None:
            self._trend_widget.set_language(normalized)
        self.detail_title.setText(self._t(TEXT["current_download"]))
        self.detail_events_title.setText(self._t(TEXT["event_title"]))
        if hasattr(self, "queue_control_title"):
            self.queue_control_title.setText(self._t(TEXT["queue_control"]))
        if hasattr(self, "max_retry_label"):
            self.max_retry_label.setText(self._t(TEXT["max_retry"]))
        if hasattr(self, "threads_label"):
            self.threads_label.setText(self._t(TEXT["threads"]))
        self.auto_retry.setText(self._t(TEXT["auto_retry"]))
        self._sync_retry_combo_labels()
        self._sync_thread_combo_labels()
        self._update_running_count_label()
        if changed:
            self._detail_signature = None
            self._render_selected_detail(force=True)
        self._translation_dirty = False

    def _t(self, text: str) -> str:
        return tr(text, self._language)

    def _running_count_text(self, count: int) -> str:
        if self._language == "en-US":
            noun = "task" if int(count) == 1 else "tasks"
            return f"Running: {int(count)} {noun}"
        if self._language == "zh-TW":
            return f"目前執行：{int(count)} 個任務"
        return TEXT["running_count"].format(count=int(count))

    def _update_running_count_label(self) -> None:
        count = int(self._running_count_value or 0)
        self.running_count_label.setText(self._running_count_text(count))

    def _retry_count_label(self, value: int) -> str:
        if self._language == "en-US":
            return f"{int(value)}x"
        if self._language == "zh-TW":
            return f"{int(value)} 次"
        return f"{int(value)}次"

    def _sync_retry_combo_labels(self) -> None:
        blocked = self.retry_combo.blockSignals(True)
        try:
            for index in range(self.retry_combo.count()):
                value = int(self.retry_combo.itemData(index) or 0)
                if value:
                    self.retry_combo.setItemText(index, self._retry_count_label(value))
        finally:
            self.retry_combo.blockSignals(blocked)

    def _sync_thread_combo_labels(self) -> None:
        value_to_label: dict[int, str] = {}
        for option in download_concurrency_options():
            try:
                value = int(option["value"])
            except (TypeError, ValueError, KeyError):
                continue
            value_to_label[value] = self._t(str(option.get("label") or value))
        blocked = self.thread_combo.blockSignals(True)
        try:
            for index in range(self.thread_combo.count()):
                value = int(self.thread_combo.itemData(index) or 0)
                if value:
                    self.thread_combo.setItemText(index, value_to_label.get(value, str(value)))
        finally:
            self.thread_combo.blockSignals(blocked)

    def _build_queue_controls(self, parent_layout: QVBoxLayout) -> None:
        panel = QFrame()
        panel.setObjectName("QueueControlPanel")
        panel.setFixedHeight(96)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(7)
        self.queue_control_title = QLabel(self._t(TEXT["queue_control"]))
        self.queue_control_title.setObjectName("SectionTitle")
        layout.addWidget(self.queue_control_title)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)
        self.auto_retry = WideHitCheckBox(self._t(TEXT["auto_retry"]))
        self.auto_retry.setObjectName("ActiveAutoRetryCheck")
        self.auto_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_retry.setMinimumHeight(34)
        self.auto_retry.setChecked(True)
        self.auto_retry.stateChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.auto_retry)
        self.max_retry_label = QLabel(self._t(TEXT["max_retry"]))
        settings_row.addWidget(self.max_retry_label)
        self.retry_combo = ThemedComboBox(row_height=32)
        for value in range(1, 11):
            self.retry_combo.addItem(self._retry_count_label(value), value)
        self.retry_combo.setCurrentIndex(2)
        self.retry_combo.currentIndexChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.retry_combo)
        self.threads_label = QLabel(self._t(TEXT["threads"]))
        settings_row.addWidget(self.threads_label)
        self.thread_combo = ThemedComboBox(row_height=32)
        for option in download_concurrency_options():
            try:
                value = int(option["value"])
            except (TypeError, ValueError):
                continue
            self.thread_combo.addItem(self._t(str(option["label"])), value)
        self.thread_combo.setCurrentIndex(self.thread_combo.findData(3))
        self.thread_combo.currentIndexChanged.connect(self._emit_options_changed)
        settings_row.addWidget(self.thread_combo)
        self.running_count_label = QLabel(self._running_count_text(0))
        settings_row.addStretch(1)
        settings_row.addWidget(self.running_count_label)
        layout.addLayout(settings_row)
        parent_layout.addWidget(panel)

    def _emit_options_changed(self) -> None:
        if self._syncing_download_options:
            return
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
        self._sync_download_options(snapshot)
        self.items = list(snapshot.get("active_downloads") or [])
        running_count = len(self.items)
        if running_count != self._running_count_value:
            self._running_count_value = running_count
            self._update_running_count_label()
            self._translation_dirty = True
        selected_id = self.table.selected_id()
        table_changed = self.table.set_rows(self.items)
        if selected_id:
            self.table.select_id(selected_id)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
            self._selected_detail_id = self.table.selected_id()
        self._render_selected_detail(force=table_changed and self._detail_value_labels == {})

    def _sync_download_options(self, snapshot: dict) -> None:
        options: dict[str, Any] = {}
        if "download_options" in snapshot:
            options = dict(snapshot.get("download_options") or {})
        elif "settings_snapshot" in snapshot:
            settings = snapshot.get("settings_snapshot") or {}
            download_settings = settings.get("\u4e0b\u8f7d\u8bbe\u7f6e") or {}
            if download_settings:
                options = {
                    "auto_retry": self.auto_retry.isChecked(),
                    "max_retries": download_settings.get("max_retries", self.retry_combo.currentData() or 3),
                    "max_concurrent": download_settings.get("max_concurrent", self.thread_combo.currentData() or 3),
                }
        if not options:
            return
        self._syncing_download_options = True
        try:
            self.auto_retry.setChecked(bool(options.get("auto_retry", True)))
            self._set_combo_value(self.retry_combo, int(options.get("max_retries") or 3), suffix=self._retry_count_label(0).replace("0", ""))
            self._set_combo_value(
                self.thread_combo,
                normalize_download_concurrency(options.get("max_concurrent") or 3),
            )
        finally:
            self._syncing_download_options = False

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: int, *, suffix: str = "") -> None:
        index = combo.findData(value)
        if index < 0:
            combo.addItem(f"{value}{suffix}", value)
            values = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
            values.sort(key=lambda item: int(item[1] or 0))
            combo.clear()
            for text, data in values:
                combo.addItem(text, data)
            index = combo.findData(value)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)

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
            if rebuild:
                self._rebuild_detail_body([])
            self.events.set_events([])
            return
        pairs = self._detail_pairs(item)
        if rebuild:
            self._rebuild_detail_body(pairs)
        else:
            self._update_detail_labels(pairs, item)
        events = item.get("events", [])
        self.events.set_events(list(events))

    def _detail_pairs(self, item: dict[str, Any]) -> list[tuple[str, Any]]:
        detail_fields = self._active_detail_fields(item)
        if detail_fields:
            return [
                *detail_fields,
                (TEXT["chunk_progress"], self._active_chunk_label(item)),
                (TEXT["trend_title"], self._active_trend_payload(item)),
            ]
        return [
            (TEXT["title"], item.get("title", "")),
            (TEXT["platform"], item.get("platform", "")),
            (TEXT["save_dir"], item.get("save_dir", "")),
            (TEXT["output_filename"], item.get("output_filename", "")),
            (TEXT["chunk_progress"], self._active_chunk_label(item)),
            (TEXT["source_url"], item.get("source_url", "")),
            (TEXT["trace_id"], item.get("trace_id", "")),
            (TEXT["trend_title"], self._active_trend_payload(item)),
        ]

    @staticmethod
    def _active_detail_fields(item: dict[str, Any]) -> list[tuple[str, Any]]:
        fields: list[tuple[str, Any]] = []
        live_values = {
            TEXT["save_dir"]: item.get("save_dir"),
            TEXT["output_filename"]: item.get("output_filename"),
            TEXT["source_url"]: item.get("source_url"),
            TEXT["trace_id"]: item.get("trace_id"),
        }
        for field in list(item.get("detail_fields") or []):
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or "")
            if not label:
                continue
            value = field.get("value", "")
            live_value = live_values.get(label)
            if live_value is not None and str(live_value) != "":
                value = live_value
            fields.append((label, value))
        return fields

    @staticmethod
    def _active_chunk_label(item: dict[str, Any]) -> str:
        label = str(item.get("chunk_progress_label") or "")
        if label:
            return label
        chunk = item.get("chunk_progress") or {}
        percent = int(chunk.get("percent") or item.get("progress") or 0)
        completed = int(chunk.get("completed") or 0)
        total = int(chunk.get("total") or 0)
        return f"{percent}% ({completed}/{total})" if total else f"{percent}%"

    @staticmethod
    def _active_trend_payload(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "values": item.get("speed_trend", []),
            "speed": item.get("speed_trend_label") or item.get("speed", "0 B/s"),
        }

    def _rebuild_detail_body(self, pairs: list[tuple[str, Any]]) -> None:
        self._translation_dirty = True
        old_widget = self.detail_fields_scroll.takeWidget()
        if old_widget is not None:
            old_widget.deleteLater()
        while self.detail_fixed_layout.count():
            layout_item = self.detail_fixed_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.deleteLater()
        self._detail_value_labels = {}
        self._chunk_bar = None
        self._trend_widget = None
        self.detail_fields_host = QWidget()
        self.detail_fields_host.setObjectName("ActiveDetailFieldsHost")
        self.detail_fields_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        host_layout = QVBoxLayout(self.detail_fields_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.detail_body = QWidget()
        self.detail_body.setObjectName("ActiveDetailFieldsBody")
        self.detail_body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_layout = QGridLayout(self.detail_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setHorizontalSpacing(6)
        body_layout.setVerticalSpacing(2)
        body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        body_layout.setColumnMinimumWidth(0, 82)
        body_layout.setColumnStretch(0, 0)
        body_layout.setColumnStretch(1, 1)
        host_layout.addWidget(self.detail_body, 0, Qt.AlignmentFlag.AlignTop)
        host_layout.addStretch(1)
        self.detail_fields_scroll.setWidget(self.detail_fields_host)
        if not pairs:
            body_layout.addWidget(QLabel(self._t(TEXT["no_selection"])), 0, 0, 1, 2)
            self.detail_fixed.setVisible(False)
            return
        self.detail_fixed.setVisible(True)
        field_row = 0
        for label, value in pairs:
            if label == TEXT["chunk_progress"]:
                self._add_chunk_row(self.detail_fixed_layout, label, str(value))
            elif label == TEXT["trend_title"]:
                self._add_trend_row(
                    self.detail_fixed_layout,
                    list((value or {}).get("values") or []),
                    str((value or {}).get("speed") or "0 B/s"),
                )
            else:
                self._add_value_row(body_layout, field_row, str(label), value)
                field_row += 1

    def _add_value_row(self, body_layout: QGridLayout, row: int, label: str, value: Any) -> None:
        label_widget = QLabel(label)
        label_widget.setText(self._t(label))
        label_widget.setFixedWidth(82)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label_widget.setContentsMargins(0, 0, 0, 0)
        label_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if label in {TEXT["title"], TEXT["save_dir"], TEXT["output_filename"], TEXT["source_url"]}:
            value_label = SmartWrapLabel(value)
            value_label.setObjectName("LinkValueLabel" if label == TEXT["source_url"] else "SmartWrapLabel")
        else:
            value_label = QLabel(str(value))
            value_label.setWordWrap(True)
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setContentsMargins(0, 0, 0, 0)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_layout.addWidget(label_widget, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(value_label, row, 1)
        self._detail_value_labels[label] = value_label

    def _add_chunk_row(self, body_layout: QVBoxLayout, label: str, value: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QLabel(label)
        label_widget.setText(self._t(label))
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
        trend_title = QLabel(self._t(TEXT["trend_title"]))
        trend_title.setObjectName("SectionTitle")
        body_layout.addWidget(trend_title)
        self._trend_widget = SpeedTrendWidget()
        self._trend_widget.set_language(self._language)
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
                self._set_detail_widget_text(widget, str(value))
            if label == TEXT["chunk_progress"] and self._chunk_bar is not None:
                next_value = self._parse_percent(str(value))
                if self._chunk_bar.value() != next_value:
                    self._chunk_bar.setValue(next_value)

    @staticmethod
    def _set_detail_widget_text(widget: QLabel, value: str) -> None:
        raw_text = getattr(widget, "raw_text", None)
        if callable(raw_text):
            if raw_text() != value:
                widget.setText(value)
            return
        if widget.text() != value:
            widget.setText(value)

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
            item.get("source_url", ""),
            item.get("trace_id", ""),
            item.get("chunk_progress_label", ""),
            item.get("speed_trend_label", ""),
            tuple(
                (str(field.get("label") or ""), str(field.get("value") or ""))
                for field in list(item.get("detail_fields") or [])
                if isinstance(field, dict)
            ),
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
