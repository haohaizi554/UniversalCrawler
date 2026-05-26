from __future__ import annotations

import re
import urllib.parse
from collections import defaultdict


class MissAVParser:
    def inject_url_params(self, url: str, individual_only: bool) -> str:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if individual_only:
            filters = qs.get("filters", [""])[0]
            parts = filters.split(",") if filters else []
            if "individual" not in parts:
                parts.append("individual")
                qs["filters"] = [",".join([part for part in parts if part])]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(qs, doseq=True)))

    def add_chinese_filter(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        filters = qs.get("filters", [""])[0]
        parts = filters.split(",") if filters else []
        if "chinese-subtitle" not in parts:
            parts.append("chinese-subtitle")
            qs["filters"] = [",".join([part for part in parts if part])]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(qs, doseq=True)))

    def group_candidates(self, scraped_data: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        code_pattern = re.compile(r"/cn/.*?([a-zA-Z]+-\d+)")
        for url, title in scraped_data.items():
            match = code_pattern.search(url)
            code = match.group(1).upper() if match else url
            grouped[code].append((url, title))
        return grouped

    def calculate_score(self, url: str, title: str, verified_chinese: set[str], priority_list: list[str]) -> int:
        url_lower = url.lower()
        title_lower = title.lower()
        is_uncensored = "uncensored" in url_lower or "leak" in url_lower or "无码" in title_lower
        is_english = "english" in url_lower or "英文字幕" in title_lower
        is_chinese = (url in verified_chinese) or ("chinese" in url_lower) or ("中文字幕" in title_lower)
        if is_uncensored:
            is_chinese = False
        feature_map = {
            "中文字幕": is_chinese,
            "英文字幕": is_english,
            "无码流出": is_uncensored,
            "普通": (not is_chinese and not is_english and not is_uncensored),
        }
        total = len(priority_list)
        for idx, name in enumerate(priority_list):
            score = (total - idx) * 20
            for key, satisfies in feature_map.items():
                if key in name and satisfies:
                    return score
        return 0

    def generate_display_title(self, url: str, title: str, verified_chinese: set[str]) -> str:
        tags: list[str] = []
        url_lower = url.lower()
        is_uncensored = "uncensored" in url_lower or "leak" in url_lower or "无码" in title.lower()
        is_chinese = (url in verified_chinese) or ("chinese" in url_lower) or ("中文字幕" in title.lower())
        if is_uncensored:
            tags.append("[无码]")
            is_chinese = False
        if is_chinese:
            tags.append("[中字]")
        if "english" in url_lower:
            tags.append("[英字]")
        tag_str = "".join(tags)
        return f"{tag_str} {title}" if tag_str else title
