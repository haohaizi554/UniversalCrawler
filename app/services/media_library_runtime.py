from __future__ import annotations

import os
import stat
import threading
from copy import deepcopy
from dataclasses import dataclass

from app.config import cfg
from app.core.state import VideoStatus, parse_video_status
from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.file_service import ScanResult
from app.services.keyed_lock_pool import KeyedLockPool


_MEDIA_ITEM_POOL_INIT_LOCK = threading.RLock()

@dataclass
class MediaDeleteContext:
    video_id: str
    video: VideoItem
    cancel_result: str | None
    detached_from_store: bool = False
    superseded: bool = False
    generation: object | None = None

@dataclass
class MediaDeleteOutcome:
    status: str
    video_id: str
    video: VideoItem | None = None
    cancel_result: str | None = None
    deleted: bool = False
    error: str | None = None

@dataclass
class MediaRenameOutcome:
    status: str
    video_id: str
    video: VideoItem | None = None
    old_path: str | None = None
    new_path: str | None = None
    new_title: str | None = None
    error: str | None = None

@dataclass(frozen=True)
class MediaScanReconcileOutcome:
    """Stable-ID result of reconciling one filesystem scan with runtime state."""

    items: tuple[VideoItem, ...]
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    retained_ids: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added_ids or self.removed_ids)

