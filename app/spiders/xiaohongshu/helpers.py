"""小红书共享解析辅助函数。"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.utils.filenames import sanitize_filename

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
    nickname: str = ""
    red_id: str = ""
    note_hint: str = ""

@dataclass(slots=True)
class CreatorLookupInfo:
    keyword: str

def extract_url_params_to_dict(url: str) -> dict[str, str]:
    """把查询参数解析成单值字典。"""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return {key: values[-1] for key, values in params.items() if values}

def extract_first_url(raw_text: str) -> str:
    """从复制的分享文案提取首个 URL；没有 URL 时返回清理后的原文。"""
    raw = str(raw_text or "").strip()
    match = re.search(r"https?://[^\s`，。！？；;,)）\]'\"]+", raw)
    candidate = match.group(0) if match else raw
    return candidate.rstrip("，。！？；;,.!?)）]}'\"")

def is_note_url(text: str) -> bool:
    lowered = text.lower()
    return "xiaohongshu.com/explore/" in lowered or "xiaohongshu.com/discovery/item/" in lowered

def is_creator_url(text: str) -> bool:
    return "xiaohongshu.com/user/profile/" in text.lower()

def parse_creator_lookup_input(text: str) -> CreatorLookupInfo | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    prefixes = ("小红书号:", "小红书号：", "账号:", "账号：", "user:", "uid:", "redid:")
    lowered = raw.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            keyword = raw[len(prefix):].strip().lstrip("@")
            return CreatorLookupInfo(keyword=keyword) if keyword else None
    if raw.startswith("@") and len(raw) > 1:
        return CreatorLookupInfo(keyword=raw[1:].strip())
    if raw.isdigit() and len(raw) >= 6:
        return CreatorLookupInfo(keyword=raw)
    return None

def parse_note_info_from_note_url(url: str) -> NoteUrlInfo:
    """从小红书笔记 URL 解析笔记 ID 和 xsec 参数。"""
    parsed = urlparse(url.strip())
    note_id = parsed.path.rstrip("/").split("/")[-1]
    params = extract_url_params_to_dict(url)
    return NoteUrlInfo(
        note_id=note_id,
        xsec_token=params.get("xsec_token", ""),
        xsec_source=params.get("xsec_source", ""),
    )

def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    """从小红书作者 URL 或原始用户 ID 解析作者与 xsec 参数。"""
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
    """从小红书 HTML 初始状态中提取笔记详情。"""
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
    """生成适合 UI 选择列表和文件命名的稳定标题。"""
    title = str(note.get("title") or "").strip()
    if title:
        if sanitize_filename(title) != "untitled":
            return title[:60]
    desc = str(note.get("desc") or "").strip()
    if desc:
        if sanitize_filename(desc) != "untitled":
            return desc[:60]
    note_id = str(note.get("note_id") or note.get("noteId") or "xiaohongshu-note")
    return note_id

def note_author_name(note: dict[str, Any]) -> str:
    """提取作者昵称，缺失时使用兜底名称。"""
    user = note.get("user") or {}
    return str(user.get("nickname") or user.get("nick_name") or "未知作者")

def extract_video_candidates(note: dict[str, Any]) -> list[str]:
    """从小红书笔记详情提取视频流候选 URL。"""
    if str(note.get("type", "")).lower() != "video":
        return []
    video_dict = note.get("video") or {}
    consumer = video_dict.get("consumer") or {}
    origin_video_key = consumer.get("origin_video_key") or consumer.get("originVideoKey") or ""
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
            for key in ("master_url", "backup_url", "backup_urls"):
                url = item.get(key)
                if isinstance(url, list):
                    candidates.extend(str(entry) for entry in url if entry)
                elif url:
                    candidates.append(str(url))
    if origin_video_key:
        candidates.append(f"http://sns-video-bd.xhscdn.com/{origin_video_key}")
    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    def _candidate_score(url: str) -> tuple[int, int, int, int, int]:
        lowered = url.lower()
        bak_rank = 0 if "sns-bak" in lowered else 1
        no_watermark_rank = 0 if "_114." in lowered else 1
        medium_rank = 0 if "_115." in lowered or "_130." in lowered or "_108." in lowered else 1
        origin_penalty = 1 if "sns-video-bd" in lowered else 0
        watermark_penalty = 1 if "_259." in lowered else 0
        return (bak_rank, no_watermark_rank, medium_rank, origin_penalty, watermark_penalty)
    deduped.sort(key=_candidate_score)
    return deduped

def extract_image_entries(note: dict[str, Any]) -> list[dict[str, str]]:
    """从小红书笔记详情提取图片 URL。"""
    result: list[dict[str, str]] = []
    for image in note.get("image_list") or []:
        if not isinstance(image, dict):
            continue
        image_url = image.get("url_default") or image.get("url") or ""
        if image_url:
            result.append({"image_url": str(image_url)})
    return result

def build_note_summary(note: dict[str, Any]) -> str:
    """为选择界面生成简洁的笔记摘要。"""
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
