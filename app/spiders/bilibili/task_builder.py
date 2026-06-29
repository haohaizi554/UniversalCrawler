"""爬虫实现模块，负责 `app/spiders/bilibili/task_builder.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.base_task_builder import BaseTaskBuilder

class BilibiliTaskBuilder(BaseTaskBuilder):
    """负责将解析结果转换为 `BilibiliTaskBuilder` 对应的任务或数据对象。"""
    def __init__(self, parser: BilibiliParser):
        """初始化当前实例并准备运行所需的状态，供 `BilibiliTaskBuilder` 使用。"""
        self.parser = parser

    def build_single_task(self, episode: dict, referer: str, video_title: str | None = None) -> dict:
        """构建 `single_task` 对应的结果、参数或对象，供 `BilibiliTaskBuilder` 使用。"""
        part_title = str(episode.get("title") or "").strip()
        main_title = str(video_title or "").strip()
        # 单 P 视频应以主标题命名；分 P 标题常为「正片」、空串或与主标题重复。
        display_title = main_title or part_title or "untitled"
        return self.build_download_meta(
            trace_id=f"bilibili_{episode['bvid']}_{episode['cid']}",
            referer=referer,
            bvid=episode["bvid"],
            cid=episode["cid"],
            file_name=self.parser.clean_name(display_title) + ".mp4",
            folder_name=None,
        )

    def build_episode_task(self, info: dict, episode: dict, sub_idx: int) -> dict:
        """构建 `episode_task` 对应的结果、参数或对象，供 `BilibiliTaskBuilder` 使用。"""
        folder_name = self.parser.clean_name(info.get("season_title") or info["title"])
        num_str = str(episode.get("page_num", sub_idx + 1)).zfill(2)
        part_title = str(episode.get("title") or "").strip()
        fallback_title = str(info.get("season_title") or info.get("title") or "").strip()
        safe_title = self.parser.clean_name(part_title or fallback_title or "untitled")
        return self.build_download_meta(
            trace_id=f"bilibili_{episode['bvid']}_{episode['cid']}",
            referer=f"https://www.bilibili.com/video/{episode['bvid']}",
            bvid=episode["bvid"],
            cid=episode["cid"],
            file_name=f"P{num_str}_{safe_title}.mp4",
            folder_name=folder_name,
        )