class MediaLibraryMixin:
    """GUI/Web host 共用的媒体库编排；文件 IO 结果通过统一 Outcome 返回。"""

    def _resolve_scan_limit(self, scan_limit: int | None = None) -> int:
        return scan_limit if scan_limit is not None else cfg.get("download", "local_scan_limit", 1000)

    def _scan_media_directory(self, directory: str, scan_limit: int | None = None) -> ScanResult:
        return self.file_service.scan_directory(
            directory,
            max_scan_count=self._resolve_scan_limit(scan_limit),
        )

    @staticmethod
    def _build_scan_summary_message(result: ScanResult) -> str:
        if result.truncated:
            return f"⚠️ 文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
        if result.total_count == 0:
            return "ℹ️ 该目录下没有找到视频或图片"
        return f"✅ 已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"

    @classmethod
    def _build_scan_messages(cls, result: ScanResult) -> list[str]:
        if result.truncated:
            return [
                cls._build_scan_summary_message(result),
                f"✅ 已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})",
            ]
        return [cls._build_scan_summary_message(result)]

    def _cache_scanned_items(self, result: ScanResult) -> list[VideoItem]:
        items: list[VideoItem] = []
        for item in result.items:
            self._prepare_local_item(item)
            items.append(item)
            if getattr(self, "app_state", None) is None:
                self._store_video_item(item)
        return items

    @staticmethod
    def _normalize_library_path(path: str | None) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        try:
            return os.path.normcase(os.path.abspath(os.path.expanduser(raw)))
        except (OSError, TypeError, ValueError):
            return os.path.normcase(raw)

    @classmethod
    def _path_is_within_directory(cls, path: str, directory: str) -> bool:
        normalized_path = cls._normalize_library_path(path)
        normalized_directory = cls._normalize_library_path(directory)
        if not normalized_path or not normalized_directory:
            return False
        try:
            return os.path.commonpath((normalized_path, normalized_directory)) == normalized_directory
        except (OSError, ValueError):
            return False

    @staticmethod
    def _is_completed_library_item(item: VideoItem) -> bool:
        status = parse_video_status(getattr(item, "status", ""))
        return getattr(item, "source", "") == "local" or status in {
            VideoStatus.COMPLETED,
            VideoStatus.LOCAL,
        }

    def _snapshot_video_references(self) -> dict[str, VideoItem]:
        with self._video_state_guard():
            return dict(getattr(self, "videos", {}))

    def _find_missing_library_items(self, directory: str) -> dict[str, VideoItem]:
        """Check file existence off the UI/event-loop thread.

        Direct children are also checked by the directory scan, while this pass
        covers collection subdirectories that are intentionally not enumerated.
        """

        missing: dict[str, VideoItem] = {}
        for video_id, item in self._snapshot_video_references().items():
            path = self._normalize_library_path(getattr(item, "local_path", ""))
            if (
                not path
                or not self._is_completed_library_item(item)
                or not self._path_is_within_directory(path, directory)
            ):
                continue
            try:
                mode = os.stat(path).st_mode
            except (FileNotFoundError, NotADirectoryError):
                missing[video_id] = item
            except OSError:
                # Permission and transient network errors must not erase a row.
                continue
            else:
                if not stat.S_ISREG(mode):
                    missing[video_id] = item
        return missing

    def _scan_media_directory_with_missing(
        self,
        directory: str,
        scan_limit: int | None = None,
    ) -> tuple[ScanResult, dict[str, VideoItem]]:
        """Build the complete filesystem snapshot in a worker thread."""

        result = self._scan_media_directory(directory, scan_limit)
        return result, self._find_missing_library_items(directory)

    def _reconcile_scanned_items(
        self,
        result: ScanResult,
        directory: str,
        *,
        missing_items: dict[str, VideoItem] | None = None,
    ) -> MediaScanReconcileOutcome:
        """Preserve stable IDs and commit one add/remove batch for a scan."""

        candidates = list(result.items)
        for item in candidates:
            self._prepare_local_item(item)

        snapshot = self._snapshot_video_references()
        existing_by_path: dict[str, VideoItem] = {}
        for item in snapshot.values():
            path = self._normalize_library_path(getattr(item, "local_path", ""))
            if path and path not in existing_by_path:
                existing_by_path[path] = item

        resolved_items: list[VideoItem] = []
        additions: list[VideoItem] = []
        retained_ids: set[str] = set()
        scanned_paths: set[str] = set()
        for candidate in candidates:
            path = self._normalize_library_path(getattr(candidate, "local_path", ""))
            if path:
                scanned_paths.add(path)
            existing = existing_by_path.get(path) if path else None
            if existing is not None and existing.id not in retained_ids:
                retained_ids.add(existing.id)
                resolved_items.append(existing)
                continue
            additions.append(candidate)
            resolved_items.append(candidate)

        normalized_directory = self._normalize_library_path(directory)
        expected_removals: dict[str, VideoItem] = {}
        missing_items = dict(missing_items or {})
        for video_id, item in snapshot.items():
            if not self._is_completed_library_item(item) or video_id in retained_ids:
                continue
            path = self._normalize_library_path(getattr(item, "local_path", ""))
            if not path:
                continue
            parent = self._normalize_library_path(os.path.dirname(path))
            outside_library = not self._path_is_within_directory(path, normalized_directory)
            absent_direct_child = parent == normalized_directory and path not in scanned_paths
            missing_nested_item = missing_items.get(video_id) is item
            duplicate_scanned_path = path in scanned_paths and video_id not in retained_ids
            if outside_library or absent_direct_child or missing_nested_item or duplicate_scanned_path:
                expected_removals[video_id] = item

        app_state = getattr(self, "app_state", None)
        if app_state is not None and callable(getattr(app_state, "reconcile_videos", None)):
            added_ids, removed_ids = app_state.reconcile_videos(
                additions,
                remove_if_matches=expected_removals,
            )
        else:
            added_ids: list[str] = []
            removed_ids: list[str] = []
            with self._video_state_guard():
                videos = getattr(self, "videos", {})
                for video_id, expected in expected_removals.items():
                    if videos.get(video_id) is expected:
                        videos.pop(video_id, None)
                        removed_ids.append(video_id)
                for item in additions:
                    if item.id not in videos:
                        added_ids.append(item.id)
                    videos[item.id] = item

        return MediaScanReconcileOutcome(
            items=tuple(resolved_items),
            added_ids=tuple(added_ids),
            removed_ids=tuple(removed_ids),
            retained_ids=tuple(sorted(retained_ids)),
        )

    def _media_watch_directories(self, directory: str) -> tuple[str, ...]:
        """Watch the root plus collection folders represented in completed state."""

        normalized_directory = self._normalize_library_path(directory)
        paths = {normalized_directory} if normalized_directory else set()
        for item in self._snapshot_video_references().values():
            if not self._is_completed_library_item(item):
                continue
            local_path = self._normalize_library_path(getattr(item, "local_path", ""))
            if local_path and self._path_is_within_directory(local_path, normalized_directory):
                paths.add(self._normalize_library_path(os.path.dirname(local_path)))
        paths.discard("")
        return tuple(sorted(paths))

    def _refresh_media_directory_watch_paths(self, directory: str) -> None:
        handle = getattr(self, "_media_directory_watch_handle", None)
        replace_paths = getattr(handle, "replace_paths", None)
        if callable(replace_paths):
            replace_paths(self._media_watch_directories(directory))

    def _prepare_delete_video(self, video_id: str) -> MediaDeleteContext | None:
        """只读取待删媒体；下载线程的停止等待必须由后台任务执行。"""
        video = self._video_lookup(video_id)
        if not video:
            return None
        generation = object()
        with video.meta_guard():
            video._media_delete_generation = generation
        return MediaDeleteContext(
            video_id=video_id,
            video=video,
            cancel_result=None,
            generation=generation,
        )

    def _delete_video_state_guard(self):
        app_state = getattr(self, "app_state", None)
        lock = getattr(app_state, "_lock", None)
        if lock is not None:
            return lock
        return self._video_state_guard()

    def _media_item_lock_pool(self) -> KeyedLockPool:
        app_state = getattr(self, "app_state", None)
        pool = getattr(app_state, "_media_item_locks", None)
        if isinstance(pool, KeyedLockPool):
            return pool
        with _MEDIA_ITEM_POOL_INIT_LOCK:
            pool = getattr(self, "_media_item_locks", None)
            if not isinstance(pool, KeyedLockPool):
                pool = KeyedLockPool()
                self._media_item_locks = pool
            return pool

    def _media_item_guard(self, video_id: str):
        return self._media_item_lock_pool().hold(video_id)

    @staticmethod
    def _snapshot_video_for_file_mutation(video: VideoItem) -> VideoItem:
        """冻结文件操作的路径与元数据，避免授权后再被并发修改。"""

        return deepcopy(video)

    def _mark_delete_context_superseded(self, context: MediaDeleteContext) -> bool:
        generation = getattr(context, "generation", None)
        with self._delete_video_state_guard(), context.video.meta_guard():
            generation_is_current = generation is None or (
                getattr(context.video, "_media_delete_generation", None) is generation
            )
            current = self._video_lookup(context.video_id)
            valid = generation_is_current and (
                current is context.video
                or (current is None and bool(getattr(context, "detached_from_store", False)))
            )
        context.superseded = bool(getattr(context, "superseded", False) or not valid)
        return context.superseded

    @staticmethod
    def _finish_delete_context_generation(context: MediaDeleteContext) -> None:
        generation = getattr(context, "generation", None)
        if generation is None:
            return
        with context.video.meta_guard():
            if getattr(context.video, "_media_delete_generation", None) is generation:
                delattr(context.video, "_media_delete_generation")

    @staticmethod
    def _superseded_delete_outcome(context: MediaDeleteContext) -> MediaDeleteOutcome:
        return MediaDeleteOutcome(
            status="superseded",
            video_id=context.video_id,
            video=context.video,
            cancel_result=context.cancel_result,
            deleted=False,
        )

    def _cancel_delete_context_and_wait(self, context: MediaDeleteContext) -> MediaDeleteContext:
        """停止仍在写入目标文件的任务，避免下载发布与文件删除发生竞态。"""
        if self._mark_delete_context_superseded(context):
            return context
        cancel_video_and_wait = getattr(type(self.dl_manager), "cancel_video_and_wait", None)
        cancel_and_wait = getattr(type(self.dl_manager), "cancel_task_and_wait", None)
        if callable(cancel_video_and_wait):
            cancel_result = self.dl_manager.cancel_video_and_wait(context.video)
        elif callable(cancel_and_wait):
            cancel_result = self.dl_manager.cancel_task_and_wait(context.video_id)
        else:
            cancel_result = self.dl_manager.cancel_task(context.video_id)
        context.cancel_result = cancel_result
        if cancel_result == "timeout":
            raise FileOperationError("Download task did not stop before the deletion timeout")
        self._mark_delete_context_superseded(context)
        return context

    def _begin_delete_video(self, video_id: str) -> MediaDeleteContext | None:
        """删除文件前取消并等待下载任务停写，避免 worker 在删除后继续写回同一路径。"""
        context = self._prepare_delete_video(video_id)
        if context is None:
            return None
        try:
            return self._cancel_delete_context_and_wait(context)
        except Exception:
            self._finish_delete_context_generation(context)
            raise

    def _complete_delete_video_state_locked(
        self,
        context: MediaDeleteContext,
        *,
        deleted: bool,
    ) -> tuple[MediaDeleteOutcome, bool, object | None]:
        """在 per-ID 锁内按 state → meta 完成 compare-and-remove，不发布事件。"""
        generation = getattr(context, "generation", None)
        publish_removal = False
        app_state = getattr(self, "app_state", None)
        with self._delete_video_state_guard():
            with context.video.meta_guard():
                generation_is_current = generation is None or (
                    getattr(context.video, "_media_delete_generation", None) is generation
                )
                current = self._video_lookup(context.video_id)
                valid = generation_is_current and (
                    current is context.video
                    or (current is None and bool(getattr(context, "detached_from_store", False)))
                )
                if not valid:
                    context.superseded = True
                    outcome = self._superseded_delete_outcome(context)
                else:
                    if current is context.video:
                        if app_state is not None and hasattr(app_state, "videos"):
                            app_state.videos.pop(context.video_id, None)
                            task_state = getattr(app_state, "task_state", None)
                            if isinstance(task_state, dict):
                                task_state.pop(context.video_id, None)
                            progress_state = getattr(app_state, "_last_progress_emit_at", None)
                            if isinstance(progress_state, dict):
                                progress_state.pop(context.video_id, None)
                            publish_removal = True
                        else:
                            self._remove_video_item(context.video_id)
                    outcome = MediaDeleteOutcome(
                        status="ok",
                        video_id=context.video_id,
                        video=context.video,
                        cancel_result=context.cancel_result,
                        deleted=deleted,
                    )
        return outcome, publish_removal, app_state

    def _finish_delete_video_completion(
        self,
        context: MediaDeleteContext,
        outcome: MediaDeleteOutcome,
        *,
        publish_removal: bool,
        app_state: object | None,
    ) -> MediaDeleteOutcome:
        """清理 generation 后在全部媒体锁之外发布同步状态事件。"""
        self._finish_delete_context_generation(context)
        if publish_removal:
            publisher = getattr(app_state, "_publish_change", None)
            if callable(publisher):
                publisher("videos.remove", {"video_id": context.video_id})
        return outcome

    def _complete_delete_video(self, context: MediaDeleteContext, *, deleted: bool) -> MediaDeleteOutcome:
        with self._media_item_guard(context.video_id):
            outcome, publish_removal, app_state = self._complete_delete_video_state_locked(
                context,
                deleted=deleted,
            )
        return self._finish_delete_video_completion(
            context,
            outcome,
            publish_removal=publish_removal,
            app_state=app_state,
        )

    def _delete_video_sync(self, video_id: str) -> MediaDeleteOutcome:
        try:
            context = self._begin_delete_video(video_id)
        except FileOperationError as exc:
            return MediaDeleteOutcome(
                status="error",
                video_id=video_id,
                video=self._video_lookup(video_id),
                cancel_result="timeout",
                error=str(exc),
            )
        if context is None:
            return MediaDeleteOutcome(status="missing", video_id=video_id)
        if context.superseded or self._mark_delete_context_superseded(context):
            outcome = self._superseded_delete_outcome(context)
            self._finish_delete_context_generation(context)
            return outcome
        try:
            with self._media_item_guard(context.video_id):
                if self._mark_delete_context_superseded(context):
                    outcome = self._superseded_delete_outcome(context)
                    self._finish_delete_context_generation(context)
                    return outcome
                delete_target = self._snapshot_video_for_file_mutation(context.video)
                deleted = self.file_service.delete_media(delete_target)
                outcome, publish_removal, app_state = self._complete_delete_video_state_locked(
                    context,
                    deleted=deleted,
                )
        except FileOperationError as exc:
            if self._mark_delete_context_superseded(context):
                outcome = self._superseded_delete_outcome(context)
            else:
                outcome = MediaDeleteOutcome(
                    status="error",
                    video_id=video_id,
                    video=context.video,
                    cancel_result=context.cancel_result,
                    error=str(exc),
                )
            self._finish_delete_context_generation(context)
            return outcome
        return self._finish_delete_video_completion(
            context,
            outcome,
            publish_removal=publish_removal,
            app_state=app_state,
        )

    @staticmethod
    def _delete_outcome_messages(outcome: MediaDeleteOutcome) -> list[str]:
        if outcome.status != "ok" or not outcome.video:
            return []
        messages = []
        basename = os.path.basename(outcome.video.local_path) if outcome.video.local_path else outcome.video.title
        if outcome.deleted:
            messages.append(f"🗑️ 已删除: {basename}")
        else:
            messages.append(f"ℹ️ 文件不存在，仅从列表移除: {outcome.video.title}")
        if outcome.cancel_result == "queued":
            messages.append(f"🛑 已取消队列任务: {outcome.video.title}")
        elif outcome.cancel_result == "running":
            messages.append(f"🛑 已请求停止下载: {outcome.video.title}")
        return messages

    def _rename_video_io(
        self,
        video_id: str,
        new_title: str,
        save_dir: str,
        *,
        expected_video: VideoItem | None = None,
    ) -> MediaRenameOutcome:
        normalized_title = new_title.strip()
        with self._media_item_guard(video_id):
            video = self._video_lookup(video_id)
            if not video:
                return MediaRenameOutcome(status="missing", video_id=video_id, error="视频不存在")
            if expected_video is not None and video is not expected_video:
                return MediaRenameOutcome(
                    status="superseded",
                    video_id=video_id,
                    video=expected_video,
                )
            if not normalized_title:
                return MediaRenameOutcome(status="error", video_id=video_id, video=video, error="标题不能为空")
            if not video.local_path or not os.path.exists(video.local_path):
                return MediaRenameOutcome(status="error", video_id=video_id, video=video, error="文件不存在，无法重命名")
            try:
                old_path, new_path = self.file_service.rename_media(video, normalized_title, save_dir)
            except FileOperationError as exc:
                return MediaRenameOutcome(
                    status="error",
                    video_id=video_id,
                    video=video,
                    error=str(exc),
                )
            video.title = normalized_title
            video.local_path = new_path
            return MediaRenameOutcome(
                status="ok",
                video_id=video_id,
                video=video,
                old_path=old_path,
                new_path=new_path,
                new_title=normalized_title,
            )

    def _rename_video_sync(
        self,
        video_id: str,
        new_title: str,
        save_dir: str,
        *,
        expected_video: VideoItem | None = None,
    ) -> MediaRenameOutcome:
        outcome = self._rename_video_io(
            video_id,
            new_title,
            save_dir,
            expected_video=expected_video,
        )
        if outcome.status == "ok" and outcome.video is not None:
            if outcome.new_title is not None:
                outcome.video.title = outcome.new_title
            if outcome.new_path is not None:
                outcome.video.local_path = outcome.new_path
        return outcome

    @staticmethod
    def _rename_outcome_message(outcome: MediaRenameOutcome) -> str | None:
        if outcome.status != "ok" or not outcome.old_path or not outcome.new_path:
            return None
        return f"📝 重命名: {os.path.basename(outcome.old_path)} -> {os.path.basename(outcome.new_path)}"

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
        with self._media_item_guard(item.id):
            with self._video_state_guard():
                self.videos[item.id] = item

    def _remove_video_item(self, video_id: str) -> VideoItem | None:
        with self._video_state_guard():
            return self.videos.pop(video_id, None)
