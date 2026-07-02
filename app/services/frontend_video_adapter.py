"""Pure frontend row adapters for video-like state.

The state service owns orchestration, events, and side effects. This module
keeps deterministic formatting and classification helpers small enough to test
without booting the GUI, web layer, or download manager.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from app.core.state import VideoStatus, parse_video_status
from app.models import VideoItem
from app.services.media_metadata_service import MediaMetadataService

QUEUE_STATUSES = ("\u5f85\u89e3\u6790", "\u89e3\u6790\u4e2d", "\u5df2\u89e3\u6790", "\u6392\u961f\u4e2d", "\u5df2\u5b58\u5728", "\u5f85\u4e0b\u8f7d")


def trace_id(item: VideoItem) -> str:
    return str((item.meta or {}).get("trace_id") or "")


def queue_subtitle(meta: Mapping[str, Any]) -> str:
    raw = str(meta.get("created_at") or meta.get("discovered_at") or meta.get("added_at") or "").strip()
    if not raw:
        return ""
    return raw.replace("T", " ")[:19]


def queue_status(item: VideoItem, queued_ids: set[str]) -> str:
    meta = item.meta or {}
    parsed = parse_video_status(item.status)
    if parsed == VideoStatus.LOCAL:
        return "\u672c\u5730"
    if meta.get("frontend_status") in QUEUE_STATUSES:
        return str(meta["frontend_status"])
    if meta.get("already_exists"):
        return "\u5df2\u5b58\u5728"
    if item.id in queued_ids:
        return "\u6392\u961f\u4e2d"
    raw = str(item.status or "")
    if "\u89e3\u6790" in raw:
        return "\u5df2\u89e3\u6790"
    if "\u7b49\u5f85" in raw:
        return "\u5f85\u4e0b\u8f7d"
    return "\u5f85\u89e3\u6790" if not item.url else "\u5f85\u4e0b\u8f7d"


def queue_item(
    item: VideoItem,
    *,
    queued_ids: set[str],
    platform_label: Callable[[VideoItem], str],
) -> dict[str, Any]:
    meta = item.meta or {}
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": queue_subtitle(meta),
        "platform": platform_label(item),
        "platform_id": item.source,
        "status": queue_status(item, queued_ids),
        "source_url": item.url,
        "trace_id": trace_id(item),
        "created_at": str(meta.get("created_at") or meta.get("discovered_at") or meta.get("added_at") or ""),
        "actions": ["delete"],
    }


def bucket_for_item(item: VideoItem, *, queued_ids: set[str], active_ids: set[str]) -> str:
    parsed = parse_video_status(item.status)
    if parsed in {VideoStatus.COMPLETED, VideoStatus.LOCAL}:
        return "completed"
    if parsed in {VideoStatus.FAILED, VideoStatus.TIMED_OUT}:
        return "failed"
    if item.id in active_ids or parsed == VideoStatus.DOWNLOADING:
        return "active"
    if item.progress >= 100 and item.local_path:
        return "completed"
    if item.id in queued_ids or parsed == VideoStatus.PENDING:
        return "queue"
    return "queue"


def active_item(
    item: VideoItem,
    *,
    platform_label: Callable[[VideoItem], str],
    current_save_dir: str,
    active_events: Callable[..., list[dict[str, str]]],
) -> dict[str, Any]:
    meta = item.meta or {}
    progress = int(item.progress or 0)
    chunks_done = int(meta.get("chunks_done", 0) or 0)
    chunks_total = int(meta.get("chunks_total", 0) or 0)
    if chunks_total <= 0:
        chunks_total = 100
        chunks_done = progress
    path = Path(item.local_path) if item.local_path else None
    save_dir = str(meta.get("save_dir") or meta.get("download_dir") or (path.parent if path is not None else current_save_dir))
    output_filename = str(meta.get("output_filename") or meta.get("filename") or (path.name if path is not None else item.title))
    speed = str(meta.get("speed") or "0 B/s")
    remaining_time = str(meta.get("remaining_time") or meta.get("eta") or "--")
    item_trace_id = trace_id(item)
    write_status = str(meta.get("write_status") or default_write_status(progress))
    merge_status = str(meta.get("merge_status") or default_merge_status(item, progress))
    return {
        "id": item.id,
        "title": item.title,
        "platform": platform_label(item),
        "platform_id": item.source,
        "progress": progress,
        "save_dir": save_dir,
        "output_filename": output_filename,
        "speed": speed,
        "speed_bps": int(meta.get("speed_bps") or 0),
        "bytes_downloaded": int(meta.get("bytes_downloaded", 0) or 0),
        "bytes_total": int(meta.get("bytes_total", 0) or 0),
        "eta_seconds": meta.get("eta_seconds"),
        "eta": str(meta.get("eta") or "--"),
        "remaining_time": remaining_time,
        "trace_id": item_trace_id,
        "thread_count": int(meta.get("thread_count", meta.get("threads", 1)) or 1),
        "retry_count": int(meta.get("retry_count", 0) or 0),
        "write_status": write_status,
        "merge_status": merge_status,
        "source_url": item.url,
        "chunk_progress": {
            "completed": chunks_done,
            "total": chunks_total,
            "percent": progress,
        },
        "speed_trend": list(meta.get("speed_trend") or default_speed_trend(progress)),
        "events": active_events(
            item,
            progress=progress,
            chunks_done=chunks_done,
            chunks_total=chunks_total,
            speed=speed,
            remaining_time=remaining_time,
            write_status=write_status,
            merge_status=merge_status,
            trace_id=item_trace_id,
        ),
        "actions": ["delete"],
    }


def completed_item(
    item: VideoItem,
    *,
    path: Path | None,
    size_bytes: int,
    completed_at: str,
    metadata: Any,
    metadata_pending: bool,
    platform_label: Callable[[VideoItem], str],
) -> dict[str, Any]:
    meta = item.meta or {}
    duration = display_duration(meta.get("duration") or getattr(metadata, "duration", ""))
    resolution = display_resolution(meta.get("resolution"), meta.get("quality"), getattr(metadata, "resolution", ""))
    pending_label = "\u68c0\u6d4b\u4e2d"
    format_label = str(meta.get("format") or getattr(metadata, "format", "") or format_from_path(path))
    content_type = str(meta.get("content_type") or getattr(metadata, "content_type", "") or content_type_from_path(path))
    filename = str(meta.get("filename") or (path.name if path else "") or item.title)
    save_dir = str(meta.get("save_dir") or (path.parent if path else ""))
    return {
        "id": item.id,
        "title": item.title,
        "thumbnail": str(meta.get("thumbnail") or ""),
        "completed_at": completed_at,
        "completed_at_table": format_completed_at_table(completed_at),
        "duration": duration or (pending_label if metadata_pending else "--"),
        "resolution": resolution if resolution != "--" else (pending_label if metadata_pending else "--"),
        "size": format_size(size_bytes),
        "size_bytes": size_bytes,
        "format": format_label,
        "filename": filename,
        "save_dir": save_dir,
        "download_speed": str(meta.get("speed") or "--"),
        "download_speed_bps": int(meta.get("speed_bps") or 0),
        "local_path": item.local_path or "",
        "content_type": content_type,
        "metadata_pending": metadata_pending,
        "platform": platform_label(item),
        "actions": ["play", "open_directory", "delete"],
    }


def failed_item(
    item: VideoItem,
    *,
    platform_label: Callable[[VideoItem], str],
    log_excerpt_items: list[dict[str, Any]],
    failed_at_fallback: str,
) -> dict[str, Any]:
    meta = item.meta or {}
    reason = str(meta.get("download_error") or meta.get("error") or item.status or "\u672a\u77e5\u9519\u8bef")
    item_trace_id = trace_id(item)
    category = failure_category(reason)
    failed_at = str(meta.get("failed_at") or failed_at_fallback)
    return {
        "id": item.id,
        "title": item.title,
        "failed_at": failed_at,
        "failed_at_table": format_completed_at_table(failed_at),
        "reason": reason,
        "reason_detail": reason,
        "reason_label": category["label"],
        "reason_label_align": "center",
        "reason_category": category["key"],
        "reason_icon_file": category["icon_file"],
        "status": "\u5931\u8d25",
        "status_label": "\u5931\u8d25",
        "status_icon_file": "status_failed.png",
        "trace_id": item_trace_id,
        "platform": platform_label(item),
        "platform_id": item.source,
        "source_url": item.url,
        "log_excerpt": [entry["message"] for entry in log_excerpt_items],
        "log_excerpt_items": log_excerpt_items,
        "solutions": solutions_for_reason(reason),
        "actions": ["copy_diagnostics", "delete"],
    }


def is_real_resolution(value: Any) -> bool:
    return bool(re.match(r"^\d{2,5}\s*x\s*\d{2,5}$", str(value or "").strip(), flags=re.IGNORECASE))


def display_resolution(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if is_real_resolution(text):
            return text
    return "--"


def display_duration(value: Any) -> str:
    if isinstance(value, (int, float)):
        return MediaMetadataService.format_duration(value)
    text = str(value or "").strip()
    if not text or text == "--":
        return ""
    if text.isdigit():
        return MediaMetadataService.format_duration(text)
    return text


def format_completed_at_table(value: str) -> str:
    text = str(value or "").strip().replace("T", " ")
    if not text or text == "--":
        return text or "--"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%m-%d %H:%M")
        except ValueError:
            pass
    if len(text) >= 16 and text[4:5] in {"-", "/"}:
        return text[5:16]
    return text


def format_size(size_bytes: int) -> str:
    size = float(max(size_bytes, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "0 B"


def format_from_path(path: Path | None) -> str:
    if not path or not path.suffix:
        return "--"
    return path.suffix.lstrip(".").upper()


def content_type_from_path(path: Path | None) -> str:
    if not path:
        return ""
    return "image" if path.suffix.lower() in MediaMetadataService.IMAGE_EXTENSIONS else "video"


def default_speed_trend(progress: int) -> list[float]:
    seed = max(0, min(100, progress)) / 100
    return [round((0.7 + ((index % 5) * 0.12)) * seed, 2) for index in range(12)]


def default_write_status(progress: int) -> str:
    if progress >= 100:
        return "写入完成"
    if progress > 0:
        return "写入中"
    return "等待写入"


def default_merge_status(item: VideoItem, progress: int) -> str:
    meta = item.meta or {}
    needs_merge = bool(meta.get("audio_url") or meta.get("needs_merge") or item.source == "bilibili")
    if not needs_merge:
        return "不需要合并"
    if progress >= 100:
        return "合并完成"
    if progress >= 91:
        return "合并中"
    return "等待合并"


def active_events(
    item: VideoItem,
    *,
    progress: int,
    chunks_done: int,
    chunks_total: int,
    speed: str,
    remaining_time: str,
    write_status: str,
    merge_status: str,
    trace_id: str,
    event_time_cache: dict[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[dict[str, str]]:
    existing: list[dict[str, str]] = []
    for event in list((item.meta or {}).get("events") or [])[-6:]:
        if not isinstance(event, Mapping):
            continue
        message = str(event.get("message") or "").strip()
        if not message:
            continue
        existing.append({"time": str(event.get("time") or ""), "message": message})

    event_time = stable_active_event_time(item, existing, event_time_cache=event_time_cache, now=now)
    for event in existing:
        if not event["time"]:
            event["time"] = event_time
    if len(existing) >= 6:
        return existing[-6:]

    chunk_text = f"{progress}%"
    if chunks_total:
        chunk_text = f"{progress}% ({chunks_done}/{chunks_total})"
    derived = [
        f"\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668\uff1a{item.title}",
        f"\u8fdb\u5ea6\uff1a{chunk_text}",
        f"\u5f53\u524d\u901f\u5ea6\uff1a{speed}\uff0c\u5269\u4f59\uff1a{remaining_time}",
    ]
    if trace_id:
        derived.append(f"Trace ID\uff1a{trace_id}")
    elif item.url:
        derived.append("\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55")
    derived.extend(
        [
            f"\u5199\u5165\u72b6\u6001\uff1a{write_status}",
            f"\u5408\u5e76\u72b6\u6001\uff1a{merge_status}",
        ]
    )

    seen = {event["message"] for event in existing}
    result = list(existing)
    for message in derived:
        if message in seen:
            continue
        result.append({"time": event_time, "message": message})
        seen.add(message)
        if len(result) >= 6:
            break
    return result[:6]


def stable_active_event_time(
    item: VideoItem,
    existing: list[dict[str, str]],
    *,
    event_time_cache: dict[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> str:
    for event in existing:
        value = str(event.get("time") or "").strip()
        if value:
            return value
    meta = item.meta or {}
    cache = event_time_cache if event_time_cache is not None else {}
    for key in ("event_time", "download_started_at", "started_at", "created_at", "discovered_at", "added_at"):
        formatted = format_event_clock(meta.get(key))
        if formatted:
            cache[item.id] = formatted
            return formatted
    cached = cache.get(item.id)
    if cached:
        return cached
    clock = now or datetime.now
    generated = clock().strftime("%H:%M:%S")
    cache[item.id] = generated
    return generated


def format_event_clock(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) >= 8 and raw[-8:].count(":") == 2:
        return raw[-8:]
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        return raw


def default_active_events(item: VideoItem, *, now: Callable[[], datetime] | None = None) -> list[dict[str, str]]:
    clock = now or datetime.now
    current = clock().strftime("%H:%M:%S")
    return [
        {"time": current, "message": f"\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668\uff1a{item.title}"},
        {"time": current, "message": "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6"},
        {"time": current, "message": "\u8fdb\u5ea6\uff1a0%"},
        {"time": current, "message": "\u5f53\u524d\u901f\u5ea6\uff1a0 B/s"},
    ]


def failure_category(reason: str) -> dict[str, str]:
    lowered = str(reason or "").lower()
    if "login" in lowered or "\u767b\u5f55" in reason:
        return {"key": "login", "label": "\u9700\u8981\u767b\u5f55", "icon_file": "action_user.png"}
    if "timeout" in lowered or "\u8d85\u65f6" in reason:
        return {"key": "timeout", "label": "\u7f51\u7edc\u8d85\u65f6", "icon_file": "status_timeout.png"}
    if any(token in lowered for token in ("connection", "network", "403", "404", "forbidden", "ssl", "proxy")) or any(
        token in reason for token in ("\u8fde\u63a5", "\u7f51\u7edc", "\u62d2\u7edd", "\u5931\u6548", "\u94fe\u63a5")
    ):
        return {"key": "link", "label": "\u94fe\u63a5\u5931\u8d25", "icon_file": "action_trace_link.png"}
    if any(token in lowered for token in ("permission", "occupied", "file")) or any(token in reason for token in ("\u5360\u7528", "\u6743\u9650", "\u6587\u4ef6")):
        return {"key": "file", "label": "\u6587\u4ef6\u5360\u7528", "icon_file": "status_locked.png"}
    if any(token in lowered for token in ("parse", "parser", "extract", "decode")) or any(token in reason for token in ("\u89e3\u6790", "\u63d0\u53d6")):
        return {"key": "parse", "label": "\u89e3\u6790\u5931\u8d25", "icon_file": "action_code.png"}
    if any(token in lowered for token in ("ffmpeg", "m3u8", "external", "tool")) or any(token in reason for token in ("\u5916\u90e8\u5de5\u5177", "\u5408\u5e76")):
        return {"key": "tool", "label": "\u5de5\u5177\u5f02\u5e38", "icon_file": "action_repair.png"}
    return {"key": "unknown", "label": "\u4efb\u52a1\u5931\u8d25", "icon_file": "status_error_warning.png"}


def solutions_for_reason(reason: str) -> list[dict[str, str]]:
    lowered = reason.lower()
    if "login" in lowered or "\u767b\u5f55" in reason:
        return [
            {"title": "\u786e\u8ba4\u767b\u5f55\u72b6\u6001", "description": "\u90e8\u5206\u5185\u5bb9\u9700\u8981\u767b\u5f55\u540e\u624d\u80fd\u8bbf\u95ee\uff0c\u8bf7\u68c0\u67e5\u5e73\u53f0\u8ba4\u8bc1\u72b6\u6001\u3002", "icon_file": "action_user.png"},
            {"title": "\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5", "description": "\u767b\u5f55\u540e\u91cd\u65b0\u590d\u5236\u5206\u4eab\u94fe\u63a5\u5e76\u91cd\u8bd5\u4efb\u52a1\u3002", "icon_file": "action_trace_link.png"},
        ]
    if "timeout" in lowered or "\u8d85\u65f6" in reason:
        return [
            {"title": "\u68c0\u67e5\u7f51\u7edc", "description": "\u786e\u8ba4\u7f51\u7edc\u8fde\u63a5\u6b63\u5e38\uff0c\u6216\u5c1d\u8bd5\u5207\u6362\u7f51\u7edc\u73af\u5883\u540e\u91cd\u8bd5\u3002", "icon_file": "status_network_warning.png"},
            {"title": "\u589e\u52a0\u8d85\u65f6\u65f6\u95f4", "description": "\u5728\u914d\u7f6e\u4e2d\u5fc3\u63d0\u9ad8\u8bf7\u6c42\u8d85\u65f6\u548c\u91cd\u8bd5\u6b21\u6570\u3002", "icon_file": "status_timeout.png"},
        ]
    if any(token in lowered for token in ("connection", "network", "403", "404", "forbidden")) or any(token in reason for token in ("\u8fde\u63a5", "\u7f51\u7edc", "\u62d2\u7edd", "\u5931\u6548")):
        return [
            {"title": "\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5", "description": "\u8bf7\u91cd\u65b0\u590d\u5236\u6700\u65b0\u7684\u5206\u4eab\u94fe\u63a5\u5e76\u91cd\u8bd5\u4efb\u52a1\u3002", "icon_file": "action_trace_link.png"},
            {"title": "\u68c0\u67e5\u7f51\u7edc", "description": "\u786e\u8ba4\u4ee3\u7406\u3001DNS \u548c\u7f51\u7edc\u73af\u5883\u6b63\u5e38\uff0c\u5fc5\u8981\u65f6\u5207\u6362\u7f51\u7edc\u540e\u91cd\u8bd5\u3002", "icon_file": "status_network_warning.png"},
        ]
    if any(token in lowered for token in ("permission", "occupied", "file")) or any(token in reason for token in ("\u5360\u7528", "\u6743\u9650", "\u6587\u4ef6")):
        return [
            {"title": "\u91ca\u653e\u6587\u4ef6\u5360\u7528", "description": "\u5173\u95ed\u6b63\u5728\u64ad\u653e\u6216\u5360\u7528\u76ee\u6807\u6587\u4ef6\u7684\u7a0b\u5e8f\u540e\u91cd\u8bd5\u3002", "icon_file": "status_locked.png"},
            {"title": "\u66f4\u6539\u76ee\u5f55", "description": "\u5c1d\u8bd5\u5207\u6362\u5230\u6709\u5199\u5165\u6743\u9650\u7684\u4fdd\u5b58\u76ee\u5f55\u3002", "icon_file": "action_open_directory.png"},
        ]
    return [
        {"title": "\u91cd\u65b0\u83b7\u53d6\u94fe\u63a5", "description": "\u8bf7\u91cd\u65b0\u590d\u5236\u6700\u65b0\u7684\u5206\u4eab\u94fe\u63a5\u5e76\u91cd\u8bd5\u4efb\u52a1\u3002", "icon_file": "action_trace_link.png"},
        {"title": "\u67e5\u770b Trace ID", "description": "\u5728\u65e5\u5fd7\u4e2d\u5fc3\u6309 Trace ID \u8fc7\u6ee4\uff0c\u5b9a\u4f4d\u540c\u4e00\u4efb\u52a1\u7684\u4e0a\u4e0b\u6e38\u65e5\u5fd7\u3002", "icon_file": "action_search.png"},
    ]
