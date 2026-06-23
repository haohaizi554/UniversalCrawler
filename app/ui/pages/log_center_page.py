from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.pages.common import PageFrame, SnapshotActionTable


LOG_CATEGORIES = {
    "all": "全部日志",
    "download": "下载日志",
    "system": "系统日志",
    "error": "错误日志",
}


class LogCenterPage(PageFrame):
    log_action_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        self._all_items: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self._category = "all"
        self._tab_buttons: dict[str, QPushButton] = {}

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("LogCenterSplitter")

        self.table_card = QFrame()
        self.table_card.setObjectName("LogTableCard")
        table_card_layout = QVBoxLayout(self.table_card)
        table_card_layout.setContentsMargins(12, 10, 12, 12)
        table_card_layout.setSpacing(10)

        table_card_layout.addWidget(self._build_tabs())
        table_card_layout.addWidget(self._build_filters())
        table_card_layout.addWidget(self._build_actions())

        self.table = SnapshotActionTable(
            headers=["时间", "级别", "来源", "Trace ID", "消息摘要"],
            columns=["time", "level", "source", "trace_id", "message_summary"],
            row_height=42,
            cell_padding=(12, 10),
            suppress_native_selection=True,
        )
        self.table.setObjectName("LogItemsTable")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_detail())
        table_card_layout.addWidget(self.table, 1)
        splitter.addWidget(self.table_card)

        self.right_column = QWidget()
        self.right_column.setObjectName("LogRightColumn")
        self.right_column.setMinimumWidth(360)
        self.right_column.setMaximumWidth(520)
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("LogDetailCard")
        detail_layout = QVBoxLayout(self.detail_card)
        detail_layout.setContentsMargins(14, 12, 14, 14)
        detail_layout.setSpacing(8)
        detail_title = QLabel("日志详情")
        detail_title.setObjectName("SectionTitle")
        detail_layout.addWidget(detail_title)
        self.detail = QTextEdit()
        self.detail.setObjectName("LogDetailText")
        self.detail.setReadOnly(True)
        detail_layout.addWidget(self.detail, 1)
        right_layout.addWidget(self.detail_card, 1)

        self.extra_card = QFrame()
        self.extra_card.setObjectName("LogExtraCard")
        extra_layout = QVBoxLayout(self.extra_card)
        extra_layout.setContentsMargins(14, 12, 14, 14)
        extra_layout.setSpacing(8)
        self.extra_title = QLabel("详细信息")
        self.extra_title.setObjectName("SectionTitle")
        extra_layout.addWidget(self.extra_title)
        self.extra = QTextEdit()
        self.extra.setObjectName("LogExtraText")
        self.extra.setReadOnly(True)
        extra_layout.addWidget(self.extra, 1)
        right_layout.addWidget(self.extra_card, 1)

        splitter.addWidget(self.right_column)
        splitter.setSizes([860, 420])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)

    def _build_tabs(self) -> QWidget:
        row = QWidget()
        row.setObjectName("LogTabs")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for category, label in LOG_CATEGORIES.items():
            button = QPushButton(label)
            button.setObjectName("LogTabButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, key=category: self._set_category(key))
            layout.addWidget(button)
            self._tab_buttons[category] = button
        layout.addStretch(1)
        self._sync_tab_buttons()
        return row

    def _build_filters(self) -> QWidget:
        row = QWidget()
        row.setObjectName("LogFilters")
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        self.level_filter = QComboBox()
        self.level_filter.addItems(["全部", "INFO", "SUCCESS", "WARN", "ERROR"])
        self.time_filter = QComboBox()
        self.time_filter.addItems(["近 30 分钟", "近 1 小时", "近 24 小时", "全部"])
        self.platform_filter = QComboBox()
        self.platform_filter.addItems(["全部", "抖音", "Bilibili", "快手", "MissAV", "小红书", "系统"])
        self.trace_filter = QLineEdit()
        self.trace_filter.setPlaceholderText("请输入 Trace ID")
        self.keyword_filter = QLineEdit()
        self.keyword_filter.setPlaceholderText("请输入关键词")

        filters = [
            ("日志级别", self.level_filter),
            ("时间范围", self.time_filter),
            ("平台", self.platform_filter),
            ("Trace ID", self.trace_filter),
            ("关键词搜索", self.keyword_filter),
        ]
        for index, (label, widget) in enumerate(filters):
            label_widget = QLabel(label)
            label_widget.setObjectName("MutedLabel")
            layout.addWidget(label_widget, 0, index)
            layout.addWidget(widget, 1, index)
            layout.setColumnStretch(index, 1)

        self.level_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.time_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.platform_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.trace_filter.textChanged.connect(lambda *_args: self._apply_filters())
        self.keyword_filter.textChanged.connect(lambda *_args: self._apply_filters())
        return row

    def _build_actions(self) -> QWidget:
        row = QWidget()
        row.setObjectName("LogActions")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        actions = [
            ("clear", "清空日志"),
            ("export", "导出日志"),
            ("refresh", "刷新缓冲"),
            ("open_latest", "打开 latest_debug.log"),
            ("open_error_summary", "打开 latest_error_summary.md"),
        ]
        for operation, label in actions:
            button = QPushButton(label)
            button.setObjectName("LogActionButton")
            button.clicked.connect(lambda _checked=False, key=operation: self.log_action_requested.emit(key))
            layout.addWidget(button)
        layout.addStretch(1)
        return row

    def render(self, snapshot: dict) -> None:
        self._all_items = list(snapshot.get("log_items") or [])
        self._apply_filters()

    def _set_category(self, category: str) -> None:
        self._category = category if category in LOG_CATEGORIES else "all"
        self._sync_tab_buttons()
        self._apply_filters()

    def _sync_tab_buttons(self) -> None:
        for category, button in self._tab_buttons.items():
            button.setChecked(category == self._category)

    def _apply_filters(self) -> None:
        previous_id = self.selected_id()
        self.items = [item for item in self._all_items if self._matches_filters(item)]
        self.table.set_rows(self.items)
        if previous_id and self.select_id(previous_id):
            self._render_detail()
            return
        if self.items:
            self.table.selectRow(0)
        self._render_detail()

    def _matches_filters(self, item: dict[str, Any]) -> bool:
        if not self._matches_category(item):
            return False
        level = self.level_filter.currentText() if hasattr(self, "level_filter") else "全部"
        if level != "全部" and str(item.get("level") or "").upper() != level:
            return False
        if not self._matches_time_range(item):
            return False
        platform = self.platform_filter.currentText() if hasattr(self, "platform_filter") else "全部"
        if platform != "全部" and platform not in self._searchable_text(item, include_detail=True):
            return False
        trace_query = self.trace_filter.text().strip().lower() if hasattr(self, "trace_filter") else ""
        if trace_query and trace_query not in str(item.get("trace_id") or "").lower():
            return False
        keyword = self.keyword_filter.text().strip().lower() if hasattr(self, "keyword_filter") else ""
        if keyword and keyword not in self._searchable_text(item, include_detail=True).lower():
            return False
        return True

    def _matches_category(self, item: dict[str, Any]) -> bool:
        if self._category == "all":
            return True
        if self._category == "error":
            return str(item.get("level") or "").upper() == "ERROR" or item.get("category") == "error"
        return item.get("category") == self._category

    def _matches_time_range(self, item: dict[str, Any]) -> bool:
        label = self.time_filter.currentText() if hasattr(self, "time_filter") else "全部"
        minutes = {"近 30 分钟": 30, "近 1 小时": 60, "近 24 小时": 24 * 60}.get(label)
        if minutes is None:
            return True
        timestamp = self._item_datetime(item)
        if timestamp is None:
            return False
        return timestamp >= datetime.now() - timedelta(minutes=minutes)

    @staticmethod
    def _item_datetime(item: dict[str, Any]) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(str(item.get("time") or ""), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _searchable_text(item: dict[str, Any], *, include_detail: bool = False) -> str:
        keys = ["platform", "source", "trace_id", "level", "message_summary", "message"]
        if include_detail:
            keys.extend(["detail", "stack"])
        return " ".join(str(item.get(key) or "") for key in keys)

    def _render_detail(self) -> None:
        item = self.table.row_at(self.table.currentIndex().row())
        if not item:
            self.detail.setPlainText("暂无日志")
            self.extra.setPlainText("暂无详细信息")
            self.extra_card.setVisible(True)
            return
        rows = [
            ("时间", item.get("time", "")),
            ("级别", item.get("level", "")),
            ("来源", item.get("source", "")),
            ("平台", item.get("platform", "")),
            ("线程", item.get("thread", "")),
            ("Trace ID", item.get("trace_id", "")),
            ("消息", item.get("message") or item.get("message_summary", "")),
        ]
        self.detail.setPlainText("\n".join(f"{label}: {value}" for label, value in rows))
        detail = str(item.get("detail") or "").strip()
        stack = str(item.get("stack") or "").strip()
        if stack and stack != "无":
            self.extra_title.setText("详细信息 / 堆栈跟踪")
            self.extra.setPlainText(f"{detail}\n\n堆栈跟踪:\n{stack}".strip())
            self.extra_card.setVisible(True)
        elif detail:
            self.extra_title.setText("详细信息")
            self.extra.setPlainText(detail)
            self.extra_card.setVisible(True)
        else:
            self.extra_card.setVisible(False)

    def selected_id(self) -> str | None:
        row = self.table.currentIndex().row()
        item = self.table.row_at(row)
        if not item:
            return None
        return self._item_id(item, row)

    def row_for_id(self, item_id: str) -> int:
        for row, item in enumerate(self.items):
            if self._item_id(item, row) == item_id:
                return row
        return -1

    def select_id(self, item_id: str) -> bool:
        row = self.row_for_id(item_id)
        if row < 0:
            return False
        self.table.selectRow(row)
        return True

    @staticmethod
    def _item_id(item: dict[str, Any], row: int) -> str:
        return str(item.get("id") or f"{item.get('time', '')}|{item.get('trace_id', '')}|{row}")
