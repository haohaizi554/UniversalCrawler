"""控制器与下载分发层共用的媒体类型判定规则。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from app.models import VideoItem

IMAGE_CONTENT_TYPES = frozenset({"image", "gallery", "photo", "photos"})
VIDEO_CONTENT_TYPES = frozenset({"video", "live_video"})
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m3u8")
IMAGE_META_KEYS = (
    "image_url",
    "image_index",
    "images_data",
    "cover_url",
    "cover",
    "static_cover",
    "dynamic_cover",
    "thumbnail",
)
VIDEO_META_KEYS = ("video_url", "live_video_url", "play_url", "download_url", "video_candidates")


def _item_meta(item: VideoItem | Any | None) -> Mapping[str, Any]:
    meta = getattr(item, "meta", None)
    return meta if isinstance(meta, Mapping) else {}


def _url_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return urlsplit(raw).path.lower()
    except ValueError:
        return raw.split("?", 1)[0].lower()


def is_video_like_resource(item: VideoItem | Any | None) -> bool:
    """判断项目是否指向视频载荷。"""
    if item is None:
        return False
    meta = _item_meta(item)
    content_type = str(meta.get("content_type") or "").strip().lower()
    if content_type in VIDEO_CONTENT_TYPES:
        return True
    if any(meta.get(key) for key in VIDEO_META_KEYS):
        return True
    return _url_path(getattr(item, "url", "")).endswith(VIDEO_EXTENSIONS)


def is_image_like_resource(item: VideoItem | Any | None) -> bool:
    """判断项目是否属于图片、封面或图集资源。"""
    if item is None:
        return False
    meta = _item_meta(item)
    content_type = str(meta.get("content_type") or "").strip().lower()
    if content_type in IMAGE_CONTENT_TYPES:
        return True
    if any(meta.get(key) for key in IMAGE_META_KEYS):
        return True
    return _url_path(getattr(item, "url", "")).endswith(IMAGE_EXTENSIONS)


def should_skip_for_video_only(item: VideoItem | Any | None) -> bool:
    """判断全局“仅视频”策略是否应过滤当前项目。"""
    return is_image_like_resource(item) and not is_video_like_resource(item)
