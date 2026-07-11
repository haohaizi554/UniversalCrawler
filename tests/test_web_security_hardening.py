import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.models import VideoItem
from app.web.server import create_app


class WebSecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.get("/api/ping")
        cookie_name = self.client.app.state.web_session_cookie_name
        session_id = self.client.cookies.get(cookie_name)
        self.context = self.client.app.state.web_session_registry.get_or_create(session_id)

    def test_production_app_uses_composed_rest_and_websocket_routers(self):
        route_endpoints = {
            route.path: route.endpoint.__module__
            for route in self.client.app.routes
            if hasattr(route, "endpoint") and route.path in {"/api/scan", "/ws"}
        }

        self.assertEqual(route_endpoints["/api/scan"], "app.web.rest_router")
        self.assertEqual(route_endpoints["/ws"], "app.web.ws_router")

    def test_directory_listing_rejects_unapproved_root(self):
        with tempfile.TemporaryDirectory() as outside_root:
            response = self.client.get("/api/dir/list", params={"path": outside_root})

        self.assertEqual(response.status_code, 403)

    def test_media_endpoint_requires_session_token_even_for_loopback(self):
        csrf_cookie = self.client.app.state.web_csrf_cookie_name
        self.client.cookies.delete(csrf_cookie)

        response = self.client.get("/api/media/nonexistent_id")

        self.assertEqual(response.status_code, 403)

    def test_delete_and_rename_reject_invalid_video_ids(self):
        delete_response = self.client.delete("/api/video/bad.id")
        rename_response = self.client.post(
            "/api/video/rename",
            json={"video_id": "bad.id", "new_title": "renamed"},
        )

        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(rename_response.status_code, 400)

    def test_unsatisfiable_media_range_returns_416(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir, "sample.mp4")
            media_path.write_bytes(b"0123456789")
            self.context.approve_directory(temp_dir)
            item = VideoItem(url="", title="sample", source="local")
            item.id = "range_sample"
            item.local_path = os.fspath(media_path)
            self.context.controller._store_video_item(item)

            response = self.client.get(
                f"/api/media/{item.id}",
                headers={"Range": "bytes=20-30"},
            )

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers.get("Content-Range"), "bytes */10")

    def test_media_suffix_range_returns_file_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir, "sample.mp4")
            media_path.write_bytes(b"0123456789")
            self.context.approve_directory(temp_dir)
            item = VideoItem(url="", title="sample", source="local")
            item.id = "suffix_range_sample"
            item.local_path = os.fspath(media_path)
            self.context.controller._store_video_item(item)

            response = self.client.get(
                f"/api/media/{item.id}",
                headers={"Range": "bytes=-4"},
            )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"6789")
        self.assertEqual(response.headers.get("Content-Range"), "bytes 6-9/10")


if __name__ == "__main__":
    unittest.main()
