"""爬虫实现模块，负责 `app/spiders/bilibili/parser.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations

import re
from typing import Any

from app.exceptions import SpiderParseError

class BilibiliParser:
    """负责 `BilibiliParser` 对应的数据清洗与结构化解析。"""
    def parse_video_info_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """解析 `video_info_response` 对应的输入数据并返回结构化结果，供 `BilibiliParser` 使用。"""
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
        """解析 `play_url_response` 对应的输入数据并返回结构化结果，供 `BilibiliParser` 使用。"""
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
        
        return re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip()
