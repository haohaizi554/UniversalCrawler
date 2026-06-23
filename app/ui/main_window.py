"""Main window assembly for the unified 7-page GUI."""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QByteArray, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFileDialog, QDialog, QMainWindow, QApplication

from app.config import cfg, get_platform_runtime_defaults
from app.debug_logger import debug_logger
from app.core.event_bus import EventBus
from app.core.plugin_registry import registry
from app.services.app_state import AppState
from app.services.frontend_state_service import FrontendStateService
from app.ui.connection_registry import ConnectionRegistry
from app.ui.dialogs import FileAssociationDialog
from app.ui.dialogs.selection import SelectionDialog
from app.ui.layout.app_shell import AppShell
from app.ui.plugin_settings import read_plugin_run_options
from app.ui.styles import apply_application_theme, build_palette, polish_data_views
from app.ui.ui_update_scheduler import UiUpdateScheduler
from app.utils.qt_runtime import load_qt_icon
from app.utils.runtime_paths import user_data_root

class MainWindow(QMainWindow):
    """Thin GUI host that forwards user actions and renders frontend snapshots."""

    FRONTEND_REFRESH_INTERVAL_MS = 200
    FRONTEND_REFRESH_MAX_INTERVAL_MS = 750
    FRONTEND_RENDER_WARN_MS = 50
    LOG_REFRESH_DEBOUNCE_MS = 500

    sig_start_crawl = pyqtSignal(str, str, dict)
    sig_stop_crawl = pyqtSignal()
    sig_theme_changed = pyqtSignal(bool)
    sig_change_dir = pyqtSignal()
    sig_play_video = pyqtSignal(str)
    sig_delete_video = pyqtSignal(int, str)
    sig_clear_queue = pyqtSignal()
    sig_open_latest_log = pyqtSignal()
    sig_open_error_summary = pyqtSignal()
    sig_copy_trace_id = pyqtSignal(str)
    sig_register_file_associations = pyqtSignal(bool, bool)
    sig_switch_preview = pyqtSignal(int)
    sig_auto_next_preview = pyqtSignal()

    def __init__(self, *, app_state: AppState | None = None, event_bus: EventBus | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Universal Crawler Pro")
        QApplication.setFont(QFont("Microsoft YaHei UI", 10))
        self.resize(1500, 880)
        self.is_dark_theme = bool(cfg.get("common", "dark_theme", cfg.get("common", "theme", "light") == "dark"))
        self._apply_theme_stylesheet()
        icon = load_qt_icon(["favicon.ico"], fallback_names=["Web.ico"])
        if icon is not None:
            self.setWindowIcon(icon)

        self._save_dir_lock = threading.RLock()
        self.current_save_dir = cfg.get("common", "save_directory") or str(user_data_root())
        self.current_plugin = None
        self.plugin_widget = None
        self.is_fullscreen_mode = False
        self.event_bus = event_bus or EventBus()
        self.app_state = app_state or AppState(event_bus=self.event_bus)
        self._frontend_state_service = FrontendStateService(app_state=self.app_state)
        self._connections = ConnectionRegistry()
        self._frontend_refresh_pending_mock = False
        self._ui_update_scheduler = UiUpdateScheduler(
            interval_ms=self.FRONTEND_REFRESH_INTERVAL_MS,
            on_flush=self._flush_frontend_state,
            parent=self,
        )
        self._app_state_handler = self.event_bus.subscribe("app_state.changed", self._on_app_state_changed)
        self._pending_delete_video_id: str | None = None
        self._title_rename_handler = None
        self._pending_refresh_topics: set[str] = set()
        self._cached_snapshot: dict | None = None
        self._log_refresh_timer = QTimer(self)
        self._log_refresh_timer.setSingleShot(True)
        self._log_refresh_timer.setInterval(self.LOG_REFRESH_DEBOUNCE_MS)
        self._log_refresh_timer.timeout.connect(self._flush_log_refresh)
        self._active_selection_dialog: SelectionDialog | None = None

        self._build_ui()
        self._expose_component_refs()
        self._bind_component_signals()
        self._apply_theme_stylesheet()
        self.load_initial_state()
        self.refresh_frontend_state(mock=True, force=True)

    @property
    def current_save_dir(self) -> str:
        lock = getattr(self, "_save_dir_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._save_dir_lock = lock
        with lock:
            return getattr(self, "_current_save_dir", "")

    @current_save_dir.setter
    def current_save_dir(self, value: str) -> None:
        lock = getattr(self, "_save_dir_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._save_dir_lock = lock
        with lock:
            self._current_save_dir = str(value)

    def _build_ui(self) -> None:
        self.app_shell = AppShell(is_dark_theme=self.is_dark_theme, style_provider=self)
        self.setCentralWidget(self.app_shell)

    def _expose_component_refs(self) -> None:
        self.top_bar = self.app_shell.top_bar
        self.combo_source = self.app_shell.sidebar.combo_source
        self.inp_search = self.top_bar.inp_search
        self.combo_video_count = self.top_bar.combo_video_count
        self.container_dynamic = self.top_bar.container_dynamic
        self.layout_dynamic = self.top_bar.layout_dynamic
        self.btn_start = self.top_bar.btn_start
        self.btn_stop = self.top_bar.btn_stop
        self.btn_dir = self.top_bar.btn_dir
        self.btn_theme = self.top_bar.btn_theme
        self.media_panel = self.app_shell.pages["completed"].media_panel
        self.btn_fullscreen = self.media_panel.btn_fullscreen
        self.btn_prev = self.media_panel.btn_prev
        self.btn_next = self.media_panel.btn_next

    def _bind_component_signals(self) -> None:
        self._connections.connect(self.combo_source.currentIndexChanged, self.on_source_changed)
        self._connections.connect(self.btn_start.clicked, self.on_btn_start_clicked)
        self._connections.connect(self.inp_search.returnPressed, self.on_btn_start_clicked)
        self._connections.connect(self.btn_stop.clicked, lambda: self.sig_stop_crawl.emit())
        self._connections.connect(self.btn_dir.clicked, self.on_btn_dir_clicked)
        self._connections.connect(self.btn_theme.clicked, self.toggle_theme)
        self._connections.connect(self.app_shell.delete_requested, self._emit_delete_for_video)
        self._connections.connect(self.app_shell.play_requested, lambda video_id: self.sig_play_video.emit(video_id))
        self._connections.connect(self.app_shell.open_directory_requested, self._open_item_directory)
        self._connections.connect(self.app_shell.retry_requested, self._retry_failed_item)
        self._connections.connect(self.app_shell.copy_diagnostics_requested, self._copy_item_diagnostics)
        self._connections.connect(self.app_shell.tool_requested, self._run_tool)
        self._connections.connect(self.app_shell.completed_metadata_detected, self._update_completed_metadata)
        self._connections.connect(self.app_shell.file_association_requested, self._register_file_associations_from_frontend)
        self._connections.connect(self.app_shell.page_changed, self._on_page_changed)
        self._connections.connect(self.app_shell.refresh_requested, self._on_queue_refresh_requested)
        self._connections.connect(self.app_shell.clear_all_requested, self._on_clear_queue_requested)
        self._connections.connect(self.app_shell.active_options_changed, self._update_download_options)
        self._connections.connect(self.app_shell.log_action_requested, self._handle_log_action)
        self._connections.connect(self.media_panel.sig_switch_preview, self.sig_switch_preview.emit)
        self._connections.connect(self.media_panel.sig_auto_next_preview, self.sig_auto_next_preview.emit)

    def set_frontend_state_service(self, service: FrontendStateService) -> None:
        new_event_bus = service.app_state.event_bus
        if new_event_bus is not self.event_bus:
            self.event_bus.unsubscribe("app_state.changed", self._app_state_handler)
            self.event_bus = new_event_bus
            self._app_state_handler = self.event_bus.subscribe("app_state.changed", self._on_app_state_changed)
        self._frontend_state_service = service
        self.app_state = service.app_state
        self.refresh_frontend_state(force=True)

    def refresh_frontend_state(self, *, mock: bool = False, force: bool = False, topics: set[str] | None = None) -> None:
        if "app_shell" not in self.__dict__ or "_frontend_state_service" not in self.__dict__:
            return
        if topics:
            pending = self.__dict__.setdefault("_pending_refresh_topics", set())
            pending.update(topics)
        if force:
            self._render_frontend_state(mock=mock, topics=None)
            return
        self._frontend_refresh_pending_mock = bool(self.__dict__.get("_frontend_refresh_pending_mock", False) or mock)
        self._ui_update_scheduler.schedule("frontend")

    def _flush_frontend_state(self, _topics: set[str] | None = None) -> None:
        mock = bool(self.__dict__.get("_frontend_refresh_pending_mock", False))
        self._frontend_refresh_pending_mock = False
        pending = set(self.__dict__.get("_pending_refresh_topics", set()))
        self.__dict__["_pending_refresh_topics"] = set()
        self._render_frontend_state(mock=mock, topics=pending or None)

    def _render_frontend_state(self, *, mock: bool = False, topics: set[str] | None = None) -> None:
        started = time.perf_counter()
        sections = self._sections_for_topics(topics)
        service = self._frontend_state_service
        cached = self.__dict__.get("_cached_snapshot")
        changed_keys: set[str] | None = None

        if (
            not mock
            and sections
            and cached
            and isinstance(service, FrontendStateService)
            and hasattr(service, "get_delta")
        ):
            base_version = int(cached.get("version") or self.__dict__.get("_cached_frontend_version", 0) or 0)
            delta = service.get_delta(base_version, sections=sections)
            snapshot, changed_keys = self._merge_frontend_delta(cached, delta)
            if not changed_keys:
                return
        else:
            snapshot = service.get_snapshot(mock=mock, sections=sections)
            if cached and sections:
                merged = dict(cached)
                merged.update(snapshot)
                snapshot = merged
            changed_keys = set(snapshot.keys()) if sections else None

        self.__dict__["_cached_snapshot"] = snapshot
        self.__dict__["_cached_frontend_version"] = int(snapshot.get("version") or 0)
        self.app_shell.render(snapshot, changed_sections=changed_keys)
        self._record_frontend_render_duration((time.perf_counter() - started) * 1000)

    def _merge_frontend_delta(self, cached: dict, delta: dict) -> tuple[dict, set[str]]:
        changed_sections = set(delta.get("changed_sections") or [])
        sections = delta.get("sections") or {}
        snapshot = dict(cached)
        if isinstance(sections, dict):
            snapshot.update(sections)
        snapshot["version"] = int(delta.get("version") or snapshot.get("version") or 0)
        return snapshot, changed_sections

    def _record_frontend_render_duration(self, duration_ms: float) -> None:
        self.__dict__["_last_frontend_render_ms"] = duration_ms
        if duration_ms <= self.FRONTEND_RENDER_WARN_MS:
            return
        scheduler = self.__dict__.get("_ui_update_scheduler")
        metrics = scheduler.metrics() if hasattr(scheduler, "metrics") else {}
        interval = int(metrics.get("interval_ms") or self.FRONTEND_REFRESH_INTERVAL_MS)
        if hasattr(scheduler, "set_interval_ms") and interval < self.FRONTEND_REFRESH_MAX_INTERVAL_MS:
            scheduler.set_interval_ms(min(self.FRONTEND_REFRESH_MAX_INTERVAL_MS, interval + 50))
        debug_logger.log(
            component="MainWindow",
            action="frontend_render_slow",
            level="WARN",
            message="Frontend render exceeded the interactive budget; refresh cadence was relaxed",
            status_code="FRONTEND_RENDER_SLOW",
            details={"duration_ms": round(duration_ms, 2), "scheduler": metrics},
        )

    def _sections_for_topics(self, topics: set[str] | None) -> frozenset[str] | None:
        if not topics:
            return None
        sections: set[str] = set()
        for topic in topics:
            if topic == "videos.update":
                sections.update({"active_downloads", "app_status"})
            elif topic == "videos.terminal":
                sections.update({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"})
            elif topic == "videos.metadata":
                sections.update({"completed_items", "app_status"})
            elif topic in {"videos.upsert", "videos.remove", "videos.remove_many", "videos.clear", "videos.replace"}:
                sections.update({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"})
            elif topic == "logs.append":
                sections.add("log_items")
            elif topic in {"app.running_state", "page.visibility"}:
                sections.add("app_status")
            elif topic in {"settings.update", "config"}:
                sections.update({"settings_snapshot", "download_options", "app_status"})
            else:
                return None
        if "log_items" in sections:
            sections.add("app_status")
        return frozenset(sections) if sections else None

    def _flush_log_refresh(self) -> None:
        self.__dict__.setdefault("_pending_refresh_topics", set()).add("logs.append")
        self._ui_update_scheduler.schedule("frontend", force=True)

    def _on_app_state_changed(self, payload) -> None:
        topic = ""
        if isinstance(payload, dict):
            topic = str(payload.get("topic") or "")
        if topic == "logs.append":
            if not self._log_refresh_timer.isActive():
                self._log_refresh_timer.start()
            return
        if topic in {"videos.update", "videos.metadata"}:
            refresh_topic = topic
            if topic == "videos.update" and isinstance(payload, dict):
                sections = FrontendStateService._sections_for_recorded_event(topic, payload)
                if sections is not None and "completed_items" in sections:
                    refresh_topic = "videos.terminal"
            self.__dict__.setdefault("_pending_refresh_topics", set()).add(refresh_topic)
            self._ui_update_scheduler.schedule("frontend")
            return
        if topic in {"videos.upsert", "videos.remove", "videos.remove_many", "videos.clear", "videos.replace", "app.running_state"}:
            self.__dict__.setdefault("_pending_refresh_topics", set()).add(topic)
            self.refresh_frontend_state()
            return
        self.refresh_frontend_state()

    def _on_queue_refresh_requested(self) -> None:
        self._frontend_state_service.invalidate_refresh_caches()
        queue_page = self.app_shell.pages.get("queue")
        prepare = getattr(queue_page, "prepare_force_refresh", None)
        if callable(prepare):
            prepare()
        self.refresh_frontend_state(force=True)

    def _on_clear_queue_requested(self) -> None:
        self.sig_clear_queue.emit()

    def _handle_log_action(self, operation: str) -> None:
        if operation == "open_latest":
            self.sig_open_latest_log.emit()
            return
        if operation == "open_error_summary":
            self.sig_open_error_summary.emit()
            return
        result = self._frontend_state_service.handle_action("log_operation", {"operation": operation})
        if operation != "clear":
            self.append_log(result.get("message") or "日志操作完成")
        self.refresh_frontend_state(topics={"logs.append"}, force=True)

    def _on_page_changed(self, page_id: str) -> None:
        self.app_state.set_visible_page(page_id, list(self.app_shell.pages), emit_change=False)

    def bind_video_rename(self, on_rename) -> None:
        # Titles are no longer editable in the queue table.  Keep the hook so the
        # controller can still bind without knowing the presentation changed.
        self._title_rename_handler = on_rename

    def toggle_theme(self) -> None:
        self.is_dark_theme = not self.is_dark_theme
        self._apply_theme_stylesheet()
        cfg.set("common", "dark_theme", self.is_dark_theme)
        cfg.set("common", "theme", "dark" if self.is_dark_theme else "light")
        self.append_log(f"已切换到{'深色' if self.is_dark_theme else '浅色'}主题")
        self.sig_theme_changed.emit(self.is_dark_theme)

    def _apply_theme_stylesheet(self) -> None:
        apply_application_theme(self.is_dark_theme)
        self.setPalette(build_palette(self.is_dark_theme))
        top_bar = self.__dict__.get("top_bar")
        if top_bar is not None:
            top_bar.set_theme_icon(self.is_dark_theme)
        app_shell = self.__dict__.get("app_shell")
        if app_shell is not None:
            app_shell.apply_theme(self.is_dark_theme)
            if "_frontend_state_service" in self.__dict__:
                self.refresh_frontend_state(force=True)

    def toggle_fullscreen_mode(self) -> None:
        if "app_shell" in self.__dict__:
            top_bar = self.app_shell.top_bar
            sidebar = self.app_shell.sidebar
            status_bar = self.app_shell.status_bar
        else:
            top_bar = getattr(self, "top_bar", None)
            sidebar = getattr(self, "left_panel", None)
            status_bar = getattr(self, "log_txt", None)
        if not self.is_fullscreen_mode:
            for widget in (top_bar, sidebar, status_bar):
                if widget is not None:
                    widget.hide()
            self.showFullScreen()
            self.is_fullscreen_mode = True
            self.btn_fullscreen.setText("[ 退出 ]")
            return
        for widget in (top_bar, sidebar, status_bar):
            if widget is not None:
                widget.show()
        self.showNormal()
        self.is_fullscreen_mode = False
        self.btn_fullscreen.setText("[ 全屏 ]")
        state_hex = cfg.get("ui", "window_state")
        if state_hex:
            self.restoreState(QByteArray.fromHex(state_hex.encode()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen_mode:
            self.toggle_fullscreen_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def load_initial_state(self) -> None:
        last_source_id = cfg.get("common", "last_source", "kuaishou")
        index = self.combo_source.findData(last_source_id)
        self.combo_source.setCurrentIndex(index if index != -1 else 0)
        self.on_source_changed(self.combo_source.currentIndex())
        visible_page = self.app_state.get_visible_page()
        if visible_page in self.app_shell.pages:
            self.app_shell.show_page(visible_page, emit_change=False, render_page=False)
        geometry_hex = cfg.get("ui", "geometry")
        if geometry_hex:
            self.restoreGeometry(QByteArray.fromHex(geometry_hex.encode()))
        state_hex = cfg.get("ui", "window_state")
        if state_hex:
            self.restoreState(QByteArray.fromHex(state_hex.encode()))

    def closeEvent(self, event) -> None:
        self.cleanup_media()
        self._connections.disconnect_all()
        self._ui_update_scheduler.stop()
        self.event_bus.unsubscribe("app_state.changed", self._app_state_handler)
        cfg.save_ui_state(
            geometry=self.saveGeometry(),
            state=self.saveState(),
            main_splitter=b"",
            right_splitter=b"",
            is_fs=self.is_fullscreen_mode,
        )
        event.accept()

    def on_btn_start_clicked(self) -> None:
        if not self.current_plugin:
            self.append_log("未选择有效平台")
            return
        keyword = self.inp_search.text().strip()
        if not keyword:
            self.append_log("请输入主页链接、分享链接或合集链接")
            return
        try:
            run_options = read_plugin_run_options(self.current_plugin.id, self.plugin_widget)
        except (AttributeError, TypeError, ValueError) as exc:
            self.append_log(f"配置读取错误: {exc}")
            return
        run_options.update(self._video_count_run_options(self.current_plugin.id))
        self.sig_start_crawl.emit(keyword, self.current_plugin.id, run_options)

    def _video_count_run_options(self, plugin_id: str) -> dict:
        top_bar = self.__dict__.get("top_bar")
        try:
            count = int(top_bar.current_video_count()) if top_bar is not None else 20
        except (TypeError, ValueError, AttributeError):
            count = 20
        if plugin_id == "bilibili":
            return {"max_pages": count}
        if plugin_id in {"douyin", "kuaishou", "xiaohongshu", "missav"}:
            return {"max_items": count}
        return {}

    def on_source_changed(self, _index: int) -> None:
        plugin_id = self.combo_source.currentData()
        if not plugin_id:
            return
        self.current_plugin = registry.get_plugin(plugin_id)
        if not self.current_plugin:
            return
        self.inp_search.setPlaceholderText(self.current_plugin.get_search_placeholder())
        defaults = get_platform_runtime_defaults(plugin_id)
        top_bar = getattr(self, "top_bar", None)
        if top_bar is not None:
            top_bar.configure_for_platform(plugin_id, defaults)
        cfg.set("common", "last_source", plugin_id)

    def set_crawl_running_state(self, is_running: bool) -> None:
        self.app_shell.set_crawl_running_state(is_running, self.plugin_widget)
        self._frontend_state_service.set_running(is_running)

    def on_btn_dir_clicked(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", self.current_save_dir)
        if selected_dir:
            self.set_current_save_dir(selected_dir, persist=True)
            self.sig_change_dir.emit()

    def set_current_save_dir(self, save_dir: str, *, persist: bool = False) -> None:
        previous = self.current_save_dir
        self.current_save_dir = save_dir
        if persist:
            try:
                cfg.set("common", "save_directory", save_dir)
            except Exception:
                self.current_save_dir = previous
                raise
        self.refresh_frontend_state()

    def add_video_row(self, video_item) -> None:
        self._frontend_state_service.upsert_video(video_item)

    def update_video_status(self, video_id, status, progress=None) -> None:
        # Controller updates video fields in-place; UI refresh is driven by app_state.changed.
        return

    def refresh_table_bindings(self) -> None:
        self.refresh_frontend_state()

    def reorder_video_row(self, video_item) -> int:
        self._frontend_state_service.upsert_video(video_item)
        self.refresh_frontend_state(force=True)
        return self.app_shell.row_for_video_id(video_item.id)

    def clear_video_rows(self) -> None:
        self._frontend_state_service.clear_videos()

    def remove_video_row(self, row: int) -> None:
        if self._pending_delete_video_id:
            self._frontend_state_service.remove_video(self._pending_delete_video_id)
            self._pending_delete_video_id = None
        self.refresh_frontend_state(force=True)

    def show_selection_dialog(self, items):
        selected = None
        try:
            normalized_items = items or []
            if not normalized_items:
                return []
            dialog = SelectionDialog(self, items=normalized_items)
            self._active_selection_dialog = dialog
            dialog.setModal(True)
            dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            dialog.raise_()
            dialog.activateWindow()
            from PyQt6.QtWidgets import QDialog

            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected = dialog.selected_indices
        except Exception as exc:
            self.append_log(f"任务清单对话框打开失败: {exc}")
            return None
        finally:
            self._active_selection_dialog = None
        if selected is not None:
            self.append_log(f"用户确认了 {len(selected)} 个任务")
            return selected
        self.append_log("用户取消了任务")
        return None

    def dismiss_selection_dialog(self) -> None:
        dialog = self._active_selection_dialog
        if dialog is not None:
            dialog.reject()

    def append_log(
        self,
        msg,
        *,
        trace_id: str | None = None,
        source: str = "GUI",
        level: str = "INFO",
    ) -> None:
        self._frontend_state_service.record_log(
            str(msg),
            source=source or "GUI",
            level=level or "INFO",
            trace_id=str(trace_id or ""),
        )

    def _emit_delete_for_video(self, video_id: str) -> None:
        if "app_shell" in self.__dict__:
            row = self.app_shell.row_for_video_id(video_id)
        else:
            left_panel = getattr(self, "left_panel", None)
            row = left_panel.find_row_by_video_id(video_id) if left_panel is not None else -1
        if row != -1:
            self._pending_delete_video_id = video_id
            self.sig_delete_video.emit(row, video_id)

    def get_selected_video_id(self) -> str | None:
        return self.app_shell.selected_video_id()

    def get_adjacent_video_id(self, current_video_id: str | None, direction: int, *, wrap: bool = True) -> str | None:
        video_order = self.app_shell.completed_id_order()
        if not video_order:
            return None
        current_index = video_order.index(current_video_id) if current_video_id in video_order else -1
        if current_index == -1:
            return video_order[0] if direction >= 0 else video_order[-1]
        next_index = current_index + (1 if direction >= 0 else -1)
        if wrap:
            next_index %= len(video_order)
        elif next_index < 0 or next_index >= len(video_order):
            return None
        return video_order[next_index]

    def select_video_by_id(self, video_id: str) -> bool:
        return self.app_shell.select_video_id(video_id)

    def _on_copy_trace_clicked(self) -> None:
        video_id = self.get_selected_video_id()
        if not video_id:
            self.append_log("请先选择一个任务")
            return
        self.sig_copy_trace_id.emit(video_id)

    def on_btn_file_association_clicked(self) -> None:
        choice = self.show_file_association_dialog()
        if choice is None:
            return
        self.sig_register_file_associations.emit(choice.include_video, choice.include_image)

    def show_file_association_dialog(self):
        dialog = FileAssociationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.choice()

    def show_image(self, image_path: str) -> None:
        self.app_shell.show_image(image_path)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.media_panel.resize_media()

    def play_video(self, video_path: str) -> None:
        self.app_shell.play_video(video_path)

    def stop_media_playback(self) -> None:
        self.media_panel.stop_playback()

    def release_media_playback(self) -> None:
        if "app_shell" in self.__dict__:
            self.app_shell.release_media()
            return
        media_panel = getattr(self, "media_panel", None)
        if media_panel is not None:
            media_panel.release_media()

    def cleanup_media(self) -> None:
        if "app_shell" in self.__dict__:
            self.app_shell.cleanup_media()
            return
        media_panel = getattr(self, "media_panel", None)
        if media_panel is not None:
            media_panel.cleanup()

    def _open_item_directory(self, video_id: str) -> None:
        result = self._frontend_state_service.handle_action("open_directory", {"video_id": video_id})
        if result.get("status") != "ok":
            self.append_log(result.get("message") or "打开目录失败")

    def _retry_failed_item(self, video_id: str) -> None:
        result = self._frontend_state_service.handle_action("retry_failed", {"video_id": video_id})
        if result.get("status") != "ok":
            self.append_log(result.get("message") or "重试失败")
        self.refresh_frontend_state()

    def _copy_item_diagnostics(self, video_id: str) -> None:
        result = self._frontend_state_service.handle_action("copy_diagnostics", {"video_id": video_id})
        if result.get("status") != "ok":
            self.append_log(result.get("message") or "复制诊断失败")
            return
        text = (result.get("data") or {}).get("text", "")
        QApplication.clipboard().setText(text)
        self.append_log("Trace ID 已复制")

    def _update_download_options(self, options: dict) -> None:
        result = self._frontend_state_service.handle_action("update_download_options", options or {})
        if result.get("status") == "ok":
            data = result.get("data") or {}
            self.append_log(
                f"Download options updated: concurrency={data.get('max_concurrent')}, retries={data.get('max_retries')}, auto_retry={data.get('auto_retry')}"
            )
            if self.__dict__.get("_cached_snapshot"):
                self._render_frontend_state(topics={"settings.update"})
            else:
                self.refresh_frontend_state(force=True)
        else:
            self.append_log(result.get("message") or "download options update failed")

    def _update_completed_metadata(self, video_id: str, metadata: dict) -> None:
        result = self._frontend_state_service.update_completed_metadata(video_id, metadata or {}, source="gui_player")
        if result.get("status") == "ok" and self.__dict__.get("_cached_snapshot"):
            self.refresh_frontend_state(topics={"videos.metadata"})

    def _pause_download_item(self, video_id: str) -> None:
        result = self._frontend_state_service.handle_action("pause_download", {"video_id": video_id})
        self.append_log(result.get("message") or "download paused")
        self.refresh_frontend_state()

    def _run_tool(self, tool_id: str) -> None:
        result = self._frontend_state_service.handle_action("run_tool", {"tool_id": tool_id})
        self.append_log(result.get("message") or f"工具已启动: {tool_id}")

    def _register_file_associations_from_frontend(self, include_video: bool, include_image: bool) -> None:
        result = self._frontend_state_service.handle_action(
            "register_file_associations",
            {"include_video": include_video, "include_image": include_image},
        )
        self.append_log(result.get("message") or "默认打开方式绑定完成")
