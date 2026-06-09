"""Task builders for XiaoHongShu spider."""

from __future__ import annotations

from typing import Any

from app.models import VideoItem
from app.spiders.base_task_builder import BaseTaskBuilder

from .helpers import note_author_name, sanitize_note_title


class XiaohongshuTaskBuilder(BaseTaskBuilder):
    """Convert normalized XHS note payloads into download items."""

    def build_items(
        self,
        note: dict[str, Any],
        *,
        trace_id_factory,
        referer: str,
        user_agent: str,
        cookie_str: str,
        proxy: str | None = None,
    ) -> list[VideoItem]:
        """Build one or more download items from a note detail."""
        title = sanitize_note_title(note)
        author = note_author_name(note)
        note_id = str(note.get("note_id") or note.get("noteId") or "")
        video_candidates = list(note.get("video_candidates") or [])
        images_data = list(note.get("images_data") or [])
        base_trace = trace_id_factory("xhs")
        base_meta = self.build_download_meta(
            trace_id=base_trace,
            referer=referer,
            user_agent=user_agent,
            proxy=proxy,
            cookie=cookie_str,
            note_id=note_id,
            author=author,
            folder_name=author,
            use_subdir=True,
        )

        if video_candidates:
            item = VideoItem(url=video_candidates[0], title=title, source="xiaohongshu")
            item.meta = {
                **base_meta,
                "content_type": "video",
                "download_strategy": "http",
                "video_candidates": video_candidates,
            }
            return [item]

        if images_data:
            item = VideoItem(url=images_data[0].get("image_url", ""), title=title, source="xiaohongshu")
            item.meta = {
                **base_meta,
                "content_type": "gallery",
                "is_gallery": True,
                "images_data": images_data,
                "image_count": len(images_data),
            }
            return [item]

        return []
