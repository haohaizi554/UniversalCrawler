from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSplitter, QTextEdit, QVBoxLayout, QWidget

from app.ui.pages.common import PageFrame, SnapshotActionTable, key_value_panel

class FailedPage(PageFrame):
    retry_requested = pyqtSignal(str)
    copy_diagnostics_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("失败列表", use_island=True)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = SnapshotActionTable(
            headers=["标题", "失败时间", "失败原因", "状态", "操作"],
            columns=["title", "failed_at", "reason", "status"],
            actions={"retry": "重试", "copy_diagnostics": "复制诊断", "delete": "删除"},
        )
        splitter.addWidget(self.table)
        self.detail = QWidget()
        self.detail.setMinimumWidth(340)
        self.detail.setMaximumWidth(460)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(14, 0, 0, 0)
        self.detail_title = QLabel("错误详情")
        self.detail_title.setObjectName("PageTitle")
        self.detail_layout.addWidget(self.detail_title)
        self.detail_body = QWidget()
        self.detail_layout.addWidget(self.detail_body)
        self.log_excerpt = QTextEdit()
        self.log_excerpt.setReadOnly(True)
        self.detail_layout.addWidget(QLabel("Trace / 日志片段"))
        self.detail_layout.addWidget(self.log_excerpt, 1)
        splitter.addWidget(self.detail)
        splitter.setSizes([760, 360])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict] = []
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_selected_detail())
        self.table.action_requested.connect(self._on_table_action)

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("failed_items") or [])
        self.table.set_rows(self.items)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _selected_item(self) -> dict | None:
        selected = self.table.selected_id()
        if not selected and self.items:
            selected = self.items[0].get("id")
        return next((item for item in self.items if item.get("id") == selected), None)

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "retry":
            self.retry_requested.emit(item_id)
        elif action == "copy_diagnostics":
            self.copy_diagnostics_requested.emit(item_id)
        elif action == "delete":
            self.delete_requested.emit(item_id)

    def _render_selected_detail(self) -> None:
        item = self._selected_item()
        self.detail_layout.removeWidget(self.detail_body)
        self.detail_body.deleteLater()
        if not item:
            self.detail_body = QWidget()
            self.detail_layout.insertWidget(1, self.detail_body)
            self.log_excerpt.setPlainText("")
            return
        solutions = "\n".join(f"- {s.get('title')}: {s.get('description')}" for s in item.get("solutions", []))
        self.detail_body = key_value_panel(
            [
                ("标题", item.get("title", "")),
                ("失败时间", item.get("failed_at", "")),
                ("失败原因", item.get("reason", "")),
                ("平台", item.get("platform", "")),
                ("Trace ID", item.get("trace_id", "")),
                ("可能解决方案", solutions),
            ]
        )
        self.detail_layout.insertWidget(1, self.detail_body)
        self.log_excerpt.setPlainText("\n".join(item.get("log_excerpt", [])))

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        return self.table.select_id(item_id)
