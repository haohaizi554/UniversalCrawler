from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.services.icon_registry import ui_icon_path
from shared.icon_contract import action_icon_file
from app.ui.components.pagination_footer import PaginationFooter
from app.ui.layout.island import IslandCard
from shared.localization import normalize_language, tr
from app.ui.pages.common import PageFrame, SnapshotActionTable
from app.ui.viewmodels.list_page_worker import ListPageRequest, ListPageResult, ListPageWorker
from app.utils.qt_lifecycle import connect_destroyed_cleanup
from app.utils.qt_runtime import load_qt_icon

class DownloadQueuePage(PageFrame):
    _page_result_ready = pyqtSignal(object)

    delete_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()

    PAGE_SIZE_OPTIONS = (20, 50, 100)
    ROW_HEIGHT = 52

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self._id_order: tuple[str, ...] = ()
        self._path_text = ""
        self._events_signature: tuple | None = None
        self._page = 1
        self._page_size = 20
        self._language = "zh-CN"
        self._page_sequence = 0
        self._page_worker: ListPageWorker | None = None
        self._page_result_ready.connect(self._apply_page_result, Qt.ConnectionType.QueuedConnection)
        connect_destroyed_cleanup(self, self._shutdown_page_worker)

        self.table_island = IslandCard(object_name="QueueTableIsland")
        self.table_island.content_layout.setContentsMargins(10, 10, 10, 10)
        table_host = QWidget()
        table_layout = QVBoxLayout(table_host)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(10)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(10)
        self.path_prefix_label = QLabel("保存至:")
        path_layout.addWidget(self.path_prefix_label)
        self.path_label = QLabel("")
        self.path_label.setObjectName("PathLabel")
        path_layout.addWidget(self.path_label, 1)
        self.btn_clear_all = QPushButton()
        self.btn_clear_all.setObjectName("ToolbarIconBtn")
        self.btn_clear_all.setToolTip(self._t("删除所有"))
        clear_icon = load_qt_icon([ui_icon_path(action_icon_file("clear_all"))])
        if clear_icon is not None:
            self.btn_clear_all.setIcon(clear_icon)
            self.btn_clear_all.setIconSize(QSize(24, 24))
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        path_layout.addWidget(self.btn_clear_all)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("ToolbarIconBtn")
        self.btn_refresh.setToolTip(self._t("立即刷新"))
        refresh_icon = load_qt_icon([ui_icon_path(action_icon_file("refresh"))])
        if refresh_icon is not None:
            self.btn_refresh.setIcon(refresh_icon)
            self.btn_refresh.setIconSize(QSize(24, 24))
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        path_layout.addWidget(self.btn_refresh)
        table_layout.addWidget(path_row)

        self.table = SnapshotActionTable(
            headers=["视频标题", "平台", "状态", "操作"],
            columns=["title", "platform", "status"],
            actions={"delete": ""},
            icon_columns={"platform", "status"},
            title_columns={"title"},
            row_height=self.ROW_HEIGHT,
        )
        self.table.action_requested.connect(self._on_table_action)
        table_layout.addWidget(self.table, 1)

        self.pagination_footer = PaginationFooter(
            self.PAGE_SIZE_OPTIONS,
            default_page_size=self._page_size,
            combo_min_width=82,
            combo_max_width=112,
        )
        self.total_label = self.pagination_footer.total_label
        self.btn_prev = self.pagination_footer.btn_prev
        self.btn_next = self.pagination_footer.btn_next
        self.page_label = self.pagination_footer.page_label
        self.page_size_combo = self.pagination_footer.page_size_combo
        table_layout.addWidget(self.pagination_footer)

        self.table_island.add_widget(table_host, stretch=1)

        self.activity_island = IslandCard(object_name="ActivityIsland")
        self.activity_island.content_layout.setContentsMargins(12, 10, 12, 10)
        self.event_title = QLabel(self._t("任务动态（最近 3 条）"))
        self.event_title.setObjectName("MutedLabel")
        self.event_body = QLabel()
        self.event_body.setObjectName("EventFeedBody")
        self.event_body.setWordWrap(True)
        self.event_body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.event_body.setMinimumHeight(54)
        self.activity_island.add_widget(self.event_title)
        self.activity_island.add_widget(self.event_body)

        self.root_layout.addWidget(self.table_island, stretch=1)
        self.root_layout.addWidget(self.activity_island)

        self.pagination_footer.page_requested.connect(lambda delta: self._set_page(self._page + delta))
        self.pagination_footer.page_size_changed.connect(self._on_page_size_changed)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.path_prefix_label.setText(self._t("保存至:"))
        self.btn_clear_all.setToolTip(self._t("删除所有"))
        self.btn_refresh.setToolTip(self._t("立即刷新"))
        self.event_title.setText(self._t("任务动态（最近 3 条）"))
        self.pagination_footer.set_language(normalized)
        if hasattr(self.table, "table_model"):
            self.table.table_model.set_language(normalized)
        self._events_signature = None
        self._render_recent_events()

    def _t(self, text: object) -> str:
        return tr(str(text or ""), self._language)

    @property
    def event_layout(self):
        """供既有调用方继续使用的兼容别名。"""
        return self.activity_island.content_layout

    def prepare_force_refresh(self) -> None:
        self._events_signature = None
        self.table.force_refresh()

    def render(self, snapshot: dict) -> None:
        items = snapshot.get("queue_items") or []
        path_text = str((snapshot.get("settings_snapshot") or {}).get("基础设置", {}).get("download_directory", ""))
        if path_text != self._path_text:
            self._path_text = path_text
            self.path_label.setText(path_text)
        selected_id = self.table.selected_id()
        self._submit_page_request(items, selected_id=selected_id or "", selected_id_moves_page=True)

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        if item_id not in self._id_order and item_id != self.table.selected_id():
            return False
        self._submit_page_request(self.items, selected_id=item_id, selected_id_moves_page=True)
        return self.table.select_id(item_id) or item_id in self._id_order

    def _on_refresh_clicked(self) -> None:
        self.prepare_force_refresh()
        self.refresh_requested.emit()

    def _on_clear_all_clicked(self) -> None:
        self.clear_all_requested.emit()

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "delete":
            self.delete_requested.emit(item_id)

    def _submit_page_request(self, items: object, *, selected_id: str = "", selected_id_moves_page: bool = True) -> None:
        self._page_sequence += 1
        source_items = items if isinstance(items, list | tuple) else ()
        request = ListPageRequest(
            sequence=self._page_sequence,
            items=source_items,
            page=self._page,
            page_size=self._page_size,
            selected_id=selected_id,
            recent_count=3,
            selected_id_moves_page=selected_id_moves_page,
        )
        worker = self._page_worker
        if worker is None:
            worker = ListPageWorker(self._page_result_ready.emit)
            self._page_worker = worker
        worker.submit(request)

    def _apply_page_result(self, result: object) -> None:
        if not isinstance(result, ListPageResult) or result.sequence != self._page_sequence:
            return
        self.items = result.items
        self._id_order = result.id_order
        self._page = result.current_page
        self.table.setUpdatesEnabled(False)
        try:
            self.table.set_rows(result.page_items)
            if result.selected_id:
                self.table.select_id(result.selected_id)
        finally:
            self.table.setUpdatesEnabled(True)
        self.pagination_footer.sync(
            total_items=result.total_count,
            current_page=self._page,
            total_pages=result.total_pages,
            page_size=self._page_size,
        )
        self._render_recent_events(result.recent_items)

    def _set_page(self, page: int) -> None:
        self._page = int(page or 1)
        selected_id = self.table.selected_id()
        self._submit_page_request(self.items, selected_id=selected_id or "", selected_id_moves_page=False)

    def _on_page_size_changed(self, page_size: int | None = None) -> None:
        self._page_size = int(page_size or self.page_size_combo.currentData() or 20)
        self._page = 1
        self._submit_page_request(self.items)

    def _fit_page_size_combo_width(self) -> None:
        self.pagination_footer.fit_page_size_combo_width()

    def _render_recent_events(self, recent_items: list[dict] | None = None) -> None:
        recent = recent_items if recent_items is not None else self.items[-3:]
        signature = tuple((item.get("id", ""), item.get("status", ""), item.get("title", "")) for item in recent)
        if signature == self._events_signature:
            return
        self._events_signature = signature
        if not recent:
            self.event_body.setText(self._t("暂无队列任务"))
            return
        lines = [f"{self._t(item.get('status', '待下载'))}: {item.get('title', '')}" for item in reversed(recent)]
        self.event_body.setText("\n".join(lines))

    def _shutdown_page_worker(self) -> None:
        worker = self._page_worker
        self._page_worker = None
        if worker is not None:
            worker.shutdown()

    def deleteLater(self) -> None:
        self._shutdown_page_worker()
        super().deleteLater()
