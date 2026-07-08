"""XiaoHongShu spider adapted to UniversalCrawlerProplus conventions."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

import requests
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg, get_setting_default
from app.debug_logger import debug_logger
from app.exceptions import SpiderAuthError, SpiderParseError
from app.spiders.base import BaseSpider
from app.services.auth_service import AuthService
from app.utils.user_agents import resolve_user_agent

from .client import XiaohongshuClient
from .helpers import (
    CreatorLookupInfo,
    CreatorUrlInfo,
    NoteUrlInfo,
    extract_first_url,
    is_creator_url,
    is_note_url,
    parse_creator_lookup_input,
    parse_creator_info_from_url,
    parse_note_info_from_note_url,
)
from .parser import XiaohongshuParser
from .task_builder import XiaohongshuTaskBuilder

class XiaohongshuSpider(BaseSpider):
    """Browser-assisted XiaoHongShu spider."""

    HOME_URL = "https://www.xiaohongshu.com/"
    DETAIL_WORKER_CAP = 8
    PROFILE_READY_SELECTOR = "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']"

    def __init__(self, keyword: str, config: dict):
        super().__init__(keyword, config)
        self.parser = XiaohongshuParser()
        self.task_builder = XiaohongshuTaskBuilder()
        self.auth_service = AuthService()
        self.auth_file = cfg.get(
            "auth",
            "xiaohongshu_cookie_file",
            get_setting_default("auth", "xiaohongshu_cookie_file"),
        )
        self._detail_request_count = 0
        self._detail_request_lock = threading.RLock()
        self._client: XiaohongshuClient | None = None
        self.user_agent = resolve_user_agent(
            "xiaohongshu",
            self.config,
            configured_user_agent=cfg.get("xiaohongshu", "user_agent", DEFAULT_USER_AGENT),
            default_user_agent=DEFAULT_USER_AGENT,
        )

    def _user_agent(self) -> str:
        return str(getattr(self, "user_agent", "") or DEFAULT_USER_AGENT)

    def _proxy(self) -> str | None:
        return self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))

    def _max_items_limit(self) -> int:
        default_limit = get_setting_default("xiaohongshu", "max_items")
        value = self.config.get("max_items", cfg.get("xiaohongshu", "max_items", default_limit))
        try:
            return max(1, min(int(value), 9999))
        except (TypeError, ValueError):
            return int(default_limit)

    def _search_max_pages(self) -> int:
        default_pages = get_setting_default("xiaohongshu", "search_max_pages")
        value = self.config.get("search_max_pages", cfg.get("xiaohongshu", "search_max_pages", default_pages))
        try:
            return max(1, min(int(value), 100))
        except (TypeError, ValueError):
            return int(default_pages)

    def _request_interval(self) -> float:
        default_interval = get_setting_default("xiaohongshu", "request_interval")
        value = self.config.get("request_interval", cfg.get("xiaohongshu", "request_interval", default_interval))
        try:
            return max(0.0, min(float(value), 10.0))
        except (TypeError, ValueError):
            return float(default_interval)

    def _pause_between_requests(self, multiplier: float = 1.0) -> None:
        delay = self._request_interval() * max(multiplier, 0.0)
        if delay > 0:
            self.interruptible_sleep(delay, step=min(0.5, delay))

    def _detail_request_interval(self) -> float:
        default_interval = get_setting_default("xiaohongshu", "detail_request_interval")
        value = self.config.get(
            "detail_request_interval",
            cfg.get("xiaohongshu", "detail_request_interval", default_interval),
        )
        try:
            return max(0.0, min(float(value), 5.0))
        except (TypeError, ValueError):
            return float(default_interval)

    def _pause_between_detail_requests(self, multiplier: float = 1.0) -> None:
        delay = self._detail_request_interval() * max(multiplier, 0.0)
        if delay > 0:
            self.interruptible_sleep(delay, step=min(0.5, delay))

    def _detail_pause_multiplier(self) -> float:
        # Parse details faster than list crawling, but still yield periodically.
        if self._detail_request_count <= 6:
            return 0.75
        if self._detail_request_count > 0 and self._detail_request_count % 16 == 0:
            return 1.9
        if self._detail_request_count > 0 and self._detail_request_count % 8 == 0:
            return 1.15
        return 1.0

    @staticmethod
    def _should_log_progress(current: int, total: int, *, step: int = 10) -> bool:
        current = max(0, int(current or 0))
        total = max(0, int(total or 0))
        if current <= 3 or current >= total:
            return True
        return step > 0 and current % step == 0

    @staticmethod
    def _first_text(*values: object) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _nested_dict(*values: object) -> dict[str, Any]:
        for value in values:
            if isinstance(value, dict):
                return value
        return {}

    @classmethod
    def _detail_worker_count(cls, total: int) -> int:
        return max(1, min(int(total or 1), cls.DETAIL_WORKER_CAP))

    def _should_stream_download_items(self) -> bool:
        """Keep user confirmation as the default boundary before queueing downloads."""
        value = self.config.get("stream_downloads")
        if value is None:
            return False
        return bool(value)

    @staticmethod
    def _extract_search_ref(entry: dict[str, Any]) -> dict[str, str] | None:
        if not isinstance(entry, dict):
            return None
        if entry.get("model_type") in {"rec_query", "hot_query"}:
            return None
        note_card = entry.get("note_card") if isinstance(entry.get("note_card"), dict) else {}
        note_info = entry.get("note_info") if isinstance(entry.get("note_info"), dict) else {}
        note = entry.get("note") if isinstance(entry.get("note"), dict) else {}
        note_id = str(
            entry.get("id")
            or entry.get("note_id")
            or note_card.get("note_id")
            or note_card.get("id")
            or note_info.get("note_id")
            or note_info.get("id")
            or note.get("note_id")
            or note.get("id")
            or ""
        ).strip()
        if not note_id:
            return None
        user = XiaohongshuSpider._nested_dict(
            note_card.get("user"),
            note_card.get("user_info"),
            note_info.get("user"),
            note_info.get("user_info"),
            note.get("user"),
            entry.get("user"),
            entry.get("author"),
        )
        title = XiaohongshuSpider._first_text(
            entry.get("display_title"),
            entry.get("title"),
            note_card.get("display_title"),
            note_card.get("title"),
            note_info.get("display_title"),
            note_info.get("title"),
            note.get("display_title"),
            note.get("title"),
            note.get("desc"),
        )
        author = XiaohongshuSpider._first_text(
            user.get("nickname"),
            user.get("nick_name"),
            user.get("name"),
        )
        note_type = XiaohongshuSpider._first_text(
            entry.get("type"),
            entry.get("note_type"),
            note_card.get("type"),
            note_card.get("note_type"),
            note_info.get("type"),
            note.get("type"),
        )
        return {
            "note_id": note_id,
            "xsec_source": str(
                entry.get("xsec_source")
                or note_card.get("xsec_source")
                or note_info.get("xsec_source")
                or note.get("xsec_source")
                or "pc_search"
            ),
            "xsec_token": str(
                entry.get("xsec_token")
                or note_card.get("xsec_token")
                or note_info.get("xsec_token")
                or note.get("xsec_token")
                or ""
            ),
            "title": title,
            "author": author,
            "note_type": note_type,
        }

    def _resolve_short_share_url(self, url: str) -> str:
        lowered = url.lower()
        if not lowered.startswith(("http://", "https://")):
            return url.strip()
        if "xhslink.com" not in lowered and "xhslink.cn" not in lowered:
            return url.strip()
        try:
            proxy = self._proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            response = requests.get(
                url,
                headers={"User-Agent": self._user_agent(), "Referer": self.HOME_URL},
                timeout=self._configured_timeout_seconds(default=30),
                allow_redirects=True,
                proxies=proxies,
            )
            resolved = response.url or url
            self.log(f"🔗 [分享链接解析] {url} -> {resolved}")
            return resolved
        except requests.RequestException as exc:
            self.log(f"⚠️ 小红书分享链接解析失败: {exc}")
            return url.strip()

    def _normalize_keyword(self, raw_text: str) -> str:
        extracted = extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _classify_input(self, normalized_keyword: str) -> tuple[str, str]:
        raw = normalized_keyword.strip()
        creator_lookup = parse_creator_lookup_input(raw)
        if creator_lookup:
            return ("creator_lookup", creator_lookup.keyword)
        if is_note_url(raw):
            return ("note_url", raw)
        if is_creator_url(raw):
            return ("creator_url", raw)
        if len(raw) == 24 and all(ch in "0123456789abcdef" for ch in raw.lower()):
            return ("creator_id", raw)
        return ("keyword", raw)

    def _current_web_session(self, cookies: list[dict[str, Any]] | dict[str, Any] | None) -> str:
        cookie_dict = self.auth_service.extract_cookie_dict(cookies)
        return str(cookie_dict.get("web_session") or "")

    def _discard_saved_cookie_file(self) -> None:
        if not os.path.exists(self.auth_file):
            return
        try:
            os.remove(self.auth_file)
        except OSError:
            pass

    def _probe_cookie_login_status(self, cookie_str: str) -> bool | None:
        if not cookie_str:
            return False
        client = self._build_client(cookie_str)
        if not client.check_cookie_ready():
            return False
        return client.probe_login_status()

    def _page_shows_logged_in_state(self, page, *, context, baseline_web_session: str = "") -> bool:
        try:
            if page.locator(self.PROFILE_READY_SELECTOR).count() > 0:
                return True
        except (PlaywrightError, RuntimeError, AttributeError) as exc:
            debug_logger.log_exception("XiaohongshuSpider", "profile_ready_probe", exc)
        current_web_session = self._current_web_session(context.cookies())
        if baseline_web_session and current_web_session and current_web_session != baseline_web_session:
            return True
        return False

    def _load_saved_cookie_string(self) -> str:
        if not os.path.exists(self.auth_file):
            return ""
        payload = self.auth_service.load_json_file(self.auth_file)
        if not payload:
            return ""
        cookie_str = self.auth_service.build_cookie_string(payload, required_cookie="a1")
        if not cookie_str:
            return ""
        login_status = self._probe_cookie_login_status(cookie_str)
        if login_status is True:
            return cookie_str
        if login_status is False:
            self.log("⚠️ 本地小红书 Cookie 已失效，已丢弃并准备重新登录")
            self._discard_saved_cookie_file()
        else:
            self.log("⚠️ 无法确认本地小红书 Cookie 登录态，本次将重新获取会话")
        return ""

    def _save_context_cookies(self, context) -> str:
        cookies = context.cookies()
        self.auth_service.save_json_file(self.auth_file, cookies)
        return self.auth_service.build_cookie_string(cookies, required_cookie="a1")

    def _bootstrap_cookie_string(self, entry_url: str) -> str:
        self.log("🔐 未找到可用的小红书 Cookie，启动浏览器采集会话...")
        proxy = self._proxy()
        launch_kwargs: dict[str, Any] = {"headless": self._browser_headless(login_window=True)}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
            self.log(f"🌍 使用代理: {proxy}")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            self._track_playwright_instance(playwright)
            self._track_playwright_browser(browser)
            try:
                context = browser.new_context(
                    **self._playwright_context_kwargs(
                        user_agent=self._user_agent(),
                        referer=self.HOME_URL,
                        viewport={"width": 1280, "height": 800},
                    )
                )
                self._apply_stealth_to_context(context)
                if os.path.exists(self.auth_file):
                    try:
                        self.auth_service.restore_playwright_cookies(context, self.auth_file)
                        self.log("📂 已尝试恢复本地小红书 Cookie")
                    except Exception:
                        self.log("⚠️ 本地小红书 Cookie 恢复失败，继续使用新会话")
                page = context.new_page()
                target = entry_url or self.HOME_URL
                baseline_web_session = self._current_web_session(context.cookies())
                if not self.interruptible_playwright_goto(
                    page,
                    target,
                    wait_until="domcontentloaded",
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    return ""
                if not self.interruptible_page_wait(page, 3000):
                    return ""
                if self._page_shows_logged_in_state(page, context=context, baseline_web_session=baseline_web_session):
                    cookie_str = self._save_context_cookies(context)
                    if cookie_str:
                        self.log("✅ 检测到已登录的小红书会话，Cookie 已保存")
                    return cookie_str

                self.log("🔑 若页面要求登录，请在浏览器中完成登录；程序会继续等待会话稳定")
                for _ in range(120):
                    if not self.is_running:
                        return ""
                    if not self.interruptible_page_wait(page, 1000):
                        return ""
                    if self._page_shows_logged_in_state(
                        page,
                        context=context,
                        baseline_web_session=baseline_web_session,
                    ):
                        cookie_str = self._save_context_cookies(context)
                        self.log("✅ 小红书登录成功，Cookie 已保存")
                        return cookie_str
                return ""
            finally:
                self._close_tracked_playwright_browser(browser)
                self._clear_playwright_instance(playwright)

    def _ensure_cookie_string(self, entry_url: str) -> str:
        cookie_str = self._load_saved_cookie_string()
        if cookie_str:
            self.log(f"👤 已加载本地小红书 Cookie: {self.auth_file}")
            return cookie_str
        return self._bootstrap_cookie_string(entry_url)

    def _build_client(self, cookie_str: str) -> XiaohongshuClient:
        default_timeout = get_setting_default("xiaohongshu", "timeout")
        return XiaohongshuClient(
            user_agent=self._user_agent(),
            cookie_str=cookie_str,
            proxy=self._proxy(),
            timeout=int(self.config.get("timeout", cfg.get("xiaohongshu", "timeout", default_timeout)) or default_timeout),
        )

    def _fetch_note_detail(self, client: XiaohongshuClient, ref: dict[str, str]) -> dict[str, Any] | None:
        note_id = ref.get("note_id", "")
        xsec_source = ref.get("xsec_source", "")
        xsec_token = ref.get("xsec_token", "")
        with self._detail_request_lock:
            self._detail_request_count += 1
        try:
            detail = client.get_note_detail(note_id=note_id, xsec_source=xsec_source, xsec_token=xsec_token)
            if not detail:
                detail = client.get_note_detail_from_html(
                    note_id=note_id,
                    xsec_source=xsec_source,
                    xsec_token=xsec_token,
                )
            if not detail:
                self.log(f"⚠️ 无法解析小红书笔记详情: {note_id}")
                return None
            return self.parser.normalize_note(detail)
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            self.log(f"⚠️ 获取小红书笔记失败: {note_id} | {exc}")
            if status_code == 461:
                self.log("⏳ 小红书返回 461，触发限流冷却后继续")
                self._pause_between_requests(multiplier=4.0)
            return None
        except Exception as exc:
            self.log(f"⚠️ 获取小红书笔记失败: {note_id} | {exc}")
            return None

    def _emit_note_items(self, note: dict[str, Any], cookie_str: str, referer: str) -> int:
        items = self.task_builder.build_items(
            note,
            trace_id_factory=self.new_trace_id,
            referer=referer,
            user_agent=self._user_agent(),
            cookie_str=cookie_str,
            proxy=self._proxy(),
        )
        for item in items:
            self.emit_video(
                item.url,
                item.title,
                "xiaohongshu",
                meta=item.meta,
            )
        return len(items)

    def _handle_note_url(
        self,
        client: XiaohongshuClient,
        note_info: NoteUrlInfo,
        cookie_str: str,
        *,
        referer: str,
    ) -> None:
        note = self._fetch_note_detail(
            client,
            {
                "note_id": note_info.note_id,
                "xsec_source": note_info.xsec_source,
                "xsec_token": note_info.xsec_token,
            },
        )
        if not note:
            self.log("❌ 未能获取指定小红书笔记详情")
            return
        count = self._emit_note_items(note, cookie_str, referer=referer)
        self.log(f"✅ 已生成 {count} 个小红书下载任务")

    def _collect_search_refs(self, client: XiaohongshuClient, keyword: str) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        limit = self._max_items_limit()
        page_size = 20
        max_pages = self._search_max_pages()
        for page in range(1, max_pages + 1):
            if not self.is_running or len(refs) >= limit:
                break
            self.log(f"🔎 正在搜索小红书，第 {page} 页... 已发现 {len(refs)}/{limit}")
            data = client.search_notes(
                keyword=keyword,
                page=page,
                page_size=page_size,
                sort=str(
                    self.config.get("sort")
                    or cfg.get("xiaohongshu", "sort", get_setting_default("xiaohongshu", "sort"))
                ),
                note_type=int(
                    self.config.get(
                        "note_type",
                        cfg.get("xiaohongshu", "note_type", get_setting_default("xiaohongshu", "note_type")),
                    )
                ),
            )
            items = data.get("items") or []
            page_added = 0
            for entry in items:
                ref = self._extract_search_ref(entry)
                if not ref:
                    continue
                note_id = ref["note_id"]
                if note_id in seen:
                    continue
                seen.add(note_id)
                refs.append(ref)
                page_added += 1
                if self._should_log_progress(len(refs), limit):
                    self.log(f"🧾 搜索候选累计 {len(refs)}/{limit}")
                if len(refs) >= limit:
                    break
            self.log(f"📄 第 {page} 页新增 {page_added} 条候选")
            if not data.get("has_more", False):
                break
            self._pause_between_requests()
        return refs

    def _collect_creator_refs(self, client: XiaohongshuClient, creator: CreatorUrlInfo) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        cursor = ""
        limit = self._max_items_limit()
        while self.is_running and len(refs) < limit:
            self.log(f"👤 正在读取小红书作者笔记列表... 已抓到 {len(refs)}/{limit}")
            data = client.get_creator_notes(
                user_id=creator.user_id,
                cursor=cursor,
                xsec_token=creator.xsec_token,
                xsec_source=creator.xsec_source or "pc_feed",
            )
            notes = data.get("notes") or []
            for entry in notes:
                if not isinstance(entry, dict):
                    continue
                note_id = str(entry.get("note_id") or entry.get("id") or "")
                if not note_id or note_id in seen:
                    continue
                seen.add(note_id)
                user = self._nested_dict(entry.get("user"), entry.get("user_info"), entry.get("author"))
                refs.append(
                    {
                        "note_id": note_id,
                        "xsec_source": str(entry.get("xsec_source") or creator.xsec_source or "pc_feed"),
                        "xsec_token": str(entry.get("xsec_token") or creator.xsec_token or ""),
                        "title": self._first_text(
                            entry.get("display_title"),
                            entry.get("title"),
                            entry.get("desc"),
                        ),
                        "author": self._first_text(
                            user.get("nickname"),
                            user.get("nick_name"),
                            user.get("name"),
                            creator.nickname,
                        ),
                        "note_type": self._first_text(entry.get("type"), entry.get("note_type")),
                    }
                )
                if self._should_log_progress(len(refs), limit):
                    self.log(f"📚 主页候选累计 {len(refs)}/{limit}")
                if len(refs) >= limit:
                    break
            if len(refs) >= limit or not data.get("has_more", False):
                break
            cursor = str(data.get("cursor") or "")
            if not cursor:
                break
            self._pause_between_requests(multiplier=1.5)
        return refs

    def _extract_creator_search_candidates(self, payload: dict[str, Any]) -> list[CreatorUrlInfo]:
        items = payload.get("users") or payload.get("items") or payload.get("user_list") or []
        candidates: list[CreatorUrlInfo] = []
        seen: set[str] = set()
        for entry in items:
            if not isinstance(entry, dict):
                continue
            user = (
                entry.get("user")
                if isinstance(entry.get("user"), dict)
                else entry.get("user_info")
                if isinstance(entry.get("user_info"), dict)
                else entry.get("author")
                if isinstance(entry.get("author"), dict)
                else entry.get("user_card")
                if isinstance(entry.get("user_card"), dict)
                else entry
            )
            user_id = str(user.get("user_id") or user.get("id") or user.get("userid") or "").strip()
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            candidates.append(
                CreatorUrlInfo(
                    user_id=user_id,
                    xsec_token=str(user.get("xsec_token") or entry.get("xsec_token") or ""),
                    xsec_source=str(user.get("xsec_source") or entry.get("xsec_source") or "pc_search"),
                    nickname=str(user.get("nickname") or user.get("nick_name") or entry.get("title") or "").strip(),
                    red_id=str(
                        user.get("red_id")
                        or user.get("redId")
                        or user.get("xhs_id")
                        or user.get("display_id")
                        or user.get("redid")
                        or ""
                    ).strip(),
                )
            )
        return candidates

    def _extract_creator_candidates_from_note_search(
        self, payload: dict[str, Any], lookup_keyword: str
    ) -> list[CreatorUrlInfo]:
        items = payload.get("items") or []
        candidates_by_user: dict[str, CreatorUrlInfo] = {}
        keyword = lookup_keyword.strip().lower()
        for entry in items:
            if not isinstance(entry, dict):
                continue
            note_card = entry.get("note_card") if isinstance(entry.get("note_card"), dict) else {}
            user = note_card.get("user") if isinstance(note_card.get("user"), dict) else {}
            user_id = str(user.get("user_id") or user.get("id") or "").strip()
            if not user_id:
                continue
            note_hint = str(
                note_card.get("display_title")
                or note_card.get("title")
                or entry.get("display_title")
                or entry.get("title")
                or ""
            ).strip()
            candidate = candidates_by_user.get(user_id)
            if candidate is None:
                candidates_by_user[user_id] = CreatorUrlInfo(
                    user_id=user_id,
                    xsec_token=str(user.get("xsec_token") or ""),
                    xsec_source=str(entry.get("xsec_source") or "pc_search"),
                    nickname=str(user.get("nickname") or user.get("nick_name") or "").strip(),
                    red_id=str(
                        user.get("red_id")
                        or user.get("redId")
                        or user.get("xhs_id")
                        or user.get("display_id")
                        or user.get("redid")
                        or ""
                    ).strip(),
                    note_hint=note_hint,
                )
            elif note_hint and not candidate.note_hint:
                candidate.note_hint = note_hint

        def _score(candidate: CreatorUrlInfo) -> tuple[int, int, int]:
            red_id = candidate.red_id.lower()
            nickname = candidate.nickname.lower()
            note_hint = candidate.note_hint.lower()
            red_id_exact = 0 if keyword and red_id == keyword else 1
            nickname_exact = 0 if keyword and nickname == keyword else 1
            text_contains = 0 if keyword and keyword in f"{red_id} {nickname} {note_hint}" else 1
            return (red_id_exact, nickname_exact, text_contains)

        return sorted(candidates_by_user.values(), key=_score)

    def _pick_creator_candidate(self, candidates: list[CreatorUrlInfo], *, source_label: str) -> CreatorUrlInfo | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        dialog_items = [
            {
                "title": " / ".join(
                    part
                    for part in (candidate.nickname, candidate.red_id, candidate.note_hint[:24], candidate.user_id)
                    if part
                ),
                "index": idx,
            }
            for idx, candidate in enumerate(candidates)
        ]
        self.log(f"🧾 {source_label}共发现 {len(dialog_items)} 个账号候选，请选择主页...")
        selected = self.ask_user_selection(dialog_items)
        if not selected:
            self.log(f"⚠️ 用户取消了{source_label}账号选择流程")
            return None
        chosen_idx = selected[0]
        if not isinstance(chosen_idx, int) or chosen_idx < 0 or chosen_idx >= len(candidates):
            return None
        return candidates[chosen_idx]

    def _lookup_creator_by_keyword(self, client: XiaohongshuClient, lookup: CreatorLookupInfo) -> CreatorUrlInfo | None:
        self.log(f"🔍 正在搜索小红书账号: {lookup.keyword}")
        try:
            data = client.search_notes(keyword=lookup.keyword, page=1, page_size=20)
        except Exception as exc:
            self.log(f"⚠️ 小红书号预搜索失败，回退到网页用户搜索: {exc}")
            return self._lookup_creator_by_browser_search(lookup)
        candidates = self._extract_creator_candidates_from_note_search(data, lookup.keyword)
        if not candidates:
            self.log(f"⚠️ 预搜索未提取到小红书账号候选，回退网页用户搜索: {lookup.keyword}")
            return self._lookup_creator_by_browser_search(lookup)
        return self._pick_creator_candidate(candidates, source_label="预搜索")

    def _lookup_creator_by_browser_search(self, lookup: CreatorLookupInfo) -> CreatorUrlInfo | None:
        self.log(f"🌐 正在通过网页搜索小红书号: {lookup.keyword}")
        proxy = self._proxy()
        launch_kwargs: dict[str, Any] = {"headless": self._browser_headless()}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            self._track_playwright_instance(playwright)
            self._track_playwright_browser(browser)
            try:
                context = browser.new_context(
                    **self._playwright_context_kwargs(
                        user_agent=self._user_agent(),
                        referer=self.HOME_URL,
                        viewport={"width": 1280, "height": 800},
                    )
                )
                self._apply_stealth_to_context(context)
                if os.path.exists(self.auth_file):
                    try:
                        self.auth_service.restore_playwright_cookies(context, self.auth_file)
                    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
                        debug_logger.log_exception("XiaohongshuSpider", "restore_playwright_cookies", exc)
                page = context.new_page()
                search_url = f"{self.HOME_URL}search_result?keyword={quote(lookup.keyword)}&type=51"
                if not self.interruptible_playwright_goto(
                    page,
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    return None
                if not self.interruptible_page_wait(page, 3000):
                    return None
                current_url = page.url
                if "/login" in current_url:
                    self.log("⚠️ 网页用户搜索被重定向到登录页，无法直接解析小红书号")
                    return None
                raw_candidates = page.locator("a[href*='/user/profile/']").evaluate_all(
                    """(elements) => elements.map((el) => ({
                        href: el.href || '',
                        text: (el.textContent || '').trim()
                    }))"""
                )
                candidates: list[CreatorUrlInfo] = []
                seen: set[str] = set()
                for item in raw_candidates:
                    href = str(item.get("href") or "").strip()
                    if not href:
                        continue
                    try:
                        parsed = parse_creator_info_from_url(href)
                    except ValueError:
                        continue
                    if parsed.user_id in seen:
                        continue
                    seen.add(parsed.user_id)
                    candidates.append(
                        CreatorUrlInfo(
                            user_id=parsed.user_id,
                            xsec_token=parsed.xsec_token,
                            xsec_source=parsed.xsec_source or "pc_search",
                            nickname=str(item.get("text") or "").strip(),
                        )
                    )
                if not candidates:
                    self.log(f"⚠️ 网页用户搜索未找到匹配的小红书号: {lookup.keyword}")
                    return None
                return self._pick_creator_candidate(candidates, source_label="网页搜索")
            finally:
                self._close_tracked_playwright_browser(browser)
                self._clear_playwright_instance(playwright)

    def _handle_multi_refs(self, client: XiaohongshuClient, refs: list[dict[str, str]], cookie_str: str) -> None:
        if not refs:
            self.log("⚠️ 未找到可处理的小红书结果")
            return

        if self._should_stream_download_items():
            self._handle_multi_refs_streaming(client, refs, cookie_str)
            return

        selected_refs = self._select_refs_before_detail(refs)
        if selected_refs is None:
            return
        if not selected_refs:
            self.log("No XiaoHongShu items selected; crawl finished without queueing downloads.")
            return
        self.log(f"XiaoHongShu user confirmed {len(selected_refs)} candidates; starting parse-to-download pipeline.")
        self._handle_multi_refs_streaming(
            client,
            selected_refs,
            cookie_str,
            require_user_confirmed=True,
        )
        return

    def _build_ref_selection_entry(self, ref: dict[str, Any], index: int) -> dict[str, Any]:
        title = self._first_text(ref.get("title"), ref.get("note_id"), f"XiaoHongShu note {index + 1}")
        author = self._first_text(ref.get("author"))
        note_type = self._first_text(ref.get("note_type"), ref.get("type"))
        parts = [title]
        if author:
            parts.append(author)
        if note_type:
            parts.append(note_type)
        return {
            "title": " | ".join(parts),
            "note_id": ref.get("note_id", ""),
            "note_type": note_type,
            "author": author,
            "index": index,
        }

    def _select_refs_before_detail(self, refs: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if len(refs) == 1:
            return list(refs)
        selection_entries = [self._build_ref_selection_entry(ref, index) for index, ref in enumerate(refs)]
        self.log(f"XiaoHongShu found {len(selection_entries)} candidates; waiting for user confirmation before parsing details.")
        selected = self.ask_user_selection(selection_entries)
        if selected is None:
            self.log("XiaoHongShu selection was cancelled by the user.")
            return None
        selected_refs: list[dict[str, Any]] = []
        for idx in selected:
            if not isinstance(idx, int) or idx < 0 or idx >= len(refs):
                continue
            selected_refs.append(refs[idx])
        return selected_refs

    def _handle_multi_refs_streaming(
        self,
        client: XiaohongshuClient,
        refs: list[dict[str, str]],
        cookie_str: str,
        *,
        require_user_confirmed: bool = False,
    ) -> None:
        total_refs = len(refs)
        worker_count = self._detail_worker_count(total_refs)
        parsed = 0
        emitted = 0
        if require_user_confirmed:
            self.log(f"XiaoHongShu confirmed pipeline is active: {total_refs} selected candidates.")
        self.log(f"🚀 小红书流水线模式：详情解析成功后立即投递下载队列 | 候选 {total_refs}")

        def fetch_one(index_ref: tuple[int, dict[str, str]]) -> tuple[int, dict[str, Any] | None]:
            idx, ref = index_ref
            if not self.is_running:
                return idx, None
            worker_client = self._build_client(cookie_str) if worker_count > 1 else client
            try:
                return idx, self._fetch_note_detail(worker_client, ref)
            finally:
                if worker_client is not client:
                    worker_client.close()

        indexed_refs = list(enumerate(refs, 1))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="xhs-detail") as executor:
            future_map = {executor.submit(fetch_one, index_ref): index_ref[0] for index_ref in indexed_refs}
            completed_refs = 0
            for future in as_completed(future_map):
                idx = future_map[future]
                completed_refs += 1
                if not self.is_running:
                    break
                try:
                    _idx, detail = future.result()
                except Exception as exc:
                    self.log(f"⚠️ 小红书笔记详情线程失败 {idx} | {exc}")
                    detail = None
                if detail:
                    parsed += 1
                    referer = f"{self.HOME_URL}explore/{detail.get('note_id', '')}"
                    emitted += self._emit_note_items(detail, cookie_str, referer=referer)
                if self._should_log_progress(completed_refs, total_refs):
                    self.log(f"📥 已解析详情 {completed_refs}/{total_refs} | 成功 {parsed} | 已投递 {emitted}")

        if not self.revive_for_partial_selection(parsed, "条候选笔记"):
            return
        if parsed <= 0:
            self.log("⚠️ 未能成功解析任何小红书笔记详情，全程未投递下载项")
            return
        self.log(f"✅ 小红书流水线投递完成，共投递 {emitted} 个下载项")

    def run(self) -> None:
        self.log(f"🚀 启动小红书任务 | 目标: {self.keyword}")
        self.debug_state(
            action="run_start",
            message="启动小红书爬虫任务",
            status_code="XHS_SPIDER_START",
            context={"keyword": self.keyword},
            details={"config": self.config},
        )
        try:
            normalized_keyword = self._normalize_keyword(self.keyword)
            if normalized_keyword != self.keyword.strip():
                self.log(f"🔗 小红书输入已归一化: {normalized_keyword}")
            route, route_value = self._classify_input(normalized_keyword)
            entry_url = normalized_keyword if normalized_keyword.startswith("http") else self.HOME_URL
            cookie_str = self._ensure_cookie_string(entry_url)
            if not cookie_str:
                raise SpiderAuthError("无法获取小红书会话 Cookie（至少需要 a1）")

            client = self._build_client(cookie_str)
            self._client = client
            if not client.check_cookie_ready():
                raise SpiderAuthError("小红书 Cookie 缺少 a1，无法进行签名请求")
            login_status = client.probe_login_status()
            if login_status is False:
                raise SpiderAuthError("小红书 Cookie 无有效登录态，请重新登录后再试")
            if login_status is None:
                self.log("⚠️ 小红书登录态探活失败，继续尝试使用当前浏览器确认过的会话")

            if route == "note_url":
                self._handle_note_url(
                    client,
                    parse_note_info_from_note_url(route_value),
                    cookie_str,
                    referer=route_value,
                )
            elif route in {"creator_url", "creator_id"}:
                creator = parse_creator_info_from_url(route_value)
                refs = self._collect_creator_refs(client, creator)
                self._handle_multi_refs(client, refs, cookie_str)
            elif route == "creator_lookup":
                creator = self._lookup_creator_by_keyword(client, CreatorLookupInfo(keyword=route_value))
                if creator:
                    refs = self._collect_creator_refs(client, creator)
                else:
                    self.log(f"↩️ 小红书号未命中主页结果，回退为关键词搜索: {route_value}")
                    refs = self._collect_search_refs(client, route_value)
                self._handle_multi_refs(client, refs, cookie_str)
            else:
                refs = self._collect_search_refs(client, route_value)
                self._handle_multi_refs(client, refs, cookie_str)
        except (SpiderAuthError, SpiderParseError, ValueError, PlaywrightError) as exc:
            self.log(f"❌ 小红书任务失败: {exc}")
            self.debug_state(
                action="run_error",
                message="小红书爬虫运行异常",
                status_code="XHS_SPIDER_ERROR",
                details={"error": str(exc)},
            )
        except Exception as exc:
            self.log(f"💥 小红书运行时异常: {exc}")
            self.debug_state(
                action="run_error",
                message="小红书爬虫运行异常",
                status_code="XHS_SPIDER_ERROR",
                details={"error": str(exc)},
            )
        finally:
            client = getattr(self, "_client", None)
            if client is not None:
                client.close()
                self._client = None
            self.debug_state(
                action="run_finish",
                message="小红书爬虫任务结束",
                status_code="XHS_SPIDER_FINISH",
            )
            self._emit_finished()
