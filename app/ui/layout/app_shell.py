from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.combo_popup import fit_combo_width_to_contents, refresh_themed_combo_boxes
from app.ui.layout.island import IslandCard
from app.ui.localization import is_translation_of, normalize_language, source_text_for_translation, tr
from app.ui.layout.sidebar import SidebarWidget
from app.ui.layout.status_bar import StatusBarWidget
from app.ui.layout.top_bar import TopBarWidget
from app.ui.styles import build_palette, polish_data_views
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
    completed_metadata_detected = pyqtSignal(str, dict)
    file_association_requested = pyqtSignal(bool, bool)
    setting_changed = pyqtSignal(str, str, object)
    platform_settings_visible = pyqtSignal()
    refresh_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()
    active_options_changed = pyqtSignal(dict)
    log_action_requested = pyqtSignal(str)
    update_check_requested = pyqtSignal(str)

    def __init__(self, *, is_dark_theme: bool, style_provider) -> None:
        super().__init__()
        self.setObjectName("AppShell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.is_dark_theme = bool(is_dark_theme)
        self.current_page_id = "queue"
        self._last_snapshot: dict | None = None
        self._language = "zh-CN"
        self._translation_dirty_pages: set[str] = set()
        self._top_quantity_signature: tuple | None = None
        self.top_bar = TopBarWidget(is_dark_theme)
        self.sidebar = SidebarWidget()
        self.status_bar = StatusBarWidget(is_dark=is_dark_theme)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        self.stack.setMinimumHeight(0)
        self.stack.setMinimumWidth(0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

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
            page.setMinimumHeight(0)
            page.setMinimumWidth(0)
            page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
            self.stack.addWidget(page)

        self.control_island = IslandCard(object_name="ControlIsland")
        self.control_island.content_layout.setContentsMargins(14, 10, 14, 10)
        self.control_island.add_widget(self.top_bar)

        self.status_island = IslandCard(object_name="StatusIsland")
        self.status_island.content_layout.setContentsMargins(8, 0, 8, 0)
        self.status_island.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status_island.add_widget(self.status_bar)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
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
        self.is_dark_theme = bool(is_dark)
        self._close_combo_popups(self)
        palette = build_palette(is_dark)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.stack.setPalette(palette)
        self.stack.setAutoFillBackground(True)
        self.top_bar.set_theme_icon(is_dark)
        self.sidebar.refresh_theme(is_dark)
        self.status_bar.set_theme(is_dark)
        polish_data_views(self, is_dark)
        refresh_themed_combo_boxes(self)
        for page in self.pages.values():
            refresh_style = getattr(page, "_apply_settings_page_style", None)
            if callable(refresh_style):
                refresh_style()
            refresh_theme = getattr(page, "_refresh_theme_widgets", None)
            if callable(refresh_theme):
                refresh_theme()

    def apply_playback_settings(self, settings: dict) -> None:
        completed = self.pages.get("completed")
        media_panel = getattr(completed, "media_panel", None)
        apply_settings = getattr(media_panel, "apply_playback_settings", None)
        if callable(apply_settings):
            apply_settings(settings)

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
        completed.metadata_detected.connect(self.completed_metadata_detected.emit)
        failed = self.pages["failed"]
        failed.retry_requested.connect(self.retry_requested.emit)
        failed.copy_diagnostics_requested.connect(self.copy_diagnostics_requested.emit)
        failed.delete_requested.connect(self.delete_requested.emit)
        toolbox = self.pages["toolbox"]
        toolbox.tool_requested.connect(self.tool_requested.emit)
        settings = self.pages["settings"]
        settings.file_association_requested.connect(self.file_association_requested.emit)
        settings.setting_changed.connect(self.setting_changed.emit)
        settings.platform_settings_visible.connect(self.platform_settings_visible.emit)
        logs = self.pages["logs"]
        logs.log_action_requested.connect(self.log_action_requested.emit)
        self.status_bar.update_check_requested.connect(self.update_check_requested.emit)

    def show_page(self, page_id: str, *, emit_change: bool = True, render_page: bool = True) -> None:
        page = self.pages.get(page_id)
        if page is None:
            return
        self._close_combo_popups(self)
        already_current = self.current_page_id == page_id and self.stack.currentWidget() is page
        if already_current:
            self.sidebar.set_active(page_id)
            if render_page and page_id in self._translation_dirty_pages:
                self._render_page(page_id)
                self._translation_dirty_pages.discard(page_id)
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
        language_changed = self.apply_language(self._language_from_snapshot(snapshot))

        page_needs_render = full_refresh or self._page_needs_render(self.current_page_id, changed_sections)
        if language_changed and self.current_page_id == "settings":
            page_needs_render = True

        if page_needs_render:
            self._render_page(self.current_page_id)

        if full_refresh or "settings_snapshot" in changed_sections:
            self._sync_top_quantity_from_settings(snapshot.get("settings_snapshot") or {})

        if full_refresh or "app_status" in changed_sections:
            self.status_bar.render(snapshot.get("app_status") or {})

        count_sections = set(self._PAGE_SECTION_KEYS.values())
        if full_refresh or "app_status" in changed_sections or changed_sections & count_sections:
            counts = self._counts_from_snapshot(snapshot)
            if full_refresh or "app_status" in changed_sections:
                self.sidebar.set_counts(counts)
            else:
                keys = {
                    page_id
                    for page_id, section in self._PAGE_SECTION_KEYS.items()
                    if section in changed_sections
                }
                self.sidebar.update_counts({page_id: counts[page_id] for page_id in keys})

    def _counts_from_snapshot(self, snapshot: dict) -> dict[str, int]:
        status = snapshot.get("app_status") or {}

        def count_for(status_key: str, section_key: str) -> int:
            if isinstance(status, dict) and status_key in status:
                try:
                    return int(status.get(status_key) or 0)
                except (TypeError, ValueError):
                    return 0
            return len(snapshot.get(section_key) or [])

        return {
            "queue": count_for("queue_count", "queue_items"),
            "active": count_for("active_count", "active_downloads"),
            "completed": count_for("completed_count", "completed_items"),
            "failed": count_for("failed_count", "failed_items"),
        }

    def _sync_top_quantity_from_settings(self, settings_snapshot: dict) -> None:
        rows = settings_snapshot.get("平台设置") if isinstance(settings_snapshot, dict) else None
        if not isinstance(rows, list):
            return
        platform_id = str(self.sidebar.combo_source.currentData() or "")
        if not platform_id:
            return
        row = next((item for item in rows if str(item.get("id") or "") == platform_id), None)
        if not isinstance(row, dict):
            return
        key = str(row.get("count_config_key") or "")
        if key not in {"max_items", "max_pages", "search_max_pages"}:
            return
        count_unit = str(row.get("count_unit") or ("pages" if key != "max_items" else "videos"))
        try:
            value = int(row.get("default_count") or (1 if key != "max_items" else 20))
        except (TypeError, ValueError):
            value = 1 if key != "max_items" else 20
        options = list(row.get("count_options") or [])
        signature = (
            platform_id,
            key,
            count_unit,
            value,
            tuple(
                (
                    str(option.get("value") if isinstance(option, dict) else option),
                    str(option.get("label") if isinstance(option, dict) else option),
                )
                for option in options
            ),
        )
        if signature == self._top_quantity_signature:
            return
        self._top_quantity_signature = signature
        defaults = {key: value}
        self.top_bar.configure_for_platform(
            platform_id,
            defaults,
            count_options=options,
            count_unit=count_unit,
        )

    def _page_needs_render(self, page_id: str, changed_sections: set[str] | None) -> bool:
        if changed_sections is None:
            return True
        if page_id == "logs":
            return "log_items" in changed_sections
        if page_id == "active" and {"settings_snapshot", "download_options"} & changed_sections:
            return True
        if page_id == "settings" and {"settings_snapshot", "settings_contract"} & changed_sections:
            return True
        section = self._PAGE_SECTION_KEYS.get(page_id)
        return bool(section and section in changed_sections)

    @staticmethod
    def _language_from_snapshot(snapshot: dict) -> str:
        appearance = (snapshot.get("settings_snapshot") or {}).get("外观设置") or {}
        return normalize_language(appearance.get("language"))

    def apply_language(self, language: str | None) -> bool:
        normalized = normalize_language(language)
        changed = normalized != self._language
        if not changed:
            return False
        self._close_combo_popups(self)
        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            self._language = normalized
            self.top_bar.set_language(normalized)
            self.sidebar.set_language(normalized)
            self.status_bar.set_language(normalized)
            self._translation_dirty_pages = set(self.pages)
            self._translation_dirty_pages.discard("settings")
            self._translation_dirty_pages.discard(self.current_page_id)
            self._translate_page(self.current_page_id)
        finally:
            self.setUpdatesEnabled(updates_enabled)
            if updates_enabled:
                self.update()
        return changed

    def _render_page(self, page_id: str) -> None:
        snapshot = self._last_snapshot
        if snapshot is None:
            return
        page = self.pages.get(page_id)
        render = getattr(page, "render", None)
        if callable(render):
            render(snapshot)
        should_translate = page_id in self._translation_dirty_pages
        consume_translation_dirty = getattr(page, "consume_translation_dirty", None)
        if callable(consume_translation_dirty):
            should_translate = bool(consume_translation_dirty()) or should_translate
        if should_translate:
            self._translate_page(page_id)
            self._translation_dirty_pages.discard(page_id)

    def _translate_page(self, page_id: str) -> None:
        if page_id == "settings":
            return
        page = self.pages.get(page_id)
        if page is None:
            return
        self._apply_language_to_widget_tree(page, self._language)
        for label in self._safe_find_children(page, QLabel):
            try:
                if label.property("i18nSkipText") != "true":
                    self._translate_text_widget(label, label.text, label.setText)
                self._translate_tooltip(label)
            except RuntimeError:
                continue
        for button in self._safe_find_children(page, QAbstractButton):
            try:
                if button.property("i18nSkipText") != "true" and button.text():
                    self._translate_text_widget(button, button.text, button.setText)
                self._translate_tooltip(button)
            except RuntimeError:
                continue
        for line_edit in self._safe_find_children(page, QLineEdit):
            try:
                self._translate_placeholder(line_edit)
                self._translate_tooltip(line_edit)
            except RuntimeError:
                continue
        for combo in self._safe_find_children(page, QComboBox):
            try:
                self._translate_combo(combo)
                self._translate_tooltip(combo)
            except RuntimeError:
                continue
        for table in self._safe_find_children(page, QTableWidget):
            try:
                self._translate_table_headers(table)
            except RuntimeError:
                continue
        for table in self._safe_find_children(page, QTableView):
            if not isinstance(table, QTableWidget):
                try:
                    self._translate_table_view_headers(table)
                except RuntimeError:
                    continue

    def _apply_language_to_widget_tree(self, root: QWidget, language: str) -> None:
        seen: set[int] = set()
        for widget in (root, *self._safe_find_children(root, QWidget)):
            if not self._qt_widget_alive(widget):
                continue
            marker = id(widget)
            if marker in seen:
                continue
            seen.add(marker)
            setter = getattr(widget, "set_language", None)
            if callable(setter):
                try:
                    setter(language)
                except RuntimeError:
                    continue

    def _safe_find_children(self, root: QWidget, widget_type):
        if not self._qt_widget_alive(root):
            return []
        try:
            return [child for child in root.findChildren(widget_type) if self._qt_widget_alive(child)]
        except RuntimeError:
            return []

    @staticmethod
    def _qt_widget_alive(widget: QWidget | None) -> bool:
        if widget is None:
            return False
        try:
            return not sip.isdeleted(widget)
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _close_combo_popups(self, root: QWidget | None) -> None:
        if root is None:
            return
        for combo in self._safe_find_children(root, QComboBox):
            try:
                view = combo.view()
                if view is not None and (view.isVisible() or view.window().isVisible()):
                    combo.hidePopup()
                combo.setProperty("popupOpen", "false")
            except RuntimeError:
                continue
        for popup in QApplication.topLevelWidgets():
            try:
                if popup is self.window():
                    continue
                if popup.objectName() == "PolishedComboPopupWindow":
                    popup.hide()
                    popup.setProperty("popupOpen", "false")
            except RuntimeError:
                continue

    def _translate_text_widget(self, widget: QWidget, getter, setter) -> None:
        text = str(getter() or "")
        if not text:
            return
        source = widget.property("_i18n_source_text")
        if source is None:
            source = source_text_for_translation(text)
            widget.setProperty("_i18n_source_text", source)
        elif not is_translation_of(text, str(source)):
            source = source_text_for_translation(text)
            widget.setProperty("_i18n_source_text", source)
        translated = tr(str(source), self._language)
        if translated != text:
            setter(translated)

    def _translate_tooltip(self, widget: QWidget) -> None:
        text = str(widget.toolTip() or "")
        if not text:
            return
        source = widget.property("_i18n_source_tooltip")
        if source is None:
            source = source_text_for_translation(text)
            widget.setProperty("_i18n_source_tooltip", source)
        elif not is_translation_of(text, str(source)):
            source = source_text_for_translation(text)
            widget.setProperty("_i18n_source_tooltip", source)
        translated = tr(str(source), self._language)
        if translated != text:
            widget.setToolTip(translated)

    def _translate_placeholder(self, line_edit: QLineEdit) -> None:
        text = str(line_edit.placeholderText() or "")
        if not text:
            return
        source = line_edit.property("_i18n_source_placeholder")
        if source is None:
            source = source_text_for_translation(text)
            line_edit.setProperty("_i18n_source_placeholder", source)
        elif not is_translation_of(text, str(source)):
            source = source_text_for_translation(text)
            line_edit.setProperty("_i18n_source_placeholder", source)
        translated = tr(str(source), self._language)
        if translated != text:
            line_edit.setPlaceholderText(translated)

    def _translate_combo(self, combo: QComboBox) -> None:
        try:
            view = combo.view()
            if view is not None and (view.isVisible() or view.window().isVisible()):
                combo.hidePopup()
                combo.setProperty("popupOpen", "false")
        except RuntimeError:
            return
        source_role = int(Qt.ItemDataRole.UserRole) + 77
        try:
            blocked = combo.blockSignals(True)
        except RuntimeError:
            return
        try:
            for index in range(combo.count()):
                source = combo.itemData(index, source_role)
                if source is None:
                    source = source_text_for_translation(combo.itemText(index))
                    combo.setItemData(index, source, source_role)
                elif not is_translation_of(combo.itemText(index), str(source)):
                    source = source_text_for_translation(combo.itemText(index))
                    combo.setItemData(index, source, source_role)
                translated = tr(str(source), self._language)
                if translated != combo.itemText(index):
                    combo.setItemText(index, translated)
        except RuntimeError:
            return
        finally:
            try:
                combo.blockSignals(blocked)
            except RuntimeError:
                return
        padding = combo.property("contentWidthPadding")
        if padding is not None:
            try:
                extra = int(padding)
                min_width = int(combo.property("contentMinWidth") or 0)
                max_width = int(combo.property("contentMaxWidth") or 16777215)
            except (TypeError, ValueError):
                return
            if max_width > 0:
                try:
                    fit_combo_width_to_contents(
                        combo,
                        min_width=min_width,
                        max_width=max_width,
                        horizontal_padding=extra,
                    )
                    refresh_themed_combo_boxes(combo)
                except RuntimeError:
                    return

    def _translate_table_headers(self, table: QTableWidget) -> None:
        source_role = int(Qt.ItemDataRole.UserRole) + 78
        for index in range(table.columnCount()):
            item = table.horizontalHeaderItem(index)
            if item is None:
                continue
            source = item.data(source_role)
            if source is None:
                source = source_text_for_translation(item.text())
                item.setData(source_role, source)
            elif not is_translation_of(item.text(), str(source)):
                source = source_text_for_translation(item.text())
                item.setData(source_role, source)
            item.setText(tr(str(source), self._language))

    def _translate_table_view_headers(self, table: QTableView) -> None:
        model = table.model()
        if model is None:
            return
        column_count = model.columnCount()
        current = [
            str(model.headerData(index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or "")
            for index in range(column_count)
        ]
        source = table.property("_i18n_source_headers")
        if not isinstance(source, list) or len(source) != column_count:
            source = [source_text_for_translation(value) for value in current]
            table.setProperty("_i18n_source_headers", source)
        else:
            translated_source = [tr(str(value), self._language) for value in source]
            if current != translated_source and not all(
                is_translation_of(text, str(source_value))
                for text, source_value in zip(current, source)
            ):
                source = [source_text_for_translation(value) for value in current]
                table.setProperty("_i18n_source_headers", source)
        translated = [tr(str(value), self._language) for value in source]
        set_headers = getattr(model, "set_headers", None)
        if callable(set_headers):
            set_headers(translated)
        set_language = getattr(model, "set_language", None)
        if callable(set_language):
            set_language(self._language)

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
