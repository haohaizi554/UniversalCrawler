from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.services.icon_registry import action_icon_file, ui_icon_path
from app.ui.components.combo_popup import ThemedComboBox, fit_combo_width_to_contents
from app.ui.layout.island import IslandCard
from app.ui.pages.common import PageFrame, SnapshotActionTable
from app.utils.qt_runtime import load_qt_icon

class DownloadQueuePage(PageFrame):
    delete_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()

    PAGE_SIZE_OPTIONS = (20, 50, 100)
    ROW_HEIGHT = 52

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []
        self._path_text = ""
        self._events_signature: tuple | None = None
        self._page = 1
        self._page_size = 20

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
        path_layout.addWidget(QLabel("保存至:"))
        self.path_label = QLabel("")
        self.path_label.setObjectName("PathLabel")
        path_layout.addWidget(self.path_label, 1)
        self.btn_clear_all = QPushButton()
        self.btn_clear_all.setObjectName("ToolbarIconBtn")
        self.btn_clear_all.setToolTip("删除所有")
        clear_icon = load_qt_icon([ui_icon_path(action_icon_file("clear_all"))])
        if clear_icon is not None:
            self.btn_clear_all.setIcon(clear_icon)
            self.btn_clear_all.setIconSize(QSize(24, 24))
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        path_layout.addWidget(self.btn_clear_all)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("ToolbarIconBtn")
        self.btn_refresh.setToolTip("立即刷新")
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

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)
        self.total_label = QLabel("共 0 项")
        self.total_label.setObjectName("MutedLabel")
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch(1)
        self.btn_prev = QPushButton("‹")
        self.btn_prev.setObjectName("PaginationButton")
        self.btn_prev.setToolTip("上一页")
        self.btn_prev.setFixedSize(38, 34)
        self.btn_next = QPushButton("›")
        self.btn_next.setObjectName("PaginationButton")
        self.btn_next.setToolTip("下一页")
        self.btn_next.setFixedSize(38, 34)
        self.page_label = QLabel("1 / 1 页")
        self.page_label.setObjectName("MutedLabel")
        self.page_size_combo = ThemedComboBox(row_height=32)
        self.page_size_combo.setFixedHeight(34)
        for option in self.PAGE_SIZE_OPTIONS:
            self.page_size_combo.addItem(f"{option} 条/页", option)
        self._fit_page_size_combo_width()
        footer_layout.addWidget(self.btn_prev)
        footer_layout.addWidget(self.page_label)
        footer_layout.addWidget(self.btn_next)
        footer_layout.addWidget(self.page_size_combo)
        table_layout.addWidget(footer)

        self.table_island.add_widget(table_host, stretch=1)

        self.activity_island = IslandCard(object_name="ActivityIsland")
        self.activity_island.content_layout.setContentsMargins(12, 10, 12, 10)
        self.event_title = QLabel("任务动态（最近 3 条）")
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

        self.btn_prev.clicked.connect(lambda: self._set_page(self._page - 1))
        self.btn_next.clicked.connect(lambda: self._set_page(self._page + 1))
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

    @property
    def event_layout(self):
        """Backward-compatible alias for tests and legacy callers."""
        return self.activity_island.content_layout

    def prepare_force_refresh(self) -> None:
        self._events_signature = None
        self.table.force_refresh()

    def render(self, snapshot: dict) -> None:
        self.items = list(snapshot.get("queue_items") or [])
        path_text = str((snapshot.get("settings_snapshot") or {}).get("基础设置", {}).get("download_directory", ""))
        if path_text != self._path_text:
            self._path_text = path_text
            self.path_label.setText(path_text)
        selected_id = self.table.selected_id()
        if selected_id:
            self._page = self._page_for_item(selected_id) or self._page
        self._render_current_page(selected_id=selected_id)
        self._render_recent_events()

    def selected_id(self) -> str | None:
        return self.table.selected_id()

    def row_for_id(self, item_id: str) -> int:
        return self.table.row_for_id(item_id)

    def select_id(self, item_id: str) -> bool:
        page = self._page_for_item(item_id)
        if page is None:
            return False
        self._page = page
        self._render_current_page(selected_id=item_id)
        return self.table.select_id(item_id)

    def _on_refresh_clicked(self) -> None:
        self.prepare_force_refresh()
        self.refresh_requested.emit()

    def _on_clear_all_clicked(self) -> None:
        self.clear_all_requested.emit()

    def _on_table_action(self, action: str, item_id: str) -> None:
        if action == "delete":
            self.delete_requested.emit(item_id)

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

    def _on_page_size_changed(self) -> None:
        self._page_size = int(self.page_size_combo.currentData() or 20)
        self._page = 1
        self._render_current_page()

    def _fit_page_size_combo_width(self) -> None:
        fit_combo_width_to_contents(
            self.page_size_combo,
            min_width=82,
            max_width=112,
            horizontal_padding=16,
        )

    def _total_pages(self) -> int:
        return max(1, (len(self.items) + self._page_size - 1) // self._page_size)

    def _page_for_item(self, item_id: str) -> int | None:
        for index, item in enumerate(self.items):
            if item.get("id") == item_id:
                return index // self._page_size + 1
        return None

    def _render_recent_events(self) -> None:
        recent = self.items[-3:]
        signature = tuple((item.get("id", ""), item.get("status", ""), item.get("title", "")) for item in recent)
        if signature == self._events_signature:
            return
        self._events_signature = signature
        if not recent:
            self.event_body.setText("暂无队列任务")
            return
        lines = [f"{item.get('status', '待下载')}：{item.get('title', '')}" for item in reversed(recent)]
        self.event_body.setText("\n".join(lines))
