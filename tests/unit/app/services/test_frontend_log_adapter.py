from datetime import datetime, timezone
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
                "状态码: APP_INIT",
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
    assert items[0]["level"] == "CMD"
    assert items[0]["action"] == "app init"
    assert items[0]["message_summary"] == "应用开始初始化"
    assert items[0]["status_code"] == "APP_INIT"
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

    assert item["level"] == "CMD"
    assert item["trace_id"] == "xhs_trace_1"
    assert item["platform"] == "\u5c0f\u7ea2\u4e66"
    assert item["category"] == "download"
    assert item["timestamp_ms"] > 0
    assert item["message_summary"] == "download ok"
    assert item["level_display"] == "CMD"
    assert item["source_display"]
    assert item["source_display_align"] == "center"
    assert item["message_summary_align"] == "center"


def test_enrich_log_item_turns_boundary_newlines_into_readable_single_line_summary():
    message = "\n📜 开始滚动加载列表... (点击【停止】生成清单)\n"

    item = enrich_log_item(
        {
            "time": "2026-07-18 19:18:45",
            "level": "INFO",
            "source": "kuaishou",
            "message": message,
            "message_summary": message,
        }
    )

    assert item["message"] == "📜 开始滚动加载列表... (点击【停止】生成清单)"
    assert item["message_summary"] == "📜 开始滚动加载列表... (点击【停止】生成清单)"


def test_enrich_log_item_projects_gui_detail_payload_when_raw_detail_is_empty():
    item = enrich_log_item(
        {
            "time": "2026-07-14 20:43:04",
            "level": "INFO",
            "source": "WebController",
            "platform": "System",
            "trace_id": "web-scan-1",
            "status_code": "WEB_SCAN_START",
            "message": r"Scanning directory: D:\downloads",
            "detail": "",
        }
    )

    assert item["detail_payload"] == {
        "description": "Scanning directory",
        "path": r"D:\downloads",
        "event": "WEB_SCAN_START",
        "status_code": "WEB_SCAN_START",
        "platform": "System",
        "source": "WebController",
        "trace_id": "web-scan-1",
    }


def test_enrich_log_item_converts_utc_iso_time_to_local_display():
    raw = "2026-06-29T19:32:35Z"
    expected = datetime(2026, 6, 29, 19, 32, 35, tzinfo=timezone.utc).astimezone()

    item = enrich_log_item({"time": raw, "level": "INFO", "source": "Bilibili", "message": "ok"})

    assert item["time"] == expected.strftime("%Y-%m-%d %H:%M:%S")
    assert item["timestamp_ms"] == int(expected.timestamp() * 1000)


def test_platform_and_category_helpers_are_stable_for_known_inputs():
    assert platform_from_log({"trace_id": "bilibili_trace"}) == "Bilibili"
    assert platform_from_log({"source": "missav downloader"}) == "MissAV"
    assert platform_from_log({"source": "xhs downloader"}) == "\u5c0f\u7ea2\u4e66"
    assert log_category({"level": "ERROR"}) == "error"
    assert log_category({"source": "Downloader", "message": "download started"}) == "download"
    assert parse_trace_line("- trace_id: abc-123") == "abc-123"


def test_enrich_log_item_uses_shared_gui_pipeline_semantics_for_crawl_start():
    item = enrich_log_item(
        {
            "time": "2026-07-14 20:14:24",
            "level": "INFO",
            "source": "WebController",
            "action": "start_crawl",
            "status_code": "WEB_CRAWL_START",
            "message": "Web 端启动爬虫任务",
            "detail": {
                "source_id": "bilibili",
                "active_config": {"timeout": 60, "api_workers": 8},
            },
        }
    )

    assert item["raw_level"] == "INFO"
    assert item["level_display"] == "INFO"
    assert item["result_type"] == "info"
    assert item["category"] == "crawl"
    assert item["log_scope"] == "crawl"
    assert item["event_stage"] == "start"


def test_enrich_log_item_classifies_bilibili_spider_as_crawl_not_download():
    item = enrich_log_item(
        {
            "time": "2026-07-14 20:14:24",
            "level": "INFO",
            "source": "BilibiliSpider",
            "action": "run_start",
            "status_code": "BILI_SPIDER_START",
            "message": "启动 Bilibili 爬虫任务",
        }
    )

    assert item["level_display"] == "INFO"
    assert item["category"] == "crawl"
    assert item["log_scope"] == "crawl"
    assert item["event_stage"] == "start"


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
