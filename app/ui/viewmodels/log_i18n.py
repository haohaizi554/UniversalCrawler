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
_DYNAMIC_PREFIX = r"(?P<prefix>[\U0001F300-\U0001FAFF\u2600-\u27BF]*\s*)?"
_CRAWL_CONFIRM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}用户确认了\s*(?P<count>\d+)\s*个任务$")
_CRAWL_FINAL_CONFIRM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}最终确认\s*(?P<count>\d+)\s*个.*$")
_CRAWL_START_RE = re.compile(rf"^{_DYNAMIC_PREFIX}启动\s*(?P<platform>.*?)\s*爬虫任务$")
_TASK_START_MODE_RE = re.compile(rf"^{_DYNAMIC_PREFIX}启动任务\s*\|\s*模式[:：]\s*(?P<mode>.*)$")
_SCAN_FINISH_RE = re.compile(rf"^{_DYNAMIC_PREFIX}扫描结束[，,]\s*共\s*(?P<count>\d+)(?P<tail>.*)$")
_FETCH_OK_RE = re.compile(rf"^{_DYNAMIC_PREFIX}获取成功\s*(?P<detail>.*)$")
_PARSE_STREAM_RE = re.compile(rf"^{_DYNAMIC_PREFIX}解析流[:：]\s*(?P<detail>.*)$")
_EXPANDING_RE = re.compile(rf"^{_DYNAMIC_PREFIX}正在展开[:：]\s*(?P<detail>.*)$")
_PIPELINE_RE = re.compile(rf"^{_DYNAMIC_PREFIX}流水线已建立[:：]\s*(?P<detail>.*)$")

_EN_DYNAMIC_REPLACEMENTS = (
    ("已刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL successfully"),
    ("重新刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"),
    ("重刷新 B站 CDN URL 成功", "Refreshed B-site CDN URL again successfully"),
    ("B站 audio 流连接断开", "B-site audio stream disconnected"),
    ("B站 video 流连接断开", "B-site video stream disconnected"),
    ("爬虫任务结束", "Crawl task finished"),
    ("Bilibili 爬虫任务结束", "Bilibili crawl task finished"),
    ("爬虫发现可下载资源", "Crawler found downloadable resources"),
    ("检查 Bilibili 登录状态", "Checking Bilibili login status"),
    ("已登录，Cookie", "Logged in; Cookie"),
    ("下载任务开始执行", "Download task started"),
    ("下载任务完成", "Download task completed"),
    ("准备下载 Bilibili 音", "Preparing Bilibili audio download"),
    ("准备合并 Bilibili 音", "Preparing to merge Bilibili audio"),
    ("Bilibili 音视频合并", "Bilibili audio/video merge"),
    ("分发队列", "Dispatched queue"),
    ("释放下载", "Released download"),
)

_EVENT_CODE_SEGMENT_ALIASES = {
    "GUI": "图形界面",
    "WebUI": "网页端",
    "MainWindow": "主窗口",
    "ApplicationContext": "应用上下文",
}


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

    match = _CRAWL_CONFIRM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}User confirmed {match.group('count')} tasks"

    match = _CRAWL_FINAL_CONFIRM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Final confirmation: {match.group('count')} tasks"

    match = _CRAWL_START_RE.match(text)
    if match:
        platform = match.group("platform").strip()
        return f"{match.group('prefix') or ''}Started {platform} crawl task"

    match = _TASK_START_MODE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Started task | mode: {match.group('mode')}"

    match = _SCAN_FINISH_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Scan finished, total {match.group('count')}{match.group('tail')}"

    match = _FETCH_OK_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Fetched successfully {match.group('detail')}".rstrip()

    match = _PARSE_STREAM_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Parsed stream: {match.group('detail')}"

    match = _EXPANDING_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Expanding: {match.group('detail')}"

    match = _PIPELINE_RE.match(text)
    if match:
        return f"{match.group('prefix') or ''}Pipeline established: {match.group('detail')}"

    result = text
    for source, target in _EN_DYNAMIC_REPLACEMENTS:
        result = result.replace(source, target)
    return result


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
    normalized = normalize_language(language)
    if not value or value == "-":
        return value
    if normalized != "en-US":
        if normalized == "zh-TW" and "_" in value:
            return "_".join(
                localize_log_text(_EVENT_CODE_SEGMENT_ALIASES.get(part, part), normalized)
                for part in value.split("_")
            )
        return localize_log_text(value, normalized)

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
        localized: dict[Any, Any] = {}
        for key, value in payload.items():
            if str(key) in {"status_code", "event_code"}:
                localized[key] = localize_log_event_code(value, language)
            else:
                localized[key] = localize_log_payload(value, language)
        return localized
    if isinstance(payload, list):
        return [localize_log_payload(value, language) for value in payload]
    if isinstance(payload, tuple):
        return tuple(localize_log_payload(value, language) for value in payload)
    if isinstance(payload, str):
        return localize_log_text(payload, language)
    return payload
