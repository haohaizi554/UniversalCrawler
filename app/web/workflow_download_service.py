"""Download orchestration helpers extracted from WebWorkflowService."""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from app.core.events import (
    build_task_error_event,
    build_task_finished_event,
    build_task_started_event,
    build_video_state_event,
)
from app.core.state import VideoStatus
from app.models.video_item import VideoItem
from app.web.logging_utils import log_web_event
from shared.runtime_options import infer_content_type, infer_content_type_from_url

BroadcastFn = Callable[[str, Any], Awaitable[None]]


class _WorkflowLoggerCompat:
    """兼容旧测试 patch 接缝，同时把日志转发到统一调试入口。"""

    @staticmethod
    def warning(message: str, *args: Any) -> None:
        if args:
            try:
                message = message % args
            except Exception:
                message = " ".join([message, *(str(arg) for arg in args)])
        log_web_event(
            "WebWorkflowDownloadService",
            "warning",
            message,
            level="WARNING",
        )


logger = _WorkflowLoggerCompat()


class WebWorkflowDownloadService:
    """Owns pending-item creation and download event broadcasting."""

    def __init__(self, controller, broadcast: BroadcastFn):
        self.controller = controller
        self.broadcast = broadcast

    def create_pending_item(self, url: str, source: str, title: str) -> VideoItem:
        item = VideoItem(url=url, title=title, source=source, status=VideoStatus.PENDING.label, progress=0)
        prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
        item.meta["trace_id"] = f"{prefix}-dl-{uuid.uuid4().hex[:8]}"
        pre_ct = infer_content_type_from_url(url)
        if pre_ct:
            item.meta["content_type"] = pre_ct
        return item

    async def broadcast_download_started(self, pending_item: VideoItem) -> None:
        self.controller.videos[pending_item.id] = pending_item
        await self.broadcast("item_found", self.controller._video_item_to_dict(pending_item))
        pending_item.status = VideoStatus.DOWNLOADING.label
        await self.broadcast("task_started", build_task_started_event(pending_item.id, pending_item).to_payload())
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=0).to_payload(),
        )

    async def broadcast_download_error(
        self,
        pending_item: VideoItem,
        error_msg: str,
        *,
        emit_log: Callable[[str], Awaitable[None]],
    ) -> None:
        if "超时" in error_msg:
            pending_item.status = VideoStatus.TIMED_OUT.label
        else:
            pending_item.status = VideoStatus.FAILED.label
        pending_item.progress = 0
        if pending_item.meta is None:
            pending_item.meta = {}
        pending_item.meta["download_error"] = error_msg
        await self.broadcast("task_error", build_task_error_event(pending_item.id, pending_item, error_msg).to_payload())
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=0).to_payload(),
        )
        await emit_log(f"❌ 下载失败: {error_msg}")

    async def broadcast_download_success(
        self,
        pending_item: VideoItem,
        result: dict,
        *,
        emit_log: Callable[[str], Awaitable[None]],
    ) -> dict:
        pending_item.status = VideoStatus.COMPLETED.label
        pending_item.progress = 100
        local_path = result.get("local_path", "")
        if local_path:
            pending_item.local_path = local_path
        pending_item.title = result.get("title", pending_item.title)
        if pending_item.meta is None:
            pending_item.meta = {}
        content_type = result.get("content_type", "")
        if not content_type and local_path:
            content_type = infer_content_type(local_path)
            result["content_type"] = content_type
        if content_type:
            pending_item.meta["content_type"] = content_type
        pending_item.meta.update(result.get("meta", {}))
        result["video_id"] = pending_item.id
        await self.broadcast("task_finished", build_task_finished_event(pending_item.id, pending_item).to_payload())
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=100).to_payload(),
        )
        await emit_log(f"✅ 下载完成: {pending_item.title}")
        return result

    @staticmethod
    def close_sdk(sdk) -> None:
        try:
            sdk.close()
        except Exception as exc:
            logger.warning("workflow 关闭 SDK 失败: %s", exc)
