from __future__ import annotations

import threading
from pathlib import Path

from app.ui.viewmodels.log_detail_worker import (
    LogDetailExportRequest,
    LogDetailExportWorker,
    LogDetailRequest,
    LogDetailWorker,
    build_cached_log_detail_result,
    build_log_detail_result,
)
from app.ui.viewmodels.log_platforms import builtin_platform_metas


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
