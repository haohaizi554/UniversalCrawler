from pathlib import Path

from app.models import VideoItem
from app.services import frontend_video_adapter as adapter


def _item(**overrides):
    item_id = overrides.pop("id", "v1")
    data = {
        "title": "Demo",
        "url": "",
        "source": "bilibili",
        "status": "pending",
        "progress": 0,
        "local_path": "",
        "meta": {},
    }
    data.update(overrides)
    item = VideoItem(**data)
    item.id = item_id
    return item


def test_queue_status_keeps_frontend_status_precedence():
    item = _item(url="https://example.com/video", meta={"frontend_status": "\u89e3\u6790\u4e2d", "already_exists": True})

    assert adapter.queue_status(item, {"v1"}) == "\u89e3\u6790\u4e2d"


def test_queue_status_detects_existing_and_queued_items():
    assert adapter.queue_status(_item(meta={"already_exists": True}), set()) == "\u5df2\u5b58\u5728"
    assert adapter.queue_status(_item(url="https://example.com/video"), {"v1"}) == "\u6392\u961f\u4e2d"


def test_queue_item_preserves_frontend_contract_shape():
    item = _item(url="https://example.com/video", meta={"trace_id": "trace-1", "created_at": "2026-06-30T03:32:35"})
    row = adapter.queue_item(item, queued_ids={"v1"}, platform_label=lambda _: "Bilibili")

    assert row["platform"] == "Bilibili"
    assert row["status"] == "\u6392\u961f\u4e2d"
    assert row["subtitle"] == "2026-06-30 03:32:35"
    assert row["trace_id"] == "trace-1"
    assert row["actions"] == ["delete"]


def test_bucket_for_item_routes_active_completed_failed_and_queue():
    assert adapter.bucket_for_item(_item(status="downloading"), queued_ids=set(), active_ids=set()) == "active"
    assert adapter.bucket_for_item(_item(status="failed"), queued_ids=set(), active_ids=set()) == "failed"
    assert adapter.bucket_for_item(_item(progress=100, local_path="D:/video.mp4"), queued_ids=set(), active_ids=set()) == "completed"
    assert adapter.bucket_for_item(_item(url="https://example.com/video"), queued_ids={"v1"}, active_ids=set()) == "queue"


def test_active_item_builds_download_row_with_injected_events():
    item = _item(
        url="https://example.com/video",
        progress=40,
        local_path="D:/Downloads/demo.mp4",
        meta={
            "chunks_done": 4,
            "chunks_total": 10,
            "speed": "1.2 MB/s",
            "trace_id": "trace-active",
            "thread_count": 3,
        },
    )

    row = adapter.active_item(
        item,
        platform_label=lambda _: "Bilibili",
        current_save_dir="D:/Downloads",
        active_events=lambda *_args, **_kwargs: [{"time": "12:00:00", "message": "ok"}],
    )

    assert row["platform"] == "Bilibili"
    assert row["progress"] == 40
    assert row["save_dir"].replace("\\", "/") == "D:/Downloads"
    assert row["output_filename"] == "demo.mp4"
    assert row["chunk_progress"] == {"completed": 4, "total": 10, "percent": 40}
    assert row["thread_count"] == 3
    assert row["events"][0]["message"] == "ok"


def test_completed_formatters_are_stable():
    assert adapter.format_completed_at_table("2026-06-30 03:32:35") == "06-30 03:32"
    assert adapter.display_duration("65") == "00:01:05"
    assert adapter.display_resolution("1080p", "1080 x 1920") == "1080 x 1920"
    assert adapter.format_size(1536) == "1.5 KB"
    assert adapter.format_from_path(Path("demo.mp4")) == "MP4"
    assert adapter.content_type_from_path(Path("cover.webp")) == "image"


def test_failure_category_and_solutions_are_data_only():
    category = adapter.failure_category("403 forbidden")
    solutions = adapter.solutions_for_reason("403 forbidden")

    assert category["key"] == "link"
    assert category["label"] == "\u94fe\u63a5\u5931\u8d25"
    assert solutions[0]["title"] == "\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5"


def test_failed_item_builds_failure_row_from_injected_log_excerpt():
    item = _item(
        status="failed",
        meta={"download_error": "403 forbidden", "trace_id": "trace-failed"},
    )

    row = adapter.failed_item(
        item,
        platform_label=lambda _: "Bilibili",
        log_excerpt_items=[{"time": "12:00:00", "level": "ERROR", "message": "blocked"}],
        failed_at_fallback="2026-06-30 03:32:35",
    )

    assert row["failed_at_table"] == "06-30 03:32"
    assert row["reason_category"] == "link"
    assert row["reason_label"] == "\u94fe\u63a5\u5931\u8d25"
    assert row["trace_id"] == "trace-failed"
    assert row["log_excerpt"] == ["blocked"]
    assert row["actions"] == ["copy_diagnostics", "delete"]

