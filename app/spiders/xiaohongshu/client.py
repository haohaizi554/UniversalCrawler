"""HTTP client for XiaoHongShu web APIs."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests

from app.debug_logger import debug_logger

from app.exceptions import SpiderParseError

from .helpers import build_search_id, extract_note_detail_from_html
from .sign import sign_with_xhshow

class XiaohongshuClient:
    """Signed XHS web-api client."""

    def __init__(
        self,
        *,
        user_agent: str,
        cookie_str: str,
        proxy: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.timeout = timeout
        self.cookie_str = cookie_str
        self.host = "https://edith.xiaohongshu.com"
        self.domain = "https://www.xiaohongshu.com"
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Referer": self.domain + "/",
                "Origin": self.domain,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=UTF-8",
                "Cookie": cookie_str,
            }
        )

    @staticmethod
    def _build_query_string(params: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, value in params.items():
            if isinstance(value, list):
                value_str = ",".join(str(item) for item in value)
            elif value is None:
                value_str = ""
            else:
                value_str = str(value)
            parts.append(f"{key}={quote(value_str, safe=',')}")
        return "&".join(parts)

    def _signed_headers(self, *, uri: str, data: dict[str, Any], method: str) -> dict[str, str]:
        headers = dict(self.session.headers)
        headers.update(
            sign_with_xhshow(
                uri=uri,
                data=data,
                cookie_str=self.cookie_str,
                method=method,
            )
        )
        return headers

    def _parse_json(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpiderParseError(f"小红书响应不是合法 JSON: {response.text[:200]}") from exc
        if not isinstance(payload, dict):
            raise SpiderParseError("小红书响应结构非法")
        if payload.get("success") is True:
            return payload.get("data") or {}
        code = payload.get("code")
        msg = payload.get("msg") or payload.get("message") or response.text[:200]
        raise SpiderParseError(f"小红书接口返回失败 code={code}: {msg}")

    def get(self, uri: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = self._signed_headers(uri=uri, data=params, method="GET")
        query = self._build_query_string(params)
        url = f"{self.host}{uri}"
        if query:
            url = f"{url}?{query}"
        response = self.session.get(url, headers=headers, timeout=self.timeout, proxies=self.proxies)
        response.raise_for_status()
        return self._parse_json(response)

    def post(self, uri: str, data: dict[str, Any]) -> dict[str, Any]:
        headers = self._signed_headers(uri=uri, data=data, method="POST")
        response = self.session.post(
            f"{self.host}{uri}",
            data=json.dumps(data, separators=(",", ":"), ensure_ascii=False),
            headers=headers,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        response.raise_for_status()
        return self._parse_json(response)

    def search_notes(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int = 20,
        sort: str = "general",
        note_type: int = 0,
        search_id: str | None = None,
    ) -> dict[str, Any]:
        return self.post(
            "/api/sns/web/v1/search/notes",
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "search_id": search_id or build_search_id(),
                "sort": sort,
                "note_type": note_type,
            },
        )

    def search_users(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int = 10,
        search_id: str | None = None,
    ) -> dict[str, Any]:
        return self.post(
            "/api/sns/web/v1/search/usersearch",
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "search_id": search_id or build_search_id(),
            },
        )

    def get_note_detail(self, *, note_id: str, xsec_source: str = "", xsec_token: str = "") -> dict[str, Any]:
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source or "pc_search",
            "xsec_token": xsec_token,
        }
        data = self.post("/api/sns/web/v1/feed", payload)
        items = data.get("items") or []
        if items:
            note_card = items[0].get("note_card") or {}
            if note_card:
                note_card["xsec_token"] = xsec_token
                note_card["xsec_source"] = xsec_source or "pc_search"
                return note_card
        return {}

    def get_note_detail_from_html(
        self,
        *,
        note_id: str,
        xsec_source: str = "",
        xsec_token: str = "",
    ) -> dict[str, Any]:
        uri = f"/explore/{note_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        response = self.session.get(
            f"{self.domain}{uri}",
            headers=dict(self.session.headers),
            timeout=self.timeout,
            proxies=self.proxies,
        )
        response.raise_for_status()
        detail = extract_note_detail_from_html(note_id, response.text)
        if detail:
            detail["xsec_token"] = xsec_token
            detail["xsec_source"] = xsec_source or "pc_search"
            return detail
        return {}

    def get_creator_notes(
        self,
        *,
        user_id: str,
        cursor: str = "",
        page_size: int = 20,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> dict[str, Any]:
        return self.get(
            "/api/sns/web/v1/user_posted",
            {
                "num": page_size,
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
                "xsec_source": xsec_source,
            },
        )

    @staticmethod
    def _self_info_indicates_login(payload: dict[str, Any]) -> bool:
        if not payload:
            return False
        if payload.get("success") is True:
            return True
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return False
        result = data.get("result") or {}
        if isinstance(result, dict) and result.get("success") is True:
            return True
        for key in ("basic_info", "user", "user_info"):
            value = data.get(key)
            if isinstance(value, dict) and value:
                return True
        return False

    def query_self(self) -> dict[str, Any]:
        uri = "/api/sns/web/v1/user/selfinfo"
        headers = self._signed_headers(uri=uri, data={}, method="GET")
        response = self.session.get(
            f"{self.host}{uri}",
            headers=headers,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def probe_login_status(self) -> bool | None:
        """Return True for logged-in, False for confirmed guest, None for probe failure."""
        try:
            payload = self.query_self()
        except requests.HTTPError:
            return False
        except (requests.RequestException, ValueError):
            return None
        return self._self_info_indicates_login(payload)

    def check_cookie_ready(self) -> bool:
        """Guest and login flows both need at least the a1 cookie for signing."""
        return "a1=" in self.cookie_str

    def close(self) -> None:
        try:
            self.session.close()
        except (requests.RequestException, RuntimeError, AttributeError) as exc:
            debug_logger.log_exception("XiaohongshuClient", "close_session", exc)
