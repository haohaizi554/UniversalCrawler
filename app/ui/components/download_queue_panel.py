"""界面模块，封装 `app/ui/components/download_queue_panel.py` 对应的窗口、对话框或界面组件逻辑。"""

from __future__ import annotations

import re
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from app.models import VideoItem
from app.ui.styles.table_rows import bind_qtablewidget_row_selection

class DownloadQueuePanel(QFrame):
    """下载队列表面板，封装表格的增删改查和交互绑定。"""

    _DIGIT_RE = re.compile(r"(\d+)")

    def __init__(self, current_save_dir: str, style_provider: QWidget):
        """初始化当前实例并准备运行所需的状态，供 `DownloadQueuePanel` 使用。"""
        super().__init__()
        self.setObjectName("ContentPanel")
        self._style_provider = style_provider
        self._on_play: Callable[[str], None] | None = None
        self._on_delete: Callable[[str], None] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_bar = QFrame()
        header_bar.setObjectName("HeaderBar")
        header_bar.setFixedHeight(35)
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(QLabel("📋 下载队列"))
        header_layout.addWidget(QLabel(" | 保存至: ", styleSheet="color: #888;"))

        self.lbl_full_path = QLabel(current_save_dir)
        self.lbl_full_path.setObjectName("PathLabel")
        self.lbl_full_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self.lbl_full_path)
        layout.addWidget(header_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["视频标题", "状态", "进度", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        bind_qtablewidget_row_selection(self.table)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

    def set_current_save_dir(self, save_dir: str) -> None:
        """设置 `current_save_dir` 对应的值或运行状态，供 `DownloadQueuePanel` 使用。"""
        self.lbl_full_path.setText(save_dir)
        self.lbl_full_path.setToolTip(save_dir)

    def add_video_row(
        self,
        video_item: VideoItem,
        on_play: Callable[[str], None],
        on_delete: Callable[[str], None],
    ) -> None:
        
        self._on_play = on_play
        self._on_delete = on_delete
        row = self._find_insert_row(video_item.title, video_item.id)
        self.table.insertRow(row)
        self._populate_row(row, video_item)

    @classmethod
    def build_sort_key(cls, title: str, video_id: str = "") -> tuple:
        """Natural sort key for visible media rows."""
        tokens: list[tuple[int, object]] = []
        for part in cls._DIGIT_RE.split((title or "").strip()):
            if not part:
                continue
            if part.isdigit():
                tokens.append((0, int(part)))
            else:
                tokens.append((1, part.casefold()))
        return (*tokens, (2, video_id))

    def reorder_video_row(self, video_item: VideoItem) -> int:
        """Move an existing row to the position implied by the title sort key."""
        current_row = self.find_row_by_video_id(video_item.id)
        if current_row == -1:
            return -1
        was_selected = self.get_selected_video_id() == video_item.id
        self.table.removeRow(current_row)
        insert_row = self._find_insert_row(video_item.title, video_item.id)
        self.table.insertRow(insert_row)
        self._populate_row(insert_row, video_item)
        if was_selected:
            self.select_video_by_id(video_item.id)
        return insert_row

    def _populate_row(self, row: int, video_item: VideoItem) -> None:
        """Populate a row after insert or reorder."""
        if self._on_play is None or self._on_delete is None:
            raise RuntimeError("video row callbacks must be configured before populating rows")

        title_item = QTableWidgetItem(video_item.title)
        title_item.setData(Qt.ItemDataRole.UserRole, video_item.id)
        title_item.setToolTip(video_item.title)
        self.table.setItem(row, 0, title_item)

        status_item = QTableWidgetItem(video_item.status)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, status_item)

        progress_bar = QProgressBar()
        progress_bar.setValue(video_item.progress)
        self.table.setCellWidget(row, 2, progress_bar)

        operation_widget = QWidget()
        operation_layout = QHBoxLayout(operation_widget)
        operation_layout.setContentsMargins(5, 2, 5, 2)
        operation_layout.setSpacing(8)
        operation_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        play_btn = QPushButton()
        play_btn.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        play_btn.setFixedSize(28, 26)
        play_btn.clicked.connect(lambda: self._on_play(video_item.id))

        delete_btn = QPushButton()
        delete_btn.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        delete_btn.setFixedSize(28, 26)
        delete_btn.clicked.connect(
            lambda checked=False, video_id=video_item.id: self._on_delete(video_id)
        )

        operation_layout.addWidget(play_btn)
        operation_layout.addWidget(delete_btn)
        self.table.setCellWidget(row, 3, operation_widget)

    def _find_insert_row(self, title: str, video_id: str) -> int:
        target_key = self.build_sort_key(title, video_id)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            current_key = self.build_sort_key(item.text(), item.data(Qt.ItemDataRole.UserRole) or "")
            if target_key < current_key:
                return row
        return self.table.rowCount()

    def update_video_status(self, video_id: str, status: str, progress: int | None = None) -> None:
        """更新 `video_status` 对应的状态或数据内容，供 `DownloadQueuePanel` 使用。"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == video_id:
                status_item = self.table.item(row, 1)
                if status_item is not None:
                    status_item.setText(status)
                if progress is not None:
                    progress_bar = self.table.cellWidget(row, 2)
                    if progress_bar is not None:
                        progress_bar.setValue(progress)
                break

    def refresh_delete_bindings(self, on_delete: Callable[[str], None]) -> None:
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            video_id = item.data(Qt.ItemDataRole.UserRole)
            widget = self.table.cellWidget(row, 3)
            if not widget:
                continue
            layout = widget.layout()
            button = layout.itemAt(1).widget() if layout and layout.count() > 1 else None
            if isinstance(button, QPushButton):
                try:
                    # 删除一行后表格可能重排，这里统一重绑，避免旧 lambda 还指向错误的视频 ID。
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                button.clicked.connect(lambda checked=False, value=video_id: on_delete(value))

    def clear_rows(self) -> None:
        
        self.table.setRowCount(0)

    def remove_row(self, row: int) -> None:
        
        if row >= 0:
            self.table.removeRow(row)

    def bind_title_rename(self, on_rename: Callable) -> None:
        
        self.table.itemChanged.connect(on_rename)

    def find_row_by_video_id(self, video_id: str) -> int:
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == video_id:
                return row
        return -1

    def get_selected_video_id(self) -> str | None:
        
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def get_adjacent_video_id(self, current_video_id: str | None, direction: int, *, wrap: bool = True) -> str | None:
        """Return the previous/next video id according to current table order."""
        video_order = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                video_id = item.data(Qt.ItemDataRole.UserRole)
                if video_id:
                    video_order.append(video_id)
        if not video_order:
            return None
        current_index = video_order.index(current_video_id) if current_video_id in video_order else -1
        if current_index == -1:
            return video_order[0] if direction >= 0 else video_order[-1]
        next_index = current_index + (1 if direction >= 0 else -1)
        if wrap:
            next_index %= len(video_order)
        elif next_index < 0 or next_index >= len(video_order):
            return None
        return video_order[next_index]

    def select_video_by_id(self, video_id: str) -> bool:
        """Select the row for a media id and scroll it into view."""
        row = self.find_row_by_video_id(video_id)
        if row == -1:
            return False
        self.table.setCurrentCell(row, 0)
        self.table.selectRow(row)
        item = self.table.item(row, 0)
        if item is not None:
            self.table.scrollToItem(item)
        return True
