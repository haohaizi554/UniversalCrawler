import unittest

from app.exceptions import AppError
from app.core.events import (
    build_crawl_state_event,
    build_item_found_event,
    build_log_event,
    build_selection_required_event,
    build_task_error_event,
    build_task_finished_event,
    build_task_started_event,
    build_video_state_event,
)
from app.core.state import CrawlStatus, VideoStatus, parse_video_status, video_status_label
from app.models import VideoItem


class StateAndEventTests(unittest.TestCase):
    def test_app_error_exposes_metadata_for_recovery_and_logging(self):
        error = AppError("boom", code="E_BANG", severity="critical", recoverable=True)

        self.assertEqual(error.code, "E_BANG")
        self.assertEqual(error.severity, "critical")
        self.assertTrue(error.recoverable)
        self.assertEqual(
            error.to_dict(),
            {
                "message": "boom",
                "code": "E_BANG",
                "severity": "critical",
                "recoverable": True,
            },
        )

    def test_video_status_label_supports_enum_and_legacy_label(self):
        self.assertEqual(video_status_label(VideoStatus.PENDING), "⏳ 等待中")
        self.assertEqual(video_status_label("✅ 完成"), "✅ 完成")

    def test_parse_video_status_accepts_enum_value_and_label(self):
        self.assertEqual(parse_video_status(VideoStatus.FAILED), VideoStatus.FAILED)
        self.assertEqual(parse_video_status("❌ 超时"), VideoStatus.TIMED_OUT)
        self.assertEqual(parse_video_status("completed"), VideoStatus.COMPLETED)

    def test_build_video_state_event_adds_status_code_and_terminal_payload(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.status = VideoStatus.COMPLETED.label
        item.progress = 100
        item.local_path = "downloads/demo.mp4"
        item.meta["content_type"] = "video"
        item.meta["trace_id"] = "trace-1"

        event = build_video_state_event(item.id, item, requested_progress=100)
        payload = event.to_payload()

        self.assertEqual(payload["status"], "✅ 完成")
        self.assertEqual(payload["status_code"], "completed")
        self.assertEqual(payload["progress"], 100)
        self.assertEqual(payload["local_path"], "downloads/demo.mp4")
        self.assertEqual(payload["content_type"], "video")
        self.assertEqual(payload["trace_id"], "trace-1")

    def test_build_video_state_event_prefers_requested_progress_over_cached_item_progress(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.status = VideoStatus.DOWNLOADING.label
        item.progress = 0

        payload = build_video_state_event(item.id, item, requested_progress=66).to_payload()

        self.assertEqual(payload["progress"], 66)

    def test_build_crawl_state_event_keeps_canonical_status(self):
        event = build_crawl_state_event(CrawlStatus.RUNNING, is_running=True, source="douyin")
        payload = event.to_payload()

        self.assertEqual(payload["status"], "running")
        self.assertTrue(payload["is_running"])
        self.assertEqual(payload["source"], "douyin")

    def test_build_log_and_selection_events_keep_payload(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        log_payload = build_log_event("hello", channel="gui").to_payload()
        found_event = build_item_found_event(item)
        selection_payload = build_selection_required_event([item]).to_payload()

        self.assertEqual(log_payload["event_type"], "log")
        self.assertEqual(log_payload["message"], "hello")
        self.assertEqual(log_payload["channel"], "gui")
        self.assertEqual(found_event.event_type.value, "item_found")
        self.assertIs(found_event.to_payload()["item"], item)
        self.assertEqual(selection_payload["event_type"], "selection_required")
        self.assertEqual(selection_payload["items"], [item])

    def test_build_task_events_keep_legacy_fields_and_add_event_metadata(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.local_path = "downloads/demo.mp4"
        item.meta["content_type"] = "video"
        item.meta["trace_id"] = "trace-task"

        started = build_task_started_event(item.id, item).to_payload()
        finished = build_task_finished_event(item.id, item).to_payload()
        errored = build_task_error_event(item.id, item, "boom").to_payload()

        self.assertEqual(started["event_type"], "task_started")
        self.assertEqual(started["video_id"], item.id)
        self.assertEqual(started["content_type"], "video")
        self.assertEqual(finished["event_type"], "task_finished")
        self.assertEqual(finished["local_path"], "downloads/demo.mp4")
        self.assertEqual(errored["event_type"], "task_error")
        self.assertEqual(errored["error"], "boom")
        self.assertEqual(errored["trace_id"], "trace-task")

