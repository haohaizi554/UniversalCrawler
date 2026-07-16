from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.web.ws_bootstrap import WebSocketBootstrapper


class _FakeBridge:
    def __init__(self) -> None:
        self.marked_versions: list[int] = []

    def mark_frontend_version_sent(self, version: int) -> None:
        self.marked_versions.append(version)


class _FakeController:
    def __init__(self) -> None:
        self.bridge = _FakeBridge()
        self.worker_threads: list[int] = []
        self.videos = {
            "video-1": SimpleNamespace(id="video-1", title="cached"),
        }

    def _record_thread(self) -> None:
        self.worker_threads.append(threading.get_ident())

    def get_state(self) -> dict:
        self._record_thread()
        return {"is_crawling": False}

    def get_frontend_state(self) -> dict:
        self._record_thread()
        return {"version": 12, "completed_items": []}

    def get_platforms(self) -> list[dict]:
        self._record_thread()
        return [{"id": "bilibili"}]

    def get_config(self) -> dict:
        self._record_thread()
        return {"common": {"theme": "light"}}

    def _video_items_snapshot(self) -> dict:
        self._record_thread()
        return dict(self.videos)

    def _video_item_to_dict(self, item: SimpleNamespace) -> dict:
        self._record_thread()
        return {"id": item.id, "title": item.title}


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class WebSocketBootstrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_snapshot_getters_and_encoding_run_off_event_loop_thread(self) -> None:
        main_thread = threading.get_ident()
        controller = _FakeController()
        ws = _FakeWebSocket()
        encode_threads: list[int] = []

        def encode_message(event_type: str, data: object) -> str:
            encode_threads.append(threading.get_ident())
            return json.dumps({"type": event_type, "data": data}, ensure_ascii=False)

        with patch("app.web.ws_bootstrap._encode_message", side_effect=encode_message):
            await WebSocketBootstrapper()._send_initial_snapshot(ws, SimpleNamespace(controller=controller))

        sent_types = [json.loads(text)["type"] for text in ws.sent]

        self.assertEqual(sent_types, ["init_state", "frontend_state", "platforms", "config", "item_found"])
        self.assertEqual(controller.bridge.marked_versions, [12])
        self.assertTrue(controller.worker_threads)
        self.assertTrue(encode_threads)
        self.assertTrue(all(thread_id != main_thread for thread_id in controller.worker_threads))
        self.assertTrue(all(thread_id != main_thread for thread_id in encode_threads))


if __name__ == "__main__":
    unittest.main()
