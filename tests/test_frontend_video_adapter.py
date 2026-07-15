from datetime import datetime, timezone
from pathlib import Path

from app.models import VideoItem
from app.services import frontend_video_adapter as adapter
from app.services.media_metadata_service import MediaMetadata


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


def test_frontend_time_formatters_convert_utc_iso_to_local_display():
    raw = "2026-06-29T19:32:35Z"
    expected = datetime(2026, 6, 29, 19, 32, 35, tzinfo=timezone.utc).astimezone()

    assert adapter.queue_subtitle({"created_at": raw}) == expected.strftime("%Y-%m-%d %H:%M:%S")
    assert adapter.format_event_clock(raw) == expected.strftime("%H:%M:%S")
    assert adapter.format_completed_at_table(raw) == expected.strftime("%m-%d %H:%M")


def test_stage_display_titles_prefer_locked_stage_snapshots():
    item = _item(
        title="Original",
        local_path="D:/Downloads/actual.mp4",
        meta={
            "ui_title_queue": "Queue Snapshot",
            "ui_title_active": "Active Snapshot",
            "ui_title_completed": "Completed Snapshot",
            "ui_title_failed": "Failed Snapshot",
            "output_filename": "active-output.mp4",
            "filename": "done-output.mp4",
        },
    )

    assert adapter.queue_item(item, queued_ids={"v1"}, platform_label=lambda _: "Bilibili")["title"] == "Queue Snapshot"
    assert adapter.active_item(
        item,
        platform_label=lambda _: "Bilibili",
        current_save_dir="D:/Downloads",
        active_events=lambda *_args, **_kwargs: [],
    )["title"] == "Active Snapshot"
    assert adapter.completed_item(
        item,
        path=Path("D:/Downloads/actual.mp4"),
        size_bytes=0,
        completed_at="2026-06-30 03:32:35",
        metadata=MediaMetadata(),
        metadata_pending=False,
        platform_label=lambda _: "Bilibili",
    )["title"] == "Completed Snapshot"
    assert adapter.failed_item(
        item,
        platform_label=lambda _: "Bilibili",
        log_excerpt_items=[],
        failed_at_fallback="2026-06-30 03:32:35",
    )["title"] == "Failed Snapshot"


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


def test_active_events_fill_derived_rows_and_reuse_cached_time():
    item = _item(
        url="https://example.com/video",
        progress=57,
        meta={
            "events": [{"message": "existing"}],
            "trace_id": "trace-active",
        },
    )
    cache = {}

    events = adapter.active_events(
        item,
        progress=57,
        chunks_done=57,
        chunks_total=100,
        speed="1.4 MB/s",
        remaining_time="00:12",
        write_status="\u7b49\u5f85\u5199\u5165",
        merge_status="\u7b49\u5f85\u5408\u5e76",
        trace_id="trace-active",
        event_time_cache=cache,
        now=lambda: datetime(2026, 6, 30, 3, 32, 35),
    )

    assert len(events) == 6
    assert events[0] == {"time": "03:32:35", "message": "existing"}
    assert events[1]["message"].startswith("\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668")
    assert "\u8fdb\u5ea6\uff1a57% (57/100)" in {event["message"] for event in events}
    assert "Trace ID\uff1atrace-active" in {event["message"] for event in events}
    assert cache[item.id] == "03:32:35"

    second = adapter.active_events(
        item,
        progress=58,
        chunks_done=58,
        chunks_total=100,
        speed="2.0 MB/s",
        remaining_time="00:08",
        write_status="\u7b49\u5f85\u5199\u5165",
        merge_status="\u7b49\u5f85\u5408\u5e76",
        trace_id="trace-active",
        event_time_cache=cache,
        now=lambda: datetime(2026, 6, 30, 3, 33, 0),
    )
    assert {event["time"] for event in second} == {"03:32:35"}


def test_active_events_preserve_existing_times_and_cap_at_six():
    item = _item(
        meta={
            "events": [
                {"time": f"12:00:0{index}", "message": f"event-{index}"}
                for index in range(7)
            ]
        }
    )

    events = adapter.active_events(
        item,
        progress=99,
        chunks_done=99,
        chunks_total=100,
        speed="1 MB/s",
        remaining_time="00:01",
        write_status="writing",
        merge_status="merging",
        trace_id="trace",
        now=lambda: datetime(2026, 6, 30, 3, 32, 35),
    )

    assert [event["message"] for event in events] == [f"event-{index}" for index in range(1, 7)]
    assert events[0]["time"] == "12:00:01"


