import unittest
from unittest.mock import Mock

from app.controllers.download_controller_mixin import DownloadControllerMixin
from app.core.events import build_log_event, build_task_error_event, build_task_finished_event, build_task_started_event
from app.models import VideoItem
from shared.controller_session import ControllerSessionMixin

class _DummyDownloadController(DownloadControllerMixin, ControllerSessionMixin):
    DOWNLOAD_LOG_COMPONENT = "DummyDownloadController"
    DOWNLOAD_FINISHED_STATUS_CODE = "DUMMY_OK"
    DOWNLOAD_ERROR_STATUS_CODE = "DUMMY_ERR"
    DOWNLOAD_FINISHED_MESSAGE = "dummy finished"
    DOWNLOAD_ERROR_MESSAGE = "dummy error"

    def __init__(self):
        self.dl_manager = Mock()
        self.host = Mock()
        self.videos = {}
        self._download_bridge = Mock()

    def _host(self):
        return self.host

    def _emit_controller_log(
        self,
        message: str,
        *,
        trace_id: str | None = None,
        source: str = "Controller",
        level: str = "INFO",
    ) -> None:
        self.host.append_log(message, trace_id=trace_id, source=source, level=level)

    def _publish_video_state(self, vid: str, item, *, requested_progress: int | None) -> None:
        self.host.update_video_status(
            vid,
            item.status,
            requested_progress if requested_progress is not None else item.progress,
        )

class DownloadControllerMixinTests(unittest.TestCase):
    def test_connect_download_signals_binds_bridge_callbacks(self):
        controller = _DummyDownloadController()

        controller._connect_download_signals()

        controller.dl_manager.task_started.connect.assert_called_once_with(controller._emit_task_started_event)
        controller.dl_manager.task_progress.connect.assert_called_once_with(controller._emit_task_progress_event)
        controller.dl_manager.task_finished.connect.assert_called_once_with(controller._emit_task_finished_event)
        controller.dl_manager.task_error.connect.assert_called_once_with(controller._emit_task_error_event)

    def test_emit_task_progress_event_ignores_unknown_video(self):
        controller = _DummyDownloadController()

        controller._emit_task_progress_event("missing", 66)

        controller._download_bridge.sig_event.emit.assert_not_called()

    def test_emit_task_progress_event_drops_duplicate_percentages(self):
        controller = _DummyDownloadController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        controller.videos[item.id] = item

        for progress in (10, 10, "10", 11):
            controller._emit_task_progress_event(item.id, progress)

        events = [call.args[0].to_payload() for call in controller._download_bridge.sig_event.emit.call_args_list]
        self.assertEqual([event["progress"] for event in events], [10, 11])

    def test_emit_task_started_event_falls_back_to_running_worker_video(self):
        controller = _DummyDownloadController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.local_path = "downloads/demo.mp4"
        controller.dl_manager._find_worker.return_value = Mock(video=item)

        controller._emit_task_started_event(item.id)

        event = controller._download_bridge.sig_event.emit.call_args.args[0]
        payload = event.to_payload()
        self.assertEqual(payload["title"], "demo")
        self.assertEqual(payload["local_path"], "downloads/demo.mp4")

    def test_publish_video_state_uses_requested_progress_or_item_progress(self):
        controller = _DummyDownloadController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.status = "⏳ 下载中..."
        item.progress = 35

        controller._publish_video_state(item.id, item, requested_progress=66)
        controller._publish_video_state(item.id, item, requested_progress=None)

        self.assertEqual(
            controller.host.update_video_status.call_args_list,
            [
                unittest.mock.call(item.id, "⏳ 下载中...", 66),
                unittest.mock.call(item.id, "⏳ 下载中...", 35),
            ],
        )

    def test_dispatch_download_event_routes_to_shared_handlers(self):
        controller = _DummyDownloadController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        controller.videos[item.id] = item
        controller._on_task_started = Mock()
        controller._on_task_progress = Mock()
        controller._on_task_finished = Mock()
        controller._on_task_error = Mock()

        controller._dispatch_download_event(build_task_started_event(item.id, item))
        controller._dispatch_download_event(controller._build_video_state_event(item.id, item, requested_progress=80))
        controller._dispatch_download_event(build_task_finished_event(item.id, item))
        controller._dispatch_download_event(build_task_error_event(item.id, item, "网络超时"))

        controller._on_task_started.assert_called_once_with(item.id)
        controller._on_task_progress.assert_called_once_with(item.id, 80)
        controller._on_task_finished.assert_called_once_with(item.id)
        controller._on_task_error.assert_called_once_with(item.id, "网络超时")

    def test_dispatch_download_event_ignores_irrelevant_event_types(self):
        controller = _DummyDownloadController()
        controller._on_task_started = Mock()

        controller._dispatch_download_event(build_log_event("noop"))
        controller._dispatch_download_event(build_task_started_event("", None))

        controller._on_task_started.assert_not_called()

if __name__ == "__main__":
    unittest.main()
