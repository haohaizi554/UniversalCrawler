from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.media_preview_panel import MediaPreviewPanel
from app.ui.pages.active_downloads_page import SmartWrapLabel
from app.ui.pages.common import PageFrame, SnapshotActionTable

class CompletedPage(PageFrame):
    play_requested = pyqtSignal(str)
    open_directory_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    metadata_detected = pyqtSignal(str, dict)

    PAGE_SIZE_OPTIONS = (20, 50, 100)

    def __init__(self, style_provider) -> None:
        super().__init__("", use_island=False)
        self._page = 1
        self._page_size = 20
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("CompletedPageSplitter")
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left = QWidget()
        left.setObjectName("CompletedLeftColumn")
        left.setMinimumHeight(0)
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table_card = QFrame()
        self.table_card.setObjectName("CompletedTableCard")
        table_card_layout = QVBoxLayout(self.table_card)
        table_card_layout.setContentsMargins(12, 10, 12, 12)
        table_card_layout.setSpacing(0)
        self.table = SnapshotActionTable(
            headers=["标题", "完成时间", "时长", "格式", "操作"],
            columns=["title", "completed_at_table", "duration", "format"],
            actions={"play": "播放", "open_directory": "打开目录", "delete": "删除"},
            cell_padding=(12, 10),
            suppress_native_selection=True,
        )
        self.table.setObjectName("CompletedItemsTable")
        table_card_layout.addWidget(self.table, 1)
        footer = QWidget()
        footer.setObjectName("CompletedPaginationFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 0)
        footer_layout.setSpacing(10)
        self.total_label = QLabel("共 0 项")
        self.total_label.setObjectName("MutedLabel")
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch(1)
        self.btn_prev = QPushButton("‹")
        self.btn_prev.setToolTip("上一页")
        self.btn_prev.setFixedSize(34, 30)
        self.btn_next = QPushButton("›")
        self.btn_next.setToolTip("下一页")
        self.btn_next.setFixedSize(34, 30)
        self.page_label = QLabel("1 / 1 页")
        self.page_label.setObjectName("MutedLabel")
        self.page_size_combo = QComboBox()
        self.page_size_combo.setFixedHeight(30)
        for option in self.PAGE_SIZE_OPTIONS:
            self.page_size_combo.addItem(f"{option} 条/页", option)
        footer_layout.addWidget(self.btn_prev)
        footer_layout.addWidget(self.page_label)
        footer_layout.addWidget(self.btn_next)
        footer_layout.addWidget(self.page_size_combo)
        table_card_layout.addWidget(footer)
        left_layout.addWidget(self.table_card, 1)
        splitter.addWidget(left)

        self.detail = QWidget()
        self.detail.setObjectName("CompletedRightColumn")
        self.detail.setMinimumWidth(360)
        self.detail.setMaximumWidth(500)
        self.detail.setMinimumHeight(0)
        self.detail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("CompletedPreviewCard")
        preview_layout = QVBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(0)
        self.media_panel = MediaPreviewPanel(style_provider)
        self.media_panel.setMinimumHeight(260)
        preview_layout.addWidget(self.media_panel, 1)
        self.detail_layout.addWidget(self.preview_card, 2)

        self.info_card = QFrame()
        self.info_card.setObjectName("CompletedInfoCard")
        self.info_card_layout = QVBoxLayout(self.info_card)
        self.info_card_layout.setContentsMargins(12, 10, 12, 12)
        self.info_card_layout.setSpacing(8)
        self.info_title = QLabel("文件信息")
        self.info_title.setObjectName("SectionTitle")
        self.info_card_layout.addWidget(self.info_title)
        self.info_body = QWidget()
        self.info_card_layout.addWidget(self.info_body, 1)
        self.detail_layout.addWidget(self.info_card, 1)
        splitter.addWidget(self.detail)
        splitter.setSizes([820, 420])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict] = []
        self._detail_signature: tuple | None = None
        self._cleanup_done = False
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_selected_detail())
        self.table.action_requested.connect(self._on_table_action)
        self.media_panel.sig_media_metadata_detected.connect(self._on_media_metadata_detected)
        self.btn_prev.clicked.connect(lambda: self._set_page(self._page - 1))
        self.btn_next.clicked.connect(lambda: self._set_page(self._page + 1))
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("completed_items") or [])
        selected_id = self.table.selected_id()
        if selected_id:
            self._page = self._page_for_item(selected_id) or self._page
        self._render_current_page(selected_id=selected_id)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _selected_item(self) -> dict | None:
        selected = self.table.selected_id()
        if not selected and self.items:
            selected = self.items[0].get("id")
        return next((item for item in self.items if item.get("id") == selected), None)

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "play":
            self.play_requested.emit(item_id)
        elif action == "open_directory":
            self.open_directory_requested.emit(item_id)
        elif action == "delete":
            self.delete_requested.emit(item_id)

    def _on_media_metadata_detected(self, media_path: str, metadata: dict) -> None:
        item = self._item_for_media_path(media_path) or self._selected_item()
        item_id = str((item or {}).get("id") or "")
        if item_id and metadata:
            self.metadata_detected.emit(item_id, dict(metadata))

    def _item_for_media_path(self, media_path: str) -> dict | None:
        normalized = self._normalize_path(media_path)
        if not normalized:
            return None
        for item in self.items:
            if self._normalize_path(str(item.get("local_path") or "")) == normalized:
                return item
        return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    def _render_selected_detail(self) -> None:
        item = self._selected_item()
        signature = self._detail_signature_for(item)
        if signature == self._detail_signature:
            return
        self._detail_signature = signature
        self.info_card_layout.removeWidget(self.info_body)
        self.info_body.deleteLater()
        if not item:
            self.info_body = QWidget()
            self.info_card_layout.insertWidget(1, self.info_body, 1)
            return
        self.info_body = self._file_info_panel(
            [
                ("文件名", self._filename_for(item)),
                ("保存路径", self._save_dir_for(item)),
                ("完成时间", item.get("completed_at", "")),
                ("时长", item.get("duration", "")),
                ("分辨率", item.get("resolution", "")),
                ("大小", item.get("size", "")),
                ("格式", item.get("format", "")),
            ]
        )
        self.info_card_layout.insertWidget(1, self.info_body, 1)

    def _file_info_panel(self, pairs: list[tuple[str, object]]) -> QWidget:
        panel = QWidget()
        panel.setObjectName("CompletedInfoBody")
        layout = QGridLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        layout.setColumnMinimumWidth(0, 86)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        for index, (key, value) in enumerate(pairs):
            key_label = QLabel(str(key), panel)
            key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            key_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

            if index in {0, 1}:
                value_label = SmartWrapLabel(value, panel, compact=True)
                value_label.setObjectName("CompletedInfoSmartWrapLabel")
            else:
                value_label = QLabel(str(value or ""), panel)
                value_label.setObjectName("CompletedInfoValueLabel")
                value_label.setWordWrap(True)
                value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                value_label.setMinimumWidth(0)

            layout.addWidget(key_label, index, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(value_label, index, 1, Qt.AlignmentFlag.AlignTop)
        layout.setRowStretch(len(pairs), 1)
        return panel

    @staticmethod
    def _filename_for(item: dict) -> str:
        value = str(item.get("filename") or "").strip()
        if value:
            return value
        local_path = str(item.get("local_path") or "").strip()
        return Path(local_path).name if local_path else str(item.get("title") or "")

    @staticmethod
    def _save_dir_for(item: dict) -> str:
        value = str(item.get("save_dir") or "").strip()
        if value:
            return value
        local_path = str(item.get("local_path") or "").strip()
        return str(Path(local_path).parent) if local_path else ""

    @staticmethod
    def _detail_signature_for(item: dict | None) -> tuple | None:
        if not item:
            return None
        return (
            item.get("id", ""),
            item.get("local_path", ""),
            item.get("completed_at", ""),
            item.get("duration", ""),
            item.get("resolution", ""),
            item.get("format", ""),
            item.get("size", ""),
            item.get("filename", ""),
            item.get("save_dir", ""),
        )

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def id_order(self) -> list[str]:
        return [str(item.get("id")) for item in self.items if item.get("id")]

    def select_id(self, item_id: str) -> bool:
        page = self._page_for_item(item_id)
        if page is None:
            return False
        self._page = page
        self._render_current_page(selected_id=item_id)
        return self.table.select_id(item_id)

    def _render_current_page(self, *, selected_id: str | None = None) -> None:
        total = len(self.items)
        total_pages = self._total_pages()
        self._page = max(1, min(self._page, total_pages))
        start = (self._page - 1) * self._page_size
        end = start + self._page_size
        visible_items = self.items[start:end]
        self.table.setUpdatesEnabled(False)
        try:
            self.table.set_rows(visible_items)
            if selected_id:
                self.table.select_id(selected_id)
        finally:
            self.table.setUpdatesEnabled(True)
        self.total_label.setText(f"共 {total} 项")
        self.page_label.setText(f"{self._page} / {total_pages} 页")
        self.btn_prev.setEnabled(self._page > 1)
        self.btn_next.setEnabled(self._page < total_pages)
        index = self.page_size_combo.findData(self._page_size)
        if index >= 0 and self.page_size_combo.currentIndex() != index:
            blocked = self.page_size_combo.blockSignals(True)
            self.page_size_combo.setCurrentIndex(index)
            self.page_size_combo.blockSignals(blocked)

    def _set_page(self, page: int) -> None:
        self._page = max(1, min(page, self._total_pages()))
        selected_id = self.table.selected_id()
        self._render_current_page(selected_id=selected_id)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _on_page_size_changed(self) -> None:
        self._page_size = int(self.page_size_combo.currentData() or 20)
        self._page = 1
        self._render_current_page()
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _total_pages(self) -> int:
        return max(1, (len(self.items) + self._page_size - 1) // self._page_size)

    def _page_for_item(self, item_id: str) -> int | None:
        for index, item in enumerate(self.items):
            if item.get("id") == item_id:
                return index // self._page_size + 1
        return None

    def show_image(self, image_path: str) -> None:
        self.media_panel.show_image(image_path)

    def play_video(self, video_path: str) -> None:
        self.media_panel.play_video(video_path)

    def release_media(self) -> None:
        self.media_panel.release_media()

    def cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self.media_panel.cleanup()

    def deleteLater(self) -> None:
        self.cleanup()
        super().deleteLater()

    def _cleanup_before_destroy(self, *_args) -> None:
        self.cleanup()
