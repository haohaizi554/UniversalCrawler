"""Main window assembly for the unified 7-page GUI."""

from __future__ import annotations

import threading
import time
import ctypes
import sys
import weakref
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QByteArray, QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QPalette
from PyQt6.QtWidgets import QFileDialog, QDialog, QMainWindow, QApplication, QComboBox, QVBoxLayout, QWidget

from app.config import cfg, get_platform_runtime_defaults
from app.debug_logger import debug_logger
from app.core.event_bus import EventBus
from app.core.plugin_registry import registry
from app.services.app_state import AppState
from app.services.frontend_event_aggregator import sections_for_topic
from app.services.frontend_state_service import FrontendStateService
from app.ui.connection_registry import ConnectionRegistry
from app.ui.dialogs import FileAssociationDialog
from app.ui.dialogs.selection import SelectionDialog
from app.ui.layout.app_shell import AppShell
from app.ui.layout.window_title_bar import WindowTitleBar
from app.ui.plugin_settings import read_plugin_run_options
from app.ui.styles import apply_application_theme, build_palette, polish_data_views
from app.ui.ui_update_scheduler import UiUpdateScheduler
from app.utils.qt_runtime import load_qt_icon
from app.utils.runtime_paths import user_data_root
from app.utils.safe_slot import safe_slot


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", wintypes.POINT),
        ("ptMaxSize", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("ptMinTrackSize", wintypes.POINT),
        ("ptMaxTrackSize", wintypes.POINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [
        ("rgrc", wintypes.RECT * 3),
        ("lppos", ctypes.c_void_p),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class _WindowsFrameNativeEventFilter(QAbstractNativeEventFilter):
    """Application-wide Windows frame hook for frameless native messages."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window_ref = weakref.ref(window)

    def nativeEventFilter(self, event_type, message):
        window = self._window_ref()
        if window is None:
            return False, 0
        hit_test = window._handle_frameless_native_event(event_type, message)
        if hit_test is None:
            return False, 0
        return True, hit_test


class MainWindow(QMainWindow):
    """Thin GUI host that forwards user actions and renders frontend snapshots."""

    FRONTEND_REFRESH_INTERVAL_MS = 200
    FRONTEND_REFRESH_MAX_INTERVAL_MS = 750
    FRONTEND_RENDER_WARN_MS = 50
    FRAMELESS_RESIZE_BORDER_PX = 8
    AUTO_HIDE_TASKBAR_RESERVE_PX = 2
    WVR_REDRAW = 0x0300
    SM_CXSIZEFRAME = 32
    SM_CYSIZEFRAME = 33
    SM_CXPADDEDBORDER = 92
    DEFAULT_WINDOW_SIZE = QSize(1500, 880)
    MIN_WINDOW_SIZE = QSize(1500, 760)
    WINDOW_SCREEN_MARGIN_PX = 16
    GWL_STYLE = -16
    MONITOR_DEFAULTTONEAREST = 2
    ABM_GETSTATE = 0x00000004
    ABM_GETTASKBARPOS = 0x00000005
    ABM_GETAUTOHIDEBAREX = 0x0000000B
    ABS_AUTOHIDE = 0x00000001
    ABE_LEFT = 0
    ABE_TOP = 1
    ABE_RIGHT = 2
    ABE_BOTTOM = 3
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000
    WS_SYSMENU = 0x00080000
    WS_THICKFRAME = 0x00040000
    WM_GETMINMAXINFO = 0x0024
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCLBUTTONDOWN = 0x00A1
    WM_NCLBUTTONUP = 0x00A2
    WM_NCLBUTTONDBLCLK = 0x00A3
    HTCLIENT = 1
    HTCAPTION = 2
    HTMINBUTTON = 8
    HTMAXBUTTON = 9
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    HTCLOSE = 20
    PAGE_SECTION_BY_ID = {
        "queue": "queue_items",
        "active": "active_downloads",
        "completed": "completed_items",
        "failed": "failed_items",
    }
    VISIBLE_SCOPED_SECTIONS = frozenset(PAGE_SECTION_BY_ID.values()) | frozenset({"log_items"})

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
    _clipboard_copy_requested = pyqtSignal(str)

    def __init__(self, *, app_state: AppState | None = None, event_bus: EventBus | None = None) -> None:
        super().__init__()
        self.setObjectName("MainWindow")
        self.setAutoFillBackground(True)
        self._qt_initialized = True
        self.setWindowTitle("Universal Crawler Pro")
        if sys.platform.startswith("win"):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        QApplication.setFont(QFont("Microsoft YaHei UI", 10))
        self._apply_default_window_geometry()
        configured_theme = str(cfg.get("common", "theme", "dark" if cfg.get("common", "dark_theme", False) else "light") or "light").lower()
        self.is_dark_theme = configured_theme == "dark"
        self._apply_theme_stylesheet()
        icon = load_qt_icon(["favicon.ico"], fallback_names=["Web.ico"])
        if icon is not None:
            self.setWindowIcon(icon)

        self._save_dir_lock = threading.RLock()
        self.current_save_dir = cfg.get("common", "save_directory") or str(user_data_root())
        self.current_plugin = None
        self.plugin_widget = None
        self.is_fullscreen_mode = False
        self._pre_fullscreen_geometry: QByteArray | None = None
        self._pre_fullscreen_was_maximized = False
        self._custom_maximized = False
        self._native_maximize_requested = False
        self._pre_custom_maximize_geometry: QRect | None = None
        self._windows_frameless_style_applied = False
        self._frameless_resize_override_cursor_active = False
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
        self._connections.connect(
            self._clipboard_copy_requested,
            self._copy_text_to_clipboard,
            Qt.ConnectionType.QueuedConnection,
        )
        self._app_state_handler = self.event_bus.subscribe("app_state.changed", self._on_app_state_changed)
        self._pending_delete_video_ids: list[str] = []
        self._title_rename_handler = None
        self._applying_appearance = False
        self._pending_refresh_lock = threading.RLock()
        self._pending_refresh_topics: set[str] = set()
        self._cached_snapshot: dict | None = None
        self._active_selection_dialog: SelectionDialog | None = None
        self._directory_dialog: QFileDialog | None = None

        self._build_ui()
        self._expose_component_refs()
        self._bind_component_signals()
        self._apply_playback_runtime_settings()
        self._apply_theme_stylesheet()
        self.load_initial_state()
        self.refresh_frontend_state(mock=True, force=True)
        self._install_frameless_resize_event_filter()
        self._install_windows_native_frame_filter()

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
        self.window_root = QWidget()
        self.window_root.setObjectName("WindowRoot")
        self.window_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.window_root.setAutoFillBackground(True)
        self.window_title_bar = WindowTitleBar(
            title=self.windowTitle(),
            icon=self.windowIcon(),
            is_dark_theme=self.is_dark_theme,
        )
        self.app_shell = AppShell(is_dark_theme=self.is_dark_theme, style_provider=self)

        root_layout = QVBoxLayout(self.window_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.window_title_bar)
        root_layout.addWidget(self.app_shell, stretch=1)
        self.setCentralWidget(self.window_root)

    @classmethod
    def _bounded_window_size(cls, desired: QSize, available: QRect | None) -> QSize:
        if available is None or available.isNull() or not available.isValid():
            return QSize(desired)
        width = min(desired.width(), max(1, available.width() - cls.WINDOW_SCREEN_MARGIN_PX))
        height = min(desired.height(), max(1, available.height() - cls.WINDOW_SCREEN_MARGIN_PX))
        return QSize(width, height)

    @classmethod
    def _minimum_window_size_for_available(cls, available: QRect | None) -> QSize:
        return cls._bounded_window_size(cls.MIN_WINDOW_SIZE, available)

    @classmethod
    def _default_window_size_for_available(cls, available: QRect | None) -> QSize:
        minimum = cls._minimum_window_size_for_available(available)
        size = cls._bounded_window_size(cls.DEFAULT_WINDOW_SIZE, available)
        return QSize(max(size.width(), minimum.width()), max(size.height(), minimum.height()))

    def _available_geometry_for_rect(self, rect: QRect | None = None) -> QRect:
        probe = rect.center() if rect is not None and rect.isValid() else QCursor.pos()
        screen = QApplication.screenAt(probe) or self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect()

    def _apply_default_window_geometry(self) -> None:
        available = self._available_geometry_for_rect()
        minimum = self._minimum_window_size_for_available(available)
        default_size = self._default_window_size_for_available(available)
        self.setMinimumSize(minimum)
        self.resize(default_size)
        if available.isValid():
            x = available.x() + max(0, (available.width() - default_size.width()) // 2)
            y = available.y() + max(0, (available.height() - default_size.height()) // 2)
            self.setGeometry(QRect(QPoint(x, y), default_size))

    def _constrain_window_geometry_to_screen(self) -> None:
        available = self._available_geometry_for_rect(self.frameGeometry())
        if not available.isValid():
            return
        minimum = self._minimum_window_size_for_available(available)
        self.setMinimumSize(minimum)
        current = self.geometry()
        width = min(max(current.width(), minimum.width()), available.width())
        height = min(max(current.height(), minimum.height()), available.height())
        max_x = available.x() + max(0, available.width() - width)
        max_y = available.y() + max(0, available.height() - height)
        x = min(max(current.x(), available.x()), max_x)
        y = min(max(current.y(), available.y()), max_y)
        constrained = QRect(x, y, width, height)
        if constrained != current:
            self.setGeometry(constrained)

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
        self.window_title_bar.set_icon(self.windowIcon())
        self.window_title_bar.set_maximized(self.isMaximized())

    def _bind_component_signals(self) -> None:
        self._connections.connect(self.windowTitleChanged, self.window_title_bar.set_title)
        self._connections.connect(self.window_title_bar.minimize_requested, self.showMinimized)
        self._connections.connect(self.window_title_bar.maximize_restore_requested, self._toggle_maximized)
        self._connections.connect(self.window_title_bar.close_requested, self.close)
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
        self._connections.connect(self.app_shell.file_association_requested, lambda *_args: self.on_btn_file_association_clicked())
        self._connections.connect(self.app_shell.setting_changed, self._update_basic_setting)
        self._connections.connect(self.app_shell.platform_settings_visible, self._refresh_platform_auth_if_needed)
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
            self._add_pending_refresh_topics(topics)
        if force:
            self._render_frontend_state(mock=mock, topics=None)
            return
        self._frontend_refresh_pending_mock = bool(self.__dict__.get("_frontend_refresh_pending_mock", False) or mock)
        self._ui_update_scheduler.schedule("frontend")

    def _flush_frontend_state(self, _topics: set[str] | None = None) -> None:
        mock = bool(self.__dict__.get("_frontend_refresh_pending_mock", False))
        self._frontend_refresh_pending_mock = False
        pending = self._drain_pending_refresh_topics()
        self._render_frontend_state(mock=mock, topics=pending or None)

    def _pending_refresh_topic_lock(self) -> threading.RLock:
        lock = self.__dict__.get("_pending_refresh_lock")
        if lock is None:
            lock = threading.RLock()
            self.__dict__["_pending_refresh_lock"] = lock
        return lock

    def _add_pending_refresh_topic(self, topic: str) -> None:
        self._add_pending_refresh_topics({topic})

    def _add_pending_refresh_topics(self, topics) -> None:
        normalized = {str(topic) for topic in topics or () if topic}
        if not normalized:
            return
        with self._pending_refresh_topic_lock():
            pending = self.__dict__.setdefault("_pending_refresh_topics", set())
            pending.update(normalized)

    def _drain_pending_refresh_topics(self) -> set[str]:
        with self._pending_refresh_topic_lock():
            pending = set(self.__dict__.get("_pending_refresh_topics", set()))
            self.__dict__["_pending_refresh_topics"] = set()
        return pending

    def _render_frontend_state(self, *, mock: bool = False, topics: set[str] | None = None) -> None:
        started = time.perf_counter()
        sections = self._sections_for_topics(topics)
        service = self._frontend_state_service
        cached = self.__dict__.get("_cached_snapshot")
        changed_keys: set[str] | None = None
        # GUI refreshes ask for exactly the sections that can be painted now.
        # `get_delta()` intentionally unions retained dirty history for WebSocket
        # recovery, which would re-expand hidden pages during event storms.
        use_delta = False

        if (
            use_delta
            and
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
        visibility_sections: set[str] = set()
        for topic in topics:
            visible_page = self._page_id_from_visibility_topic(topic)
            if visible_page:
                section = self.PAGE_SECTION_BY_ID.get(visible_page)
                if section:
                    sections.update({section, "app_status"})
                    visibility_sections.add(section)
                    continue
                if visible_page == "logs":
                    sections.update({"log_items", "app_status"})
                    visibility_sections.add("log_items")
                    continue
                if visible_page == "settings":
                    sections.update({"settings_snapshot", "settings_contract", "download_options", "app_status"})
                    visibility_sections.update({"settings_snapshot", "settings_contract", "download_options"})
                    continue
                sections.add("app_status")
                continue
            if topic == "videos.terminal":
                sections.update({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"})
                continue
            mapped = sections_for_topic(topic)
            if mapped is None:
                return None
            sections.update(mapped)
        if "log_items" in sections:
            sections.add("app_status")
        if not sections:
            return None
        scoped = set(self._scope_sections_to_visible_page(frozenset(sections)))
        scoped.update(visibility_sections)
        if visibility_sections:
            scoped.add("app_status")
        return frozenset(scoped)

    def _scope_sections_to_visible_page(self, sections: frozenset[str]) -> frozenset[str]:
        scoped = set(sections)
        current_page = self._current_visible_page_id()
        if current_page is None:
            return sections
        visible_section = self.PAGE_SECTION_BY_ID.get(current_page)
        page_sections = scoped & set(self.PAGE_SECTION_BY_ID.values())
        if page_sections:
            scoped.difference_update(page_sections)
            if visible_section in page_sections:
                scoped.add(visible_section)
            scoped.add("app_status")
        if "log_items" in scoped and current_page != "logs":
            scoped.discard("log_items")
            scoped.add("app_status")
        return frozenset(scoped)

    def _current_visible_page_id(self) -> str | None:
        shell = self.__dict__.get("app_shell")
        page_id = getattr(shell, "current_page_id", None)
        if not isinstance(page_id, str):
            return None
        return page_id

    @staticmethod
    def _visibility_topic_for_page(page_id: str) -> str:
        return f"page.visible.{page_id}"

    @staticmethod
    def _page_id_from_visibility_topic(topic: str) -> str | None:
        prefix = "page.visible."
        normalized = str(topic or "")
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        return None

    def _flush_log_refresh(self) -> None:
        self._add_pending_refresh_topic("logs.append")
        self._ui_update_scheduler.schedule("logs.append", force=True)

    @safe_slot
    def _on_app_state_changed(self, payload) -> None:
        topic = ""
        if isinstance(payload, dict):
            topic = str(payload.get("topic") or "")
        if topic == "logs.append":
            self._add_pending_refresh_topic("logs.append")
            self._ui_update_scheduler.schedule("logs.append")
            return
        if topic in {"videos.update", "videos.metadata"}:
            refresh_topic = topic
            if topic == "videos.update" and isinstance(payload, dict):
                sections = FrontendStateService._sections_for_recorded_event(topic, payload)
                if sections is not None and "completed_items" in sections:
                    refresh_topic = "videos.terminal"
            self._add_pending_refresh_topic(refresh_topic)
            self._ui_update_scheduler.schedule("frontend")
            return
        if sections_for_topic(topic) is not None:
            self._add_pending_refresh_topic(topic)
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

    def _refresh_platform_auth_if_needed(self) -> None:
        service = getattr(self, "_frontend_state_service", None)
        handler = getattr(service, "handle_action", None)
        if not callable(handler):
            return
        try:
            result = handler("refresh_platform_auth_status", {})
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "refresh_platform_auth_status", exc)
            return
        data = result.get("data") if isinstance(result, dict) else {}
        if isinstance(data, dict) and data.get("refreshed"):
            self.refresh_frontend_state(topics={"settings.platform_auth"})

    def _on_page_changed(self, page_id: str) -> None:
        self.app_state.set_visible_page(page_id, list(self.app_shell.pages), emit_change=False)
        if page_id == "settings":
            settings_page = self.app_shell.pages.get("settings")
            is_platform_visible = getattr(settings_page, "is_platform_settings_visible", None)
            if callable(is_platform_visible) and is_platform_visible():
                self._refresh_platform_auth_if_needed()
        self.refresh_frontend_state(topics={self._visibility_topic_for_page(page_id)})

    def bind_video_rename(self, on_rename) -> None:
        # Titles are no longer editable in the queue table.  Keep the hook so the
        # controller can still bind without knowing the presentation changed.
        self._title_rename_handler = on_rename

    def toggle_theme(self) -> None:
        self.is_dark_theme = not self.is_dark_theme
        self._persist_manual_theme_config(self.is_dark_theme)
        self._apply_theme_stylesheet()
        self.append_log(f"已切换到{'深色' if self.is_dark_theme else '浅色'}主题")
        self.sig_theme_changed.emit(self.is_dark_theme)

    def _persist_manual_theme_config(self, is_dark: bool) -> None:
        previous_applying = bool(self.__dict__.get("_applying_appearance", False))
        self.__dict__["_applying_appearance"] = True
        try:
            try:
                cfg.set("appearance", "follow_system", False)
            except Exception as exc:
                debug_logger.log_exception("MainWindow", "disable_follow_system_for_manual_theme", exc)
            self._persist_theme_config(is_dark)
        finally:
            self.__dict__["_applying_appearance"] = previous_applying

    def _persist_theme_config(self, is_dark: bool) -> None:
        theme_values = {"theme": "dark" if is_dark else "light", "dark_theme": bool(is_dark)}
        set_many = getattr(cfg, "set_many", None)
        if callable(set_many):
            set_many("common", theme_values)
            return
        for key, value in theme_values.items():
            cfg.set("common", key, value)

    def _apply_theme_stylesheet(
        self,
        *,
        refresh_shell_theme: bool = True,
        sync_settings_theme: bool = True,
    ) -> None:
        if refresh_shell_theme:
            self._close_transient_popups_before_theme()
        self._apply_root_background()
        apply_application_theme(self.is_dark_theme)
        self._apply_root_background()
        title_bar = self.__dict__.get("window_title_bar")
        if title_bar is not None:
            title_bar.apply_theme(self.is_dark_theme)
        top_bar = self.__dict__.get("top_bar")
        if top_bar is not None and refresh_shell_theme:
            top_bar.set_theme_icon(self.is_dark_theme)
        app_shell = self.__dict__.get("app_shell")
        if app_shell is not None and refresh_shell_theme:
            app_shell.apply_theme(self.is_dark_theme)
        if app_shell is not None and sync_settings_theme:
            settings_page = getattr(app_shell, "pages", {}).get("settings")
            sync_theme = getattr(settings_page, "sync_external_theme", None)
            if callable(sync_theme):
                sync_theme(
                    self.is_dark_theme,
                    follow_system=bool(cfg.get("appearance", "follow_system", False)),
                )
        refreshed = False
        if "_frontend_state_service" in self.__dict__:
            self._refresh_frontend_after_theme_change()
            refreshed = True
        if not self.__dict__.get("_qt_initialized", False):
            return
        if not refreshed:
            self._finalize_theme_repaint()

    def _apply_root_background(self) -> None:
        palette = build_palette(self.is_dark_theme)
        widgets = []
        if self.__dict__.get("_qt_initialized", False) or "setPalette" in self.__dict__:
            widgets.append(self)
        if self.__dict__.get("_qt_initialized", False):
            try:
                widgets.append(self.centralWidget())
            except RuntimeError:
                pass
        widgets.append(self.__dict__.get("window_root"))
        widgets.append(self.__dict__.get("window_title_bar"))
        widgets.append(self.__dict__.get("app_shell"))
        for widget in widgets:
            try:
                if widget is None:
                    continue
                set_palette = getattr(widget, "setPalette", None)
                if callable(set_palette):
                    set_palette(palette)
                set_auto_fill = getattr(widget, "setAutoFillBackground", None)
                if callable(set_auto_fill):
                    set_auto_fill(True)
            except RuntimeError:
                continue

    def _refresh_frontend_after_theme_change(self) -> None:
        try:
            self.refresh_frontend_state(topics={"settings.update"})
        finally:
            self._finalize_theme_repaint()

    def _finalize_theme_repaint(self) -> None:
        try:
            app_shell = self.__dict__.get("app_shell")
            if app_shell is not None:
                settings_page = getattr(app_shell, "pages", {}).get("settings")
                repair = getattr(settings_page, "_repair_empty_view_if_needed", None)
                if callable(repair):
                    repair()
                for widget in (
                    settings_page,
                    getattr(settings_page, "nav_panel", None),
                    getattr(settings_page, "detail_panel", None),
                    app_shell,
                ):
                    if widget is not None and widget.isVisible():
                        widget.update()
            self.update()
        except RuntimeError as exc:
            debug_logger.log_exception("MainWindow", "finalize_theme_repaint", exc)

    def _close_transient_popups_before_theme(self) -> None:
        try:
            for combo in self.findChildren(QComboBox):
                combo.hidePopup()
            focused = QApplication.focusWidget()
            if focused is not None and (focused is self or self.isAncestorOf(focused)):
                focused.clearFocus()
            for widget in QApplication.topLevelWidgets():
                if widget is not self and widget.windowType() == Qt.WindowType.Popup:
                    widget.close()
        except RuntimeError as exc:
            debug_logger.log_exception("MainWindow", "close_transient_popups_before_theme", exc)

    def event(self, event) -> bool:
        handled = super().event(event)
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._handle_system_palette_changed()
        return handled

    def _follow_system_theme_enabled(self) -> bool:
        return bool(cfg.get("appearance", "follow_system", False))

    def _system_palette_is_dark(self) -> bool:
        palette = QApplication.palette()
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        return window.lightness() < text.lightness()

    def _handle_system_palette_changed(self) -> None:
        if not self._follow_system_theme_enabled():
            return
        is_dark = self._system_palette_is_dark()
        self._persist_theme_config(is_dark)
        if self.is_dark_theme == is_dark:
            return
        self.is_dark_theme = is_dark
        self._apply_theme_stylesheet()
        self.sig_theme_changed.emit(is_dark)
        self.refresh_frontend_state(topics={"settings.update"})

    def _toggle_maximized(self) -> None:
        if self.is_fullscreen_mode or self._safe_is_fullscreen():
            self._exit_legacy_main_fullscreen()
            return
        if self._is_effectively_maximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = self._safe_is_native_maximized()
        self._sync_window_title_bar_state()
        QTimer.singleShot(0, self._sync_window_title_bar_state)

    def _is_effectively_maximized(self) -> bool:
        try:
            native_maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized) or self.isMaximized()
        except RuntimeError:
            native_maximized = bool(self.isMaximized())
        return (
            bool(self.__dict__.get("_custom_maximized", False))
            or bool(self.__dict__.get("_native_maximize_requested", False))
            or native_maximized
        )

    def _current_work_area_geometry(self) -> QRect:
        screen = QApplication.screenAt(self.frameGeometry().center()) or self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else self.geometry()

    def _maximize_to_work_area(self) -> None:
        if not self.__dict__.get("_qt_initialized", False):
            self.showMaximized()
            return
        if not self.isMaximized() and not self.__dict__.get("_custom_maximized", False):
            self._pre_custom_maximize_geometry = QRect(self.geometry())
        if self.isFullScreen():
            self.showNormal()
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = True
        self.showMaximized()

    def _restore_from_custom_or_native_maximized(self) -> None:
        custom_maximized = bool(self.__dict__.get("_custom_maximized", False))
        geometry = self.__dict__.get("_pre_custom_maximize_geometry") if custom_maximized else None
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = False
        self._pre_custom_maximize_geometry = None
        if custom_maximized and isinstance(geometry, QRect) and geometry.isValid():
            self.setGeometry(geometry)

    def _sync_window_title_bar_state(self) -> None:
        title_bar = self.__dict__.get("window_title_bar")
        if title_bar is not None:
            title_bar.set_maximized(self._is_effectively_maximized())

    def _set_shell_widgets_visible(self, visible: bool) -> None:
        if "app_shell" in self.__dict__:
            widgets = (
                self.__dict__.get("window_title_bar"),
                self.app_shell.top_bar,
                self.app_shell.sidebar,
                self.app_shell.status_bar,
            )
        else:
            widgets = (
                self.__dict__.get("window_title_bar"),
                getattr(self, "top_bar", None),
                getattr(self, "left_panel", None),
                getattr(self, "log_txt", None),
            )
        for widget in widgets:
            if widget is not None:
                widget.setVisible(visible)

    def toggle_fullscreen_mode(self) -> None:
        """Compatibility entrypoint: main-window fullscreen is retired.

        Fullscreen belongs to the media preview window. Keeping the main window
        in Qt::WindowFullScreen can confuse Windows Shell auto-hide taskbar
        activation after restore, so legacy calls are either cleaned up or
        forwarded to the media panel.
        """
        if self.is_fullscreen_mode or self._safe_is_fullscreen():
            self._exit_legacy_main_fullscreen()
            return
        media_panel = self.__dict__.get("media_panel")
        toggle_media = getattr(media_panel, "toggle_media_fullscreen", None)
        if callable(toggle_media):
            toggle_media()

    def _safe_is_fullscreen(self) -> bool:
        try:
            return bool(self.isFullScreen())
        except RuntimeError:
            return bool(self.__dict__.get("is_fullscreen_mode", False))

    def _safe_is_native_maximized(self) -> bool:
        try:
            return bool(self.windowState() & Qt.WindowState.WindowMaximized)
        except RuntimeError:
            return False

    def _exit_legacy_main_fullscreen(self) -> None:
        if self._safe_is_fullscreen():
            self.showNormal()
        self._set_shell_widgets_visible(True)
        self.is_fullscreen_mode = False
        self._pre_fullscreen_geometry = None
        self._pre_fullscreen_was_maximized = False
        self.__dict__["_native_maximize_requested"] = self._safe_is_native_maximized()
        btn_fullscreen = self.__dict__.get("btn_fullscreen")
        if btn_fullscreen is not None:
            btn_fullscreen.setText("[ 全屏 ]")
        self._sync_window_title_bar_state()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and (self.is_fullscreen_mode or self._safe_is_fullscreen()):
            self._exit_legacy_main_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.__dict__["_native_maximize_requested"] = bool(self.windowState() & Qt.WindowState.WindowMaximized)
            self._sync_window_title_bar_state()

    def load_initial_state(self) -> None:
        last_source_id = cfg.get("common", "last_source", "kuaishou")
        index = self.combo_source.findData(last_source_id)
        self.combo_source.setCurrentIndex(index if index != -1 else 0)
        self.on_source_changed(self.combo_source.currentIndex())
        visible_page = self.app_state.get_visible_page()
        if visible_page in self.app_shell.pages:
            self.app_shell.show_page(visible_page, emit_change=False, render_page=False)
        geometry_hex = cfg.get("ui", "geometry")
        geometry_restored = False
        if geometry_hex:
            try:
                geometry_restored = bool(self.restoreGeometry(QByteArray.fromHex(geometry_hex.encode())))
            except (RuntimeError, ValueError) as exc:
                debug_logger.log_exception("MainWindow", "restore_geometry", exc)
        if geometry_restored:
            self._constrain_window_geometry_to_screen()
        else:
            self._apply_default_window_geometry()
        state_hex = cfg.get("ui", "window_state")
        if state_hex:
            self.restoreState(QByteArray.fromHex(state_hex.encode()))

    @safe_slot
    def closeEvent(self, event) -> None:
        self._connections.disconnect_all()
        self._remove_frameless_resize_event_filter()
        self._remove_windows_native_frame_filter()
        self.cleanup_media()
        self._ui_update_scheduler.stop()
        self.event_bus.unsubscribe("app_state.changed", self._app_state_handler)
        cfg.save_ui_state(
            geometry=self.saveGeometry(),
            state=self.saveState(),
            main_splitter=b"",
            right_splitter=b"",
            is_fs=False,
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
            return {"max_pages": count, "max_items": 9999}
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
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "选择保存目录",
            self.current_save_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        self._on_directory_selected(selected_dir)

    def _clear_directory_dialog(self, dialog: QFileDialog) -> None:
        if self.__dict__.get("_directory_dialog") is dialog:
            self._directory_dialog = None

    def _on_directory_selected(self, selected_dir: str) -> None:
        selected_dir = str(selected_dir or "").strip()
        if not selected_dir:
            return
        try:
            self.set_current_save_dir(selected_dir, persist=True)
        except Exception as exc:
            self.append_log(f"保存目录更新失败: {exc}", level="ERROR")
            self.refresh_frontend_state(topics={"settings.update"}, force=True)
            return
        self.sig_change_dir.emit()

    def set_current_save_dir(self, save_dir: str, *, persist: bool = False) -> None:
        previous = self.current_save_dir
        self.current_save_dir = save_dir
        if persist:
            try:
                if "_frontend_state_service" in self.__dict__:
                    result = self._frontend_state_service.handle_action(
                        "update_basic_setting",
                        {"key": "download_directory", "value": save_dir},
                    )
                    if result.get("status") != "ok":
                        raise RuntimeError(result.get("message") or "download directory update failed")
                    data = result.get("data") or {}
                    self.current_save_dir = str(data.get("directory") or data.get("value") or save_dir)
                else:
                    cfg.set("common", "save_directory", save_dir)
            except Exception:
                self.current_save_dir = previous
                raise
        self.refresh_frontend_state(topics={"settings.update"} if persist else None)

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

    def remove_video_row(self, row: int, video_id: str | None = None) -> None:
        del row
        pending_ids = self._pending_delete_ids()
        target_id = str(video_id or "")
        if target_id:
            if target_id in pending_ids:
                pending_ids.remove(target_id)
            self._frontend_state_service.remove_video(target_id)
        elif pending_ids:
            self._frontend_state_service.remove_video(pending_ids.pop(0))
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
        normalized_trace_id = str(trace_id or "")
        normalized_level = str(level or "INFO").upper()
        self._frontend_state_service.record_log(
            str(msg),
            source=source or "GUI",
            level=normalized_level,
            trace_id=normalized_trace_id,
        )
        app_state = getattr(self._frontend_state_service, "app_state", None)
        should_copy = getattr(app_state, "should_auto_copy_trace_on_error", None)
        if normalized_level == "ERROR" and normalized_trace_id and callable(should_copy) and should_copy():
            self._request_clipboard_copy(normalized_trace_id)

    def _request_clipboard_copy(self, text: str) -> None:
        signal = getattr(self, "_clipboard_copy_requested", None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            emit(str(text))
            return
        self._copy_text_to_clipboard(str(text))

    def _copy_text_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(str(text))

    def _emit_delete_for_video(self, video_id: str) -> None:
        if not video_id:
            return
        if "app_shell" in self.__dict__:
            row = self.app_shell.row_for_video_id(video_id)
        else:
            left_panel = getattr(self, "left_panel", None)
            row = left_panel.find_row_by_video_id(video_id) if left_panel is not None else -1
        self._remember_pending_delete(video_id)
        self.sig_delete_video.emit(row, video_id)

    def _pending_delete_ids(self) -> list[str]:
        pending_ids = self.__dict__.get("_pending_delete_video_ids")
        if not isinstance(pending_ids, list):
            pending_ids = []
            self._pending_delete_video_ids = pending_ids
        legacy_id = self.__dict__.pop("_pending_delete_video_id", None)
        if legacy_id and legacy_id not in pending_ids:
            pending_ids.append(legacy_id)
        return pending_ids

    def _remember_pending_delete(self, video_id: str) -> None:
        pending_ids = self._pending_delete_ids()
        if video_id not in pending_ids:
            pending_ids.append(video_id)

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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_windows_frameless_window_style()
        self._sync_window_title_bar_state()

    def nativeEvent(self, event_type, message):
        hit_test = self._handle_frameless_native_event(event_type, message)
        if hit_test is not None:
            return True, hit_test
        return False, 0

    def _handle_frameless_native_event(self, _event_type, message) -> int | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            msg = _MSG.from_address(int(message))
        except (AttributeError, TypeError, ValueError):
            return None
        if not self._native_msg_belongs_to_this_window(msg):
            return None
        message_id = int(msg.message)
        if message_id == self.WM_NCCALCSIZE and bool(msg.wParam):
            return self._handle_nc_calc_size(msg)
        if message_id == self.WM_GETMINMAXINFO:
            self._handle_get_min_max_info(msg)
            return 0
        if message_id == self.WM_NCHITTEST:
            return self._win32_hit_test(msg)
        if message_id == self.WM_NCLBUTTONDOWN and int(msg.wParam) == self.HTMAXBUTTON:
            return 0
        if message_id == self.WM_NCLBUTTONUP:
            if int(msg.wParam) == self.HTMAXBUTTON:
                self._toggle_maximized()
                return 0
        if message_id == self.WM_NCLBUTTONDBLCLK and int(msg.wParam) == self.HTCAPTION:
            self._toggle_maximized()
            return 0
        return None

    def _dwm_def_window_proc(self, msg) -> int | None:
        try:
            result_type = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
            result = result_type()
            handled = ctypes.windll.dwmapi.DwmDefWindowProc(
                msg.hWnd,
                msg.message,
                msg.wParam,
                msg.lParam,
                ctypes.byref(result),
            )
        except Exception:
            return None
        return int(result.value) if handled else None

    def _native_msg_belongs_to_this_window(self, msg) -> bool:
        try:
            hwnd = int(msg.hWnd)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        cached_hwnd = self.__dict__.get("_windows_hwnd")
        return cached_hwnd is not None and hwnd == int(cached_hwnd)

    def _apply_windows_frameless_window_style(self) -> None:
        if self.__dict__.get("_windows_frameless_style_applied", False):
            return
        if not sys.platform.startswith("win"):
            return
        try:
            hwnd = int(self.winId())
            self.__dict__["_windows_hwnd"] = hwnd
            user32 = ctypes.windll.user32
            long_ptr = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = long_ptr
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
            set_window_long.restype = long_ptr
            hwnd_handle = wintypes.HWND(hwnd)
            style = int(get_window_long(hwnd_handle, self.GWL_STYLE))
            desired_style = (style & ~self.WS_POPUP) | (
                self.WS_CAPTION
                | self.WS_THICKFRAME
                | self.WS_SYSMENU
                | self.WS_MINIMIZEBOX
                | self.WS_MAXIMIZEBOX
            )
            if desired_style != style:
                set_window_long(hwnd_handle, self.GWL_STYLE, long_ptr(desired_style))
            user32.SetWindowPos(
                hwnd_handle,
                0,
                0,
                0,
                0,
                0,
                self.SWP_NOMOVE
                | self.SWP_NOSIZE
                | self.SWP_NOZORDER
                | self.SWP_NOACTIVATE
                | self.SWP_FRAMECHANGED,
            )
            self.__dict__["_windows_frameless_style_applied"] = True
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "apply_windows_frameless_window_style", exc)

    def _handle_nc_calc_size(self, msg) -> int:
        try:
            return 0
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "handle_nc_calc_size", exc)
            return 0

    def _monitor_info_for_hwnd(self, hwnd) -> _MONITORINFO | None:
        monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, self.MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        monitor_info = _MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return None
        return monitor_info

    def _is_hwnd_maximized(self, hwnd) -> bool:
        try:
            return bool(ctypes.windll.user32.IsZoomed(hwnd))
        except Exception:
            return False

    def _window_dpi(self, hwnd) -> int:
        try:
            get_dpi_for_window = getattr(ctypes.windll.user32, "GetDpiForWindow")
            dpi = int(get_dpi_for_window(hwnd))
            return dpi if dpi > 0 else 96
        except Exception:
            return 96

    def _system_metric_for_hwnd(self, metric: int, hwnd) -> int:
        try:
            get_metric_for_dpi = getattr(ctypes.windll.user32, "GetSystemMetricsForDpi")
            return int(get_metric_for_dpi(metric, self._window_dpi(hwnd)))
        except Exception:
            return int(ctypes.windll.user32.GetSystemMetrics(metric))

    def _resize_border_thickness_for_hwnd(self, hwnd, *, horizontal: bool) -> int:
        frame_metric = self.SM_CXSIZEFRAME if horizontal else self.SM_CYSIZEFRAME
        frame = self._system_metric_for_hwnd(frame_metric, hwnd)
        padded = self._system_metric_for_hwnd(self.SM_CXPADDEDBORDER, hwnd)
        return max(0, frame + padded)

    def _native_client_pos_from_lparam(self, msg) -> QPoint:
        point = wintypes.POINT(
            self._signed_word(int(msg.lParam)),
            self._signed_word(int(msg.lParam) >> 16),
        )
        try:
            ctypes.windll.user32.ScreenToClient(msg.hWnd, ctypes.byref(point))
        except Exception:
            return QPoint(int(point.x), int(point.y))
        return QPoint(int(point.x), int(point.y))

    def _native_client_size_for_hwnd(self, hwnd) -> tuple[int, int]:
        rect = wintypes.RECT()
        try:
            if ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return max(1, int(rect.right - rect.left)), max(1, int(rect.bottom - rect.top))
        except Exception:
            pass
        dpr = self._qt_dpr()
        return max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))

    def _qt_dpr(self) -> float:
        try:
            handle = self.windowHandle()
            if handle is not None:
                dpr = float(handle.devicePixelRatio())
                if dpr > 0:
                    return dpr
        except Exception:
            pass
        try:
            dpr = float(self.devicePixelRatioF())
            return dpr if dpr > 0 else 1.0
        except Exception:
            return 1.0

    def _widget_rect_client_px(self, widget: QWidget | None) -> tuple[int, int, int, int] | None:
        if widget is None or not widget.isVisible():
            return None
        dpr = self._qt_dpr()
        pos = widget.mapTo(self, QPoint(0, 0))
        return (
            round(pos.x() * dpr),
            round(pos.y() * dpr),
            round((pos.x() + widget.width()) * dpr),
            round((pos.y() + widget.height()) * dpr),
        )

    @staticmethod
    def _point_in_rect_px(rect: tuple[int, int, int, int] | None, x: int, y: int) -> bool:
        if rect is None:
            return False
        left, top, right, bottom = rect
        return left <= x < right and top <= y < bottom

    def _win32_hit_test(self, msg) -> int:
        pos = self._native_client_pos_from_lparam(msg)
        x = int(pos.x())
        y = int(pos.y())
        width, height = self._native_client_size_for_hwnd(msg.hWnd)

        title_bar = self.__dict__.get("window_title_bar")
        if title_bar is not None and title_bar.isVisible():
            if self._point_in_rect_px(self._widget_rect_client_px(getattr(title_bar, "btn_maximize", None)), x, y):
                return self.HTMAXBUTTON
            for button in (
                getattr(title_bar, "btn_minimize", None),
                getattr(title_bar, "btn_close", None),
            ):
                if self._point_in_rect_px(self._widget_rect_client_px(button), x, y):
                    return self.HTCLIENT

        if not self._is_effectively_maximized() and not self.isFullScreen():
            border_x, border_y = self._frameless_resize_margins()
            left = x < border_x
            right = x >= width - border_x
            top = y < border_y
            bottom = y >= height - border_y
            if top and left:
                return self.HTTOPLEFT
            if top and right:
                return self.HTTOPRIGHT
            if bottom and left:
                return self.HTBOTTOMLEFT
            if bottom and right:
                return self.HTBOTTOMRIGHT
            if left:
                return self.HTLEFT
            if right:
                return self.HTRIGHT
            if top:
                return self.HTTOP
            if bottom:
                return self.HTBOTTOM

        if isinstance(title_bar, QWidget) and self._point_in_rect_px(self._widget_rect_client_px(title_bar), x, y):
            return self.HTCAPTION
        return self.HTCLIENT

    def _apply_auto_hide_taskbar_reserve_to_rect(self, rect, edge: int | None) -> None:
        reserve = self.AUTO_HIDE_TASKBAR_RESERVE_PX
        if edge == self.ABE_LEFT:
            rect.left += reserve
        elif edge == self.ABE_TOP:
            rect.top += reserve
        elif edge == self.ABE_RIGHT:
            rect.right -= reserve
        elif edge == self.ABE_BOTTOM:
            rect.bottom -= reserve

    def _handle_get_min_max_info(self, msg) -> None:
        try:
            monitor = ctypes.windll.user32.MonitorFromWindow(
                msg.hWnd,
                self.MONITOR_DEFAULTTONEAREST,
            )
            if not monitor:
                return
            monitor_info = _MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return
            min_max_info = ctypes.cast(msg.lParam, ctypes.POINTER(_MINMAXINFO)).contents
            monitor_rect = monitor_info.rcMonitor
            work_rect = monitor_info.rcWork
            taskbar_edge = self._auto_hide_taskbar_edge_for_monitor(monitor_rect)
            work_left, work_top, work_right, work_bottom = self._adjust_work_area_for_auto_hide_taskbar(
                monitor_rect,
                work_rect,
                taskbar_edge,
            )
            min_max_info.ptMaxPosition.x = work_left - monitor_rect.left
            min_max_info.ptMaxPosition.y = work_top - monitor_rect.top
            max_track_width = max(1, work_right - work_left)
            max_track_height = max(1, work_bottom - work_top)
            min_max_info.ptMaxSize.x = max_track_width
            min_max_info.ptMaxSize.y = max_track_height
            min_max_info.ptMaxTrackSize.x = max_track_width
            min_max_info.ptMaxTrackSize.y = max_track_height
            min_size = self.minimumSize()
            if min_size.width() > 0:
                min_max_info.ptMinTrackSize.x = min(
                    max_track_width,
                    max(min_max_info.ptMinTrackSize.x, min_size.width()),
                )
            if min_size.height() > 0:
                min_max_info.ptMinTrackSize.y = min(
                    max_track_height,
                    max(min_max_info.ptMinTrackSize.y, min_size.height()),
                )
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "handle_get_min_max_info", exc)

    @staticmethod
    def _rect_edges(rect) -> tuple[int, int, int, int]:
        return (
            int(getattr(rect, "left", 0)),
            int(getattr(rect, "top", 0)),
            int(getattr(rect, "right", 0)),
            int(getattr(rect, "bottom", 0)),
        )

    @classmethod
    def _rects_intersect(cls, first, second) -> bool:
        left1, top1, right1, bottom1 = cls._rect_edges(first)
        left2, top2, right2, bottom2 = cls._rect_edges(second)
        return left1 < right2 and right1 > left2 and top1 < bottom2 and bottom1 > top2

    @classmethod
    def _adjust_work_area_for_auto_hide_taskbar(cls, monitor_rect, work_rect, edge: int | None) -> tuple[int, int, int, int]:
        left, top, right, bottom = cls._rect_edges(work_rect)
        monitor_left, monitor_top, monitor_right, monitor_bottom = cls._rect_edges(monitor_rect)
        reserve = cls.AUTO_HIDE_TASKBAR_RESERVE_PX
        if edge == cls.ABE_LEFT and left <= monitor_left:
            left += reserve
        elif edge == cls.ABE_TOP and top <= monitor_top:
            top += reserve
        elif edge == cls.ABE_RIGHT and right >= monitor_right:
            right -= reserve
        elif edge == cls.ABE_BOTTOM and bottom >= monitor_bottom:
            bottom -= reserve
        return left, top, max(left + 1, right), max(top + 1, bottom)

    def _copy_rect_to_appbar_data(self, data: _APPBARDATA, rect) -> None:
        left, top, right, bottom = self._rect_edges(rect)
        data.rc.left = left
        data.rc.top = top
        data.rc.right = right
        data.rc.bottom = bottom

    def _auto_hide_taskbar_edge_for_monitor(self, monitor_rect) -> int | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            shell32 = ctypes.windll.shell32
            for edge in (self.ABE_BOTTOM, self.ABE_TOP, self.ABE_LEFT, self.ABE_RIGHT):
                data = _APPBARDATA()
                data.cbSize = ctypes.sizeof(_APPBARDATA)
                data.uEdge = edge
                self._copy_rect_to_appbar_data(data, monitor_rect)
                if shell32.SHAppBarMessage(self.ABM_GETAUTOHIDEBAREX, ctypes.byref(data)):
                    return edge

            data = _APPBARDATA()
            data.cbSize = ctypes.sizeof(_APPBARDATA)
            state = int(shell32.SHAppBarMessage(self.ABM_GETSTATE, ctypes.byref(data)))
            if not state & self.ABS_AUTOHIDE:
                return None

            data = _APPBARDATA()
            data.cbSize = ctypes.sizeof(_APPBARDATA)
            if not shell32.SHAppBarMessage(self.ABM_GETTASKBARPOS, ctypes.byref(data)):
                return None
            if not self._rects_intersect(data.rc, monitor_rect):
                return None
            return int(data.uEdge)
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "detect_auto_hide_taskbar", exc)
            return None

    @classmethod
    def _global_pos_from_lparam(cls, lparam: int) -> QPoint:
        return QPoint(cls._signed_word(lparam), cls._signed_word(lparam >> 16))

    @staticmethod
    def _signed_word(value: int) -> int:
        value &= 0xFFFF
        return value - 0x10000 if value & 0x8000 else value

    def _uses_windows_native_resize(self) -> bool:
        return sys.platform.startswith("win")

    def _frameless_resize_margins(self) -> tuple[int, int]:
        fallback = int(self.FRAMELESS_RESIZE_BORDER_PX)
        if not sys.platform.startswith("win"):
            return fallback, fallback
        try:
            hwnd = int(self.winId())
            horizontal = max(fallback, int(self._resize_border_thickness_for_hwnd(hwnd, horizontal=True)))
            vertical = max(fallback, int(self._resize_border_thickness_for_hwnd(hwnd, horizontal=False)))
            return horizontal, vertical
        except Exception:
            return fallback, fallback

    @staticmethod
    def _point_in_leading_edge(value: int, start: int, thickness: int) -> bool:
        thickness = max(1, thickness)
        return start - thickness <= value < start + thickness

    @staticmethod
    def _point_in_trailing_edge(value: int, end: int, thickness: int) -> bool:
        thickness = max(1, thickness)
        return end - thickness < value <= end + thickness

    def _frameless_hit_test(self, global_pos: QPoint) -> int | None:
        if self.isFullScreen():
            return None
        frame = self.frameGeometry()
        border_x, border_y = self._frameless_resize_margins()
        hit_frame = frame.adjusted(-border_x, -border_y, border_x, border_y)
        if not hit_frame.contains(global_pos):
            return None

        title_bar = self.__dict__.get("window_title_bar")
        title_local_pos = None
        title_contains_pos = False
        if title_bar is not None and title_bar.isVisible():
            title_local_pos = title_bar.mapFromGlobal(global_pos)
            title_contains_pos = title_bar.rect().contains(title_local_pos)
            if title_contains_pos and hasattr(title_bar, "chrome_button_kind_at"):
                button_kind = title_bar.chrome_button_kind_at(title_local_pos)
                if button_kind == "minimize":
                    return self.HTMINBUTTON
                if button_kind == "maximize":
                    return self.HTMAXBUTTON
                if button_kind == "close":
                    return self.HTCLOSE

        if not self._is_effectively_maximized():
            x = global_pos.x()
            y = global_pos.y()
            left = self._point_in_leading_edge(x, frame.left(), border_x)
            right = self._point_in_trailing_edge(x, frame.right(), border_x)
            top = self._point_in_leading_edge(y, frame.top(), border_y)
            bottom = self._point_in_trailing_edge(y, frame.bottom(), border_y)
            if top and left:
                return self.HTTOPLEFT
            if top and right:
                return self.HTTOPRIGHT
            if bottom and left:
                return self.HTBOTTOMLEFT
            if bottom and right:
                return self.HTBOTTOMRIGHT
            if left:
                return self.HTLEFT
            if right:
                return self.HTRIGHT
            if top:
                return self.HTTOP
            if bottom:
                return self.HTBOTTOM

        if title_contains_pos and title_local_pos is not None and not title_bar.is_interactive_at(title_local_pos):
            return self.HTCAPTION
        return None

    def _frameless_resize_edges_for_global_pos(self, global_pos: QPoint):
        if self.isFullScreen() or self._is_effectively_maximized():
            return None
        frame = self.frameGeometry()
        border_x, border_y = self._frameless_resize_margins()
        hit_frame = frame.adjusted(-border_x, -border_y, border_x, border_y)
        if not hit_frame.contains(global_pos):
            return None
        x = global_pos.x()
        y = global_pos.y()
        left = self._point_in_leading_edge(x, frame.left(), border_x)
        right = self._point_in_trailing_edge(x, frame.right(), border_x)
        top = self._point_in_leading_edge(y, frame.top(), border_y)
        bottom = self._point_in_trailing_edge(y, frame.bottom(), border_y)
        edge = None
        for enabled, qt_edge in (
            (left, Qt.Edge.LeftEdge),
            (right, Qt.Edge.RightEdge),
            (top, Qt.Edge.TopEdge),
            (bottom, Qt.Edge.BottomEdge),
        ):
            if enabled:
                edge = qt_edge if edge is None else edge | qt_edge
        return edge

    @staticmethod
    def _cursor_for_resize_edges(edges) -> Qt.CursorShape | None:
        if edges is None:
            return None
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (top and left) or (bottom and right):
            return Qt.CursorShape.SizeFDiagCursor
        if (top and right) or (bottom and left):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return None

    def _set_frameless_resize_cursor(self, cursor: Qt.CursorShape | None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        active = bool(self.__dict__.get("_frameless_resize_override_cursor_active", False))
        if cursor is None:
            if active:
                app.restoreOverrideCursor()
                self.__dict__["_frameless_resize_override_cursor_active"] = False
            return
        qt_cursor = QCursor(cursor)
        if active:
            app.changeOverrideCursor(qt_cursor)
        else:
            app.setOverrideCursor(qt_cursor)
            self.__dict__["_frameless_resize_override_cursor_active"] = True

    def _update_frameless_resize_cursor(self, global_pos: QPoint) -> None:
        cursor = self._cursor_for_resize_edges(self._frameless_resize_edges_for_global_pos(global_pos))
        self._set_frameless_resize_cursor(cursor)

    def _start_frameless_system_resize(self, global_pos: QPoint) -> bool:
        edge = self._frameless_resize_edges_for_global_pos(global_pos)
        if edge is None:
            return False
        window_handle = self.windowHandle()
        start_resize = getattr(window_handle, "startSystemResize", None)
        if not callable(start_resize):
            return False
        try:
            started = bool(start_resize(edge))
            if started:
                self._set_frameless_resize_cursor(None)
            return started
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "start_system_resize", exc)
            return False

    def _install_frameless_resize_event_filter(self) -> None:
        if self._uses_windows_native_resize():
            return
        app = QApplication.instance()
        if app is None or self.__dict__.get("_frameless_resize_event_filter_installed", False):
            return
        app.installEventFilter(self)
        self.__dict__["_frameless_resize_event_filter_installed"] = True

    def _install_windows_native_frame_filter(self) -> None:
        if not sys.platform.startswith("win") or self.__dict__.get("_windows_native_frame_filter_installed", False):
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            self.__dict__["_windows_hwnd"] = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        native_filter = _WindowsFrameNativeEventFilter(self)
        app.installNativeEventFilter(native_filter)
        self.__dict__["_windows_native_frame_filter"] = native_filter
        self.__dict__["_windows_native_frame_filter_installed"] = True

    def _remove_windows_native_frame_filter(self) -> None:
        if not self.__dict__.get("_windows_native_frame_filter_installed", False):
            return
        app = QApplication.instance()
        native_filter = self.__dict__.get("_windows_native_frame_filter")
        if app is not None and native_filter is not None:
            app.removeNativeEventFilter(native_filter)
        self.__dict__["_windows_native_frame_filter"] = None
        self.__dict__["_windows_native_frame_filter_installed"] = False

    def _remove_frameless_resize_event_filter(self) -> None:
        if not self.__dict__.get("_frameless_resize_event_filter_installed", False):
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.__dict__["_frameless_resize_event_filter_installed"] = False
        self._set_frameless_resize_cursor(None)

    def _event_belongs_to_this_window(self, watched: object) -> bool:
        widget = watched if isinstance(watched, QWidget) else None
        return widget is not None and widget.window() is self

    @staticmethod
    def _mouse_event_global_pos(event) -> QPoint:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return QCursor.pos()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._start_frameless_system_resize(self._mouse_event_global_pos(event)):
                event.accept()
                return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if self._event_belongs_to_this_window(watched):
            if event_type in {QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Enter}:
                self._update_frameless_resize_cursor(self._mouse_event_global_pos(event))
            elif event_type in {QEvent.Type.Leave, QEvent.Type.WindowDeactivate}:
                self._set_frameless_resize_cursor(None)
            elif (
                event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._start_frameless_system_resize(self._mouse_event_global_pos(event))
            ):
                event.accept()
                return True
        elif event_type in {QEvent.Type.Leave, QEvent.Type.WindowDeactivate}:
            self._set_frameless_resize_cursor(None)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_media_panel_if_ready()

    def _resize_media_panel_if_ready(self) -> None:
        media_panel = self.__dict__.get("media_panel")
        resize_media = getattr(media_panel, "resize_media", None)
        if callable(resize_media):
            resize_media()

    def play_video(self, video_path: str) -> None:
        self.app_shell.play_video(video_path)

    def stop_media_playback(self) -> None:
        media_panel = self.__dict__.get("media_panel")
        stop_playback = getattr(media_panel, "stop_playback", None)
        if callable(stop_playback):
            stop_playback()

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

    @safe_slot
    def _update_basic_setting(self, section: str, key: str, value) -> None:
        normalized_section = str(section or "common")
        action = "update_basic_setting" if normalized_section == "common" else "update_setting"
        payload = {"key": key, "value": value}
        if action == "update_setting":
            payload["section"] = normalized_section
        if normalized_section == "common" and str(key or "") == "theme":
            self._disable_follow_system_for_manual_theme()
        result = self._frontend_state_service.handle_action(action, payload)
        if result.get("status") != "ok":
            self.append_log(result.get("message") or "setting update failed", level="ERROR")
            self.refresh_frontend_state(topics={"settings.update"}, force=True)
            return
        data = result.get("data") or {}
        config_key = str(data.get("config_key") or data.get("key") or key or "")
        if normalized_section == "common" and config_key == "save_directory":
            directory = str(data.get("directory") or data.get("value") or "")
            if directory:
                changed = directory != self.current_save_dir
                self.current_save_dir = directory
                if changed:
                    self.sig_change_dir.emit()
        if normalized_section == "common" and config_key == "theme":
            theme_value = str(data.get("value") or value or "light").lower()
            is_dark = theme_value == "dark"
            if self.is_dark_theme != is_dark:
                self.is_dark_theme = is_dark
                self.sig_theme_changed.emit(is_dark)
        extra_topics = self._apply_runtime_setting_after_update(
            str(data.get("section") or normalized_section),
            config_key,
            data.get("value", value),
        )
        self.refresh_frontend_state(topics={"settings.update", *extra_topics})

    def _disable_follow_system_for_manual_theme(self) -> None:
        previous_applying = bool(self.__dict__.get("_applying_appearance", False))
        self.__dict__["_applying_appearance"] = True
        try:
            if bool(cfg.get("appearance", "follow_system", False)):
                cfg.set("appearance", "follow_system", False)
        except Exception as exc:
            debug_logger.log_exception("MainWindow", "disable_follow_system_for_setting_theme", exc)
        finally:
            self.__dict__["_applying_appearance"] = previous_applying

    def _apply_runtime_setting_after_update(self, section: str, key: str, value) -> set[str]:
        section = str(section or "")
        key = str(key or "")
        topics: set[str] = set()
        if section == "common" and key == "theme":
            self._apply_appearance_runtime_settings(key)
        elif section == "appearance":
            self._apply_appearance_runtime_settings(key)
        elif section == "playback":
            self._apply_playback_runtime_settings()
        elif section == "logging":
            topics.add("logs.append")
        elif key in {"max_items", "max_pages", "search_max_pages"}:
            current_plugin_id = str(getattr(getattr(self, "current_plugin", None), "id", "") or "")
            if section and section == current_plugin_id:
                top_bar = getattr(self, "top_bar", None)
                if top_bar is not None:
                    try:
                        top_bar.configure_for_platform(section, get_platform_runtime_defaults(section))
                        top_bar.set_video_count(int(value))
                    except (TypeError, ValueError, AttributeError) as exc:
                        debug_logger.log_exception(
                            "MainWindow",
                            "sync_top_quantity_after_setting",
                            exc,
                            details={"section": section, "key": key, "value": value},
                        )
        return topics

    @safe_slot
    def _apply_common_setting(self, key: str, value) -> None:
        key = str(key or "")
        if key == "save_directory":
            directory = str(value or cfg.get("common", "save_directory", self.current_save_dir) or "")
            if directory:
                self.current_save_dir = directory
                self.refresh_frontend_state(topics={"settings.update"})
            return
        if key in {"theme", "dark_theme"}:
            self._apply_appearance_runtime_settings(key)
            self.sig_theme_changed.emit(self.is_dark_theme)
            return
        if key in {"default_open_mode", "open_after_download", "filename_template"}:
            self.refresh_frontend_state(topics={"settings.update"})

    @safe_slot
    def _apply_appearance_runtime_settings(self, changed_key: str | None = None) -> None:
        if self._applying_appearance:
            return
        changed_key = str(changed_key or "").strip()
        self._applying_appearance = True
        try:
            if self._follow_system_theme_enabled():
                self.is_dark_theme = self._system_palette_is_dark()
                new_theme = "dark" if self.is_dark_theme else "light"
                if (
                    cfg.get("common", "dark_theme", None) != self.is_dark_theme
                    or cfg.get("common", "theme", None) != new_theme
                ):
                    self._persist_theme_config(self.is_dark_theme)
            else:
                theme_value = str(cfg.get("common", "theme", "light") or "light").lower()
                self.is_dark_theme = theme_value == "dark"
            if changed_key == "language":
                return
            if changed_key in {"font_size", "scale"}:
                self._apply_theme_stylesheet(
                    refresh_shell_theme=False,
                    sync_settings_theme=False,
                )
                self.setPalette(build_palette(self.is_dark_theme))
                return
            self._apply_theme_stylesheet()
            self.setPalette(build_palette(self.is_dark_theme))
        finally:
            self._applying_appearance = False

    @safe_slot
    def _apply_playback_runtime_settings(self) -> None:
        settings = dict((cfg.data.get("playback") or {}))
        apply_shell_settings = getattr(getattr(self, "app_shell", None), "apply_playback_settings", None)
        if callable(apply_shell_settings):
            apply_shell_settings(settings)
            return
        media_panel = getattr(self, "media_panel", None)
        apply_panel_settings = getattr(media_panel, "apply_playback_settings", None)
        if callable(apply_panel_settings):
            apply_panel_settings(settings)

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
        ok = result.get("status") == "ok"
        message = result.get("message") or ("默认打开方式绑定完成" if ok else "默认打开方式绑定失败")
        self.append_log(message, level="INFO" if ok else "ERROR")
        settings_page = getattr(getattr(self, "app_shell", None), "pages", {}).get("settings")
        feedback = getattr(settings_page, "show_action_feedback", None)
        if callable(feedback):
            feedback(message, ok=ok)
        self.refresh_frontend_state(topics={"settings.update"}, force=True)


