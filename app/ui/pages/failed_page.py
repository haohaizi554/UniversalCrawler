from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import platform_icon_file, ui_icon_path
from app.ui.pages.common import PageFrame, SnapshotActionTable
from app.utils.qt_runtime import load_qt_icon


class FailedPage(PageFrame):
    retry_requested = pyqtSignal(str)
    copy_diagnostics_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("FailedPageSplitter")

        self.table_card = QFrame()
        self.table_card.setObjectName("FailedTableCard")
        table_card_layout = QVBoxLayout(self.table_card)
        table_card_layout.setContentsMargins(12, 10, 12, 12)
        table_card_layout.setSpacing(0)
        self.table = SnapshotActionTable(
            headers=["标题", "失败时间", "失败原因", "状态", "操作"],
            columns=["title", "failed_at_table", "reason_label", "status_label"],
            actions={"copy_diagnostics": "复制 Trace ID", "delete": "删除"},
            icon_columns={"reason_label"},
            cell_padding=(12, 10),
            suppress_native_selection=True,
        )
        self.table.setObjectName("FailedItemsTable")
        table_card_layout.addWidget(self.table, 1)
        splitter.addWidget(self.table_card)

        self.detail = QWidget()
        self.detail.setObjectName("FailedRightColumn")
        self.detail.setMinimumWidth(380)
        self.detail.setMaximumWidth(520)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("FailedDetailCard")
        self.detail_card_layout = QVBoxLayout(self.detail_card)
        self.detail_card_layout.setContentsMargins(8, 12, 12, 14)
        self.detail_card_layout.setSpacing(10)
        self.detail_title = QLabel("错误详情")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_card_layout.addWidget(self.detail_title)

        self.summary_body = QWidget()
        self.summary_body.setObjectName("FailedSummaryBody")
        self.summary_layout = QVBoxLayout(self.summary_body)
        self.summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_layout.setSpacing(7)
        self.detail_card_layout.addWidget(self.summary_body)

        self.log_title = QLabel("Trace / 日志片段")
        self.log_title.setObjectName("SectionTitle")
        self.detail_card_layout.addWidget(self.log_title)
        self.log_scroll = self._scroll_container("FailedLogExcerptScroll")
        self.log_list = QWidget()
        self.log_list.setObjectName("FailedLogExcerptList")
        self.log_layout = QVBoxLayout(self.log_list)
        self.log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_layout.setSpacing(4)
        self.log_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.log_scroll.setWidget(self.log_list)
        self.detail_card_layout.addWidget(self.log_scroll, 1)
        self.detail_layout.addWidget(self.detail_card, 2)

        self.solutions_card = QFrame()
        self.solutions_card.setObjectName("FailedSolutionsCard")
        self.solutions_layout = QVBoxLayout(self.solutions_card)
        self.solutions_layout.setContentsMargins(14, 12, 14, 14)
        self.solutions_layout.setSpacing(8)
        self.solutions_title = QLabel("可能的解决方案")
        self.solutions_title.setObjectName("SectionTitle")
        self.solutions_layout.addWidget(self.solutions_title)
        self.solutions_list = QWidget()
        self.solutions_list.setObjectName("FailedSolutionsList")
        self.solutions_list_layout = QVBoxLayout(self.solutions_list)
        self.solutions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.solutions_list_layout.setSpacing(8)
        self.solutions_layout.addWidget(self.solutions_list, 1)
        self.detail_layout.addWidget(self.solutions_card, 1)

        splitter.addWidget(self.detail)
        splitter.setSizes([820, 420])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)

        self.items: list[dict[str, Any]] = []
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_selected_detail())
        self.table.action_requested.connect(self._on_table_action)

    @staticmethod
    def _scroll_container(object_name: str) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("failed_items") or [])
        self.table.set_rows(self.items)
        if self.items and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        self._render_selected_detail()

    def _selected_item(self) -> dict[str, Any] | None:
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
        self._clear_layout(self.summary_layout)
        self._clear_layout(self.log_layout)
        self._clear_layout(self.solutions_list_layout)
        if not item:
            self.summary_layout.addWidget(self._empty_label("暂无失败任务"))
            self.log_layout.addWidget(self._empty_label("暂无日志片段"))
            self.solutions_list_layout.addWidget(self._empty_label("暂无建议"))
            return

        self.summary_layout.addWidget(self._detail_row("标题", item.get("title", "")))
        self.summary_layout.addWidget(self._detail_row("失败时间", item.get("failed_at", "")))
        self.summary_layout.addWidget(
            self._detail_row(
                "失败原因",
                item.get("reason_detail") or item.get("reason") or "",
                icon_file=str(item.get("reason_icon_file") or ""),
                emphasized=True,
            )
        )
        self.summary_layout.addWidget(
            self._detail_row(
                "平台",
                item.get("platform", ""),
                icon_file=platform_icon_file(str(item.get("platform_id") or "")),
            )
        )
        self.summary_layout.addWidget(self._detail_row("Trace ID", item.get("trace_id", "")))

        for entry in list(item.get("log_excerpt_items") or []):
            self.log_layout.addWidget(self._log_row(entry))
        if not (item.get("log_excerpt_items") or []):
            for message in list(item.get("log_excerpt") or []):
                self.log_layout.addWidget(self._log_row({"level": "INFO", "message": message, "icon_file": "log_level_info.png"}))
        if self.log_layout.count() == 0:
            self.log_layout.addWidget(self._empty_label("暂无日志片段"))
        self.log_layout.addStretch(1)

        for solution in list(item.get("solutions") or []):
            self.solutions_list_layout.addWidget(self._solution_row(solution))
        if self.solutions_list_layout.count() == 0:
            self.solutions_list_layout.addWidget(self._empty_label("暂无建议"))
        self.solutions_list_layout.addStretch(1)

    def _detail_row(self, label: str, value: Any, *, icon_file: str = "", emphasized: bool = False) -> QWidget:
        row = QWidget()
        row.setObjectName("FailedDetailRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        key = QLabel(label)
        key.setObjectName("FailedDetailKey")
        key.setMinimumWidth(82)
        row_layout.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
        value_widget = self._icon_text(value, icon_file=icon_file, object_name="FailedDetailValue")
        if emphasized:
            value_widget.setProperty("emphasized", True)
        row_layout.addWidget(value_widget, 1)
        return row

    def _log_row(self, entry: dict[str, Any]) -> QWidget:
        row = QFrame()
        row.setObjectName("FailedLogRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        time_label = QLabel(str(entry.get("time") or "--:--:--")[-8:])
        time_label.setObjectName("FailedLogTime")
        time_width = max(52, time_label.fontMetrics().horizontalAdvance("00:00:00"))
        time_label.setFixedWidth(time_width)
        time_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(time_label, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        level_badge = self._log_level_badge(entry)
        layout.addWidget(level_badge, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        message = QLabel(str(entry.get("message") or ""))
        message.setObjectName("FailedLogMessage")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(message, 1, Qt.AlignmentFlag.AlignTop)
        return row

    @classmethod
    def _log_level_text(cls, entry: dict[str, Any]) -> str:
        level = str(entry.get("level") or entry.get("raw_level") or "").strip().upper()
        if not level:
            icon_file = str(entry.get("icon_file") or "").lower()
            if "error" in icon_file:
                level = "ERROR"
            elif "warn" in icon_file:
                level = "WARN"
            elif "success" in icon_file or "ok" in icon_file:
                level = "SUCCESS"
            elif "cmd" in icon_file or "command" in icon_file:
                level = "CMD"
            else:
                level = "INFO"
        if level == "WARNING":
            return "WARN"
        if level in {"OK", "SUCCESS"}:
            return "SUCCESS"
        if level == "COMMAND":
            return "CMD"
        if level in {"INFO", "WARN", "ERROR", "CMD"}:
            return level
        return level[:8] or "INFO"

    def _log_level_badge(self, entry: dict[str, Any]) -> QLabel:
        level = self._log_level_text(entry)
        object_names = {
            "INFO": "LogLevelBadgeInfo",
            "SUCCESS": "LogLevelBadgeSuccess",
            "WARN": "LogLevelBadgeWarn",
            "ERROR": "LogLevelBadgeError",
            "CMD": "LogLevelBadgeCommand",
        }
        badge = QLabel(level)
        badge.setObjectName(object_names.get(level, "LogLevelBadgeInfo"))
        badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(22)
        badge.setMinimumWidth(max(46, badge.fontMetrics().horizontalAdvance(level) + 18))
        badge.setMaximumWidth(92)
        return badge

    def _solution_row(self, solution: dict[str, Any]) -> QWidget:
        row = QFrame()
        row.setObjectName("FailedSolutionRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self._icon_label(str(solution.get("icon_file") or "action_help.png"), 18), 0, Qt.AlignmentFlag.AlignTop)
        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        title = QLabel(str(solution.get("title") or "建议"))
        title.setObjectName("FailedSolutionTitle")
        desc = QLabel(str(solution.get("description") or ""))
        desc.setObjectName("FailedSolutionDescription")
        desc.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(desc)
        layout.addWidget(text_box, 1)
        return row

    def _icon_text(self, value: Any, *, icon_file: str = "", object_name: str = "") -> QWidget:
        widget = QWidget()
        widget.setObjectName(object_name)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        if icon_file:
            layout.addWidget(self._icon_label(icon_file, 18), 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(str(value or ""))
        label.setObjectName(f"{object_name}Text" if object_name else "IconTextLabel")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label, 1)
        return widget

    @staticmethod
    def _icon_label(icon_file: str, size: int) -> QLabel:
        label = QLabel()
        label.setObjectName("InlineIcon")
        label.setFixedSize(size, size)
        icon = load_qt_icon([ui_icon_path(icon_file)])
        if icon is not None:
            label.setPixmap(icon.pixmap(size, size))
        return label

    @staticmethod
    def _empty_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        return self.table.select_id(item_id)
