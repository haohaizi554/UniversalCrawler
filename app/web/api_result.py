"""Helpers for consistent Web API success/error responses."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

def error_result(
    message: str,
    *,
    http_status: int = 400,
    error_key: str = "error",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "error", error_key: message, "http_status": http_status}
    payload.update(extra)
    return payload

def is_error_result(payload: Any) -> bool:
    return isinstance(payload, dict) and (payload.get("status") == "error" or "error" in payload)

def finalize_api_result(payload: Any, *, default_error_status: int = 400) -> Any:
    if not is_error_result(payload):
        return payload
    body = dict(payload)
    status_code = int(body.pop("http_status", default_error_status))
    return JSONResponse(body, status_code=status_code)
