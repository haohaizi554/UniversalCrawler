from __future__ import annotations

import threading

from app.ui.viewmodels.log_platforms import builtin_platform_metas
from app.ui.viewmodels.log_query_worker import LogQueryRequest, LogQueryWorker, query_log_items


def _platform_context():
    metas = builtin_platform_metas()
    return tuple(metas.values()), metas


def _request(rows, **overrides):
    options, metas = _platform_context()
    values = {
        "sequence": 1,
        "items": tuple(rows),
        "categories": ("all", "crawl", "download", "system", "performance", "error"),
        "category": "all",
        "level": "全部",
        "time_range": "全部",
        "platform_id": None,
        "trace_query": "",
        "keyword": "",
        "platform_options": options,
        "platform_meta_by_id": metas,
        "page": 1,
        "page_size": 2,
        "selected_id": "",
    }
    values.update(overrides)
    return LogQueryRequest(**values)


def test_query_log_items_filters_counts_sorts_and_paginates():
    rows = [
        {"id": "old", "time": "2026-06-30 10:00:00", "level": "INFO", "source": "ApplicationController"},
        {
            "id": "download",
            "time": "2026-06-30 10:01:00",
            "level": "INFO",
            "source": "DownloadWorker",
            "status_code": "DL_START",
            "message": "download task",
        },
        {"id": "error", "time": "2026-06-30 10:02:00", "level": "ERROR", "source": "BiliAPI", "message": "failed"},
    ]

    result = query_log_items(_request(rows, keyword="task"))

    assert result.total_count == 3
    assert result.matched_count == 1
    assert result.visible_count == 1
    assert [item["id"] for item in result.page_items] == ["download"]
    assert result.category_counts["all"] == 1
    assert result.category_counts["download"] == 1


def test_query_log_items_moves_to_selected_item_page():
    rows = [
        {"id": "a", "time": "2026-06-30 10:00:00", "level": "INFO"},
        {"id": "b", "time": "2026-06-30 10:01:00", "level": "INFO"},
        {"id": "c", "time": "2026-06-30 10:02:00", "level": "INFO"},
    ]

    result = query_log_items(_request(rows, page_size=1, selected_id="a"))

    assert result.current_page == 3
    assert result.total_pages == 3
    assert [item["id"] for item in result.page_items] == ["a"]
    assert result.selected_id == "a"


def test_log_query_worker_delivers_latest_result_after_rapid_submits():
    rows = [{"id": "a", "time": "2026-06-30 10:00:00", "level": "INFO"}]
    received = []
    ready = threading.Event()

    def on_result(result):
        received.append(result.sequence)
        if result.sequence == 2:
            ready.set()

    worker = LogQueryWorker(on_result)
    try:
        worker.submit(_request(rows, sequence=1))
        worker.submit(_request(rows, sequence=2, keyword="missing"))
        assert ready.wait(timeout=2)
    finally:
        worker.shutdown()

    assert received[-1] == 2
