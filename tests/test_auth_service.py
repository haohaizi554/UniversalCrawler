import tempfile
import unittest
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
