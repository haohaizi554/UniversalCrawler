from __future__ import annotations

from app.ui.viewmodels.failed_page_projection import failed_log_time_display, prepare_failed_item_for_display


def test_failed_page_projection_localizes_dynamic_display_fields() -> None:
    item = {
        "id": "failed-1",
        "reason": "\u4e0b\u8f7d\u4efb\u52a1\u5931\u8d25",
        "log_excerpt_items": [
            {
                "time": "2026-07-06 18:34:48.123",
                "level": "INFO",
                "message": "Bilibili \u6d41\u8bf7\u6c42\u5efa\u7acb\u6210\u529f",
                "icon_file": "log_level_info.png",
            }
        ],
        "solutions": [
            {
                "title": "\u68c0\u67e5\u7f51\u7edc",
                "description": (
                    "\u786e\u8ba4\u4ee3\u7406\u3001DNS \u548c\u7f51\u7edc\u73af\u5883\u6b63\u5e38"
                    "\uff0c\u5fc5\u8981\u65f6\u5207\u6362\u7f51\u7edc\u540e\u91cd\u8bd5\u3002"
                ),
                "icon_file": "solution_network.png",
            }
        ],
    }

    projected = prepare_failed_item_for_display(item, language="en-US")

    assert projected["reason_detail_display"] == "Download task failed"
    assert projected["log_excerpt_display_items"][0]["time_display"] == "18:34:48"
    assert projected["log_excerpt_display_items"][0]["message_display"] == "Bilibili stream request established"
    assert projected["solutions_display"][0]["title_display"] == "Check network"
    assert (
        projected["solutions_display"][0]["description_display"]
        == "Confirm proxy, DNS, and network settings are working; switch networks if needed and retry."
    )


def test_failed_page_projection_falls_back_to_plain_log_excerpt() -> None:
    projected = prepare_failed_item_for_display(
        {"id": "failed-2", "log_excerpt": ["Download task completed"]},
        language="zh-CN",
    )

    assert projected["log_excerpt_display_items"] == [
        {
            "level": "INFO",
            "message": "Download task completed",
            "icon_file": "log_level_info.png",
            "time_display": "--:--:--",
            "message_display": "下载任务完成",
        }
    ]


def test_failed_log_time_display_is_worker_side_formatting() -> None:
    assert failed_log_time_display("2026-07-06 18:34:48.123") == "18:34:48"
    assert failed_log_time_display("") == "--:--:--"
