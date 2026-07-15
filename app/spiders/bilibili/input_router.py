"""Bilibili 输入路由：把用户粘贴内容分类成 BV、av、空间、搜索或兜底扫描。"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable


URL_TRAILING_PUNCTUATION = " \t\r\n`'\"\uFF0C\u3002\uFF01\uFF1F\uFF1B\uFF1A\u3001,.!?;:)]}\uFF09\u3011\u300B>"
COLLECTION_PATH_MARKERS = (
    "/list/",
    "/lists/",
    "/medialist/",
    "/playlist/",
    "/channel/collectiondetail",
    "/cheese/",
    "/bangumi/",
)
COLLECTION_QUERY_KEYS = {
    "list",
    "playlist",
    "season_id",
    "series_id",
    "sid",
    "collection_id",
    "media_id",
}
UID_LABEL_PATTERN = re.compile(r"(?i)^(?:uid|mid|up主|up主id|用户id)[:：\s]+(\d+)$")
BVID_TEXT_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])")
AVID_TEXT_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])")
SHORT_LINK_HOSTS = ("b23.tv", "bili2233.cn", "bili22.cn")
MIN_PLAIN_UID_DIGITS = 5


@dataclass(frozen=True, slots=True)
class BilibiliInputRoute:
    """纯分类结果；短链解析等网络行为由 spider 层负责，便于单测覆盖。"""

    kind: str
    value: str
    scan_kwargs: dict[str, object] | None = None


def strip_url_trailing_punctuation(value: str) -> str:
    return str(value or "").strip().strip("`").rstrip(URL_TRAILING_PUNCTUATION)


def extract_first_url(raw_text: str) -> str:
    """从分享文案提取首个 URL，并剔除中文标点等复制噪声。"""
    text = str(raw_text or "").strip()
    match = re.search(r"https?://[^\s`'\"<>]+", text)
    if match:
        return strip_url_trailing_punctuation(match.group(0))
    match = re.search(
        r"(?://)?(?:www\.)?bilibili\.com/[^\s`'\"<>]+",
        text,
        re.I,
    )
    if match:
        candidate = match.group(0)
        if "://" not in candidate:
            candidate = f"https://{candidate.lstrip('/')}"
        return strip_url_trailing_punctuation(candidate)
    for host in SHORT_LINK_HOSTS:
        match = re.search(rf"(?i)\b{re.escape(host)}/[^\s`'\"<>]+", text)
        if match:
            return strip_url_trailing_punctuation(f"https://{match.group(0)}")
    return text.strip().strip("`")


def keyword_route(keyword: str) -> BilibiliInputRoute:
    search_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(str(keyword or ''))}"
    return BilibiliInputRoute("keyword", search_url, {"is_search": True, "is_space": False})


def looks_like_collection_bvid_hint(raw_text: str) -> bool:
    """判断“BV + 合集提示词”场景，避免把合集入口误当作单视频。"""
    lowered = str(raw_text or "").lower()
    if any(marker in lowered for marker in ("合集", "系列", "列表", "收藏", "collection", "season", "series")):
        return True
    return bool(BVID_TEXT_PATTERN.search(str(raw_text or ""))) and str(raw_text or "").upper().count("BV") > 1


def normalize_bvid(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[:2].upper() == "BV":
        return "BV" + text[2:]
    return text


def bvid_from_url(url: str) -> str:
    match = re.search(r"(?i)video/(BV[0-9A-Za-z]{10})", str(url or ""))
    if not match:
        match = BVID_TEXT_PATTERN.search(str(url or ""))
    return normalize_bvid(match.group(1)) if match else ""


def bvid_from_text(text: str) -> str:
    match = BVID_TEXT_PATTERN.search(str(text or ""))
    return normalize_bvid(match.group(1)) if match else ""


def aid_from_text(text: str) -> str:
    match = AVID_TEXT_PATTERN.search(str(text or ""))
    return match.group(1) if match else ""


def aid_from_url(url: str) -> str:
    match = re.search(r"(?i)(?:/video/av|[?&](?:aid|av)=)(\d+)", str(url or ""))
    return match.group(1) if match else ""


def collection_bvid_fallback_urls(bvid: str, raw_text: str = "") -> list[str]:
    """为疑似合集 BV 构造搜索页和详情页兜底，交给网页扫描确认真实入口。"""
    normalized_bvid = normalize_bvid(bvid)
    raw = str(raw_text or "").strip()
    search_terms = [
        normalized_bvid,
        f"{normalized_bvid} 合集",
        raw,
    ]
    urls = [keyword_route(term).value for term in search_terms if term]
    urls.append(f"https://www.bilibili.com/video/{normalized_bvid}")
    return list(dict.fromkeys(urls))


def is_collection_like_url(parsed: urllib.parse.ParseResult) -> bool:
    """根据路径和 query 判断是否应走列表/合集扫描，而不是单条取流。"""
    path = (parsed.path or "").lower()
    if any(marker in path for marker in COLLECTION_PATH_MARKERS):
        return True
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return any(key.lower() in COLLECTION_QUERY_KEYS for key in query)


def is_bvid_ugc_season_entry_url(parsed: urllib.parse.ParseResult) -> bool:
    """判断是否应通过 BV 详情 API 解析 Bilibili UGC 合集条目。"""
    if not re.search(r"(?i)/video/BV[0-9A-Za-z]{10}", parsed.path or ""):
        return False
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query_keys = {str(key).lower() for key in query}
    if {"ugc_season_id", "section_id", "season_id", "series_id"} & query_keys:
        return True
    spm_values = [
        value
        for key, values in query.items()
        if str(key).lower() in {"spm_id_from", "from_spmid"}
        for value in values
    ]
    return any("videopod.sections" in str(value).lower() or "ugc_season" in str(value).lower() for value in spm_values)


def route_url(url: str) -> BilibiliInputRoute:
    """把规范 URL 分派到具体路线；只做静态判断，不跟随短链。"""
    url = strip_url_trailing_punctuation(url)
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path or ""
    is_bilibili_host = host == "bilibili.com" or host.endswith(".bilibili.com")
    is_short_link_host = host in SHORT_LINK_HOSTS
    if not is_bilibili_host and not is_short_link_host:
        return keyword_route(url)
    if host == "space.bilibili.com":
        if is_collection_like_url(parsed):
            return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})
        uid_match = re.search(r"/(\d+)(?:/|$)", path)
        target_url = url
        if uid_match and not re.search(r"/(video|lists?)(?:/|$)", path):
            # 空间首页默认补到 /video，减少网页扫描进入动态/收藏页造成的误抓。
            target_url = f"https://space.bilibili.com/{uid_match.group(1)}/video"
        return BilibiliInputRoute("scan", target_url, {"is_search": False, "is_space": True})
    if host == "search.bilibili.com":
        return BilibiliInputRoute("scan", url, {"is_search": True, "is_space": False})
    bvid = bvid_from_url(url)
    if bvid and is_bvid_ugc_season_entry_url(parsed):
        return BilibiliInputRoute(
            "bvid_with_fallback",
            bvid,
            {"is_search": False, "is_space": False, "fallback_url": url},
        )
    if is_collection_like_url(parsed):
        return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})
    if bvid:
        return BilibiliInputRoute("bvid", bvid)
    aid = aid_from_url(url)
    if aid:
        return BilibiliInputRoute("aid", aid)
    return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})


def classify_input(raw_text: str, *, normalize_keyword: Callable[[str], str] | None = None) -> BilibiliInputRoute:
    """入口函数：先处理显式 ID/URL，再从普通文本里提取 BV/av，否则落到搜索。"""
    raw = str(raw_text or "").strip()
    normalized = normalize_keyword(raw) if normalize_keyword is not None else extract_first_url(raw)
    value = str(normalized or "").strip()
    if not value:
        return keyword_route("")

    uid_label = UID_LABEL_PATTERN.match(raw)
    if uid_label:
        uid = uid_label.group(1)
        return BilibiliInputRoute(
            "scan",
            f"https://space.bilibili.com/{uid}/video",
            {"is_search": False, "is_space": True},
        )

    if re.fullmatch(r"\d+", value):
        if len(value) < MIN_PLAIN_UID_DIGITS:
            # 过短纯数字更像搜索词或 av 片段，直接当 UID 会误跳大量不存在空间。
            return keyword_route(value)
        return BilibiliInputRoute(
            "scan",
            f"https://space.bilibili.com/{value}/video",
            {"is_search": False, "is_space": True},
        )
    if re.fullmatch(r"(?i)BV[0-9A-Za-z]{10}", value):
        return BilibiliInputRoute("bvid", "BV" + value[2:])
    if re.fullmatch(r"(?i)av\d+", value):
        return BilibiliInputRoute("aid", value[2:])

    if value.lower().startswith(("http://", "https://")):
        return route_url(value)

    bvid = bvid_from_text(value)
    if bvid:
        if looks_like_collection_bvid_hint(raw):
            fallback_url = f"https://www.bilibili.com/video/{bvid}"
            fallback_urls = collection_bvid_fallback_urls(bvid, raw)
            scan_kwargs = {
                "is_search": False,
                "is_space": False,
                "fallback_url": fallback_url,
                "fallback_urls": list(dict.fromkeys(fallback_urls)),
            }
            return BilibiliInputRoute("bvid_with_fallback", bvid, scan_kwargs)
        return BilibiliInputRoute("bvid", bvid)
    aid = aid_from_text(value)
    if aid:
        return BilibiliInputRoute("aid", aid)
    return keyword_route(value)


def build_search_page_url(current_url: str, page_num: int) -> str:
    """Bilibili 搜索翻页需要同时维护 page 和 o 偏移。"""
    parsed = urllib.parse.urlparse(current_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page_num)
    query["o"] = str((page_num - 1) * 30)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
