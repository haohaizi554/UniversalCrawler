from pathlib import Path

from app.models import VideoItem
from app.services.frontend_log_adapter import (
    build_log_excerpt_index,
    enrich_log_item,
    failed_log_excerpt_items,
    log_category,
    parse_debug_log_file,
    parse_trace_line,
    platform_from_log,
)


def test_parse_debug_log_file_reads_entries_trace_and_message(tmp_path):
    log_file = Path(tmp_path) / "debug.log"
    log_file.write_text(
        "\n".join(
            [
                "[2026-06-30 10:00:00] [COMMAND] ApplicationController / app init",
                "说明: 应用开始初始化",
                "Trace ID: trace-app",
                "[2026-06-30 10:00:01] [ERROR] Downloader / failed",
                "说明: download failed with 403",
                "trace_id: trace-download",
            ]
        ),
        encoding="utf-8",
    )

    items = parse_debug_log_file(log_file, limit=10)

    assert len(items) == 2
    assert items[0]["level"] == "INFO"
    assert items[0]["message_summary"] == "应用开始初始化"
    assert items[0]["trace_id"] == "trace-app"
    assert items[1]["level"] == "ERROR"
    assert items[1]["message"] == "download failed with 403"
    assert items[1]["trace_id"] == "trace-download"


def test_parse_debug_log_file_applies_tail_limit(tmp_path):
    log_file = Path(tmp_path) / "debug.log"
    log_file.write_text(
        "\n".join(f"[2026-06-30 10:00:{index:02d}] [INFO] Test / log-{index}" for index in range(5)),
        encoding="utf-8",
    )

    items = parse_debug_log_file(log_file, limit=2)

    assert [item["message_summary"] for item in items] == ["log-3", "log-4"]


def test_enrich_log_item_adds_frontend_fields():
    item = enrich_log_item(
        {
            "time": "2026-06-30 10:00:00",
            "level": "COMMAND",
            "source": "xiaohongshu downloader",
            "detail": "Trace ID: xhs_trace_1",
            "message": "download ok",
        }
    )

    assert item["level"] == "INFO"
    assert item["trace_id"] == "xhs_trace_1"
    assert item["platform"] == "\u5c0f\u7ea2\u4e66"
    assert item["category"] == "download"
    assert item["timestamp_ms"] > 0
    assert item["message_summary"] == "download ok"


def test_platform_and_category_helpers_are_stable_for_known_inputs():
    assert platform_from_log({"trace_id": "bilibili_trace"}) == "Bilibili"
    assert platform_from_log({"source": "missav downloader"}) == "MissAV"
    assert platform_from_log({"source": "xhs downloader"}) == "\u5c0f\u7ea2\u4e66"
    assert log_category({"level": "ERROR"}) == "error"
    assert log_category({"source": "Downloader", "message": "download started"}) == "download"
    assert parse_trace_line("- trace_id: abc-123") == "abc-123"


def test_log_excerpt_index_and_failed_items_match_trace_first():
    logs = [
        {"time": "2026-06-30 10:00:00", "level": "ERROR", "source": "Downloader", "trace_id": "trace-a", "message": "line-1"},
        {"time": "2026-06-30 10:00:01", "level": "WARN", "source": "Downloader", "trace_id": "trace-a", "message": "line-2"},
    ]
    index = build_log_excerpt_index(logs)
    item = VideoItem(url="https://example.com", title="failed", source="douyin")
    item.meta["trace_id"] = "trace-a"

    entries = failed_log_excerpt_items(
        item,
        trace_id="trace-a",
        index=index,
        platform_label=lambda video: video.source,
        trace_id_for_item=lambda video: video.meta.get("trace_id", ""),
    )

    assert [entry["message"] for entry in entries] == ["line-1", "line-2"]
    assert entries[0]["icon_file"] == "log_level_error.png"
    assert entries[1]["icon_file"] == "log_level_warn.png"


def test_failed_items_fall_back_to_recent_error_when_trace_is_missing():
    logs = [
        {"time": "2026-06-30 10:00:00", "level": "INFO", "source": "Downloader", "trace_id": "", "message": "started"},
        {"time": "2026-06-30 10:00:01", "level": "ERROR", "source": "Downloader", "trace_id": "", "message": "recent failure"},
    ]
    index = build_log_excerpt_index(logs)
    item = VideoItem(url="https://example.com", title="failed", source="douyin")

    entries = failed_log_excerpt_items(
        item,
        trace_id="",
        index=index,
        platform_label=lambda video: video.source,
        trace_id_for_item=lambda video: video.meta.get("trace_id", ""),
    )

    assert [entry["message"] for entry in entries] == ["recent failure"]
