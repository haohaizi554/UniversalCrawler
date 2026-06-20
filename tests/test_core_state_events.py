import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.event_bus import EventBus
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
from app.services.app_state import AppState
from app.services.cache_service import CacheService

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

    def test_event_bus_isolates_handler_failures(self):
        bus = EventBus()
        calls: list[str] = []

        def broken(_payload):
            raise RuntimeError("boom")

        def healthy(payload):
            calls.append(payload)

        bus.subscribe("topic", broken)
        bus.subscribe("topic", healthy)

        bus.publish("topic", "ok")

        self.assertEqual(calls, ["ok"])

    def test_app_state_restores_and_updates_visible_page(self):
        cache_service = CacheService(namespace="test-app-state-visible-page")
        cache_service.set("ui.visible_page", "logs", persist=True)
        state = AppState(event_bus=EventBus(), cache_service=cache_service)

        self.assertEqual(state.get_visible_page(), "logs")
        state.set_visible_page("queue", ["queue", "logs"], emit_change=False)

        self.assertEqual(state.get_visible_page(), "queue")
        self.assertTrue(state.is_page_visible("queue"))
        self.assertFalse(state.is_page_visible("logs"))

    def test_app_state_current_playing_id_is_read_through_state_api(self):
        state = AppState(event_bus=EventBus(), cache_service=CacheService(namespace="test-current-playing"))

        state.set_current_playing_id("video-1")

        self.assertEqual(state.get_current_playing_id(), "video-1")

    def test_app_state_snapshots_do_not_expose_mutable_log_entries(self):
        state = AppState(event_bus=EventBus(), cache_service=CacheService(namespace="test-log-snapshot"))
        state.record_log("hello", trace_id="trace-1")

        logs = state.get_log_buffer()
        logs[0]["message"] = "mutated"

        self.assertEqual(state.get_log_buffer()[0]["message"], "hello")

    def test_app_state_video_snapshots_do_not_share_video_items(self):
        state = AppState(event_bus=EventBus(), cache_service=CacheService(namespace="test-video-snapshot"))
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["nested"] = {"value": 1}
        state.upsert_video(item)

        snapshot = state.snapshot_videos()
        snapshot[item.id].title = "mutated"
        snapshot[item.id].meta["nested"]["value"] = 2

        fresh = state.snapshot_videos()[item.id]
        self.assertEqual(fresh.title, "demo")
        self.assertEqual(fresh.meta["nested"]["value"], 1)

    def test_app_state_publish_change_limits_recursive_event_storms(self):
        bus = EventBus()
        state = AppState(event_bus=bus, cache_service=CacheService(namespace="test-publish-depth"))
        calls: list[int] = []

        def republish(_payload):
            calls.append(len(calls))
            state._publish_change("loop", {})

        bus.subscribe("app_state.changed", republish)

        state._publish_change("loop", {})

        self.assertEqual(len(calls), state.MAX_PUBLISH_DEPTH)

    def test_cache_service_does_not_update_memory_when_persistent_write_fails(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="test-cache-consistency", cache_dir=temp_dir)
            cache.set("key", "old")

            with patch("app.services.cache_service.sqlite3.connect", side_effect=RuntimeError("disk full")):
                with self.assertRaises(RuntimeError):
                    cache.set("key", "new", persist=True)

            self.assertEqual(cache.get("key"), "old")

    def test_cache_service_returns_mutation_isolated_values(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="test-cache-isolation", cache_dir=temp_dir)
            cache.set("key", {"nested": {"value": 1}}, persist=True)

            value = cache.get("key")
            value["nested"]["value"] = 2

            self.assertEqual(cache.get("key")["nested"]["value"], 1)

