import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shared import controller_session as session_mixin
from shared.controller_session import ControllerSessionMixin
from app.models import VideoItem

class _DummyController(ControllerSessionMixin):
    DOWNLOAD_LOG_COMPONENT = "DummyController"
    DOWNLOAD_FINISHED_STATUS_CODE = "DUMMY_OK"
    DOWNLOAD_ERROR_STATUS_CODE = "DUMMY_ERR"
    DOWNLOAD_FINISHED_MESSAGE = "dummy finished"
    DOWNLOAD_ERROR_MESSAGE = "dummy error"

    def __init__(self):
        self.videos = {}
        self.current_spider = None
        self.state_updates = []
        self.logs = []
        self.events = []

    def _publish_video_state(self, vid: str, item: VideoItem, *, requested_progress: int | None) -> None:
        self.state_updates.append((vid, item.status, requested_progress))

    def _emit_controller_log(
        self,
        message: str,
        *,
        trace_id: str | None = None,
        source: str = "Controller",
        level: str = "INFO",
    ) -> None:
        self.logs.append({"message": message, "trace_id": trace_id, "source": source, "level": level})

    def _after_task_started(self, video_id: str, item: VideoItem | None) -> None:
        self.events.append(("started", video_id, item.status if item else None))

    def _after_task_progress(self, video_id: str, item: VideoItem | None, progress: int) -> None:
        self.events.append(("progress", video_id, progress))

    def _after_task_finished(self, video_id: str, item: VideoItem | None) -> None:
        self.events.append(("finished", video_id, item.status if item else None))

    def _after_task_error(self, video_id: str, item: VideoItem | None, error: str) -> None:
        self.events.append(("error", video_id, error, item.status if item else None))

    def _build_download_finished_log_details(self, item: VideoItem) -> dict:
        return {"title": item.title}

    def _build_download_error_log_details(self, item: VideoItem, error: str) -> dict:
        return {"title": item.title, "error": error}

class _ProgressResetController(_DummyController):
    DOWNLOAD_ERROR_PROGRESS = 0

class ControllerSessionMixinTests(unittest.TestCase):
    def test_prepare_helpers_align_item_states(self):
        controller = _DummyController()
        pending = VideoItem(url="https://example.com/pending.mp4", title="pending", source="douyin")
        local = VideoItem(url="https://example.com/local.mp4", title="local", source="local")

        controller._prepare_pending_item(pending)
        controller._prepare_local_item(local)

        self.assertEqual((pending.status, pending.progress), ("⏳ 等待中", 0))
        self.assertEqual((local.status, local.progress), ("✅ 本地", 100))

    def test_summarize_active_config_filters_empty_values(self):
        summary = _DummyController._summarize_active_config(
            {"keep_int": 0, "keep_bool": False, "drop_none": None, "drop_str": "", "drop_list": []}
        )
        self.assertEqual(summary, {"keep_int": 0, "keep_bool": False})

    def test_download_lifecycle_runs_shared_hooks(self):
        controller = _DummyController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["trace_id"] = "trace-done"
        controller.videos[item.id] = item

        fake_logger = SimpleNamespace(log=lambda **_kwargs: None)
        with patch.object(session_mixin, "debug_logger", fake_logger):
            controller._on_task_started(item.id)
            controller._on_task_progress(item.id, 35)
            controller._on_task_finished(item.id)

        self.assertEqual(item.status, "✅ 完成")
        self.assertEqual(item.progress, 100)
        self.assertIn(("started", item.id, "⏳ 下载中..."), controller.events)
        self.assertIn(("progress", item.id, 35), controller.events)
        self.assertIn(("finished", item.id, "✅ 完成"), controller.events)
        self.assertTrue(any("下载完成" in item["message"] for item in controller.logs))
        self.assertEqual(controller.logs[-1]["source"], "Downloader")
        self.assertEqual(controller.logs[-1]["trace_id"], "trace-done")

    def test_download_error_respects_controller_progress_policy(self):
        controller = _ProgressResetController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.progress = 88
        item.meta["trace_id"] = "trace-error"
        controller.videos[item.id] = item

        fake_logger = SimpleNamespace(log=lambda **_kwargs: None)
        with patch.object(session_mixin, "debug_logger", fake_logger):
            controller._on_task_error(item.id, "网络超时")

        self.assertEqual(item.status, "❌ 失败")
        self.assertEqual(item.progress, 0)
        self.assertEqual(item.meta["download_error"], "网络超时")
        self.assertIn(("error", item.id, "网络超时", "❌ 失败"), controller.events)
        self.assertTrue(any("下载失败" in item["message"] for item in controller.logs))
        self.assertEqual(controller.logs[-1]["level"], "ERROR")
        self.assertEqual(controller.logs[-1]["trace_id"], "trace-error")
