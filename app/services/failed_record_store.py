"""Async SQLite store for structured failed download records."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_data_root


@dataclass(frozen=True)
class FailedRecordQuery:
    limit: int = 100
    offset: int = 0
    platform: str = ""
    status: str = ""
    trace_query: str = ""
    keyword: str = ""
    failed_from: str = ""
    failed_to: str = ""
    order: str = "desc"


@dataclass(frozen=True)
class FailedRecordQueryResult:
    records: list[dict[str, Any]]
    total_count: int
    limit: int
    offset: int


class FailedRecordStore:
    """Persist failed rows from snapshots without blocking the UI hot path."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        clock=time.time,
        on_refresh: Callable[[int], None] | None = None,
        snapshot_limit: int = 500,
    ) -> None:
        root = Path(user_data_root()) / "cache"
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(db_path or (root / "failed_records.sqlite3"))
        self._clock = clock
        self._lock = threading.RLock()
        self._init_lock = threading.RLock()
        self._snapshot_lock = threading.RLock()
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        initial_query = FailedRecordQuery(limit=max(1, int(snapshot_limit)), offset=0)
        self._refresh_requested: FailedRecordQuery | None = None
        self._last_refresh_request = initial_query
        self._snapshot: list[dict[str, Any]] = []
        self._snapshot_total_count = 0
        self._writing = False
        self._refreshing = False
        self._shutdown = False
        self._initialized = False
        self._on_refresh = on_refresh

    @property
    def db_path(self) -> Path:
        return self._db_path

    def queue_upsert(self, records: list[Mapping[str, Any]]) -> None:
        normalized = [self._normalize_record(record) for record in records]
        normalized = [record for record in normalized if record.get("video_id")]
        if not normalized:
            return
        with self._lock:
            if self._shutdown:
                return
            for record in normalized:
                self._pending[str(record["video_id"])] = record
            self._ensure_worker_locked()
            self._event.set()

    def query(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Synchronous maintenance query; UI code should use ``records_snapshot``."""
        return self.query_records(limit=limit, offset=offset).records

    def query_records(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        platform: str = "",
        status: str = "",
        trace_query: str = "",
        keyword: str = "",
        failed_from: str = "",
        failed_to: str = "",
        order: str = "desc",
    ) -> FailedRecordQueryResult:
        query = self._normalize_query(
            FailedRecordQuery(
                limit=limit,
                offset=offset,
                platform=platform,
                status=status,
                trace_query=trace_query,
                keyword=keyword,
                failed_from=failed_from,
                failed_to=failed_to,
                order=order,
            )
        )
        records, total_count = self._query_rows(query)
        return FailedRecordQueryResult(
            records=records,
            total_count=total_count,
            limit=query.limit,
            offset=query.offset,
        )

    def set_refresh_callback(self, callback: Callable[[int], None] | None) -> None:
        with self._lock:
            self._on_refresh = callback

    def request_refresh(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        platform: str = "",
        status: str = "",
        trace_query: str = "",
        keyword: str = "",
        failed_from: str = "",
        failed_to: str = "",
        order: str = "desc",
    ) -> None:
        requested = self._normalize_query(
            FailedRecordQuery(
                limit=limit if limit is not None else self._last_refresh_request.limit,
                offset=offset,
                platform=platform,
                status=status,
                trace_query=trace_query,
                keyword=keyword,
                failed_from=failed_from,
                failed_to=failed_to,
                order=order,
            )
        )
        with self._lock:
            if self._shutdown:
                return
            self._last_refresh_request = requested
            self._refresh_requested = requested
            self._ensure_worker_locked()
            self._event.set()

    def records_snapshot(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self._snapshot_lock:
            rows = self._snapshot if limit is None else self._snapshot[: max(0, int(limit))]
            return deepcopy(rows)

    @property
    def snapshot_total_count(self) -> int:
        with self._snapshot_lock:
            return int(self._snapshot_total_count)

    def flush(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            with self._lock:
                pending = bool(self._pending)
                writing = self._writing
                refreshing = self._refreshing
                refresh_requested = self._refresh_requested is not None
            if not pending and not writing and not refreshing and not refresh_requested:
                return True
            time.sleep(0.01)
        with self._lock:
            return not self._pending and not self._writing and not self._refreshing and self._refresh_requested is None

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            self._event.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _ensure_worker_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker_loop, name="failed-record-store", daemon=True)
        self._thread.start()

    def _worker_loop(self) -> None:
        while True:
            self._event.wait()
            with self._lock:
                if self._shutdown:
                    return
                batch = list(self._pending.values())
                self._pending.clear()
                refresh_request = self._refresh_requested
                self._refresh_requested = None
                if batch and refresh_request is None:
                    refresh_request = self._last_refresh_request
                self._event.clear()
                self._writing = bool(batch)
                self._refreshing = refresh_request is not None
            if not batch and refresh_request is None:
                continue
            try:
                write_failed = False
                if batch:
                    try:
                        self._write_batch(batch)
                    except Exception as exc:
                        write_failed = True
                        debug_logger.log_exception(
                            "FailedRecordStore",
                            "write_batch",
                            exc,
                            details={"count": len(batch), "db_path": str(self._db_path)},
                        )
                if refresh_request is not None and not write_failed:
                    try:
                        self._refresh_snapshot(refresh_request)
                    except Exception as exc:
                        debug_logger.log_exception(
                            "FailedRecordStore",
                            "refresh_snapshot_unhandled",
                            exc,
                            details={
                                "query": refresh_request.__dict__,
                                "db_path": str(self._db_path),
                            },
                        )
            finally:
                with self._lock:
                    self._writing = False
                    self._refreshing = False

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS failed_records (
                        video_id TEXT PRIMARY KEY,
                        title TEXT,
                        reason TEXT,
                        failed_at TEXT,
                        status TEXT,
                        platform TEXT,
                        trace_id TEXT,
                        payload_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_failed_records_failed_at ON failed_records(failed_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_failed_records_trace_id ON failed_records(trace_id)")
                conn.commit()
            self._initialized = True

    def _query_rows(self, query: FailedRecordQuery) -> tuple[list[dict[str, Any]], int]:
        self._init_db()
        where_sql, params = self._build_where_clause(query)
        order_sql = "ASC" if query.order == "asc" else "DESC"
        rows: list[sqlite3.Row]
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM failed_records {where_sql}",
                    params,
                ).fetchone()[0]
            )
            rows = list(
                conn.execute(
                    f"""
                    SELECT video_id, title, reason, failed_at, status, platform, trace_id, payload_json, updated_at
                    FROM failed_records
                    {where_sql}
                    ORDER BY COALESCE(NULLIF(failed_at, ''), printf('%020.6f', updated_at)) {order_sql}
                    LIMIT ? OFFSET ?
                    """,
                    (*params, query.limit, query.offset),
                )
            )
        return [self._row_to_record(row) for row in rows], total_count

    def _refresh_snapshot(self, request: FailedRecordQuery) -> None:
        try:
            rows, total_count = self._query_rows(request)
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            debug_logger.log_exception(
                "FailedRecordStore",
                "refresh_snapshot",
                exc,
                details={"query": request.__dict__, "db_path": str(self._db_path)},
            )
            return
        with self._snapshot_lock:
            changed = rows != self._snapshot or total_count != self._snapshot_total_count
            self._snapshot = rows
            self._snapshot_total_count = total_count
        if not changed:
            return
        callback = self._on_refresh
        if callback is None:
            return
        try:
            callback(len(rows))
        except Exception as exc:
            debug_logger.log_exception(
                "FailedRecordStore",
                "refresh_callback",
                exc,
                details={"count": len(rows), "total_count": total_count},
            )

    def _write_batch(self, records: list[dict[str, Any]]) -> None:
        self._init_db()
        now = float(self._clock())
        payloads = [
            (
                str(record.get("video_id") or ""),
                str(record.get("title") or ""),
                str(record.get("reason") or ""),
                str(record.get("failed_at") or ""),
                str(record.get("status") or ""),
                str(record.get("platform") or ""),
                str(record.get("trace_id") or ""),
                json.dumps(record.get("payload") or record, ensure_ascii=False),
                now,
            )
            for record in records
            if record.get("video_id")
        ]
        if not payloads:
            return
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO failed_records(
                    video_id, title, reason, failed_at, status, platform, trace_id, payload_json, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title,
                    reason=excluded.reason,
                    failed_at=excluded.failed_at,
                    status=excluded.status,
                    platform=excluded.platform,
                    trace_id=excluded.trace_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                payloads,
            )
            conn.commit()

    @staticmethod
    def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
        payload = deepcopy(dict(record or {}))
        return {
            "video_id": str(payload.get("id") or payload.get("video_id") or ""),
            "title": str(payload.get("title") or ""),
            "reason": str(payload.get("reason") or payload.get("reason_label") or ""),
            "failed_at": str(payload.get("failed_at") or payload.get("failed_at_table") or ""),
            "status": str(payload.get("status") or payload.get("status_label") or ""),
            "platform": str(payload.get("platform") or payload.get("platform_label") or ""),
            "trace_id": str(payload.get("trace_id") or ""),
            "payload": payload,
        }

    @staticmethod
    def _normalize_query(query: FailedRecordQuery) -> FailedRecordQuery:
        try:
            limit = int(query.limit)
        except (TypeError, ValueError):
            limit = 100
        try:
            offset = int(query.offset)
        except (TypeError, ValueError):
            offset = 0
        order = str(query.order or "desc").lower()
        if order not in {"asc", "desc"}:
            order = "desc"
        return FailedRecordQuery(
            limit=max(1, min(limit, 5000)),
            offset=max(0, offset),
            platform=str(query.platform or "").strip(),
            status=str(query.status or "").strip(),
            trace_query=str(query.trace_query or "").strip(),
            keyword=str(query.keyword or "").strip(),
            failed_from=str(query.failed_from or "").strip(),
            failed_to=str(query.failed_to or "").strip(),
            order=order,
        )

    @staticmethod
    def _build_where_clause(query: FailedRecordQuery) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query.platform:
            clauses.append("platform = ?")
            params.append(query.platform)
        if query.status:
            clauses.append("status = ?")
            params.append(query.status)
        if query.trace_query:
            clauses.append("trace_id LIKE ?")
            params.append(f"%{query.trace_query}%")
        if query.failed_from:
            clauses.append("failed_at >= ?")
            params.append(query.failed_from)
        if query.failed_to:
            clauses.append("failed_at <= ?")
            params.append(query.failed_to)
        if query.keyword:
            like = f"%{query.keyword}%"
            clauses.append("(title LIKE ? OR reason LIKE ? OR payload_json LIKE ?)")
            params.extend([like, like, like])
        if not clauses:
            return "", ()
        return "WHERE " + " AND ".join(clauses), tuple(params)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        payload: dict[str, Any]
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        result = dict(payload)
        result.update(
            {
                "id": str(row["video_id"] or payload.get("id") or ""),
                "title": str(row["title"] or payload.get("title") or ""),
                "reason": str(row["reason"] or payload.get("reason") or ""),
                "failed_at": str(row["failed_at"] or payload.get("failed_at") or ""),
                "status": str(row["status"] or payload.get("status") or ""),
                "platform": str(row["platform"] or payload.get("platform") or ""),
                "trace_id": str(row["trace_id"] or payload.get("trace_id") or ""),
                "updated_at": float(row["updated_at"] or 0.0),
            }
        )
        return result
