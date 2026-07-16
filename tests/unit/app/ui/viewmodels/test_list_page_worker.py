from app.ui.viewmodels.list_page_worker import (
    ListPageRequest,
    build_list_page_result,
    preferred_visible_selection,
    remove_list_item_optimistically,
)


def _rows(count: int) -> list[dict[str, str]]:
    return [{"id": f"item-{index}", "title": f"Item {index}"} for index in range(count)]


def test_list_page_worker_slices_and_keeps_recent_items():
    result = build_list_page_result(
        ListPageRequest(
            sequence=1,
            items=_rows(25),
            page=2,
            page_size=20,
            recent_count=3,
        )
    )

    assert result.current_page == 2
    assert result.total_pages == 2
    assert result.total_count == 25
    assert [item["id"] for item in result.page_items] == [f"item-{index}" for index in range(20, 25)]
    assert [item["id"] for item in result.recent_items] == ["item-22", "item-23", "item-24"]


def test_list_page_worker_can_select_across_pages_when_requested():
    result = build_list_page_result(
        ListPageRequest(
            sequence=1,
            items=_rows(25),
            page=2,
            page_size=20,
            selected_id="item-3",
            selected_id_moves_page=True,
        )
    )

    assert result.current_page == 1
    assert result.selected_id == "item-3"


def test_list_page_worker_keeps_manual_page_when_selection_should_not_drive_page():
    result = build_list_page_result(
        ListPageRequest(
            sequence=1,
            items=_rows(25),
            page=2,
            page_size=20,
            selected_id="item-3",
            selected_id_moves_page=False,
        )
    )

    assert result.current_page == 2
    assert result.selected_id == "item-3"
    assert [item["id"] for item in result.page_items] == [f"item-{index}" for index in range(20, 25)]


def test_preferred_visible_selection_preserves_newer_user_choice():
    visible = _rows(3)

    selected = preferred_visible_selection("item-2", "item-0", visible)

    assert selected == "item-2"


def test_preferred_visible_selection_falls_back_when_current_choice_disappears():
    visible = _rows(2)

    selected = preferred_visible_selection("item-9", "item-1", visible)

    assert selected == "item-1"


def test_optimistic_removal_clamps_empty_last_page_and_selects_previous_item():
    result = remove_list_item_optimistically(_rows(21), "item-20", page=2, page_size=20)

    assert result is not None
    assert result.current_page == 1
    assert result.total_pages == 1
    assert result.selected_id == "item-19"
    assert [item["id"] for item in result.page_items][-1] == "item-19"
