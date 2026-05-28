import tempfile
import unittest
from unittest.mock import Mock, patch

from app.exceptions import CookieLoadError
from app.services.auth_service import AuthService


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = AuthService()

    def test_extract_cookie_list_reads_storage_state_shape(self):
        cookies = self.service.extract_cookie_list(
            {"cookies": [{"name": "sessionid_ss", "value": "abc"}]}
        )

        self.assertEqual(cookies, [{"name": "sessionid_ss", "value": "abc"}])

    def test_extract_cookie_dict_supports_list_payload(self):
        cookie_dict = self.service.extract_cookie_dict(
            [{"name": "SESSDATA", "value": "xyz"}]
        )

        self.assertEqual(cookie_dict, {"SESSDATA": "xyz"})

    def test_build_cookie_string_requires_target_cookie_when_requested(self):
        cookie_str = self.service.build_cookie_string(
            [{"name": "sid_guard", "value": "1"}],
            required_cookie="sessionid_ss",
        )

        self.assertEqual(cookie_str, "")

    def test_extract_cookie_dict_skips_values_that_fail_string_conversion(self):
        class BrokenValue:
            def __str__(self):
                raise TypeError("broken")

        cookie_dict = self.service.extract_cookie_dict({"userId": BrokenValue(), "sessionid": "ok"})

        self.assertEqual(cookie_dict, {"sessionid": "ok"})

    def test_restore_playwright_cookies_loads_saved_cookie_list(self):
        context = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, {"cookies": [{"name": "userId", "value": "1001"}]})

            restored = self.service.restore_playwright_cookies(context, file_path)

        self.assertTrue(restored)
        context.add_cookies.assert_called_once_with([{"name": "userId", "value": "1001"}])

    @patch("app.services.auth_service.time.sleep", return_value=None)
    def test_wait_for_cookie_and_persist_saves_context_state(self, _mock_sleep):
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
        self.assertTrue(self.service.has_cookie([{"name": "sid_guard", "value": "1"}], "sid_guard"))
        self.assertTrue(self.service.has_cookie({"sid_guard": "1"}, "sid_guard"))
        self.assertFalse(self.service.has_cookie(None, "sid_guard"))

    def test_load_json_file_returns_none_when_file_does_not_exist(self):
        self.assertIsNone(self.service.load_json_file("missing-auth.json"))

    def test_load_json_file_raises_cookie_load_error_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            with open(file_path, "w", encoding="utf-8") as fp:
                fp.write("{bad json")

            with self.assertRaises(CookieLoadError):
                self.service.load_json_file(file_path)

    def test_save_and_load_json_file_round_trip_keeps_payload(self):
        payload = {"cookies": [{"name": "SESSDATA", "value": "demo"}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = f"{temp_dir}/auth.json"
            self.service.save_json_file(file_path, payload)
            restored = self.service.load_json_file(file_path)

        self.assertEqual(restored, payload)


if __name__ == "__main__":
    unittest.main()
