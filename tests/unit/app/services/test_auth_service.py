"""认证服务的凭据读取、校验与持久化测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.exceptions import CookieLoadError, CookieSaveError
from app.services.auth_service import AuthService

class AuthServiceTests(unittest.TestCase):
    
    def setUp(self):
        
        self.service = AuthService()

    def test_extract_cookie_list_reads_storage_state_shape(self):
        """验证 `test_extract_cookie_list_reads_storage_state_shape` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        cookies = self.service.extract_cookie_list(
            {"cookies": [{"name": "sessionid_ss", "value": "abc"}]}
        )

        self.assertEqual(cookies, [{"name": "sessionid_ss", "value": "abc"}])

    def test_extract_cookie_dict_supports_list_payload(self):
        """验证 `test_extract_cookie_dict_supports_list_payload` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        cookie_dict = self.service.extract_cookie_dict(
            [{"name": "SESSDATA", "value": "xyz"}]
        )

        self.assertEqual(cookie_dict, {"SESSDATA": "xyz"})

    def test_extract_cookie_dict_for_url_filters_wrong_domain_and_expired_cookie(self):
        payload = {
            "cookies": [
                {
                    "name": "userId",
                    "value": "identity-only",
                    "domain": "id.kuaishou.com",
                    "path": "/",
                    "expires": 2000,
                },
                {
                    "name": "userId",
                    "value": "expired-main-site",
                    "domain": ".kuaishou.com",
                    "path": "/",
                    "expires": 900,
                },
                {
                    "name": "did",
                    "value": "device",
                    "domain": ".kuaishou.com",
                    "path": "/",
                    "expires": 2000,
                },
            ]
        }

        cookie_dict = self.service.extract_cookie_dict_for_url(
            payload,
            "https://www.kuaishou.com/",
            now=1000,
        )

        self.assertEqual(cookie_dict, {"did": "device"})

    def test_extract_cookie_dict_for_url_keeps_legacy_cookie_without_scope(self):
        payload = {"cookies": [{"name": "sessionid_ss", "value": "legacy"}]}

        cookie_dict = self.service.extract_cookie_dict_for_url(
            payload,
            "https://www.douyin.com/",
            now=1000,
        )

        self.assertEqual(cookie_dict, {"sessionid_ss": "legacy"})

    def test_extract_cookie_dict_for_url_enforces_browser_path_boundary(self):
        payload = {
            "cookies": [
                {
                    "name": "share_only",
                    "value": "allowed",
                    "domain": ".kuaishou.com",
                    "path": "/f",
                }
            ]
        }

        self.assertEqual(
            self.service.extract_cookie_dict_for_url(
                payload,
                "https://www.kuaishou.com/f/example",
            ),
            {"share_only": "allowed"},
        )
        self.assertEqual(
            self.service.extract_cookie_dict_for_url(
                payload,
                "https://www.kuaishou.com/foobar",
            ),
            {},
        )

    def test_extract_cookie_dict_for_url_can_require_explicit_scope(self):
        payload = {
            "cookies": [
                {"name": "legacy", "value": "unscoped"},
                {
                    "name": "site",
                    "value": "scoped",
                    "domain": ".kuaishou.com",
                    "path": "/",
                },
            ]
        }

        cookie_dict = self.service.extract_cookie_dict_for_url(
            payload,
            "https://www.kuaishou.com/",
            require_scope=True,
        )

        self.assertEqual(cookie_dict, {"site": "scoped"})

    def test_strict_url_cookie_filter_rejects_ambiguous_expiry_and_secure_types(self):
        base = {
            "domain": ".kuaishou.com",
            "path": "/",
        }
        payload = {
            "cookies": [
                {**base, "name": "missing_expiry", "value": "allowed"},
                {
                    **base,
                    "name": "session",
                    "value": "allowed",
                    "expires": -1,
                    "secure": False,
                },
                {
                    **base,
                    "name": "future_secure",
                    "value": "allowed",
                    "expires": 2000,
                    "secure": True,
                },
                {**base, "name": "zero", "value": "blocked", "expires": 0},
                {**base, "name": "negative", "value": "blocked", "expires": -2},
                {**base, "name": "none", "value": "blocked", "expires": None},
                {**base, "name": "empty", "value": "blocked", "expires": ""},
                {
                    **base,
                    "name": "numeric_string",
                    "value": "blocked",
                    "expires": "2000",
                },
                {**base, "name": "false", "value": "blocked", "expires": False},
                {
                    **base,
                    "name": "secure_int",
                    "value": "blocked",
                    "secure": 0,
                },
                {
                    **base,
                    "name": "secure_list",
                    "value": "blocked",
                    "secure": [],
                },
                {
                    **base,
                    "name": "secure_empty",
                    "value": "blocked",
                    "secure": "",
                },
            ]
        }

        cookie_dict = self.service.extract_cookie_dict_for_url(
            payload,
            "https://www.kuaishou.com/",
            now=1000,
            require_scope=True,
        )

        self.assertEqual(
            cookie_dict,
            {
                "missing_expiry": "allowed",
                "session": "allowed",
                "future_secure": "allowed",
            },
        )

    def test_build_cookie_string_requires_target_cookie_when_requested(self):
        """验证 `test_build_cookie_string_requires_target_cookie_when_requested` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        cookie_str = self.service.build_cookie_string(
            [{"name": "sid_guard", "value": "1"}],
            required_cookie="sessionid_ss",
        )

        self.assertEqual(cookie_str, "")

    def test_extract_cookie_dict_skips_values_that_fail_string_conversion(self):
        """验证 `test_extract_cookie_dict_skips_values_that_fail_string_conversion` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        class BrokenValue:
            
            def __str__(self):
                """提供 `__str__` 对应的内部辅助逻辑，供 `BrokenValue` 使用。"""
                raise TypeError("broken")

        cookie_dict = self.service.extract_cookie_dict({"userId": BrokenValue(), "sessionid": "ok"})

        self.assertEqual(cookie_dict, {"sessionid": "ok"})

    def test_restore_playwright_cookies_loads_saved_cookie_list(self):
        """验证 `test_restore_playwright_cookies_loads_saved_cookie_list` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        context = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, {"cookies": [{"name": "userId", "value": "1001"}]})

            restored = self.service.restore_playwright_cookies(context, file_path)

        self.assertTrue(restored)
        context.add_cookies.assert_called_once_with([{"name": "userId", "value": "1001"}])

    def test_load_playwright_storage_state_preserves_origin_local_storage(self):
        payload = {
            "cookies": [{"name": "userId", "value": "1001", "domain": ".kuaishou.com", "path": "/"}],
            "origins": [
                {
                    "origin": "https://www.kuaishou.com",
                    "localStorage": [{"name": "device-id", "value": "device-1"}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, payload)

            restored = self.service.load_playwright_storage_state(file_path)

        self.assertEqual(restored, payload)

    def test_load_playwright_storage_state_upgrades_legacy_cookie_list(self):
        payload = [{"name": "userId", "value": "1001", "domain": ".kuaishou.com", "path": "/"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, payload)

            restored = self.service.load_playwright_storage_state(file_path)

        self.assertEqual(restored, {"cookies": payload, "origins": []})

    @patch("app.services.auth_service.time.sleep", return_value=None)
    def test_wait_for_cookie_and_persist_saves_context_state(self, _mock_sleep):
        """验证 `test_wait_for_cookie_and_persist_saves_context_state` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        context = Mock()
        context.cookies.side_effect = [[], [{"name": "userId", "value": "1001"}]]
        context.storage_state.return_value = {"cookies": [{"name": "userId", "value": "1001"}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            success = self.service.wait_for_cookie_and_persist(
                context=context,
                cookie_name="userId",
                save_path=file_path,
                save_mode="storage_state",
                max_attempts=3,
            )
            payload = self.service.load_json_file(file_path)

        self.assertTrue(success)
        self.assertEqual(payload["cookies"][0]["name"], "userId")

    def test_wait_for_cookie_and_persist_stops_when_stop_check_requests_cancel(self):
        """验证 `test_wait_for_cookie_and_persist_stops_when_stop_check_requests_cancel` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        context = Mock()

        success = self.service.wait_for_cookie_and_persist(
            context=context,
            cookie_name="userId",
            save_path="unused.json",
            stop_check=lambda: True,
            max_attempts=3,
        )

        self.assertFalse(success)
        context.cookies.assert_not_called()

    def test_has_cookie_supports_list_dict_and_none_payloads(self):
        """验证 `test_has_cookie_supports_list_dict_and_none_payloads` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        self.assertTrue(self.service.has_cookie([{"name": "sid_guard", "value": "1"}], "sid_guard"))
        self.assertTrue(self.service.has_cookie({"sid_guard": "1"}, "sid_guard"))
        self.assertFalse(self.service.has_cookie(None, "sid_guard"))

    def test_load_json_file_returns_none_when_file_does_not_exist(self):
        """验证 `test_load_json_file_returns_none_when_file_does_not_exist` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        self.assertIsNone(self.service.load_json_file("missing-auth.json"))

    def test_load_json_file_raises_cookie_load_error_for_invalid_json(self):
        """验证 `test_load_json_file_raises_cookie_load_error_for_invalid_json` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write("{bad json")

            with self.assertRaises(CookieLoadError):
                self.service.load_json_file(file_path)

    def test_save_and_load_json_file_round_trip_keeps_payload(self):
        """验证 `test_save_and_load_json_file_round_trip_keeps_payload` 对应场景是否符合预期，供 `AuthServiceTests` 使用。"""
        payload = {"cookies": [{"name": "SESSDATA", "value": "demo"}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, payload)
            restored = self.service.load_json_file(file_path)

        self.assertEqual(restored, payload)

    def test_save_json_file_preserves_credentials_when_serialization_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "auth.json"
            original = '{"cookies": [{"name": "session", "value": "old"}]}'
            file_path.write_text(original, encoding="utf-8")

            with self.assertRaises(CookieSaveError):
                self.service.save_json_file(
                    str(file_path),
                    {"cookies": [{"name": "session", "value": "new"}], "bad": object()},
                )

            self.assertEqual(file_path.read_text(encoding="utf-8"), original)

    def test_save_json_file_preserves_credentials_when_temp_write_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "auth.json"
            original = '{"cookies": [{"name": "session", "value": "old"}]}'
            file_path.write_text(original, encoding="utf-8")

            with patch(
                "app.services.auth_service.os.fsync",
                side_effect=OSError("simulated write interruption"),
            ), self.assertRaises(CookieSaveError):
                self.service.save_json_file(
                    str(file_path),
                    {"cookies": [{"name": "session", "value": "new"}]},
                )

            self.assertEqual(file_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(file_path.parent.iterdir()), [file_path])

if __name__ == "__main__":
    unittest.main()
