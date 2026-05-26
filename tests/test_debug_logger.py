import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.debug_logger import debug_logger


class DebugLoggerTests(unittest.TestCase):
    def test_debug_logger_proxy_is_lazy_until_first_attribute_access(self):
        import app.debug_logger as debug_logger_module

        original_singleton = debug_logger_module._debug_logger_singleton
        debug_logger_module._debug_logger_singleton = None
        try:
            self.assertIsNone(debug_logger_module._debug_logger_singleton)

            with patch.object(debug_logger_module, "DebugLogger") as mocked_logger_cls:
                mocked_logger = mocked_logger_cls.return_value
                mocked_logger.pick_used.return_value = {"title": "demo"}

                result = debug_logger_module.debug_logger.pick_used({"title": "demo"}, "title")

            self.assertEqual(result, {"title": "demo"})
            mocked_logger_cls.assert_called_once()
            self.assertIs(debug_logger_module._debug_logger_singleton, mocked_logger)
        finally:
            debug_logger_module._debug_logger_singleton = original_singleton

    def test_pick_used_filters_empty_values(self):
        result = debug_logger.pick_used(
            {
                "title": "demo",
                "empty": "",
                "none_value": None,
                "url": "https://example.com/video.mp4",
            },
            "title",
            "empty",
            "none_value",
            "url",
        )
        self.assertEqual(
            result,
            {
                "title": "demo",
                "url": "https://example.com/video.mp4",
            },
        )

    def test_infer_error_severity_for_ffmpeg_failure(self):
        severity = debug_logger._infer_error_severity(
            component="FFmpegDownloader",
            action="download_error",
            status_code="APP_DL_ERROR",
            details={"exception_type": "RuntimeError", "tool": "ffmpeg"},
        )
        self.assertEqual(severity, "P2-高")

    def test_infer_error_severity_for_user_stop(self):
        severity = debug_logger._infer_error_severity(
            component="DownloadWorker",
            action="stop_task",
            status_code="APP_STOP",
            details={"message": "用户停止"},
        )
        self.assertEqual(severity, "P4-用户操作")

    def test_pick_used_masks_sensitive_values(self):
        result = debug_logger.pick_used(
            {
                "cookie": "sessionid_ss=abc123",
                "cookie_path": "dy_auth.json",
                "token": "abcdefg123456",
                "proxy": "http://user:pass@example.com:7890",
            },
            "cookie",
            "cookie_path",
            "token",
            "proxy",
        )

        self.assertEqual(result["cookie"], "[已脱敏]")
        self.assertEqual(result["token"], "[已脱敏]")
        self.assertEqual(result["cookie_path"], "dy_auth.json")
        self.assertIn("***:***@", result["proxy"])

    def test_log_error_writes_latest_error_summary(self):
        original_latest = debug_logger.latest_error_summary_file
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.latest_error_summary_file = Path(temp_dir) / "latest_error_summary.md"
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component="BiliAPI",
                    action="get_play_url",
                    level="ERROR",
                    message="stream failed",
                    status_code="APP_DL_ERROR",
                    trace_id="trace-1",
                    details={"video_url": "https://example.com/video"},
                )
                content = debug_logger.latest_error_summary_file.read_text(encoding="utf-8")
            finally:
                debug_logger.latest_error_summary_file = original_latest
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("最近错误摘要", content)
        self.assertIn("trace-1", content)

    def test_log_command_writes_arguments_to_log_file(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log_command(
                    component="FFmpegDownloader",
                    tool_name="ffmpeg",
                    command_args=["ffmpeg", "-i", "input.mp4"],
                    trace_id="trace-2",
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("COMMAND", content)
        self.assertIn("input.mp4", content)

    def test_log_command_masks_sensitive_arguments(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log_command(
                    component="Downloader",
                    tool_name="curl",
                    command_args=[
                        "-H",
                        "Cookie: sessionid_ss=abc123",
                        "--proxy",
                        "http://user:pass@example.com:7890",
                    ],
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertNotIn("abc123", content)
        self.assertNotIn("user:pass@", content)
        self.assertIn("Cookie: [已脱敏]", content)


if __name__ == "__main__":
    unittest.main()
