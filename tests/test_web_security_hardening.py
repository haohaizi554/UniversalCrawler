import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        pending = list(self.client.app.routes)
        registered_routes = []
        while pending:
            route = pending.pop()
            included_router = getattr(route, "original_router", None)
            if included_router is not None:
                pending.extend(included_router.routes)
                continue
            registered_routes.append(route)

        route_endpoints = {
            route.path: route.endpoint.__module__
            for route in registered_routes
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

    def test_remote_session_cannot_open_native_folder_picker_on_server_desktop(self):
        remote_client = TestClient(
            create_app(),
            base_url="http://localhost",
            client=("192.0.2.10", 41000),
        )
        # The static page currently establishes the CSRF/session cookies used by
        # remote API calls, so this reproduces an authenticated browser session.
        remote_client.get("/")

        with patch(
            "app.web.directory_service.WebDirectoryService._powershell_pick_dir",
            return_value=None,
        ) as picker:
            response = remote_client.post("/api/dir/pick-native")

        self.assertEqual(response.status_code, 403)
        picker.assert_not_called()

    def test_remote_deployment_cannot_open_native_picker_through_loopback_proxy(self):
        access_token = "test-access-token-with-enough-entropy"
        client = TestClient(create_app(access_token=access_token), client=("127.0.0.1", 41002))
        client.get(f"/?access_token={access_token}")

        with patch(
            "app.web.directory_service.WebDirectoryService._powershell_pick_dir",
            return_value=None,
        ) as picker:
            response = client.post("/api/dir/pick-native")

        self.assertEqual(response.status_code, 403)
        picker.assert_not_called()

    def test_configured_remote_access_token_gates_http_and_strips_bootstrap_query(self):
        access_token = "test-access-token-with-enough-entropy"
        remote_client = TestClient(
            create_app(access_token=access_token),
            base_url="https://ucrawl.test",
            client=("192.0.2.10", 41001),
            follow_redirects=False,
        )

        contexts_before_ping = len(remote_client.app.state.web_session_registry._contexts)
        self.assertEqual(remote_client.get("/healthz").status_code, 200)
        self.assertEqual(
            len(remote_client.app.state.web_session_registry._contexts),
            contexts_before_ping,
        )
        self.assertEqual(remote_client.get("/api/ping").status_code, 200)
        self.assertEqual(remote_client.get("/").status_code, 401)
        self.assertEqual(remote_client.get("/?access_token=wrong").status_code, 401)

        bootstrap = remote_client.get(f"/?access_token={access_token}")
        self.assertEqual(bootstrap.status_code, 303)
        self.assertEqual(bootstrap.headers.get("location"), "/")
        self.assertNotIn(access_token, bootstrap.headers.get("location", ""))

        self.assertEqual(remote_client.get("/").status_code, 200)
        self.assertEqual(remote_client.get("/api/frontend/state").status_code, 200)

    def test_passwordless_local_mode_rejects_dns_rebinding_host(self):
        client = TestClient(
            create_app(),
            base_url="http://rebind.attacker.test",
            client=("127.0.0.1", 41003),
        )
        contexts_before = len(client.app.state.web_session_registry._contexts)

        response = client.get("/api/ping")

        self.assertEqual(response.status_code, 421)
        self.assertEqual(len(client.app.state.web_session_registry._contexts), contexts_before)
        self.assertNotIn("ucrawl_session", response.cookies)

        spoofed_test_host = TestClient(
            create_app(),
            base_url="http://testserver",
            client=("127.0.0.1", 41004),
        )
        self.assertEqual(spoofed_test_host.get("/").status_code, 421)


if __name__ == "__main__":
    unittest.main()
