from __future__ import annotations

from datetime import datetime

from app.ui.viewmodels import log_filtering
from app.ui.viewmodels.log_platforms import builtin_platform_metas


def _platform_context():
    metas = builtin_platform_metas()
    return list(metas.values()), metas


def test_sort_log_items_keeps_newest_first_and_stable_for_equal_times():
    older = {"id": "older", "time": "2026-06-30 10:00:00"}
    newest_a = {"id": "newest-a", "time": "2026-06-30 11:00:00"}
    newest_b = {"id": "newest-b", "time": "2026-06-30 11:00:00"}

    rows = log_filtering.sort_log_items([older, newest_a, newest_b])

    assert [row["id"] for row in rows] == ["newest-b", "newest-a", "older"]


def test_matches_filters_uses_level_time_platform_trace_and_keyword():
    options, metas = _platform_context()
    row = {
        "time": "2026-06-30 11:45:00",
        "level": "INFO",
        "source": "BiliAPI",
        "platform": "Bilibili",
        "trace_id": "bili_trace_1",
        "message": "pipeline ready",
        "detail": {"request": "playlist"},
    }

    assert log_filtering.matches_filters(
        row,
        category="all",
        level="INFO",
        time_range="\u8fd1 30 \u5206\u949f",
        platform_id="bilibili",
        trace_query="TRACE_1",
        keyword="playlist",
        platform_options=options,
        platform_meta_by_id=metas,
        now=datetime(2026, 6, 30, 12, 0, 0),
    )

    assert not log_filtering.matches_filters(
        row,
        category="all",
        level="INFO",
        time_range="\u8fd1 30 \u5206\u949f",
        platform_id="bilibili",
        trace_query="TRACE_1",
        keyword="missing",
        platform_options=options,
        platform_meta_by_id=metas,
        now=datetime(2026, 6, 30, 12, 0, 0),
    )

    assert not log_filtering.matches_filters(
        row,
        category="all",
        level="INFO",
        time_range="\u8fd1 30 \u5206\u949f",
        platform_id="bilibili",
        trace_query="TRACE_1",
        keyword="playlist",
        platform_options=options,
        platform_meta_by_id=metas,
        now=datetime(2026, 6, 30, 12, 20, 0),
    )


def test_system_and_performance_logs_are_visible_under_platform_filter():
    options, metas = _platform_context()
    system_row = {
        "time": "2026-06-30 11:45:00",
        "level": "INFO",
        "source": "ApplicationController",
        "status_code": "APP_INIT",
        "platform": "\u7cfb\u7edf",
    }

    assert log_filtering.matches_platform(
        system_row,
        "bilibili",
        platform_options=options,
        platform_meta_by_id=metas,
    )


def test_category_counts_apply_non_category_filters_once():
    options, metas = _platform_context()
    categories = ("all", "crawl", "download", "system", "performance", "error")
    rows = [
        {"time": "2026-06-30 10:00:00", "level": "INFO", "source": "DownloadWorker", "status_code": "DL_QUEUE"},
        {"time": "2026-06-30 10:01:00", "level": "ERROR", "source": "BiliAPI", "message": "failed"},
        {"time": "2026-06-30 10:02:00", "level": "INFO", "source": "ApplicationController", "status_code": "APP_INIT"},
    ]

    counts = log_filtering.category_counts(
        rows,
        categories,
        level="\u5168\u90e8",
        time_range="\u5168\u90e8",
        platform_id=None,
        trace_query="",
        keyword="",
        platform_options=options,
        platform_meta_by_id=metas,
    )

    assert counts["all"] == 3
    assert counts["download"] == 1
    assert counts["error"] == 1
    assert counts["system"] == 1
