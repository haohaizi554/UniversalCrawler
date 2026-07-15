from __future__ import annotations

import html
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.debug_logger import debug_logger
from shared.localization import normalize_language, tr
from app.ui.viewmodels.latest_worker import LatestRequestWorker
from app.ui.viewmodels.sequential_worker import SequentialRequestWorker
from shared.log_classification import (
    derive_result_type,
    normalized_event_code,
    normalized_raw_level,
    normalized_status_code,
    result_display_text,
    result_nature_text,
)
from shared.log_detail_payloads import (
    build_log_detail_payload,
    extract_trace_id,
    format_json_text,
    normalize_detail_payload,
)
from shared.log_display import format_platform_label, scope_display_text, stage_display_text
from shared.log_i18n import localize_log_event_code, localize_log_payload, localize_log_text
from shared.log_pipeline_rules import derive_event_stage, derive_log_scope
from shared.log_platforms import PlatformUiMeta


@dataclass(frozen=True)
class LogDetailRequest:
    sequence: int
    item_id: str
    item: Mapping[str, Any]
    language: str
    platform_options: tuple[PlatformUiMeta, ...]
    platform_meta_by_id: Mapping[str, PlatformUiMeta]


@dataclass(frozen=True)
class LogDetailResult:
    sequence: int
    item_id: str
    language: str
    time_text: str
    source_text: str
    platform_text: str
    trace_id: str
    message_text: str
    raw_message: str
    raw_level: str
    level_style_key: str
    status_text: str
    scope_text: str
    stage_text: str
    event_code_text: str
    event_code_tooltip: str
    detail_payload: Any
    detail_json_text: str
    detail_json_escaped: str
    full_payload: dict[str, Any]
    full_payload_text: str
    stack_text: str
    has_stack: bool


@dataclass(frozen=True)
class LogDetailExportRequest:
    sequence: int
    item_id: str
    path: str
    text: str


@dataclass(frozen=True)
class LogDetailExportResult:
    sequence: int
    item_id: str
    path: str
    ok: bool
    error: str = ""


LOG_DETAIL_CACHE_PREFIX = "frontend.log_detail."


def _platform_cache_payload(platforms: tuple[PlatformUiMeta, ...]) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            str(meta.id or ""),
            str(meta.label or ""),
            str(meta.emoji or ""),
            str(meta.icon_path or ""),
        )
        for meta in platforms
    )


