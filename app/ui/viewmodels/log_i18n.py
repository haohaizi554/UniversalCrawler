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
    ("Bilibili 爬虫任务结束", "Bilibili crawl task finished"),
    ("爬虫任务结束", "Crawl task finished"),
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

_NON_EN_DYNAMIC_EXACT = {
    "fetch video detail": {
        "zh-CN": "获取视频详情",
        "zh-TW": "取得影片詳情",
    },
    "Download task has been queued": {
        "zh-CN": "下载任务已入队",
        "zh-TW": "下載任務已入隊",
    },
    "Dispatched queued task to a download worker": {
        "zh-CN": "已将排队任务分发给下载线程",
        "zh-TW": "已將排隊任務分發給下載執行緒",
    },
    "Released download concurrency slot": {
        "zh-CN": "已释放下载并发槽位",
        "zh-TW": "已釋放下載並發槽位",
    },
    "Download task started": {
        "zh-CN": "下载任务开始执行",
        "zh-TW": "下載任務開始執行",
    },
    "Download task completed": {
        "zh-CN": "下载任务完成",
        "zh-TW": "下載任務完成",
    },
    "Download task has been queued for execution": {
        "zh-CN": "下载任务已加入执行队列",
        "zh-TW": "下載任務已加入執行隊列",
    },
    "Frontend render exceeded the interactive budget; refresh cadence was relaxed": {
        "zh-CN": "前端渲染超过交互预算，已降低刷新频率",
        "zh-TW": "前端渲染超出互動預算；已降低刷新頻率",
    },
    "App initialization started": {
        "zh-CN": "应用开始初始化",
        "zh-TW": "應用開始初始化",
    },
    "Main window initialized": {
        "zh-CN": "主窗口初始化完成",
        "zh-TW": "主視窗初始化完成",
    },
    "Local media folder scan completed": {
        "zh-CN": "本地媒体目录扫描完成",
        "zh-TW": "本機媒體目錄掃描完成",
    },
    "Started scanning local media folder": {
        "zh-CN": "开始扫描本地媒体目录",
        "zh-TW": "開始掃描本機媒體目錄",
    },
    "Web started scanning local media folder": {
        "zh-CN": "Web 端开始扫描本地媒体目录",
        "zh-TW": "Web 端開始掃描本機媒體目錄",
    },
    "Web started scanning local media folder (async)": {
        "zh-CN": "Web 端开始扫描本地媒体目录（异步）",
        "zh-TW": "Web 端開始掃描本機媒體目錄（非同步）",
    },
    "Clear queue failed": {
        "zh-CN": "清空队列失败",
        "zh-TW": "清空隊列失敗",
    },
    "setting update failed": {
        "zh-CN": "设置更新失败",
        "zh-TW": "設定更新失敗",
    },
    "download options update failed": {
        "zh-CN": "下载选项更新失败",
        "zh-TW": "下載選項更新失敗",
    },
    "download paused": {
        "zh-CN": "下载已暂停",
        "zh-TW": "下載已暫停",
    },
}

_BILIBILI_ROUTE_ALIASES = {
    "direct BV video": {
        "zh-CN": "直接 BV 视频",
        "zh-TW": "直接 BV 影片",
    },
    "direct BV video with search fallback": {
        "zh-CN": "直接 BV 视频，失败后回退搜索",
        "zh-TW": "直接 BV 影片，失敗後回退搜尋",
    },
    "direct av video": {
        "zh-CN": "直接 av 视频",
        "zh-TW": "直接 av 影片",
    },
    "keyword search": {
        "zh-CN": "关键词搜索",
        "zh-TW": "關鍵字搜尋",
    },
}

