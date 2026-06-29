"""Task selection dialog shown after spider scanning completes."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.theme_checkbox import ThemeCheckBox
from app.ui.dialogs.dialog_styles import apply_themed_dialog_styles
from app.ui.styles import apply_dialog_theme, theme_colors
from app.ui.styles.table_rows import install_click_only_row_selection, install_stable_vertical_scrollbar

_ROW_HEIGHT = 34

def normalize_selection_items(items: list[Any] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or f"项目 {index + 1}"
        else:
            title = getattr(item, "title", None) or getattr(item, "name", None) or str(item)
        normalized.append({"title": str(title), "index": index})
    return normalized

def exec_selection_dialog(parent, items: list[Any] | None, *, title: str = "任务清单确认") -> list[int] | None:
    """Show the modal selection dialog and return chosen row indexes."""
    normalized = normalize_selection_items(items)
    if not normalized:
        return []

    dialog = SelectionDialog(parent, title=title, items=normalized)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_indices
    return None

class SelectionDialog(QDialog):
    """Lets the user choose which scanned items should enter the queue."""

    def __init__(self, parent, title="任务清单确认", items=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("SelectionDialog")
        self.setModal(True)
        self.resize(800, 600)
        self.selected_indices: list[int] = []
        self.items = normalize_selection_items(items)
        self._is_dark = apply_dialog_theme(self, parent=parent)
        self._colors = theme_colors(self._is_dark)
        apply_themed_dialog_styles(self, self._colors)
        self.init_ui()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QLabel(
            f"共扫描到 {len(self.items)} 个资源，请勾选需要下载的项目："
        )
        header.setObjectName("SelectionDialogHeader")
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setObjectName("SelectionTable")
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["选择", "视频标题 / 描述"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 48)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.cellClicked.connect(self._on_cell_clicked)
        install_click_only_row_selection(self.table)
        install_stable_vertical_scrollbar(self.table)
        self.table.selectionModel().selectionChanged.connect(self._on_row_selection_changed)
        self.populate_table()
        self._refresh_table_theme()
        layout.addWidget(self.table)

        btn_box = QFrame()
        btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_all = QPushButton("全选")
        self.btn_invert = QPushButton("反选")
        self.btn_all.setObjectName("SelectionActionBtn")
        self.btn_invert.setObjectName("SelectionActionBtn")
        self.btn_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_invert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_all.setFixedSize(80, 30)
        self.btn_invert.setFixedSize(80, 30)
        self.btn_all.clicked.connect(self.select_all)
        self.btn_invert.clicked.connect(self.select_invert)
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消任务")
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setFixedSize(100, 35)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("开始下载")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setFixedSize(120, 35)
        self.btn_confirm.clicked.connect(self.confirm_selection)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addWidget(btn_box)

        apply_dialog_theme(self, is_dark=self._is_dark)
        apply_themed_dialog_styles(self, self._colors)
        self._refresh_table_theme()

    def _refresh_table_theme(self) -> None:
        palette = self.table.palette()
        palette.setColor(self.table.backgroundRole(), QColor(self._colors["panel"]))
        self.table.setPalette(palette)
        self.table.setAutoFillBackground(True)
        self.table.viewport().setPalette(palette)
        self.table.viewport().setAutoFillBackground(True)
        header = self.table.horizontalHeader()
        if header is not None:
            header.setPalette(palette)
            header.viewport().setPalette(palette)
            header.viewport().setAutoFillBackground(True)

    def populate_table(self) -> None:
        self.table.setRowCount(len(self.items))
        for index, item_data in enumerate(self.items):
            row_widget = QWidget()
            row_widget.setAutoFillBackground(True)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox = ThemeCheckBox(checked=True, colors=self._colors, interactive=False)
            checkbox.toggled.connect(lambda _checked, row=index: self._sync_row_style(row))
            row_layout.addWidget(checkbox)
            self.table.setCellWidget(index, 0, row_widget)

            title_item = QTableWidgetItem(str(item_data.get("title", "未知标题")))
            title_item.setFlags(title_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(index, 1, title_item)
            self._sync_row_style(index)

    def _checkbox_at(self, row: int) -> ThemeCheckBox | None:
        widget = self.table.cellWidget(row, 0)
        if widget is None:
            return None
        child = widget.findChild(ThemeCheckBox)
        return child if isinstance(child, ThemeCheckBox) else None

    def _row_colors(self, checked: bool, *, selected: bool) -> tuple[QColor, QColor]:
        if selected:
            return QColor(self._colors["row_selected"]), QColor(self._colors["text"])
        if checked:
            return QColor(self._colors["panel"]), QColor(self._colors["text"])
        return QColor(self._colors["panel_soft"]), QColor(self._colors["muted"])

    def _is_row_selected(self, row: int) -> bool:
        model = self.table.selectionModel()
        if model is None:
            return False
        return row in {index.row() for index in model.selectedRows()}

    def _sync_row_style(self, row: int) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        item = self.table.item(row, 1)
        checkbox = self._checkbox_at(row)
        if item is None or checkbox is None:
            return
        background, foreground = self._row_colors(
            checkbox.isChecked(),
            selected=self._is_row_selected(row),
        )
        item.setBackground(background)
        item.setForeground(foreground)

        cell_widget = self.table.cellWidget(row, 0)
        if cell_widget is not None:
            palette = cell_widget.palette()
            palette.setColor(cell_widget.backgroundRole(), background)
            cell_widget.setPalette(palette)
            cell_widget.setAutoFillBackground(True)

    def _apply_bulk_check(self, *, select_all: bool | None) -> None:
        """Bulk update check states without re-entrant signal storms."""
        self.table.setUpdatesEnabled(False)
        try:
            for index in range(self.table.rowCount()):
                checkbox = self._checkbox_at(index)
                if checkbox is None:
                    continue
                if select_all is None:
                    checkbox.setChecked(not checkbox.isChecked(), notify=False)
                else:
                    checkbox.setChecked(select_all, notify=False)
                self._sync_row_style(index)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()

    def _on_row_selection_changed(self, *_args) -> None:
        for row in range(self.table.rowCount()):
            self._sync_row_style(row)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        self.table.selectRow(row)
        checkbox = self._checkbox_at(row)
        if checkbox is not None:
            checkbox.setChecked(not checkbox.isChecked())

    def select_all(self) -> None:
        self._apply_bulk_check(select_all=True)

    def select_invert(self) -> None:
        self._apply_bulk_check(select_all=None)

    def confirm_selection(self) -> None:
        self.selected_indices = []
        for index in range(self.table.rowCount()):
            checkbox = self._checkbox_at(index)
            if checkbox is not None and checkbox.isChecked():
                self.selected_indices.append(index)
        self.accept()
