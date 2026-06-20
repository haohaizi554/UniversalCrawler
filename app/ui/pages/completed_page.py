from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from app.ui.components.media_preview_panel import MediaPreviewPanel
from app.ui.pages.common import PageFrame, SnapshotActionTable, key_value_panel

class CompletedPage(PageFrame):
    play_requested = pyqtSignal(str)
    open_directory_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, style_provider) -> None:
        super().__init__("已完成", use_island=True)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = SnapshotActionTable(
            headers=["标题", "完成时间", "时长", "分辨率", "大小", "格式", "操作"],
            columns=["title", "completed_at", "duration", "resolution", "size", "format"],
            actions={"play": "播放", "open_directory": "打开目录", "delete": "删除"},
        )
        left_layout.addWidget(self.table, 1)
        splitter.addWidget(left)

        self.detail = QWidget()
        self.detail.setMinimumWidth(360)
        self.detail.setMaximumWidth(500)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(14, 0, 0, 0)
        self.media_panel = MediaPreviewPanel(style_provider)
        self.media_panel.setMinimumHeight(260)
        self.detail_layout.addWidget(self.media_panel, 2)
        self.info_title = QLabel("文件信息")
        self.info_title.setObjectName("PageTitle")
        self.detail_layout.addWidget(self.info_title)
        self.info_body = QWidget()
        self.detail_layout.addWidget(self.info_body, 1)
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

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("completed_items") or [])
        selected_id = self.table.selected_id()
        self.table.set_rows(self.items)
        if selected_id:
            self.table.select_id(selected_id)
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

    def _render_selected_detail(self) -> None:
        item = self._selected_item()
        signature = self._detail_signature_for(item)
        if signature == self._detail_signature:
            return
        self._detail_signature = signature
        self.detail_layout.removeWidget(self.info_body)
        self.info_body.deleteLater()
        if not item:
            self.info_body = QWidget()
            self.detail_layout.insertWidget(3, self.info_body, 1)
            return
        self.info_body = key_value_panel(
            [
                ("保存路径", item.get("local_path", "")),
                ("完成时间", item.get("completed_at", "")),
                ("时长", item.get("duration", "")),
                ("分辨率", item.get("resolution", "")),
                ("格式", item.get("format", "")),
                ("大小", item.get("size", "")),
                ("完成概览", f"共 {len(self.items)} 个"),
                ("存储占用", item.get("size", "")),
            ]
        )
        self.detail_layout.insertWidget(3, self.info_body, 1)

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
        )

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def id_order(self) -> list[str]:
        return self.table.id_order()

    def select_id(self, item_id: str) -> bool:
        return self.table.select_id(item_id)

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
