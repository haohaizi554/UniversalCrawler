"""Filename cleanup helpers."""
#文件名规范化处理
import re
from typing import Any

def sanitize_filename(name: str) -> str:
    """Strip invalid Windows filename characters and trim length."""
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip()
    safe_name = safe_name.rstrip(". ")
    safe_name = safe_name[:200]
    return safe_name or "untitled"

def build_media_filename(title: str, source: str, extension: str = ".mp4", meta: dict[str, Any] | None = None) -> str:
    """Build a normalized media filename while preserving platform-specific suffixes."""
    meta = meta or {}
    raw_name = title
    if source == "missav":
        tags = meta.get("tags", [])
        if "中文字幕" in tags:
            raw_name += " [中文字幕]"
        elif "英文字幕" in tags:
            raw_name += " [英文字幕]"
        elif "无码流出" in tags:
            raw_name += " [无码]"
    safe_name = sanitize_filename(raw_name)
    if not extension.startswith("."):
        extension = f".{extension}"
    fallback = f"{source}_untitled"
    return f"{safe_name or fallback}{extension}"
