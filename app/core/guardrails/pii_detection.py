"""PII detection and masking helpers for crawler output."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Any

PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
ID_CARD_RE = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
EMAIL_RE = re.compile(r"(?<![\w.%-])[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
BANK_CARD_RE = re.compile(
    r"(?<![\w/=&?#])"
    r"(?:62[0-9]{14,17}|45[0-9]{12,15}|52[0-9]{14,17}|37[0-9]{11,13}|35[0-9]{14,17})"
    r"(?![\w/=&?#])"
)

_masked_count = {"phone": 0, "id_card": 0, "email": 0, "bank_card": 0}
_masked_count_lock = threading.Lock()
MAX_SANITIZE_DEPTH = 64
MAX_DEPTH_SENTINEL = "<max-depth-exceeded>"


def sanitize(value: Any) -> Any:
    return _sanitize(value, depth=0)


def _sanitize(value: Any, *, depth: int) -> Any:
    if depth >= MAX_SANITIZE_DEPTH:
        return MAX_DEPTH_SENTINEL
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {key: _sanitize(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, depth=depth + 1) for item in value)
    return value


def sanitize_text(value: str) -> str:
    text, phone_count = PHONE_RE.subn(_mask_phone, value)
    text, id_card_count = ID_CARD_RE.subn(_mask_id_card, text)
    text, email_count = EMAIL_RE.subn(_mask_email, text)
    text, bank_card_count = BANK_CARD_RE.subn(_mask_bank_card, text)
    with _masked_count_lock:
        _masked_count["phone"] += phone_count
        _masked_count["id_card"] += id_card_count
        _masked_count["email"] += email_count
        _masked_count["bank_card"] += bank_card_count
    return text


def get_masked_count() -> dict[str, int]:
    """Return PII masking count snapshot (for monitoring/audit)."""
    with _masked_count_lock:
        return dict(_masked_count)


def reset_masked_count() -> None:
    """Reset PII masking counters (for test isolation)."""
    with _masked_count_lock:
        for key in _masked_count:
            _masked_count[key] = 0


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[-11:]
    return f"{digits[:3]}****{digits[-4:]}"


def _mask_id_card(match: re.Match[str]) -> str:
    value = match.group(0)
    return f"{value[:6]}********{value[-4:]}"


def _mask_email(match: re.Match[str]) -> str:
    value = match.group(0)
    name, domain = value.split("@", 1)
    if len(name) <= 2:
        masked_name = name[:1] + "*"
    else:
        masked_name = name[:2] + "***"
    return f"{masked_name}@{domain}"


def _mask_bank_card(match: re.Match[str]) -> str:
    value = match.group(0)
    digits = re.sub(r"\D", "", value)
    if len(digits) < 14:
        return value
    return f"{digits[:6]}******{digits[-4:]}"
