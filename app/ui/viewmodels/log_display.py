from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.ui.viewmodels.log_classification import (
    classification_facts,
    derive_result_type,
    normalized_event_code,
    normalized_raw_level,
    normalized_status_code,
    result_display_text,
)
from app.ui.viewmodels.log_platforms import PlatformUiMeta, builtin_platform_metas, platform_icon_file_for_id


def stage_display_text(stage: str) -> str:
    return {
        "init": "初始化",
        "config": "配置",
        "scan": "扫描",
        "start": "启动",
        "login": "登录",
        "aggregate": "聚合",
        "expand": "展开",
        "confirm": "确认",
        "parse": "解析",
        "fetch": "获取",
        "request": "请求",
        "found": "发现",
        "emit": "提交",
        "queue": "入队",
        "dispatch": "分发",
        "prepare": "准备",
        "download": "下载",
        "merge": "合并",
        "normalize": "修正",
        "release": "释放",
        "finish": "完成",
        "performance": "性能",
        "error": "异常",
        "step": "步骤",
    }.get(stage, stage or "-")


def scope_display_text(scope: str) -> str:
    return {
        "system": "系统",
        "crawl": "采集",
        "download": "下载",
        "performance": "性能",
        "error": "异常",
    }.get(scope, scope or "-")


def resolve_item_platform_id(
    item: Mapping[str, Any],
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> str:
    builtins = builtin_platform_metas()

    explicit = str(item.get("platform_id") or "").strip().lower()
    if explicit and explicit not in {"", "all"}:
        if explicit in platform_meta_by_id or explicit in builtins:
            return explicit

    source_id = str(item.get("source_id") or "").strip().lower()
    if source_id and (source_id in platform_meta_by_id or source_id in builtins):
        return source_id

    platform_text = str(item.get("platform") or "").strip()
    lowered = platform_text.lower()
    for meta in platform_options:
        if lowered == meta.id or lowered == meta.label.lower():
            return meta.id
        if any(lowered == alias.lower() for alias in meta.aliases):
            return meta.id

    source_text = " ".join(
        str(item.get(key) or "")
        for key in (
            "source",
            "action",
            "event",
            "event_type",
            "trace_id",
            "traceId",
            "message",
            "message_summary",
            "detail",
            "source_id",
            "platform_id",
            "plugin_name",
        )
    ).lower()
    facts = classification_facts(dict(item))
    source_text = " ".join(
        [
            source_text,
            facts["source_lower"],
            facts["action_lower"],
            facts["detail_lower"],
        ]
    )
    for meta in platform_options:
        if meta.id in {"", "all"}:
            continue
        tokens = (meta.id, *meta.aliases)
        if any(token.lower() in source_text for token in tokens if token):
            return meta.id

    if platform_text in {"系统", "绯荤粺", "system"}:
        return "system"
    return ""


def platform_meta_for_id(platform_id: str, item: Mapping[str, Any], platform_meta_by_id: Mapping[str, PlatformUiMeta]) -> PlatformUiMeta:
    meta = platform_meta_by_id.get(platform_id) or builtin_platform_metas().get(platform_id)
    if meta is not None:
        return meta
    if platform_id:
        return PlatformUiMeta(platform_id, platform_id)
    fallback_label = str(item.get("platform") or "未知")
    return PlatformUiMeta("", fallback_label)


def source_display_fields(
    item: Mapping[str, Any],
    platform_id: str,
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> dict[str, str]:
    meta = platform_meta_for_id(platform_id, item, platform_meta_by_id)
    source = str(item.get("source") or "").strip()
    label = meta.label
    icon_file = platform_icon_file_for_id(platform_id, meta)

    fields: dict[str, str] = {
        "platform_id": platform_id or meta.id,
        "platform_label": label,
        "platform_icon_path": meta.icon_path or "",
        "platform_emoji": meta.emoji or "",
    }

    if icon_file:
        display_text = f"{label} · {source}" if source else label
        fields["source_display_icon_file"] = icon_file
    else:
        emoji = meta.emoji or ""
        prefix = f"{emoji} {label}".strip() if emoji else label
        display_text = f"{prefix} · {source}" if source else prefix

    fields.update(
        {
            "source_display_text": display_text,
            "source_display": display_text,
            "source_display_full": display_text,
            "source_display_align": "center",
        }
    )
    return fields


def format_platform_label(
    item: Mapping[str, Any],
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> str:
    platform_id = resolve_item_platform_id(item, platform_options, platform_meta_by_id)
    meta = platform_meta_by_id.get(platform_id) or builtin_platform_metas().get(platform_id)
    if meta is None:
        return str(item.get("platform") or "-")
    icon_file = platform_icon_file_for_id(platform_id, meta)
    if icon_file:
        return meta.label
    prefix = meta.emoji or ""
    if prefix:
        return f"{prefix} {meta.label}".strip()
    return meta.label


def decorate_log_item(
    item: Mapping[str, Any],
    *,
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
    log_scope: str,
    event_stage: str,
    scope_reason: str,
) -> dict[str, Any]:
    row = dict(item)
    platform_id = resolve_item_platform_id(row, platform_options, platform_meta_by_id)
    display_fields = source_display_fields(row, platform_id, platform_meta_by_id)
    for key, value in display_fields.items():
        row[key] = value
    if "source_display_icon_file" not in display_fields:
        row.pop("source_display_icon_file", None)

    row["message_summary_align"] = "center"

    result_type = derive_result_type(row)
    raw_level = normalized_raw_level(row)
    event_code = normalized_event_code(row)

    row["raw_level"] = raw_level
    row["result_type"] = result_type
    row["level_display"] = result_display_text(result_type, raw_level)
    row["level_display_align"] = "center"
    row["log_scope"] = log_scope
    row["event_stage"] = event_stage
    row["event_stage_display"] = stage_display_text(event_stage)
    row["status_code"] = normalized_status_code(row)
    row["event_code"] = event_code

    facts = classification_facts(row)
    row["_classification_source"] = facts["source"]
    row["_classification_action"] = facts["action"]
    row["_classification_status"] = facts["status"]
    row["_classification_legacy_category"] = facts["legacy_category"]
    row["_scope_reason"] = scope_reason
    return row
