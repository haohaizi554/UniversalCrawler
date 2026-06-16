from __future__ import annotations

from app.controllers.event_bridge import DomainEventBridge
from app.core.events import (
    DomainEvent,
    DomainEventType,
    build_task_error_event,
    build_task_finished_event,
    build_task_started_event,
)


class DownloadControllerMixin:
    """Shared download bridge and event routing for host-backed controllers."""

    EVENT_BRIDGE_CLASS = DomainEventBridge

    def _connect_download_signals(self):
        """Connect download manager callbacks through the unified download bridge."""
        self.dl_manager.task_started.connect(self._emit_task_started_event)
        self.dl_manager.task_progress.connect(self._emit_task_progress_event)
        self.dl_manager.task_finished.connect(self._emit_task_finished_event)
        self.dl_manager.task_error.connect(self._emit_task_error_event)

    def _publish_video_state(self, vid: str, item, *, requested_progress: int | None) -> None:
        self._host().update_video_status(
            vid,
            item.status,
            requested_progress if requested_progress is not None else item.progress,
        )

    def _emit_controller_log(self, message: str) -> None:
        self._host().append_log(message)

    def _resolve_event_video_item(self, video_id: str):
        item = self.videos.get(video_id)
        if item is not None:
            return item
        find_worker = getattr(self.dl_manager, "_find_worker", None)
        if callable(find_worker):
            worker = find_worker(video_id)
            if worker is not None:
                return getattr(worker, "video", None)
        return None

    def _emit_task_started_event(self, video_id: str) -> None:
        self._download_bridge.sig_event.emit(build_task_started_event(video_id, self._resolve_event_video_item(video_id)))

    def _emit_task_progress_event(self, video_id: str, progress: int) -> None:
        item = self.videos.get(video_id)
        if item is None:
            return
        self._download_bridge.sig_event.emit(
            self._build_video_state_event(video_id, item, requested_progress=progress)
        )

    def _emit_task_finished_event(self, video_id: str) -> None:
        self._download_bridge.sig_event.emit(build_task_finished_event(video_id, self._resolve_event_video_item(video_id)))

    def _emit_task_error_event(self, video_id: str, error: str) -> None:
        self._download_bridge.sig_event.emit(build_task_error_event(video_id, self._resolve_event_video_item(video_id), error))

    @staticmethod
    def _event_payload(event: DomainEvent) -> dict:
        return event.to_payload()

    @staticmethod
    def _event_video_id(event: DomainEvent) -> str | None:
        payload = event.to_payload()
        return payload.get("video_id") or event.entity_id

    def _handle_download_task_started_event(self, event: DomainEvent) -> None:
        video_id = self._event_video_id(event)
        if video_id:
            self._on_task_started(video_id)

    def _handle_download_video_state_event(self, event: DomainEvent) -> None:
        video_id = self._event_video_id(event)
        if not video_id:
            return
        progress = self._event_payload(event).get("progress")
        if progress is not None:
            self._on_task_progress(video_id, progress)

    def _handle_download_task_finished_event(self, event: DomainEvent) -> None:
        video_id = self._event_video_id(event)
        if video_id:
            self._on_task_finished(video_id)

    def _handle_download_task_error_event(self, event: DomainEvent) -> None:
        video_id = self._event_video_id(event)
        if video_id:
            self._on_task_error(video_id, self._event_payload(event).get("error", ""))

    def _download_event_handlers(self) -> dict[DomainEventType, callable]:
        return {
            DomainEventType.TASK_STARTED: self._handle_download_task_started_event,
            DomainEventType.VIDEO_STATE_CHANGED: self._handle_download_video_state_event,
            DomainEventType.TASK_FINISHED: self._handle_download_task_finished_event,
            DomainEventType.TASK_ERROR: self._handle_download_task_error_event,
        }

    def _dispatch_download_event(self, event: DomainEvent) -> None:
        handler = self._download_event_handlers().get(event.event_type)
        if handler:
            handler(event)
