from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from app.ui.layout.island import IslandCard
from app.ui.layout.sidebar import SidebarWidget
from app.ui.layout.status_bar import StatusBarWidget
from app.ui.layout.top_bar import TopBarWidget
from app.ui.styles import polish_data_views
from app.ui.pages.active_downloads_page import ActiveDownloadsPage
from app.ui.pages.completed_page import CompletedPage
from app.ui.pages.download_queue_page import DownloadQueuePage
from app.ui.pages.failed_page import FailedPage
from app.ui.pages.log_center_page import LogCenterPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.toolbox_page import ToolboxPage

class AppShell(QWidget):
    """Top-level GUI shell for the unified 7-page structure."""

    page_changed = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    play_requested = pyqtSignal(str)
    open_directory_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    copy_diagnostics_requested = pyqtSignal(str)
    tool_requested = pyqtSignal(str)
    file_association_requested = pyqtSignal(bool, bool)
    refresh_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()
    active_options_changed = pyqtSignal(dict)

    def __init__(self, *, is_dark_theme: bool, style_provider) -> None:
        super().__init__()
        self.setObjectName("AppShell")
        self.current_page_id = "queue"
        self._last_snapshot: dict | None = None
        self.top_bar = TopBarWidget(is_dark_theme)
        self.sidebar = SidebarWidget()
        self.status_bar = StatusBarWidget(is_dark=is_dark_theme)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")

        self.pages: dict[str, QWidget] = {
            "queue": DownloadQueuePage(),
            "active": ActiveDownloadsPage(),
            "completed": CompletedPage(style_provider),
            "failed": FailedPage(),
            "logs": LogCenterPage(),
            "settings": SettingsPage(),
            "toolbox": ToolboxPage(),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.control_island = IslandCard(object_name="ControlIsland")
        self.control_island.content_layout.setContentsMargins(14, 10, 14, 10)
        self.control_island.add_widget(self.top_bar)

        self.status_island = IslandCard(object_name="StatusIsland")
        self.status_island.content_layout.setContentsMargins(8, 0, 8, 0)
        self.status_island.add_widget(self.status_bar)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self.sidebar)

        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        right_column.addWidget(self.control_island)
        right_column.addWidget(self.stack, stretch=1)
        body.addLayout(right_column, stretch=1)

        root.addLayout(body, stretch=1)
        root.addWidget(self.status_island)

        self.sidebar.page_selected.connect(self.show_page)
        self._connect_page_signals()
        self.apply_theme(is_dark_theme)

    def apply_theme(self, is_dark: bool) -> None:
        self.sidebar.refresh_theme(is_dark)
        self.status_bar.set_theme(is_dark)
        polish_data_views(self, is_dark)

    def set_crawl_running_state(self, is_running: bool, plugin_widget=None) -> None:
        self.top_bar.set_crawl_running_state(
            is_running,
            plugin_widget,
            combo_source=self.sidebar.combo_source,
        )

    def _connect_page_signals(self) -> None:
        queue = self.pages["queue"]
        queue.delete_requested.connect(self.delete_requested.emit)
        queue.refresh_requested.connect(self.refresh_requested.emit)
        queue.clear_all_requested.connect(self.clear_all_requested.emit)
        active = self.pages["active"]
        active.delete_requested.connect(self.delete_requested.emit)
        active.options_changed.connect(self.active_options_changed.emit)
        completed = self.pages["completed"]
        completed.play_requested.connect(self.play_requested.emit)
        completed.open_directory_requested.connect(self.open_directory_requested.emit)
        completed.delete_requested.connect(self.delete_requested.emit)
        failed = self.pages["failed"]
        failed.retry_requested.connect(self.retry_requested.emit)
        failed.copy_diagnostics_requested.connect(self.copy_diagnostics_requested.emit)
        failed.delete_requested.connect(self.delete_requested.emit)
        toolbox = self.pages["toolbox"]
        toolbox.tool_requested.connect(self.tool_requested.emit)
        settings = self.pages["settings"]
        settings.file_association_requested.connect(self.file_association_requested.emit)

    def show_page(self, page_id: str, *, emit_change: bool = True, render_page: bool = True) -> None:
        page = self.pages.get(page_id)
        if page is None:
            return
        if self.current_page_id == "completed" and page_id != "completed":
            self.release_media()
        self.current_page_id = page_id
        self.stack.setCurrentWidget(page)
        self.sidebar.set_active(page_id)
        if emit_change:
            self.page_changed.emit(page_id)
        if render_page:
            self._render_page(page_id)

    _PAGE_SECTION_KEYS = {
        "queue": "queue_items",
        "active": "active_downloads",
        "completed": "completed_items",
        "failed": "failed_items",
    }

    def render(self, snapshot: dict, *, changed_sections: set[str] | None = None) -> None:
        self._last_snapshot = snapshot
        full_refresh = changed_sections is None

        if full_refresh or self._page_needs_render(self.current_page_id, changed_sections):
            self._render_page(self.current_page_id)

        if full_refresh or "app_status" in changed_sections:
            self.status_bar.render(snapshot.get("app_status") or {})

        count_sections = set(self._PAGE_SECTION_KEYS.values())
        if full_refresh or changed_sections & count_sections:
            counts = {
                "queue": len(snapshot.get("queue_items") or []),
                "active": len(snapshot.get("active_downloads") or []),
                "completed": len(snapshot.get("completed_items") or []),
                "failed": len(snapshot.get("failed_items") or []),
            }
            if full_refresh:
                self.sidebar.set_counts(counts)
            else:
                keys = {
                    page_id
                    for page_id, section in self._PAGE_SECTION_KEYS.items()
                    if section in changed_sections
                }
                self.sidebar.update_counts({page_id: counts[page_id] for page_id in keys})

    def _page_needs_render(self, page_id: str, changed_sections: set[str] | None) -> bool:
        if changed_sections is None:
            return True
        if page_id == "logs":
            return "log_items" in changed_sections
        section = self._PAGE_SECTION_KEYS.get(page_id)
        return bool(section and section in changed_sections)

    def _render_page(self, page_id: str) -> None:
        snapshot = self._last_snapshot
        if snapshot is None:
            return
        page = self.pages.get(page_id)
        render = getattr(page, "render", None)
        if callable(render):
            render(snapshot)

    def selected_video_id(self) -> str | None:
        page = self.pages.get(self.current_page_id)
        getter = getattr(page, "selected_id", None)
        if callable(getter):
            selected = getter()
            if selected:
                return selected
        items = self._items_for_page(self.current_page_id)
        return items[0].get("id") if items else None

    def row_for_video_id(self, video_id: str) -> int:
        for page_id in ("queue", "active", "completed", "failed"):
            for row, item in enumerate(self._items_for_page(page_id)):
                if item.get("id") == video_id:
                    return row
        return -1

    def completed_id_order(self) -> list[str]:
        return [item.get("id", "") for item in self._items_for_page("completed") if item.get("id")]

    def select_video_id(self, video_id: str) -> bool:
        for page_id in ("completed", "queue", "active", "failed"):
            if not any(item.get("id") == video_id for item in self._items_for_page(page_id)):
                continue
            page = self.pages[page_id]
            if self.current_page_id != page_id:
                self.show_page(page_id)
            selector = getattr(page, "select_id", None)
            if callable(selector) and selector(video_id):
                return True
            row_for_id = getattr(page, "row_for_id", None)
            table = getattr(page, "table", None)
            if callable(row_for_id) and table is not None:
                row = row_for_id(video_id)
                if row >= 0:
                    table.selectRow(row)
                    return True
        return False

    def _items_for_page(self, page_id: str) -> list[dict]:
        snapshot = self._last_snapshot or {}
        return list(
            {
                "queue": snapshot.get("queue_items") or [],
                "active": snapshot.get("active_downloads") or [],
                "completed": snapshot.get("completed_items") or [],
                "failed": snapshot.get("failed_items") or [],
            }.get(page_id, [])
        )

    def show_image(self, image_path: str) -> None:
        self.show_page("completed")
        self.pages["completed"].show_image(image_path)

    def play_video(self, video_path: str) -> None:
        self.show_page("completed")
        self.pages["completed"].play_video(video_path)

    def release_media(self) -> None:
        for page in self.pages.values():
            release = getattr(page, "release_media", None)
            if callable(release):
                release()

    def cleanup_media(self) -> None:
        """Release media players; only pages that define ``cleanup`` are torn down."""
        for page in self.pages.values():
            cleanup = getattr(page, "cleanup", None)
            if callable(cleanup):
                cleanup()
