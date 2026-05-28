"""爬虫实现模块，负责 `app/spiders/douyin/parser.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

from typing import Any

from app.models import VideoItem


class DouyinItemParser:
    """抖音数据解析器。"""

    def parse_aweme(self, data: dict[str, Any]) -> VideoItem | None:
        """解析 `aweme` 对应的输入数据并返回结构化结果，供 `DouyinItemParser` 使用。"""
        try:
            aweme_id = data.get("aweme_id", "unknown")
            desc = data.get("desc", aweme_id)
            create_time = data.get("create_time", 0)
            author = data.get("author", {}).get("nickname", "Unknown")

            video_url = ""
            video = data.get("video", {})
            play_addr = video.get("play_addr", {})
            url_list = play_addr.get("url_list", [])
            if url_list:
                video_url = url_list[-1]

            is_real_video = bool(video_url and ".mp3" not in video_url.lower())

            images_data: list[dict[str, Any]] = []
            has_live_photo = False
            for image in data.get("images") or []:
                clip_type = image.get("clip_type", 2)
                image_url = ""
                for candidate in image.get("url_list") or []:
                    if "~noop" in candidate:
                        image_url = candidate
                        break
                if not image_url and image.get("url_list"):
                    image_url = image["url_list"][-1]

                live_video_url = ""
                if clip_type == 3 and "video" in image:
                    live_addr = image["video"].get("play_addr_h264") or image["video"].get("play_addr")
                    if live_addr:
                        live_urls = live_addr.get("url_list", [])
                        if live_urls:
                            live_video_url = live_urls[-1]
                            has_live_photo = True
                images_data.append(
                    {
                        "image_url": image_url,
                        "live_video_url": live_video_url,
                        "clip_type": clip_type,
                    }
                )

            duration_ms = video.get("duration", 0)
            if is_real_video and not images_data:
                item = VideoItem(url=video_url, title=desc, source="douyin")
                item.meta = {
                    "trace_id": f"dy-{aweme_id}",
                    "content_type": "video",
                    "media_label": "视频",
                    "aweme_id": aweme_id,
                    "create_time": create_time,
                    "author": author,
                    "folder_name": author,
                    "duration": duration_ms // 1000,
                }
                return item

            if images_data:
                item = VideoItem(url=images_data[0]["image_url"], title=desc, source="douyin")
                item.meta = {
                    "trace_id": f"dy-{aweme_id}",
                    "content_type": "gallery",
                    "media_label": "实况" if has_live_photo else "图集",
                    "is_gallery": True,
                    "has_live_photo": has_live_photo,
                    "images_data": images_data,
                    "aweme_id": aweme_id,
                    "create_time": create_time,
                    "author": author,
                    "folder_name": author,
                }
                return item
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            import traceback

            traceback.print_exc()
        return None

    def summarize_aweme(self, data: dict[str, Any]) -> dict[str, Any]:
        """执行 `summarize_aweme` 对应的业务逻辑，供 `DouyinItemParser` 使用。"""
        video = data.get("video", {}) or {}
        author = data.get("author", {}) or {}
        images = data.get("images") or []
        return {
            "aweme_id": data.get("aweme_id"),
            "desc": data.get("desc"),
            "author": author.get("nickname"),
            "aweme_type": data.get("aweme_type"),
            "has_video": bool(video.get("play_addr")),
            "duration_ms": video.get("duration", 0),
            "image_count": len(images),
            "has_live_photo": any((img.get("clip_type") == 3) for img in images),
        }
