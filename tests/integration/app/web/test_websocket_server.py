import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

class _FakeBridge:
    def __init__(self):
        self.loop = None

    def set_loop(self, loop):
        self.loop = loop

class _FakeController:
    instances = []

    def __init__(self, _loop, _broadcast):
        self.bridge = _FakeBridge()
        self.current_save_dir = "downloads"
        self.tool_profile_providers = []
        self.frontend_state_service = SimpleNamespace(
            set_tool_execution_profile_provider=self.tool_profile_providers.append,
        )
        self.videos = {}
        self.file_service = SimpleNamespace(scan_directory=lambda *_args, **_kwargs: None)
        self.async_scan_local_dir = AsyncMock()
        self.async_change_dir = AsyncMock()
        self.async_delete_video = AsyncMock()
        self.async_rename_video = AsyncMock()
        self.stop_crawl_called = False
        type(self).instances.append(self)

    def get_state(self):
        return {"current_save_dir": self.current_save_dir, "is_crawling": False, "video_count": 0}

    def get_platforms(self):
        return [{"id": "douyin", "name": "抖音"}]

    def get_config(self):
        return {"common": {"theme": "dark"}}

    def stop_crawl(self):
        self.stop_crawl_called = True

class _FakeWorkflowService:
    instances = []

    def __init__(self, controller, broadcast, *, execution_profile_factory=None):
        self.controller = controller
        self.broadcast = broadcast
        self.execution_profile_factory = execution_profile_factory
        self.start_crawl_completed = threading.Event()

        async def _start_crawl(*_args, **_kwargs):
            self.start_crawl_completed.set()

        self.start_crawl = AsyncMock(side_effect=_start_crawl)
        self.select_tasks = AsyncMock()
        self.direct_download = AsyncMock()
        type(self).instances.append(self)

class WebsocketServerTests(unittest.TestCase):
    def _create_client(self):
        from fastapi.testclient import TestClient
        from app.web.server import create_app

        _FakeController.instances.clear()
        _FakeWorkflowService.instances.clear()

        with (
            patch("app.web.controller.WebController", _FakeController),
            patch("app.web.workflows.WebWorkflowService", _FakeWorkflowService),
            patch("app.web.server.asyncio.create_task", lambda coro: coro.close()),
        ):
            client = TestClient(create_app())
        # WebSocket 与 HTTP 共用同一会话令牌。先走公开 ping，让中间件
        # 建立 session cookie；测试不得依赖 localhost 鉴权旁路。
        # The public ping endpoint is intentionally stateless. Bootstrap the
        # same HTTP session that a browser creates before opening /ws.
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        return client

    def test_websocket_sends_init_state_platforms_and_config(self):
        client = self._create_client()

        with client.websocket_connect("/ws") as ws:
            first = json.loads(ws.receive_text())
            second = json.loads(ws.receive_text())
            third = json.loads(ws.receive_text())

        self.assertEqual(first["type"], "init_state")
        self.assertEqual(second["type"], "platforms")
        self.assertEqual(third["type"], "config")
        workflow = _FakeWorkflowService.instances[-1]
        self.assertTrue(callable(workflow.execution_profile_factory))
        profile = workflow.execution_profile_factory()
        matching_context = next(
            context
            for context in client.app.state.web_session_registry._contexts.values()
            if context.controller is workflow.controller
        )
        self.assertEqual(profile.host_surface, "public_web")
        self.assertEqual(profile.owner_id, f"web:{matching_context.session_id}")
        self.assertFalse(profile.allow_tool_execution)
        self.assertIn(
            Path(matching_context.controller.current_save_dir).resolve(),
            profile.approved_roots,
        )
        self.assertEqual(len(workflow.controller.tool_profile_providers), 1)
        frontend_profile = workflow.controller.tool_profile_providers[0]()
        self.assertEqual(frontend_profile.owner_id, profile.owner_id)
        self.assertEqual(frontend_profile.approved_roots, frozenset())

    def test_websocket_start_crawl_dispatches_to_workflow(self):
        client = self._create_client()

        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.receive_text()
            workflow = _FakeWorkflowService.instances[-1]
            ws.send_text(json.dumps({"type": "start_crawl", "data": {"source": "douyin", "keyword": "demo"}}))
            self.assertTrue(
                workflow.start_crawl_completed.wait(timeout=1.0),
                "WebSocket start_crawl was not dispatched before the bounded deadline",
            )

        workflow.start_crawl.assert_awaited_once_with({"source": "douyin", "keyword": "demo"}, log_error=True)

    def test_websocket_invalid_change_theme_broadcasts_log(self):
        client = self._create_client()

        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.receive_text()
            ws.receive_text()
            ws.send_text(json.dumps({"type": "change_theme", "data": {"dark_theme": "yes"}}))
            message = json.loads(ws.receive_text())

        self.assertEqual(message["type"], "log")
        self.assertIn("dark_theme 必须是布尔值", message["data"]["message"])

if __name__ == "__main__":
    unittest.main()
