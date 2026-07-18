"""组装统一七页桌面 GUI 的主窗口。"""

from __future__ import annotations

import sys
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from PyQt6.QtCore import QByteArray, QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QPalette
from PyQt6.QtWidgets import QFileDialog, QDialog, QMainWindow, QApplication, QComboBox, QWidget

from app.config import cfg, get_platform_runtime_defaults
from app.debug_logger import debug_logger
from app.core.event_bus import EventBus
from app.core.plugin_registry import registry
from app.services.app_state import AppState
from app.services.frontend_event_aggregator import sections_for_topic
from app.services.frontend_state_service import FrontendStateService
from app.services.media_release_coordination import normalize_media_path
from app.services.update_check_service import (
    UPDATE_STATUS_AVAILABLE,
    UPDATE_STATUS_CURRENT,
    UPDATE_STATUS_LOCAL_NEWER,
    UPDATE_STATUS_UNTRUSTED,
    UPDATE_PUBLIC_KEY_PEM,
    UPDATE_REQUIRE_OS_SIGNATURE,
    PreparedUpdate,
    UpdateCheckResult,
    check_secure_update,
    launch_prepared_update,
    prepare_verified_update,
)
from app.services.secure_updater import (
    Downloader,
    PackageVerifier,
    UpdateManifestVerifier,
    default_update_staging_dir,
    record_skipped_update,
    record_startup_update_health,
)
from app.ui.connection_registry import ConnectionRegistry
from app.ui.gui_runtime_adapter import QtGuiRuntimeAdapter
from app.ui.dialogs import FileAssociationDialog
from app.ui.dialogs.selection import SelectionDialog
from app.ui.dialogs.update_check import UpdateCheckDialog, UpdateDownloadDialog
from app.ui.layout.app_shell import AppShell
from app.ui.layout.window_chrome import WindowChromeFrame
from app.ui.layout.window_chrome_controller import FramelessWindowChromeController, _NCCALCSIZE_PARAMS  # noqa: F401
from shared.localization import normalize_language, tr
from app.ui.plugin_settings import read_plugin_run_options
from app.ui.styles import apply_application_theme, build_palette
from app.ui.ui_update_scheduler import UiUpdateScheduler
from app.ui import window_state_persistence
from app.ui.viewmodels.frontend_snapshot_worker import (
    FrontendSnapshotRequest,
    FrontendSnapshotResult,
    FrontendSnapshotWorker,
)
from app.ui.viewmodels.frontend_action_worker import (
    FrontendActionRequest,
    FrontendActionResult,
    FrontendActionWorker,
)
from app.ui.viewmodels.latest_worker import LatestRequestWorker
from app.utils.qt_runtime import load_qt_icon
from app.utils.runtime_paths import user_data_root
from app.utils.safe_slot import safe_slot

@dataclass(frozen=True)
class _UpdateCheckRequest:
    sequence: int
    local_version: str


@dataclass(frozen=True)
class _UpdateCheckOutcome:
    sequence: int
    result: UpdateCheckResult | None = None
    error: str = ""


@dataclass(frozen=True)
class _PreparedUpdate:
    installer_path: str
    manifest_path: str
    signature_path: str
    version: str
    log_path: str


