from __future__ import annotations

import re
from typing import Any

from shared.localization import normalize_language, platform_display_name, tr

_EVENT_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "en-US": (
        (re.compile(r"^\u4efb\u52a1\u8fdb\u5165\s*(.*?)\s*\u4e0b\u8f7d\u5668$"), "Task entered {value} downloader"),
        (re.compile(r"^\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668[:\uff1a]\s*(.*)$"), "Task entered downloader: {value}"),
        (re.compile(r"^\u8fdb\u5ea6[:\uff1a]\s*(.*)$"), "Progress: {value}"),
        (
            re.compile(r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*?)\s*[\uff0c,]\s*\u5269\u4f59[:\uff1a]\s*(.*)$"),
            "Current speed: {value}, remaining: {extra}",
        ),
        (re.compile(r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*)$"), "Current speed: {value}"),
        (re.compile(r"^\u5199\u5165\u72b6\u6001[:\uff1a]\s*(.*)$"), "Write status: {value}"),
        (re.compile(r"^\u5408\u5e76\u72b6\u6001[:\uff1a]\s*(.*)$"), "Merge status: {value}"),
    ),
    "zh-TW": (
        (re.compile(r"^\u4efb\u52a1\u8fdb\u5165\s*(.*?)\s*\u4e0b\u8f7d\u5668$"), "\u4efb\u52d9\u9032\u5165 {value} \u4e0b\u8f09\u5668"),
        (re.compile(r"^\u4efb\u52a1\u8fdb\u5165\u4e0b\u8f7d\u5668[:\uff1a]\s*(.*)$"), "\u4efb\u52d9\u9032\u5165\u4e0b\u8f09\u5668\uff1a{value}"),
        (re.compile(r"^\u8fdb\u5ea6[:\uff1a]\s*(.*)$"), "\u9032\u5ea6\uff1a{value}"),
        (
            re.compile(r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*?)\s*[\uff0c,]\s*\u5269\u4f59[:\uff1a]\s*(.*)$"),
            "\u76ee\u524d\u901f\u5ea6\uff1a{value}\uff0c\u5269\u9918\uff1a{extra}",
        ),
        (re.compile(r"^\u5f53\u524d\u901f\u5ea6[:\uff1a]\s*(.*)$"), "\u76ee\u524d\u901f\u5ea6\uff1a{value}"),
        (re.compile(r"^\u5199\u5165\u72b6\u6001[:\uff1a]\s*(.*)$"), "\u5beb\u5165\u72c0\u614b\uff1a{value}"),
        (re.compile(r"^\u5408\u5e76\u72b6\u6001[:\uff1a]\s*(.*)$"), "\u5408\u4f75\u72c0\u614b\uff1a{value}"),
    ),
}

_EVENT_EXACT: dict[str, dict[str, str]] = {
    "en-US": {
        "\u97f3\u89c6\u9891\u6d41\u4e0b\u8f7d\u4e2d": "Audio/video stream downloading",
        "\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55": "Source link recorded",
        "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6": "Waiting for downloader events",
    },
    "zh-TW": {
        "\u97f3\u89c6\u9891\u6d41\u4e0b\u8f7d\u4e2d": "\u97f3\u8996\u983b\u6d41\u4e0b\u8f09\u4e2d",
        "\u6765\u6e90\u94fe\u63a5\u5df2\u8bb0\u5f55": "\u4f86\u6e90\u9023\u7d50\u5df2\u8a18\u9304",
        "\u7b49\u5f85\u4e0b\u8f7d\u5668\u4e0a\u62a5\u8be6\u7ec6\u4e8b\u4ef6": "\u7b49\u5f85\u4e0b\u8f09\u5668\u56de\u5831\u8a73\u7d30\u4e8b\u4ef6",
    },
}


def prepare_active_item_for_display(item: dict[str, Any], *, language: str) -> dict[str, Any]:
    """Build active-download display fields before Qt paints timeline widgets."""

    row = dict(item)
    row["events_display"] = [
        _display_event(event, language=language)
        for event in list(row.get("events") or [])
        if isinstance(event, dict)
    ]
    return row


def localize_active_event_message(message: object, language: str | None) -> str:
    text = str(message or "")
    normalized = normalize_language(language)
    for pattern, template in _EVENT_PATTERNS.get(normalized, ()):
        match = pattern.match(text)
        if not match:
            continue
        value = platform_display_name("", normalized, fallback=match.group(1))
        if len(match.groups()) > 1:
            return template.format(value=value, extra=tr(match.group(2), normalized))
        return template.format(value=value)
    exact = _EVENT_EXACT.get(normalized, {})
    return exact.get(text, tr(text, normalized))


def _display_event(event: dict[str, Any], *, language: str) -> dict[str, Any]:
    row = dict(event)
    row["message_display"] = localize_active_event_message(row.get("message") or "", language)
    return row
