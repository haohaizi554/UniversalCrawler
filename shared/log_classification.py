"""日志事实归一化与结果性质分类。

公开分类函数接收原始或兼容旧字段的日志字典，并先构造字符串事实对象。长规则
链均采用“首个命中即返回”；显式字段、排除规则和终态规则必须保持在宽泛文本
匹配之前，不能只按词表长度或视觉分组随意换序。未识别的结果性质回退为
``info``，归一化字段则使用空字符串或 ``-``，具体契约见各函数 docstring。
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.log_detail_payloads import parse_structured_detail_text

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
    """把日志行交给 UI 前移除私有分类缓存。"""
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
    """按固定来源优先级提取状态码，未找到时返回空字符串。

    输入可同时含顶层字段、字典/字符串 ``detail`` 和嵌套 payload。每层都按
    ``status_code``、中文状态码、code/event/status、HTTP/API code 的顺序取第
    一个非空值；顶层先于 detail，结构化 detail 先于文本正则。该顺序决定冲突
    字段的胜者，不可随意调整。
    """
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
    """生成稳定事件码：状态码优先，其次 action，再次 source/message，最后 ``-``。"""
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
    """返回分类规则使用的字符串事实；存在完整私有缓存时直接复用。"""
    cached = _cached_facts(item)
    if cached is not None:
        return cached
    return _build_classification_facts(item)


def cache_classification_facts(item: dict[str, Any]) -> dict[str, str]:
    """在工作线程日志行上预计算私有事实；交给 UI 前必须移除该缓存。"""
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
    """在归一化组合文本中识别明确的性能诊断标记。"""
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
    """识别显式配置事件，或受限系统来源中的配置消息。"""
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
        "async_scan_local_dir",
        "scan_local_dir_finished",
    }
    explicit_config_statuses = (
        "APP_DIR_CHANGED",
        "APP_SCAN_START",
        "APP_SCAN_OK",
        "WEB_SCAN_START",
        "WEB_SCAN_OK",
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
    """把日志字典分类为 info、success、warn、error 或 command。

    规则按首命中返回：显式 level 最优先，其次命令信号、错误与恢复组合、配置
    信息、一般警告、成功事件码、成功消息/detail，最后是受限上下文中的 HTTP
    200。恢复中的错误必须在一般错误前降为 warn，显式故障 level 又必须位于
    恢复判断之前；宽泛的成功/警告词也不能提前。未命中任何规则时回退 info。
    """
    facts = classification_facts(item)

    raw_level = facts["raw_level"]
    source = facts["source_lower"]
    action = facts["action_lower"]
    status = facts["status_upper"]
    event_signal = " ".join(
        [
            facts["source"],
            facts["action"],
            facts["status"],
            facts["event_code"],
            facts["message"],
        ]
    ).upper()

    if raw_level in {"ERROR", "FATAL", "CRITICAL"}:
        return "error"

    if raw_level in {"WARN", "WARNING"}:
        return "warn"

    if raw_level in {"SUCCESS", "OK"}:
        return "success"

    if raw_level in {"COMMAND", "CMD"}:
        return "command"

    if "FFMPEG" in event_signal or "COMMAND" in event_signal or action == "ffmpeg":
        return "command"

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
    recovery_tokens = (
        "FALLING BACK",
        "FALLBACK",
        "TRYING",
        "RETRYING",
        "DEGRADED TO",
    )
    terminal_recovery_tokens = (
        "FALLBACK FAILED",
        "RETRY FAILED",
        "RETRYING FAILED",
    )
    # details 含配置值和 payload 键，若把它们当作事件语义，普通的
    # ``timeout: 60`` 选项也会被误判为 ERROR。严重级别只从事件信封推断；
    # 上方的显式 level 对真实故障仍具有最高优先级。
    has_error_signal = any(token in event_signal for token in error_tokens)
    is_recovering = any(token in event_signal for token in recovery_tokens)
    recovery_failed = any(token in event_signal for token in terminal_recovery_tokens)
    if has_error_signal and is_recovering and not recovery_failed:
        return "warn"
    if has_error_signal:
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
    if any(token in event_signal for token in config_tokens):
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
    if any(token in event_signal for token in warn_tokens):
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
    if any(token in event_signal for token in success_tokens):
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
    """返回展示标签；未知类型优先保留 raw_level，否则回退 INFO。"""
    return {
        "info": "INFO",
        "success": "SUCCESS",
        "warn": "WARN",
        "error": "ERROR",
        "command": "CMD",
    }.get(result_type, raw_level or "INFO")


def result_nature_text(result_type: str) -> str:
    """返回中文性质标签；未知类型回退为“过程”。"""
    return {
        "info": "过程",
        "success": "成功",
        "warn": "预警",
        "error": "错误",
        "command": "命令",
    }.get(result_type, "过程")
