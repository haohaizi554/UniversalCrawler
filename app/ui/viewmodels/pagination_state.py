from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def total_pages(total_items: int, page_size: int) -> int:
    if page_size <= 0:
        return 1
    return max(1, (max(0, int(total_items)) + page_size - 1) // page_size)


def clamp_page(page: int, total_items: int, page_size: int) -> int:
    return max(1, min(int(page or 1), total_pages(total_items, page_size)))


def page_bounds(page: int, total_items: int, page_size: int) -> tuple[int, int]:
    if page_size <= 0:
        return 0, max(0, int(total_items))
    safe_page = clamp_page(page, total_items, page_size)
    start = (safe_page - 1) * page_size
    return start, min(max(0, int(total_items)), start + page_size)


def page_slice(items: Sequence[T], page: int, page_size: int) -> list[T]:
    start, end = page_bounds(page, len(items), page_size)
    return list(items[start:end])


def page_for_item(
    items: Sequence[dict[str, Any]],
    item_id: str,
    page_size: int,
    *,
    id_key: str = "id",
) -> int | None:
    if page_size <= 0:
        return 1 if any(str(item.get(id_key) or "") == str(item_id) for item in items) else None
    for index, item in enumerate(items):
        if str(item.get(id_key) or "") == str(item_id):
            return index // page_size + 1
    return None


def page_for_match(items: Sequence[T], predicate: Callable[[T, int], bool], page_size: int) -> int | None:
    if page_size <= 0:
        for index, item in enumerate(items):
            if predicate(item, index):
                return 1
        return None
    for index, item in enumerate(items):
        if predicate(item, index):
            return index // page_size + 1
    return None


def parse_page_size(value: Any, text: str = "", *, default: int = 20, all_labels: set[str] | None = None) -> int:
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

    text_value = str(text or "").strip()
    labels = all_labels or {"全部", "All"}
    if text_value in labels:
        return 0
    try:
        return int(text_value.split()[0])
    except (IndexError, ValueError):
        return int(default)
