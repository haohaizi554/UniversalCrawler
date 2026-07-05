from __future__ import annotations

import re
from typing import Any

from app.ui.localization import normalize_language, tr


_LOCAL_FILE_LOADED_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"已加载\s*(?P<count>\d+)\s*个本地文件\s*"
    r"\(视频[:：]\s*(?P<videos>\d+)\s*,\s*图片[:：]\s*(?P<images>\d+)\)$"
)
_SCAN_DIR_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"正在扫描目录[:：]\s*(?P<path>.+)$"
)
_DOWNLOAD_DONE_RE = re.compile(r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?下载完成[:：]\s*(?P<title>.+)$")
_DOWNLOAD_FAILED_RE = re.compile(
    r"^(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
    r"下载失败\s*\[(?P<title>.+?)\][：:]\s*(?P<error>.+)$"
)


def _plural(value: str, singular: str, plural: str) -> str:
    return singular if str(value) == "1" else plural


def _localize_english_dynamic(text: str) -> str:
    match = _LOCAL_FILE_LOADED_RE.match(text)
    if match:
        count = match.group("count")
        noun = _plural(count, "file", "files")
        return (
            f"{match.group('prefix') or ''}Loaded {count} local {noun} "
            f"(videos: {match.group('videos')}, images: {match.group('images')})"
        )

    match = _SCAN_DIR_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Scanning directory: {match.group('path')}"

    match = _DOWNLOAD_DONE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Download completed: {match.group('title')}"

    match = _DOWNLOAD_FAILED_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Download failed [{match.group('title')}]: {match.group('error')}"

    return text


def localize_log_text(text: object, language: str | None) -> str:
    value = str(text or "")
    if not value:
        return value
    normalized = normalize_language(language)
    translated = tr(value, normalized)
    if translated != value:
        return translated
    if normalized == "en-US":
        return _localize_english_dynamic(value)
    return translated


def localize_log_event_code(code: object, language: str | None) -> str:
    value = str(code or "")
    if normalize_language(language) != "en-US" or not value or value == "-":
        return value

    loaded = re.match(
        r"^(?P<prefix>[A-Z0-9_]+)_已加载_(?P<count>\d+)_个本地文件_视频_(?P<videos>\d+)_图片_(?P<images>\d+)$",
        value,
    )
    if loaded:
        return (
            f"{loaded.group('prefix')}_LOADED_{loaded.group('count')}_LOCAL_FILES"
            f"_VIDEOS_{loaded.group('videos')}_IMAGES_{loaded.group('images')}"
        )

    replacements = {
        "日志缓存已刷新": "LOG_CACHE_REFRESHED",
        "正在扫描目录": "SCANNING_DIRECTORY",
        "开始扫描本地媒体目录": "LOCAL_MEDIA_SCAN_START",
        "本地媒体目录扫描完成": "LOCAL_MEDIA_SCAN_OK",
        "主窗口初始化完成": "MAIN_WINDOW_READY",
        "应用开始初始化": "APP_INIT",
        "已切换到浅色主题": "THEME_LIGHT",
        "已切换到深色主题": "THEME_DARK",
        "爬虫任务结束": "CRAWL_FINISH",
    }
    result = value
    for source, target in replacements.items():
        result = result.replace(source, target)
    result = re.sub(r"[^A-Za-z0-9_]+", "_", result)
    result = re.sub(r"_+", "_", result).strip("_")
    return result.upper() if result else value


def localize_log_payload(payload: Any, language: str | None) -> Any:
    if isinstance(payload, dict):
        return {key: localize_log_payload(value, language) for key, value in payload.items()}
    if isinstance(payload, list):
        return [localize_log_payload(value, language) for value in payload]
    if isinstance(payload, tuple):
        return tuple(localize_log_payload(value, language) for value in payload)
    if isinstance(payload, str):
        return localize_log_text(payload, language)
    return payload
