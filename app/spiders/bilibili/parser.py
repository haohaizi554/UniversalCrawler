"""Bilibili API 响应解析：把视频信息和播放流整理成平台无关结构。"""

from __future__ import annotations

import re
from typing import Any

from app.exceptions import SpiderParseError
from app.spiders.parser_cache import cached_parser_result

class BilibiliParser:
    """只做结构化解析，不访问网络，便于 spider 和测试复用。"""

    def parse_video_info_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """解析视频详情；合集按 section 展平成连续 P 序，普通视频按 pages 保留原页码。"""
        return cached_parser_result(
            "bilibili.video_info",
            data,
            lambda: self._parse_video_info_response_uncached(data),
        )

    def _parse_video_info_response_uncached(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            info = {
                "bvid": data["bvid"],
                "title": data["title"],
                "owner": data["owner"]["name"],
                "is_season": False,
                "season_id": None,
                "season_title": "",
                "episodes": [],
            }
            if data.get("ugc_season"):
                info["is_season"] = True
                info["season_id"] = data["ugc_season"]["id"]
                info["season_title"] = data["ugc_season"]["title"]
                ep_counter = 1
                # UGC season 的 section/page 层级不稳定，下载文件名只需要稳定顺序。
                for section in data["ugc_season"]["sections"]:
                    for episode in section["episodes"]:
                        info["episodes"].append(
                            {
                                "title": episode["title"],
                                "bvid": episode["bvid"],
                                "cid": episode["cid"],
                                "page_num": ep_counter,
                            }
                        )
                        ep_counter += 1
                return info

            info["season_title"] = data["title"]
            for page in data.get("pages", []):
                info["episodes"].append(
                    {
                        "title": page["part"],
                        "bvid": data["bvid"],
                        "cid": page["cid"],
                        "page_num": page["page"],
                    }
                )
            return info
        except (KeyError, TypeError, IndexError) as exc:
            raise SpiderParseError("Bilibili 视频信息结构不完整") from exc

    def parse_play_url_response(self, resp: dict[str, Any]) -> tuple[str | None, str | None, int]:
        """解析 DASH 播放流；下载层后续会把首个 video/audio 流交给 Bilibili 下载器合并。"""
        return cached_parser_result(
            "bilibili.play_url",
            resp,
            lambda: self._parse_play_url_response_uncached(resp),
        )

    def _parse_play_url_response_uncached(self, resp: dict[str, Any]) -> tuple[str | None, str | None, int]:
        try:
            if resp.get("code") == 0 and "data" in resp and "dash" in resp["data"]:
                dash = resp["data"]["dash"]
                video_url = dash["video"][0]["baseUrl"]
                audio_url = dash["audio"][0]["baseUrl"] if dash.get("audio") else None
                quality_id = dash["video"][0]["id"]
                return video_url, audio_url, quality_id
            return None, None, 0
        except (KeyError, TypeError, IndexError) as exc:
            raise SpiderParseError("Bilibili 播放流结构不完整") from exc

    @staticmethod
    def clean_name(name: str) -> str:
        """清理 Windows 文件名禁用字符，保持平台 task builder 命名一致。"""
        return re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip()
