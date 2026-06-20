#!/usr/bin/env python3
"""Desktop application composition root."""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from typing import Sequence

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from app.config import cfg
from app.models import VideoItem
from app.controllers.application_lifecycle_mixin import ApplicationLifecycleMixin
from app.controllers.controller_host_mixin import ControllerHostMixin
from app.controllers.crawl_controller_mixin import CrawlControllerMixin
from app.controllers.debug_controller_mixin import DebugControllerMixin
from app.controllers.desktop_host import DesktopHostAdapter
from app.controllers.download_controller_mixin import DownloadControllerMixin
from app.controllers.event_bridge import DomainEventBridge
from app.core.event_bus import EventBus
from app.controllers.media_host_controller_mixin import MediaHostControllerMixin
from app.controllers.media_library_mixin import MediaLibraryMixin
from app.core.download_manager import DownloadManager
from app.core.plugin_registry import registry
from app.debug_logger import debug_logger
from app.services.app_state import AppState
from app.services.cache_service import CacheService
from app.services.debug_service import DebugArtifactsService
from app.services.file_service import MediaLibraryService
from app.services.frontend_state_service import FrontendStateService
from app.services.media_release_coordination import (
    normalize_media_path,
    poll_media_release_request,
    publish_media_release_request,
)
from app.ui.main_window import MainWindow
from app.utils.qt_runtime import MAIN_APP_USER_MODEL_ID, ensure_windows_app_user_model_id, load_qt_icon
from app.utils.runtime_paths import install_root
from shared.controller_session import ControllerSessionMixin
from shared.spider_session_runtime import SpiderSession

