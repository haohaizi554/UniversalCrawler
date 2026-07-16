from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.debug_logger import debug_logger
from shared.localization import normalize_language, tr
from app.ui.viewmodels import log_filtering
from app.ui.viewmodels.latest_worker import LatestRequestWorker
from shared.log_classification import cache_classification_facts, drop_classification_facts
from shared.log_display import decorate_log_item
from shared.log_i18n import localize_log_text
from shared.log_pipeline_rules import derive_event_stage, derive_log_scope, derive_scope_reason
from shared.log_platforms import PlatformUiMeta
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
    language: str = "zh-CN"
    selected_id: str = ""
    selected_id_moves_page: bool = True


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
    """为没有显式 id 的旧日志构造稳定行 ID。"""

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
    """在后台完成日志分类缓存、筛选、排序、分页和本地化装饰。"""

    all_items = [_prepare_query_row(item) for item in request.items if isinstance(item, Mapping)]
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
    if request.selected_id and request.selected_id_moves_page:
        # 详情面板选中某条日志时，筛选/刷新后优先翻到该日志所在页。
        selected_page = page_for_match(
            sorted_items,
            lambda item, index: stable_log_item_id(item, index) == request.selected_id,
            request.page_size,
        )
        if selected_page is not None:
            current_page = selected_page
    current_page = clamp_page(current_page, len(sorted_items), request.page_size)
    page_rows = [
        _with_log_pipeline_fields(item)
        for item in page_slice(sorted_items, current_page, request.page_size)
    ]
    selected_id = ""
    if request.selected_id and any(
        stable_log_item_id(item, index) == request.selected_id for index, item in enumerate(page_rows)
    ):
        selected_id = request.selected_id
    elif page_rows:
        selected_id = stable_log_item_id(page_rows[0], 0)
    page_items = [_decorate_log_row(item, request) for item in page_rows]

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


def _prepare_query_row(item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(item)
    # 分类事实缓存只存在于 worker 临时行上，最终回传前会移除，避免污染快照。
    cache_classification_facts(row)
    return row


def _with_log_pipeline_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(item)
    scope = str(row.get("log_scope") or derive_log_scope(row) or "")
    stage = str(row.get("event_stage") or derive_event_stage(row) or "")
    row["log_scope"] = scope
    row["event_stage"] = stage
    row["_scope_reason"] = str(row.get("_scope_reason") or derive_scope_reason(row) or "")
    return row


def _translate_platform_display(
    text: object,
    *,
    language: str,
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> str:
    translated = str(text or "")
    for meta in platform_meta_by_id.values():
        if meta.label:
            translated = translated.replace(meta.label, tr(meta.label, language))
    return tr(translated, language)


def _decorate_log_row(item: Mapping[str, Any], request: LogQueryRequest) -> dict[str, Any]:
    language = normalize_language(request.language)
    row = decorate_log_item(
        item,
        platform_options=request.platform_options,
        platform_meta_by_id=request.platform_meta_by_id,
        log_scope=str(item.get("log_scope") or ""),
        event_stage=str(item.get("event_stage") or ""),
        scope_reason=str(item.get("_scope_reason") or ""),
    )
    for key in ("platform_label", "source_display", "source_display_text", "source_display_full"):
        if row.get(key):
            translated = _translate_platform_display(
                row[key],
                language=language,
                platform_meta_by_id=request.platform_meta_by_id,
            )
            row[key] = localize_log_text(translated, language)
    if row.get("event_stage_display"):
        row["event_stage_display"] = tr(row["event_stage_display"], language)
    for key in ("message", "message_summary"):
        if row.get(key):
            row[key] = localize_log_text(row[key], language)
    return drop_classification_facts(row)


class LogQueryWorker:
    """以最新状态为准，处理高开销的日志筛选、排序与分页。"""

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
