from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QHeaderView,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.media_preview_panel import MediaPreviewPanel
from app.ui.components.pagination_footer import PaginationFooter
from app.ui.components.smart_wrap_label import SmartWrapLabel
from app.ui.localization import normalize_language, tr
from app.ui.pages.common import PageFrame, SnapshotActionTable
from app.ui.viewmodels.pagination_state import clamp_page, page_for_item, page_slice, total_pages

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
        self._language = "zh-CN"
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
            cell_padding=(4, 4),
            column_widths={"completed_at_table": 142, "duration": 108, "format": 76},
            suppress_native_selection=True,
        )
        self.table.setObjectName("CompletedItemsTable")
        table_card_layout.addWidget(self.table, 1)
        self.pagination_footer = PaginationFooter(
            self.PAGE_SIZE_OPTIONS,
            default_page_size=self._page_size,
            object_name="CompletedPaginationFooter",
        )
        self.pagination_footer.layout().setContentsMargins(0, 10, 0, 0)
        self.total_label = self.pagination_footer.total_label
        self.btn_prev = self.pagination_footer.btn_prev
        self.btn_next = self.pagination_footer.btn_next
        self.page_label = self.pagination_footer.page_label
        self.page_size_combo = self.pagination_footer.page_size_combo
        table_card_layout.addWidget(self.pagination_footer)
        left_layout.addWidget(self.table_card, 1)
        splitter.addWidget(left)

        self.detail = QWidget()
        self.detail.setObjectName("CompletedRightColumn")
        self.detail.setMinimumWidth(430)
        self.detail.setMaximumWidth(620)
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
        self.info_card.setMinimumHeight(0)
        self.info_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.info_card_layout = QVBoxLayout(self.info_card)
        self.info_card_layout.setContentsMargins(12, 10, 12, 12)
        self.info_card_layout.setSpacing(8)
        self.info_title = QLabel(self._t("文件信息"))
        self.info_title.setObjectName("SectionTitle")
        self.info_card_layout.addWidget(self.info_title)
        self.info_body = QWidget()
        self.info_scroll = QScrollArea()
        self.info_scroll.setObjectName("CompletedInfoScroll")
        self.info_scroll.setWidgetResizable(True)
        self.info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.info_scroll.setMinimumHeight(0)
        self.info_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.info_scroll.setWidget(self.info_body)
        self.info_card_layout.addWidget(self.info_scroll, 1)
        self.detail_layout.addWidget(self.info_card, 1)
        splitter.addWidget(self.detail)
        splitter.setSizes([760, 520])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict] = []
        self._visible_items: list[dict] = []
        self._column_fit_pending = False
        self._detail_signature: tuple | None = None
        self._cleanup_done = False
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_selected_detail())
        self.table.action_requested.connect(self._on_table_action)
        self.media_panel.sig_media_metadata_detected.connect(self._on_media_metadata_detected)
        self.pagination_footer.page_requested.connect(lambda delta: self._set_page(self._page + delta))
        self.pagination_footer.page_size_changed.connect(self._on_page_size_changed)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.info_title.setText(self._t("文件信息"))
        self.pagination_footer.set_language(normalized)
        if hasattr(self.table, "table_model"):
            self.table.table_model.set_language(normalized)
        if hasattr(self.media_panel, "set_language"):
            self.media_panel.set_language(normalized)
        self._detail_signature = None
        self._render_selected_detail()

    def _t(self, text: object) -> str:
        return tr(str(text or ""), self._language)

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
        old_body = self.info_scroll.takeWidget()
        if old_body is not None:
            old_body.deleteLater()
        if not item:
            self.info_body = QWidget()
            self.info_scroll.setWidget(self.info_body)
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
        self.info_scroll.setWidget(self.info_body)

    def _file_info_panel(self, pairs: list[tuple[str, object]]) -> QWidget:
        panel = QWidget()
        panel.setObjectName("CompletedInfoBody")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QGridLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)
        layout.setColumnMinimumWidth(0, 76)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        row = 0
        for index, (key, value) in enumerate(pairs):
            key_label = QLabel(self._t(key), panel)
            key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            key_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

            if index in {0, 1}:
                value_label = SmartWrapLabel(value, panel, compact=True)
                value_label.setObjectName("CompletedInfoSmartWrapLabel")
                value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                value_label.setMinimumWidth(0)
            else:
                value_label = QLabel(str(value or ""), panel)
                value_label.setObjectName("CompletedInfoValueLabel")
                value_label.setWordWrap(True)
                value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                value_label.setMinimumWidth(0)

            layout.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(value_label, row, 1, Qt.AlignmentFlag.AlignTop)
            row += 1
        layout.setRowStretch(row, 1)
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
        self._page = clamp_page(self._page, total, self._page_size)
        visible_items = page_slice(self.items, self._page, self._page_size)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.set_rows(visible_items)
            self._visible_items = list(visible_items)
            if selected_id:
                self.table.select_id(selected_id)
        finally:
            self.table.setUpdatesEnabled(True)
        self._schedule_fit_columns()
        self.pagination_footer.sync(
            total_items=total,
            current_page=self._page,
            total_pages=total_pages,
            page_size=self._page_size,
        )

    def _set_page(self, page: int) -> None:
        self._page = clamp_page(page, len(self.items), self._page_size)
        selected_id = self.table.selected_id()
        self._render_current_page(selected_id=selected_id)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _on_page_size_changed(self, page_size: int | None = None) -> None:
        self._page_size = int(page_size or self.page_size_combo.currentData() or 20)
        self._page = 1
        self._render_current_page()
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _fit_page_size_combo_width(self) -> None:
        self.pagination_footer.fit_page_size_combo_width()

    def _total_pages(self) -> int:
        return total_pages(len(self.items), self._page_size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_fit_columns()

    def _schedule_fit_columns(self) -> None:
        if self._column_fit_pending:
            return
        self._column_fit_pending = True
        QTimer.singleShot(0, self._fit_current_page_columns)

    def _fit_current_page_columns(self) -> None:
        self._column_fit_pending = False
        if self.table.model().columnCount() < 5:
            return
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        widths = self._completed_table_widths(self._visible_items)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, widths[0])
        for column, width in enumerate(widths[1:], start=1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)

    def _completed_table_widths(self, rows: list[dict]) -> list[int]:
        metrics = self.table.fontMetrics()

        def text_width(value: object) -> int:
            return metrics.horizontalAdvance(str(value or ""))

        def bounded(column: int, values: list[object], *, minimum: int, maximum: int, padding: int) -> int:
            header_text = self.table.model().headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            widest = text_width(header_text)
            for value in values:
                widest = max(widest, text_width(value))
            return max(minimum, min(maximum, widest + padding))

        title_width = bounded(
            0,
            [row.get("title", "") for row in rows],
            minimum=168,
            maximum=720,
            padding=32,
        )
        time_width = bounded(
            1,
            [row.get("completed_at_table") or row.get("completed_at") or "" for row in rows],
            minimum=142,
            maximum=156,
            padding=10,
        )
        duration_width = bounded(
            2,
            [row.get("duration", "") for row in rows],
            minimum=108,
            maximum=116,
            padding=12,
        )
        format_width = bounded(
            3,
            [row.get("format", "") for row in rows],
            minimum=76,
            maximum=88,
            padding=18,
        )
        action_width = 80
        return [title_width, time_width, duration_width, format_width, action_width]

    def _page_for_item(self, item_id: str) -> int | None:
        return page_for_item(self.items, item_id, self._page_size)

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
