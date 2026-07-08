from __future__ import annotations

import json
import re
from typing import Any

from app.ui.viewmodels.log_detail_payloads import parse_structured_detail_text

CLASSIFICATION_FACTS_KEY = "_classification_facts"

_FACT_KEYS = (
    "raw_level",
    "source",
    "source_lower",
    "action",
    "action_lower",
    "status",
    "status_upper",
    "event_code",
    "event_code_upper",
    "message",
    "message_lower",
    "platform",
    "platform_lower",
    "trace_id",
    "detail_text",
    "detail_lower",
    "legacy_category",
    "combined",
    "combined_upper",
    "combined_lower",
)


def _cached_facts(item: dict[str, Any]) -> dict[str, str] | None:
    cached = item.get(CLASSIFICATION_FACTS_KEY)
    if not isinstance(cached, dict):
        return None
    if all(isinstance(cached.get(key), str) for key in _FACT_KEYS):
        return cached
    return None


def drop_classification_facts(item: dict[str, Any]) -> dict[str, Any]:
    """Remove private classification cache before handing rows to the UI."""
    item.pop(CLASSIFICATION_FACTS_KEY, None)
    return item


def normalized_source(item: dict[str, Any]) -> str:
    value = str(
        item.get("source")
        or item.get("logger")
        or item.get("module")
        or item.get("component")
        or ""
    ).strip()

    if "/" in value:
        left, _right = value.split("/", 1)
        return left.strip()

    return value


def normalized_action(item: dict[str, Any]) -> str:
    value = str(
        item.get("action")
        or item.get("event")
        or item.get("event_type")
        or item.get("operation")
        or ""
    ).strip()

    if value:
        return value

    source = str(item.get("source") or "").strip()
    if "/" in source:
        _left, right = source.split("/", 1)
        return right.strip()

    return ""


def normalized_status_code(item: dict[str, Any]) -> str:
    def pick_from_dict(data: dict[str, Any]) -> str:
        keys = (
            "status_code",
            "状态码",
            "code",
            "event",
            "event_type",
            "status",
            "状态",
            "http_status",
            "api_code",
        )
        for key in keys:
            value = data.get(key)
            text = str(value or "").strip()
            if text:
                return text

        nested_keys = (
            "detail",
            "details",
            "extra",
            "request",
            "response",
            "response_summary",
            "响应摘要",
            "context",
            "上下文",
            "payload",
        )
        for key in nested_keys:
            value = data.get(key)
            if isinstance(value, dict):
                nested = pick_from_dict(value)
                if nested:
                    return nested
        return ""

    candidates: list[str] = []

    direct = pick_from_dict(item)
    if direct:
        candidates.append(direct)

    detail = item.get("detail")
    if isinstance(detail, dict):
        value = pick_from_dict(detail)
        if value:
            candidates.append(value)
    elif isinstance(detail, str) and detail.strip():
        text = detail.strip()
        structured = parse_structured_detail_text(text)
        if structured:
            value = pick_from_dict(structured)
            if value:
                candidates.append(value)

        for pattern in (
            r"状态码\s*[:：]\s*([A-Za-z0-9_./:-]+)",
            r"status_code\s*[:：]\s*([A-Za-z0-9_./:-]+)",
            r"状态\s*[:：]\s*([A-Za-z0-9_./:-]+)",
        ):
            match = re.search(pattern, text)
            if match:
                candidates.append(match.group(1).strip())

    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text

    return ""


