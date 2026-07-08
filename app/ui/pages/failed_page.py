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
from app.ui.components.pagination_footer import PaginationFooter
from app.ui.localization import normalize_language, tr
from app.ui.pages.common import PageFrame, SnapshotActionTable
from app.ui.viewmodels.failed_page_projection import prepare_failed_item_for_display
from app.ui.viewmodels.list_page_worker import ListPageRequest, ListPageResult, ListPageWorker
from app.utils.qt_runtime import load_qt_icon


class FailedPage(PageFrame):
    _page_result_ready = pyqtSignal(object)

    retry_requested = pyqtSignal(str)
    copy_diagnostics_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    PAGE_SIZE_OPTIONS = (20, 50, 100)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        self._language = "zh-CN"
        self._page = 1
        self._page_size = 20
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
        self.pagination_footer = PaginationFooter(
            self.PAGE_SIZE_OPTIONS,
            default_page_size=self._page_size,
            object_name="FailedPaginationFooter",
        )
        self.pagination_footer.layout().setContentsMargins(0, 10, 0, 0)
        self.total_label = self.pagination_footer.total_label
        self.btn_prev = self.pagination_footer.btn_prev
        self.btn_next = self.pagination_footer.btn_next
        self.page_label = self.pagination_footer.page_label
        self.page_size_combo = self.pagination_footer.page_size_combo
        table_card_layout.addWidget(self.pagination_footer)
        splitter.addWidget(self.table_card)

        self.detail = QWidget()
        self.detail.setObjectName("FailedRightColumn")
        self.detail.setMinimumWidth(420)
        self.detail.setMaximumWidth(540)
        self.detail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(10)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("FailedDetailCard")
        self.detail_card_layout = QVBoxLayout(self.detail_card)
        self.detail_card_layout.setContentsMargins(14, 12, 14, 14)
        self.detail_card_layout.setSpacing(10)
        self.detail_title = QLabel(self._t("错误详情"))
        self.detail_title.setObjectName("SectionTitle")
        self.detail_card_layout.addWidget(self.detail_title)

        self.summary_body = QWidget()
        self.summary_body.setObjectName("FailedSummaryBody")
        self.summary_layout = QVBoxLayout(self.summary_body)
        self.summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_layout.setSpacing(7)
        self.detail_card_layout.addWidget(self.summary_body)

        self.log_title = QLabel(self._t("Trace / 日志片段"))
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
        self.solutions_title = QLabel(self._t("可能的解决方案"))
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
        splitter.setSizes([800, 440])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)

        self.items: list[dict[str, Any]] = []
        self._id_order: tuple[str, ...] = ()
        self._items_by_id: dict[str, dict[str, Any]] = {}
        self._detail_signature: tuple[Any, ...] | None = None
        self._selected_item_id: str | None = None
        self._syncing_selection = False
        self._page_sequence = 0
        self._page_request_preserves_selection = False
        self._page_worker: ListPageWorker | None = None
        self._page_result_ready.connect(self._apply_page_result, Qt.ConnectionType.QueuedConnection)
        self.table.selectionModel().currentChanged.connect(self._on_table_selection_changed)
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self.table.action_requested.connect(self._on_table_action)
        self.pagination_footer.page_requested.connect(lambda delta: self._set_page(self._page + delta))
        self.pagination_footer.page_size_changed.connect(self._on_page_size_changed)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.detail_title.setText(self._t("错误详情"))
        self.log_title.setText(self._t("Trace / 日志片段"))
        self.solutions_title.setText(self._t("可能的解决方案"))
        self.pagination_footer.set_language(normalized)
        if hasattr(self.table, "table_model"):
            self.table.table_model.set_language(normalized)
        selected_id = self.table.selected_id() or self._selected_item_id or ""
        self._submit_page_request(self.items, selected_id=str(selected_id or ""))

    def _t(self, text: object) -> str:
        return tr(str(text or ""), self._language)

    @staticmethod
    def _scroll_container(object_name: str) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def render(self, snapshot: dict) -> None:
        previous_id = self._selected_item_id or self.table.selected_id()
        self._submit_page_request(snapshot.get("failed_items") or [], selected_id=str(previous_id or ""))

    def _submit_page_request(self, items: object, *, selected_id: str = "") -> None:
        self._page_sequence += 1
        self._page_request_preserves_selection = bool(selected_id)
        source_items = items if isinstance(items, list | tuple) else ()
        request = ListPageRequest(
            sequence=self._page_sequence,
            items=source_items,
            page=self._page,
            page_size=self._page_size,
            selected_id=selected_id,
            select_first=True,
            selected_id_moves_page=bool(selected_id),
            item_transformer=lambda item, language=self._language: prepare_failed_item_for_display(
                item,
                language=language,
            ),
        )
        worker = self._page_worker
        if worker is None:
            worker = ListPageWorker(self._page_result_ready.emit)
            self._page_worker = worker
        worker.submit(request)

    def _apply_page_result(self, result: object) -> None:
        if not isinstance(result, ListPageResult) or result.sequence != self._page_sequence:
            return
        current_selected_id = ""
        if self._page_request_preserves_selection:
            current_selected_id = str(self._selected_item_id or self.table.selected_id() or "")
        self.items = result.items
        self._id_order = result.id_order
        self._items_by_id = result.items_by_id
        self._page = result.current_page
        if current_selected_id and current_selected_id in self._items_by_id:
            self._selected_item_id = current_selected_id
        else:
            self._selected_item_id = result.selected_id or None
        self._syncing_selection = True
        try:
            self.table.set_rows(result.page_items)
            self._sync_table_selection()
        finally:
            self._syncing_selection = False
        self.pagination_footer.sync(
            total_items=result.total_count,
            current_page=self._page,
            total_pages=result.total_pages,
            page_size=self._page_size,
        )
        self._render_selected_detail()

    def _set_page(self, page: int) -> None:
        self._page = int(page or 1)
        self._selected_item_id = None
        self._submit_page_request(self.items, selected_id="")

    def _on_page_size_changed(self, page_size: int | None = None) -> None:
        self._page_size = int(page_size or self.page_size_combo.currentData() or 20)
        self._page = 1
        selected_id = self.table.selected_id() or self._selected_item_id or ""
        self._submit_page_request(self.items, selected_id=str(selected_id or ""))

    def _selected_item(self) -> dict[str, Any] | None:
        selected = self._valid_item_id(self._selected_item_id)
        if not selected:
            selected = self._valid_item_id(self.table.selected_id()) or self._first_item_id()
            self._selected_item_id = selected
        return self._items_by_id.get(selected or "")

    def _on_table_selection_changed(self, *_args: Any) -> None:
        if self._syncing_selection:
            return
        selected = self._valid_item_id(self.table.selected_id())
        if not selected:
            if self.items:
                return
            self._selected_item_id = None
        elif selected != self._selected_item_id:
            self._selected_item_id = selected
        self._render_selected_detail()

    def _valid_item_id(self, item_id: object) -> str | None:
        value = str(item_id or "")
        if not value:
            return None
        return value if value in self._items_by_id else None

    def _first_item_id(self) -> str | None:
        return self._id_order[0] if self._id_order else None

    def _sync_table_selection(self) -> None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        if not self._selected_item_id:
            selection_model.clearSelection()
            return
        if self.table.selected_id() != self._selected_item_id:
            self.table.select_id(self._selected_item_id)

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "retry":
            self.retry_requested.emit(item_id)
        elif action == "copy_diagnostics":
            self.copy_diagnostics_requested.emit(item_id)
        elif action == "delete":
            self.delete_requested.emit(item_id)

    def _render_selected_detail(self) -> None:
        item = self._selected_item()
        signature = self._detail_signature_for(item)
        if signature == self._detail_signature:
            return
        self._detail_signature = signature
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
                item.get("reason_detail_display") or "",
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

        for entry in list(item.get("log_excerpt_display_items") or []):
            self.log_layout.addWidget(self._log_row(entry))
        if self.log_layout.count() == 0:
            self.log_layout.addWidget(self._empty_label("暂无日志片段"))
        self.log_layout.addStretch(1)

        for solution in list(item.get("solutions_display") or []):
            self.solutions_list_layout.addWidget(self._solution_row(solution))
        if self.solutions_list_layout.count() == 0:
            self.solutions_list_layout.addWidget(self._empty_label("暂无建议"))
        self.solutions_list_layout.addStretch(1)

    def _detail_signature_for(self, item: dict[str, Any] | None) -> tuple[Any, ...]:
        if not item:
            return ("empty", self._language)
        return (
            self._language,
            item.get("id", ""),
            item.get("title", ""),
            item.get("failed_at", ""),
            item.get("reason_detail_display") or "",
            item.get("reason_icon_file", ""),
            item.get("platform", ""),
            item.get("platform_id", ""),
            item.get("trace_id", ""),
            self._log_entries_signature(item.get("log_excerpt_display_items") or []),
            self._solutions_signature(item.get("solutions_display") or []),
        )

    @staticmethod
    def _log_entries_signature(entries: Any) -> tuple[tuple[str, str, str, str, str], ...]:
        return tuple(
            (
                str(entry.get("time") or ""),
                str(entry.get("time_display") or ""),
                str(entry.get("level") or entry.get("raw_level") or ""),
                str(entry.get("message_display") or ""),
                str(entry.get("icon_file") or ""),
            )
            for entry in list(entries or [])
            if isinstance(entry, dict)
        )

    @staticmethod
    def _solutions_signature(solutions: Any) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (
                str(solution.get("title_display") or ""),
                str(solution.get("description_display") or ""),
                str(solution.get("icon_file") or ""),
            )
            for solution in list(solutions or [])
            if isinstance(solution, dict)
        )

    def _detail_row(self, label: str, value: Any, *, icon_file: str = "", emphasized: bool = False) -> QWidget:
        row = QWidget()
        row.setObjectName("FailedDetailRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        key = QLabel(self._t(label))
        key.setObjectName("FailedDetailKey")
        key.setFixedWidth(82)
        row_layout.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
        value_widget = self._icon_text(value, icon_file=icon_file, object_name="FailedDetailValue")
        value_widget.setMinimumWidth(0)
        value_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if emphasized:
            value_widget.setProperty("emphasized", True)
        row_layout.addWidget(value_widget, 1)
        row_layout.setStretch(1, 1)
        return row

    def _log_row(self, entry: dict[str, Any]) -> QWidget:
        row = QFrame()
        row.setObjectName("FailedLogRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 1, 0, 1)
        layout.setSpacing(7)
        time_label = QLabel(str(entry.get("time_display") or "--:--:--"))
        time_label.setObjectName("FailedLogTime")
        time_label.ensurePolished()
        time_width = max(
            64,
            time_label.fontMetrics().horizontalAdvance("88:88:88"),
            time_label.fontMetrics().horizontalAdvance(time_label.text()),
        ) + 10
        time_label.setFixedWidth(time_width)
        time_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.addWidget(time_label, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        level_badge = self._log_level_badge(entry)
        layout.addWidget(level_badge, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        message = QLabel(str(entry.get("message_display") or ""))
        message.setObjectName("FailedLogMessage")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message.setMinimumWidth(0)
        message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(message, 1, Qt.AlignmentFlag.AlignTop)
        layout.setStretch(2, 1)
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
        badge.setFixedWidth(74)
        return badge

    def _solution_row(self, solution: dict[str, Any]) -> QWidget:
        row = QFrame()
        row.setObjectName("FailedSolutionRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self._icon_label(str(solution.get("icon_file") or "action_help.png"), 18), 0, Qt.AlignmentFlag.AlignTop)
        text_box = QWidget()
        text_box.setMinimumWidth(0)
        text_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        title = QLabel(str(solution.get("title_display") or ""))
        title.setObjectName("FailedSolutionTitle")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        desc = QLabel(str(solution.get("description_display") or ""))
        desc.setObjectName("FailedSolutionDescription")
        desc.setWordWrap(True)
        desc.setMinimumWidth(0)
        desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        text_layout.addWidget(title)
        text_layout.addWidget(desc)
        layout.addWidget(text_box, 1)
        return row

    def _icon_text(self, value: Any, *, icon_file: str = "", object_name: str = "") -> QWidget:
        widget = QWidget()
        widget.setObjectName(object_name)
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        if icon_file:
            layout.addWidget(self._icon_label(icon_file, 18), 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(self._t(value or ""))
        label.setObjectName(f"{object_name}Text" if object_name else "IconTextLabel")
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label, 1)
        layout.setStretch(layout.count() - 1, 1)
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

    def _empty_label(self, text: str) -> QLabel:
        label = QLabel(self._t(text))
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                FailedPage._clear_layout(child_layout)

    def selected_id(self) -> str | None:
        return self._selected_item_id or self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        selected = self._valid_item_id(item_id)
        if not selected:
            return False
        self._selected_item_id = selected
        if selected not in self.table.id_order():
            self._submit_page_request(self.items, selected_id=selected)
            return True
        self._syncing_selection = True
        try:
            ok = self.table.select_id(selected)
        finally:
            self._syncing_selection = False
        if ok:
            self._render_selected_detail()
        return ok

    def deleteLater(self) -> None:
        if self._page_worker is not None:
            self._page_worker.shutdown()
            self._page_worker = None
        super().deleteLater()
