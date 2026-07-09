"""Bilibili 下载任务装配，把 episode 信息转换为下载层 meta。"""

from __future__ import annotations

from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.base_task_builder import BaseTaskBuilder

class BilibiliTaskBuilder(BaseTaskBuilder):
    """集中处理 Bilibili 文件名、合集目录和 trace_id 约定。"""

    def __init__(self, parser: BilibiliParser):
        """复用 parser 的命名清理规则，避免任务层重复维护文件名逻辑。"""
        self.parser = parser

    def build_single_task(self, episode: dict, referer: str, video_title: str | None = None) -> dict:
        """构建单视频任务；单 P 不进合集目录，直接以主标题落盘。"""
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
        """构建合集/分 P 任务；目录用合集标题，文件名前缀保留稳定 P 序。"""
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
