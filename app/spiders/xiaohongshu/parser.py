"""Parser helpers for XiaoHongShu spider."""

from __future__ import annotations

from typing import Any

from .helpers import (
    build_note_summary,
    extract_image_entries,
    extract_video_candidates,
    note_author_name,
    sanitize_note_title,
)


class XiaohongshuParser:
    """Normalize raw XHS payloads into spider-friendly structures."""

    @staticmethod
    def normalize_note(note: dict[str, Any] | None) -> dict[str, Any]:
        """Return a dict with the core fields the spider depends on."""
        payload = dict(note or {})
        payload.setdefault("title", sanitize_note_title(payload))
        payload.setdefault("author", note_author_name(payload))
        payload.setdefault("video_candidates", extract_video_candidates(payload))
        payload.setdefault("images_data", extract_image_entries(payload))
        return payload

    def build_selection_entry(self, note: dict[str, Any]) -> dict[str, Any]:
        """Build a selection entry consumable by Web/UI/CLI."""
        normalized = self.normalize_note(note)
        return {
            "title": build_note_summary(normalized),
            "note_id": normalized.get("note_id") or normalized.get("noteId", ""),
            "note_type": normalized.get("type", ""),
            "author": normalized.get("author", ""),
            "raw": normalized,
        }
