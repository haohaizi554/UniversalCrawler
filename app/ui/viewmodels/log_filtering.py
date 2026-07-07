from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from app.ui.viewmodels.log_classification import (
    classification_facts,
    derive_result_type,
    normalized_raw_level,
    result_display_text,
)
from app.ui.viewmodels.log_display import resolve_item_platform_id
from app.ui.viewmodels.log_pipeline_rules import derive_event_stage, derive_log_scope
from app.ui.viewmodels.log_platforms import PlatformUiMeta, builtin_platform_metas


ALL_LABELS = {"", "all", "\u5168\u90e8"}
TIME_RANGE_MINUTES = {
    "\u8fd1 30 \u5206\u949f": 30,
    "\u8fd1 1 \u5c0f\u65f6": 60,
    "\u8fd1 24 \u5c0f\u65f6": 24 * 60,
}


def item_datetime(item: Mapping[str, Any]) -> datetime | None:
    text = str(item.get("time") or "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def sort_log_items(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(items))

    def sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[datetime, int]:
        index, item = pair
        timestamp = item_datetime(item) or datetime.min
        return timestamp, index

    return [item for _, item in sorted(indexed, key=sort_key, reverse=True)]


def matches_category(item: Mapping[str, Any], category: str) -> bool:
    if str(category or "").strip().lower() in ALL_LABELS:
        return True
    return derive_log_scope(dict(item)) == category


def matches_platform(
    item: Mapping[str, Any],
    platform_id: str | None,
    *,
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> bool:
    platform_id = str(platform_id or "").strip().lower()
    if not platform_id or platform_id == "all":
        return True

    row = dict(item)
    resolved = resolve_item_platform_id(row, platform_options, platform_meta_by_id)
    if resolved:
        return resolved == platform_id

    meta = platform_meta_by_id.get(platform_id) or builtin_platform_metas().get(platform_id)
    tokens: set[str] = {platform_id.lower()}
    if meta is not None:
        tokens.add(meta.id.lower())
        tokens.add(meta.label.lower())
        tokens.update(alias.lower() for alias in meta.aliases)

    facts = classification_facts(row)
    text = " ".join(
        [
            facts["platform_lower"],
            facts["source_lower"],
            facts["action_lower"],
            facts["message_lower"],
            facts["detail_lower"],
            str(row.get("source_id") or "").lower(),
            str(row.get("platform_id") or "").lower(),
            str(row.get("plugin_name") or "").lower(),
            str(row.get("trace_id") or "").lower(),
            str(row.get("traceId") or "").lower(),
        ]
    )

    return any(token and token in text for token in tokens if len(token) > 1)


def matches_time_range(item: Mapping[str, Any], time_range: str, *, now: datetime | None = None) -> bool:
    minutes = TIME_RANGE_MINUTES.get(str(time_range or ""))
    if minutes is None:
        return True
    timestamp = item_datetime(item)
    if timestamp is None:
        return False
    return timestamp >= (now or datetime.now()) - timedelta(minutes=minutes)


def searchable_text(item: Mapping[str, Any], *, include_detail: bool = False) -> str:
    row = dict(item)
    facts = classification_facts(row)
    keys = [
        "platform",
        "source",
        "trace_id",
        "traceId",
        "level",
        "message_summary",
        "message",
        "status_code",
        "action",
        "event",
        "event_type",
        "category",
    ]
    values = [str(row.get(key) or "") for key in keys]
    values.extend(
        [
            facts["raw_level"],
            facts["source"],
            facts["action"],
            facts["status"],
            facts["event_code"],
            facts["platform"],
            facts["legacy_category"],
            derive_log_scope(row),
            derive_event_stage(row),
            derive_result_type(row),
        ]
    )
    if include_detail:
        values.extend([facts["detail_text"], str(row.get("stack") or "")])
    return " ".join(values)


def matches_non_category_filters(
    item: Mapping[str, Any],
    *,
    level: str,
    time_range: str,
    platform_id: str | None,
    trace_query: str,
    keyword: str,
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
    now: datetime | None = None,
) -> bool:
    row = dict(item)
    level = str(level or "").strip()
    if level and level not in ALL_LABELS:
        result_type = derive_result_type(row)
        display = result_display_text(result_type, normalized_raw_level(row))
        if display != level:
            return False

    if not matches_time_range(row, time_range, now=now):
        return False

    if not matches_platform(
        row,
        platform_id,
        platform_options=platform_options,
        platform_meta_by_id=platform_meta_by_id,
    ):
        return False

    trace_query = str(trace_query or "").strip().lower()
    if trace_query and trace_query not in str(row.get("trace_id") or "").lower():
        return False

    keyword = str(keyword or "").strip().lower()
    if keyword and keyword not in searchable_text(row, include_detail=True).lower():
        return False

    return True


def matches_filters(
    item: Mapping[str, Any],
    *,
    category: str,
    level: str,
    time_range: str,
    platform_id: str | None,
    trace_query: str,
    keyword: str,
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
    now: datetime | None = None,
) -> bool:
    if not matches_category(item, category):
        return False
    return matches_non_category_filters(
        item,
        level=level,
        time_range=time_range,
        platform_id=platform_id,
        trace_query=trace_query,
        keyword=keyword,
        platform_options=platform_options,
        platform_meta_by_id=platform_meta_by_id,
        now=now,
    )


def category_counts(
    items: Sequence[dict[str, Any]],
    categories: Sequence[str],
    *,
    level: str,
    time_range: str,
    platform_id: str | None,
    trace_query: str,
    keyword: str,
    platform_options: Sequence[PlatformUiMeta],
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> dict[str, int]:
    counts = {key: 0 for key in categories}
    for item in items:
        if not matches_non_category_filters(
            item,
            level=level,
            time_range=time_range,
            platform_id=platform_id,
            trace_query=trace_query,
            keyword=keyword,
            platform_options=platform_options,
            platform_meta_by_id=platform_meta_by_id,
        ):
            continue
        counts["all"] = counts.get("all", 0) + 1
        scope = derive_log_scope(item)
        if scope in counts:
            counts[scope] += 1
    return counts
