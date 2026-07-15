from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.models import VideoItem
from shared.log_detail_payloads import normalize_detail_payload
from shared.log_display import decorate_log_item
from shared.log_pipeline_rules import derive_event_stage, derive_log_scope, derive_scope_reason
from shared.log_platforms import builtin_platform_metas

LOG_ENTRY_RE = re.compile(
    r"^\[(?P<time>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s+(?P<source>[^/]+?)\s*/\s*(?P<action>.+)$"
)


def _local_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone()
    return parsed


def normalize_log_time_display(value: str) -> str:
    text = str(value or "").strip()
    parsed = _local_datetime(text)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed is not None else text


def normalize_log_level(level: str) -> str:
    normalized = str(level or "").upper()
    if normalized == "COMMAND":
        return "CMD"
    if normalized == "WARNING":
        return "WARN"
    if normalized == "OK":
        return "SUCCESS"
    return normalized


def looks_like_trace_line(line: str) -> bool:
    lowered = str(line or "").strip().lower()
    return lowered.startswith(
        (
            "追踪id:",
            "追踪id：",
            "trace id:",
            "trace id：",
            "trace_id:",
            "trace_id：",
            "- trace_id:",
            "- trace_id：",
            "- trace id:",
            "- trace id：",
        )
    )


def parse_trace_line(line: str) -> str:
    text = str(line or "").strip()
    if text.startswith("-"):
        text = text[1:].strip()
    for delimiter in (":", "："):
        if delimiter in text:
            return text.split(delimiter, 1)[1].strip()
    return ""


