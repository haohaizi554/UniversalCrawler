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


def test_failed_record_store_worker_resets_state_after_unexpected_write_error(tmp_path):
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
