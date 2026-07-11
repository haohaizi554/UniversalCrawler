"""失败下载记录的异步 SQLite 存储，供失败列表分页和筛选使用。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

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
    """后台批量写入失败记录，并维护一份前端可直接读取的快照。"""

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
        self._prune_retention_days: int | None = None
        self._last_refresh_request = initial_query
        self._snapshot: list[dict[str, Any]] = []
        self._snapshot_total_count = 0
        self._writing = False
        self._refreshing = False
        self._pruning = False
        self._shutdown = False
        self._initialized = False
        self._on_refresh = on_refresh

    @property
    def db_path(self) -> Path:
        return self._db_path

    def queue_upsert(self, records: list[Mapping[str, Any]]) -> None:
        """合并同 video_id 的待写入记录，避免失败列表刷新时重复写库。"""
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
        """请求后台刷新快照；查询参数会覆盖上一次失败列表筛选条件。"""
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

    def request_prune(self, retention_days: int) -> None:
        """Request background cleanup for expired failed records and refresh the snapshot."""
        days = self._normalize_retention_days(retention_days)
        with self._lock:
            if self._shutdown:
                return
            self._prune_retention_days = days
            self._refresh_requested = self._last_refresh_request
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
        """测试和关闭路径使用：等待待写入与刷新任务清空。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            with self._lock:
                pending = bool(self._pending)
                writing = self._writing
                refreshing = self._refreshing
                pruning = self._pruning
                refresh_requested = self._refresh_requested is not None
                prune_requested = self._prune_retention_days is not None
            if not pending and not writing and not refreshing and not pruning and not refresh_requested and not prune_requested:
                return True
            time.sleep(0.01)
        with self._lock:
            return (
                not self._pending
                and not self._writing
                and not self._refreshing
                and not self._pruning
                and self._refresh_requested is None
                and self._prune_retention_days is None
            )

    def record_by_id(self, video_id: str) -> dict[str, Any] | None:
        normalized_id = str(video_id or "").strip()
        if not normalized_id:
            return None
        self._init_db()
        with self._open_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT video_id, title, reason, failed_at, status, platform, trace_id, payload_json, updated_at
                FROM failed_records
                WHERE video_id = ?
                LIMIT 1
                """,
                (normalized_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def delete_record(self, video_id: str) -> bool:
        normalized_id = str(video_id or "").strip()
        if not normalized_id:
            return False
        self._init_db()
        with self._open_connection() as conn:
            cursor = conn.execute("DELETE FROM failed_records WHERE video_id = ?", (normalized_id,))
            conn.commit()
            deleted = int(cursor.rowcount or 0) > 0
        self._refresh_after_mutation()
        return deleted

    def clear_records(self) -> int:
        self._init_db()
        with self._open_connection() as conn:
            cursor = conn.execute("DELETE FROM failed_records")
            conn.commit()
            deleted_count = max(0, int(cursor.rowcount or 0))
        self._refresh_after_mutation()
        return deleted_count

    def prune_expired(self, retention_days: int) -> int:
        days = self._normalize_retention_days(retention_days)
        cutoff_dt = datetime.now() - timedelta(days=days)
        cutoff_text = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        cutoff_ts = cutoff_dt.timestamp()
        self._init_db()
        with self._open_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM failed_records
                WHERE
                    (length(COALESCE(failed_at, '')) >= 19 AND failed_at < ?)
                    OR (length(COALESCE(failed_at, '')) < 19 AND updated_at < ?)
                """,
                (cutoff_text, cutoff_ts),
            )
            conn.commit()
            deleted_count = max(0, int(cursor.rowcount or 0))
        if deleted_count:
            self._refresh_after_mutation()
        return deleted_count

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
        """串行处理写入和刷新，避免 SQLite 写锁与 UI 查询互相打架。"""
        while True:
            self._event.wait()
            with self._lock:
                if self._shutdown:
                    return
                batch = list(self._pending.values())
                self._pending.clear()
                refresh_request = self._refresh_requested
                self._refresh_requested = None
                prune_retention_days = self._prune_retention_days
                self._prune_retention_days = None
                if batch and refresh_request is None:
                    refresh_request = self._last_refresh_request
                if prune_retention_days is not None and refresh_request is None:
                    refresh_request = self._last_refresh_request
                self._event.clear()
                self._writing = bool(batch)
                self._pruning = prune_retention_days is not None
                self._refreshing = refresh_request is not None
            if not batch and prune_retention_days is None and refresh_request is None:
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
                if prune_retention_days is not None:
                    try:
                        deleted_count = self.prune_expired(prune_retention_days)
                        if deleted_count:
                            debug_logger.log(
                                "FailedRecordStore",
                                "failed_record_prune",
                                message=f"Pruned {deleted_count} expired failed records",
                                details={"count": deleted_count, "retention_days": prune_retention_days},
                            )
                    except Exception as exc:
                        debug_logger.log_exception(
                            "FailedRecordStore",
                            "prune_expired",
                            exc,
                            details={"retention_days": prune_retention_days, "db_path": str(self._db_path)},
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
                    self._pruning = False

    @contextmanager
    def _open_connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._db_path, timeout=5.0)) as conn:
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA synchronous = FULL")
            yield conn

    def _init_db(self) -> None:
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
        with self._open_connection() as conn:
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
        """根据最近一次查询刷新内存快照，并只在内容变化时通知前端。"""
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
        """用 upsert 写入失败记录，保留完整 payload_json 供详情面板展示。"""
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
        with self._open_connection() as conn:
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
        """把不同前端投影字段统一到失败记录表字段。"""
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
    def _normalize_retention_days(value: Any) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = 7
        return max(1, min(days, 365))

    def _refresh_after_mutation(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._refresh_requested = self._last_refresh_request
            self._ensure_worker_locked()
            self._event.set()

    @staticmethod
    def _build_where_clause(query: FailedRecordQuery) -> tuple[str, tuple[Any, ...]]:
        """按筛选项构造参数化 WHERE，避免拼接用户输入到 SQL。"""
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
        """把数据库行还原成前端记录；表字段覆盖旧 payload 中的派生值。"""
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
