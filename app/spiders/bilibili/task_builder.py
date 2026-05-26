from __future__ import annotations

from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.base_task_builder import BaseTaskBuilder


class BilibiliTaskBuilder(BaseTaskBuilder):
    def __init__(self, parser: BilibiliParser):
        self.parser = parser

    def build_single_task(self, episode: dict, referer: str) -> dict:
        return self.build_download_meta(
            trace_id=f"bili-{episode['bvid']}-{episode['cid']}",
            referer=referer,
            bvid=episode["bvid"],
            cid=episode["cid"],
            file_name=self.parser.clean_name(episode["title"]) + ".mp4",
            folder_name=None,
        )

    def build_episode_task(self, info: dict, episode: dict, sub_idx: int) -> dict:
        folder_name = self.parser.clean_name(info.get("season_title") or info["title"])
        num_str = str(episode.get("page_num", sub_idx + 1)).zfill(2)
        safe_title = self.parser.clean_name(episode["title"])
        return self.build_download_meta(
            trace_id=f"bili-{episode['bvid']}-{episode['cid']}",
            referer=f"https://www.bilibili.com/video/{episode['bvid']}",
            bvid=episode["bvid"],
            cid=episode["cid"],
            file_name=f"P{num_str}_{safe_title}.mp4",
            folder_name=folder_name,
        )
