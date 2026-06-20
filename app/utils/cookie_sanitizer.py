"""Cookie transport sanitization helpers shared by models and services."""

from __future__ import annotations

from typing import Any

MINIMAL_COOKIE_NAMES: dict[str, tuple[str, ...]] = {
    "douyin": ("sessionid_ss",),
    "bilibili": ("SESSDATA",),
    "kuaishou": ("userId",),
    "xiaohongshu": ("a1",),
}

def _safe_to_string(value: Any) -> str | None:
    try:
        return str(value)
    except (TypeError, ValueError):
        return None

def required_cookie_names_for_source(source: str | None) -> tuple[str, ...]:
    return MINIMAL_COOKIE_NAMES.get(str(source or "").strip().lower(), ())

def extract_cookie_list(payload: list[dict] | dict | None) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
        return payload["cookies"]
    return []

def extract_cookie_dict(payload: list[dict] | dict | None) -> dict[str, str]:
    if isinstance(payload, dict) and "cookies" not in payload:
        result: dict[str, str] = {}
        for key, value in payload.items():
            safe_key = _safe_to_string(key)
            safe_value = _safe_to_string(value)
            if safe_key is not None and safe_value is not None:
                result[safe_key] = safe_value
        return result
    cookies = extract_cookie_list(payload)
    result: dict[str, str] = {}
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            safe_name = _safe_to_string(name)
            safe_value = _safe_to_string(value)
            if safe_name is not None and safe_value is not None:
                result[safe_name] = safe_value
    return result

def build_cookie_string(payload: list[dict] | dict | None, required_cookie: str | None = None) -> str:
    cookie_dict = extract_cookie_dict(payload)
    if required_cookie and required_cookie not in cookie_dict:
        return ""
    return "; ".join(f"{name}={value}" for name, value in cookie_dict.items())

def minimize_cookie_dict(source: str | None, payload: list[dict] | dict | None) -> dict[str, str]:
    cookie_dict = extract_cookie_dict(payload)
    keep_names = required_cookie_names_for_source(source)
    if not keep_names:
        return {}
    return {name: cookie_dict[name] for name in keep_names if name in cookie_dict}

def minimize_cookie_string(source: str | None, payload: list[dict] | dict | str | None) -> str:
    keep_names = required_cookie_names_for_source(source)
    if not keep_names:
        return ""
    if isinstance(payload, str):
        cookie_dict: dict[str, str] = {}
        for pair in payload.split(";"):
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            safe_name = _safe_to_string(name.strip())
            safe_value = _safe_to_string(value.strip())
            if safe_name and safe_value is not None:
                cookie_dict[safe_name] = safe_value
    else:
        cookie_dict = extract_cookie_dict(payload)
    minimized = {name: cookie_dict[name] for name in keep_names if name in cookie_dict}
    return "; ".join(f"{name}={value}" for name, value in minimized.items())
