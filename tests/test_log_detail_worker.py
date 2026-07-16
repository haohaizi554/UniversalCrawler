from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.ui.pages.log_center_page import (
    LOG_TIME_COLUMN_MIN_WIDTH,
    LOG_TIME_COLUMN_SAMPLE,
    LogCenterPage,
)
from app.ui.styles.themes import generate_log_center_stylesheet
from app.ui.viewmodels.log_detail_worker import (
    LogDetailExportRequest,
    LogDetailExportResult,
    LogDetailExportWorker,
    LogDetailRequest,
    LogDetailWorker,
    build_cached_log_detail_result,
    build_log_detail_result,
)
from app.ui.viewmodels.log_query_worker import LogQueryResult
from shared.log_platforms import builtin_platform_metas


def _request(item, **overrides):
    metas = builtin_platform_metas()
    values = {
        "sequence": 1,
        "item_id": str(item.get("id") or "row-1"),
        "item": item,
        "language": "en-US",
        "platform_options": tuple(metas.values()),
        "platform_meta_by_id": metas,
    }
    values.update(overrides)
    return LogDetailRequest(**values)


def test_build_log_detail_result_formats_payload_for_direct_render():
    item = {
        "id": "row-1",
        "time": "2026-07-06 03:31:00",
        "level": "INFO",
        "source": "GUI",
        "platform": "系统",
        "message": "日志缓存已刷新",
        "detail": {"description": "日志缓存已刷新", "trace_id": "trace-1"},
        "status_code": "GUI_REFRESH",
    }

    result = build_log_detail_result(_request(item))

    assert result.item_id == "row-1"
    assert result.time_text == "2026-07-06 03:31:00"
    assert result.platform_text.endswith("System")
    assert result.trace_id == "trace-1"
    assert result.detail_payload["trace_id"] == "trace-1"
    assert '"trace_id": "trace-1"' in result.detail_json_text
    assert "&quot;trace_id&quot;" in result.detail_json_escaped
    assert '"message"' in result.full_payload_text


def test_log_detail_worker_delivers_latest_result_after_rapid_submits():
    first = {"id": "first", "time": "2026-07-06 03:30:00", "level": "INFO", "message": "first"}
    second = {"id": "second", "time": "2026-07-06 03:31:00", "level": "ERROR", "message": "second"}
    received = []
    ready = threading.Event()

    def on_result(result):
        received.append(result.sequence)
        if result.sequence == 2:
            ready.set()

    worker = LogDetailWorker(on_result)
    try:
        worker.submit(_request(first, sequence=1, item_id="first"))
        worker.submit(_request(second, sequence=2, item_id="second"))
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert received[-1] == 2


def test_cached_log_detail_result_reuses_persisted_worker_payload():
    class FakeCacheService:
        def __init__(self):
            self.values = {}
            self.persist_flags = {}
            self.set_count = 0

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, *, ttl_seconds=None, persist=False):
            self.values[key] = value
            self.persist_flags[key] = persist
            self.set_count += 1

    item = {
        "id": "row-cache",
        "time": "2026-07-06 03:31:00",
        "level": "INFO",
        "source": "GUI",
        "platform": "System",
        "message": "Download completed: demo",
        "detail": {"description": "Download completed: demo", "trace_id": "trace-cache"},
        "status_code": "DOWNLOADER",
    }
    cache = FakeCacheService()

    first = build_cached_log_detail_result(_request(item, sequence=1), cache_service=cache)
    second = build_cached_log_detail_result(_request(item, sequence=2), cache_service=cache)

    assert first.trace_id == "trace-cache"
    assert second.trace_id == "trace-cache"
    assert second.sequence == 2
    assert cache.set_count == 1
    assert len(cache.values) == 1
    assert next(iter(cache.persist_flags.values())) is False


def test_log_detail_export_worker_writes_payload_off_ui_thread(tmp_path):
    target = tmp_path / "log_detail.json"
    received = []
    ready = threading.Event()

    def on_result(result):
        received.append(result)
        ready.set()

    worker = LogDetailExportWorker(on_result)
    try:
        worker.submit(
            LogDetailExportRequest(
                sequence=7,
                item_id="row-1",
                path=str(target),
                text='{"message": "ok"}',
            )
        )
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert target.read_text(encoding="utf-8") == '{"message": "ok"}'
    assert received[-1].sequence == 7
    assert received[-1].ok is True


def test_log_detail_export_success_feedback_is_non_modal(monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = LogCenterPage()
    information_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: information_calls.append((args, kwargs)),
    )
    page._detail_export_sequence = 3
    page._current_detail_result = object()

    try:
        page._on_log_detail_export_result(
            LogDetailExportResult(
                sequence=3,
                item_id="row-1",
                path="log_detail.json",
                ok=True,
            )
        )
        app.processEvents()
    finally:
        page._log_query_worker.shutdown()
        page._log_detail_worker.shutdown()
        page._log_detail_export_worker.shutdown()
        page.deleteLater()
        app.processEvents()

    assert information_calls == []


