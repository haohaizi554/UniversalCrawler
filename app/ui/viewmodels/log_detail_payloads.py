from __future__ import annotations

import json
import re
from typing import Any


LOG_EMOJI_PREFIX_RE = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]+")


def soft_wrap_text(text: str) -> str:
    value = str(text or "")
    for sep in ("\\", "/", "_", "-"):
        value = value.replace(sep, f"{sep}\u200b")
    return value


def strip_leading_emoji(text: str) -> str:
    return LOG_EMOJI_PREFIX_RE.sub("", str(text or "").strip()).strip()


def looks_like_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if ":\\" in text or text.startswith("/") or text.startswith("\\\\"):
        return True
    return "\\" in text and len(text) >= 8


def extract_message_payload(message: str) -> dict[str, Any] | None:
    clean = strip_leading_emoji(message)
    if ":" not in clean:
        return None
    before, after = clean.split(":", 1)
    before = before.strip()
    after = after.strip()
    if looks_like_path(after):
        return {"description": before, "path": after}
    return None


def refine_description_path(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    description = str(result.get("description") or "").strip()
    if description:
        extracted = extract_message_payload(description)
        if extracted:
            result["description"] = extracted["description"]
            result.setdefault("path", extracted["path"])
        else:
            result["description"] = strip_leading_emoji(description)
    detail_text = str(result.get("detail") or "").strip()
    if detail_text and "description" not in result:
        extracted = extract_message_payload(detail_text)
        if extracted:
            result.update(extracted)
        else:
            result["description"] = strip_leading_emoji(detail_text)
    return result


def parse_structured_detail_text(detail: str) -> dict[str, Any] | None:
    text = str(detail or "").strip()
    if not text:
        return None

    result: dict[str, Any] = {}
    in_details = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("说明:"):
            result["description"] = strip_leading_emoji(line.split(":", 1)[1].strip())
            in_details = False
            continue
        if line.startswith("状态码:"):
            result["status_code"] = line.split(":", 1)[1].strip()
            in_details = False
            continue
        if line.rstrip(":") in {"详情", "详细信息"}:
            in_details = True
            continue

        bullet_match = re.match(r"^-\s*(.+)$", line)
        if bullet_match:
            payload = bullet_match.group(1).strip()
            if ":" in payload:
                key, value = payload.split(":", 1)
                result[key.strip()] = value.strip()
            continue

        if in_details and ":" in line:
            key, value = line.split(":", 1)
            result[key.strip().lstrip("- ")] = value.strip()
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            normalized_key = key.strip()
            normalized_value = value.strip()
            if normalized_key == "说明":
                result["description"] = strip_leading_emoji(normalized_value)
            elif normalized_key == "状态码":
                result["status_code"] = normalized_value
            elif normalized_key:
                result[normalized_key] = normalized_value

    return result or None


def format_json_text(payload: Any) -> str:
    if payload in (None, ""):
        return "{}"
    return json.dumps(payload, ensure_ascii=False, indent=2)



def normalize_detail_payload(item: dict[str, Any] | None, *, status_code: str = "") -> Any:
    if not item:
        return {}

    detail = item.get("detail")
    payload: dict[str, Any] | list[Any] | None = None

    if detail is not None and detail != "":
        if isinstance(detail, dict):
            payload = dict(detail)
        elif isinstance(detail, list):
            payload = list(detail)
        else:
            text = str(detail).strip()
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    structured = parse_structured_detail_text(text)
                    payload = structured if structured else {"detail": text}

    if payload is None:
        payload = {}

    if isinstance(payload, dict):
        payload = refine_description_path(payload)
        message = str(item.get("message") or item.get("message_summary") or "").strip()
        extracted = extract_message_payload(message) if message else None
        if extracted:
            if not payload.get("description"):
                payload["description"] = extracted["description"]
            payload.setdefault("path", extracted.get("path"))
        elif message and not payload.get("description"):
            payload["description"] = strip_leading_emoji(message)
        event = item.get("event") or item.get("event_type") or item.get("status_code")
        if event and "status_code" not in payload and "event" not in payload:
            payload["event"] = event
        normalized_status = str(status_code or "").strip()
        if normalized_status and "status_code" not in payload:
            payload["status_code"] = normalized_status
        for key in ("platform", "source", "trace_id"):
            value = item.get(key)
            if value and key not in payload:
                payload[key] = value
        payload = {key: value for key, value in payload.items() if value not in (None, "", [])}

    return payload or {}


def extract_trace_id(item: dict[str, Any] | None, *, payload: Any | None = None, status_code: str = "") -> str:
    if not item:
        return ""
    candidates = [
        item.get("trace_id"),
        item.get("traceId"),
        item.get("trace"),
    ]

    detail = item.get("detail")
    if isinstance(detail, dict):
        candidates.extend(
            [
                detail.get("trace_id"),
                detail.get("traceId"),
                detail.get("trace"),
            ]
        )

    normalized_payload = payload if payload is not None else normalize_detail_payload(item, status_code=status_code)
    if isinstance(normalized_payload, dict):
        candidates.extend(
            [
                normalized_payload.get("trace_id"),
                normalized_payload.get("traceId"),
                normalized_payload.get("trace"),
            ]
        )

    for value in candidates:
        text = str(value or "").strip()
        if text and text != "-":
            return text
    return ""


def build_log_detail_payload(
    item: dict[str, Any],
    *,
    platform_label: str,
    status_code: str = "",
) -> dict[str, Any]:
    detail_payload = normalize_detail_payload(item, status_code=status_code)
    return {
        "time": item.get("time"),
        "level": item.get("level"),
        "platform": platform_label,
        "source": item.get("source"),
        "trace_id": extract_trace_id(item, payload=detail_payload) or item.get("trace_id") or "",
        "message": item.get("message") or item.get("message_summary") or "",
        "detail": detail_payload,
        "stack": item.get("stack") or "",
    }
