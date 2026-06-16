"""Web 层统一调试日志桥接。"""

from __future__ import annotations

from typing import Any

from app.debug_logger import debug_logger


def log_web_event(
    component: str,
    action: str,
    message: str,
    *,
    level: str = "INFO",
    status_code: int | str | None = None,
    context: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """将 Web 基础设施日志统一收口到 debug_logger。"""
    debug_logger.log(
        component=component,
        action=action,
        level=level,
        message=message,
        status_code=status_code,
        context=context,
        details=details,
    )


def log_web_exception(
    component: str,
    action: str,
    exc: Exception,
    *,
    context: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """记录 Web 层异常，保留统一结构化上下文。"""
    debug_logger.log_exception(
        component=component,
        action=action,
        exc=exc,
        context=context,
        details=details,
    )
