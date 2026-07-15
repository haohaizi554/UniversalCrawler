"""小红书 Spider 的解析辅助逻辑。"""

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
    """把小红书原始载荷归一化为 Spider 易用的结构。"""

    @staticmethod
    def normalize_note(note: dict[str, Any] | None) -> dict[str, Any]:
        """返回包含 Spider 所需核心字段的字典。"""
        payload = dict(note or {})
        payload.setdefault("title", sanitize_note_title(payload))
        payload.setdefault("author", note_author_name(payload))
        payload.setdefault("video_candidates", extract_video_candidates(payload))
        payload.setdefault("images_data", extract_image_entries(payload))
        return payload

    def build_selection_entry(self, note: dict[str, Any]) -> dict[str, Any]:
        """构造 Web、UI 和 CLI 均可消费的选择项。"""
        normalized = self.normalize_note(note)
        return {
            "title": build_note_summary(normalized),
            "note_id": normalized.get("note_id") or normalized.get("noteId", ""),
            "note_type": normalized.get("type", ""),
            "author": normalized.get("author", ""),
            "raw": normalized,
        }