_STRUCTURED_SEGMENT_ALIASES = {
    "System": {"zh-CN": "系统", "zh-TW": "系統"},
    "系统": {"en-US": "System", "zh-TW": "系統"},
    "系統": {"zh-CN": "系统", "en-US": "System"},
    "MainWindow": {"zh-CN": "主窗口", "zh-TW": "主視窗"},
    "主窗口": {"en-US": "MainWindow", "zh-TW": "主視窗"},
    "主視窗": {"zh-CN": "主窗口", "en-US": "MainWindow"},
    "ApplicationContext": {"zh-CN": "应用上下文", "zh-TW": "應用上下文"},
    "应用上下文": {"en-US": "ApplicationContext", "zh-TW": "應用上下文"},
    "應用上下文": {"zh-CN": "应用上下文", "en-US": "ApplicationContext"},
    "WebUI": {"zh-CN": "网页端", "zh-TW": "網頁端"},
    "网页端": {"en-US": "WebUI", "zh-TW": "網頁端"},
    "網頁端": {"zh-CN": "网页端", "en-US": "WebUI"},
}

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


def _localized(language_map: dict[str, str], language: str) -> str:
    return language_map.get(language) or language_map.get("zh-CN") or ""


def _localize_structured_segments(text: str, language: str) -> str:
    if " · " not in text and " / " not in text:
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(text)
        if mapped:
            return _localized(mapped, language) or text
        return text
    parts = re.split(r"(\s+·\s+|\s+/\s+)", text)
    changed = False
    translated_parts: list[str] = []
    for part in parts:
        if re.fullmatch(r"\s*(?:·|/)\s*", part):
            translated_parts.append(part)
            continue
        translated = tr(part, language)
        mapped = _STRUCTURED_SEGMENT_ALIASES.get(part)
        if mapped:
            translated = _localized(mapped, language) or translated
        changed = changed or translated != part
        translated_parts.append(translated)
    return "".join(translated_parts) if changed else text


def _localize_non_english_dynamic(text: str, language: str) -> str:
    mapped = _NON_EN_DYNAMIC_EXACT.get(text)
    if mapped:
        return _localized(mapped, language)

    match = re.match(r"^Bilibili route:\s*(?P<route>.+)$", text)
    if match:
        route = match.group("route").strip()
        browser_scan = re.match(r"^browser scan\s*(?P<target>.*)$", route)
        if browser_scan:
            target = browser_scan.group("target").strip()
            prefix = "Bilibili 路由：浏览器扫描" if language == "zh-CN" else "Bilibili 路由：瀏覽器掃描"
            return f"{prefix} {target}".rstrip()
        route_label = _BILIBILI_ROUTE_ALIASES.get(route)
        if route_label:
            return f"Bilibili 路由：{_localized(route_label, language)}"

    match = re.match(r"^Bilibili browser producer error:\s*(?P<error>.+)$", text)
    if match:
        prefix = "Bilibili 浏览器生产线程异常" if language == "zh-CN" else "Bilibili 瀏覽器生產執行緒異常"
        return f"{prefix}：{match.group('error')}"

    match = re.match(r"^XiaoHongShu user confirmed\s*(?P<count>\d+)\s*candidates; starting parse-to-download pipeline\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书用户已确认 {count} 个候选，开始解析到下载流水线。"
            if language == "zh-CN"
            else f"小紅書使用者已確認 {count} 個候選，開始解析到下載流水線。"
        )

    match = re.match(r"^XiaoHongShu found\s*(?P<count>\d+)\s*candidates; waiting for user confirmation before parsing details\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书发现 {count} 个候选，等待用户确认后解析详情。"
            if language == "zh-CN"
            else f"小紅書發現 {count} 個候選，等待使用者確認後解析詳情。"
        )

    match = re.match(r"^XiaoHongShu confirmed pipeline is active:\s*(?P<count>\d+)\s*selected candidates\.$", text)
    if match:
        count = match.group("count")
        return (
            f"小红书流水线已激活：{count} 个已选候选。"
            if language == "zh-CN"
            else f"小紅書流水線已啟用：{count} 個已選候選。"
        )

    return text


def localize_log_text(text: object, language: str | None) -> str:
    value = str(text or "")
    if not value:
        return value
    normalized = normalize_language(language)
    translated = tr(value, normalized)
    if translated != value:
        return translated
    structured = _localize_structured_segments(value, normalized)
    if structured != value:
        return structured
    if normalized == "en-US":
        return _localize_english_dynamic(value)
    return _localize_non_english_dynamic(value, normalized)


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
