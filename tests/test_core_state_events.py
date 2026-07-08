import unittest
import sqlite3
import threading
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

    def test_event_bus_storm_warning_does_not_drop_events(self):
        bus = EventBus()
        calls: list[int] = []
        bus.subscribe("storm", calls.append)

        with self.assertLogs("app.core.event_bus", level="WARNING") as logs:
            for index in range(7):
                bus.publish("storm", index)

        self.assertEqual(calls, list(range(7)))
        self.assertTrue(any("EventBus storm detected" in line for line in logs.output))

    def test_event_bus_publish_is_safe_under_concurrent_storm_tracking(self):
        bus = EventBus()
        calls: list[int] = []
        errors: list[Exception] = []
        calls_lock = threading.Lock()

        def handler(payload):
            with calls_lock:
                calls.append(payload)

        def worker(base: int):
            try:
                for offset in range(25):
                    bus.publish("storm", base + offset)
            except Exception as exc:  # pragma: no cover - should fail the assertion below
                errors.append(exc)

        bus.subscribe("storm", handler)
        threads = [threading.Thread(target=worker, args=(index * 100,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(calls), 100)

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

    def test_app_state_video_update_event_includes_terminal_state(self):
        bus = EventBus()
        state = AppState(event_bus=bus, cache_service=CacheService(namespace="test-video-update-payload"))
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.local_path = "downloads/demo.mp4"
        seen: list[dict] = []
        bus.subscribe("app_state.changed", seen.append)

        state.upsert_video(item)
        state.update_video_state(item.id, status=VideoStatus.COMPLETED.label, progress=100)

        payload = seen[-1]
        self.assertEqual(payload["topic"], "videos.update")
        self.assertEqual(payload["video_id"], item.id)
        self.assertEqual(payload["status"], VideoStatus.COMPLETED.label)
        self.assertEqual(payload["progress"], 100)
        self.assertEqual(payload["local_path"], "downloads/demo.mp4")

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

    def test_app_state_progress_gate_throttles_bursts_but_keeps_terminal_updates(self):
        state = AppState(event_bus=EventBus(), cache_service=CacheService(namespace="test-progress-throttle"))

        with patch("app.services.app_state.time.monotonic", side_effect=[100.00, 100.05, 100.30, 100.31]):
            self.assertTrue(state.should_emit_progress("video-1", 10))
            self.assertFalse(state.should_emit_progress("video-1", 11))
            self.assertTrue(state.should_emit_progress("video-1", 11))
            self.assertTrue(state.should_emit_progress("video-1", 100))

    def test_cache_service_falls_back_to_sqlite_when_diskcache_write_fails(self):
        class FailingDiskCache:
            def __init__(self, _path: str) -> None:
                self.values = {}

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, _key, _value, *, expire=None):
                raise RuntimeError("diskcache locked")

            def delete(self, key):
                self.values.pop(key, None)

            def close(self):
                return None

        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            with patch("app.services.cache_service.DiskCache", FailingDiskCache):
                cache = CacheService(namespace="test-cache-diskcache-fallback", cache_dir=temp_dir)
                with patch("app.services.cache_service.debug_logger.log_exception") as log_exception:
                    cache.set("key", "new", persist=True)

                self.assertEqual(cache.get("key"), "new")
                with cache._memory_lock:
                    cache._memory_cache.pop("key", None)
                self.assertEqual(cache.get("key"), "new")
                log_exception.assert_called_once()
                self.assertEqual(log_exception.call_args.args[:2], ("CacheService", "write_diskcache"))

    def test_cache_service_does_not_update_memory_when_all_persistent_writes_fail(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="test-cache-consistency", cache_dir=temp_dir)
            cache.set("key", "old")

            if cache._disk_cache is not None:
                with (
                    patch.object(cache._disk_cache, "set", side_effect=RuntimeError("disk full")),
                    patch.object(cache, "_write_sqlite_persistent", side_effect=RuntimeError("sqlite full")),
                ):
                    with self.assertRaises(RuntimeError):
                        cache.set("key", "new", persist=True)
            else:
                with patch("app.services.cache_service.sqlite3.connect", side_effect=RuntimeError("disk full")):
                    with self.assertRaises(RuntimeError):
                        cache.set("key", "new", persist=True)

            self.assertEqual(cache.get("key"), "old")

    def test_cache_service_treats_corrupt_persistent_value_as_cache_miss(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="test-cache-corrupt", cache_dir=temp_dir)
            with sqlite3.connect(cache._db_path) as conn:
                conn.execute(
                    "INSERT INTO cache_entries(key, value, expires_at) VALUES(?, ?, ?)",
                    ("bad", b"not-a-pickle", None),
                )
                conn.commit()

            with patch("app.services.cache_service.debug_logger.log_exception") as log_exception:
                self.assertEqual(cache.get("bad", "fallback"), "fallback")

            log_exception.assert_called_once()
            self.assertEqual(log_exception.call_args.args[:2], ("CacheService", "read_persistent"))
            with sqlite3.connect(cache._db_path) as conn:
                row = conn.execute("SELECT key FROM cache_entries WHERE key = ?", ("bad",)).fetchone()
            self.assertIsNone(row)

    def test_cache_service_returns_mutation_isolated_values(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            cache = CacheService(namespace="test-cache-isolation", cache_dir=temp_dir)
            cache.set("key", {"nested": {"value": 1}}, persist=True)

            value = cache.get("key")
            value["nested"]["value"] = 2

            self.assertEqual(cache.get("key")["nested"]["value"], 1)

    def test_cache_service_close_releases_diskcache_once(self):
        class FakeDiskCache:
            instances: list["FakeDiskCache"] = []

            def __init__(self, _path: str) -> None:
                self.close_count = 0
                FakeDiskCache.instances.append(self)

            def close(self) -> None:
                self.close_count += 1

        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            with patch("app.services.cache_service.DiskCache", FakeDiskCache):
                cache = CacheService(namespace="test-cache-close", cache_dir=temp_dir)

                cache.close()
                cache.close()

        self.assertEqual(FakeDiskCache.instances[0].close_count, 1)
        self.assertIsNone(cache._disk_cache)

    def test_app_state_shutdown_closes_owned_cache_service(self):
        class CloseableCache:
            def __init__(self, *_args, **_kwargs) -> None:
                self.closed = 0

            def get(self, _key, default=None):
                return default

            def set(self, *_args, **_kwargs) -> None:
                return None

            def close(self) -> None:
                self.closed += 1

        with patch("app.services.app_state.CacheService", CloseableCache):
            state = AppState(event_bus=EventBus())
            cache = state.cache_service

            state.shutdown()
            state.shutdown()

        self.assertEqual(cache.closed, 1)

    def test_app_state_shutdown_does_not_close_borrowed_cache_service(self):
        class BorrowedCache:
            def __init__(self) -> None:
                self.closed = 0

            def get(self, _key, default=None):
                return default

            def set(self, *_args, **_kwargs) -> None:
                return None

            def close(self) -> None:
                self.closed += 1

        cache = BorrowedCache()
        state = AppState(event_bus=EventBus(), cache_service=cache)

        state.shutdown()

        self.assertEqual(cache.closed, 0)
