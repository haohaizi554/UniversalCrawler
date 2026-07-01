from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from app.services import frontend_video_adapter as video_adapter
from app.services.media_metadata_service import MediaMetadataService


def has_display_duration(value: Any) -> bool:
    text = str(value or "").strip()
    return text not in {"", "--", "00:00:00"}


def normalize_local_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        resolved = Path(text).expanduser().resolve(strict=False)
        normalized = str(resolved)
    except (OSError, RuntimeError, ValueError):
        normalized = os.path.abspath(os.path.normpath(text))
    return os.path.normcase(os.path.normpath(normalized)).replace("\\", "/")


def same_local_path(left: str, right: str) -> bool:
    normalized_left = normalize_local_path(left)
    normalized_right = normalize_local_path(right)
    return bool(normalized_left and normalized_right and normalized_left == normalized_right)


def metadata_failure_key(video_id: str, source_path: str) -> str:
    return f"{str(video_id or '')}\0{normalize_local_path(source_path)}"


def has_media_metadata(meta: Mapping[str, Any], path: Path | None = None) -> bool:
    resolution = str(meta.get("resolution") or meta.get("quality") or "").strip()
    content_type = str(meta.get("content_type") or "").strip().lower()
    is_image = content_type == "image" or (
        path is not None and path.suffix.lower() in MediaMetadataService.IMAGE_EXTENSIONS
    )
    if is_image:
        return video_adapter.is_real_resolution(resolution)
    return has_display_duration(meta.get("duration")) and video_adapter.is_real_resolution(resolution)


def normalize_completed_metadata_payload(metadata: Mapping[str, Any]) -> dict[str, str]:
    duration = video_adapter.display_duration(metadata.get("duration"))
    if not duration:
        try:
            duration_ms = float(metadata.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        if duration_ms > 0:
            duration = MediaMetadataService.format_duration(duration_ms / 1000)
    if not duration:
        duration = video_adapter.display_duration(metadata.get("duration_seconds"))

    resolution = str(metadata.get("resolution") or "").strip()
    if not video_adapter.is_real_resolution(resolution):
        try:
            width = int(float(metadata.get("width") or 0))
            height = int(float(metadata.get("height") or 0))
        except (TypeError, ValueError):
            width = height = 0
        resolution = f"{width} x {height}" if width > 0 and height > 0 else ""

    return {
        "duration": duration,
        "resolution": resolution if video_adapter.is_real_resolution(resolution) else "",
        "format": str(metadata.get("format") or "").strip(),
        "content_type": str(metadata.get("content_type") or "").strip(),
    }


def apply_completed_metadata(meta: dict[str, Any], metadata: Mapping[str, Any]) -> bool:
    changed = False
    for key, value in metadata.items():
        value_text = str(value or "").strip()
        if not value_text:
            continue
        current = str(meta.get(key) or "").strip()
        if key == "resolution":
            should_update = video_adapter.is_real_resolution(value_text) and not video_adapter.is_real_resolution(current)
        elif key == "duration":
            should_update = has_display_duration(value_text) and not has_display_duration(current)
        else:
            should_update = current in {"", "--"}
        if should_update:
            meta[key] = value_text
            changed = True
    return changed
