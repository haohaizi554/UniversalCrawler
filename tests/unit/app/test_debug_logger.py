"""调试日志记录、脱敏与结构化输出测试。"""

import tempfile
import time
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from app.debug_logger import debug_logger, normalize_trace_prefix


class _HostileDiagnosticValue:
    def __str__(self):
        raise RuntimeError("diagnostic stringification failed")


class _HostileDiagnosticError(Exception):
    def __str__(self):
        raise RuntimeError("exception stringification failed")


class _SignedDiagnosticValue:
    def __str__(self):
        return "https://cdn.example.com/video.mp4?opaque=object-secret#state"


class _HostileDiagnosticInt(int):
    def __str__(self):
        raise RuntimeError("integer stringification failed")


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

    def test_pick_used_strips_unknown_signed_query_and_fragment_from_urls(self):
        """CDN 签名字段名不可枚举，诊断 URL 必须统一去除 query/fragment。"""
        signed_url = (
            "https://cdn.example.com/video.mp4?wsSecret=unknown-secret"
            "&expires=1780000000#player-state"
        )

        result = debug_logger.pick_used(
            {
                "source_url": signed_url,
                "message": f"下载失败，地址 {signed_url}，请重试",
            },
            "source_url",
            "message",
        )

        self.assertEqual(result["source_url"], "https://cdn.example.com/video.mp4")
        self.assertEqual(
            result["message"],
            "下载失败，地址 https://cdn.example.com/video.mp4",
        )
        self.assertNotIn("unknown-secret", str(result))
        self.assertNotIn("expires", str(result))
        self.assertNotIn("player-state", str(result))

    def test_pick_used_strips_query_from_a_complete_unicode_url_value(self):
        result = debug_logger.pick_used(
            {"source_url": "https://例子.测试/视频.mp4?签名=不应落盘#播放器"},
            "source_url",
        )

        self.assertEqual(result["source_url"], "https://例子.测试/视频.mp4")

    def test_pick_used_strips_unicode_signed_url_embedded_in_prose(self):
        result = debug_logger.pick_used(
            {
                "message": (
                    "下载失败，地址 "
                    "https://例子.测试/视频.mp4?签名=不应落盘#播放器，"
                    "请重试"
                )
            },
            "message",
        )

        self.assertEqual(
            result["message"],
            "下载失败，地址 https://例子.测试/视频.mp4",
        )

    def test_pick_used_does_not_leave_a_quoted_unknown_query_value(self):
        result = debug_logger.pick_used(
            {
                "message": (
                    "download failed for "
                    "https://cdn.example.com/video.mp4?opaque='quoted-secret', retry"
                )
            },
            "message",
        )

        self.assertIn("https://cdn.example.com/video.mp4", result["message"])
        self.assertIn("retry", result["message"])
        self.assertNotIn("opaque", result["message"])
        self.assertNotIn("quoted-secret", result["message"])

    def test_pick_used_strips_query_from_json_escaped_http_url(self):
        result = debug_logger.pick_used(
            {
                "message": (
                    'payload={"photoUrl":"https:\\/\\/cdn.example.com\\/video.mp4'
                    '?opaque=escaped-secret#player"}'
                )
            },
            "message",
        )

        self.assertIn(r"https:\/\/cdn.example.com\/video.mp4", result["message"])
        self.assertNotIn("opaque", result["message"])
        self.assertNotIn("escaped-secret", result["message"])
        self.assertNotIn("player", result["message"])

    def test_pick_used_fails_closed_for_malformed_url_with_query_secret(self):
        result = debug_logger.pick_used(
            {
                "message": (
                    "请求失败："
                    "https://[invalid.example/video.mp4?opaque=不应落盘，"
                    "请检查地址"
                )
            },
            "message",
        )

        self.assertEqual(
            result["message"],
            "请求失败：https://[invalid.example/video.mp4",
        )

    def test_pick_used_fails_closed_for_whitespace_and_broken_url_capabilities(self):
        result = debug_logger.pick_used(
            {
                "newline": (
                    "https://cdn.example.com/video.mp4\n"
                    "?opaque=line-secret#state"
                ),
                "space": (
                    "https://cdn.example.com/video.mp4 "
                    "?opaque=space-secret#state"
                ),
                "broken": (
                    "https:/ /cdn.example.com/video.mp4"
                    "?opaque=broken-secret#state"
                ),
            },
            "newline",
            "space",
            "broken",
        )

        rendered = str(result)
        for secret in ("line-secret", "space-secret", "broken-secret", "opaque", "state"):
            self.assertNotIn(secret, rendered)
        self.assertIn("cdn.example.com/video.mp4", rendered)

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

    def test_log_command_masks_values_after_sensitive_flags(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log_command(
                    component="ReleaseSigner",
                    tool_name="signtool",
                    command_args=[
                        "signtool",
                        "sign",
                        "/p",
                        "pfx-secret-value",
                        "--token=token-secret-value",
                    ],
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertNotIn("pfx-secret-value", content)
        self.assertNotIn("token-secret-value", content)

    def test_log_command_strips_unknown_signed_url_query(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log_command(
                    component="KuaishouDownloader",
                    tool_name="ffmpeg",
                    command_args=[
                        "ffmpeg",
                        "-i",
                        "https://cdn.example.com/video.mp4?clientCacheKey=secret-value&foo=bar",
                    ],
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("https://cdn.example.com/video.mp4", content)
        self.assertNotIn("clientCacheKey", content)
        self.assertNotIn("secret-value", content)
        self.assertNotIn("foo=bar", content)

    def test_log_sanitizes_url_capabilities_from_every_metadata_surface(self):
        signed = "https://cdn.example.com/video.mp4?opaque=metadata-secret#state"
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component=signed,
                    action=signed,
                    level=signed,
                    message=signed,
                    status_code=signed,
                    trace_id=signed,
                )
                debug_logger.log_api(
                    component=signed,
                    api_name=signed,
                    message=signed,
                    status_code=signed,
                    trace_id=signed,
                )
                debug_logger.log_command(
                    component=signed,
                    tool_name=signed,
                    message=signed,
                    trace_id=signed,
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("https://cdn.example.com/video.mp4", content)
        self.assertNotIn("opaque", content)
        self.assertNotIn("metadata-secret", content)
        self.assertNotIn("state", content)

    def test_logging_is_best_effort_for_hostile_objects_and_sanitizes_nested_values(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component=_HostileDiagnosticValue(),
                    action=_HostileDiagnosticValue(),
                    status_code=_HostileDiagnosticValue(),
                    trace_id=_HostileDiagnosticValue(),
                    details={
                        _HostileDiagnosticValue(): {
                            "candidate": _SignedDiagnosticValue(),
                        }
                    },
                )
                debug_logger.log_command(
                    component="Downloader",
                    tool_name="tool",
                    command_args=[_HostileDiagnosticValue()],
                )
                debug_logger.log_exception(
                    component="Downloader",
                    action="request",
                    exc=_HostileDiagnosticError(),
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("https://cdn.example.com/video.mp4", content)
        self.assertNotIn("object-secret", content)
        self.assertNotIn("opaque", content)
        self.assertIn("[unprintable]", content)

    def test_diagnostic_text_is_bounded_before_secret_scanning(self):
        started_at = time.monotonic()

        cleaned = debug_logger._safe_diagnostic_text("a" * 16_384)

        self.assertLessEqual(len(cleaned), 8_220)
        self.assertLess(time.monotonic() - started_at, 1.0)
        self.assertTrue(cleaned.endswith("...[truncated]"))

    def test_malformed_url_scanning_is_linear_under_slash_flood(self):
        payload = "http:" + "/ " * 4_096
        started_at = time.monotonic()

        cleaned = debug_logger._safe_diagnostic_text(payload)

        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertTrue(cleaned.endswith("...[truncated]"))

    def test_malformed_url_scanning_keeps_source_indices_after_unicode_text(self):
        cleaned = debug_logger._safe_diagnostic_text(
            "\u0130 https:/ /cdn.example.com/video.mp4?opaque=unicode-prefix-secret"
        )

        self.assertIn("\u0130 https:/ /cdn.example.com/video.mp4", cleaned)
        self.assertNotIn("opaque", cleaned)
        self.assertNotIn("unicode-prefix-secret", cleaned)

    def test_pure_path_url_redaction_allows_ascii_punctuation_in_the_path(self):
        for punctuation in (")", ";", "!", ",", "]", "}"):
            with self.subTest(punctuation=punctuation):
                cleaned = debug_logger._safe_diagnostic_text(
                    PurePosixPath(
                        f"https://cdn.example.com/video{punctuation}clip.mp4"
                        "?opaque=path-secret#state"
                    )
                )

                self.assertNotIn("opaque", cleaned)
                self.assertNotIn("path-secret", cleaned)
                self.assertNotIn("state", cleaned)

    def test_url_redaction_does_not_release_query_tail_after_ascii_punctuation(self):
        for punctuation in ("!", ",", ";", ")", "]", "}"):
            with self.subTest(punctuation=punctuation):
                cleaned = debug_logger._safe_diagnostic_text(
                    "https://cdn.example.com/video.mp4"
                    f"?opaque=head{punctuation}tail-secret#state"
                )

                self.assertNotIn("opaque", cleaned)
                self.assertNotIn("tail-secret", cleaned)
                self.assertNotIn("state", cleaned)

    def test_url_redaction_does_not_release_query_tail_after_unicode_punctuation(self):
        for punctuation in "，。；：！？）》】、":
            with self.subTest(punctuation=punctuation):
                cleaned = debug_logger._safe_diagnostic_text(
                    "https://cdn.example.com/video.mp4"
                    f"?opaque=head{punctuation}tail-secret#state"
                )

                self.assertNotIn("opaque", cleaned)
                self.assertNotIn("tail-secret", cleaned)
                self.assertNotIn("state", cleaned)

    def test_log_preserves_prose_between_multiple_signed_urls(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component="Downloader",
                    action="request",
                    message=(
                        "failed https://cdn.example.com/video.mp4?token=first-secret "
                        "please retry https://backup.example.com/video.mp4?token=second-secret "
                        "after refresh"
                    ),
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("https://cdn.example.com/video.mp4", content)
        self.assertIn("please retry", content)
        self.assertIn("https://backup.example.com/video.mp4", content)
        self.assertIn("after refresh", content)
        self.assertNotIn("first-secret", content)
        self.assertNotIn("second-secret", content)

    def test_log_redacts_signed_url_stringified_by_pure_path(self):
        result = debug_logger.pick_used(
            {
                "nested_path": PurePosixPath(
                    "https://cdn.example.com/video.mp4?token=path-secret"
                )
            },
            "nested_path",
        )

        self.assertNotIn("path-secret", str(result))
        self.assertIn("https:/cdn.example.com/video.mp4", str(result))

    def test_hostile_integer_subclass_does_not_drop_the_log_event(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component="Downloader",
                    action="request",
                    message="hostile integer retained",
                    details={"attempt": _HostileDiagnosticInt(1)},
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("hostile integer retained", content)
        self.assertIn("[unprintable]", content)

    def test_truncation_cannot_hide_the_userinfo_delimiter(self):
        secret = "S3CR3T" * 2_000

        cleaned = debug_logger._safe_diagnostic_text(
            f"failed http://user:{secret}@example.com/video.mp4"
        )

        self.assertNotIn("S3CR3T", cleaned)
        self.assertNotIn("user:", cleaned)
        self.assertIn("[redacted]", cleaned)
        self.assertTrue(cleaned.endswith("...[truncated]"))

    def test_userinfo_redaction_covers_escaped_and_single_slash_urls(self):
        values = (
            r"http:\/\/user:json-secret@example.com/video.mp4",
            r"https:\/\/user:json-secret@example.com/video.mp4?signature=opaque",
            PurePosixPath("https://user:path-secret@example.com/video.mp4"),
        )

        for value in values:
            with self.subTest(value=value):
                cleaned = debug_logger._safe_diagnostic_text(value)
                self.assertNotIn("json-secret", cleaned)
                self.assertNotIn("path-secret", cleaned)
                self.assertNotIn("user:", cleaned)
                self.assertIn("***:***@", cleaned)

    def test_userinfo_redaction_handles_empty_user_and_last_at_separator(self):
        values = (
            "http://:token-secret@example.com/video.mp4",
            "http://user:alpha-secret@beta-secret@example.com/video.mp4",
            r"http:\/\/user:alpha-secret@beta-secret@example.com/video.mp4",
            r"http:\\/\\/user:alpha-secret@beta-secret@example.com/video.mp4",
            "http://///user:alpha-secret@beta-secret@example.com/video.mp4",
        )

        for value in values:
            with self.subTest(value=value):
                cleaned = debug_logger._safe_diagnostic_text(value)
                self.assertNotIn("token-secret", cleaned)
                self.assertNotIn("alpha-secret", cleaned)
                self.assertNotIn("beta-secret", cleaned)
                self.assertIn("***:***@example.com/video.mp4", cleaned)

    def test_log_strips_signed_url_query_from_nested_mapping_keys(self):
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log(
                    component="KuaishouDownloader",
                    action="candidate_failures",
                    details={
                        "failures": {
                            "https://cdn.example.com/video.mp4?opaque=key-secret#player": "timeout"
                        }
                    },
                )
                content = debug_logger.session_file.read_text(encoding="utf-8")
            finally:
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        self.assertIn("https://cdn.example.com/video.mp4", content)
        self.assertNotIn("opaque", content)
        self.assertNotIn("key-secret", content)
        self.assertNotIn("player", content)

    def test_log_exception_masks_inline_secrets_in_log_and_summary(self):
        original_latest = debug_logger.latest_error_summary_file
        original_session = debug_logger.session_file
        original_latest_log = debug_logger.latest_file
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_logger.latest_error_summary_file = Path(temp_dir) / "latest_error_summary.md"
            debug_logger.session_file = Path(temp_dir) / "session.log"
            debug_logger.latest_file = Path(temp_dir) / "latest_debug.log"
            try:
                debug_logger.log_exception(
                    "ApiClient",
                    "request",
                    RuntimeError(
                        "request failed: cookie=session-secret; "
                        "Authorization: Bearer bearer-secret; "
                        "https://cdn.example.com/video.mp4?opaqueSignature=cdn-secret"
                        "#private-player-state"
                    ),
                )
                session_content = debug_logger.session_file.read_text(encoding="utf-8")
                summary_content = debug_logger.latest_error_summary_file.read_text(encoding="utf-8")
            finally:
                debug_logger.latest_error_summary_file = original_latest
                debug_logger.session_file = original_session
                debug_logger.latest_file = original_latest_log

        for content in (session_content, summary_content):
            self.assertNotIn("session-secret", content)
            self.assertNotIn("bearer-secret", content)
            self.assertNotIn("opaqueSignature", content)
            self.assertNotIn("cdn-secret", content)
            self.assertNotIn("private-player-state", content)

    def test_trace_id_prefixes_are_platform_normalized(self):
        self.assertEqual(normalize_trace_prefix("douyin-dy"), "dy")
        self.assertEqual(normalize_trace_prefix("bili-BV1xx-123"), "bilibili_BV1xx_123")
        self.assertEqual(normalize_trace_prefix("miss-m3u8"), "missav_m3u8")

        trace_id = debug_logger.new_trace_id("xiaohongshu-task")

        self.assertTrue(trace_id.startswith("xhs_task_"))
        self.assertNotIn("-", trace_id)

if __name__ == "__main__":
    unittest.main()
