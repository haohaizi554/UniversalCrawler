"""Crash-resilient SQLite ledger for download paths and startup maintenance."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from app.utils.runtime_paths import user_data_root


@dataclass(frozen=True)
class _RecoveryBatch:
    directories: tuple[str, ...]
    active_records: tuple[tuple[str, str], ...]
    pending_records: tuple[tuple[str, str], ...]


class DownloadRecoveryStore:
    """Persist path ownership before workers create temporary artifacts.

    Active task rows are removed immediately after success. Failed or interrupted
    tasks hand their exact output directory to a deduplicated cleanup queue. The
    queue is consumed only after startup maintenance has attempted that path,
    regardless of whether an artifact was found.
    """

    LEGACY_SWEEP_VERSION = 2

    def __init__(
        self,
        *,
        db_path: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = Path(
            db_path
            or (Path(user_data_root()) / "cache" / "download_recovery.sqlite3")
        )
        self._clock = clock
        self._init_lock = threading.RLock()
        self._initialized = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    @staticmethod
    def _normalize_directory(directory: str | os.PathLike[str]) -> str:
        raw_directory = str(directory or "").strip()
        if not raw_directory:
            raise ValueError("directory is empty")
        path = Path(raw_directory).expanduser().resolve(strict=False)
        return os.path.normcase(str(path))

    @classmethod
    def _is_within_root(cls, path: str, root: str) -> bool:
        try:
            return os.path.commonpath((path, root)) == root
        except (OSError, TypeError, ValueError):
            return False

    def register_task(
        self,
        *,
        video_id: str,
        save_directory: str | os.PathLike[str],
        source_url: str = "",
        trace_id: str = "",
        platform: str = "",
    ) -> None:
        """Commit task ownership before dispatch and return after durable commit."""
        normalized_video_id = str(video_id or "").strip()
        if not normalized_video_id:
            raise ValueError("video_id is empty")
        normalized_directory = self._normalize_directory(save_directory)
        now = float(self._clock())
        generation = uuid.uuid4().hex
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO download_task_paths(
                    video_id, save_directory, source_url, trace_id, platform, state, updated_at,
                    generation
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    save_directory = excluded.save_directory,
                    source_url = excluded.source_url,
                    trace_id = excluded.trace_id,
                    platform = excluded.platform,
                    state = 'active',
                    updated_at = excluded.updated_at,
                    generation = excluded.generation
                """,
                (
                    normalized_video_id,
                    normalized_directory,
                    str(source_url or ""),
                    str(trace_id or ""),
                    str(platform or ""),
                    now,
                    generation,
                ),
            )

    def handoff_failed_task(self, video_id: str) -> bool:
        """Move one active task to the deduplicated startup cleanup queue."""
        normalized_video_id = str(video_id or "").strip()
        if not normalized_video_id:
            return False
        generation = uuid.uuid4().hex
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_cleanup_directories(save_directory, updated_at, generation)
                SELECT save_directory, ?, ?
                FROM download_task_paths
                WHERE video_id = ?
                ON CONFLICT(save_directory) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    generation = excluded.generation
                """,
                (float(self._clock()), generation, normalized_video_id),
            )
            conn.execute(
                "DELETE FROM download_task_paths WHERE video_id = ?",
                (normalized_video_id,),
            )
            return int(cursor.rowcount or 0) > 0

    def delete_task(self, video_id: str) -> bool:
        """Delete a completed task immediately; completed rows never age out."""
        normalized_video_id = str(video_id or "").strip()
        if not normalized_video_id:
            return False
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM download_task_paths WHERE video_id = ?",
                (normalized_video_id,),
            )
            return int(cursor.rowcount or 0) > 0

    def consume_recovery_records(self, batch: _RecoveryBatch | None = None) -> int:
        """Acknowledge only records represented by the completed cleanup batch."""
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            if batch is None:
                active = conn.execute("DELETE FROM download_task_paths").rowcount or 0
                pending = conn.execute("DELETE FROM pending_cleanup_directories").rowcount or 0
                return max(0, int(active)) + max(0, int(pending))

            consumed = 0
            for video_id, generation in batch.active_records:
                cursor = conn.execute(
                    "DELETE FROM download_task_paths WHERE video_id = ? AND generation = ?",
                    (video_id, generation),
                )
                consumed += max(0, int(cursor.rowcount or 0))
            for save_directory, generation in batch.pending_records:
                cursor = conn.execute(
                    """
                    DELETE FROM pending_cleanup_directories
                    WHERE save_directory = ? AND generation = ?
                    """,
                    (save_directory, generation),
                )
                consumed += max(0, int(cursor.rowcount or 0))
            return consumed

    def task_path(self, video_id: str) -> dict[str, Any] | None:
        normalized_video_id = str(video_id or "").strip()
        if not normalized_video_id:
            return None
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT video_id, save_directory, source_url, trace_id, platform, state, updated_at
                FROM download_task_paths
                WHERE video_id = ?
                """,
                (normalized_video_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def recovery_batch(self) -> _RecoveryBatch:
        """Snapshot unresolved records so startup cleanup can acknowledge them exactly once."""
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            active_rows = list(
                conn.execute(
                    """
                    SELECT video_id, save_directory, generation, updated_at
                    FROM download_task_paths
                    """
                )
            )
            pending_rows = list(
                conn.execute(
                    """
                    SELECT save_directory, generation, updated_at
                    FROM pending_cleanup_directories
                    """
                )
            )
        ordered_entries = [
            (float(updated_at), str(save_directory), "active", str(video_id))
            for video_id, save_directory, _generation, updated_at in active_rows
        ]
        ordered_entries.extend(
            (float(updated_at), str(save_directory), "pending", str(save_directory))
            for save_directory, _generation, updated_at in pending_rows
        )
        ordered_entries.sort()
        directories = tuple(dict.fromkeys(entry[1] for entry in ordered_entries))
        return _RecoveryBatch(
            directories=directories,
            active_records=tuple(
                (str(video_id), str(generation))
                for video_id, _save_directory, generation, _updated_at in active_rows
            ),
            pending_records=tuple(
                (str(save_directory), str(generation))
                for save_directory, generation, _updated_at in pending_rows
            ),
        )

    def directories(self) -> list[str]:
        """Return only unresolved paths; no historical directory index is kept."""
        return list(self.recovery_batch().directories)

    def recovery_counts(self) -> dict[str, int]:
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            active = int(conn.execute("SELECT COUNT(*) FROM download_task_paths").fetchone()[0])
            pending = int(
                conn.execute("SELECT COUNT(*) FROM pending_cleanup_directories").fetchone()[0]
            )
        return {"active": active, "pending_cleanup": pending}

    def needs_legacy_sweep(self, directory: str | os.PathLike[str]) -> bool:
        normalized = self._normalize_directory(directory)
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT legacy_sweep_version FROM maintenance_state WHERE root = ?",
                (normalized,),
            ).fetchone()
        return row is None or int(row[0] or 0) < self.LEGACY_SWEEP_VERSION

    def prepare_legacy_sweep(self, directory: str | os.PathLike[str]) -> bool:
        """Initialize a resumable depth-bounded migration frontier for one root."""
        normalized = self._normalize_directory(directory)
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM legacy_sweep_frontier WHERE root <> ?", (normalized,))
            conn.execute("DELETE FROM maintenance_state WHERE root <> ?", (normalized,))
            row = conn.execute(
                "SELECT legacy_sweep_version FROM maintenance_state WHERE root = ?",
                (normalized,),
            ).fetchone()
            if row is not None and int(row[0] or 0) >= self.LEGACY_SWEEP_VERSION:
                return False
            conn.execute(
                """
                INSERT INTO maintenance_state(root, legacy_sweep_version, updated_at)
                VALUES (?, 0, ?)
                ON CONFLICT(root) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (normalized, float(self._clock())),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO legacy_sweep_frontier(root, path, depth, queued_at)
                VALUES (?, ?, 0, ?)
                """,
                (normalized, normalized, float(self._clock())),
            )
        return True

    def next_legacy_sweep_directory(
        self,
        directory: str | os.PathLike[str],
    ) -> tuple[str, int] | None:
        normalized = self._normalize_directory(directory)
        self._ensure_initialized()
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT path, depth
                FROM legacy_sweep_frontier
                WHERE root = ?
                ORDER BY depth ASC, path ASC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), int(row[1])

    def complete_legacy_sweep_directory(
        self,
        root: str | os.PathLike[str],
        directory: str | os.PathLike[str],
        children: Iterable[tuple[str | os.PathLike[str], int]],
    ) -> None:
        """Persist discovered children and consume one attempted frontier row."""
        normalized_root = self._normalize_directory(root)
        normalized_directory = self._normalize_directory(directory)
        if not self._is_within_root(normalized_directory, normalized_root):
            raise ValueError("legacy sweep directory escaped its root")
        normalized_children: list[tuple[str, str, int, float]] = []
        now = float(self._clock())
        for child, depth in children:
            normalized_child = self._normalize_directory(child)
            normalized_depth = int(depth)
            if normalized_depth < 0 or normalized_depth > 2:
                continue
            if not self._is_within_root(normalized_child, normalized_root):
                continue
            normalized_children.append(
                (normalized_root, normalized_child, normalized_depth, now)
            )
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            if normalized_children:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO legacy_sweep_frontier(root, path, depth, queued_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    normalized_children,
                )
            conn.execute(
                "DELETE FROM legacy_sweep_frontier WHERE root = ? AND path = ?",
                (normalized_root, normalized_directory),
            )
            remaining = int(
                conn.execute(
                    "SELECT COUNT(*) FROM legacy_sweep_frontier WHERE root = ?",
                    (normalized_root,),
                ).fetchone()[0]
            )
            if remaining == 0:
                self._mark_legacy_sweep_complete_conn(conn, normalized_root, now)

    def mark_legacy_sweep_complete(self, directory: str | os.PathLike[str]) -> None:
        normalized = self._normalize_directory(directory)
        self._ensure_initialized()
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM legacy_sweep_frontier WHERE root = ?", (normalized,))
            self._mark_legacy_sweep_complete_conn(conn, normalized, float(self._clock()))

    def _mark_legacy_sweep_complete_conn(
        self,
        conn: sqlite3.Connection,
        normalized_root: str,
        now: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO maintenance_state(root, legacy_sweep_version, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(root) DO UPDATE SET
                legacy_sweep_version = excluded.legacy_sweep_version,
                updated_at = excluded.updated_at
            """,
            (normalized_root, self.LEGACY_SWEEP_VERSION, now),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path, timeout=5.0)) as conn:
                conn.execute("PRAGMA busy_timeout = 5000")
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = FULL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS download_task_paths (
                        video_id TEXT PRIMARY KEY,
                        save_directory TEXT NOT NULL,
                        source_url TEXT NOT NULL DEFAULT '',
                        trace_id TEXT NOT NULL DEFAULT '',
                        platform TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        generation TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_download_task_paths_state_updated
                    ON download_task_paths(state, updated_at);
                    CREATE TABLE IF NOT EXISTS pending_cleanup_directories (
                        save_directory TEXT PRIMARY KEY,
                        updated_at REAL NOT NULL,
                        generation TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS maintenance_state (
                        root TEXT PRIMARY KEY,
                        legacy_sweep_version INTEGER NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS legacy_sweep_frontier (
                        root TEXT NOT NULL,
                        path TEXT NOT NULL,
                        depth INTEGER NOT NULL,
                        queued_at REAL NOT NULL,
                        PRIMARY KEY(root, path)
                    );
                    """
                )
                task_columns = {
                    str(row[1]) for row in conn.execute("PRAGMA table_info(download_task_paths)")
                }
                if "generation" not in task_columns:
                    conn.execute(
                        "ALTER TABLE download_task_paths ADD COLUMN generation TEXT NOT NULL DEFAULT ''"
                    )
                pending_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(pending_cleanup_directories)")
                }
                if "generation" not in pending_columns:
                    conn.execute(
                        """
                        ALTER TABLE pending_cleanup_directories
                        ADD COLUMN generation TEXT NOT NULL DEFAULT ''
                        """
                    )
                conn.execute(
                    """
                    UPDATE download_task_paths
                    SET generation = lower(hex(randomblob(16)))
                    WHERE generation = ''
                    """
                )
                conn.execute(
                    """
                    UPDATE pending_cleanup_directories
                    SET generation = lower(hex(randomblob(16)))
                    WHERE generation = ''
                    """
                )
                legacy_handoff_exists = conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'failed_path_handoffs'
                    """
                ).fetchone()
                if legacy_handoff_exists is not None:
                    conn.execute(
                        """
                        INSERT INTO pending_cleanup_directories(
                            save_directory, updated_at, generation
                        )
                        SELECT save_directory, MAX(updated_at), lower(hex(randomblob(16)))
                        FROM failed_path_handoffs
                        GROUP BY save_directory
                        ON CONFLICT(save_directory) DO UPDATE SET
                            updated_at = MAX(updated_at, excluded.updated_at),
                            generation = excluded.generation
                        """
                    )
                    conn.execute("DROP TABLE failed_path_handoffs")
                conn.execute("DROP TABLE IF EXISTS managed_download_directories")
                conn.commit()
            self._initialized = True
