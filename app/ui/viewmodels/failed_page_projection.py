from __future__ import annotations

from typing import Any

from app.ui.viewmodels.log_i18n import localize_log_text


def prepare_failed_item_for_display(item: dict[str, Any], *, language: str) -> dict[str, Any]:
    """Build failed-page display fields in the list worker, before Qt widgets render."""

    row = dict(item)
    row["reason_detail_display"] = localize_log_text(
        row.get("reason_detail") or row.get("reason") or "",
        language,
    )
    row["log_excerpt_display_items"] = _display_log_entries(row, language=language)
    row["solutions_display"] = [
        _display_solution(solution, language=language)
        for solution in list(row.get("solutions") or [])
        if isinstance(solution, dict)
    ]
    return row


def failed_log_time_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "--:--:--"
    parts = text.split()
    candidate = parts[-1] if parts else text
    if "." in candidate:
        candidate = candidate.split(".", 1)[0]
    if len(candidate) >= 8 and candidate[-8:-6].isdigit() and candidate[-5:-3].isdigit() and candidate[-2:].isdigit():
        return candidate[-8:]
    return text[-8:].rjust(8, "-")


def _display_log_entries(item: dict[str, Any], *, language: str) -> list[dict[str, Any]]:
    raw_entries = [entry for entry in list(item.get("log_excerpt_items") or []) if isinstance(entry, dict)]
    if not raw_entries:
        raw_entries = [
            {"level": "INFO", "message": message, "icon_file": "log_level_info.png"}
            for message in list(item.get("log_excerpt") or [])
        ]
    return [_display_log_entry(entry, language=language) for entry in raw_entries]


def _display_log_entry(entry: dict[str, Any], *, language: str) -> dict[str, Any]:
    row = dict(entry)
    row["time_display"] = failed_log_time_display(row.get("time"))
    row["message_display"] = localize_log_text(row.get("message") or "", language)
    return row


def _display_solution(solution: dict[str, Any], *, language: str) -> dict[str, Any]:
    row = dict(solution)
    row["title_display"] = localize_log_text(row.get("title") or "\u5efa\u8bae", language)
    row["description_display"] = localize_log_text(row.get("description") or "", language)
    return row
