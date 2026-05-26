from __future__ import annotations

from app.models import VideoItem
from app.spiders.base_task_builder import BaseTaskBuilder


class DouyinTaskBuilder(BaseTaskBuilder):
    def build_items(self, item: VideoItem, trace_id_factory) -> list[VideoItem]:
        if not item.meta.get("is_gallery"):
            return [item]

        built_items: list[VideoItem] = []
        images_data = item.meta.get("images_data", [])
        base_title = item.title
        for idx, image_info in enumerate(images_data):
            image_url = image_info.get("image_url", "")
            live_url = image_info.get("live_video_url", "")
            seq = idx + 1
            base_trace = item.meta.get("trace_id", trace_id_factory("dy"))

            if live_url:
                live_item = VideoItem(url=live_url, title=f"{base_title}_{seq}", source="douyin")
                live_item.meta = item.meta.copy()
                live_item.meta.update(
                    self.build_download_meta(
                        trace_id=f"{base_trace}-live-{seq}",
                        is_gallery=False,
                        content_type="video",
                        media_label="实况",
                    )
                )
                built_items.append(live_item)
            elif image_url:
                image_item = VideoItem(url=image_url, title=f"{base_title}_{seq}", source="douyin")
                image_item.meta = item.meta.copy()
                image_item.meta.update(
                    self.build_download_meta(
                        trace_id=f"{base_trace}-img-{seq}",
                        is_gallery=False,
                        content_type="image",
                        media_label="图集",
                    )
                )
                built_items.append(image_item)
        return built_items
