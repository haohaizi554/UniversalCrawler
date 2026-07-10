from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.debug_logger import debug_logger
from app.ui.viewmodels.latest_worker import LatestRequestWorker
from app.ui.viewmodels.pagination_state import clamp_page, page_for_match, page_slice, total_pages


@dataclass(frozen=True)
class ListPageRequest:
    sequence: int
    items: Sequence[Any]
    page: int
    page_size: int
    selected_id: str = ""
    recent_count: int = 0
    paginate: bool = True
    select_first: bool = False
    selected_id_moves_page: bool = True
    item_transformer: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(frozen=True)
class ListPageResult:
    sequence: int
    items: list[dict[str, Any]]
    page_items: list[dict[str, Any]]
    recent_items: list[dict[str, Any]]
    id_order: tuple[str, ...]
    items_by_id: dict[str, dict[str, Any]]
    selected_id: str
    total_count: int
    current_page: int
    total_pages: int


def item_stable_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or "")


def preferred_visible_selection(
    current_id: str,
    result_id: str,
    visible_items: Sequence[Mapping[str, Any]],
) -> str:
    """Keep a newer UI selection when a background list result arrives."""
    visible_ids = {item_stable_id(item) for item in visible_items}
    for candidate in (str(current_id or ""), str(result_id or "")):
        if candidate and candidate in visible_ids:
            return candidate
    return ""


def build_list_page_result(request: ListPageRequest) -> ListPageResult:
    """把原始列表转换为 UI 可直接渲染的一页结果。

    分页、选中项跨页定位和 item_transformer 都放到 worker 里做，页面层
    只负责 patch table，避免大列表刷新卡住 Qt 主线程。
    """

    items: list[dict[str, Any]] = []
    for item in request.items:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        transformer = request.item_transformer
        if transformer is not None:
            transformed = transformer(row)
            if isinstance(transformed, Mapping):
                row = dict(transformed)
        items.append(row)
    id_order = tuple(item_stable_id(item) for item in items if item_stable_id(item))
    items_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = item_stable_id(item)
        if item_id:
            items_by_id[item_id] = item
    page_size = max(0, int(request.page_size or 0))
    current_page = max(1, int(request.page or 1))

    selected_id = str(request.selected_id or "")
    selected_is_valid = bool(selected_id and selected_id in set(id_order))
    if selected_is_valid and request.selected_id_moves_page and request.paginate and page_size > 0:
        # 删除/刷新后仍保留选中项时，自动跳到它所在页；否则用户会看到
        # 详情存在但表格当前页没有对应行的错位状态。
        selected_page = page_for_match(items, lambda item, _index: item_stable_id(item) == selected_id, page_size)
        if selected_page is not None:
            current_page = selected_page

    if request.paginate and page_size > 0:
        current_page = clamp_page(current_page, len(items), page_size)
        page_items = page_slice(items, current_page, page_size)
        resolved_total_pages = total_pages(len(items), page_size)
    else:
        current_page = 1
        page_items = list(items)
        resolved_total_pages = 1

    if selected_is_valid:
        resolved_selected_id = selected_id
    elif request.select_first and page_items:
        resolved_selected_id = item_stable_id(page_items[0])
    else:
        resolved_selected_id = ""

    recent_count = max(0, int(request.recent_count or 0))
    recent_items = items[-recent_count:] if recent_count else []
    return ListPageResult(
        sequence=request.sequence,
        items=items,
        page_items=page_items,
        recent_items=recent_items,
        id_order=id_order,
        items_by_id=items_by_id,
        selected_id=resolved_selected_id,
        total_count=len(items),
        current_page=current_page,
        total_pages=resolved_total_pages,
    )


class ListPageWorker:
    """列表分页 worker；只回传最新请求结果。"""

    def __init__(self, on_result: Callable[[ListPageResult], None]) -> None:
        self._worker = LatestRequestWorker(
            name="list-page-worker",
            on_result=on_result,
            process=self._process,
        )

    def submit(self, request: ListPageRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    @staticmethod
    def _process(request: ListPageRequest) -> ListPageResult:
        try:
            return build_list_page_result(request)
        except Exception as exc:
            debug_logger.log_exception(
                "ListPageWorker",
                "build_list_page_result",
                exc,
                details={"sequence": request.sequence, "item_count": len(request.items)},
            )
            return ListPageResult(
                sequence=request.sequence,
                items=[],
                page_items=[],
                recent_items=[],
                id_order=(),
                items_by_id={},
                selected_id="",
                total_count=0,
                current_page=1,
                total_pages=1,
            )