def _log_detail_cache_key(request: LogDetailRequest) -> str:
    """把日志原始 payload 和平台元信息一起纳入缓存 key。"""

    payload = {
        "item_id": request.item_id,
        "language": normalize_language(request.language),
        "item": dict(request.item),
        "platforms": _platform_cache_payload(tuple(request.platform_options)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8", errors="replace")
    return f"{LOG_DETAIL_CACHE_PREFIX}{sha256(encoded).hexdigest()}"


def build_cached_log_detail_result(
    request: LogDetailRequest,
    *,
    cache_service: Any | None = None,
    ttl_seconds: float = 300.0,
) -> LogDetailResult:
    """构建日志详情，并用短 TTL 缓存规避重复 JSON 格式化开销。"""

    if cache_service is None:
        return build_log_detail_result(request)

    cache_key = _log_detail_cache_key(request)
    try:
        cached = cache_service.get(cache_key)
    except Exception as exc:
        debug_logger.log_exception(
            "LogDetailWorker",
            "read_log_detail_cache",
            exc,
            details={"item_id": request.item_id},
        )
        cached = None
    if isinstance(cached, LogDetailResult):
        return replace(
            cached,
            sequence=request.sequence,
            item_id=request.item_id,
            language=normalize_language(request.language),
        )

    result = build_log_detail_result(request)
    try:
        # 详情结果是短期 UI dataclass，没有跨启动复用价值；只存内存也避免持久化任意 Python 对象。
        cache_service.set(cache_key, result, ttl_seconds=ttl_seconds, persist=False)
    except Exception as exc:
        debug_logger.log_exception(
            "LogDetailWorker",
            "write_log_detail_cache",
            exc,
            details={"item_id": request.item_id},
        )
    return result


def _translate_platform_display(
    text: object,
    *,
    language: str,
    platform_meta_by_id: Mapping[str, PlatformUiMeta],
) -> str:
    translated = str(text or "")
    for meta in platform_meta_by_id.values():
        if meta.label:
            translated = translated.replace(meta.label, tr(meta.label, language))
    return tr(translated, language)


def build_log_detail_result(request: LogDetailRequest) -> LogDetailResult:
    """把一条原始日志展开为详情页需要的所有展示字段。"""

    language = normalize_language(request.language)
    item = dict(request.item)
    status_code = normalized_status_code(item)
    platform_text = _translate_platform_display(
        format_platform_label(item, request.platform_options, request.platform_meta_by_id),
        language=language,
        platform_meta_by_id=request.platform_meta_by_id,
    )
    trace_id = extract_trace_id(item, status_code=status_code)
    raw_message = str(item.get("message") or item.get("message_summary") or "")
    message_text = localize_log_text(raw_message or "-", language)

    raw_level = str(item.get("raw_level") or normalized_raw_level(item) or "")
    result_type = str(item.get("result_type") or derive_result_type(item) or "")
    scope = str(item.get("log_scope") or derive_log_scope(item) or "")
    stage = str(item.get("event_stage") or derive_event_stage(item) or "")
    event_code = str(item.get("event_code") or normalized_event_code(item) or "")
    detail_payload = localize_log_payload(normalize_detail_payload(item, status_code=status_code), language)
    full_payload = localize_log_payload(
        build_log_detail_payload(
            item,
            platform_label=platform_text,
            status_code=status_code,
        ),
        language,
    )
    stack_text = str(item.get("stack") or "").strip()
    detail_json_text = format_json_text(detail_payload)
    return LogDetailResult(
        sequence=request.sequence,
        item_id=request.item_id,
        language=language,
        time_text=str(item.get("time") or "-"),
        source_text=localize_log_text(str(item.get("source") or "-"), language),
        platform_text=platform_text,
        trace_id=trace_id or "",
        message_text=message_text,
        raw_message=raw_message,
        raw_level=raw_level or "-",
        level_style_key=result_display_text(result_type, raw_level),
        status_text=tr(result_nature_text(result_type), language),
        scope_text=tr(scope_display_text(scope), language),
        stage_text=tr(stage_display_text(stage), language),
        event_code_text=localize_log_event_code(event_code, language) or "-",
        event_code_tooltip=event_code,
        detail_payload=detail_payload,
        detail_json_text=detail_json_text,
        detail_json_escaped=html.escape(detail_json_text),
        full_payload=full_payload,
        full_payload_text=format_json_text(full_payload),
        stack_text=stack_text,
        has_stack=bool(stack_text and stack_text != "无"),
    )


class LogDetailWorker:
    """日志详情 worker：详情切换时只保留最新选中项。"""

    def __init__(
        self,
        on_result: Callable[[LogDetailResult], None],
        *,
        cache_service: Any | None = None,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self._cache_lock = threading.RLock()
        self._cache_service = cache_service
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._worker = LatestRequestWorker(
            name="log-detail-worker",
            on_result=on_result,
            process=self._process,
        )

    def set_cache_service(self, cache_service: Any | None) -> None:
        with self._cache_lock:
            self._cache_service = cache_service

    def submit(self, request: LogDetailRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    def _process(self, request: LogDetailRequest) -> LogDetailResult:
        try:
            with self._cache_lock:
                cache_service = self._cache_service
                ttl_seconds = self._cache_ttl_seconds
            return build_cached_log_detail_result(
                request,
                cache_service=cache_service,
                ttl_seconds=ttl_seconds,
            )
        except Exception as exc:
            debug_logger.log_exception(
                "LogDetailWorker",
                "build_log_detail_result",
                exc,
                details={"sequence": request.sequence, "item_id": request.item_id},
            )
            return LogDetailResult(
                sequence=request.sequence,
                item_id=request.item_id,
                language=normalize_language(request.language),
                time_text="-",
                source_text="-",
                platform_text="-",
                trace_id="",
                message_text="-",
                raw_message="",
                raw_level="-",
                level_style_key="INFO",
                status_text="-",
                scope_text="-",
                stage_text="-",
                event_code_text="-",
                event_code_tooltip="",
                detail_payload={},
                detail_json_text="{}",
                detail_json_escaped="{}",
                full_payload={},
                full_payload_text="{}",
                stack_text="",
                has_stack=False,
            )


class LogDetailExportWorker:
    """按序写出日志详情文件。

    GUI 线程只负责文件对话框和反馈；可能较大的 payload 由本 worker 写入，
    使日志查看过程保持响应。
    """

    def __init__(self, on_result: Callable[[LogDetailExportResult], None]) -> None:
        self._worker = SequentialRequestWorker(
            name="log-detail-export-worker",
            on_result=on_result,
            process=self._write,
        )

    def submit(self, request: LogDetailExportRequest) -> None:
        self._worker.submit(request)

    def shutdown(self) -> None:
        self._worker.shutdown()

    @staticmethod
    def _write(request: LogDetailExportRequest) -> LogDetailExportResult:
        try:
            Path(request.path).write_text(request.text, encoding="utf-8")
        except OSError as exc:
            return LogDetailExportResult(
                sequence=request.sequence,
                item_id=request.item_id,
                path=request.path,
                ok=False,
                error=str(exc),
            )
        return LogDetailExportResult(
            sequence=request.sequence,
            item_id=request.item_id,
            path=request.path,
            ok=True,
        )
