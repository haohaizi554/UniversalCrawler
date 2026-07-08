from app.ui.viewmodels.list_page_worker import ListPageRequest, build_list_page_result


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
