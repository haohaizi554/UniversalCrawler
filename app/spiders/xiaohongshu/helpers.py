"""Shared XiaoHongShu parsing helpers."""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


def _base36_encode(number: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"
    sign = ""
    if number < 0:
        sign = "-"
        number = -number
    base36 = ""
    while number:
        number, idx = divmod(number, len(alphabet))
        base36 = alphabet[idx] + base36
    return sign + base36


def build_search_id() -> str:
    """Build XHS search_id following the browser-compatible MediaCrawler strategy."""
    epoch_part = int(time.time() * 1000) << 64
    random_part = int(random.uniform(0, 2147483646))
    return _base36_encode(epoch_part + random_part)


@dataclass(slots=True)
class NoteUrlInfo:
    note_id: str
    xsec_token: str
    xsec_source: str


@dataclass(slots=True)
class CreatorUrlInfo:
    user_id: str
    xsec_token: str
    xsec_source: str


def extract_url_params_to_dict(url: str) -> dict[str, str]:
    """Parse query params into a flat dict."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return {key: values[-1] for key, values in params.items() if values}


def is_note_url(text: str) -> bool:
    lowered = text.lower()
    return "xiaohongshu.com/explore/" in lowered or "xiaohongshu.com/discovery/item/" in lowered


def is_creator_url(text: str) -> bool:
    return "xiaohongshu.com/user/profile/" in text.lower()


def parse_note_info_from_note_url(url: str) -> NoteUrlInfo:
    """Parse note id and xsec tokens from a Xiaohongshu note URL."""
    parsed = urlparse(url.strip())
    note_id = parsed.path.rstrip("/").split("/")[-1]
    params = extract_url_params_to_dict(url)
    return NoteUrlInfo(
        note_id=note_id,
        xsec_token=params.get("xsec_token", ""),
        xsec_source=params.get("xsec_source", ""),
    )


def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    """Parse creator id and xsec tokens from a Xiaohongshu profile URL or raw user id."""
    raw = url.strip()
    if len(raw) == 24 and all(ch in "0123456789abcdef" for ch in raw.lower()):
        return CreatorUrlInfo(user_id=raw, xsec_token="", xsec_source="")

    match = re.search(r"/user/profile/([^/?]+)", raw)
    if not match:
        raise ValueError(f"无法从链接中解析小红书作者信息: {url}")
    params = extract_url_params_to_dict(url)
    return CreatorUrlInfo(
        user_id=match.group(1),
        xsec_token=params.get("xsec_token", ""),
        xsec_source=params.get("xsec_source", ""),
    )


def extract_note_detail_from_html(note_id: str, html: str) -> dict[str, Any] | None:
    """Extract note detail from XHS HTML initial state."""
    if "noteDetailMap" not in html:
        return None
    match = re.search(r"window\.__INITIAL_STATE__=(\{.*\})</script>", html, re.S)
    if not match:
        return None
    state_text = match.group(1).replace(":undefined", ":null").replace("undefined", '""')
    try:
        state = json.loads(state_text, strict=False)
    except json.JSONDecodeError:
        return None
    note_container = state.get("note", {})
    detail_map = note_container.get("noteDetailMap", {})
    note_entry = detail_map.get(note_id, {})
    if isinstance(note_entry, dict):
        return note_entry.get("note")
    return None


def sanitize_note_title(note: dict[str, Any]) -> str:
    """Build a stable title for UI selection and file naming."""
    title = str(note.get("title") or "").strip()
    if title:
        return title
    desc = str(note.get("desc") or "").strip()
    if desc:
        return desc[:60]
    note_id = str(note.get("note_id") or note.get("noteId") or "xiaohongshu-note")
    return note_id


def note_author_name(note: dict[str, Any]) -> str:
    """Extract author nickname with graceful fallback."""
    user = note.get("user") or {}
    return str(user.get("nickname") or user.get("nick_name") or "未知作者")


def extract_video_candidates(note: dict[str, Any]) -> list[str]:
    """Extract video stream URLs from an XHS note detail."""
    if str(note.get("type", "")).lower() != "video":
        return []
    video_dict = note.get("video") or {}
    consumer = video_dict.get("consumer") or {}
    origin_video_key = consumer.get("origin_video_key") or consumer.get("originVideoKey") or ""
    if origin_video_key:
        return [f"http://sns-video-bd.xhscdn.com/{origin_video_key}"]

    media = video_dict.get("media") or {}
    stream = media.get("stream") or {}
    candidates: list[str] = []
    for codec in ("h264", "h265", "av1"):
        values = stream.get(codec) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            url = item.get("master_url") or item.get("backup_url") or item.get("backup_urls")
            if isinstance(url, list):
                candidates.extend(str(entry) for entry in url if entry)
            elif url:
                candidates.append(str(url))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def extract_image_entries(note: dict[str, Any]) -> list[dict[str, str]]:
    """Extract image urls from an XHS note detail."""
    result: list[dict[str, str]] = []
    for image in note.get("image_list") or []:
        if not isinstance(image, dict):
            continue
        image_url = image.get("url_default") or image.get("url") or ""
        if image_url:
            result.append({"image_url": str(image_url)})
    return result


def build_note_summary(note: dict[str, Any]) -> str:
    """Build a concise note summary for the selection UI."""
    title = sanitize_note_title(note)
    author = note_author_name(note)
    note_type = str(note.get("type") or "normal")
    image_count = len(note.get("image_list") or [])
    if note_type == "video":
        media_hint = "视频"
    elif image_count:
        media_hint = f"图文 {image_count} 张"
    else:
        media_hint = "笔记"
    return f"{title} | {author} | {media_hint}"
