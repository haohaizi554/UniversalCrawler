from app.ui.viewmodels.pagination_state import (
    clamp_page,
    page_bounds,
    page_for_item,
    page_for_match,
    page_slice,
    parse_page_size,
    total_pages,
)


def test_total_pages_and_clamp_page_keep_valid_range():
    assert total_pages(0, 20) == 1
    assert total_pages(41, 20) == 3
    assert total_pages(41, 0) == 1
    assert clamp_page(-3, 41, 20) == 1
    assert clamp_page(99, 41, 20) == 3


def test_page_bounds_and_slice_support_all_items_mode():
    items = list(range(12))

    assert page_bounds(2, len(items), 5) == (5, 10)
    assert page_slice(items, 2, 5) == [5, 6, 7, 8, 9]
    assert page_bounds(3, len(items), 5) == (10, 12)
    assert page_slice(items, 1, 0) == items


def test_page_for_item_and_match_find_selected_row_page():
    items = [{"id": f"item-{index}", "title": f"Item {index}"} for index in range(9)]

    assert page_for_item(items, "item-0", 4) == 1
    assert page_for_item(items, "item-8", 4) == 3
    assert page_for_item(items, "missing", 4) is None
    assert page_for_item(items, "item-8", 0) == 1
    assert page_for_match(items, lambda item, _index: item["title"] == "Item 5", 4) == 2


def test_parse_page_size_accepts_data_text_and_all_labels():
    assert parse_page_size(50, "20 条/页") == 50
    assert parse_page_size(None, "100 条/页") == 100
    assert parse_page_size(None, "全部") == 0
    assert parse_page_size(None, "All") == 0
    assert parse_page_size("bad", "also bad", default=20) == 20
