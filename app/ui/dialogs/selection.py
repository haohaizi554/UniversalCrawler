"""采集扫描完成后显示任务选择对话框。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QModelIndex, Qt
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app.ui.components.theme_checkbox import ThemeCheckBox
from app.ui.dialogs.chromed_dialog import ChromedDialog
from shared.localization import normalize_language, tr
from app.ui.styles.table_rows import install_click_only_row_selection, install_stable_vertical_scrollbar

_ROW_HEIGHT = 34
_BUTTON_HORIZONTAL_PADDING = 56
_SELECTION_COLUMN_MIN_WIDTH = 72

class SelectionTableDelegate(QStyledItemDelegate):
    """绘制选择行时移除 Qt 原生当前单元格焦点框。"""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, clean_option, index)

def normalize_selection_items(items: list[Any] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or f"项目 {index + 1}"
        else:
            title = getattr(item, "title", None) or getattr(item, "name", None) or str(item)
        normalized.append({"title": str(title), "index": index})
    return normalized

def exec_selection_dialog(
    parent,
    items: list[Any] | None,
    *,
    title: str = "任务清单确认",
    language: str = "zh-CN",
) -> list[int] | None:
    """显示模态选择对话框并返回已选行索引。"""
    normalized = normalize_selection_items(items)
    if not normalized:
        return []

    dialog = SelectionDialog(parent, title=title, items=normalized, language=language)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.raise_()
    dialog.activateWindow()
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_indices
    return None

class SelectionDialog(ChromedDialog):
    """让用户选择哪些扫描结果进入下载队列。"""

    def __init__(self, parent, title="任务清单确认", items=None, *, language: str = "zh-CN"):
        self._language = normalize_language(language)
        super().__init__(
            parent,
            title=self._dialog_title(title),
            object_name="SelectionDialog",
            body_margins=(20, 20, 20, 20),
            body_spacing=15,
        )
        self.resize(800, 600)
        self.selected_indices: list[int] = []
        self.items = normalize_selection_items(items)
        self.init_ui()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def init_ui(self) -> None:
        layout = self.content_layout

        header = QLabel(self._header_text())
        header.setObjectName("SelectionDialogHeader")
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setObjectName("SelectionTable")
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([self._tr("选择"), self._tr("视频标题 / 描述")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, self._selection_column_width())
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setItemDelegate(SelectionTableDelegate(self.table))
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
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

        self.btn_all = QPushButton(self._tr("全选"))
        self.btn_invert = QPushButton(self._tr("反选"))
        self.btn_all.setObjectName("SelectionActionBtn")
        self.btn_invert.setObjectName("SelectionActionBtn")
        self.btn_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_invert.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fit_action_button(self.btn_all, min_width=96, height=34)
        self._fit_action_button(self.btn_invert, min_width=96, height=34)
        self.btn_all.setAutoDefault(False)
        self.btn_invert.setAutoDefault(False)
        self.btn_all.clicked.connect(self.select_all)
        self.btn_invert.clicked.connect(self.select_invert)
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(self._tr("取消任务"))
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fit_action_button(self.btn_cancel, min_width=128, height=40)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton(self._tr("开始下载"))
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fit_action_button(self.btn_confirm, min_width=148, height=40)
        self.btn_confirm.setDefault(True)
        self.btn_confirm.setAutoDefault(True)
        self.btn_confirm.clicked.connect(self.confirm_selection)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addWidget(btn_box)

        self._install_dialog_shortcuts()
        self.apply_chrome_theme(self._is_dark)
        self._fit_action_buttons()
        self._refresh_table_theme()

    def _selection_column_width(self) -> int:
        header_width = self.table.horizontalHeader().fontMetrics().horizontalAdvance(self._tr("选择")) + 30
        return max(_SELECTION_COLUMN_MIN_WIDTH, header_width)

    def _fit_action_buttons(self) -> None:
        for button, min_width, height in (
            (self.btn_all, 96, 34),
            (self.btn_invert, 96, 34),
            (self.btn_cancel, 128, 40),
            (self.btn_confirm, 148, 40),
        ):
            self._fit_action_button(button, min_width=min_width, height=height)

    def _fit_action_button(self, button: QPushButton, *, min_width: int, height: int) -> None:
        button.ensurePolished()
        text_width = button.fontMetrics().horizontalAdvance(button.text())
        width = max(min_width, button.sizeHint().width(), text_width + _BUTTON_HORIZONTAL_PADDING)
        button.setMinimumSize(width, height)
        button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def _tr(self, text: str) -> str:
        return tr(text, self._language)

    def _dialog_title(self, title: str) -> str:
        base_title = "任务清单确认"
        text = str(title or base_title)
        if text == base_title:
            return self._tr(base_title)
        if text.startswith(f"{base_title} - "):
            suffix = text[len(base_title) + 3 :]
            return f"{self._tr(base_title)} - {suffix}"
        return self._tr(text)

    def _header_text(self) -> str:
        count = len(self.items)
        if self._language == "en-US":
            noun = "resource" if count == 1 else "resources"
            return f"Scanned {count} {noun}; select the items to download:"
        if self._language == "zh-TW":
            return f"共掃描到 {count} 個資源，請勾選需要下載的項目："
        return f"共扫描到 {count} 个资源，请勾选需要下载的项目："

    def _install_dialog_shortcuts(self) -> None:
        self._dialog_shortcuts = []
        for sequence, slot in (
            ("Return", self.confirm_selection),
            ("Enter", self.confirm_selection),
            ("Esc", self.reject),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)
            self._dialog_shortcuts.append(shortcut)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        if watched in (self.table, self.table.viewport()) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.confirm_selection()
                event.accept()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm_selection()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

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
        """批量更新勾选状态，并阻止重入式信号风暴。"""
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
        checkbox = self._checkbox_at(row)
        if checkbox is not None:
            checkbox.setChecked(not checkbox.isChecked())
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())

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
