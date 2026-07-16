"""MissAV 候选 URL、分组、评分和展示标签测试。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.spiders.missav import parser as parser_module
from app.spiders.missav.parser import MissAVParser


def _filters(url: str) -> list[str]:
    value = parse_qs(urlparse(url).query).get("filters", [""])[0]
    return [part for part in value.split(",") if part]


def test_url_filters_preserve_existing_query_and_are_idempotent() -> None:
    parser = MissAVParser()
    original = "https://missav.ai/cn/search/demo?page=2&filters=featured"

    individual = parser.inject_url_params(original, individual_only=True)
    repeated = parser.inject_url_params(individual, individual_only=True)
    chinese = parser.add_chinese_filter(repeated)
    chinese_repeated = parser.add_chinese_filter(chinese)

    assert parse_qs(urlparse(individual).query)["page"] == ["2"]
    assert _filters(individual) == ["featured", "individual"]
    assert _filters(repeated) == ["featured", "individual"]
    assert _filters(chinese_repeated) == ["featured", "individual", "chinese-subtitle"]


def test_individual_filter_can_be_disabled() -> None:
    parser = MissAVParser()
    url = "https://missav.ai/cn/search/demo?page=2"

    assert parser.inject_url_params(url, individual_only=False) == url


def test_group_candidates_normalizes_codes_and_keeps_unmatched_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        parser_module,
        "cached_parser_result",
        lambda _namespace, _payload, producer: producer(),
    )
    parser = MissAVParser()

    grouped = parser.group_candidates(
        {
            "https://missav.ai/cn/abp-001": "普通版",
            "https://missav.ai/cn/abp-001-chinese-subtitle": "中文字幕",
            "https://missav.ai/cn/search/no-code": "未知",
        }
    )

    assert [title for _url, title in grouped["ABP-001"]] == ["普通版", "中文字幕"]
    assert grouped["https://missav.ai/cn/search/no-code"] == [
        ("https://missav.ai/cn/search/no-code", "未知")
    ]


@pytest.mark.parametrize(
    ("url", "title", "verified", "priority", "expected"),
    [
        ("https://missav.ai/cn/abp-001", "普通版", set(), ["中文字幕", "普通"], 20),
        ("https://missav.ai/cn/abp-001-english", "英文字幕", set(), ["英文字幕", "普通"], 40),
        ("https://missav.ai/cn/abp-001", "中文字幕", set(), ["中文字幕", "普通"], 40),
        ("https://missav.ai/cn/abp-001-leak", "中文字幕 无码", set(), ["中文字幕", "无码流出"], 20),
        ("https://missav.ai/cn/abp-001", "普通版", set(), ["英文字幕"], 0),
    ],
)
def test_candidate_score_honors_priority_and_uncensored_exclusivity(
    url: str,
    title: str,
    verified: set[str],
    priority: list[str],
    expected: int,
) -> None:
    assert MissAVParser().calculate_score(url, title, verified, priority) == expected


@pytest.mark.parametrize(
    ("url", "title", "verified", "expected"),
    [
        ("https://missav.ai/cn/abp-001", "普通版", set(), "普通版"),
        ("https://missav.ai/cn/abp-001-chinese", "版本", set(), "[中字] 版本"),
        ("https://missav.ai/cn/abp-001-english", "版本", set(), "[英字] 版本"),
        ("https://missav.ai/cn/abp-001-leak", "中文字幕", set(), "[无码] 中文字幕"),
    ],
)
def test_display_title_uses_non_conflicting_version_tags(
    url: str,
    title: str,
    verified: set[str],
    expected: str,
) -> None:
    assert MissAVParser().generate_display_title(url, title, verified) == expected
