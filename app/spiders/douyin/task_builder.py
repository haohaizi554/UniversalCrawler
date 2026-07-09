"""抖音任务装配：把解析出的逻辑作品展开成实际下载项。"""

from __future__ import annotations
from app.models import VideoItem
from app.spiders.base_task_builder import BaseTaskBuilder

class DouyinTaskBuilder(BaseTaskBuilder):
    """负责图集/实况照片的展开，并为每个子资源生成独立 trace_id。"""

    def build_items(self, item: VideoItem, trace_id_factory) -> list[VideoItem]:
        """非图集直接透传；图集按图片或实况视频拆成多个下载任务。"""
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
                # 实况资源保留原作品 meta，但重写 content_type，避免图片下载器误接管。
                live_item = VideoItem(url=live_url, title=f"{base_title}_{seq}", source="douyin")
                live_item.meta = item.meta.copy()
                live_item.meta.update(
                    self.build_download_meta(
                        trace_id=f"{base_trace}_live_{seq}",
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
                        trace_id=f"{base_trace}_img_{seq}",
                        is_gallery=False,
                        content_type="image",
                        media_label="图集",
                    )
                )
                built_items.append(image_item)
        return built_items
