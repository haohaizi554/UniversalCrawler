from __future__ import annotations

from typing import Any, Iterable

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import action_icon_file, ui_icon_path
from app.ui.layout.island import IslandCard
from app.ui.styles.table_rows import (
    bind_qtablewidget_row_selection,
    install_click_only_row_selection,
    install_stable_vertical_scrollbar,
    normalize_table_item_option,
    paint_item_interaction_background,
    sync_qtablewidget_row_highlights,
)
from app.utils.qt_runtime import load_qt_icon
from app.ui.viewmodels.snapshot_table_model import SUBTITLE_ROLE, SnapshotTableModel

COLUMN_WIDTHS = {
    "time": 142,
    "level": 76,
    "source": 110,
    "trace_id": 148,
    "platform": 96,
    "status": 112,
    "progress": 118,
    "speed": 92,
    "remaining_time": 100,
    "completed_at": 120,
    "completed_at_table": 168,
    "failed_at": 132,
    "failed_at_table": 112,
    "duration": 124,
    "resolution": 84,
    "size": 72,
    "format": 60,
    "reason": 160,
    "reason_label": 150,
    "status_label": 82,
}

class PageFrame(QFrame):
    """Base page frame; flat by default to avoid nested panel boxes."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        use_panel: bool = False,
        use_island: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("PageFrame")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        if use_island:
            island = IslandCard(object_name="PageIsland")
            outer.addWidget(island, stretch=1)
            self.root_layout = island.content_layout
        else:
            self.root_layout = outer
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(10)
        if title:
            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(10)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("PageTitle")
            header_layout.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = QLabel(subtitle)
                self.subtitle_label.setObjectName("MutedLabel")
                header_layout.addWidget(self.subtitle_label)
            header_layout.addStretch(1)
            self.root_layout.addWidget(header)

class ActionTable(QTableWidget):
    """Small table wrapper that keeps IDs on the first column item."""

    def __init__(self, headers: Iterable[str]) -> None:
        super().__init__()
        headers = list(headers)
        self._headers = headers
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self._rows_signature = None
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(56)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFrameShape(QFrame.Shape.NoFrame)
        bind_qtablewidget_row_selection(self)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        install_stable_vertical_scrollbar(self)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.horizontalHeader()
        header.setMinimumSectionSize(72)
        header.setStretchLastSection(False)
        for index in range(len(headers)):
            mode = QHeaderView.ResizeMode.Stretch if index == 0 else QHeaderView.ResizeMode.Interactive
            header.setSectionResizeMode(index, mode)

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        actions: dict[str, str] | None = None,
        stretch_key: str | None = None,
    ) -> bool:
        actions = actions or {}
        signature = self._build_rows_signature(rows, columns, actions, stretch_key=stretch_key or columns[0])
        if signature == self._rows_signature:
            return False

        selected_id = self.selected_id()
        updates_enabled = self.updatesEnabled()
        signals_blocked = self.blockSignals(True)
        self.setUpdatesEnabled(False)
        try:
            self.setRowCount(0)
            for row_data in rows:
                row = self.rowCount()
                self.insertRow(row)
                for col, key in enumerate(columns):
                    if key == "progress":
                        progress = QProgressBar()
                        progress.setRange(0, 100)
                        progress.setValue(int(row_data.get(key) or 0))
                        self.setCellWidget(row, col, progress)
                        continue
                    value = row_data.get(key, "")
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, row_data.get("id", ""))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if col == 0 else Qt.AlignmentFlag.AlignCenter))
                    self.setItem(row, col, item)
                if actions:
                    self.setCellWidget(row, len(columns), build_action_widget(row_data.get("id", ""), actions))
            self._apply_column_widths(columns, actions, stretch_key=stretch_key or columns[0])
            if selected_id:
                row = self.row_for_id(selected_id)
                if row >= 0:
                    self.selectRow(row)
            self._rows_signature = signature
            sync_qtablewidget_row_highlights(self)
        finally:
            self.blockSignals(signals_blocked)
            self.setUpdatesEnabled(updates_enabled)
        return True

    @staticmethod
    def _build_rows_signature(
        rows: list[dict[str, Any]],
        columns: list[str],
        actions: dict[str, str],
        *,
        stretch_key: str,
    ) -> tuple:
        return (
            tuple(columns),
            tuple(actions.items()),
            stretch_key,
            tuple(
                (
                    row_data.get("id", ""),
                    tuple(str(row_data.get(key, "")) for key in columns),
                )
                for row_data in rows
            ),
        )

    def _apply_column_widths(self, columns: list[str], actions: dict[str, str], *, stretch_key: str) -> None:
        header = self.horizontalHeader()
        if self.columnCount() == 0:
            return
        stretch_index = columns.index(stretch_key) if stretch_key in columns else 0
        for index, key in enumerate(columns):
            if index == stretch_index:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
                continue
            width = COLUMN_WIDTHS.get(key)
            if width:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                self.setColumnWidth(index, width)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
        if actions:
            action_col = len(columns)
            action_width = max(68, min(156, 36 * len(actions) + 12))
            header.setSectionResizeMode(action_col, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(action_col, action_width)

    def selected_id(self) -> str | None:
        row = self.currentRow()
        if row < 0:
            return None
        item = self.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def row_for_id(self, item_id: str) -> int:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == item_id:
                return row
        return -1

    def id_order(self) -> list[str]:
        ids: list[str] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    ids.append(value)
        return ids

class ActionButton(QPushButton):
    clicked_with_id = pyqtSignal(str)

    def __init__(self, action_id: str, text: str, item_id: str) -> None:
        super().__init__()
        self.item_id = item_id
        self.setObjectName("TableActionButton")
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setFixedSize(32, 28)
        icon_name = action_icon_file(action_id)
        icon = load_qt_icon([ui_icon_path(icon_name)])
        if icon is not None:
            self.setIcon(icon)
            self.setIconSize(QSize(16, 16))
        else:
            self.setText(text)
            self.setMinimumWidth(56)
        self.clicked.connect(lambda: self.clicked_with_id.emit(self.item_id))

def build_action_widget(item_id: str, actions: dict[str, str]) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    for action_id, label in actions.items():
        button = ActionButton(action_id, label, item_id)
        button.setProperty("action_id", action_id)
        layout.addWidget(button)
    return widget

def connect_table_actions(table: ActionTable, handlers: dict[str, Any]) -> None:
    for row in range(table.rowCount()):
        widget = table.cellWidget(row, table.columnCount() - 1)
        if widget is None or widget.layout() is None:
            continue
        for index in range(widget.layout().count()):
            button = widget.layout().itemAt(index).widget()
            if not isinstance(button, ActionButton):
                continue
            action_id = button.property("action_id")
            handler = handlers.get(action_id)
            if callable(handler):
                button.clicked_with_id.connect(handler)

class SnapshotActionDelegate(QStyledItemDelegate):
    def __init__(
        self,
        *,
        progress_columns: set[int],
        icon_columns: set[int],
        title_columns: set[int],
        action_column: int | None,
        action_ids: tuple[str, ...],
        cell_padding: tuple[int, int] = (8, 8),
        suppress_native_selection: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._progress_columns = progress_columns
        self._icon_columns = icon_columns
        self._title_columns = title_columns
        self._action_column = action_column
        self._action_ids = action_ids
        self._cell_padding = cell_padding
        self._suppress_native_selection = suppress_native_selection
        self._action_icon_cache: dict[str, QIcon] = {}
        self._missing_action_icons: set[str] = set()

    def paint(self, painter: QPainter, option, index) -> None:
        paint_item_interaction_background(painter, option)
        if self._is_failed_status_cell(index):
            self._paint_failed_status(painter, option, index)
            return
        if index.column() in self._progress_columns:
            value = int(index.data(Qt.ItemDataRole.DisplayRole) or 0)
            progress_option = QStyleOptionProgressBar()
            progress_option.rect = option.rect.adjusted(8, 10, -8, -10)
            progress_option.minimum = 0
            progress_option.maximum = 100
            progress_option.progress = max(0, min(100, value))
            progress_option.text = f"{progress_option.progress}%"
            progress_option.textVisible = True
            QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, progress_option, painter)
            return
        if self._action_column is not None and index.column() == self._action_column:
            self._paint_action_icons(painter, option)
            return
        if index.column() in self._title_columns:
            self._paint_title_cell(painter, option, index)
            return
        if index.column() in self._icon_columns:
            self._paint_icon_text(painter, option, index)
            return
        padded = QStyleOptionViewItem(option)
        normalize_table_item_option(padded)
        if self._suppress_native_selection:
            padded.state &= ~QStyle.StateFlag.State_Selected
            padded.state &= ~QStyle.StateFlag.State_HasFocus
        left, right = self._cell_padding
        padded.rect = padded.rect.adjusted(left, 0, -right, 0)
        super().paint(painter, padded, index)

    def _paint_title_cell(self, painter: QPainter, option, index) -> None:
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        subtitle = str(index.data(SUBTITLE_ROLE) or "")
        painter.save()
        rect = option.rect.adjusted(10, 4, -8, -4)
        title_rect = QRect(rect.x(), rect.y(), rect.width(), rect.height() // 2 + 4)
        subtitle_rect = QRect(rect.x(), title_rect.bottom(), rect.width(), rect.height() - title_rect.height())
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)
        if subtitle:
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(subtitle_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), subtitle)
        painter.restore()

    def _paint_action_icons(self, painter: QPainter, option) -> None:
        if not self._action_ids:
            return
        painter.save()
        icon_size = 18
        gap = 8
        total_width = icon_size * len(self._action_ids) + gap * max(0, len(self._action_ids) - 1)
        x = option.rect.x() + max(6, (option.rect.width() - total_width) // 2)
        y = option.rect.y() + max(0, (option.rect.height() - icon_size) // 2)
        for index, action_id in enumerate(self._action_ids):
            icon = self._action_icon(action_id)
            if icon is not None:
                icon.paint(painter, QRect(x + index * (icon_size + gap), y, icon_size, icon_size))
        painter.restore()

    def _action_icon(self, action_id: str) -> QIcon | None:
        normalized = str(action_id or "")
        if not normalized or normalized in self._missing_action_icons:
            return None
        cached = self._action_icon_cache.get(normalized)
        if cached is not None:
            return cached
        icon = load_qt_icon([ui_icon_path(action_icon_file(normalized))])
        if icon is None:
            self._missing_action_icons.add(normalized)
            return None
        self._action_icon_cache[normalized] = icon
        return icon

    def _paint_icon_text(self, painter: QPainter, option, index) -> None:
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.save()
        rect = option.rect.adjusted(8, 0, -8, 0)
        icon_size = 16
        gap = 6
        has_icon = isinstance(icon, QIcon) and not icon.isNull()
        center_content = self._is_failed_reason_cell(index)
        available_text_width = max(0, rect.width() - (icon_size + gap if has_icon else 0))
        display_text = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, available_text_width)
        text_width = min(available_text_width, option.fontMetrics.horizontalAdvance(display_text))
        content_width = (icon_size + gap if has_icon else 0) + text_width
        x = rect.x() + max(0, (rect.width() - content_width) // 2) if center_content else rect.x()
        if isinstance(icon, QIcon) and not icon.isNull():
            icon_rect = QRect(x, rect.y() + max(0, (rect.height() - icon_size) // 2), icon_size, icon_size)
            icon.paint(painter, icon_rect)
            text_rect = QRect(icon_rect.right() + gap, rect.y(), max(text_width + 2, available_text_width if not center_content else text_width + 2), rect.height())
        else:
            text_rect = QRect(x, rect.y(), max(text_width + 2, rect.width() if not center_content else text_width + 2), rect.height())
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), display_text)
        painter.restore()

    def _is_failed_reason_cell(self, index) -> bool:
        parent = self.parent()
        if not parent or getattr(parent, "objectName", lambda: "")() != "FailedItemsTable":
            return False
        return self._column_key(index) == "reason_label"

    def _is_failed_status_cell(self, index) -> bool:
        parent = self.parent()
        if not parent or getattr(parent, "objectName", lambda: "")() != "FailedItemsTable":
            return False
        return self._column_key(index) == "status_label"

    @staticmethod
    def _column_key(index) -> str:
        columns = getattr(index.model(), "_columns", ())
        if 0 <= index.column() < len(columns):
            return str(columns[index.column()])
        return ""

    def _paint_failed_status(self, painter: QPainter, option, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "失败")
        painter.save()
        rect = option.rect.adjusted(8, 0, -8, 0)
        icon_size = 15
        gap = 7
        content_width = icon_size + gap + min(28, max(0, option.fontMetrics.horizontalAdvance(text)))
        x = rect.x() + max(0, (rect.width() - content_width) // 2)
        y = rect.y() + max(0, (rect.height() - icon_size) // 2)
        circle_rect = QRect(x, y, icon_size, icon_size)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor("#ef4444"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle_rect)

        painter.setPen(QPen(QColor("#ffffff"), 1.7))
        pad = 4
        painter.drawLine(circle_rect.left() + pad, circle_rect.top() + pad, circle_rect.right() - pad, circle_rect.bottom() - pad)
        painter.drawLine(circle_rect.right() - pad, circle_rect.top() + pad, circle_rect.left() + pad, circle_rect.bottom() - pad)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        text_rect = QRect(circle_rect.right() + gap, rect.y(), rect.right() - circle_rect.right() - gap, rect.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()

class SnapshotActionTable(QTableView):
    action_requested = pyqtSignal(str, str)

    def __init__(
        self,
        *,
        headers: list[str],
        columns: list[str],
        actions: dict[str, str] | None = None,
        stretch_key: str | None = None,
        icon_columns: set[str] | None = None,
        title_columns: set[str] | None = None,
        row_height: int = 56,
        cell_padding: tuple[int, int] = (8, 8),
        column_widths: dict[str, int] | None = None,
        suppress_native_selection: bool = False,
    ) -> None:
        super().__init__()
        self._data_columns = list(columns)
        self._actions = actions or {}
        self._icon_columns = set(icon_columns or ())
        self._title_columns = set(title_columns or ())
        self._column_widths = dict(column_widths or {})
        model_headers = list(headers)
        model_columns = list(columns)
        self._action_column = None
        if self._actions:
            self._action_column = len(model_columns)
            model_columns.append("__actions__")
        self.table_model = SnapshotTableModel(
            headers=model_headers,
            columns=model_columns,
            icon_columns=self._icon_columns,
            parent=self,
        )
        self.setModel(self.table_model)
        progress_columns = {index for index, key in enumerate(model_columns) if key == "progress"}
        icon_column_indexes = {
            index for index, key in enumerate(model_columns) if key in self._icon_columns
        }
        title_column_indexes = {
            index for index, key in enumerate(model_columns) if key in self._title_columns
        }
        self.setItemDelegate(
            SnapshotActionDelegate(
                progress_columns=progress_columns,
                icon_columns=icon_column_indexes,
                title_columns=title_column_indexes,
                action_column=self._action_column,
                action_ids=tuple(self._actions),
                cell_padding=cell_padding,
                suppress_native_selection=suppress_native_selection,
                parent=self,
            )
        )
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(12)
        install_stable_vertical_scrollbar(self)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        install_click_only_row_selection(self)
        self._apply_column_widths(model_columns, stretch_key=stretch_key or columns[0])

    def _apply_column_widths(self, columns: list[str], *, stretch_key: str) -> None:
        header = self.horizontalHeader()
        header.setMinimumSectionSize(72)
        header.setStretchLastSection(False)
        stretch_index = columns.index(stretch_key) if stretch_key in columns else 0
        for index, key in enumerate(columns):
            if index == stretch_index:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
                continue
            if key == "__actions__":
                width = max(44, 28 * max(1, len(self._actions)) + 16)
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                self.setColumnWidth(index, width)
                continue
            width = self._column_widths.get(key, COLUMN_WIDTHS.get(key))
            if width:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                self.setColumnWidth(index, width)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)

    def mouseReleaseEvent(self, event) -> None:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(position)
        if (
            self._action_column is not None
            and index.isValid()
            and index.column() == self._action_column
            and event.button() == Qt.MouseButton.LeftButton
        ):
            item_id = self.table_model.row_at(index.row()).get("id", "") if self.table_model.row_at(index.row()) else ""
            action_ids = list(self._actions)
            if item_id and action_ids:
                rect = self.visualRect(index)
                action_index = min(len(action_ids) - 1, max(0, int((position.x() - rect.x()) / max(1, rect.width()) * len(action_ids))))
                self.action_requested.emit(action_ids[action_index], item_id)
            return
        super().mouseReleaseEvent(event)

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        return self.table_model.set_rows(rows)

    def force_refresh(self) -> None:
        self.table_model.force_reset()

    def selected_id(self) -> str | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        item = self.table_model.row_at(indexes[0].row())
        return str((item or {}).get("id") or "") or None

    def row_for_id(self, item_id: str) -> int:
        return self.table_model.row_for_id(item_id)

    def id_order(self) -> list[str]:
        return self.table_model.id_order()

    def row_at(self, row: int) -> dict[str, Any] | None:
        return self.table_model.row_at(row)

    def select_id(self, item_id: str) -> bool:
        row = self.row_for_id(item_id)
        if row < 0:
            return False
        self.selectRow(row)
        return True

def key_value_panel(pairs: Iterable[tuple[str, Any]]) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for label, value in pairs:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        label_widget = QLabel(str(label))
        label_widget.setMinimumWidth(86)
        row_layout.addWidget(label_widget)
        value_label = QLabel(str(value))
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(value_label, 1)
        layout.addWidget(row)
    layout.addStretch(1)
    return widget
