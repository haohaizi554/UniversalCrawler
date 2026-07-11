"""Crash-resilient download path ledger tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.services.download_recovery_store import DownloadRecoveryStore


def test_store_commits_task_path_before_a_new_instance_reads_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        db_path = root / "recovery.sqlite3"
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=db_path)

        store.register_task(
            video_id="video-1",
            save_directory=save_dir,
            source_url="https://example.com/video.mp4",
            trace_id="trace-1",
            platform="bilibili",
        )

        restored = DownloadRecoveryStore(db_path=db_path)
        row = restored.task_path("video-1")
        assert row is not None
        assert row["save_directory"] == os.path.normcase(str(save_dir.resolve()))
        assert row["state"] == "active"
        assert restored.directories() == [os.path.normcase(str(save_dir.resolve()))]


def test_store_uses_wal_and_full_synchronous_durability() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        db_path = root / "recovery.sqlite3"
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=db_path)
        store.register_task(video_id="video-1", save_directory=save_dir)

        with closing(sqlite3.connect(db_path)) as conn:
            assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
            assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 2


def test_store_hands_failed_path_off_and_legacy_marker_persists() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        db_path = root / "recovery.sqlite3"
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=db_path)
        store.register_task(video_id="video-1", save_directory=save_dir)

        assert store.handoff_failed_task("video-1")
        assert store.task_path("video-1") is None
        assert store.directories() == [os.path.normcase(str(save_dir.resolve()))]
        assert store.recovery_counts() == {"active": 0, "pending_cleanup": 1}
        assert store.needs_legacy_sweep(save_dir)
        store.mark_legacy_sweep_complete(save_dir)

        restored = DownloadRecoveryStore(db_path=db_path)
        assert not restored.needs_legacy_sweep(save_dir)


def test_failed_path_is_deleted_after_startup_cleanup_attempts_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=root / "recovery.sqlite3")
        store.register_task(video_id="video-1", save_directory=save_dir)
        store.handoff_failed_task("video-1")

        assert store.consume_recovery_records() == 1
        assert store.directories() == []


def test_completed_task_is_deleted_instead_of_accumulating() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=root / "recovery.sqlite3")
        store.register_task(video_id="video-1", save_directory=save_dir)

        assert store.delete_task("video-1")
        assert store.task_path("video-1") is None
        assert store.directories() == []


def test_failed_tasks_share_one_pending_cleanup_directory_until_it_is_consumed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        save_dir = root / "downloads"
        save_dir.mkdir()
        store = DownloadRecoveryStore(db_path=root / "recovery.sqlite3")
        for video_id in ("video-1", "video-2"):
            store.register_task(video_id=video_id, save_directory=save_dir)
            assert store.handoff_failed_task(video_id)

        assert store.recovery_counts() == {"active": 0, "pending_cleanup": 1}
        assert store.directories() == [os.path.normcase(str(save_dir.resolve()))]

        assert store.consume_recovery_records() == 1
        assert store.recovery_counts() == {"active": 0, "pending_cleanup": 0}
        assert store.directories() == []


def test_legacy_sweep_frontier_survives_restart_and_is_consumed_by_use() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        child = root / "collection"
        child.mkdir()
        db_path = root / "recovery.sqlite3"
        store = DownloadRecoveryStore(db_path=db_path)

        store.prepare_legacy_sweep(root)
        assert store.next_legacy_sweep_directory(root) == (
            os.path.normcase(str(root.resolve())),
            0,
        )
        store.complete_legacy_sweep_directory(root, root, [(child, 1)])

        restored = DownloadRecoveryStore(db_path=db_path)
        assert restored.next_legacy_sweep_directory(root) == (
            os.path.normcase(str(child.resolve())),
            1,
        )
        restored.complete_legacy_sweep_directory(root, child, [])
        assert restored.next_legacy_sweep_directory(root) is None


def test_preparing_a_new_legacy_root_discards_unused_old_frontier() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        old_root = base / "old"
        new_root = base / "new"
        old_root.mkdir()
        new_root.mkdir()
        store = DownloadRecoveryStore(db_path=base / "recovery.sqlite3")

        store.prepare_legacy_sweep(old_root)
        store.prepare_legacy_sweep(new_root)

        assert store.next_legacy_sweep_directory(old_root) is None
        assert store.next_legacy_sweep_directory(new_root) == (
            os.path.normcase(str(new_root.resolve())),
            0,
        )