def test_active_events_normalize_existing_utc_event_times():
    raw = "2026-06-29T19:32:35Z"
    expected = datetime(2026, 6, 29, 19, 32, 35, tzinfo=timezone.utc).astimezone().strftime("%H:%M:%S")
    item = _item(meta={"events": [{"time": raw, "message": "event-utc"}]})

    events = adapter.active_events(
        item,
        progress=1,
        chunks_done=1,
        chunks_total=100,
        speed="1 MB/s",
        remaining_time="00:59",
        write_status="writing",
        merge_status="merging",
        trace_id="trace",
    )

    assert events[0] == {"time": expected, "message": "event-utc"}


def test_completed_formatters_are_stable():
    assert adapter.format_completed_at_table("2026-06-30 03:32:35") == "06-30 03:32"
    assert adapter.display_duration("65") == "00:01:05"
    assert adapter.display_resolution("1080p", "1080 x 1920") == "1080 x 1920"
    assert adapter.format_size(1536) == "1.5 KB"
    assert adapter.format_from_path(Path("demo.mp4")) == "MP4"
    assert adapter.content_type_from_path(Path("cover.webp")) == "image"


def test_completed_item_builds_file_info_from_metadata():
    path = Path("D:/Downloads/done.mp4")
    item = _item(
        local_path=str(path),
        meta={"speed": "940.9 KB/s", "speed_bps": 940900},
    )

    row = adapter.completed_item(
        item,
        path=path,
        size_bytes=1536,
        completed_at="2026-06-30 03:32:35",
        metadata=MediaMetadata(duration="00:00:13", resolution="1080 x 1920", format="MP4", content_type="video"),
        metadata_pending=False,
        platform_label=lambda _: "Bilibili",
    )

    assert row["completed_at_table"] == "06-30 03:32"
    assert row["duration"] == "00:00:13"
    assert row["resolution"] == "1080 x 1920"
    assert row["size"] == "1.5 KB"
    assert row["filename"] == "done.mp4"
    assert row["save_dir"].replace("\\", "/") == "D:/Downloads"
    assert row["download_speed"] == "940.9 KB/s"
    assert row["content_type"] == "video"
    assert row["actions"] == ["play", "open_directory", "delete"]


def test_completed_item_marks_missing_metadata_as_pending():
    row = adapter.completed_item(
        _item(local_path="D:/Downloads/pending.mp4"),
        path=Path("D:/Downloads/pending.mp4"),
        size_bytes=0,
        completed_at="2026-06-30 03:32:35",
        metadata=MediaMetadata(),
        metadata_pending=True,
        platform_label=lambda _: "Bilibili",
    )

    assert row["duration"] == "--"
    assert row["resolution"] == "--"
    assert row["metadata_pending"] is True


def test_failure_category_and_solutions_are_data_only():
    category = adapter.failure_category("403 forbidden")
    solutions = adapter.solutions_for_reason("403 forbidden")

    assert category["key"] == "link"
    assert category["label"] == "\u94fe\u63a5\u5931\u8d25"
    assert solutions[0]["title"] == "\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5"


def test_ffmpeg_output_format_error_is_tool_failure_not_file_lock():
    reason = (
        "Bilibili 音视频合并失败: Unable to choose an output format for "
        "'video.mp4.merging'; Error opening output file: Invalid argument"
    )

    category = adapter.failure_category(reason)
    solutions = adapter.solutions_for_reason(reason)

    assert category["key"] == "tool"
    assert category["label"] == "工具异常"
    assert all(solution["title"] != "释放文件占用" for solution in solutions)


def test_failed_item_builds_failure_row_from_injected_log_excerpt():
    item = _item(
        status="failed",
        local_path="D:/Downloads/demo.mp4.downloading",
        meta={
            "download_error": "403 forbidden",
            "trace_id": "trace-failed",
            "save_directory": "D:/Downloads",
        },
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
    assert row["save_directory"] == "D:/Downloads"
    assert row["local_path"] == "D:/Downloads/demo.mp4.downloading"
    assert row["log_excerpt"] == ["blocked"]
    assert row["actions"] == ["copy_diagnostics", "delete"]

