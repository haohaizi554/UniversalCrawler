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