class MainWindow(QMainWindow):
    """转发用户动作并渲染前端快照的轻量 GUI 宿主。"""

    FRONTEND_REFRESH_INTERVAL_MS = 200
    FRONTEND_REFRESH_MAX_INTERVAL_MS = 750
    FRONTEND_RENDER_WARN_MS = 50
    FRONTEND_RENDER_WARN_MIN_INTERVAL_MS = 10_000
    LOG_REFRESH_THROTTLE_MS = 350
    THEME_TOGGLE_COALESCE_MS = 120
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
    UPDATE_DOWNLOAD_SHUTDOWN_JOIN_SECONDS = 0.25

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
    sig_auto_next_image_preview = pyqtSignal()
    _clipboard_copy_requested = pyqtSignal(str)
    _update_check_finished = pyqtSignal(object)
    _update_check_failed = pyqtSignal(str)
    _update_download_progress = pyqtSignal(object)
    _update_download_finished = pyqtSignal(object)
    _update_download_failed = pyqtSignal(object)
    _app_state_changed_queued = pyqtSignal(object)
    _frontend_snapshot_finished = pyqtSignal(object)
    _frontend_action_finished = pyqtSignal(object)

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
        self._owns_event_bus = event_bus is None
        self._owns_app_state = app_state is None
        self.app_state = app_state or AppState(event_bus=self.event_bus)
        self._frontend_state_service = FrontendStateService(app_state=self.app_state, gui_runtime_adapter=QtGuiRuntimeAdapter())
        self._owns_frontend_state_service = True
        self._connections = ConnectionRegistry()
        self._frontend_refresh_pending_mock = False
        self._frontend_snapshot_sequence = 0
        self._frontend_action_sequence = 0
        self._frontend_snapshot_worker = FrontendSnapshotWorker(
            lambda result: self._frontend_snapshot_finished.emit(result)
        )
        self._frontend_action_worker = FrontendActionWorker(
            lambda result: self._frontend_action_finished.emit(result)
        )
        # 主题切换执行中只保留最后目标，并用 sequence 淘汰迟到回调；已提交仅表示本地路径执行，
        # 不代表异步写入或前端确认。
        self._theme_transition_in_progress = False
        self._queued_theme_is_dark: bool | None = None
        self._theme_transition_target_is_dark: bool | None = None
        self._theme_transition_sequence = 0
        self._last_committed_theme_sequence = 0
        self._update_check_sequence = 0
        self._update_check_worker: LatestRequestWorker[_UpdateCheckRequest, _UpdateCheckOutcome] | None = None
        self._update_check_loading_dialog: UpdateCheckDialog | None = None
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
        self._connections.connect(
            self._update_check_finished,
            self._on_update_check_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._update_check_failed,
            self._on_update_check_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._update_download_progress,
            self._on_update_download_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._update_download_finished,
            self._on_update_download_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._update_download_failed,
            self._on_update_download_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._app_state_changed_queued,
            self._on_app_state_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._frontend_snapshot_finished,
            self._on_frontend_snapshot_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._connections.connect(
            self._frontend_action_finished,
            self._on_frontend_action_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._app_state_handler = self._subscribe_app_state_changed()
        self._pending_delete_video_ids: list[str] = []
        self._title_rename_handler = None
        self._applying_appearance = False
        self._pending_refresh_lock = threading.RLock()
        self._pending_refresh_topics: set[str] = set()
        self._cached_snapshot: dict | None = None
        self._frontend_section_signatures: dict[str, str] = {}
        self._active_selection_dialog: SelectionDialog | None = None
        self._directory_dialog: QFileDialog | None = None
        self._update_check_running = False
        self._update_check_lock = threading.RLock()
        self._update_download_sequence = 0
        self._update_download_lock = threading.RLock()
        self._update_download_shutdown = False
        self._update_download_thread: threading.Thread | None = None
        self._update_download_cancel_event: threading.Event | None = None
        self._update_download_dialog: UpdateDownloadDialog | None = None
        self._last_update_result: UpdateCheckResult | None = None
        self._prepared_update: _PreparedUpdate | None = None
        window_state_persistence.initialize_window_state_persistence(self)

        self._build_ui()
        self._debug_shell_visibility("after_build_ui")
        self._expose_component_refs()
        self._bind_component_signals()
        self._apply_playback_runtime_settings()
        self._apply_theme_stylesheet(
            refresh_frontend_snapshot=False,
            update_theme_icon=True,
            freeze_updates=False,
        )
        self.load_initial_state()
        self._record_update_startup_health()
        self._exit_stale_media_fullscreen_if_needed(reason="after_load_initial_state")
        self._ensure_shell_chrome_visible(reason="after_load_initial_state")
        self._debug_shell_visibility("after_load_initial_state")
        self.refresh_frontend_state(mock=True, force=True)
        self._ensure_shell_chrome_visible(reason="after_initial_refresh")
        self._debug_shell_visibility("after_initial_refresh")
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
        self.window_chrome = WindowChromeFrame(
            title=self.windowTitle(),
            icon=self.windowIcon(),
            is_dark_theme=self.is_dark_theme,
        )
        self.window_root = self.window_chrome
        self.window_root.setObjectName("WindowRoot")
        self.window_title_bar = self.window_chrome.title_bar
        self.app_shell = AppShell(is_dark_theme=self.is_dark_theme, style_provider=self)
        self.window_chrome.body_layout.addWidget(self.app_shell, stretch=1)
        self._window_chrome_controller = FramelessWindowChromeController(
            self,
            title_bar_getter=lambda: self.window_title_bar,
            is_effectively_maximized=self._is_effectively_maximized,
            toggle_maximized=self._toggle_maximized,
            resizable=True,
            minimizable=True,
            maximizable=True,
        )
        self._window_chrome_controller.set_window_flags()
        self.setCentralWidget(self.window_root)

    def _chrome_controller(self) -> FramelessWindowChromeController:
        controller = self.__dict__.get("_window_chrome_controller")
        if controller is not None:
            return controller
        controller = FramelessWindowChromeController(
            self,
            title_bar_getter=lambda: self.__dict__.get("window_title_bar"),
            is_effectively_maximized=self._is_effectively_maximized,
            toggle_maximized=self._toggle_maximized,
            resizable=True,
            minimizable=True,
            maximizable=True,
        )
        self.__dict__["_window_chrome_controller"] = controller
        return controller

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
        self._connections.connect(self.app_shell.delete_failed_record_requested, self._delete_failed_record)
        self._connections.connect(self.app_shell.tool_requested, self._run_tool)
        self._connections.connect(self.app_shell.completed_metadata_detected, self._update_completed_metadata)
        self._connections.connect(self.app_shell.file_association_requested, lambda *_args: self.on_btn_file_association_clicked())
        self._connections.connect(self.app_shell.setting_changed, self._update_basic_setting)
        self._connections.connect(self.app_shell.platform_settings_visible, self._refresh_platform_auth_if_needed)
        self._connections.connect(self.app_shell.page_changed, self._on_page_changed)
        self._connections.connect(self.app_shell.refresh_requested, self._on_queue_refresh_requested)
        self._connections.connect(self.app_shell.clear_all_requested, self._on_clear_queue_requested)
        self._connections.connect(self.app_shell.clear_failed_records_requested, self._clear_failed_records)
        self._connections.connect(self.app_shell.active_options_changed, self._update_download_options)
        self._connections.connect(self.app_shell.log_action_requested, self._handle_log_action)
        self._connections.connect(self.app_shell.update_check_requested, self._on_update_check_requested)
        self._connections.connect(self.media_panel.sig_switch_preview, self.sig_switch_preview.emit)
        self._connections.connect(self.media_panel.sig_auto_next_preview, self.sig_auto_next_preview.emit)
        self._connections.connect(
            self.media_panel.sig_auto_next_image_preview,
            self.sig_auto_next_image_preview.emit,
        )

    def _on_update_check_requested(self, version_text: str = "") -> None:
        del version_text
        if not self._try_begin_update_check():
            loading_dialog = self.__dict__.get("_update_check_loading_dialog")
            if loading_dialog is not None and loading_dialog.isVisible():
                loading_dialog.raise_()
                loading_dialog.activateWindow()
                return
            self._show_basic_message(
                "检查更新",
                "正在检查更新，请稍候。",
            )
            return
        self._set_status_bar_update_checking(True)
        from cli import __version__

        local_version = str(__version__).strip()
        self._last_update_check_local_version = local_version
        self._show_update_check_loading(local_version)
        worker = self._ensure_update_check_worker()
        self._update_check_sequence = int(self.__dict__.get("_update_check_sequence", 0) or 0) + 1
        worker.submit(_UpdateCheckRequest(sequence=self._update_check_sequence, local_version=local_version))

    def _show_update_check_loading(self, local_version: str) -> None:
        self._dismiss_update_check_loading()
        dialog = UpdateCheckDialog(
            self,
            title="检查更新",
            message="正在检查更新，请稍候。",
            primary_text="正在检查更新...",
            status="checking",
            local_version=self._display_version(local_version),
            latest_version="",
            language=self._current_ui_language(),
        )
        self._update_check_loading_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_update_check_loading_dialog", None))
        dialog.show()

    def _dismiss_update_check_loading(self) -> None:
        dialog = self.__dict__.pop("_update_check_loading_dialog", None)
        if dialog is None:
            return
        dialog.reject()
        dialog.deleteLater()

    def _try_begin_update_check(self) -> bool:
        with self._update_check_lock:
            if self._update_check_running:
                return False
            self._update_check_running = True
            return True

    def _finish_update_check(self) -> None:
        with self._update_check_lock:
            self._update_check_running = False
        self._set_status_bar_update_checking(False)

    def _set_status_bar_update_checking(self, checking: bool) -> None:
        status_bar = getattr(getattr(self, "app_shell", None), "status_bar", None)
        setter = getattr(status_bar, "set_update_checking", None)
        if callable(setter):
            setter(checking)

    def _current_status_version(self) -> str:
        status_bar = getattr(getattr(self, "app_shell", None), "status_bar", None)
        label = getattr(status_bar, "lbl_version", None)
        text = getattr(label, "text", None)
        if callable(text):
            return str(text())
        return "v3.6.21"

    def _record_update_startup_health(self) -> None:
        try:
            current_version = self._display_version(self._current_status_version()).lstrip("vV")
            record_startup_update_health(
                current_version=current_version,
                staging_dir=default_update_staging_dir(),
            )
        except Exception as exc:
            debug_logger.log_exception(
                "MainWindow",
                "record_update_startup_health",
                exc,
                details={"version": self._current_status_version()},
            )

    def _ensure_update_check_worker(self) -> LatestRequestWorker[_UpdateCheckRequest, _UpdateCheckOutcome]:
        worker = self.__dict__.get("_update_check_worker")
        if worker is None:
            worker = LatestRequestWorker(
                name="update-check-worker",
                on_result=self._on_update_check_worker_result,
                process=self._process_update_check_request,
            )
            self._update_check_worker = worker
        return worker

    def _current_ui_language(self) -> str:
        shell_language = getattr(getattr(self, "app_shell", None), "_language", "")
        if shell_language:
            return normalize_language(str(shell_language))
        return normalize_language(str(cfg.get("appearance", "language", "zh-CN") or "zh-CN"))

    def _tr(self, text: str) -> str:
        return tr(text, self._current_ui_language())

    @staticmethod
    def _process_update_check_request(request: _UpdateCheckRequest) -> _UpdateCheckOutcome:
        try:
            result = check_secure_update(request.local_version)
        except Exception as exc:
            return _UpdateCheckOutcome(sequence=request.sequence, error=str(exc))
        return _UpdateCheckOutcome(sequence=request.sequence, result=result)

    def _on_update_check_worker_result(self, outcome: _UpdateCheckOutcome) -> None:
        current_sequence = int(self.__dict__.get("_update_check_sequence", 0) or 0)
        if outcome.sequence != current_sequence:
            return
        if outcome.error:
            self._update_check_failed.emit(outcome.error)
            return
        self._update_check_finished.emit(outcome.result)

    def _on_update_check_finished(self, result: object) -> None:
        self._finish_update_check()
        self._dismiss_update_check_loading()
        if not isinstance(result, UpdateCheckResult):
            self._show_update_check_error("更新检测返回了无法识别的结果。")
            return
        self._show_update_check_result(result)

    def _on_update_check_failed(self, message: str) -> None:
        self._finish_update_check()
        self._dismiss_update_check_loading()
        self._show_update_check_error(message)

    def _show_update_check_error(self, message: str) -> None:
        local_version = str(self.__dict__.get("_last_update_check_local_version") or "").strip()
        self._show_basic_message(
            "检查更新失败",
            "暂时无法检查最新版本。",
            message,
            status="error",
            local_version=self._display_version(local_version) if local_version else "",
            latest_version="",
        )

    def _show_update_check_result(self, result: UpdateCheckResult) -> None:
        local_version = self._display_version(result.local_version)
        latest_version = self._display_version(result.latest_version)
        if result.status == UPDATE_STATUS_CURRENT:
            self._show_basic_message(
                "检查更新",
                self._tr("当前版本 {version} 已经是最新版本。").format(version=local_version),
                "本地版本与 GitHub 最新 Release 一致，无需更新。",
                status=UPDATE_STATUS_CURRENT,
                local_version=local_version,
                latest_version=latest_version,
                release_url=result.html_url,
            )
            return
        if result.status == UPDATE_STATUS_LOCAL_NEWER:
            self._show_basic_message(
                "检查更新",
                self._tr("当前版本 {local_version} 高于最新 Release {latest_version}。").format(
                    local_version=local_version,
                    latest_version=latest_version,
                ),
                "这通常表示你正在使用本地构建或预发布构建，无需更新。",
                status=UPDATE_STATUS_LOCAL_NEWER,
                local_version=local_version,
                latest_version=latest_version,
                release_url=result.html_url,
            )
            return
        if result.status == UPDATE_STATUS_AVAILABLE:
            self._show_update_available_message(local_version, latest_version, result)
            return
        if result.status == UPDATE_STATUS_UNTRUSTED:
            self._show_basic_message(
                "检查更新",
                self._tr("检测到版本 {version}，但该 Release 未提供签名更新清单。").format(
                    version=latest_version,
                ),
                self._tr("自动更新已安全阻止，请等待发布者补充 latest.json 与 latest.json.sig。"),
                status="error",
                local_version=local_version,
                latest_version=latest_version,
                release_url=result.html_url,
            )
            return
        self._show_update_check_error(f"未知更新状态：{result.status}")

    def _show_update_available_message(
        self,
        local_version: str,
        latest_version: str,
        result: UpdateCheckResult,
    ) -> None:
        box = UpdateCheckDialog(
            self,
            title="检测到新版本",
            message=self._tr("检测到最新版本 {version}，是否要更新？").format(version=latest_version),
            details=result.notes or "更新前建议关闭正在运行的采集任务。安装包会先完成更新清单签名、大小和 SHA-256 校验。",
            primary_text="下载更新",
            secondary_text="稍后",
            skip_text="" if result.mandatory else "跳过此版本",
            status=UPDATE_STATUS_AVAILABLE,
            local_version=local_version,
            latest_version=latest_version,
            release_url=result.html_url,
            candidates=result.candidates,
            language=self._current_ui_language(),
        )
        dialog_result = box.exec()
        if dialog_result == QDialog.DialogCode.Accepted:
            selected_result = result
            selected_version = box.selected_update_version()
            if selected_version and result.candidates:
                try:
                    selected_result = result.for_version(selected_version)
                except ValueError as exc:
                    self._show_update_check_error(str(exc))
                    return
            self._begin_update_download(selected_result)
        elif int(dialog_result) == UpdateCheckDialog.SKIP_CODE:
            self._skip_update_version(box.selected_update_version() or result.latest_version)

    def _skip_update_version(self, version: str) -> None:
        try:
            record_skipped_update(version)
        except Exception as exc:
            self._show_update_check_error(str(exc))
            return
        self.append_log(f"已跳过更新版本: {version}")

    def _begin_update_download(self, result: UpdateCheckResult) -> None:
        with self._update_download_lock:
            if self._update_download_shutdown:
                return
            old_cancel_event = self.__dict__.get("_update_download_cancel_event")
            if old_cancel_event is not None:
                old_cancel_event.set()
            self._update_download_sequence = int(self.__dict__.get("_update_download_sequence", 0) or 0) + 1
            sequence = self._update_download_sequence
            cancel_event = threading.Event()
            self._last_update_result = result
            self._prepared_update = None
            self._update_download_cancel_event = cancel_event

        previous_dialog = self.__dict__.get("_update_download_dialog")
        if previous_dialog is not None:
            previous_dialog.done(0)

        dialog = UpdateDownloadDialog(
            self,
            version=self._display_version(result.latest_version),
            asset_name=result.asset_name,
            release_url=result.html_url,
            language=self._current_ui_language(),
        )
        dialog.cancel_requested.connect(self._cancel_update_download)
        dialog.retry_requested.connect(self._retry_update_download)
        dialog.install_requested.connect(self._install_prepared_update)
        dialog.view_log_requested.connect(lambda: self._handle_log_action("open_latest"))
        self._update_download_dialog = dialog
        dialog.show()

        worker = threading.Thread(
            target=self._run_update_download,
            args=(sequence, result, cancel_event),
            name="update-download-worker",
            daemon=True,
        )
        self._update_download_thread = worker
        worker.start()

    def _emit_update_download_event(self, signal: object, payload: dict[str, object]) -> bool:
        """关闭开始或请求已被替代后丢弃 `worker` 事件，避免迟到结果回写 UI。"""
        sequence = int(payload.get("sequence") or 0)
        with self._update_download_lock:
            if self._update_download_shutdown or sequence != self._update_download_sequence:
                return False
            emitter = getattr(signal, "emit", None)
            if not callable(emitter):
                return False
            emitter(payload)
            return True

    def _run_update_download(
        self,
        sequence: int,
        result: UpdateCheckResult,
        cancel_event: threading.Event,
    ) -> None:
        try:
            prepared = self._download_verified_update(
                result,
                cancel_event=cancel_event,
                progress_callback=lambda progress: self._emit_update_download_event(
                    self._update_download_progress,
                    {"sequence": sequence, "progress": progress},
                ),
            )
        except Exception as exc:
            message = "已取消下载。" if cancel_event.is_set() else str(exc)
            self._emit_update_download_event(
                self._update_download_failed,
                {"sequence": sequence, "message": message},
            )
            return
        if cancel_event.is_set():
            self._emit_update_download_event(
                self._update_download_failed,
                {"sequence": sequence, "message": "已取消下载。"},
            )
            return
        self._emit_update_download_event(
            self._update_download_finished,
            {"sequence": sequence, "prepared": prepared},
        )

    def _on_update_download_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if self._update_download_shutdown:
            return
        if int(payload.get("sequence") or 0) != self._update_download_sequence:
            return
        dialog = self.__dict__.get("_update_download_dialog")
        if dialog is not None:
            dialog.set_progress(dict(payload.get("progress") or {}))

    def _on_update_download_finished(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if self._update_download_shutdown:
            return
        if int(payload.get("sequence") or 0) != self._update_download_sequence:
            return
        prepared = payload.get("prepared")
        if not isinstance(prepared, _PreparedUpdate):
            self._on_update_download_failed({"sequence": payload.get("sequence"), "message": "更新准备结果无效。"})
            return
        self._prepared_update = prepared
        self._update_download_cancel_event = None
        dialog = self.__dict__.get("_update_download_dialog")
        if dialog is not None:
            dialog.set_ready(prepared.installer_path)
        self.append_log(f"更新安装包已下载并通过校验: {Path(prepared.installer_path).name}")

    def _on_update_download_failed(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if self._update_download_shutdown:
            return
        if int(payload.get("sequence") or 0) != self._update_download_sequence:
            return
        self._update_download_cancel_event = None
        message = str(payload.get("message") or "更新下载失败")
        dialog = self.__dict__.get("_update_download_dialog")
        if dialog is not None:
            if "取消" in message or "cancel" in message.lower():
                dialog.set_cancelled()
            else:
                dialog.set_error(message)
        self.append_log(message, level="ERROR")

    def _cancel_update_download(self) -> None:
        cancel_event = self.__dict__.get("_update_download_cancel_event")
        if cancel_event is not None:
            cancel_event.set()
        dialog = self.__dict__.get("_update_download_dialog")
        if dialog is not None:
            dialog.set_cancelling()
        self.append_log("用户取消更新下载")

    def _retry_update_download(self) -> None:
        worker = self.__dict__.get("_update_download_thread")
        is_alive = getattr(worker, "is_alive", None)
        if callable(is_alive) and is_alive():
            self.append_log("正在等待上一次更新下载线程停止，暂不能重试。")
            return
        result = self.__dict__.get("_last_update_result")
        if not isinstance(result, UpdateCheckResult):
            self._show_update_check_error("没有可重试的更新任务。")
            return
        self._begin_update_download(result)

    def _install_prepared_update(self) -> None:
        prepared = self.__dict__.get("_prepared_update")
        if not isinstance(prepared, _PreparedUpdate):
            self._show_update_check_error("更新安装包尚未准备好。")
            return
        try:
            launch_prepared_update(
                PreparedUpdate(
                    installer_path=prepared.installer_path,
                    manifest_path=prepared.manifest_path,
                    signature_path=prepared.signature_path,
                    version=prepared.version,
                    log_path=prepared.log_path,
                ),
                restart_argv=self._restart_argv_after_update(),
            )
        except Exception as exc:
            self._show_update_check_error(str(exc))
            self.append_log(f"更新安装程序启动失败: {exc}", level="ERROR")
            return
        self.append_log("更新安装程序已启动，应用即将退出。")
        QTimer.singleShot(250, self.close)

    @staticmethod
    def _restart_argv_after_update() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, "-m", "entry.gui_entry"]

    @staticmethod
    def _download_verified_update(
        result: UpdateCheckResult,
        *,
        cancel_event: threading.Event | None = None,
        progress_callback=None,
    ) -> _PreparedUpdate:
        prepared = prepare_verified_update(
            result,
            public_key_pem=UPDATE_PUBLIC_KEY_PEM,
            require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE,
            manifest_verifier_cls=UpdateManifestVerifier,
            downloader_cls=Downloader,
            package_verifier_cls=PackageVerifier,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
        return _PreparedUpdate(
            installer_path=prepared.installer_path,
            manifest_path=prepared.manifest_path,
            signature_path=prepared.signature_path,
            version=prepared.version,
            log_path=prepared.log_path,
        )

    def _show_basic_message(
        self,
        title: str,
        text: str,
        informative_text: str = "",
        *,
        status: str = "info",
        local_version: str = "",
        latest_version: str = "",
        release_url: str = "",
    ) -> int:
        box = UpdateCheckDialog(
            self,
            title=title,
            message=text,
            details=informative_text,
            primary_text="确定",
            status=status,
            local_version=local_version,
            latest_version=latest_version,
            release_url=release_url,
            language=self._current_ui_language(),
        )
        return int(box.exec())

    @staticmethod
    def _display_version(version: str) -> str:
        value = str(version or "").strip()
        if not value:
            return "v?"
        return value if value.lower().startswith("v") else f"v{value}"

    def set_frontend_state_service(self, service: FrontendStateService) -> None:
        current_service = self.__dict__.get("_frontend_state_service")
        if current_service is not service and self.__dict__.get("_owns_frontend_state_service", False):
            destroy_current = getattr(current_service, "destroy", None)
            if callable(destroy_current):
                destroy_current()
        new_event_bus = service.app_state.event_bus
        if new_event_bus is not self.event_bus:
            self.event_bus.unsubscribe("app_state.changed", self._app_state_handler)
            self.event_bus = new_event_bus
            self._owns_event_bus = False
            self._app_state_handler = self._subscribe_app_state_changed()
        self._frontend_state_service = service
        self._owns_frontend_state_service = False
        set_cache_service = getattr(self.app_shell, "set_cache_service", None)
        if callable(set_cache_service):
            set_cache_service(getattr(service, "cache_service", None))
        self.app_state = service.app_state
        self._owns_app_state = False
        self._cached_snapshot = None
        self._frontend_section_signatures = {}
        self._frontend_snapshot_sequence = int(self.__dict__.get("_frontend_snapshot_sequence", 0) or 0) + 1
        self.refresh_frontend_state(force=True)

    def _subscribe_app_state_changed(self):
        subscribe_async = getattr(self.event_bus, "subscribe_async", None)
        if callable(subscribe_async):
            return subscribe_async("app_state.changed", self._queue_app_state_changed)
        return self.event_bus.subscribe("app_state.changed", self._queue_app_state_changed)

    def refresh_frontend_state(self, *, mock: bool = False, force: bool = False, topics: set[str] | None = None) -> None:
        if "app_shell" not in self.__dict__ or "_frontend_state_service" not in self.__dict__:
            return
        if topics:
            self._add_pending_refresh_topics(topics)
        if force:
            self._render_frontend_state(mock=mock, topics=None, force=True)
            return
        # 调度器合并待处理 `topic`，快照构建和 `delta` 合并交给后台 worker。
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

    def _render_frontend_state(self, *, mock: bool = False, topics: set[str] | None = None, force: bool = False) -> None:
        sections = self._sections_for_topics(topics)
        service = self._frontend_state_service
        cached = self.__dict__.get("_cached_snapshot")
        cached_version = self._snapshot_frontend_version(cached)
        # 有缓存且非强制刷新时优先请求 `delta`，减少 GUI 主线程需要局部更新的内容。
        use_delta = bool(cached is not None and not force and not mock)
        self._frontend_snapshot_sequence = int(self.__dict__.get("_frontend_snapshot_sequence", 0) or 0) + 1
        request = FrontendSnapshotRequest(
            sequence=self._frontend_snapshot_sequence,
            service=service,
            service_token=id(service),
            mock=mock,
            sections=sections,
            cached_snapshot=cached,
            section_signatures=dict(self.__dict__.get("_frontend_section_signatures") or {}),
            use_delta=use_delta,
            base_version=cached_version,
        )
        worker = self.__dict__.get("_frontend_snapshot_worker")
        if worker is None:
            raise RuntimeError("frontend snapshot worker is not initialized")
        worker.submit(request)

    @staticmethod
    def _snapshot_frontend_version(cached_snapshot) -> int:
        if not isinstance(cached_snapshot, dict):
            return 0
        try:
            return int(cached_snapshot.get("version") or 0)
        except (TypeError, ValueError):
            return 0

    def _on_frontend_snapshot_finished(self, result: FrontendSnapshotResult) -> None:
        current_sequence = int(self.__dict__.get("_frontend_snapshot_sequence", 0) or 0)
        service = self.__dict__.get("_frontend_state_service")
        if result.service_token != id(service):
            return

        is_stale = result.sequence != current_sequence
        # 迟到的部分结果仍可更新缓存签名，但不能触发渲染，否则页面会回滚。
        self._remember_frontend_snapshot_result(result, allow_stale_partial=not is_stale)
        if is_stale:
            return

        snapshot = result.snapshot
        self.__dict__["_last_frontend_snapshot_build_ms"] = float(result.build_duration_ms)
        if result.skip_render:
            return

        started = time.perf_counter()
        self.app_shell.render(
            snapshot,
            changed_sections=result.changed_sections,
            page_item_rows=result.page_item_rows,
            completed_item_ids=result.completed_item_ids,
        )
        self._record_frontend_render_duration((time.perf_counter() - started) * 1000)
        self._repair_black_shell_if_needed("_on_frontend_snapshot_finished")

    def _submit_frontend_action(self, action: str, payload: dict[str, object] | None = None) -> bool:
        service = self.__dict__.get("_frontend_state_service")
        worker = self.__dict__.get("_frontend_action_worker")
        if service is None or worker is None:
            return False
        # 设置保存、打开目录和失败重试交给 worker，UI 信号槽只分发请求与处理结果。
        self._frontend_action_sequence = int(self.__dict__.get("_frontend_action_sequence", 0) or 0) + 1
        worker.submit(
            FrontendActionRequest(
                sequence=self._frontend_action_sequence,
                service=service,
                service_token=id(service),
                action=str(action or ""),
                payload=dict(payload or {}),
            )
        )
        return True

    def _on_frontend_action_finished(self, result: FrontendActionResult) -> None:
        service = self.__dict__.get("_frontend_state_service")
        if result.service_token != id(service):
            return
        action_result = result.result if isinstance(result.result, dict) else {}
        if result.action == "log_operation":
            self._finish_log_operation(result.payload, action_result)
        elif result.action == "refresh_platform_auth_status":
            self._finish_refresh_platform_auth_status(action_result)
        elif result.action == "open_directory":
            self._finish_open_directory(action_result)
        elif result.action == "retry_failed":
            self._finish_retry_failed(action_result)
        elif result.action == "copy_diagnostics":
            self._finish_copy_diagnostics(action_result)
        elif result.action in {"delete_failed_record", "clear_failed_records"}:
            self._finish_failed_record_mutation(action_result)
        elif result.action == "update_download_options":
            self._finish_update_download_options(action_result)
        elif result.action == "pause_download":
            self._finish_pause_download(action_result)
        elif result.action == "run_tool":
            self._finish_run_tool(result.payload, action_result)
        elif result.action == "register_file_associations":
            self._finish_register_file_associations(action_result)
        elif result.action == "update_completed_metadata":
            self._finish_update_completed_metadata(action_result)
        elif result.action in {"update_basic_setting", "update_setting", "change_directory"}:
            self._finish_setting_update(result.payload, action_result)

    def _finish_log_operation(self, payload: dict[str, object], action_result: dict[str, object]) -> None:
        operation = str(payload.get("operation") or "")
        if operation not in {"clear", "refresh"}:
            message = action_result.get("message")
            if message:
                self.append_log(str(message))
        self._request_log_refresh(force=operation == "clear")

    def _finish_refresh_platform_auth_status(self, action_result: dict[str, object]) -> None:
        data = action_result.get("data") if isinstance(action_result, dict) else {}
        if isinstance(data, dict) and data.get("refreshed"):
            self.refresh_frontend_state(topics={"settings.platform_auth"})

    def _finish_open_directory(self, action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "open directory failed"), level="ERROR")

    def _finish_retry_failed(self, action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "retry failed"), level="ERROR")
        self.refresh_frontend_state(topics={"videos.replace"})

    def _finish_copy_diagnostics(self, action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "copy diagnostics failed"), level="ERROR")
            return
        data = action_result.get("data") if isinstance(action_result, dict) else {}
        text = (data or {}).get("text", "") if isinstance(data, dict) else ""
        if text:
            self._request_clipboard_copy(str(text))
        self.append_log(str(action_result.get("message") or "Trace ID copied"))

    def _finish_failed_record_mutation(self, action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "failed record mutation failed"), level="ERROR")
            self.refresh_frontend_state(force=True)
            return
        self.append_log(str(action_result.get("message") or "failed records updated"))
        self.refresh_frontend_state(topics={"failed_records.refresh"})

    def _finish_update_download_options(self, action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "download options update failed"), level="ERROR")
            return
        data = action_result.get("data") if isinstance(action_result, dict) else {}
        data = data if isinstance(data, dict) else {}
        self.append_log(
            f"Download options updated: concurrency={data.get('max_concurrent')}, retries={data.get('max_retries')}, auto_retry={data.get('auto_retry')}"
        )
        if self.__dict__.get("_cached_snapshot"):
            self._render_frontend_state(topics={"settings.update"})
        else:
            self.refresh_frontend_state(force=True)

    def _finish_pause_download(self, action_result: dict[str, object]) -> None:
        self.append_log(str(action_result.get("message") or "download paused"))
        self.refresh_frontend_state(topics={"videos.update"})

    def _finish_run_tool(self, payload: dict[str, object], action_result: dict[str, object]) -> None:
        tool_id = str(payload.get("tool_id") or "")
        self.append_log(str(action_result.get("message") or f"tool started: {tool_id}"))

    def _finish_register_file_associations(self, action_result: dict[str, object]) -> None:
        ok = action_result.get("status") == "ok"
        message = str(action_result.get("message") or ("file associations registered" if ok else "file association registration failed"))
        self.append_log(message, level="INFO" if ok else "ERROR")
        settings_page = getattr(getattr(self, "app_shell", None), "pages", {}).get("settings")
        feedback = getattr(settings_page, "show_action_feedback", None)
        if callable(feedback):
            feedback(message, ok=ok)
        self.refresh_frontend_state(topics={"settings.update"})

    def _finish_update_completed_metadata(self, action_result: dict[str, object]) -> None:
        data = action_result.get("data") if isinstance(action_result, dict) else {}
        if isinstance(data, dict) and data.get("changed"):
            self.refresh_frontend_state(topics={"videos.metadata"})

    def _finish_setting_update(self, payload: dict[str, object], action_result: dict[str, object]) -> None:
        if action_result.get("status") != "ok":
            self.append_log(str(action_result.get("message") or "setting update failed"), level="ERROR")
            self.refresh_frontend_state(topics={"settings.update"}, force=True)
            return
        data = action_result.get("data") if isinstance(action_result, dict) else {}
        data = data if isinstance(data, dict) else {}
        normalized_section = str(data.get("section") or payload.get("section") or "common")
        config_key = str(data.get("config_key") or data.get("key") or payload.get("key") or "")
        if config_key == "download_directory":
            config_key = "save_directory"
        value = data.get("value", payload.get("value"))
        frontend_state_service = self.__dict__.get("_frontend_state_service")
        config_observer_owns_runtime = (
            getattr(frontend_state_service, "_config_events_drive_runtime", False) is True
        )
        if normalized_section == "common" and config_key == "save_directory":
            directory = str(data.get("directory") or value or "")
            if directory and not config_observer_owns_runtime:
                changed = directory != self.current_save_dir
                self.current_save_dir = directory
                if changed:
                    self.sig_change_dir.emit()
            if config_observer_owns_runtime:
                return
        if normalized_section == "common" and config_key == "theme":
            source = str(payload.get("source") or "")
            if payload.get("ui_applied") is True and source in {"theme_toggle", "system_palette"}:
                if source == "theme_toggle":
                    try:
                        payload_sequence = int(payload.get("theme_sequence") or 0)
                    except (TypeError, ValueError):
                        payload_sequence = 0
                    current_sequence = int(self.__dict__.get("_theme_transition_sequence", 0) or 0)
                    if payload_sequence and payload_sequence != current_sequence:
                        return
                return
        extra_topics = self._apply_runtime_setting_after_update(normalized_section, config_key, value)
        self.refresh_frontend_state(topics={"settings.update", *extra_topics})

    def _remember_frontend_snapshot_result(
        self,
        result: FrontendSnapshotResult,
        *,
        allow_stale_partial: bool,
    ) -> None:
        snapshot = result.snapshot
        if not isinstance(snapshot, dict):
            return
        previous_version = self._snapshot_frontend_version(self.__dict__.get("_cached_snapshot"))
        snapshot_version = self._snapshot_frontend_version(snapshot)
        if previous_version and snapshot_version < previous_version:
            return
        if result.changed_sections is not None and not allow_stale_partial and not previous_version:
            return
        self.__dict__["_cached_snapshot"] = snapshot
        self.__dict__["_cached_frontend_version"] = snapshot_version
        self.__dict__["_frontend_section_signatures"] = dict(result.section_signatures)

    def _record_frontend_render_duration(self, duration_ms: float) -> None:
        self.__dict__["_last_frontend_render_ms"] = duration_ms
        if duration_ms <= self.FRONTEND_RENDER_WARN_MS:
            return
        scheduler = self.__dict__.get("_ui_update_scheduler")
        metrics = scheduler.metrics() if hasattr(scheduler, "metrics") else {}
        interval = int(metrics.get("interval_ms") or self.FRONTEND_REFRESH_INTERVAL_MS)
        if hasattr(scheduler, "set_interval_ms") and interval < self.FRONTEND_REFRESH_MAX_INTERVAL_MS:
            scheduler.set_interval_ms(min(self.FRONTEND_REFRESH_MAX_INTERVAL_MS, interval + 50))
        now_ms = int(time.monotonic() * 1000)
        last_warn_ms = int(self.__dict__.get("_last_frontend_render_warn_ms", 0) or 0)
        if now_ms - last_warn_ms < self.FRONTEND_RENDER_WARN_MIN_INTERVAL_MS:
            return
        self.__dict__["_last_frontend_render_warn_ms"] = now_ms
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
        self._request_log_refresh()

    def _queue_app_state_changed(self, payload) -> None:
        self._app_state_changed_queued.emit(payload)

    @safe_slot
    def _on_app_state_changed(self, payload) -> None:
        topic = ""
        if isinstance(payload, dict):
            topic = str(payload.get("topic") or "")
        if topic == "logs.append":
            # 日志追加频率高，单独的 `topic` 可让日志页使用更轻量的局部刷新路径。
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
        operation = str(operation or "").strip()
        if operation == "refresh" and self._should_throttle_log_refresh():
            return
        self._submit_frontend_action("log_operation", {"operation": operation})

    def _should_throttle_log_refresh(self) -> bool:
        now_ms = int(time.monotonic() * 1000)
        last_ms = int(self.__dict__.get("_last_manual_log_refresh_ms", 0) or 0)
        if now_ms - last_ms < self.LOG_REFRESH_THROTTLE_MS:
            self._request_log_refresh()
            return True
        self.__dict__["_last_manual_log_refresh_ms"] = now_ms
        return False

    def _request_log_refresh(self, *, force: bool = False) -> None:
        self._add_pending_refresh_topic("logs.append")
        self._ui_update_scheduler.schedule("logs.append", force=force)

    def _refresh_platform_auth_if_needed(self) -> None:
        self._submit_frontend_action("refresh_platform_auth_status", {})

    def _on_page_changed(self, page_id: str) -> None:
        self.app_state.set_visible_page(page_id, list(self.app_shell.pages), emit_change=False)
        if page_id == "settings":
            settings_page = self.app_shell.pages.get("settings")
            is_platform_visible = getattr(settings_page, "is_platform_settings_visible", None)
            if callable(is_platform_visible) and is_platform_visible():
                self._refresh_platform_auth_if_needed()
        self.refresh_frontend_state(topics={self._visibility_topic_for_page(page_id)})

    def bind_video_rename(self, on_rename) -> None:
        # 队列表格已不允许编辑标题；保留绑定入口，避免控制器感知展示层差异。
        self._title_rename_handler = on_rename

    def toggle_theme(self) -> None:
        # QSS 更新必须在 GUI 线程串行执行；连续点击只保留最后一次目标主题。
        if self.__dict__.get("_theme_transition_in_progress", False):
            base_theme = self.__dict__.get("_queued_theme_is_dark")
            if base_theme is None:
                base_theme = self.__dict__.get("_theme_transition_target_is_dark", self.is_dark_theme)
            self.__dict__["_queued_theme_is_dark"] = not bool(base_theme)
            self._set_theme_button_busy(True)
            return

        self._begin_theme_transition(not bool(self.is_dark_theme))

    def _begin_theme_transition(self, is_dark: bool) -> None:
        is_dark = bool(is_dark)
        last_applied = self.__dict__.get("_last_applied_theme_is_dark")
        if last_applied is not None and bool(last_applied) == is_dark:
            self._set_theme_icon_immediate(is_dark)
            self._set_theme_button_busy(False)
            return

        self.__dict__["_theme_transition_in_progress"] = True
        self.__dict__["_queued_theme_is_dark"] = None
        self.__dict__["_theme_transition_target_is_dark"] = is_dark
        self.__dict__["_theme_transition_sequence"] = int(
            self.__dict__.get("_theme_transition_sequence", 0) or 0
        ) + 1
        sequence = int(self.__dict__["_theme_transition_sequence"])
        self._set_theme_button_busy(True)
        QTimer.singleShot(0, lambda: self._commit_theme_toggle_interactive(is_dark, sequence))

    def _commit_theme_toggle_interactive(self, is_dark: bool, sequence: int) -> None:
        if sequence != int(self.__dict__.get("_theme_transition_sequence", 0) or 0):
            return
        queued_before_start = self.__dict__.pop("_queued_theme_is_dark", None)
        if queued_before_start is not None:
            is_dark = bool(queued_before_start)
            self.__dict__["_theme_transition_target_is_dark"] = is_dark
            if is_dark == bool(self.is_dark_theme):
                self._finish_theme_transition(bool(self.is_dark_theme), 0.0, failed=False, queued=True)
                return
        started = time.perf_counter()
        failed = False
        try:
            self._commit_theme_toggle(bool(is_dark), ui_already_serialized=True)
        except Exception as exc:
            failed = True
            debug_logger.log_exception(
                "MainWindow",
                "theme_transition",
                exc,
                details={"is_dark": bool(is_dark), "sequence": int(sequence)},
            )
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            self._finish_theme_transition(bool(self.is_dark_theme), duration_ms, failed=failed)

    def _finish_theme_transition(
        self,
        applied_is_dark: bool,
        duration_ms: float,
        *,
        failed: bool = False,
        queued: bool | None = None,
    ) -> None:
        applied_is_dark = bool(applied_is_dark)
        queued_after_apply = self.__dict__.pop("_queued_theme_is_dark", None)
        has_next = queued_after_apply is not None and bool(queued_after_apply) != bool(self.is_dark_theme)
        self._set_theme_icon_immediate(applied_is_dark)
        self.__dict__["_theme_transition_in_progress"] = False
        self.__dict__["_theme_transition_target_is_dark"] = None

        queued_exists = bool(queued) if queued is not None else has_next
        self._log_theme_transition_finished(
            applied_is_dark,
            duration_ms,
            queued=queued_exists,
            failed=failed,
        )
        if has_next:
            self._set_theme_button_busy(True)
            self._ensure_shell_chrome_visible(reason="theme_transition_queued")
            self._repair_black_shell_if_needed("theme_transition_queued")
            QTimer.singleShot(16, lambda: self._begin_theme_transition(bool(queued_after_apply)))
            return

        self._set_theme_button_busy(False)
        self._ensure_shell_chrome_visible(reason="theme_transition_finished")
        self._repair_black_shell_if_needed("theme_transition_finished")

    def _log_theme_transition_finished(
        self,
        is_dark: bool,
        duration_ms: float,
        *,
        queued: bool,
        failed: bool,
    ) -> None:
        visible_page = ""
        app_state = self.__dict__.get("app_state")
        get_visible_page = getattr(app_state, "get_visible_page", None)
        if callable(get_visible_page):
            try:
                visible_page = str(get_visible_page() or "")
            except RuntimeError:
                visible_page = ""
        is_slow = duration_ms > 80
        debug_logger.log(
            component="MainWindow",
            action="theme_transition_finished",
            level="ERROR" if failed else ("WARN" if is_slow else "INFO"),
            message="Theme transition failed" if failed else "Theme transition finished",
            status_code="THEME_TRANSITION_FAILED" if failed else ("THEME_APPLY_SLOW" if is_slow else "THEME_TRANSITION_FINISHED"),
            details={
                "apply_theme_duration_ms": round(float(duration_ms), 2),
                "visible_page": visible_page,
                "refresh_frontend_snapshot": bool(self.__dict__.get("_last_theme_refresh_frontend_snapshot", False)),
                "queued_theme": bool(queued),
                "is_dark": bool(is_dark),
            },
        )

    def _commit_theme_toggle(self, is_dark: bool, *, ui_already_serialized: bool = False) -> None:
        self.is_dark_theme = bool(is_dark)
        last_applied = self.__dict__.get("_last_applied_theme_is_dark")
        if last_applied is not None and bool(last_applied) == self.is_dark_theme:
            return
        payload = {"key": "theme", "value": "dark" if self.is_dark_theme else "light"}
        if ui_already_serialized:
            payload.update(
                {
                    "source": "theme_toggle",
                    "ui_applied": True,
                    "theme_sequence": int(self.__dict__.get("_theme_transition_sequence", 0) or 0),
                }
            )
        self._submit_frontend_action("update_basic_setting", payload)
        self._apply_theme_stylesheet(
            refresh_frontend_snapshot=False,
            update_theme_icon=False,
            freeze_updates=False,
        )
        self.append_log(f"已切换到{'深色' if self.is_dark_theme else '浅色'}主题")
        self.sig_theme_changed.emit(self.is_dark_theme)
        self.__dict__["_last_committed_theme_sequence"] = int(
            self.__dict__.get("_theme_transition_sequence", 0) or 0
        )

    def _set_theme_icon_immediate(self, is_dark: bool) -> None:
        top_bar = self.__dict__.get("top_bar")
        set_preview_icon = getattr(top_bar, "set_theme_preview_icon", None)
        if callable(set_preview_icon):
            set_preview_icon(bool(is_dark))

    def _set_theme_button_busy(self, busy: bool) -> None:
        top_bar = self.__dict__.get("top_bar")
        setter = getattr(top_bar, "set_theme_button_busy", None)
        if callable(setter):
            setter(bool(busy))

    def _persist_theme_config(
        self,
        is_dark: bool,
        *,
        source: str = "",
        ui_applied: bool = False,
    ) -> None:
        payload = {"key": "theme", "value": "dark" if is_dark else "light", "manual": False}
        if source:
            payload.update({"source": source, "ui_applied": bool(ui_applied)})
        self._submit_frontend_action("update_basic_setting", payload)

    def _apply_theme_stylesheet(
        self,
        *,
        refresh_shell_theme: bool = True,
        sync_settings_theme: bool = True,
        refresh_frontend_snapshot: bool = False,
        update_theme_icon: bool = True,
        freeze_updates: bool = False,
    ) -> None:
        self._debug_shell_visibility("before_theme_apply")
        self.__dict__["_last_theme_refresh_frontend_snapshot"] = bool(refresh_frontend_snapshot)
        freeze_states: list[tuple[QWidget, bool]] = []
        if freeze_updates and refresh_shell_theme:
            for widget in (self.__dict__.get("app_shell"),):
                if widget is None:
                    continue
                try:
                    if not widget.isVisible():
                        continue
                    was_enabled = bool(widget.updatesEnabled())
                    freeze_states.append((widget, was_enabled))
                    if was_enabled:
                        widget.setUpdatesEnabled(False)
                except RuntimeError:
                    continue
        try:
            if refresh_shell_theme:
                self._close_transient_popups_before_theme()
            self._apply_root_background()
            apply_application_theme(self.is_dark_theme)
            self._apply_root_background()
            window_chrome = self.__dict__.get("window_chrome")
            if window_chrome is not None:
                window_chrome.apply_theme(self.is_dark_theme)
            title_bar = self.__dict__.get("window_title_bar")
            if title_bar is not None and window_chrome is None:
                title_bar.apply_theme(self.is_dark_theme)
            top_bar = self.__dict__.get("top_bar")
            if top_bar is not None and refresh_shell_theme and update_theme_icon:
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
            self.__dict__["_last_applied_theme_is_dark"] = bool(self.is_dark_theme)
            self.__dict__["_theme_apply_refreshed_snapshot"] = False
            if refresh_frontend_snapshot and "_frontend_state_service" in self.__dict__:
                self._refresh_frontend_after_theme_change()
                self.__dict__["_theme_apply_refreshed_snapshot"] = True
            if not self.__dict__.get("_qt_initialized", False):
                return
        finally:
            for widget, was_enabled in reversed(freeze_states):
                try:
                    widget.setUpdatesEnabled(was_enabled)
                    if was_enabled:
                        widget.update()
                except RuntimeError:
                    continue
            if self.__dict__.get("_qt_initialized", False):
                self._ensure_shell_chrome_visible(reason="theme_apply_finally")
                self._repair_black_shell_if_needed("theme_apply_finally")
                if not self.__dict__.get("_theme_apply_refreshed_snapshot", False):
                    self._finalize_theme_repaint()
                self._debug_shell_visibility("after_theme_apply")

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

    def _debug_shell_visibility(self, reason: str) -> None:
        shell = self.__dict__.get("app_shell")
        widgets = {
            "main_window": self,
            "window_root": self.__dict__.get("window_root"),
            "window_title_bar": self.__dict__.get("window_title_bar"),
            "app_shell": shell,
            "control_island": getattr(shell, "control_island", None),
            "top_bar": self.__dict__.get("top_bar"),
            "sidebar": getattr(shell, "sidebar", None),
            "page_stack": getattr(shell, "stack", None),
            "status_island": getattr(shell, "status_island", None),
            "status_bar": getattr(shell, "status_bar", None),
            "media_panel": self.__dict__.get("media_panel"),
        }
        details: dict[str, dict[str, object]] = {}
        for name, widget in widgets.items():
            if widget is None:
                details[name] = {"exists": False}
                continue
            try:
                details[name] = {
                    "exists": True,
                    "visible": bool(widget.isVisible()),
                    "hidden": bool(widget.isHidden()),
                    "updates_enabled": bool(widget.updatesEnabled()),
                    "geometry": str(widget.geometry()),
                    "object_name": str(widget.objectName()),
                }
            except RuntimeError:
                details[name] = {"exists": True, "deleted": True}
        debug_logger.log(
            component="MainWindow",
            action="shell_visibility_probe",
            level="INFO",
            message=f"Shell visibility probe: {reason}",
            status_code="SHELL_VISIBILITY_PROBE",
            details=details,
        )

    def _media_panel_is_fullscreen(self) -> bool:
        media_panel = self.__dict__.get("media_panel")
        if media_panel is None:
            return False
        for attr in ("is_media_fullscreen", "is_fullscreen", "_is_fullscreen", "_fullscreen"):
            value = getattr(media_panel, attr, None)
            if callable(value):
                try:
                    return bool(value())
                except Exception:
                    continue
            if value is not None:
                return bool(value)
        try:
            return bool(getattr(media_panel, "_fullscreen_window", None) is not None)
        except RuntimeError:
            return False

    def _exit_stale_media_fullscreen_if_needed(self, *, reason: str = "") -> None:
        media_panel = self.__dict__.get("media_panel")
        if media_panel is None:
            return
        try:
            if getattr(media_panel, "_fullscreen_window", None) is None:
                return
        except RuntimeError:
            return
        exit_fullscreen = getattr(media_panel, "exit_media_fullscreen", None)
        if not callable(exit_fullscreen):
            return
        try:
            exit_fullscreen()
            debug_logger.log(
                component="MainWindow",
                action="exit_stale_media_fullscreen",
                level="WARN",
                message="Exited stale media fullscreen while restoring shell chrome",
                status_code="STALE_MEDIA_FULLSCREEN_EXITED",
                details={"reason": reason},
            )
        except Exception as exc:
            debug_logger.log_exception(
                "MainWindow",
                "exit_stale_media_fullscreen",
                exc,
                details={"reason": reason},
            )

    def _ensure_shell_chrome_visible(self, *, reason: str = "") -> None:
        if self.__dict__.get("is_fullscreen_mode", False):
            return
        try:
            if self.isFullScreen():
                return
        except RuntimeError:
            pass
        if self._media_panel_is_fullscreen():
            return

        shell = self.__dict__.get("app_shell")
        widgets = [
            self.__dict__.get("window_root"),
            self.__dict__.get("window_title_bar"),
            shell,
            getattr(shell, "control_island", None),
            getattr(shell, "top_bar", None),
            getattr(shell, "sidebar", None),
            getattr(shell, "stack", None),
            getattr(shell, "status_island", None),
            getattr(shell, "status_bar", None),
        ]
        for widget in widgets:
            if widget is None:
                continue
            try:
                widget.setUpdatesEnabled(True)
                widget.setVisible(True)
                widget.show()
                widget.updateGeometry()
                widget.update()
            except RuntimeError:
                continue
        self._debug_shell_visibility(f"ensure_shell_chrome_visible:{reason}")

    def _repair_black_shell_if_needed(self, reason: str = "") -> None:
        shell = self.__dict__.get("app_shell")
        top_bar = self.__dict__.get("top_bar")
        control_island = getattr(shell, "control_island", None)
        sidebar = getattr(shell, "sidebar", None)
        page_stack = getattr(shell, "stack", None)
        status_island = getattr(shell, "status_island", None)
        status_bar = getattr(shell, "status_bar", None)
        missing_shell = False
        for widget in (control_island, top_bar, sidebar, page_stack, status_island, status_bar):
            try:
                if widget is None or not widget.isVisible() or not widget.updatesEnabled():
                    missing_shell = True
                    break
            except RuntimeError:
                missing_shell = True
                break
        if not missing_shell:
            return
        debug_logger.log(
            component="MainWindow",
            action="repair_black_shell",
            level="WARN",
            message="Shell chrome was hidden unexpectedly; restoring shell chrome",
            status_code="BLACK_SHELL_REPAIR",
            details={"reason": reason},
        )
        self._ensure_shell_chrome_visible(reason=f"repair:{reason}")

    def _refresh_frontend_after_theme_change(self) -> None:
        self.refresh_frontend_state(topics={"settings.update"})

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
        if self.is_dark_theme == is_dark:
            self._persist_theme_config(is_dark, source="system_palette", ui_applied=True)
            return
        if self.__dict__.get("_theme_transition_in_progress", False):
            self.__dict__["_queued_theme_is_dark"] = is_dark
            return
        started = time.perf_counter()
        failed = False
        self._set_theme_button_busy(True)
        self._persist_theme_config(is_dark, source="system_palette", ui_applied=True)
        self.is_dark_theme = is_dark
        try:
            self._apply_theme_stylesheet(refresh_frontend_snapshot=False)
            self.sig_theme_changed.emit(is_dark)
        except Exception as exc:
            failed = True
            debug_logger.log_exception(
                "MainWindow",
                "system_palette_theme_transition",
                exc,
                details={"is_dark": bool(is_dark)},
            )
        finally:
            self._set_theme_icon_immediate(self.is_dark_theme)
            self._set_theme_button_busy(False)
            self._log_theme_transition_finished(
                bool(self.is_dark_theme),
                (time.perf_counter() - started) * 1000,
                queued=False,
                failed=failed,
            )

    def _toggle_maximized(self) -> None:
        if self.is_fullscreen_mode or self._safe_is_fullscreen():
            self._exit_legacy_main_fullscreen()
            return
        should_maximize = not self._is_effectively_maximized()
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = bool(should_maximize)
        self._apply_native_maximized_state(should_maximize)
        self._set_window_title_bar_maximized(should_maximize)
        QTimer.singleShot(80, self._sync_chrome_maximized_state)
        QTimer.singleShot(220, self._sync_chrome_maximized_state)

    def _is_effectively_maximized(self) -> bool:
        if bool(self.__dict__.get("_custom_maximized", False)):
            return True
        return self._safe_is_native_maximized()

    def _apply_native_maximized_state(self, maximized: bool) -> None:
        if sys.platform.startswith("win"):
            try:
                hwnd = int(self.winId())
                if self._chrome_controller().set_hwnd_maximized(hwnd, bool(maximized)):
                    return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            except Exception as exc:
                debug_logger.log_exception("MainWindow", "set_hwnd_maximized", exc)
        if maximized:
            self.showMaximized()
        else:
            self.showNormal()

    def _refresh_native_maximize_requested_state(self) -> None:
        self.__dict__["_native_maximize_requested"] = self._safe_is_native_maximized()

    def _sync_chrome_maximized_state(self) -> None:
        self._refresh_native_maximize_requested_state()
        self._sync_window_title_bar_state()

    def _maximize_to_work_area(self) -> None:
        if not self.__dict__.get("_qt_initialized", False):
            self.showMaximized()
            return
        if not self._safe_is_native_maximized() and not self.__dict__.get("_custom_maximized", False):
            self._pre_custom_maximize_geometry = QRect(self.geometry())
        if self.isFullScreen():
            self.showNormal()
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = True
        self._apply_native_maximized_state(True)

    def _restore_from_custom_or_native_maximized(self) -> None:
        custom_maximized = bool(self.__dict__.get("_custom_maximized", False))
        geometry = self.__dict__.get("_pre_custom_maximize_geometry") if custom_maximized else None
        if self.isFullScreen():
            self.showNormal()
        elif self._safe_is_native_maximized():
            self._apply_native_maximized_state(False)
        self.__dict__["_custom_maximized"] = False
        self.__dict__["_native_maximize_requested"] = False
        self._pre_custom_maximize_geometry = None
        if custom_maximized and isinstance(geometry, QRect) and geometry.isValid():
            self.setGeometry(geometry)

    def _set_window_title_bar_maximized(self, maximized: bool) -> None:
        title_bar = self.__dict__.get("window_title_bar")
        if title_bar is not None:
            title_bar.set_maximized(bool(maximized))

    def _sync_window_title_bar_state(self) -> None:
        self._set_window_title_bar_maximized(self._is_effectively_maximized())

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
        """保留旧入口，但主窗口不再进入全屏。

        全屏状态归媒体预览窗口所有。主窗口保留 Qt::WindowFullScreen 会使 Windows
        Shell 在恢复后误判自动隐藏任务栏的激活区域，因此旧调用只负责清理残留状态
        或转交媒体面板。
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

    def _windows_hwnd_is_zoomed(self) -> bool | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            hwnd = int(self.winId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        try:
            return bool(self._chrome_controller()._is_hwnd_maximized(hwnd))
        except Exception:
            return None

    def _qt_reports_native_maximized(self) -> bool:
        try:
            return bool(self.windowState() & Qt.WindowState.WindowMaximized) or bool(self.isMaximized())
        except (AttributeError, RuntimeError):
            return False

    def _safe_is_native_maximized(self) -> bool:
        # 无边框窗口经 Snap/还原后 Qt 状态可能滞后；Windows 上以 Win32 IsZoomed 为真值。
        windows_zoomed = self._windows_hwnd_is_zoomed()
        if windows_zoomed is not None:
            return bool(windows_zoomed)
        return self._qt_reports_native_maximized()

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
            self._sync_chrome_maximized_state()
            QTimer.singleShot(0, self._sync_chrome_maximized_state)
            QTimer.singleShot(80, self._sync_chrome_maximized_state)

    def load_initial_state(self) -> None:
        last_source_id = cfg.get("common", "last_source", "kuaishou")
        index = self.combo_source.findData(last_source_id)
        self.combo_source.setCurrentIndex(index if index != -1 else 0)
        self.on_source_changed(self.combo_source.currentIndex())
        visible_page = self.app_state.get_visible_page()
        if visible_page in self.app_shell.pages:
            self.app_shell.show_page(visible_page, emit_change=False, render_page=False)
        window_state_persistence.restore_window_state(self, cfg)

    @safe_slot
    def closeEvent(self, event) -> None:
        ui_state_snapshot = window_state_persistence.capture_window_state(self)
        # 先停止调度器和 worker 再销毁服务，避免后台线程回调已释放的 QObject。
        update_download_lock = self.__dict__.get("_update_download_lock")
        if update_download_lock is None:
            update_download_lock = threading.RLock()
            self._update_download_lock = update_download_lock
        with update_download_lock:
            self._update_download_shutdown = True
            self._update_download_sequence = int(self.__dict__.get("_update_download_sequence", 0) or 0) + 1
            update_cancel_event = self.__dict__.get("_update_download_cancel_event")
        if update_cancel_event is not None:
            update_cancel_event.set()
        update_download_thread = self.__dict__.get("_update_download_thread")
        is_alive = getattr(update_download_thread, "is_alive", None)
        join = getattr(update_download_thread, "join", None)
        if (
            update_download_thread is not threading.current_thread()
            and callable(is_alive)
            and is_alive()
            and callable(join)
        ):
            join(timeout=self.UPDATE_DOWNLOAD_SHUTDOWN_JOIN_SECONDS)
        self._ui_update_scheduler.stop()
        snapshot_worker = self.__dict__.get("_frontend_snapshot_worker")
        if snapshot_worker is not None:
            snapshot_worker.shutdown()
        action_worker = self.__dict__.get("_frontend_action_worker")
        if action_worker is not None:
            action_worker.shutdown()
        update_check_worker = self.__dict__.get("_update_check_worker")
        if update_check_worker is not None:
            update_check_worker.shutdown()
        frontend_state_service = self.__dict__.get("_frontend_state_service")
        if self.__dict__.get("_owns_frontend_state_service", False) and frontend_state_service is not None:
            destroy_frontend_state = getattr(frontend_state_service, "destroy", None)
            if callable(destroy_frontend_state):
                destroy_frontend_state()
        app_state = self.__dict__.get("app_state")
        if self.__dict__.get("_owns_app_state", False) and app_state is not None:
            shutdown_app_state = getattr(app_state, "shutdown", None)
            if callable(shutdown_app_state):
                shutdown_app_state()
        self._connections.disconnect_all()
        self._remove_frameless_resize_event_filter()
        self._remove_windows_native_frame_filter()
        self.cleanup_media()
        self.event_bus.unsubscribe("app_state.changed", self._app_state_handler)
        event_bus_shutdown = getattr(self.event_bus, "shutdown", None)
        if self.__dict__.get("_owns_event_bus", False) and callable(event_bus_shutdown):
            event_bus_shutdown()
        window_state_persistence.start_window_state_persistence(self, ui_state_snapshot, cfg.save_ui_state)
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
        if not self._apply_source_runtime(plugin_id):
            return
        self._submit_frontend_action("update_basic_setting", {"key": "last_source", "value": plugin_id})

    def _apply_source_runtime(self, plugin_id: str) -> bool:
        plugin_id = str(plugin_id or "")
        plugin = registry.get_plugin(plugin_id)
        if plugin is None:
            return False
        self.current_plugin = plugin
        defaults = get_platform_runtime_defaults(plugin_id)
        top_bar = getattr(self, "top_bar", None)
        if top_bar is not None:
            top_bar.configure_for_platform(plugin_id, defaults)
        else:
            self.inp_search.setPlaceholderText(plugin.get_search_placeholder())
        return True

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
        if normalize_media_path(selected_dir) == normalize_media_path(self.current_save_dir):
            # Re-selecting the active directory is an explicit refresh request.
            self.sig_change_dir.emit()
            return
        self.set_current_save_dir(selected_dir, persist=True)

    def set_current_save_dir(self, save_dir: str, *, persist: bool = False) -> None:
        if persist:
            if self._submit_frontend_action("update_basic_setting", {"key": "download_directory", "value": save_dir}):
                return
        self.current_save_dir = save_dir
        self.refresh_frontend_state(topics={"settings.update"} if persist else None)

    def add_video_row(self, video_item) -> None:
        self._frontend_state_service.upsert_video(video_item)

    def add_video_rows(self, video_items) -> None:
        self._frontend_state_service.upsert_videos(list(video_items or []))

    def update_video_status(self, video_id, status, progress=None) -> None:
        # Controller 原地更新 VideoItem；UI 统一由 app_state.changed 驱动，避免重复渲染。
        return

    def refresh_table_bindings(self) -> None:
        self.refresh_frontend_state(topics={"videos.replace"})

    def reorder_video_row(self, video_item) -> int:
        self._frontend_state_service.upsert_video(video_item)
        self.refresh_frontend_state(topics={"videos.replace"})
        return self.app_shell.row_for_video_id(video_item.id)

    def clear_video_rows(self) -> None:
        self._frontend_state_service.clear_videos()

    def remove_video_row(self, row: int, video_id: str | None = None) -> None:
        """确认控制器已完成的删除并刷新视图，不再二次修改 AppState。"""
        del row
        pending_ids = self._pending_delete_ids()
        target_id = str(video_id or "")
        if target_id:
            if target_id in pending_ids:
                pending_ids.remove(target_id)
        elif pending_ids:
            pending_ids.pop(0)
        self.refresh_frontend_state(topics={"videos.remove"})

    def show_selection_dialog(self, items):
        selected = None
        try:
            normalized_items = items or []
            if not normalized_items:
                return []
            dialog = SelectionDialog(self, items=normalized_items, language=self._current_ui_language())
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

    def get_adjacent_image_id(self, current_video_id: str | None, direction: int, *, wrap: bool = True) -> str | None:
        image_order = self.app_shell.completed_image_id_order()
        if len(image_order) <= 1:
            return None
        current_index = image_order.index(current_video_id) if current_video_id in image_order else -1
        if current_index == -1:
            return image_order[0] if direction >= 0 else image_order[-1]
        next_index = current_index + (1 if direction >= 0 else -1)
        if wrap:
            next_index %= len(image_order)
        elif next_index < 0 or next_index >= len(image_order):
            return None
        return image_order[next_index]

    def select_video_by_id(self, video_id: str) -> bool:
        return self.app_shell.select_video_id(video_id)

    def show_completed_item(self, video_id: str) -> None:
        """切到已完成页，并在异步列表首轮渲染后补一次目标选择。"""
        self.app_shell.show_page("completed")
        if not self.app_shell.select_video_id(video_id):
            QTimer.singleShot(100, lambda item_id=video_id: self.app_shell.select_video_id(item_id))

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
        self._register_file_associations_from_frontend(choice.include_video, choice.include_image)

    def show_file_association_dialog(self):
        dialog = FileAssociationDialog(self, language=self._current_ui_language())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.choice()

    def show_image(self, image_path: str) -> None:
        slideshow_available = len(self.app_shell.completed_image_id_order()) > 1
        self.app_shell.show_image(image_path, slideshow_available=slideshow_available)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        controller = self._chrome_controller()
        controller.install()
        controller.on_show_event()
        self._ensure_shell_chrome_visible(reason="show_event")
        self._repair_black_shell_if_needed("show_event")
        self._debug_shell_visibility("show_event")

    def nativeEvent(self, event_type, message):
        hit_test = self._chrome_controller().handle_native_event(event_type, message)
        if hit_test is not None:
            return True, hit_test
        return False, 0

    def _handle_frameless_native_event(self, _event_type, message) -> int | None:
        return self._chrome_controller().handle_native_event(_event_type, message)

    def _dwm_def_window_proc(self, msg) -> int | None:
        return self._chrome_controller()._dwm_def_window_proc(msg)

    def _native_msg_belongs_to_this_window(self, msg) -> bool:
        return self._chrome_controller()._native_msg_belongs_to_this_window(msg)

    def _apply_windows_frameless_window_style(self) -> None:
        self._chrome_controller().apply_windows_frameless_window_style()

    def _handle_nc_calc_size(self, msg) -> int:
        return self._chrome_controller()._handle_nc_calc_size(msg)

    def _monitor_info_for_hwnd(self, hwnd):
        return self._chrome_controller()._monitor_info_for_hwnd(hwnd)

    def _is_hwnd_maximized(self, hwnd) -> bool:
        return self._chrome_controller()._is_hwnd_maximized(hwnd)

    def _window_dpi(self, hwnd) -> int:
        return self._chrome_controller()._window_dpi(hwnd)

    def _system_metric_for_hwnd(self, metric: int, hwnd) -> int:
        return self._chrome_controller()._system_metric_for_hwnd(metric, hwnd)

    def _resize_border_thickness_for_hwnd(self, hwnd, *, horizontal: bool) -> int:
        return self._chrome_controller()._resize_border_thickness_for_hwnd(hwnd, horizontal=horizontal)

    def _native_client_pos_from_lparam(self, msg) -> QPoint:
        return self._chrome_controller()._native_client_pos_from_lparam(msg)

    def _native_client_size_for_hwnd(self, hwnd) -> tuple[int, int]:
        return self._chrome_controller()._native_client_size_for_hwnd(hwnd)

    def _qt_dpr(self) -> float:
        return self._chrome_controller()._qt_dpr()

    def _widget_rect_client_px(self, widget: QWidget | None) -> tuple[int, int, int, int] | None:
        return self._chrome_controller()._widget_rect_client_px(widget)

    @staticmethod
    def _point_in_rect_px(rect: tuple[int, int, int, int] | None, x: int, y: int) -> bool:
        return FramelessWindowChromeController._point_in_rect_px(rect, x, y)

    def _win32_hit_test(self, msg) -> int:
        return self._chrome_controller()._win32_hit_test(msg)

    def _apply_auto_hide_taskbar_reserve_to_rect(self, rect, edge: int | None) -> None:
        self._chrome_controller()._apply_auto_hide_taskbar_reserve_to_rect(rect, edge)

    def _handle_get_min_max_info(self, msg) -> None:
        self._chrome_controller()._handle_get_min_max_info(msg)

    @staticmethod
    def _rect_edges(rect) -> tuple[int, int, int, int]:
        return FramelessWindowChromeController._rect_edges(rect)

    @classmethod
    def _rects_intersect(cls, first, second) -> bool:
        return FramelessWindowChromeController._rects_intersect(first, second)

    @classmethod
    def _adjust_work_area_for_auto_hide_taskbar(cls, monitor_rect, work_rect, edge: int | None) -> tuple[int, int, int, int]:
        return FramelessWindowChromeController.adjust_work_area_for_auto_hide_taskbar(monitor_rect, work_rect, edge)

    def _copy_rect_to_appbar_data(self, data, rect) -> None:
        self._chrome_controller()._copy_rect_to_appbar_data(data, rect)

    def _auto_hide_taskbar_edge_for_monitor(self, monitor_rect) -> int | None:
        return self._chrome_controller()._auto_hide_taskbar_edge_for_monitor(monitor_rect)

    @classmethod
    def _global_pos_from_lparam(cls, lparam: int) -> QPoint:
        return FramelessWindowChromeController.global_pos_from_lparam(lparam)

    @staticmethod
    def _signed_word(value: int) -> int:
        return FramelessWindowChromeController._signed_word(value)

    def _uses_windows_native_resize(self) -> bool:
        return self._chrome_controller()._uses_windows_native_resize()

    def _frameless_resize_margins(self) -> tuple[int, int]:
        return self._chrome_controller().frameless_resize_margins()

    @staticmethod
    def _point_in_leading_edge(value: int, start: int, thickness: int) -> bool:
        return FramelessWindowChromeController._point_in_leading_edge(value, start, thickness)

    @staticmethod
    def _point_in_trailing_edge(value: int, end: int, thickness: int) -> bool:
        return FramelessWindowChromeController._point_in_trailing_edge(value, end, thickness)

    def _frameless_hit_test(self, global_pos: QPoint) -> int | None:
        return self._chrome_controller().frameless_hit_test(global_pos)

    def _frameless_resize_edges_for_global_pos(self, global_pos: QPoint):
        return self._chrome_controller().frameless_resize_edges_for_global_pos(global_pos)

    @staticmethod
    def _cursor_for_resize_edges(edges) -> Qt.CursorShape | None:
        return FramelessWindowChromeController.cursor_for_resize_edges(edges)

    def _set_frameless_resize_cursor(self, cursor: Qt.CursorShape | None) -> None:
        self._chrome_controller()._set_frameless_resize_cursor(cursor)

    def _update_frameless_resize_cursor(self, global_pos: QPoint) -> None:
        self._chrome_controller()._update_frameless_resize_cursor(global_pos)

    def _start_frameless_system_resize(self, global_pos: QPoint) -> bool:
        return self._chrome_controller()._start_frameless_system_resize(global_pos)

    def _install_frameless_resize_event_filter(self) -> None:
        self._chrome_controller().install_frameless_resize_event_filter()

    def _install_windows_native_frame_filter(self) -> None:
        self._chrome_controller().install_windows_native_frame_filter()

    def _remove_windows_native_frame_filter(self) -> None:
        self._chrome_controller().remove_windows_native_frame_filter()

    def _remove_frameless_resize_event_filter(self) -> None:
        self._chrome_controller().remove_frameless_resize_event_filter()

    def _event_belongs_to_this_window(self, watched: object) -> bool:
        return self._chrome_controller()._event_belongs_to_this_window(watched)

    @staticmethod
    def _mouse_event_global_pos(event) -> QPoint:
        return FramelessWindowChromeController._mouse_event_global_pos(event)

    def mousePressEvent(self, event) -> None:
        if self._chrome_controller().mouse_press_event(event):
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if self._chrome_controller().event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_chrome_maximized_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_chrome_maximized_state()
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
        self._submit_frontend_action("open_directory", {"video_id": video_id})

    def _retry_failed_item(self, video_id: str) -> None:
        self._submit_frontend_action("retry_failed", {"video_id": video_id})

    def _copy_item_diagnostics(self, video_id: str) -> None:
        self._submit_frontend_action("copy_diagnostics", {"video_id": video_id})

    def _delete_failed_record(self, video_id: str) -> None:
        self._submit_frontend_action("delete_failed_record", {"video_id": video_id})

    def _clear_failed_records(self) -> None:
        self._submit_frontend_action("clear_failed_records", {})

    @safe_slot
    def _update_basic_setting(self, section: str, key: str, value) -> None:
        normalized_section = str(section or "common")
        action = "update_basic_setting" if normalized_section == "common" else "update_setting"
        payload = {"key": key, "value": value}
        if action == "update_setting":
            payload["section"] = normalized_section
        self._submit_frontend_action(action, payload)

    def _apply_runtime_setting_after_update(self, section: str, key: str, value) -> set[str]:
        """配置提交观察者应用运行时状态后，返回额外刷新 `topic`。"""
        del key, value
        section = str(section or "")
        topics: set[str] = set()
        if section == "logging":
            topics.add("logs.append")
        return topics

    @safe_slot
    def _apply_platform_runtime_setting(self, section: str, key: str, value) -> None:
        if str(key or "") not in {"max_items", "max_pages", "search_max_pages"}:
            return
        current_plugin_id = str(getattr(getattr(self, "current_plugin", None), "id", "") or "")
        if not section or str(section) != current_plugin_id:
            return
        top_bar = getattr(self, "top_bar", None)
        if top_bar is None:
            return
        try:
            top_bar.configure_for_platform(str(section), get_platform_runtime_defaults(str(section)))
            top_bar.set_video_count(int(value))
        except (TypeError, ValueError, AttributeError) as exc:
            debug_logger.log_exception(
                "MainWindow",
                "sync_top_quantity_after_setting",
                exc,
                details={"section": section, "key": key, "value": value},
            )

    @safe_slot
    def _apply_common_setting(self, key: str, value) -> None:
        key = str(key or "")
        if key == "last_source":
            plugin_id = str(value or "")
            index = self.combo_source.findData(plugin_id)
            if index >= 0:
                # 外部配置回放不应再次触发保存信号，否则会形成跨入口回写环。
                blocker = QSignalBlocker(self.combo_source)
                self.combo_source.setCurrentIndex(index)
                del blocker
                self._apply_source_runtime(plugin_id)
            return
        if key == "save_directory":
            directory = str(value or cfg.get("common", "save_directory", self.current_save_dir) or "")
            if directory:
                changed = directory != self.current_save_dir
                self.current_save_dir = directory
                if changed:
                    self.sig_change_dir.emit()
                self.refresh_frontend_state(topics={"settings.update"})
            return
        if key in {"theme", "dark_theme"}:
            self._apply_appearance_runtime_settings(key)
            self.sig_theme_changed.emit(self.is_dark_theme)
            return
        if key in {"default_open_mode", "open_after_download", "filename_template"}:
            self.refresh_frontend_state(topics={"settings.update"})

    @safe_slot
    def _on_external_config_changed(self, _payload=None) -> None:
        """其他 GUI/Web 进程提交设置后刷新控件。"""
        self.refresh_frontend_state(topics={"settings.update"}, force=True)

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
            if (
                changed_key in {"theme", "dark_theme"}
                and self.__dict__.get("_last_applied_theme_is_dark") == self.is_dark_theme
            ):
                self._set_theme_icon_immediate(self.is_dark_theme)
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
        self._submit_frontend_action("update_download_options", options or {})

    def _update_completed_metadata(self, video_id: str, metadata: dict) -> None:
        self._submit_frontend_action(
            "update_completed_metadata",
            {"video_id": video_id, "metadata": metadata or {}, "source": "gui_player"},
        )

    def _pause_download_item(self, video_id: str) -> None:
        self._submit_frontend_action("pause_download", {"video_id": video_id})

    def _run_tool(self, tool_id: str) -> None:
        self._submit_frontend_action("run_tool", {"tool_id": tool_id})

    def _register_file_associations_from_frontend(self, include_video: bool, include_image: bool) -> None:
        self._submit_frontend_action(
            "register_file_associations", {"include_video": include_video, "include_image": include_image}
        )
