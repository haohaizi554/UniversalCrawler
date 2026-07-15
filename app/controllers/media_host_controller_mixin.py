from __future__ import annotations

import os
import threading
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal

from app.config import cfg
from app.debug_logger import debug_logger
from app.exceptions import FileOperationError, MediaScanError
from app.models import VideoItem
from app.services import frontend_video_adapter as video_adapter
from app.services.media_release_coordination import normalize_media_path
from app.ui.task_runtime import ShortTaskRunner

class _UiCallbackInvoker(QObject):
    """把后台回调转发到 Qt 主线程。"""

    callback_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.callback_requested.connect(self._run_callback, Qt.ConnectionType.QueuedConnection)

    def invoke(self, callback) -> None:
        self.callback_requested.emit(callback)

    def _run_callback(self, callback) -> None:
        callback()

class MediaHostControllerMixin:
    """协调宿主中的媒体库与播放流程。"""

    CLEAR_QUEUE_DETAIL_LOG_LIMIT = 200

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
        """重新扫描前清空本地媒体缓存和宿主行。"""
        self._host().clear_video_rows()
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state.clear_videos()
            return
        with self._video_state_guard():
            self.videos.clear()

    def _append_scanned_items(self, result) -> None:
        """通过一次整体替换发布扫描结果。"""
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
        """扫描当前保存目录，并把本地媒体恢复到宿主。"""
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
        # 目录切换会让多次扫描并发收尾；`generation` 只允许最新任务提交结果。
        generation = int(getattr(self, "_local_scan_generation", 0) or 0) + 1
        self._local_scan_generation = generation
        previous_token = getattr(self, "_local_scan_token", None)
        if previous_token is not None:
            previous_token.cancel()
        if not self._should_scan_local_dir_in_background():
            try:
                result = self._scan_media_directory(directory)
            except MediaScanError as exc:
                self._finish_local_scan_error(directory, generation, exc)
                return
            except Exception as exc:
                self._finish_local_scan_error(directory, generation, exc)
                return
            self._finish_local_scan_success(directory, generation, result)
            return
        invoker = self._ensure_ui_callback_invoker()
        runner = self._ensure_short_task_runner()

        def scan_in_background(cancel_token) -> None:
            try:
                result = self._scan_media_directory(directory)
            except MediaScanError as exc:
                invoker.invoke(lambda exc=exc: self._finish_local_scan_error(directory, generation, exc))
                return
            except Exception as exc:
                invoker.invoke(lambda exc=exc: self._finish_local_scan_error(directory, generation, exc))
                return
            if cancel_token.is_cancelled():
                return
            invoker.invoke(lambda result=result: self._finish_local_scan_success(directory, generation, result))

        self._local_scan_token = runner.submit(name="scan-local-dir", fn=scan_in_background)

    def _finish_local_scan_success(self, directory: str, generation: int, result) -> None:
        if generation != int(getattr(self, "_local_scan_generation", 0) or 0):
            return
        host = self._host()
        if normalize_media_path(directory) != normalize_media_path(host.current_save_dir):
            return
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

    def _finish_local_scan_error(self, directory: str, generation: int, exc: Exception) -> None:
        if generation != int(getattr(self, "_local_scan_generation", 0) or 0):
            return
        self._host().report_scan_error(exc)
        debug_logger.log_exception("ApplicationController", "scan_local_dir", exc, context={"directory": directory})

    def on_dir_changed(self):
        """目录变化后刷新宿主媒体列表。"""
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
        """重命名媒体项，并同步宿主状态。"""
        if item.column() != 0:
            return
        vid = item.data(Qt.ItemDataRole.UserRole)
        video = self._video_lookup(vid) if vid else None
        if not video:
            return

        new_title = item.text().strip()
        if new_title == video.title:
            item.setText(video.title)
            return
        if self._get_current_playing_id() == vid:
            self._host().release_media_playback()
            self._set_current_playing_id(None)

        if self._should_rename_media_in_background():
            self._submit_rename_video_task(item, vid, new_title, self._host().current_save_dir)
            return

        outcome = self._rename_video_sync(vid, new_title, self._host().current_save_dir)
        self._finalize_rename_video(item, outcome, video_id=vid, fallback_video=video)

    def _should_rename_media_in_background(self) -> bool:
        app = self._qt_app_for_background_work()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    def _submit_rename_video_task(self, item, video_id: str, new_title: str, save_dir: str) -> None:
        generation_by_id = getattr(self, "_rename_generation_by_id", None)
        if not isinstance(generation_by_id, dict):
            generation_by_id = {}
            self._rename_generation_by_id = generation_by_id
        generation = int(generation_by_id.get(video_id, 0) or 0) + 1
        generation_by_id[video_id] = generation

        invoker = self._ensure_ui_callback_invoker()
        runner = self._ensure_short_task_runner()

        def rename_in_background(cancel_token) -> None:
            outcome = self._rename_video_io(video_id, new_title, save_dir)
            if cancel_token.is_cancelled():
                return
            invoker.invoke(
                lambda outcome=outcome: self._finalize_rename_video(
                    item,
                    outcome,
                    generation=generation,
                    video_id=video_id,
                )
            )

        runner.submit(name=f"rename-video-{video_id}", fn=rename_in_background)

    def _finalize_rename_video(
        self,
        item,
        outcome,
        *,
        generation: int | None = None,
        video_id: str | None = None,
        fallback_video: VideoItem | None = None,
    ) -> None:
        outcome_video_id = video_id or getattr(outcome, "video_id", None)
        if generation is not None:
            generation_by_id = getattr(self, "_rename_generation_by_id", {})
            if int(generation_by_id.get(outcome_video_id, 0) or 0) != generation:
                return
        video = getattr(outcome, "video", None) or fallback_video
        if outcome.status == "ok":
            if video is None:
                self._host().report_rename_error(getattr(outcome, "error", None) or "未知错误")
                return
            new_title = getattr(outcome, "new_title", None) or video.title
            new_path = getattr(outcome, "new_path", None)
            video.title = new_title
            if new_path is not None:
                video.local_path = new_path
            item.setToolTip(new_title)
            self._host().reorder_video_row(video)
            message = self._rename_outcome_message(outcome)
            if message:
                self._host().append_log(message)
        else:
            self._host().report_rename_error(outcome.error or "未知错误")
            if video is not None:
                item.setText(video.title)

    def on_delete_video(self, row_idx, vid):
        """删除媒体项，并协调宿主与下载队列状态。"""
        if self._video_lookup(vid) is None:
            self._remove_video_row_from_host(row_idx, vid)
            return

        release_before_delete = self._get_current_playing_id() == vid
        if release_before_delete:
            self._host().release_media_playback()
            self._set_current_playing_id(None)
        if self._should_delete_media_asynchronously():
            context = self._begin_delete_video(vid)
            if context is None:
                self._remove_video_row_from_host(row_idx, vid)
                return
            before_delete = getattr(self, "_before_media_delete", None)
            if callable(before_delete):
                before_delete(context)
            self._optimistic_remove_video_item(vid)
            self._remove_video_row_from_host(row_idx, vid)
            self._host().refresh_table_bindings()
            self._submit_delete_video_task(
                row_idx,
                context,
                delay_sec=self._delete_coordination_delay(release_before_delete),
                ui_removed=True,
            )
            return
        outcome = self._delete_video_sync(vid)
        self._finalize_delete_video(row_idx, outcome)

    def _delete_video_after_release(self, row_idx: int, video_id: str) -> None:
        outcome = self._delete_video_sync(video_id)
        self._finalize_delete_video(row_idx, outcome)

    def _submit_delete_video_task(
        self,
        row_idx: int,
        context,
        *,
        delay_sec: float = 0.0,
        ui_removed: bool = False,
    ) -> None:
        invoker = self._ensure_ui_callback_invoker()
        runner = self._ensure_short_task_runner()

        def delete_in_background(cancel_token) -> None:
            if not self._sleep_before_delete(delay_sec, cancel_token):
                return
            outcome = self._delete_video_context_sync(context)
            invoker.invoke(lambda outcome=outcome: self._finalize_delete_video(row_idx, outcome, ui_removed=ui_removed))

        runner.submit(name=f"delete-video-{context.video_id}", fn=delete_in_background)

    def _delete_coordination_delay(self, release_before_delete: bool) -> float:
        if not release_before_delete:
            return 0.0
        try:
            return max(0.0, float(getattr(self, "MEDIA_DELETE_COORDINATION_DELAY_SEC", 0.18)))
        except (TypeError, ValueError):
            return 0.18

    @staticmethod
    def _sleep_before_delete(delay_sec: float, cancel_token) -> bool:
        remaining = max(0.0, float(delay_sec or 0.0))
        if remaining <= 0:
            return not cancel_token.is_cancelled()
        wait_cancelled = getattr(cancel_token, "wait_cancelled", None)
        if callable(wait_cancelled):
            return not bool(wait_cancelled(remaining))
        threading.Event().wait(remaining)
        return not cancel_token.is_cancelled()

    def _delete_video_context_sync(self, context):
        try:
            deleted = self.file_service.delete_media(context.video)
        except FileOperationError as exc:
            return SimpleNamespace(
                status="error",
                video_id=context.video_id,
                video=context.video,
                cancel_result=context.cancel_result,
                deleted=False,
                error=str(exc),
            )
        return SimpleNamespace(
            status="ok",
            video_id=context.video_id,
            video=context.video,
            cancel_result=context.cancel_result,
            deleted=deleted,
            error=None,
        )

    def _finalize_delete_video(self, row_idx: int, outcome, *, ui_removed: bool = False) -> None:
        if outcome.status == "error":
            if ui_removed and getattr(outcome, "video", None) is not None:
                self._restore_video_item_after_delete_error(outcome.video)
                adder = getattr(self._host(), "add_video_row", None)
                if callable(adder):
                    adder(outcome.video)
                self._host().refresh_table_bindings()
            self._host().report_delete_error(outcome.error or "未知错误")
            return
        video_id = getattr(outcome, "video_id", None)
        if video_id and not ui_removed:
            self._remove_video_item(video_id)
        for message in self._delete_outcome_messages(outcome):
            self._host().append_log(message)
        if not ui_removed:
            self._remove_video_row_from_host(row_idx, video_id)
            self._host().refresh_table_bindings()

    def _remove_video_row_from_host(self, row_idx: int, video_id: str | None = None) -> None:
        remover = getattr(self._host(), "remove_video_row", None)
        if not callable(remover):
            return
        if video_id:
            try:
                remover(row_idx, video_id)
                return
            except TypeError:
                pass
        remover(row_idx)

    def _optimistic_remove_video_item(self, video_id: str) -> None:
        remover = getattr(self, "_remove_video_item", None)
        if callable(remover):
            remover(video_id)
            return
        videos = getattr(self, "videos", None)
        if isinstance(videos, dict):
            videos.pop(video_id, None)

    def _restore_video_item_after_delete_error(self, video: VideoItem) -> None:
        storer = getattr(self, "_store_video_item", None)
        if callable(storer):
            storer(video)
            return
        videos = getattr(self, "videos", None)
        if isinstance(videos, dict):
            videos[video.id] = video

    def _should_delete_media_asynchronously(self) -> bool:
        app = self._qt_app_for_background_work()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    def on_clear_queue(self) -> None:
        """在不阻塞 Qt 主线程的前提下移除队列项。"""
        if self._should_clear_queue_in_background():
            invoker = self._ensure_ui_callback_invoker()

            def clear_in_background(_cancel_token) -> None:
                try:
                    ids = self._queue_item_ids_for_clear()
                    labels = self._queue_delete_log_labels(ids)
                    if not ids:
                        invoker.invoke(lambda: self._finalize_clear_queue_removal(set(), labels))
                        return
                    self._cancel_queue_items(ids)
                    removed_ids = self._remove_queue_items_from_state(ids)
                except Exception as exc:  # pragma: no cover - UI 防御性恢复路径
                    message = str(exc)
                    debug_logger.log_exception(
                        "MediaHostControllerMixin",
                        "clear_queue_background",
                        exc,
                        details={"item_count": len(locals().get("ids", set()))},
                    )
                    invoker.invoke(lambda: self._host().append_log(f"Clear queue failed: {message}"))
                    return
                invoker.invoke(lambda: self._finalize_clear_queue_removal(removed_ids, labels))

            self._ensure_short_task_runner().submit(
                name="clear-download-queue",
                fn=clear_in_background,
            )
            return

        ids = self._queue_item_ids_for_clear()
        if not ids:
            return
        labels = self._queue_delete_log_labels(ids)
        self._cancel_queue_items(ids)
        removed_ids = self._remove_queue_items_from_state(ids)
        self._finalize_clear_queue_removal(removed_ids, labels)

    def _should_clear_queue_in_background(self) -> bool:
        app = self._qt_app_for_background_work()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    def _should_scan_local_dir_in_background(self) -> bool:
        app = self._qt_app_for_background_work()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    def _qt_app_for_background_work(self):
        app = QCoreApplication.instance()
        if app is None or getattr(self, "app", None) is not app:
            return None
        return app

    def _ensure_ui_callback_invoker(self) -> _UiCallbackInvoker:
        invoker = getattr(self, "_ui_callback_invoker", None)
        if invoker is None:
            invoker = _UiCallbackInvoker()
            self._ui_callback_invoker = invoker
        return invoker

    def _ensure_short_task_runner(self) -> ShortTaskRunner:
        runner = getattr(self, "_short_task_runner", None)
        if runner is None:
            runner = ShortTaskRunner(max_thread_count=4)
            self._short_task_runner = runner
        return runner

    def _queue_item_ids_for_clear(self) -> set[str]:
        service = getattr(self, "frontend_state_service", None)
        service_dict = getattr(service, "__dict__", {}) if service is not None else {}
        queue_item_ids = service_dict.get("queue_item_ids") if isinstance(service_dict, dict) else None
        if not callable(queue_item_ids) and callable(getattr(type(service), "queue_item_ids", None)):
            queue_item_ids = getattr(service, "queue_item_ids", None)
        if callable(queue_item_ids):
            return {str(video_id) for video_id in queue_item_ids() if video_id}
        queued_ids = self._queued_manager_video_ids()
        active_ids = self._active_manager_video_ids()
        return {
            str(video_id)
            for video_id, item in self._video_items_for_clear().items()
            if video_id and video_adapter.bucket_for_item(item, queued_ids=queued_ids, active_ids=active_ids) == "queue"
        }

    def _video_items_for_clear(self) -> dict[str, VideoItem]:
        app_state = getattr(self, "app_state", None)
        if app_state is not None and hasattr(app_state, "videos"):
            lock = getattr(app_state, "_lock", None)
            if lock is not None:
                with lock:
                    return {str(video_id): item for video_id, item in getattr(app_state, "videos", {}).items()}
            return {str(video_id): item for video_id, item in getattr(app_state, "videos", {}).items()}
        with self._video_state_guard():
            return {str(video_id): item for video_id, item in getattr(self, "videos", {}).items()}

    def _queued_manager_video_ids(self) -> set[str]:
        manager = getattr(self, "dl_manager", None)
        queued_video_ids = getattr(manager, "queued_video_ids", None)
        if callable(queued_video_ids):
            return {str(video_id) for video_id in queued_video_ids() if video_id}
        queue_obj = getattr(manager, "queue", None)
        snapshot_video_ids = getattr(queue_obj, "snapshot_video_ids", None)
        if callable(snapshot_video_ids):
            return {str(video_id) for video_id in snapshot_video_ids() if video_id}
        return set()

    def _active_manager_video_ids(self) -> set[str]:
        manager = getattr(self, "dl_manager", None)
        prune_finished = getattr(manager, "prune_finished_workers", None)
        if callable(prune_finished):
            prune_finished()
        lock = getattr(manager, "_workers_lock", None)
        if lock is not None:
            with lock:
                workers = list(getattr(manager, "workers", []) or [])
        else:
            workers = list(getattr(manager, "workers", []) or [])
        ids: set[str] = set()
        for worker in workers:
            video = getattr(worker, "video", None)
            video_id = getattr(video, "id", "")
            if video_id:
                ids.add(str(video_id))
        return ids

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
        except (RuntimeError, AttributeError) as exc:
            debug_logger.log_exception(
                "MediaHostControllerMixin",
                "clear_download_telemetry",
                exc,
                details={"video_ids": list(video_ids)},
            )

    def _remove_queue_items_from_state(self, video_ids: set[str]) -> set[str]:
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state_dict = getattr(app_state, "__dict__", {})
            remover = app_state_dict.get("remove_videos") if isinstance(app_state_dict, dict) else None
            if not callable(remover) and callable(getattr(type(app_state), "remove_videos", None)):
                remover = getattr(app_state, "remove_videos", None)
            if callable(remover):
                removed = remover(video_ids, publish=False)
                if isinstance(removed, int):
                    return set(list(video_ids)[: max(0, removed)])
                return {str(video_id) for video_id in removed if video_id}
            with app_state._lock:
                removed: set[str] = set()
                for video_id in video_ids:
                    if app_state.videos.pop(video_id, None) is None:
                        continue
                    removed.add(video_id)
                    app_state.task_state.pop(video_id, None)
                    app_state._last_progress_emit_at.pop(video_id, None)
                return removed
        with self._video_state_guard():
            removed: set[str] = set()
            for video_id in video_ids:
                if self.videos.pop(video_id, None) is not None:
                    removed.add(video_id)
            return removed

    def _queue_delete_log_labels(self, video_ids: set[str]) -> dict[str, str]:
        labels: dict[str, str] = {}
        app_state = getattr(self, "app_state", None)
        if app_state is not None and hasattr(app_state, "videos"):
            lock = getattr(app_state, "_lock", None)
            if lock is not None:
                with lock:
                    source_items = {video_id: app_state.videos.get(video_id) for video_id in video_ids}
            else:
                source_items = {video_id: app_state.videos.get(video_id) for video_id in video_ids}
        else:
            with self._video_state_guard():
                source_items = {video_id: self.videos.get(video_id) for video_id in video_ids}
        for video_id, item in source_items.items():
            labels[video_id] = self._delete_log_label(item, fallback=video_id)
        return labels

    @staticmethod
    def _delete_log_label(video: VideoItem | None, *, fallback: str) -> str:
        if video is None:
            return fallback
        local_path = str(getattr(video, "local_path", "") or "")
        if local_path:
            return os.path.basename(local_path) or local_path
        title = str(getattr(video, "title", "") or "")
        return title or fallback

    def _append_clear_queue_delete_logs(self, host, removed_ids: set[str], labels: dict[str, str]) -> None:
        limit = max(0, int(getattr(self, "CLEAR_QUEUE_DETAIL_LOG_LIMIT", 200) or 0))
        ordered_ids = sorted(removed_ids, key=lambda video_id: labels.get(video_id, video_id))
        for video_id in ordered_ids[:limit]:
            host.append_log(f"🗑️ 已删除: {labels.get(video_id, video_id)}")
        omitted = len(ordered_ids) - min(len(ordered_ids), limit)
        if omitted > 0:
            host.append_log(f"ℹ️ 另有 {omitted} 项已从下载队列移除，已省略逐条日志")

    def _finalize_clear_queue_removal(self, removed_ids: set[str], labels: dict[str, str] | None = None) -> None:
        removed = len(removed_ids)
        if removed <= 0:
            return
        app_state = getattr(self, "app_state", None)
        if app_state is not None:
            app_state._publish_change(
                "videos.remove_many",
                {"video_ids": list(removed_ids), "count": int(removed)},
            )
        host = self._host()
        self._append_clear_queue_delete_logs(host, removed_ids, labels or {})
        host.append_log(f"🗑️ 已清空下载队列 ({removed} 项)")
        refresh = getattr(host, "refresh_frontend_state", None)
        if callable(refresh):
            refresh(force=False, topics={"videos.remove_many"})

    def play_video(self, vid):
        """通过宿主适配器预览本地媒体项。"""
        video = self._video_lookup(vid) if vid else None
        if not video:
            self._host().report_missing_media()
            return
        if self._should_check_playback_file_in_background():
            self._submit_playback_file_check(vid, video.local_path)
            return
        if not self._playback_file_exists(video.local_path):
            self._host().report_missing_media()
            return
        self._finish_play_video_after_file_check(vid, video.local_path, exists=True)

    def _should_check_playback_file_in_background(self) -> bool:
        app = self._qt_app_for_background_work()
        if app is None:
            return False
        return QThread.currentThread() == app.thread()

    @staticmethod
    def _playback_file_exists(file_path: str) -> bool:
        try:
            return os.path.exists(file_path)
        except OSError as exc:
            debug_logger.log_exception(
                "MediaHostControllerMixin",
                "playback_file_exists",
                exc,
                details={"path": file_path},
            )
            return False

    def _submit_playback_file_check(self, video_id: str, local_path: str) -> None:
        generation = int(getattr(self, "_playback_file_check_generation", 0) or 0) + 1
        self._playback_file_check_generation = generation
        previous_token = getattr(self, "_playback_file_check_token", None)
        if previous_token is not None:
            previous_token.cancel()

        invoker = self._ensure_ui_callback_invoker()
        runner = self._ensure_short_task_runner()

        def check_in_background(cancel_token) -> None:
            exists = self._playback_file_exists(local_path)
            if cancel_token.is_cancelled():
                return
            invoker.invoke(
                lambda exists=exists: self._finish_play_video_after_file_check(
                    video_id,
                    local_path,
                    exists=exists,
                    generation=generation,
                )
            )

        self._playback_file_check_token = runner.submit(name=f"check-playback-file-{video_id}", fn=check_in_background)

    def _finish_play_video_after_file_check(
        self,
        video_id: str,
        expected_path: str,
        *,
        exists: bool,
        generation: int | None = None,
    ) -> None:
        # 文件探测可能乱序返回；只接受最新 `generation`，且路径仍须与当前资源一致。
        if generation is not None and generation != int(getattr(self, "_playback_file_check_generation", 0) or 0):
            return
        video = self._video_lookup(video_id)
        if not video or normalize_media_path(video.local_path) != normalize_media_path(expected_path):
            return
        if not exists:
            self._host().report_missing_media()
            return
        self._start_video_playback(video_id, video)

    def _start_video_playback(self, video_id: str, video: VideoItem) -> None:
        """路径探测完成后进入实际播放分支。"""
        self._set_current_playing_id(video_id)
        self._host().announce_playback(video.title)

        if self._should_open_with_system_player():
            releaser = getattr(self._host(), "release_media_playback", None)
            if callable(releaser):
                releaser()
            self._open_media_with_system_default(video.local_path)
            return

        if self._is_image_file(video.local_path):
            self._host().show_image(video.local_path)
        else:
            self._host().play_video(video.local_path)

    def _should_open_with_system_player(self) -> bool:
        return str(cfg.get("playback", "default_player", "builtin_player") or "builtin_player") == "system_default"

    def _open_media_with_system_default(self, file_path: str) -> None:
        opener = getattr(self, "_open_path_with_system_default", None)
        if callable(opener):
            opener(file_path)
            return
        host_opener = getattr(self._host(), "open_with_system_default", None)
        if callable(host_opener):
            host_opener(file_path)
            return
        if os.name == "nt":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise OSError("os.startfile is unavailable")
            startfile(file_path)
            return
        import subprocess

        subprocess.Popen(["xdg-open", file_path])

    def switch_preview(self, direction: int) -> None:
        """按宿主表格顺序切换到上一个或下一个预览项。"""
        self._switch_preview(direction, wrap=True)

    def autoplay_next_preview(self) -> None:
        """播放结束后前进到下一项，不循环到队首。"""
        if not bool(cfg.get("playback", "autoplay_next", True)):
            return
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
        return os.path.splitext(file_path)[1].lower() in self.IMAGE_EXTENSIONS
