from app.ui.viewmodels.log_detail_payloads import (
    extract_message_payload,
    format_json_text,
    parse_structured_detail_text,
    refine_description_path,
    soft_wrap_text,
)


def test_extract_message_payload_splits_description_and_windows_path():
    payload = extract_message_payload("📁 扫描目录: D:\\media\\Downloads")

    assert payload == {"description": "扫描目录", "path": "D:\\media\\Downloads"}


def test_refine_description_path_prefers_extracted_path():
    payload = refine_description_path({"description": "📁 扫描目录: D:\\media\\Downloads"})

    assert payload["description"] == "扫描目录"
    assert payload["path"] == "D:\\media\\Downloads"


def test_parse_structured_detail_text_keeps_description_status_and_details():
    payload = parse_structured_detail_text(
        "\n".join(
            [
                "说明: ✅ 下载完成",
                "状态码: DL_FINISH",
                "详情:",
                "- platform: Bilibili",
                "- file: demo.mp4",
            ]
        )
    )

    assert payload == {
        "description": "下载完成",
        "status_code": "DL_FINISH",
        "platform": "Bilibili",
        "file": "demo.mp4",
    }


def test_json_text_and_soft_wrap_are_reusable_for_detail_views():
    assert format_json_text({"a": 1}) == '{\n  "a": 1\n}'
    assert "\\\u200b" in soft_wrap_text("D:\\media")
