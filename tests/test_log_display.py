from shared.log_display import (
    decorate_log_item,
    format_platform_label,
    resolve_item_platform_id,
    scope_display_text,
    stage_display_text,
)
from shared.log_platforms import builtin_platform_metas


def _platform_context():
    metas = builtin_platform_metas()
    return list(metas.values()), metas


def test_resolve_platform_id_uses_explicit_id_and_alias_text():
    options, metas = _platform_context()

    assert resolve_item_platform_id({"platform_id": "bilibili"}, options, metas) == "bilibili"
    assert resolve_item_platform_id({"source": "BiliAPI", "message": "ok"}, options, metas) == "bilibili"
    assert resolve_item_platform_id({"platform": "系统"}, options, metas) == "system"


def test_format_platform_label_keeps_known_platform_label():
    options, metas = _platform_context()

    assert format_platform_label({"source": "BiliAPI"}, options, metas) == "Bilibili"
    assert format_platform_label({"platform": "unknown"}, options, metas) == "unknown"


def test_display_text_helpers_are_stable_for_known_and_unknown_values():
    assert stage_display_text("download") == "下载"
    assert stage_display_text("custom") == "custom"
    assert scope_display_text("performance") == "性能"
    assert scope_display_text("") == "-"


def test_decorate_log_item_adds_table_display_fields_without_ui_dependencies():
    options, metas = _platform_context()

    row = decorate_log_item(
        {"level": "ERROR", "source": "BiliAPI", "message": "B站下载失败"},
        platform_options=options,
        platform_meta_by_id=metas,
        log_scope="error",
        event_stage="error",
        scope_reason="level",
    )

    assert row["platform_id"] == "bilibili"
    assert row["platform_label"] == "Bilibili"
    assert row["level_display"] == "ERROR"
    assert row["level_display_align"] == "center"
    assert row["source_display_align"] == "center"
    assert row["message_summary_align"] == "center"
    assert row["log_scope"] == "error"
    assert row["event_stage_display"] == "异常"
    assert row["_scope_reason"] == "level"
