"""Log center semantic derivation tests."""

from __future__ import annotations

import unittest

from app.ui.pages.log_center_page import LogCenterPage

SEMANTIC_WARN_SAMPLE = {
    "id": "__semantic_test_warn__",
    "time": "2026-06-24 03:58:45",
    "level": "WARN",
    "source": "MainWindow",
    "status_code": "FRONTEND_RENDER_SLOW",
    "message": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
    "detail": {"duration_ms": 123.64},
}

SEMANTIC_ERROR_SAMPLE = {
    "id": "__semantic_test_error__",
    "time": "2026-06-24 03:58:52",
    "level": "ERROR",
    "source": "N_m3u8DL_RE_Downloader",
    "status_code": "LOCAL_HLS_PROXY_ERROR",
    "message": "[WinError 10054] 远程主机强迫关闭了一个现有的连接。",
    "detail": {"exception_type": "ConnectionResetError"},
}


class LogCenterSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = LogCenterPage.__new__(LogCenterPage)
        self.page._category = "all"

    def test_derive_result_type_maps_finish_status_to_success(self) -> None:
        item = {"level": "INFO", "source": "DownloadWorker", "status_code": "DL_FINISH"}
        self.assertEqual(self.page._derive_result_type(item), "success")
        self.assertEqual(self.page._result_display_text(self.page._derive_result_type(item)), "SUCCESS")

    def test_derive_result_type_queue_stays_info(self) -> None:
        item = {"level": "INFO", "source": "DownloadWorker", "status_code": "DL_QUEUE"}
        self.assertEqual(self.page._derive_result_type(item), "info")

    def test_derive_result_type_maps_command_level_to_cmd(self) -> None:
        item = {"level": "COMMAND", "source": "FFmpeg"}
        self.assertEqual(self.page._derive_result_type(item), "command")
        self.assertEqual(self.page._result_display_text("command"), "CMD")

    def test_performance_warn_not_error_scope(self) -> None:
        item = dict(SEMANTIC_WARN_SAMPLE)
        self.assertEqual(self.page._derive_result_type(item), "warn")
        self.assertEqual(self.page._derive_log_scope(item), "performance")
        self.assertEqual(self.page._derive_event_stage(item), "performance")

    def test_derive_result_type_error_sample(self) -> None:
        item = dict(SEMANTIC_ERROR_SAMPLE)
        self.assertEqual(self.page._derive_result_type(item), "error")
        self.assertEqual(self.page._derive_log_scope(item), "error")

    def test_derive_log_scope_download_worker(self) -> None:
        item = {"level": "INFO", "source": "DownloadWorker", "status_code": "DL_QUEUE"}
        self.assertEqual(self.page._derive_log_scope(item), "download")
        self.assertEqual(self.page._derive_event_stage(item), "queue")

    def test_derive_log_scope_bilibili_spider(self) -> None:
        item = {"level": "INFO", "source": "BilibiliSpider", "status_code": "BILI_SPIDER_START"}
        self.assertEqual(self.page._derive_log_scope(item), "crawl")
        self.assertEqual(self.page._derive_event_stage(item), "start")

    def test_derive_log_scope_main_window_init(self) -> None:
        item = {"level": "INFO", "source": "ApplicationController", "status_code": "APP_INIT"}
        self.assertEqual(self.page._derive_log_scope(item), "system")

    def test_matches_category_error_excludes_performance_warn(self) -> None:
        warn_item = dict(SEMANTIC_WARN_SAMPLE)
        self.page._category = "error"
        self.assertFalse(self.page._matches_category(warn_item))
        self.page._category = "performance"
        self.assertTrue(self.page._matches_category(warn_item))

    def test_decorate_log_item_sets_semantic_fields(self) -> None:
        page = LogCenterPage.__new__(LogCenterPage)
        page._platform_meta_by_id = {}
        page._platform_options = []
        item = {"level": "INFO", "source": "DownloadWorker", "status_code": "DL_FINISH", "platform": "系统"}
        row = page._decorate_log_item(item)
        self.assertEqual(row["level_display"], "SUCCESS")
        self.assertEqual(row["log_scope"], "download")
        self.assertEqual(row["event_stage"], "finish")


if __name__ == "__main__":
    unittest.main()