def trace_from_log_detail(item: Mapping[str, Any]) -> str:
    text = "\n".join(str(item.get(key) or "") for key in ("detail", "message", "message_summary"))
    for pattern in (
        r"(?:trace_id|Trace ID|追踪ID)\s*[:：]\s*([A-Za-z0-9_.:-]+)",
        r"-\s*trace_id\s*[:：]\s*([A-Za-z0-9_.:-]+)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(",;")
    return ""


def platform_from_log(item: Mapping[str, Any]) -> str:
    text = " ".join(
        str(item.get(key) or "") for key in ("trace_id", "source", "message", "message_summary", "detail")
    ).lower()
    mapping = (
        ("bilibili", "Bilibili"),
        ("bili", "Bilibili"),
        ("douyin", "抖音"),
        ("dy_", "抖音"),
        ("kuaishou", "快手"),
        ("ks_", "快手"),
        ("missav", "MissAV"),
        ("xhs", "小红书"),
        ("xiaohongshu", "小红书"),
    )
    for token, label in mapping:
        if token in text:
            return label
    return ""


def log_category(item: Mapping[str, Any]) -> str:
    return derive_log_scope(dict(item))


def log_timestamp_ms(value: str) -> int:
    parsed = _local_datetime(str(value or ""))
    return int(parsed.timestamp() * 1000) if parsed is not None else 0


def log_level_icon_file(level: str) -> str:
    normalized = str(level or "").upper()
    if normalized in {"WARN", "WARNING"}:
        return "log_level_warn.png"
    if normalized == "ERROR":
        return "log_level_error.png"
    return "log_level_info.png"


def enrich_log_item(item: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(item or {})
    enriched["time"] = normalize_log_time_display(str(enriched.get("time") or ""))
    enriched["level"] = normalize_log_level(str(enriched.get("level") or "INFO"))
    enriched["trace_id"] = str(enriched.get("trace_id") or trace_from_log_detail(enriched) or "")
    enriched["platform"] = str(enriched.get("platform") or platform_from_log(enriched) or "系统")
    enriched["category"] = log_category(enriched)
    enriched["timestamp_ms"] = log_timestamp_ms(str(enriched.get("time") or ""))
    if not enriched.get("message_summary"):
        enriched["message_summary"] = str(enriched.get("message") or "")[:120]
    return _decorate_log_display_fields(enriched)


def _decorate_log_display_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    """通过前端中立的展示契约补齐单条日志的范围、阶段和详情载荷。"""
    row = dict(item or {})
    metas = builtin_platform_metas()
    scope = derive_log_scope(row)
    stage = derive_event_stage(row)
    row["category"] = scope
    decorated = decorate_log_item(
        row,
        platform_options=list(metas.values()),
        platform_meta_by_id=metas,
        log_scope=scope,
        event_stage=stage,
        scope_reason=derive_scope_reason(row),
    )
    decorated["detail_payload"] = normalize_detail_payload(
        decorated,
        status_code=str(decorated.get("status_code") or ""),
    )
    return decorated


def parse_debug_log_text(
    text: str,
    *,
    limit: int,
    id_prefix: str = "",
) -> list[dict[str, Any]]:
    source_text = str(text or "")
    lines = source_text.splitlines()
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    detail_lines: list[str] = []
    for line in lines:
        match = LOG_ENTRY_RE.match(line.strip())
        if match:
            if current is not None:
                current["detail"] = "\n".join(detail_lines).strip()
                items.append(current)
            current = {
                "time": match.group("time"),
                "level": normalize_log_level(match.group("level")),
                "source": match.group("source").strip(),
                "action": match.group("action").strip(),
                "thread": "",
                "trace_id": "",
                "message_summary": match.group("action").strip(),
                "message": "",
                "detail": "",
                "stack": "",
            }
            detail_lines = []
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("说明:"):
            current["message"] = stripped.replace("说明:", "", 1).strip()
            current["message_summary"] = current["message"][:120]
        elif stripped.startswith("状态码:"):
            current["status_code"] = stripped.replace("状态码:", "", 1).strip()
        elif looks_like_trace_line(stripped):
            current["trace_id"] = parse_trace_line(stripped)
        detail_lines.append(line)

    if current is not None:
        current["detail"] = "\n".join(detail_lines).strip()
        items.append(current)
    # ID 由文本内容或调用方提供的文件位置稳定生成，前端刷新后才能保留选中行。
    prefix = str(id_prefix or f"parsed-log:{sha256(source_text.encode('utf-8')).hexdigest()[:16]}")
    for index, item in enumerate(items):
        item.setdefault("id", f"{prefix}:{index}")
    return items[-int(limit):]


def parse_debug_log_file(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    identity = "|".join(
        (
            str(path.resolve()),
            str(getattr(stat, "st_dev", "")),
            str(getattr(stat, "st_ino", "")),
        )
    )
    prefix = f"file-log:{sha256(identity.encode('utf-8', errors='replace')).hexdigest()[:16]}"
    return parse_debug_log_text(text, limit=limit, id_prefix=prefix)


def build_log_excerpt_index(log_items: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    fallback_key = "__recent_errors__"
    for item in log_items:
        trace_id = str(item.get("trace_id") or "")
        message = str(item.get("message_summary") or item.get("message") or "")
        if not message:
            continue
        level = normalize_log_level(str(item.get("level") or "INFO"))
        entry = {
            "time": str(item.get("time") or "")[-8:],
            "level": level,
            "source": str(item.get("source") or ""),
            "trace_id": trace_id,
            "message": message,
            "icon_file": log_level_icon_file(level),
        }
        if trace_id:
            index.setdefault(trace_id, []).append(entry)
        if entry["level"] in {"ERROR", "WARN", "WARNING"}:
            index.setdefault(fallback_key, []).append(entry)
    return index


def failed_log_excerpt_items(
    item: VideoItem,
    *,
    trace_id: str,
    index: dict[str, list[dict[str, Any]]],
    platform_label: Callable[[VideoItem], str],
    trace_id_for_item: Callable[[VideoItem], str],
) -> list[dict[str, Any]]:
    entries = list(index.get(trace_id, [])) if trace_id else []
    if not entries:
        entries = fallback_failed_log_entries(
            item,
            index,
            platform_label=platform_label,
            trace_id_for_item=trace_id_for_item,
        )
    return entries[-8:]


def fallback_failed_log_entries(
    item: VideoItem,
    index: dict[str, list[dict[str, Any]]],
    *,
    platform_label: Callable[[VideoItem], str],
    trace_id_for_item: Callable[[VideoItem], str],
) -> list[dict[str, Any]]:
    meta = item.meta or {}
    title = str(item.title or "").strip()
    reason = str(meta.get("download_error") or meta.get("error") or item.status or "").strip()
    needles = [part for part in (title[:24], reason[:32], item.source or "") if part]
    matched: list[dict[str, Any]] = []
    for entries in index.values():
        for entry in entries:
            message = str(entry.get("message") or "")
            if any(needle and needle in message for needle in needles):
                matched.append(entry)
    if matched:
        return matched[-8:]
    fallback = list(index.get("__recent_errors__", []))
    if fallback:
        return fallback[-8:]
    reason_text = reason or "任务失败，暂无可匹配日志片段"
    return [
        {
            "time": str(meta.get("failed_at") or "")[-8:],
            "level": "ERROR",
            "source": platform_label(item),
            "trace_id": trace_id_for_item(item),
            "message": reason_text,
            "icon_file": "log_level_error.png",
        }
    ]
