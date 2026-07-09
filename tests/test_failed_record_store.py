from __future__ import annotations

from app.services.failed_record_store import FailedRecordStore


def test_failed_record_store_persists_queued_records(tmp_path):
    store = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    try:
        store.queue_upsert(
            [
                {
                    "id": "video-1",
                    "title": "broken",
                    "reason": "network",
                    "failed_at": "2026-07-06 10:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-1",
                }
            ]
        )

        assert store.flush(timeout=2)
        rows = store.query(limit=10)
    finally:
        store.shutdown()

    assert len(rows) == 1
    assert rows[0]["id"] == "video-1"
    assert rows[0]["title"] == "broken"
    assert rows[0]["reason"] == "network"
    assert rows[0]["trace_id"] == "trace-1"


def test_failed_record_store_refreshes_memory_snapshot_in_worker(tmp_path):
    # records_snapshot() 暴露给 UI 热路径，必须返回副本；外部改动不能污染
    # worker 线程维护的内存快照。
    refreshed_counts: list[int] = []
    store = FailedRecordStore(
        db_path=tmp_path / "failed.sqlite3",
        on_refresh=refreshed_counts.append,
    )
    try:
        store.queue_upsert(
            [
                {
                    "id": "video-2",
                    "title": "snapshot row",
                    "reason": "timeout",
                    "failed_at": "2026-07-06 11:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-2",
                }
            ]
        )

        assert store.flush(timeout=2)
        snapshot = store.records_snapshot()
        snapshot[0]["title"] = "mutated outside"
        snapshot_after_mutation = store.records_snapshot()
    finally:
        store.shutdown()

    assert refreshed_counts[-1] == 1
    assert snapshot[0]["id"] == "video-2"
    assert snapshot_after_mutation[0]["title"] == "snapshot row"


def test_failed_record_store_query_records_uses_sql_filters_and_counts(tmp_path):
    store = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    try:
        store.queue_upsert(
            [
                {
                    "id": "bili-old",
                    "title": "old timeout",
                    "reason": "network timeout",
                    "failed_at": "2026-07-06 09:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-old",
                },
                {
                    "id": "bili-new",
                    "title": "new timeout",
                    "reason": "network timeout",
                    "failed_at": "2026-07-06 10:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-new",
                },
                {
                    "id": "douyin-row",
                    "title": "unrelated",
                    "reason": "auth",
                    "failed_at": "2026-07-06 11:00:00",
                    "status": "Failed",
                    "platform": "Douyin",
                    "trace_id": "trace-dy",
                },
            ]
        )

        assert store.flush(timeout=2)
        page = store.query_records(
            limit=1,
            offset=0,
            platform="Bilibili",
            keyword="timeout",
            failed_from="2026-07-06 09:30:00",
        )
    finally:
        store.shutdown()

    assert page.total_count == 1
    assert page.limit == 1
    assert page.offset == 0
    assert [row["id"] for row in page.records] == ["bili-new"]


def test_failed_record_store_worker_refresh_accepts_structured_query(tmp_path):
    # request_refresh 走后台 worker 查询 SQLite；这里覆盖平台和 trace 条件能
    # 防止 UI 重新退回同步 query_records。
    store = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    try:
        store.queue_upsert(
            [
                {
                    "id": "trace-a",
                    "title": "first",
                    "reason": "network",
                    "failed_at": "2026-07-06 08:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "bili-trace-a",
                },
                {
                    "id": "trace-b",
                    "title": "second",
                    "reason": "network",
                    "failed_at": "2026-07-06 08:01:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "bili-trace-b",
                },
                {
                    "id": "trace-c",
                    "title": "third",
                    "reason": "network",
                    "failed_at": "2026-07-06 08:02:00",
                    "status": "Failed",
                    "platform": "MissAV",
                    "trace_id": "missav-trace-c",
                },
            ]
        )

        assert store.flush(timeout=2)
        store.request_refresh(limit=10, platform="Bilibili", trace_query="trace")
        assert store.flush(timeout=2)
        snapshot = store.records_snapshot()
        total_count = store.snapshot_total_count
    finally:
        store.shutdown()

    assert total_count == 2
    assert [row["id"] for row in snapshot] == ["trace-b", "trace-a"]


def test_failed_record_store_worker_resets_state_after_unexpected_write_error(tmp_path):
    # 写入异常后 _writing/_refreshing 必须复位，否则下一次失败记录会被永久
    # 卡在 pending 队列里。
    store = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    original_write_batch = store._write_batch
    calls: list[list[dict]] = []

    def broken_write_batch(records: list[dict]) -> None:
        calls.append(records)
        raise TypeError("simulated bad payload")

    try:
        store._write_batch = broken_write_batch  # type: ignore[method-assign]
        store.queue_upsert(
            [
                {
                    "id": "video-bad",
                    "title": "bad row",
                    "reason": "bad payload",
                    "failed_at": "2026-07-06 12:00:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-bad",
                }
            ]
        )

        assert store.flush(timeout=2)
        assert calls
        with store._lock:
            assert not store._writing
            assert not store._refreshing

        store._write_batch = original_write_batch  # type: ignore[method-assign]
        store.queue_upsert(
            [
                {
                    "id": "video-good",
                    "title": "good row",
                    "reason": "recovered",
                    "failed_at": "2026-07-06 12:01:00",
                    "status": "Failed",
                    "platform": "Bilibili",
                    "trace_id": "trace-good",
                }
            ]
        )

        assert store.flush(timeout=2)
        rows = store.query(limit=10)
    finally:
        store.shutdown()

    assert [row["id"] for row in rows] == ["video-good"]
