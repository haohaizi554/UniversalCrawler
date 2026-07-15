"""处理 Windows 兼容的媒体文件名。"""
import re
from typing import Any

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

def sanitize_filename(name: str) -> str:
    """移除 Windows 文件名非法字符并限制长度。"""
    safe_name = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', "_", str(name)).strip()
    safe_name = safe_name.rstrip(". ")
    safe_name = safe_name[:200]
    safe_name = safe_name.rstrip(". ")
    stem = safe_name.partition(".")[0].rstrip(". ").upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        safe_name = f"_{safe_name}"
    return safe_name or "untitled"

def build_media_filename(title: str, source: str, extension: str = ".mp4", meta: dict[str, Any] | None = None) -> str:
    """生成规范化媒体文件名，同时保留平台特有后缀。"""
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
