import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from app.models import VideoItem
from app.services.frontend_state_service import FrontendStateService, QUEUE_STATUSES

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
        self.assertTrue(any("1.4 MB/s" in message for message in messages))
        self.assertTrue(any("Trace ID" in message for message in messages))

    def test_log_items_use_trace_id_without_task_id_column(self):
        service = FrontendStateService()
        service.record_log("download failed", level="ERROR", source="Downloader", trace_id="trace-1")

        item = service.get_snapshot()["log_items"][-1]

        self.assertIn("trace_id", item)
        self.assertNotIn("task_id", item)
        self.assertEqual(item["trace_id"], "trace-1")

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
        manager.set_max_concurrent.assert_called_once_with(5)
        cache.set.assert_called_once_with("download.auto_retry", True, persist=False)

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

        self.assertEqual(index["trace-a"], ["line-1", "line-2"])
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

    def test_get_delta_reports_deleted_ids(self):
        service = FrontendStateService()
        service.record_event("video_removed", {"video_id": "v1"})

        delta = service.get_delta(0)

        self.assertFalse(delta["full"])
        self.assertIn("v1", delta["deleted_ids"])

if __name__ == "__main__":
    unittest.main()