def test_log_center_table_uses_four_pixel_cell_padding():
    app = QApplication.instance() or QApplication([])
    page = LogCenterPage()

    try:
        delegate = page.table.itemDelegate()
        assert delegate._cell_padding == (4, 4)
        assert delegate._content_rect(QRect(10, 2, 100, 32)) == QRect(14, 2, 92, 32)
        expected_time_width = max(
            LOG_TIME_COLUMN_MIN_WIDTH,
            page.table.fontMetrics().horizontalAdvance(LOG_TIME_COLUMN_SAMPLE) + 16,
        )
        assert page.table.columnWidth(0) == expected_time_width

        stylesheet = generate_log_center_stylesheet(False)
        item_rule = stylesheet.split("QTableView#LogItemsTable::item {", 1)[1].split("}", 1)[0]
        assert "padding-left: 0px;" in item_rule
        assert "padding-right: 0px;" in item_rule
    finally:
        page._log_query_worker.shutdown()
        page._log_detail_worker.shutdown()
        page._log_detail_export_worker.shutdown()
        page.deleteLater()
        app.processEvents()


def test_log_center_live_refresh_follows_first_page_but_keeps_history_page():
    app = QApplication.instance() or QApplication([])
    page = LogCenterPage()
    page._log_query_worker.shutdown()
    submitted = []
    page._log_query_worker = SimpleNamespace(
        submit=submitted.append,
        shutdown=lambda: None,
    )
    old_rows = [
        {"id": "old-newest", "time": "2026-07-16 08:00:02", "level": "INFO", "message": "old newest"},
        {"id": "old-middle", "time": "2026-07-16 08:00:01", "level": "INFO", "message": "old middle"},
        {"id": "old-oldest", "time": "2026-07-16 08:00:00", "level": "INFO", "message": "old oldest"},
    ]
    newest = {"id": "newest", "time": "2026-07-16 08:00:03", "level": "INFO", "message": "newest"}
    newer = {"id": "newer", "time": "2026-07-16 08:00:04", "level": "INFO", "message": "newer"}

    try:
        page._all_items = tuple(old_rows)
        page._log_items_signature = page._make_log_items_signature(old_rows)
        page.items = list(old_rows[:2])
        page.table.set_rows(page.items)
        page.table.select_id("old-newest")
        page._current_page = 1
        page.table.scrollToTop = Mock()

        page.render({"log_items": [newest, *old_rows]})
        first_page_request = submitted[-1]
        assert first_page_request.page == 1
        assert first_page_request.selected_id == "old-newest"
        assert first_page_request.selected_id_moves_page is False

        page._on_log_query_result(
            LogQueryResult(
                sequence=first_page_request.sequence,
                page_items=[newest, old_rows[0]],
                category_counts={key: 0 for key in ("all", "crawl", "download", "system", "performance", "error")},
                total_count=4,
                matched_count=4,
                visible_count=2,
                total_pages=2,
                first_trace_id="",
                current_page=1,
                selected_id="old-newest",
            )
        )
        assert page.selected_id() == "old-newest"
        page.table.scrollToTop.assert_called_once_with()

        page._current_page = 2
        page.table.select_id("old-newest")
        page.render({"log_items": [newer, newest, *old_rows]})
        history_request = submitted[-1]
        assert history_request.page == 2
        assert history_request.selected_id == "old-newest"
        assert history_request.selected_id_moves_page is False

        scrollbar = page.table.verticalScrollBar()
        scrollbar.value = Mock(return_value=73)
        scrollbar.setValue = Mock()
        page._on_log_query_result(
            LogQueryResult(
                sequence=history_request.sequence,
                page_items=[old_rows[0], old_rows[1]],
                category_counts={key: 0 for key in ("all", "crawl", "download", "system", "performance", "error")},
                total_count=5,
                matched_count=5,
                visible_count=2,
                total_pages=3,
                first_trace_id="",
                current_page=2,
                selected_id="old-newest",
            )
        )
        assert page._current_page == 2
        scrollbar.setValue.assert_called_once_with(73)
    finally:
        page._log_query_worker.shutdown()
        page._log_detail_worker.shutdown()
        page._log_detail_export_worker.shutdown()
        page.deleteLater()
        app.processEvents()


def test_log_center_page_does_not_reintroduce_detail_formatting_fallbacks():
    page_source = Path("app/ui/pages/log_center_page.py").read_text(encoding="utf-8")

    assert "LogDetailWorker" in page_source
    assert "LogDetailExportWorker" in page_source
    assert "write_text(" not in page_source
    for forbidden in (
        "json.dumps(",
        "normalize_detail_payload(",
        "build_log_detail_payload(",
        "extract_trace_id(",
        "localize_log_payload(",
    ):
        assert forbidden not in page_source
