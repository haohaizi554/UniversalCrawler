"""小红书任务装配：把笔记详情转换成视频或图文下载项。"""

from __future__ import annotations

from typing import Any

from app.models import VideoItem
from app.spiders.base_task_builder import BaseTaskBuilder

from .helpers import note_author_name, sanitize_note_title

class XiaohongshuTaskBuilder(BaseTaskBuilder):
    """保留笔记级基础 meta，再为每个可下载资源补充资源级 trace_id。"""

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
        """视频笔记只取首个可播放候选；图文笔记按图片展开为多个下载项。"""
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
        )

        if video_candidates:
            # 小红书视频候选通常是同一资源的不同地址，下载器失败时仍可从 meta 查候选。
            item = VideoItem(url=video_candidates[0], title=title, source="xiaohongshu")
            item.meta = {
                **base_meta,
                "content_type": "video",
                "download_strategy": "http",
                "video_candidates": video_candidates,
            }
            return [item]

        if images_data:
            built_items: list[VideoItem] = []
            for idx, image_info in enumerate(images_data, start=1):
                image_url = str(image_info.get("image_url") or "").strip()
                if not image_url:
                    continue
                item = VideoItem(
                    url=image_url,
                    title=f"{title}_{idx}",
                    source="xiaohongshu",
                )
                item.meta = {
                    **base_meta,
                    **self.build_download_meta(
                        trace_id=f"{base_trace}-img-{idx}",
                        content_type="image",
                        media_label="图文",
                        image_index=idx,
                        image_total=len(images_data),
                    ),
                }
                built_items.append(item)
            return built_items

        return []
