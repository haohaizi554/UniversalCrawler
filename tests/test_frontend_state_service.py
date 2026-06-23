import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.state import VideoStatus
from app.models import VideoItem
from app.services.frontend_state_service import FrontendStateService, QUEUE_STATUSES
from app.services.media_metadata_service import MediaMetadata

class FrontendStateServiceTests(unittest.TestCase):
    def test_snapshot_exposes_all_required_sections(self):
        service = FrontendStateService()
        snapshot = service.get_snapshot(mock=True)

        for key in (
            "queue_items",
            "active_downloads",
            "completed_items",
            "failed_items",
            "log_items",
            "settings_snapshot",
            "download_options",
            "toolbox_items",
            "toolbox_recent_items",
            "app_status",
        ):
            self.assertIn(key, snapshot)

    def test_toolbox_items_include_shared_detail_contract(self):
        snapshot = FrontendStateService().get_snapshot(mock=True)

        first_tool = snapshot["toolbox_items"][0]

        self.assertIn("icon_file", first_tool)
        self.assertIn("input_example", first_tool)
        self.assertIn("output_example", first_tool)
        self.assertIn("toolbox_recent_items", snapshot)

    def test_video_items_are_bucketed_for_seven_page_contract(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "⏳ 等待中"
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 42
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "✅ 本地"
        completed.progress = 100
        completed.local_path = __file__
        failed = VideoItem(url="https://example.com/f", title="failed", source="douyin")
        failed.status = "❌ 失败"
        failed.meta["trace_id"] = "trace-123"
        failed.meta["download_error"] = "网络超时"
        controller = SimpleNamespace(videos={item.id: item for item in (queued, active, completed, failed)}, _dl_manager=None, current_spider=None)

        snapshot = FrontendStateService(controller).get_snapshot()

        self.assertEqual([item["id"] for item in snapshot["queue_items"]], [queued.id])
        self.assertEqual(snapshot["queue_items"][0]["status"], "待下载")
        self.assertIn(snapshot["queue_items"][0]["status"], QUEUE_STATUSES)
        self.assertEqual([item["id"] for item in snapshot["active_downloads"]], [active.id])
        self.assertEqual([item["id"] for item in snapshot["completed_items"]], [completed.id])
        self.assertEqual([item["id"] for item in snapshot["failed_items"]], [failed.id])
        self.assertEqual(snapshot["failed_items"][0]["trace_id"], "trace-123")

    def test_active_item_synthesizes_rich_events_when_downloader_events_are_sparse(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 67
        item.meta.update(
            {
                "speed": "1.4 MB/s",
                "chunks_done": 67,
                "chunks_total": 100,
                "remaining_time": "00:13",
                "write_status": "\u6b63\u5728\u5199\u5165",
                "merge_status": "\u7b49\u5f85\u5408\u5e76",
                "trace_id": "trace-active",
                "events": [{"time": "10:00:00", "message": "started"}],
            }
        )

        payload = FrontendStateService()._active_item(item)
        messages = [event["message"] for event in payload["events"]]

        self.assertGreaterEqual(len(messages), 4)
        self.assertEqual(messages[0], "started")
        self.assertTrue(all(event["time"] == "10:00:00" for event in payload["events"]))
        self.assertTrue(any("1.4 MB/s" in message for message in messages))
        self.assertTrue(any("Trace ID" in message for message in messages))

    def test_active_item_uses_stable_metadata_time_for_derived_events(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 10
        item.meta.update({"created_at": "2026-06-21 20:12:35"})

        payload = FrontendStateService()._active_item(item)

        self.assertTrue(payload["events"])
        self.assertTrue(all(event["time"] == "20:12:35" for event in payload["events"]))

    def test_active_item_caches_generated_event_time_when_metadata_is_missing(self):
        item = VideoItem(url="https://example.com/a.mp4", title="active", source="douyin")
        item.progress = 10
        service = FrontendStateService()

        first = service._active_item(item)
        item.progress = 20
        second = service._active_item(item)

        first_times = {event["time"] for event in first["events"]}
        second_times = {event["time"] for event in second["events"]}
        self.assertEqual(len(first_times), 1)
        self.assertEqual(first_times, second_times)
        self.assertNotIn("--:--:--", first_times)

    def test_completed_terminal_state_wins_over_stale_active_worker_id(self):
        item = VideoItem(url="https://example.com/bili.m4s", title="bili done", source="bilibili")
        item.status = VideoStatus.COMPLETED.label
        item.progress = 100
        item.local_path = __file__
        item.meta.update({"speed": "940.9 KB/s", "speed_bps": 963482})
        manager = SimpleNamespace(workers=[SimpleNamespace(video=item)], _workers_lock=threading.RLock())
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=manager, current_spider=None)

        snapshot = FrontendStateService(controller).get_snapshot()

        self.assertEqual(snapshot["active_downloads"], [])
        self.assertEqual([row["id"] for row in snapshot["completed_items"]], [item.id])
        self.assertEqual(snapshot["completed_items"][0]["download_speed"], "940.9 KB/s")

    def test_completed_item_uses_cached_local_media_metadata(self):
        class FakeMetadataService:
            def cached(self, _path):
                return MediaMetadata(duration="00:01:23", resolution="1920 x 1080", format="MP4", content_type="video")

            def ensure_probe(self, *_args, **_kwargs):
                raise AssertionError("cache hit should not schedule probe")

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "done.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            item.meta["completed_at"] = "2026-06-21 04:49:33"
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["completed_at"], "2026-06-21 04:49:33")
        self.assertEqual(payload["completed_at_table"], "06-21 04:49")
        self.assertEqual(payload["duration"], "00:01:23")
        self.assertEqual(payload["resolution"], "1920 x 1080")
        self.assertEqual(payload["format"], "MP4")
        self.assertEqual(payload["filename"], "done.mp4")
        self.assertEqual(payload["save_dir"], str(path.parent))
        self.assertEqual(payload["content_type"], "video")
        self.assertFalse(payload["metadata_pending"])

    def test_completed_item_marks_metadata_pending_without_blocking(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pending.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="pending", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["duration"], "检测中")
        self.assertEqual(payload["resolution"], "检测中")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_item_keeps_metadata_pending_during_probe_cooldown(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return False

            def is_probe_deferred(self, _path):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cooldown.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="cooldown", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["duration"], "检测中")
        self.assertEqual(payload["resolution"], "检测中")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_snapshot_limits_metadata_probe_fanout(self):
        class FakeMetadataService:
            def __init__(self):
                self.calls = 0

            def cached(self, _path):
                return None

            def is_probe_deferred(self, _path):
                return False

            def ensure_probe(self, _path, _callback):
                self.calls += 1
                return True

        with TemporaryDirectory() as temp_dir:
            videos = {}
            for index in range(8):
                path = Path(temp_dir) / f"{index}.mp4"
                path.write_bytes(b"media")
                item = VideoItem(url="", title=f"done-{index}", source="local")
                item.status = VideoStatus.COMPLETED.label
                item.progress = 100
                item.local_path = str(path)
                videos[item.id] = item
            metadata = FakeMetadataService()
            service = FrontendStateService(SimpleNamespace(videos=videos), media_metadata_service=metadata)
            service.METADATA_PROBES_PER_SNAPSHOT = 3

            snapshot = service.get_snapshot(sections=frozenset({"completed_items"}))

        self.assertEqual(metadata.calls, 3)
        self.assertEqual(len(snapshot["completed_items"]), 8)
        self.assertTrue(all(item["metadata_pending"] for item in snapshot["completed_items"]))

    def test_completed_item_quality_label_does_not_block_real_resolution_probe(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, _callback):
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quality-only.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="quality only", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            item.meta.update({"duration": "00:00:22", "quality": "1080p"})
            service = FrontendStateService(media_metadata_service=FakeMetadataService())

            payload = service._completed_item(item)

        self.assertEqual(payload["resolution"], "检测中")
        self.assertTrue(payload["metadata_pending"])

    def test_completed_metadata_probe_emits_completed_refresh_event(self):
        class FakeMetadataService:
            def cached(self, _path):
                return None

            def ensure_probe(self, _path, callback):
                callback(MediaMetadata(duration="00:01:05", resolution="720 x 1280", format="MP4", content_type="video"))
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "done.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            events: list[tuple[str, dict]] = []
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                media_metadata_service=FakeMetadataService(),
                frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
            )

            service._completed_item(item)
            refreshed = service._completed_item(item)

        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": True})])
        self.assertEqual(refreshed["duration"], "00:01:05")
        self.assertEqual(refreshed["resolution"], "720 x 1280")

    def test_empty_completed_metadata_probe_is_not_marked_useful(self):
        class FakeMetadataService:
            EMPTY_RETRY_SECONDS = 60.0

            def cached(self, _path):
                return None

            def ensure_probe(self, _path, callback):
                callback(MediaMetadata(format="MP4", content_type="video"))
                return True

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.mp4"
            path.write_bytes(b"media")
            item = VideoItem(url="", title="done", source="local")
            item.status = VideoStatus.COMPLETED.label
            item.progress = 100
            item.local_path = str(path)
            events: list[tuple[str, dict]] = []
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                media_metadata_service=FakeMetadataService(),
                frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
            )

            payload = service._completed_item(item)
            service.invalidate_refresh_caches()

        self.assertEqual(payload["duration"], "\u68c0\u6d4b\u4e2d")
        self.assertEqual(payload["resolution"], "\u68c0\u6d4b\u4e2d")
        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": False})])

    def test_completed_metadata_path_compare_treats_slashes_as_equivalent(self):
        self.assertTrue(
            FrontendStateService._same_local_path(
                r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads\a.mp4",
                "D:/desktop/project/UniversalCrawlerProplus/user_data/Downloads/a.mp4",
            )
        )

    def test_update_completed_metadata_backfills_missing_values_only(self):
        item = VideoItem(url="", title="done", source="local")
        item.status = VideoStatus.COMPLETED.label
        item.progress = 100
        item.meta.update({"duration": "--", "resolution": "1080p", "format": "MP4"})
        events: list[tuple[str, dict]] = []
        service = FrontendStateService(
            SimpleNamespace(videos={item.id: item}),
            frontend_event_emitter=lambda topic, payload: events.append((topic, payload)),
        )

        result = service.update_completed_metadata(
            item.id,
            {"duration_ms": 208000, "width": 1920, "height": 1080, "format": "WEBM"},
            source="test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["changed"])
        self.assertEqual(item.meta["duration"], "00:03:28")
        self.assertEqual(item.meta["resolution"], "1920 x 1080")
        self.assertEqual(item.meta["format"], "MP4")
        self.assertEqual(events, [("videos.metadata", {"video_id": item.id, "metadata": True, "source": "test"})])

    def test_log_items_use_trace_id_without_task_id_column(self):
        service = FrontendStateService()
        service.record_log("download failed", level="ERROR", source="Downloader", trace_id="trace-1")

        item = service.get_snapshot()["log_items"][-1]

        self.assertIn("trace_id", item)
        self.assertNotIn("task_id", item)

    def test_log_event_payload_is_persisted_with_trace_id(self):
        service = FrontendStateService()

        service.record_event(
            "log",
            {
                "message": "解析完成",
                "level": "INFO",
                "source": "bilibili",
                "trace_id": "bilibili-crawl-1",
            },
        )

        item = service.get_snapshot()["log_items"][-1]
        self.assertEqual(item["message_summary"], "解析完成")
        self.assertEqual(item["trace_id"], "bilibili-crawl-1")
        self.assertEqual(item["source"], "bilibili")

    def test_failed_item_actions_exclude_retry(self):
        item = VideoItem(url="https://example.com", title="failed", source="douyin")
        item.status = VideoStatus.FAILED.label
        item.meta["error"] = "403"
        item.meta["trace_id"] = "trace-failed"
        item.meta["failed_at"] = "2026-06-22 16:32:23"
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))
        service.record_log("download failed with 403", level="ERROR", source="Downloader", trace_id="trace-failed")

        failed = service.get_snapshot(sections=frozenset({"failed_items"}))["failed_items"][0]

        self.assertEqual(failed["actions"], ["copy_diagnostics", "delete"])
        self.assertEqual(failed["reason_label"], "链接失败")
        self.assertEqual(failed["reason_icon_file"], "action_trace_link.png")
        self.assertEqual(failed["failed_at_table"], "06-22 16:32")
        self.assertEqual(failed["status_label"], "失败")
        self.assertEqual(failed["status_icon_file"], "status_failed.png")
        self.assertEqual(failed["log_excerpt"], ["download failed with 403"])
        self.assertEqual(failed["log_excerpt_items"][0]["icon_file"], "log_level_error.png")
        self.assertTrue(all(solution.get("icon_file") for solution in failed["solutions"]))

    def test_copy_diagnostics_action_returns_trace_id_only(self):
        item = VideoItem(url="https://example.com", title="failed", source="douyin")
        item.meta["trace_id"] = "trace-copy"
        service = FrontendStateService(SimpleNamespace(videos={item.id: item}))

        result = service.handle_action("copy_diagnostics", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["text"], "trace-copy")
        self.assertEqual(result["data"]["trace_id"], "trace-copy")

    def test_open_directory_action_uses_injected_service_boundary(self):
        with TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "done.mp4"
            media_path.write_text("mock", encoding="utf-8")
            item = VideoItem(url="", title="done", source="local")
            item.local_path = str(media_path)
            opener = Mock()
            service = FrontendStateService(
                SimpleNamespace(videos={item.id: item}),
                directory_opener=opener,
            )

            result = service.handle_action("open_directory", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        opener.assert_called_once_with(str(media_path.parent))

    def test_register_file_associations_action_uses_service_boundary(self):
        association_service = SimpleNamespace(
            register_current_user=Mock(return_value=SimpleNamespace(registered=True, message="")),
            set_current_user_defaults=Mock(
                return_value=SimpleNamespace(
                    defaulted_extensions=(".mp4",),
                    failed_extensions=(),
                    message="",
                )
            ),
            diagnose_current_user=Mock(return_value=SimpleNamespace(available=True, pending_extensions=())),
            open_default_apps_settings=Mock(return_value=True),
        )
        service = FrontendStateService(
            association_service_factory=lambda: association_service,
            executable_path_provider=lambda: r"C:\App\UniversalCrawlerPro.exe",
        )

        result = service.handle_action("register_file_associations", {"include_video": True, "include_image": False})

        self.assertEqual(result["status"], "ok")
        association_service.register_current_user.assert_called_once_with(
            r"C:\App\UniversalCrawlerPro.exe",
            include_video=True,
            include_image=False,
        )
        association_service.set_current_user_defaults.assert_called_once_with(include_video=True, include_image=False)
        association_service.diagnose_current_user.assert_called_once_with(include_video=True, include_image=False)
        association_service.open_default_apps_settings.assert_not_called()
        self.assertEqual(result["data"]["defaulted_extensions"], [".mp4"])

    def test_run_tool_rejects_unknown_tool_id(self):
        result = FrontendStateService().handle_action("run_tool", {"tool_id": "not_real"})

        self.assertEqual(result["status"], "error")

    def test_pause_download_action_cancels_manager_task_and_marks_item_pending(self):
        item = VideoItem(url="https://example.com/video.mp4", title="active", source="douyin")
        manager = SimpleNamespace(cancel_task=Mock(return_value="running"))
        controller = SimpleNamespace(videos={item.id: item}, _dl_manager=manager)
        service = FrontendStateService(controller)

        result = service.handle_action("pause_download", {"id": item.id})

        self.assertEqual(result["status"], "ok")
        manager.cancel_task.assert_called_once_with(item.id)
        self.assertTrue(item.meta["user_cancel_requested"])
        self.assertEqual(item.meta["frontend_status"], "待下载")

    def test_update_download_options_applies_live_manager_concurrency(self):
        class FakeConfig:
            def __init__(self):
                self.values = {("download", "max_concurrent"): 3, ("download", "max_retries"): 3}
                self.set_calls = []

            def get(self, section, key, default=None):
                return self.values.get((section, key), default)

            def set(self, section, key, value):
                self.values[(section, key)] = value
                self.set_calls.append((section, key, value))

        manager = SimpleNamespace(set_max_concurrent=Mock(return_value=5))
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        config = FakeConfig()
        service = FrontendStateService(controller, config_manager=config, cache_service=cache)

        result = service.handle_action(
            "update_download_options",
            {"auto_retry": True, "max_retries": 5, "max_concurrent": 6},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], {"auto_retry": True, "max_retries": 5, "max_concurrent": 5})
        self.assertIn(("download", "max_concurrent", 5), config.set_calls)
        self.assertIn(("download", "max_retries", 5), config.set_calls)
        manager.set_max_concurrent.assert_called_once_with(6)
        cache.set.assert_called_once_with("download.auto_retry", True, persist=False)

    def test_download_options_snapshot_uses_effective_manager_values(self):
        class FakeConfig:
            data = {"download": {"max_concurrent": 3, "max_retries": 7}}

            def get(self, section, key, default=None):
                return self.data.get(section, {}).get(key, default)

        manager = SimpleNamespace(max_concurrent=6)
        controller = SimpleNamespace(_dl_manager=manager)
        cache = Mock()
        cache.get.return_value = False
        service = FrontendStateService(controller, config_manager=FakeConfig(), cache_service=cache)

        snapshot = service.get_snapshot(sections=frozenset({"download_options"}))

        self.assertEqual(
            snapshot["download_options"],
            {"auto_retry": False, "max_retries": 7, "max_concurrent": 6},
        )

    def test_partial_snapshot_returns_requested_sections_only(self):
        service = FrontendStateService()
        service._static_snapshot_cache = {
            "pages": [],
            "settings_snapshot": {},
            "toolbox_items": [],
            "toolbox_recent_items": [],
            "icon_manifest": {},
        }
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 10
        controller = SimpleNamespace(videos={active.id: active}, _dl_manager=None)
        service.controller = controller

        snapshot = service.get_snapshot(sections=frozenset({"active_downloads", "app_status"}))

        self.assertIn("active_downloads", snapshot)
        self.assertIn("save_dir", snapshot["active_downloads"][0])
        self.assertIn("output_filename", snapshot["active_downloads"][0])
        self.assertIn("app_status", snapshot)
        self.assertNotIn("queue_items", snapshot)
        self.assertNotIn("log_items", snapshot)

    def test_partial_app_status_keeps_completed_count_when_bucket_not_requested(self):
        queued = VideoItem(url="https://example.com/q", title="queued", source="douyin")
        queued.status = "⏳ 等待中"
        completed = VideoItem(url="", title="done", source="local")
        completed.status = "✅ 本地"
        completed.progress = 100
        completed.local_path = __file__
        active = VideoItem(url="https://example.com/a", title="active", source="douyin")
        active.status = "⏳ 下载中..."
        active.progress = 25
        active.meta["speed_bps"] = 2048
        active.meta["speed"] = "2.0 KB/s"
        controller = SimpleNamespace(
            videos={item.id: item for item in (queued, completed, active)},
            _dl_manager=None,
        )
        service = FrontendStateService(controller)

        snapshot = service.get_snapshot(sections=frozenset({"active_downloads", "app_status"}))

        self.assertEqual(snapshot["app_status"]["completed_count"], 1)
        self.assertEqual(snapshot["app_status"]["failed_count"], 0)
        self.assertIn("2.0 KB/s", snapshot["app_status"]["download_speed"])

    def test_log_excerpt_index_builds_trace_lookup_once(self):
        service = FrontendStateService()
        service.record_log("line-1", level="ERROR", source="Downloader", trace_id="trace-a")
        service.record_log("line-2", level="ERROR", source="Downloader", trace_id="trace-a")

        index = service._log_excerpt_index()

        self.assertEqual([entry["message"] for entry in index["trace-a"]], ["line-1", "line-2"])
        self.assertEqual(index["trace-a"][0]["icon_file"], "log_level_error.png")
        self.assertEqual(service._log_excerpt("trace-a"), ["line-1", "line-2"])

    def test_get_delta_returns_versioned_dirty_sections(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("video_state_changed", {"video_id": "v1", "progress": 10})
        delta = service.get_delta(base_version)

        self.assertGreater(delta["version"], base_version)
        self.assertFalse(delta["full"])
        self.assertIn("active_downloads", delta["changed_sections"])
        self.assertIn("app_status", delta["sections"])

    def test_get_delta_keeps_regular_progress_narrow(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.update", {"video_id": "v1", "progress": 42})
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"active_downloads", "app_status"})

    def test_get_delta_promotes_terminal_progress_to_video_sections(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.update", {"video_id": "v1", "progress": 100})
        delta = service.get_delta(base_version)

        for section in ("queue_items", "active_downloads", "completed_items", "failed_items", "app_status"):
            self.assertIn(section, delta["changed_sections"])

    def test_get_delta_routes_metadata_event_to_completed_items(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_event("videos.metadata", {"video_id": "v1", "metadata": True})
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"completed_items", "app_status"})

    def test_log_append_delta_stays_narrow(self):
        service = FrontendStateService()
        base_version = service.frontend_version

        service.record_log("解析完成", source="bilibili", trace_id="trace-log")
        delta = service.get_delta(base_version)

        self.assertEqual(set(delta["changed_sections"]), {"log_items", "app_status"})
        self.assertIn("log_items", delta["sections"])
        self.assertNotIn("queue_items", delta["sections"])

    def test_get_delta_reports_deleted_ids(self):
        service = FrontendStateService()
        service.record_event("video_removed", {"video_id": "v1"})

        delta = service.get_delta(0)

        self.assertFalse(delta["full"])
        self.assertIn("v1", delta["deleted_ids"])

if __name__ == "__main__":
    unittest.main()
