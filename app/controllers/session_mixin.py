from __future__ import annotations

from typing import Any

from app.debug_logger import debug_logger
from app.models import VideoItem


class ControllerSessionMixin:
    """Shared controller session behavior for GUI and Web adapters."""

    DOWNLOAD_LOG_COMPONENT = "ControllerSession"
    DOWNLOAD_FINISHED_STATUS_CODE = "CTRL_DL_FINISH"
    DOWNLOAD_ERROR_STATUS_CODE = "CTRL_DL_ERROR"
    DOWNLOAD_FINISHED_MESSAGE = "下载任务完成"
    DOWNLOAD_ERROR_MESSAGE = "下载任务失败"
    DOWNLOAD_ERROR_PROGRESS: int | None = None

    def _has_active_spider(self) -> bool:
        return bool(self.current_spider and self.current_spider.isRunning())

    @staticmethod
    def _item_trace_id(item: VideoItem | None) -> str | None:
        return item.meta.get("trace_id") if item else None

    @classmethod
    def _item_context(cls, item: VideoItem | None) -> dict[str, Any]:
        if not item:
            return {}
        return {
            "trace_id": cls._item_trace_id(item),
            "video_id": item.id,
            "source": item.source,
        }

    @staticmethod
    def _summarize_active_config(config: dict) -> dict:
        return {k: v for k, v in config.items() if v not in (None, "", [], {})}

    @staticmethod
    def _prepare_pending_item(item: VideoItem) -> VideoItem:
        item.status = "⏳ 等待中"
        item.progress = 0
        return item

    @staticmethod
    def _prepare_local_item(item: VideoItem) -> VideoItem:
        item.status = "✅ 本地"
        item.progress = 100
        return item

    def _apply_video_state(
        self,
        vid: str,
        *,
        status: str | None = None,
        progress: int | None = None,
    ) -> VideoItem | None:
        item = self.videos.get(vid)
        if not item:
            return None
        if status is not None:
            item.status = status
        if progress is not None:
            item.progress = progress
        self._publish_video_state(vid, item, requested_progress=progress)
        return item

    def _update_video_status(self, vid: str, status: str, progress: int | None = None) -> None:
        self._apply_video_state(vid, status=status, progress=progress)

    def _update_video_progress(self, vid: str, progress: int) -> None:
        self._apply_video_state(vid, progress=progress)

    def _on_task_started(self, video_id: str) -> None:
        item = self._apply_video_state(video_id, status="⏳ 下载中...", progress=0)
        self._after_task_started(video_id, item)

    def _on_task_progress(self, video_id: str, progress: int) -> None:
        item = self._apply_video_state(video_id, progress=progress)
        self._after_task_progress(video_id, item, progress)

    def _on_task_finished(self, video_id: str) -> None:
        self._on_download_finished(video_id)

    def _on_task_error(self, video_id: str, error: str) -> None:
        self._on_download_error(video_id, error)

    def _on_download_finished(self, vid: str) -> None:
        item = self._apply_video_state(vid, status="✅ 完成", progress=100)
        self._after_task_finished(vid, item)
        if not item:
            return
        self._emit_controller_log(f"✅ 下载完成: {item.title}")
        debug_logger.log(
            component=self.DOWNLOAD_LOG_COMPONENT,
            action="download_finished",
            message=self.DOWNLOAD_FINISHED_MESSAGE,
            status_code=self.DOWNLOAD_FINISHED_STATUS_CODE,
            context=self._item_context(item),
            details=self._build_download_finished_log_details(item),
            trace_id=self._item_trace_id(item),
        )

    def _on_download_error(self, vid: str, error: str) -> None:
        item = self._apply_video_state(vid, status="❌ 失败", progress=self.DOWNLOAD_ERROR_PROGRESS)
        if item:
            if item.meta is None:
                item.meta = {}
            item.meta["download_error"] = error
        self._after_task_error(vid, item, error)
        if not item:
            return
        self._emit_controller_log(f"❌ 下载失败 [{item.title}]: {error}")
        debug_logger.log(
            component=self.DOWNLOAD_LOG_COMPONENT,
            action="download_error",
            level="ERROR",
            message=self.DOWNLOAD_ERROR_MESSAGE,
            status_code=self.DOWNLOAD_ERROR_STATUS_CODE,
            context=self._item_context(item),
            details=self._build_download_error_log_details(item, error),
            trace_id=self._item_trace_id(item),
        )

    def _after_task_started(self, video_id: str, item: VideoItem | None) -> None:
        pass

    def _after_task_progress(self, video_id: str, item: VideoItem | None, progress: int) -> None:
        pass

    def _after_task_finished(self, video_id: str, item: VideoItem | None) -> None:
        pass

    def _after_task_error(self, video_id: str, item: VideoItem | None, error: str) -> None:
        pass

    def _build_download_finished_log_details(self, item: VideoItem) -> dict[str, Any]:
        return {}

    def _build_download_error_log_details(self, item: VideoItem, error: str) -> dict[str, Any]:
        return {"error": error}

    def _publish_video_state(self, vid: str, item: VideoItem, *, requested_progress: int | None) -> None:
        raise NotImplementedError

    def _emit_controller_log(self, message: str) -> None:
        raise NotImplementedError
