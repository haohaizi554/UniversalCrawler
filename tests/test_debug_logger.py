"""测试模块，覆盖 `tests/test_debug_logger.py` 对应功能的行为与回归场景。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.debug_logger import debug_logger, normalize_trace_prefix

class DebugLoggerTests(unittest.TestCase):
    
    def test_debug_logger_proxy_is_lazy_until_first_attribute_access(self):
        """验证 `test_debug_logger_proxy_is_lazy_until_first_attribute_access` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
        import app.debug_logger as debug_logger_module

        with patch.object(debug_logger_module, "_debug_logger_singleton", None):
            self.assertIsNone(debug_logger_module._debug_logger_singleton)

            with patch.object(debug_logger_module, "DebugLogger") as mocked_logger_cls:
                mocked_logger = mocked_logger_cls.return_value
                mocked_logger.pick_used.return_value = {"title": "demo"}

                result = debug_logger_module.debug_logger.pick_used({"title": "demo"}, "title")

            self.assertEqual(result, {"title": "demo"})
            mocked_logger_cls.assert_called_once()
            self.assertIs(debug_logger_module._debug_logger_singleton, mocked_logger)

    def test_pick_used_filters_empty_values(self):
        """验证 `test_pick_used_filters_empty_values` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
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
        """验证 `test_infer_error_severity_for_ffmpeg_failure` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
        severity = debug_logger._infer_error_severity(
            component="FFmpegDownloader",
            action="download_error",
            status_code="APP_DL_ERROR",
            details={"exception_type": "RuntimeError", "tool": "ffmpeg"},
        )
        self.assertEqual(severity, "P2-高")

    def test_infer_error_severity_for_user_stop(self):
        """验证 `test_infer_error_severity_for_user_stop` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
        severity = debug_logger._infer_error_severity(
            component="DownloadWorker",
            action="stop_task",
            status_code="APP_STOP",
            details={"message": "用户停止"},
        )
        self.assertEqual(severity, "P4-用户操作")

    def test_pick_used_masks_sensitive_values(self):
        """验证 `test_pick_used_masks_sensitive_values` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
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

    def test_pick_used_masks_bearer_token_inline(self):
        """验证 `test_pick_used_masks_bearer_token_inline` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
        result = debug_logger.pick_used(
            {
                "authorization": "Bearer abc.def.ghi",
                "headers": "Authorization: Bearer abc.def.ghi",
            },
            "authorization",
            "headers",
        )

        self.assertEqual(result["authorization"], "Bearer ***")
        self.assertIn("Authorization: [已脱敏]", result["headers"])

    def test_log_error_writes_latest_error_summary(self):
        """验证 `test_log_error_writes_latest_error_summary` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
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
        """验证 `test_log_command_writes_arguments_to_log_file` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
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
        """验证 `test_log_command_masks_sensitive_arguments` 对应场景是否符合预期，供 `DebugLoggerTests` 使用。"""
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

    def test_trace_id_prefixes_are_platform_normalized(self):
        self.assertEqual(normalize_trace_prefix("douyin-dy"), "dy")
        self.assertEqual(normalize_trace_prefix("bili-BV1xx-123"), "bilibili_BV1xx_123")
        self.assertEqual(normalize_trace_prefix("miss-m3u8"), "missav_m3u8")

        trace_id = debug_logger.new_trace_id("xiaohongshu-task")

        self.assertTrue(trace_id.startswith("xhs_task_"))
        self.assertNotIn("-", trace_id)

if __name__ == "__main__":
    unittest.main()