def normalized_event_code(item: dict[str, Any]) -> str:
    status = normalized_status_code(item)
    if status:
        return status

    action = normalized_action(item)
    if action:
        text = action.strip()
        text = text.replace("API::", "API_")
        text = re.sub(r"[^A-Za-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if text:
            return text.upper()

    source = normalized_source(item)
    message = str(item.get("message") or item.get("message_summary") or "").strip()
    if source or message:
        seed = f"{source}_{message[:32]}"
        seed = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", seed)
        seed = re.sub(r"_+", "_", seed).strip("_")
        return seed.upper() if seed else "-"

    return "-"


def normalized_raw_level(item: dict[str, Any]) -> str:
    return str(item.get("level") or "").strip().upper()


def classification_facts(item: dict[str, Any]) -> dict[str, str]:
    """Build one normalized fact object for semantic log classification."""
    cached = _cached_facts(item)
    if cached is not None:
        return cached
    return _build_classification_facts(item)


def cache_classification_facts(item: dict[str, Any]) -> dict[str, str]:
    """Precompute classification facts for a worker-local row."""
    cached = _cached_facts(item)
    if cached is not None:
        return cached
    facts = _build_classification_facts(item)
    item[CLASSIFICATION_FACTS_KEY] = facts
    return facts


def _build_classification_facts(item: dict[str, Any]) -> dict[str, str]:
    raw_source = str(
        item.get("source")
        or item.get("logger")
        or item.get("module")
        or item.get("component")
        or ""
    ).strip()

    raw_action = str(
        item.get("action")
        or item.get("event")
        or item.get("event_type")
        or item.get("operation")
        or ""
    ).strip()

    source = raw_source
    action = raw_action
    if "/" in raw_source:
        left, right = raw_source.split("/", 1)
        if left.strip():
            source = left.strip()
        if not action and right.strip():
            action = right.strip()

    detail = item.get("detail")
    detail_text = ""
    if isinstance(detail, dict):
        try:
            detail_text = json.dumps(detail, ensure_ascii=False, default=str)
        except TypeError:
            detail_text = str(detail)
    else:
        detail_text = str(detail or "")

    status = normalized_status_code(item)
    event_code = status or normalized_event_code(item)

    message = str(
        item.get("message")
        or item.get("message_summary")
        or item.get("description")
        or ""
    ).strip()

    platform = str(item.get("platform") or item.get("platform_label") or "").strip()
    trace_id = str(item.get("trace_id") or item.get("traceId") or "").strip()
    raw_level = normalized_raw_level(item)
    legacy_category = str(item.get("category") or "").strip().lower()

    combined = " ".join(
        [
            raw_level,
            source,
            action,
            status,
            event_code,
            message,
            platform,
            trace_id,
            detail_text,
            legacy_category,
        ]
    )

    return {
        "raw_level": raw_level,
        "source": source,
        "source_lower": source.lower(),
        "action": action,
        "action_lower": action.lower(),
        "status": status,
        "status_upper": status.upper(),
        "event_code": event_code,
        "event_code_upper": event_code.upper(),
        "message": message,
        "message_lower": message.lower(),
        "platform": platform,
        "platform_lower": platform.lower(),
        "trace_id": trace_id,
        "detail_text": detail_text,
        "detail_lower": detail_text.lower(),
        "legacy_category": legacy_category,
        "combined": combined,
        "combined_upper": combined.upper(),
        "combined_lower": combined.lower(),
    }


def is_performance_log(item: dict[str, Any]) -> bool:
    combined = classification_facts(item)["combined_upper"]
    tokens = (
        "FRONTEND_RENDER_SLOW",
        "FRONTEND RENDER SLOW",
        "UI_RENDER_SLOW",
        "UI_REFRESH_SLOW",
        "SCHEDULER_SLOW",
        "RENDER_SLOW",
        "FLUSH_SLOW",
        "INTERACTIVE BUDGET",
        "RENDER EXCEEDED",
        "REFRESH CADENCE WAS RELAXED",
        "COALESCED_COUNT",
        "SCHEDULED_COUNT",
        "LAST_FLUSH_DURATION_MS",
        "DURATION_MS",
    )
    return any(token in combined for token in tokens)


def is_system_config_log(item: dict[str, Any]) -> bool:
    facts = classification_facts(item)

    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    event_code = facts["event_code_upper"]
    message = facts["message_lower"]

    config_text = " ".join([source, action, status, event_code, message]).upper()

    config_sources = ("gui", "mainwindow", "applicationcontroller", "system")
    explicit_config_actions = {
        "update_download_options",
        "download_options_updated",
        "change_download_options",
        "set_download_options",
        "update_settings",
        "save_settings",
        "change_save_dir",
        "scan_local_dir",
        "scan_local_dir_finished",
    }
    explicit_config_statuses = (
        "APP_DIR_CHANGED",
        "APP_SCAN_START",
        "APP_SCAN_OK",
        "APP_SETTINGS_UPDATED",
        "APP_CONFIG_UPDATED",
        "DOWNLOAD_OPTIONS_UPDATED",
    )

    if action in explicit_config_actions:
        return True

    if status.startswith(explicit_config_statuses):
        return True

    if event_code.startswith(explicit_config_statuses):
        return True

    if any(src in source for src in config_sources):
        message_tokens = (
            "DOWNLOAD OPTIONS UPDATED",
            "CONCURRENCY=",
            "RETRIES=",
            "AUTO_RETRY",
            "AUTO RETRY",
            "修改线程",
            "线程并发",
            "并发数",
            "重试次数",
            "自动重试",
            "更改目录",
            "保存目录",
            "配置已更新",
            "设置已更新",
        )
        if any(token in config_text for token in message_tokens):
            return True

    return False

def derive_result_type(item: dict[str, Any]) -> str:
    facts = classification_facts(item)

    raw_level = facts["raw_level"]
    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    combined = facts["combined_upper"]

    if raw_level in {"ERROR", "FATAL", "CRITICAL"}:
        return "error"

    if raw_level in {"WARN", "WARNING"}:
        return "warn"

    if raw_level in {"COMMAND", "CMD"}:
        return "command"

    if "FFMPEG" in combined or "COMMAND" in combined or action == "ffmpeg":
        return "command"

    if is_performance_log(item):
        return "warn"

    error_tokens = (
        "ERROR",
        "FAIL",
        "FAILED",
        "EXCEPTION",
        "FATAL",
        "TIMEOUT",
        "ABORT",
        "CONNECTION_RESET",
        "PROXY_ERROR",
        "LOCAL_HLS_PROXY_ERROR",
        "HTTP_4",
        "HTTP_5",
    )
    if any(token in combined for token in error_tokens):
        return "error"

    config_tokens = (
        "DOWNLOAD OPTIONS UPDATED",
        "CONCURRENCY",
        "AUTO_RETRY",
        "AUTO RETRY",
        "RETRIES",
        "THREAD",
        "MAX_CONCURRENT",
    )
    if any(token in combined for token in config_tokens):
        return "info"

    warn_tokens = (
        "WARN",
        "WARNING",
        "SLOW",
        "RETRY",
        "DEGRADED",
        "RATE_LIMIT",
        "SKIP",
        "EMPTY",
        "NOT_FOUND",
    )
    if any(token in combined for token in warn_tokens):
        return "warn"

    success_tokens = (
        "_OK",
        "_SUCCESS",
        "_FINISH",
        "_FINISHED",
        "_COMPLETE",
        "_COMPLETED",
        "_DONE",
        "APP_READY",
        "APP_SCAN_OK",
        "DL_FINISH",
        "APP_DL_FINISH",
        "BILI_MERGE_OK",
        "MERGE_FINISHED",
        "DOWNLOAD_FINISHED",
    )
    if any(token in combined for token in success_tokens):
        return "success"

    message = facts["message_lower"]
    detail = facts["detail_lower"]

    success_message_tokens = (
        "下载完成",
        "下载任务完成",
        "合并完成",
        "音视频合并完成",
        "流请求建立成功",
    )

    if any(token in message for token in success_message_tokens):
        return "success"

    if any(token in detail for token in success_message_tokens):
        return "success"

    if status == "200":
        if (
            "api::" in action
            or action.startswith("api_")
            or "stream_" in action
            or "request" in action
            or "check_login" in action
            or "get_video_info" in action
            or "get_play_url" in action
            or "api" in source
            or "downloader" in source
        ):
            return "success"

    return "info"


def result_display_text(result_type: str, raw_level: str = "") -> str:
    return {
        "info": "INFO",
        "success": "SUCCESS",
        "warn": "WARN",
        "error": "ERROR",
        "command": "CMD",
    }.get(result_type, raw_level or "INFO")


def result_nature_text(result_type: str) -> str:
    return {
        "info": "过程",
        "success": "成功",
        "warn": "预警",
        "error": "错误",
        "command": "命令",
    }.get(result_type, "过程")
