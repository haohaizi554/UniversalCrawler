from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.debug_logger import debug_logger
from app.ui.viewmodels.latest_worker import LatestRequestWorker
from app.ui.viewmodels import log_filtering
from app.ui.viewmodels.log_pipeline_rules import derive_event_stage, derive_log_scope, derive_scope_reason
from app.ui.viewmodels.log_platforms import PlatformUiMeta
from app.ui.viewmodels.pagination_state import clamp_page, page_for_match, page_slice, total_pages


@dataclass(frozen=True)
class LogQueryRequest:
    sequence: int
    items: Sequence[Any]
    categories: tuple[str, ...]
    category: str
    level: str
    time_range: str
    platform_id: str | None
    trace_query: str
    keyword: str
    platform_options: tuple[PlatformUiMeta, ...]
    platform_meta_by_id: Mapping[str, PlatformUiMeta]
    page: int
    page_size: int
    selected_id: str = ""


@dataclass(frozen=True)
class LogQueryResult:
    sequence: int
    page_items: list[dict[str, Any]]
    category_counts: dict[str, int]
    total_count: int
    matched_count: int
    visible_count: int
    current_page: int
    total_pages: int
    selected_id: str
    first_trace_id: str


def stable_log_item_id(item: Mapping[str, Any], index: int) -> str:
    explicit = str(item.get("id") or "")
    if explicit:
        return explicit
    return "|".join(
        [
            str(item.get("time") or ""),
            str(item.get("trace_id") or ""),
            str(item.get("message_summary") or item.get("message") or ""),
            str(index),
        ]
    )


def query_log_items(request: LogQueryRequest) -> LogQueryResult:
    all_items = [dict(item) for item in request.items if isinstance(item, Mapping)]
    filtered_items = [
        item
        for item in all_items
        if log_filtering.matches_filters(
            item,
            category=request.category,
            level=request.level,
            time_range=request.time_range,
            platform_id=request.platform_id,
            trace_query=request.trace_query,
            keyword=request.keyword,
            platform_options=request.platform_options,
            platform_meta_by_id=request.platform_meta_by_id,
        )
    ]
    sorted_items = log_filtering.sort_log_items(filtered_items)
    current_page = int(request.page or 1)
    if request.selected_id:
        selected_page = page_for_match(
            sorted_items,
            lambda item, index: stable_log_item_id(item, index) == request.selected_id,
            request.page_size,
        )
        if selected_page is not None:
            current_page = selected_page
    current_page = clamp_page(current_page, len(sorted_items), request.page_size)
    page_items = [_with_log_pipeline_fields(item) for item in page_slice(sorted_items, current_page, request.page_size)]
    selected_id = ""
    if request.selected_id and any(
        stable_log_item_id(item, index) == request.selected_id for index, item in enumerate(sorted_items)
    ):
        selected_id = request.selected_id
    elif page_items:
        selected_id = stable_log_item_id(page_items[0], 0)

    counts = log_filtering.category_counts(
        all_items,
        request.categories,
        level=request.level,
        time_range=request.time_range,
        platform_id=request.platform_id,
        trace_query=request.trace_query,
        keyword=request.keyword,
        platform_options=request.platform_options,
        platform_meta_by_id=request.platform_meta_by_id,
    )
    first_trace_id = _first_trace_id(page_items) or _first_trace_id(sorted_items)
    return LogQueryResult(
        sequence=request.sequence,
        page_items=page_items,
        category_counts=counts,
        total_count=len(all_items),
        matched_count=len(sorted_items),
        visible_count=len(page_items),
        current_page=current_page,
        total_pages=total_pages(len(sorted_items), request.page_size),
        selected_id=selected_id,
        first_trace_id=first_trace_id,
    )


def _first_trace_id(items: Sequence[Mapping[str, Any]]) -> str:
    for item in items:
        trace_id = str(item.get("trace_id") or item.get("traceId") or "")
        if trace_id:
            return trace_id
    return ""


def _with_log_pipeline_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(item)
    scope = str(row.get("log_scope") or derive_log_scope(row) or "")
    stage = str(row.get("event_stage") or derive_event_stage(row) or "")
    row["log_scope"] = scope
    row["event_stage"] = stage
    row["_scope_reason"] = str(row.get("_scope_reason") or derive_scope_reason(row) or "")
    return row


class LogQueryWorker:
    """Latest-state-wins worker for expensive log filtering, sorting and paging."""

    def __init__(self, on_result: Callable[[LogQueryResult], None]) -> None:
        self._worker = LatestRequestWorker(
            name="log-query-worker",
            on_result=on_result,
            process=self._process,
        )

    def submit(self, request: LogQueryRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    @staticmethod
    def _process(request: LogQueryRequest) -> LogQueryResult:
        try:
            return query_log_items(request)
        except Exception as exc:
            debug_logger.log_exception(
                "LogQueryWorker",
                "query_log_items",
                exc,
                details={"sequence": request.sequence, "item_count": len(request.items)},
            )
            return LogQueryResult(
                sequence=request.sequence,
                page_items=[],
                category_counts={key: 0 for key in request.categories},
                total_count=len(request.items),
                matched_count=0,
                visible_count=0,
                current_page=1,
                total_pages=1,
                selected_id="",
                first_trace_id="",
            )
