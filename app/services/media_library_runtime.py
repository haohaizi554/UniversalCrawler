from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from app.config import cfg
from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.file_service import ScanResult

@dataclass
class MediaDeleteContext:
    video_id: str
    video: VideoItem
    cancel_result: str | None

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

    def _prepare_delete_video(self, video_id: str) -> MediaDeleteContext | None:
        """只读取待删媒体；下载线程的停止等待必须由后台任务执行。"""
        video = self._video_lookup(video_id)
        if not video:
            return None
        return MediaDeleteContext(video_id=video_id, video=video, cancel_result=None)

    def _cancel_delete_context_and_wait(self, context: MediaDeleteContext) -> MediaDeleteContext:
        """停止仍在写入目标文件的任务，避免下载发布与文件删除发生竞态。"""
        cancel_and_wait = getattr(type(self.dl_manager), "cancel_task_and_wait", None)
        if callable(cancel_and_wait):
            cancel_result = self.dl_manager.cancel_task_and_wait(context.video_id)
        else:
            cancel_result = self.dl_manager.cancel_task(context.video_id)
        context.cancel_result = cancel_result
        if cancel_result == "timeout":
            raise FileOperationError("Download task did not stop before the deletion timeout")
        return context

    def _begin_delete_video(self, video_id: str) -> MediaDeleteContext | None:
        """删除文件前取消并等待下载任务停写，避免 worker 在删除后继续写回同一路径。"""
        context = self._prepare_delete_video(video_id)
        if context is None:
            return None
        return self._cancel_delete_context_and_wait(context)

    def _complete_delete_video(self, context: MediaDeleteContext, *, deleted: bool) -> MediaDeleteOutcome:
        self._remove_video_item(context.video_id)
        return MediaDeleteOutcome(
            status="ok",
            video_id=context.video_id,
            video=context.video,
            cancel_result=context.cancel_result,
            deleted=deleted,
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
        try:
            deleted = self.file_service.delete_media(context.video)
        except FileOperationError as exc:
            return MediaDeleteOutcome(
                status="error",
                video_id=video_id,
                video=context.video,
                cancel_result=context.cancel_result,
                error=str(exc),
            )
        return self._complete_delete_video(context, deleted=deleted)

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

    def _rename_video_io(self, video_id: str, new_title: str, save_dir: str) -> MediaRenameOutcome:
        video = self._video_lookup(video_id)
        if not video:
            return MediaRenameOutcome(status="missing", video_id=video_id, error="视频不存在")
        normalized_title = new_title.strip()
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
        return MediaRenameOutcome(
            status="ok",
            video_id=video_id,
            video=video,
            old_path=old_path,
            new_path=new_path,
            new_title=normalized_title,
        )

    def _rename_video_sync(self, video_id: str, new_title: str, save_dir: str) -> MediaRenameOutcome:
        outcome = self._rename_video_io(video_id, new_title, save_dir)
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
        with self._video_state_guard():
            self.videos[item.id] = item

    def _remove_video_item(self, video_id: str) -> VideoItem | None:
        with self._video_state_guard():
            return self.videos.pop(video_id, None)
