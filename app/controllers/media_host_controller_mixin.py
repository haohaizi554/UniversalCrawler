from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Sequence

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal

from app.debug_logger import debug_logger
from app.exceptions import MediaScanError
from app.models import VideoItem
from app.services.media_release_coordination import normalize_media_path

class _UiCallbackInvoker(QObject):
    """Marshal background callbacks back onto the Qt main thread."""

    callback_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.callback_requested.connect(self._run_callback)

    def invoke(self, callback) -> None:
        self.callback_requested.emit(callback)

    def _run_callback(self, callback) -> None:
        callback()

class MediaHostControllerMixin:
    """Host-backed media library and playback orchestration."""

    def _video_state_guard(self):
        lock = getattr(self, "_videos_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._videos_lock = lock
        return lock

    def _video_lookup(self, video_id: str) -> VideoItem | None:
        with self._video_state_guard():
            return self.videos.get(video_id)

    def _store_video_item(self, item: VideoItem) -> None:
        with self._video_state_guard():
            self.videos[item.id] = item

    def _remove_video_item(self, video_id: str) -> VideoItem | None:
        with self._video_state_guard():
            return self.videos.pop(video_id, None)

    def _get_current_playing_id(self) -> str | None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            getter = getattr(app_state, "get_current_playing_id", None)
            current = getter() if callable(getter) else getattr(app_state, "current_playing_id", None)
            if current is not None and not isinstance(current, str):
                current = getattr(app_state, "current_playing_id", None)
            self.current_playing_id = current
            return current
        return getattr(self, "current_playing_id", None)

    def _set_current_playing_id(self, video_id: str | None) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.set_current_playing_id(video_id)
            getter = getattr(app_state, "get_current_playing_id", None)
            current = getter() if callable(getter) else getattr(app_state, "current_playing_id", video_id)
            if current is not None and not isinstance(current, str):
                current = video_id
            self.current_playing_id = current
            return
        self.current_playing_id = video_id

    def _clear_local_items(self) -> None:
        """Clear cached local media and host rows before a rescan."""
        self._host().clear_video_rows()
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.clear_videos()
            return
        with self._video_state_guard():
            self.videos.clear()

    def _append_scanned_items(self, result) -> None:
        """Populate scanned media rows through a single replace publish."""
        items = self._cache_scanned_items(result)
        if not items:
            return
        videos = {item.id: item for item in items}
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.replace_videos(videos)
            return
        with self._video_state_guard():
            self.videos.clear()
            self.videos.update(videos)
        host = self._host()
        add_row = getattr(host, "add_video_row", None)
        if callable(add_row):
            for item in items:
                add_row(item)

    def scan_local_dir(self):
        """Scan the current save directory and restore local media into the host."""
        host = self._host()
        directory = host.current_save_dir
        host.announce_scan_start(directory)
        debug_logger.log(
            component="ApplicationController",
            action="scan_local_dir",
            message="开始扫描本地媒体目录",
            status_code="APP_SCAN_START",
            details={"directory": directory},
        )

        self._clear_local_items()
        try:
            result = self._scan_media_directory(directory)
            self._append_scanned_items(result)
            for message in self._build_scan_messages(result):
                host.append_log(message)
            if result.total_count > 0:
                debug_logger.log(
                    component="ApplicationController",
                    action="scan_local_dir_finished",
                    message="本地媒体目录扫描完成",
                    status_code="APP_SCAN_OK",
                    details={
                        "directory": directory,
                        "count": result.total_count,
                        "video_count": result.video_count,
                        "image_count": result.image_count,
                    },
                )
        except MediaScanError as exc:
            host.report_scan_error(exc)
            debug_logger.log_exception("ApplicationController", "scan_local_dir", exc, context={"directory": directory})

    def on_dir_changed(self):
        """React to directory changes and refresh the host media list."""
        host = self._host()
        host.announce_directory_changed(host.current_save_dir)
        debug_logger.log(
            component="ApplicationController",
            action="change_save_dir",
            message="保存目录已变更",
            status_code="APP_DIR_CHANGED",
            details={"save_dir": host.current_save_dir},
        )
        self.scan_local_dir()

    def on_rename_video(self, item):
        """Rename a media item and keep host state in sync."""
        if item.column() != 0:
            return
        vid = item.data(Qt.ItemDataRole.UserRole)
        video = self._video_lookup(vid) if vid else None
        if not video:
            return

        new_title = item.text().strip()
        if new_title == video.title or not os.path.exists(video.local_path):
            item.setText(video.title)
            return
        if self._get_current_playing_id() == vid:
            self._host().release_media_playback()
            self._set_current_playing_id(None)

        outcome = self._rename_video_sync(vid, new_title, self._host().current_save_dir)
        if outcome.status == "ok":
            item.setToolTip(new_title)
            self._host().reorder_video_row(video)
            message = self._rename_outcome_message(outcome)
            if message:
                self._host().append_log(message)
        else:
            self._host().report_rename_error(outcome.error or "未知错误")
            item.setText(video.title)

    def on_delete_video(self, row_idx, vid):
        """Delete a media item and reconcile host/download queue state."""
        if self._video_lookup(vid) is None:
            self._host().remove_video_row(row_idx)
            return

        if self._get_current_playing_id() == vid:
            self._host().release_media_playback()
            self._set_current_playing_id(None)
        outcome = self._delete_video_sync(vid)
        if outcome.status == "error":
            self._host().report_delete_error(outcome.error or "未知错误")
            return
        for message in self._delete_outcome_messages(outcome):
            self._host().append_log(message)
        self._host().remove_video_row(row_idx)
        self._host().refresh_table_bindings()

    def on_clear_queue(self) -> None:
        """Remove queued items without blocking the Qt main thread."""
        if self._should_clear_queue_in_background():
            invoker = self._ensure_ui_callback_invoker()

            def clear_in_background() -> None:
                try:
                    ids = self._queue_item_ids_for_clear()
                    if not ids:
                        invoker.invoke(lambda: self._finalize_clear_queue_removal(0, set()))
                        return
                    self._cancel_queue_items(ids)
                    removed = self._remove_queue_items_from_state(ids)
                except Exception as exc:  # pragma: no cover - defensive UI recovery path
                    message = str(exc)
                    debug_logger.log_exception(
                        "MediaHostControllerMixin",
                        "clear_queue_background",
                        exc,
                        details={"item_count": len(locals().get("ids", set()))},
                    )
                    invoker.invoke(lambda: self._host().append_log(f"Clear queue failed: {message}"))
                    return
                invoker.invoke(lambda: self._finalize_clear_queue_removal(removed, ids))

            threading.Thread(
                target=clear_in_background,
                name="ClearDownloadQueueWorker",
                daemon=True,
            ).start()
            return

        ids = self._queue_item_ids_for_clear()
        if not ids:
            return
        self._cancel_queue_items(ids)
        removed = self._remove_queue_items_from_state(ids)
        self._finalize_clear_queue_removal(removed, ids)

    def _should_clear_queue_in_background(self) -> bool:
        if getattr(self, "app", None) is None:
            return False
        app = QCoreApplication.instance()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    def _ensure_ui_callback_invoker(self) -> _UiCallbackInvoker:
        invoker = getattr(self, "_ui_callback_invoker", None)
        if invoker is None:
            invoker = _UiCallbackInvoker()
            self._ui_callback_invoker = invoker
        return invoker

    def _queue_item_ids_for_clear(self) -> set[str]:
        service = getattr(self, "frontend_state_service", None)
        service_dict = getattr(service, "__dict__", {}) if service is not None else {}
        queue_item_ids = service_dict.get("queue_item_ids") if isinstance(service_dict, dict) else None
        if not callable(queue_item_ids) and callable(getattr(type(service), "queue_item_ids", None)):
            queue_item_ids = getattr(service, "queue_item_ids", None)
        if callable(queue_item_ids):
            return {str(video_id) for video_id in queue_item_ids() if video_id}
        if service is not None:
            snapshot = service.get_snapshot(sections=frozenset({"queue_items"}))
            return {str(item["id"]) for item in snapshot.get("queue_items", []) if item.get("id")}
        return set()

    def _cancel_queue_items(self, video_ids: set[str]) -> None:
        manager_dict = getattr(self.dl_manager, "__dict__", {}) if self.dl_manager is not None else {}
        cancel_tasks = manager_dict.get("cancel_tasks") if isinstance(manager_dict, dict) else None
        if not callable(cancel_tasks):
            cancel_tasks = getattr(type(self.dl_manager), "cancel_tasks", None)
        if callable(cancel_tasks):
            self.dl_manager.cancel_tasks(video_ids)
        else:
            for video_id in video_ids:
                self.dl_manager.cancel_task(video_id)
        try:
            from app.services.download_telemetry import get_download_telemetry_service

            telemetry = get_download_telemetry_service()
            for video_id in video_ids:
                telemetry.clear(video_id)
        except Exception:
            pass

    def _remove_queue_items_from_state(self, video_ids: set[str]) -> int:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state_dict = getattr(app_state, "__dict__", {})
            remover = app_state_dict.get("remove_videos") if isinstance(app_state_dict, dict) else None
            if not callable(remover) and callable(getattr(type(app_state), "remove_videos", None)):
                remover = getattr(app_state, "remove_videos", None)
            if callable(remover):
                return len(remover(video_ids, publish=False))
            with app_state._lock:
                removed = 0
                for video_id in video_ids:
                    if app_state.videos.pop(video_id, None) is None:
                        continue
                    removed += 1
                    app_state.task_state.pop(video_id, None)
                    app_state._last_progress_emit_at.pop(video_id, None)
                return removed
        with self._video_state_guard():
            removed = 0
            for video_id in video_ids:
                if self.videos.pop(video_id, None) is not None:
                    removed += 1
            return removed

    def _finalize_clear_queue_removal(self, removed: int, video_ids: set[str]) -> None:
        if removed <= 0:
            return
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state._publish_change(
                "videos.remove_many",
                {"video_ids": list(video_ids), "count": int(removed)},
            )
        host = self._host()
        host.append_log(f"🗑️ 已清空下载队列 ({removed} 项)")
        refresh = getattr(host, "refresh_frontend_state", None)
        if callable(refresh):
            refresh(force=False, topics={"videos.remove_many"})

    def play_video(self, vid):
        """Preview a local media item through the host adapter."""
        video = self._video_lookup(vid) if vid else None
        if not video or not os.path.exists(video.local_path):
            self._host().report_missing_media()
            return
        self._set_current_playing_id(vid)
        self._host().announce_playback(video.title)

        if self._is_image_file(video.local_path):
            self._host().show_image(video.local_path)
        else:
            self._host().play_video(video.local_path)

    def switch_preview(self, direction: int) -> None:
        """Switch to the previous or next preview item in host table order."""
        self._switch_preview(direction, wrap=True)

    def autoplay_next_preview(self) -> None:
        """Advance to the next preview item after playback, without wrapping."""
        self._switch_preview(1, wrap=False, auto_advance=True)

    def _switch_preview(self, direction: int, *, wrap: bool, auto_advance: bool = False) -> None:
        host = self._host()
        anchor_id = self._get_current_playing_id() or host.get_selected_video_id()
        next_video_id = host.get_adjacent_video_id(anchor_id, direction, wrap=wrap)
        if not next_video_id:
            if auto_advance:
                host.append_log("\u2139\ufe0f \u5df2\u64ad\u653e\u5230\u6700\u540e\u4e00\u9879")
            elif not getattr(self, "videos", {}):
                host.append_log("\u26a0\ufe0f \u961f\u5217\u4e3a\u7a7a\uff0c\u6ca1\u6709\u53ef\u5207\u6362\u7684\u8d44\u6e90")
            return
        host.select_video_by_id(next_video_id)
        self.play_video(next_video_id)

    def _is_image_file(self, file_path: str) -> bool:
        """Return whether the given local path should be previewed as an image."""
        return os.path.splitext(file_path)[1].lower() in self.IMAGE_EXTENSIONS