class ApplicationController(
    ControllerHostMixin,
    CrawlControllerMixin,
    DownloadControllerMixin,
    DebugControllerMixin,
    ApplicationLifecycleMixin,
    MediaHostControllerMixin,
    ControllerSessionMixin,
    MediaLibraryMixin,
):
    """Compose desktop UI, services, event bridges, and long-running workers."""

    VIDEO_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".m4v", ".webm", ".m3u8", ".ts")
    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    MEDIA_FILE_EXTENSIONS = VIDEO_EXTENSIONS + IMAGE_EXTENSIONS
    DOWNLOAD_LOG_COMPONENT = "ApplicationController"
    DOWNLOAD_FINISHED_STATUS_CODE = "APP_DL_FINISH"
    DOWNLOAD_ERROR_STATUS_CODE = "APP_DL_ERROR"
    DOWNLOAD_FINISHED_MESSAGE = "下载任务完成"
    DOWNLOAD_ERROR_MESSAGE = "下载任务失败"
    MEDIA_DELETE_COORDINATION_DELAY_SEC = 0.45
    MEDIA_RELEASE_POLL_INTERVAL_MS = 200

    def __init__(self, launch_args: Sequence[str] | None = None):
        self.project_root = install_root()
        self.launch_media_paths = self._collect_launch_media_paths(launch_args or ())
        self.app = self._create_application()
        self.file_service = MediaLibraryService(self.VIDEO_EXTENSIONS, self.IMAGE_EXTENSIONS)
        self.debug_service = DebugArtifactsService()
        self.spider_session = SpiderSession(registry)
        self.event_bus = EventBus()
        self.cache_service = CacheService(namespace="frontend_state")
        self.app_state = AppState(event_bus=self.event_bus, cache_service=self.cache_service)

        self._log_app_init()
        self._configure_application_identity()
        self._create_window_host()
        self._initialize_event_bridges()
        self._initialize_runtime_state()
        self._initialize_media_release_coordination()

        self.dl_manager = DownloadManager(max_concurrent=cfg.get("download", "max_concurrent", 3))
        self.frontend_state_service = FrontendStateService(self, app_state=self.app_state, cache_service=self.cache_service)
        if hasattr(self.window, "set_frontend_state_service"):
            self.window.set_frontend_state_service(self.frontend_state_service)
        self._connect_download_signals()
        self._connect_window_signals()

        if self.launch_media_paths:
            QTimer.singleShot(200, self._open_first_launch_media)
        else:
            QTimer.singleShot(200, self.scan_local_dir)
        self._log_app_ready()

    @classmethod
    def _collect_launch_media_paths(cls, launch_args: Sequence[str]) -> list[str]:
        """Keep supported media file paths passed on the command line (file association / double-click)."""
        paths: list[str] = []
        seen: set[str] = set()
        for arg in launch_args:
            token = str(arg or "").strip().strip('"')
            if not token or token.startswith("-"):
                continue
            path = Path(token)
            try:
                resolved = str(path.resolve())
            except OSError:
                continue
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in cls.MEDIA_FILE_EXTENSIONS:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
        return paths

    def _open_first_launch_media(self) -> None:
        """Open the first launch argument media file after switching to its directory."""
        paths = list(self.launch_media_paths or [])
        if not paths:
            return
        target_path = paths[0]
        target_dir = os.path.dirname(target_path)
        host = self._host()
        if target_dir:
            host.set_current_save_dir(target_dir, persist=False)
        self.scan_local_dir()
        video_id = self._video_id_for_local_path(target_path)
        if video_id is None:
            item = self._video_item_for_launch_path(target_path)
            self._store_video_item(item)
            video_id = item.id
            host.refresh_frontend_state(force=True)
        if video_id is None:
            return
        host.select_video_by_id(video_id)
        self.play_video(video_id)

    def _video_id_for_local_path(self, file_path: str) -> str | None:
        normalized = normalize_media_path(file_path)
        if not normalized:
            return None
        with self._video_state_guard():
            for video_id, item in self.videos.items():
                if normalize_media_path(getattr(item, "local_path", "")) == normalized:
                    return video_id
        return None

    def _video_item_for_launch_path(self, file_path: str) -> VideoItem:
        path = Path(file_path)
        item = VideoItem(url="", title=path.stem, source="local")
        self._prepare_local_item(item)
        item.local_path = str(path.resolve())
        suffix = path.suffix.lower()
        if suffix in self.VIDEO_EXTENSIONS:
            item.meta["content_type"] = "video"
        elif suffix in self.IMAGE_EXTENSIONS:
            item.meta["content_type"] = "image"
        return item

    @staticmethod
    def _create_application() -> QApplication:
        return QApplication(sys.argv)

    def _log_app_init(self) -> None:
        debug_logger.log(
            component="ApplicationController",
            action="app_init",
            message="应用开始初始化",
            status_code="APP_INIT",
            details={"project_root": str(self.project_root)},
        )

    def _configure_application_identity(self) -> None:
        self.app.setApplicationName("Universal Crawler Pro")
        self.app.setOrganizationName("UCP")
        ensure_windows_app_user_model_id(MAIN_APP_USER_MODEL_ID)
        icon = load_qt_icon(["favicon.ico"], fallback_names=["Web.ico"])
        if icon is not None:
            self.app.setWindowIcon(icon)

    def _create_window_host(self) -> None:
        self.window = MainWindow(app_state=self.app_state, event_bus=self.event_bus)
        self.window.show()
        self.host = DesktopHostAdapter(self.window)
        self.app.aboutToQuit.connect(self.shutdown)

    def _initialize_event_bridges(self) -> None:
        self._spider_bridge = DomainEventBridge()
        self._spider_bridge.sig_event.connect(
            lambda event: self.event_bus.publish("spider.domain_event", event),
            Qt.ConnectionType.QueuedConnection,
        )
        self._download_bridge = self.EVENT_BRIDGE_CLASS()
        self._download_bridge.sig_event.connect(
            lambda event: self.event_bus.publish("download.domain_event", event),
            Qt.ConnectionType.QueuedConnection,
        )
        self.event_bus.subscribe("spider.domain_event", self._dispatch_spider_event)
        self.event_bus.subscribe("download.domain_event", self._dispatch_download_event)

    def _initialize_runtime_state(self) -> None:
        self.videos = self.app_state.videos
        self.current_playing_id: str | None = None
        self.app_state.set_current_playing_id(None)
        self.current_spider = None
        self._active_spider_bindings = None
        self._last_media_release_request_id: str | None = None

    def _video_state_guard(self):
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            return app_state._lock
        lock = getattr(self, "_videos_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._videos_lock = lock
        return lock

    def _video_lookup(self, video_id: str) -> VideoItem | None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            with app_state._lock:
                return app_state.videos.get(video_id)
        with self._video_state_guard():
            return self.videos.get(video_id)

    def _store_video_item(self, item: VideoItem) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.upsert_video(item)
            return
        with self._video_state_guard():
            self.videos[item.id] = item

    def _remove_video_item(self, video_id: str) -> VideoItem | None:
        app_state = getattr(self, "app_state", None)
        if app_state is None:
            with self._video_state_guard():
                return self.videos.pop(video_id, None)
        with app_state._lock:
            item = app_state.videos.pop(video_id, None)
            if item is not None:
                app_state.task_state.pop(video_id, None)
                app_state._last_progress_emit_at.pop(video_id, None)
        if item is not None:
            app_state._publish_change("videos.remove", {"video_id": video_id})
        return item

    def _video_items_snapshot(self) -> dict[str, VideoItem]:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            return app_state.snapshot_videos()
        with self._video_state_guard():
            return dict(self.videos)

    def _initialize_media_release_coordination(self) -> None:
        self._media_release_timer = QTimer()
        self._media_release_timer.setInterval(self.MEDIA_RELEASE_POLL_INTERVAL_MS)
        self._media_release_timer.timeout.connect(self._poll_external_media_release_requests)
        self._media_release_timer.start()

    def _log_app_ready(self) -> None:
        debug_logger.log(
            component="ApplicationController",
            action="app_ready",
            message="主窗口初始化完成",
            status_code="APP_READY",
            details={"save_dir": self._host().current_save_dir},
        )

    def _connect_window_signals(self) -> None:
        self.window.sig_start_crawl.connect(self.on_start_crawl)
        self.window.sig_stop_crawl.connect(self.on_stop_crawl)
        self.window.sig_change_dir.connect(self.on_dir_changed)
        self.window.sig_play_video.connect(self.play_video)
        self.window.sig_delete_video.connect(self.on_delete_video)
        if hasattr(self.window, "sig_clear_queue"):
            self.window.sig_clear_queue.connect(self.on_clear_queue)
        self.window.sig_open_latest_log.connect(self.open_latest_log)
        self.window.sig_open_error_summary.connect(self.open_latest_error_summary)
        self.window.sig_copy_trace_id.connect(self.copy_trace_id_for_video)
        if hasattr(self.window, "sig_register_file_associations"):
            self.window.sig_register_file_associations.connect(self.on_register_file_associations)
        self.window.bind_video_rename(self.on_rename_video)
        if hasattr(self.window, "sig_switch_preview"):
            self.window.sig_switch_preview.connect(self.switch_preview)
        if hasattr(self.window, "sig_auto_next_preview"):
            self.window.sig_auto_next_preview.connect(self.autoplay_next_preview)

    def _before_media_delete(self, context) -> None:
        publish_media_release_request(
            local_path=context.video.local_path,
            source="gui",
            reason="delete",
        )
        time.sleep(self.MEDIA_DELETE_COORDINATION_DELAY_SEC)

    def on_register_file_associations(self, include_video: bool, include_image: bool) -> None:
        if not include_video and not include_image:
            self.window.append_log("未选择需要注册的资源类型")
            return

        from app.services.windows_file_association_service import WindowsFileAssociationService

        service = WindowsFileAssociationService()
        result = service.register_current_user(
            self._current_executable_path(),
            include_video=include_video,
            include_image=include_image,
        )
        if not result.registered:
            self.window.append_log(f"文件关联注册未完成: {result.message}")
            return

        default_result = service.set_current_user_defaults(
            include_video=include_video,
            include_image=include_image,
        )
        if default_result.defaulted_extensions:
            preview = ", ".join(default_result.defaulted_extensions[:6])
            suffix = "..." if len(default_result.defaulted_extensions) > 6 else ""
            self.window.append_log(f"已设置默认打开方式: {preview}{suffix}")
        if default_result.failed_extensions:
            preview = ", ".join(default_result.failed_extensions[:6])
            suffix = "..." if len(default_result.failed_extensions) > 6 else ""
            self.window.append_log(f"部分默认打开方式设置失败: {preview}{suffix}")

        diagnostics = service.diagnose_current_user(include_video=include_video, include_image=include_image)
        if diagnostics.available and diagnostics.pending_extensions:
            preview = ", ".join(diagnostics.pending_extensions[:6])
            suffix = "..." if len(diagnostics.pending_extensions) > 6 else ""
            self.window.append_log(f"仍需在 Windows 默认应用中确认: {preview}{suffix}")
            if service.open_default_apps_settings():
                self.window.append_log("已打开 Windows 默认应用设置，请手动确认剩余默认打开方式")
                return
            self.window.append_log("请手动打开 Windows 默认应用设置，确认剩余默认打开方式")
            return

        self.window.append_log("默认打开方式已生效")

    @staticmethod
    def _current_executable_path() -> str:
        if getattr(sys, "frozen", False):
            return sys.executable
        return sys.argv[0]

    def _poll_external_media_release_requests(self) -> None:
        self._last_media_release_request_id, request = poll_media_release_request(self._last_media_release_request_id)
        current_playing_id = self._get_current_playing_id()
        if request is None or not request.local_path or not current_playing_id:
            return
        current_video = self.videos.get(current_playing_id)
        if current_video is None:
            self._set_current_playing_id(None)
            return
        if normalize_media_path(current_video.local_path) != request.local_path:
            return
        self._host().release_media_playback()
        self._set_current_playing_id(None)
