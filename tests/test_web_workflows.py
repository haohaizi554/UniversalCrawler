import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.video_item import VideoItem

class _FakeController:
    def __init__(self):
        self.current_spider = None
        self.current_save_dir = "downloads"
        self._pending_selection_strategy = None
        self.videos = {}
        self.start_crawl = MagicMock()
        self.resume_spider_selection = MagicMock()

    def _video_item_to_dict(self, item):
        return {
            "id": item.id,
            "title": item.title,
            "status": item.status,
            "progress": item.progress,
            "local_path": item.local_path,
            "meta": item.meta,
        }

class WebWorkflowHelpersTests(unittest.TestCase):
    def test_build_selection_strategy_supports_preload(self):
        from app.web.workflows import build_selection_strategy

        strategy = build_selection_strategy({"strategy": "preload", "choices": [[0], [1, 2]]})

        self.assertEqual(type(strategy).__name__, "PipeSelection")
        self.assertEqual(strategy.select([1, 2, 3]), [0])
        self.assertEqual(strategy.select([1, 2, 3]), [1, 2])

    def test_build_selection_strategy_rejects_invalid_rule_values(self):
        from app.web.workflows import build_selection_strategy

        self.assertIsNone(build_selection_strategy({"strategy": "rule", "select": [1, 2]}))
        self.assertIsNone(build_selection_strategy({"strategy": "preload", "choices": [0, 1]}))

    def test_merge_default_config_normalizes_missav_proxy(self):
        from app.web.workflows import merge_default_config

        with (
            patch("cli.defaults.get_platform_defaults", return_value={"proxy": "Clash (7890)", "timeout": 10}),
            patch("cli.defaults.build_missav_proxy_url", return_value="http://127.0.0.1:7890"),
        ):
            merged = merge_default_config("missav", {"timeout": 20})

        self.assertEqual(merged["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(merged["timeout"], 20)

class WebWorkflowServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.web.workflows import WebWorkflowService

        self.events = []

        async def _broadcast(event_type, data):
            self.events.append((event_type, data))

        self.controller = _FakeController()
        self.service = WebWorkflowService(self.controller, _broadcast)

    async def test_start_crawl_rejects_invalid_selection_payload(self):
        result = await self.service.start_crawl(
            {
                "source": "douyin",
                "keyword": "test",
                "selection": {"strategy": "rule", "select": [1]},
            },
            log_error=True,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("无效选择策略", result["error"])
        self.assertEqual(self.events[-1], ("crawl_state", {"is_running": False}))
        self.controller.start_crawl.assert_not_called()

    async def test_start_crawl_merges_config_and_updates_save_dir(self):
        with (
            patch("app.core.plugin_registry.registry.get_plugin", return_value=object()),
            patch("app.web.workflows.validate_config_types", return_value=None),
            patch("app.web.workflows.merge_default_config", return_value={"max_items": 20}),
            patch("cli.defaults.merge_convenience_params") as merge_params,
        ):
            result = await self.service.start_crawl(
                {
                    "source": "douyin",
                    "keyword": "hello",
                    "config": {"max_items": 10},
                    "selection": {"strategy": "first"},
                    "save_dir": "new_dir",
                },
                log_error=False,
            )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(self.controller.current_save_dir, "new_dir")
        self.controller.start_crawl.assert_called_once_with("douyin", "hello", {"max_items": 20})
        merge_params.assert_called_once()
        self.assertEqual(type(self.controller._pending_selection_strategy).__name__, "RuleSelection")

    async def test_start_crawl_rejects_when_spider_running(self):
        self.controller.current_spider = SimpleNamespace(isRunning=lambda: True)

        result = await self.service.start_crawl(
            {"source": "douyin", "keyword": "busy"},
            log_error=True,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("当前已有任务在运行", result["error"])
        self.assertNotIn(("crawl_state", {"is_running": False}), self.events)

    async def test_select_tasks_normalizes_indices(self):
        self.controller.current_spider = SimpleNamespace(isRunning=lambda: True)

        result = await self.service.select_tasks({"indices": ["1", 2]}, log_error=False)

        self.assertEqual(result, {"status": "ok"})
        self.controller.resume_spider_selection.assert_called_once_with([1, 2])

    async def test_direct_download_success_broadcasts_finish(self):
        fake_sdk = MagicMock()
        fake_sdk.download_video.return_value = {
            "status": "ok",
            "title": "done.mp4",
            "local_path": "D:/downloads/done.mp4",
            "content_type": "video",
            "meta": {"origin": "sdk"},
        }
        fake_sdk.close = MagicMock()

        with (
            patch("app.core.plugin_registry.registry.get_plugin", return_value=object()),
            patch("app.core.plugin_registry.registry.get_all_plugins", return_value=[SimpleNamespace(id="douyin")]),
            patch("app.web.workflows.validate_config_types", return_value=None),
            patch("cli.defaults.get_platform_defaults", return_value={}),
            patch("cli.defaults.merge_convenience_params"),
            patch("cli.sdk.UcrawlSDK", return_value=fake_sdk),
        ):
            result = await self.service.direct_download(
                {
                    "url": "https://example.com/video",
                    "source": "douyin",
                    "title": "demo",
                },
                log_error=False,
            )

        self.assertEqual(result["status"], "ok")
        self.assertIn("video_id", result)
        event_names = [name for name, _ in self.events]
        self.assertIn("item_found", event_names)
        self.assertIn("task_started", event_names)
        self.assertIn("task_finished", event_names)
        self.assertIn("video_state_changed", event_names)
        fake_sdk.close.assert_called_once()

    async def test_workflow_progress_gate_throttles_bursts_but_keeps_terminal_progress(self):
        with patch("app.web.workflows.time.monotonic", side_effect=[100.00, 100.05, 100.06]):
            self.assertTrue(self.service._should_emit_progress("video-1", 10))
            self.assertFalse(self.service._should_emit_progress("video-1", 11))
            self.assertTrue(self.service._should_emit_progress("video-1", 100))

    async def test_workflow_progress_broadcast_coalesces_stale_queued_updates(self):
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        loop = asyncio.get_running_loop()

        with patch("app.web.workflows.time.monotonic", side_effect=[100.00, 100.30]):
            self.service._schedule_progress_broadcast(loop, item.id, item, 10)
            self.service._schedule_progress_broadcast(loop, item.id, item, 20)
        await asyncio.sleep(0.01)

        progress_events = [
            data["progress"]
            for event_type, data in self.events
            if event_type == "video_state_changed"
        ]
        self.assertEqual(progress_events, [20])

    async def test_download_success_cancels_stale_progress_before_terminal_update(self):
        started = asyncio.Event()
        release = asyncio.Event()
        events = []

        async def _broadcast(event_type, data):
            if event_type == "video_state_changed" and data.get("progress") == 55:
                started.set()
                await release.wait()
            events.append((event_type, data))

        from app.web.workflows import WebWorkflowService

        service = WebWorkflowService(self.controller, _broadcast)
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        loop = asyncio.get_running_loop()

        with patch("app.web.workflows.time.monotonic", return_value=100.00):
            service._schedule_progress_broadcast(loop, item.id, item, 55)
        await asyncio.wait_for(started.wait(), timeout=1)

        await service._broadcast_download_success(
            item,
            {
                "status": "ok",
                "title": "done.mp4",
                "local_path": "D:/downloads/done.mp4",
                "content_type": "video",
            },
        )
        release.set()
        await asyncio.sleep(0.01)

        progress_events = [
            data["progress"]
            for event_type, data in events
            if event_type == "video_state_changed"
        ]
        self.assertEqual(progress_events, [100])
        self.assertNotIn(item.id, service._pending_progress_tasks)
        self.assertNotIn(item.id, service._last_progress_emit)

    async def test_direct_download_sdk_exception_returns_error_payload(self):
        fake_sdk = MagicMock()
        fake_sdk.download_video.side_effect = RuntimeError("boom")
        fake_sdk.close = MagicMock()

        with (
            patch("app.core.plugin_registry.registry.get_plugin", return_value=object()),
            patch("app.core.plugin_registry.registry.get_all_plugins", return_value=[SimpleNamespace(id="douyin")]),
            patch("app.web.workflows.validate_config_types", return_value=None),
            patch("cli.defaults.get_platform_defaults", return_value={}),
            patch("cli.defaults.merge_convenience_params"),
            patch("cli.sdk.UcrawlSDK", return_value=fake_sdk),
        ):
            result = await self.service.direct_download(
                {
                    "url": "https://example.com/video",
                    "source": "douyin",
                },
                log_error=True,
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("下载失败", result["error"])
        event_names = [name for name, _ in self.events]
        self.assertIn("task_error", event_names)
        self.assertIn("log", event_names)
        fake_sdk.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
