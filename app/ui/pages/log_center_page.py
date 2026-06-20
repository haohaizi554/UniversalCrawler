from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QTableView,
    QTextEdit,
    QWidget,
)

from app.ui.pages.common import COLUMN_WIDTHS, PageFrame
from app.ui.styles.table_rows import install_click_only_row_selection, install_stable_vertical_scrollbar
from app.ui.viewmodels.snapshot_table_model import SnapshotTableModel

class LogCenterPage(PageFrame):
    def __init__(self) -> None:
        super().__init__("日志中心", use_island=True)
        tabs = QTabWidget()
        for label in ("下载日志", "系统日志", "错误日志"):
            tabs.addTab(QWidget(), label)
        self.root_layout.addWidget(tabs)

        filter_row = QWidget()
        filter_layout = QGridLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setHorizontalSpacing(10)
        filter_layout.setVerticalSpacing(8)
        self.level_filter = QComboBox()
        self.level_filter.addItems(["全部", "INFO", "SUCCESS", "WARN", "ERROR"])
        self.time_filter = QComboBox()
        self.time_filter.addItems(["近 24 小时", "近 7 天", "全部"])
        self.platform_filter = QComboBox()
        self.platform_filter.addItems(["全部", "抖音", "Bilibili", "快手", "MissAV", "小红书"])
        self.trace_filter = QLineEdit()
        self.trace_filter.setPlaceholderText("请输入 Trace ID")
        self.keyword_filter = QLineEdit()
        self.keyword_filter.setPlaceholderText("关键词")
        filters = (
            ("日志级别", self.level_filter),
            ("时间范围", self.time_filter),
            ("平台", self.platform_filter),
            ("Trace ID", self.trace_filter),
            ("关键词", self.keyword_filter),
        )
        for index, (label, widget) in enumerate(filters):
            row = 0 if index < 3 else 1
            col = (index % 3) * 2
            label_widget = QLabel(label)
            label_widget.setObjectName("MutedLabel")
            filter_layout.addWidget(label_widget, row, col)
            filter_layout.addWidget(widget, row, col + 1)
            if index >= 3:
                filter_layout.setColumnStretch(col + 1, 1)
        self.root_layout.addWidget(filter_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table_model = SnapshotTableModel(
            headers=["时间", "级别", "来源", "Trace ID", "消息摘要"],
            columns=["time", "level", "source", "trace_id", "message_summary"],
            parent=self.table,
        )
        self.table.setModel(self.table_model)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(72)
        for index, key in enumerate(("time", "level", "source", "trace_id", "message_summary")):
            if key == "message_summary":
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(index, COLUMN_WIDTHS.get(key, 96))
        install_click_only_row_selection(self.table)
        install_stable_vertical_scrollbar(self.table)
        splitter.addWidget(self.table)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumWidth(340)
        self.detail.setMaximumWidth(480)
        splitter.addWidget(self.detail)
        splitter.setSizes([820, 360])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict] = []
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_detail())

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("log_items") or [])
        current_row = self.table.currentIndex().row()
        changed = self.table_model.set_rows(self.items)
        if self.items and (changed or current_row < 0):
            self.table.selectRow(0)
        self._render_detail()

    def _render_detail(self) -> None:
        item = self.table_model.row_at(self.table.currentIndex().row())
        if not item:
            self.detail.setPlainText("")
            return
        self.detail.setPlainText(
            "\n".join(
                [
                    f"时间: {item.get('time', '')}",
                    f"级别: {item.get('level', '')}",
                    f"来源: {item.get('source', '')}",
                    f"线程: {item.get('thread', '')}",
                    f"Trace ID: {item.get('trace_id', '')}",
                    f"消息: {item.get('message') or item.get('message_summary', '')}",
                    "",
                    "详细信息:",
                    str(item.get("detail") or ""),
                    "",
                    "堆栈跟踪:",
                    str(item.get("stack") or "无"),
                ]
            )
        )
