import os
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.config import cfg
from app.models import VideoItem
from app.services.update_check_service import (
    UPDATE_STATUS_AVAILABLE,
    PreparedUpdate,
    UpdateCandidate,
    UpdateCheckResult,
)
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

    def test_config_update_rejects_unapproved_save_directory(self):
        original_config_dir = cfg.get("common", "save_directory", "")
        original_runtime_dir = self.context.controller.current_save_dir
        try:
            with tempfile.TemporaryDirectory() as outside_root:
                response = self.client.put(
                    "/api/config",
                    json={"common": {"save_directory": outside_root}},
                )

                self.assertEqual(response.json().get("status"), "error")
                self.assertIn("授权", response.json().get("error", ""))
                self.assertEqual(self.context.controller.current_save_dir, original_runtime_dir)
                self.assertEqual(cfg.get("common", "save_directory", ""), original_config_dir)
        finally:
            cfg.set("common", "save_directory", original_config_dir)
            self.context.controller.current_save_dir = original_runtime_dir

    def test_rest_frontend_action_rejects_unapproved_save_directory(self):
        original_config_dir = cfg.get("common", "save_directory", "")
        original_runtime_dir = self.context.controller.current_save_dir
        try:
            with tempfile.TemporaryDirectory() as outside_root:
                response = self.client.post(
                    "/api/frontend/action",
                    json={
                        "action": "update_basic_setting",
                        "payload": {"key": "download_directory", "value": outside_root},
                        "frontend_version": 0,
                    },
                )

                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json().get("status"), "error")
                self.assertIn("授权", response.json().get("message", ""))
                self.assertEqual(self.context.controller.current_save_dir, original_runtime_dir)
                self.assertEqual(cfg.get("common", "save_directory", ""), original_config_dir)
        finally:
            cfg.set("common", "save_directory", original_config_dir)
            self.context.controller.current_save_dir = original_runtime_dir

    def test_rest_frontend_action_rejects_hidden_platform_setting(self):
        original_user_agent = cfg.get("douyin", "user_agent", "")
        try:
            response = self.client.post(
                "/api/frontend/action",
                json={
                    "action": "update_setting",
                    "payload": {"section": "douyin", "key": "user_agent", "value": "unsafe"},
                    "frontend_version": 0,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json().get("status"), "error")
            self.assertEqual(response.json().get("data", {}).get("code"), "config_not_allowed")
            self.assertEqual(cfg.get("douyin", "user_agent", ""), original_user_agent)
        finally:
            cfg.set("douyin", "user_agent", original_user_agent)

    def test_rest_config_update_rejects_string_for_boolean_setting(self):
        original_value = cfg.get("download", "video_only", False)
        try:
            response = self.client.put(
                "/api/config",
                json={"download": {"video_only": "false"}},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json().get("status"), "error")
            self.assertIn("布尔", response.json().get("error", ""))
            self.assertEqual(cfg.get("download", "video_only", False), original_value)
        finally:
            cfg.set("download", "video_only", original_value)

    def test_rest_frontend_action_rejects_string_for_boolean_setting(self):
        original_value = cfg.get("download", "video_only", False)
        try:
            response = self.client.post(
                "/api/frontend/action",
                json={
                    "action": "update_setting",
                    "payload": {"section": "download", "key": "video_only", "value": "false"},
                    "frontend_version": 0,
                    "request_id": "bool-rest-1",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json().get("status"), "error")
            self.assertEqual(response.json().get("data", {}).get("code"), "invalid_config_value")
            self.assertEqual(response.json().get("request_id"), "bool-rest-1")
            self.assertEqual(cfg.get("download", "video_only", False), original_value)
        finally:
            cfg.set("download", "video_only", original_value)

    def test_download_options_action_rejects_fields_outside_its_runtime_contract(self):
        original_value = cfg.get("download", "resume_enabled", True)
        try:
            response = self.client.post(
                "/api/frontend/action",
                json={
                    "action": "update_download_options",
                    "payload": {"resume_enabled": False},
                    "frontend_version": 0,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json().get("data", {}).get("code"), "config_not_allowed")
            self.assertEqual(cfg.get("download", "resume_enabled", True), original_value)
        finally:
            cfg.set("download", "resume_enabled", original_value)

    def test_rest_frontend_action_echoes_request_id(self):
        response = self.client.post(
            "/api/frontend/action",
            json={
                "action": "refresh_platform_auth_status",
                "payload": {"force": False},
                "frontend_version": 0,
                "request_id": "rest-action-7",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")
        self.assertEqual(response.json().get("request_id"), "rest-action-7")

    def test_rest_sync_frontend_action_runs_off_event_loop_and_receives_roots(self):
        observed = {}

        def handle_frontend_action(action, payload, approved_roots=None):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                observed["on_event_loop"] = False
            else:
                observed["on_event_loop"] = True
            observed["approved_roots"] = approved_roots
            return {"status": "ok", "action": action, "payload": payload}

        with patch.object(self.context.controller, "async_handle_frontend_action", None), patch.object(
            self.context.controller,
            "handle_frontend_action",
            handle_frontend_action,
        ):
            response = self.client.post(
                "/api/frontend/action",
                json={
                    "action": "refresh_platform_auth_status",
                    "payload": {"force": False},
                    "frontend_version": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(observed["on_event_loop"])
        self.assertEqual(observed["approved_roots"], self.context.approved_roots_snapshot())

    def test_update_check_uses_secure_service_off_request_thread(self):
        from cli import __version__

        request_thread = threading.get_ident()
        worker_threads = []
        result = UpdateCheckResult(
            status=UPDATE_STATUS_AVAILABLE,
            local_version="3.6.17",
            latest_version="3.6.18",
            tag_name="v3.6.18",
            release_name="v3.6.18",
            html_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
            notes="verified release",
            manifest_path="C:/private/update/latest.json",
            signature_path="C:/private/update/latest.json.sig",
            candidates=(
                UpdateCandidate(
                    version="3.6.18",
                    tag_name="v3.6.18",
                    release_name="v3.6.18",
                    html_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
                    manifest_path="C:/private/update/latest.json",
                    signature_path="C:/private/update/latest.json.sig",
                ),
            ),
        )

        def secure_check(local_version):
            worker_threads.append(threading.get_ident())
            self.assertEqual(local_version, __version__)
            return result

        with patch("app.services.update_check_service.check_secure_update", side_effect=secure_check):
            response = self.client.post("/api/update/check", json={"local_version": "v0.0.1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], UPDATE_STATUS_AVAILABLE)
        self.assertEqual(payload["latest_version"], "3.6.18")
        self.assertEqual(payload["candidates"][0]["version"], "3.6.18")
        self.assertNotIn("manifest_path", payload)
        self.assertNotIn("signature_path", payload)
        self.assertNotIn("manifest_path", payload["candidates"][0])
        self.assertNotIn("signature_path", payload["candidates"][0])
        self.assertTrue(worker_threads)
        self.assertNotEqual(worker_threads[0], request_thread)

    def test_update_prepare_is_local_only_and_uses_verified_service(self):
        from cli import __version__

        result = UpdateCheckResult(
            status=UPDATE_STATUS_AVAILABLE,
            local_version="3.6.17",
            latest_version="3.6.18",
            tag_name="v3.6.18",
            release_name="v3.6.18",
            html_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
            candidates=(
                UpdateCandidate(
                    version="3.6.18",
                    tag_name="v3.6.18",
                    release_name="v3.6.18",
                    html_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
                ),
            ),
        )
        selected = result.for_version("3.6.18")
        prepared = PreparedUpdate(
            installer_path=os.fspath(Path(tempfile.gettempdir(), "ucrawl-update.exe")),
            manifest_path=os.fspath(Path(tempfile.gettempdir(), "latest.json")),
            signature_path=os.fspath(Path(tempfile.gettempdir(), "latest.json.sig")),
            version="3.6.18",
            log_path=os.fspath(Path(tempfile.gettempdir(), "updater-install.log")),
        )
        with (
            patch("app.services.update_check_service.check_secure_update", return_value=result) as check,
            patch("app.services.update_check_service.prepare_verified_update", return_value=prepared) as prepare,
        ):
            response = self.client.post(
                "/api/update/prepare",
                json={"local_version": "v3.6.17", "selected_version": "3.6.18"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["version"], "3.6.18")
        self.assertEqual(response.json()["installer_name"], "ucrawl-update.exe")
        check.assert_called_once_with(__version__)
        prepare.assert_called_once_with(selected)

        remote_client = TestClient(
            create_app(),
            base_url="http://localhost",
            client=("192.0.2.10", 41004),
        )
        remote_client.get("/")
        remote_response = remote_client.post(
            "/api/update/prepare",
            json={"local_version": "v3.6.17", "selected_version": "3.6.18"},
        )
        self.assertEqual(remote_response.status_code, 403)

    def test_update_prepare_rejects_unverified_result_and_clears_stale_package(self):
        result = UpdateCheckResult(
            status="untrusted",
            local_version="3.6.17",
            latest_version="3.6.18",
            tag_name="v3.6.18",
            release_name="v3.6.18",
            html_url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",
        )
        self.context.store_prepared_update(object())

        with (
            patch("app.services.update_check_service.check_secure_update", return_value=result),
            patch("app.services.update_check_service.prepare_verified_update") as prepare,
        ):
            response = self.client.post(
                "/api/update/prepare",
                json={"local_version": "v0.0.1", "selected_version": "3.6.18"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIsNone(self.context.prepared_update_snapshot())
        prepare.assert_not_called()

    def test_prepared_update_take_is_atomic(self):
        prepared = object()
        self.context.store_prepared_update(prepared)

        self.assertIs(self.context.take_prepared_update(), prepared)
        self.assertIsNone(self.context.take_prepared_update())
        self.assertIsNone(self.context.prepared_update_snapshot())

    def test_update_install_consumes_session_verified_package_and_requests_shutdown(self):
        prepared = PreparedUpdate(
            installer_path=os.fspath(Path(tempfile.gettempdir(), "ucrawl-update.exe")),
            manifest_path=os.fspath(Path(tempfile.gettempdir(), "latest.json")),
            signature_path=os.fspath(Path(tempfile.gettempdir(), "latest.json.sig")),
            version="3.6.18",
            log_path=os.fspath(Path(tempfile.gettempdir(), "updater-install.log")),
        )
        self.context.store_prepared_update(prepared)
        shutdown = Mock()
        self.client.app.state.web_shutdown_callback = shutdown
        self.client.app.state.web_restart_argv = ["CrawlerWebPortal.exe", "--port", "8000"]

        with patch("app.services.update_check_service.launch_prepared_update") as launch:
            response = self.client.post("/api/update/install", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "installing")
        launch.assert_called_once_with(
            prepared,
            restart_argv=["CrawlerWebPortal.exe", "--port", "8000"],
        )
        self.assertIsNone(self.context.prepared_update_snapshot())
        shutdown.assert_called_once_with()

    def test_update_install_restores_verified_package_when_helper_launch_fails(self):
        prepared = PreparedUpdate(
            installer_path=os.fspath(Path(tempfile.gettempdir(), "ucrawl-update.exe")),
            manifest_path=os.fspath(Path(tempfile.gettempdir(), "latest.json")),
            signature_path=os.fspath(Path(tempfile.gettempdir(), "latest.json.sig")),
            version="3.6.18",
            log_path=os.fspath(Path(tempfile.gettempdir(), "updater-install.log")),
        )
        self.context.store_prepared_update(prepared)
        shutdown = Mock()
        self.client.app.state.web_shutdown_callback = shutdown
        self.client.app.state.web_restart_argv = ["CrawlerWebPortal.exe", "--port", "8000"]

        with patch(
            "app.services.update_check_service.launch_prepared_update",
            side_effect=RuntimeError("helper launch failed"),
        ):
            response = self.client.post("/api/update/install", json={})

        self.assertEqual(response.status_code, 500)
        self.assertIs(self.context.prepared_update_snapshot(), prepared)
        shutdown.assert_not_called()

    def test_delete_endpoint_surfaces_unapproved_media_path(self):
        with tempfile.TemporaryDirectory() as outside_root:
            item = VideoItem(url="", title="outside", source="local")
            item.local_path = os.fspath(Path(outside_root, "outside.mp4"))
            self.context.controller._store_video_item(item)
            self.context.controller.file_service.delete_media = Mock(return_value=True)

            response = self.client.delete(f"/api/video/{item.id}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("status"), "error")
        self.assertIn("授权", response.json().get("message", ""))
        self.assertIs(self.context.controller._video_lookup(item.id), item)
        self.context.controller.file_service.delete_media.assert_not_called()

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
