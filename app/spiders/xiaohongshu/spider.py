"""XiaoHongShu spider adapted to UniversalCrawlerProplus conventions."""

from __future__ import annotations

import os
from typing import Any

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg
from app.exceptions import SpiderAuthError, SpiderParseError
from app.spiders.base import BaseSpider
from app.services.auth_service import AuthService

from .client import XiaohongshuClient
from .helpers import (
    CreatorUrlInfo,
    NoteUrlInfo,
    is_creator_url,
    is_note_url,
    parse_creator_info_from_url,
    parse_note_info_from_note_url,
)
from .parser import XiaohongshuParser
from .task_builder import XiaohongshuTaskBuilder


class XiaohongshuSpider(BaseSpider):
    """Browser-assisted XiaoHongShu spider."""

    HOME_URL = "https://www.xiaohongshu.com/"
    PROFILE_READY_SELECTOR = "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']"

    def __init__(self, keyword: str, config: dict):
        super().__init__(keyword, config)
        self.parser = XiaohongshuParser()
        self.task_builder = XiaohongshuTaskBuilder()
        self.auth_service = AuthService()
        self.auth_file = cfg.get("auth", "xiaohongshu_cookie_file", "xhs_auth.json")

    def _user_agent(self) -> str:
        return str(self.config.get("ua") or cfg.get("xiaohongshu", "user_agent", DEFAULT_USER_AGENT))

    def _proxy(self) -> str | None:
        proxy = self.config.get("proxy")
        return str(proxy).strip() if proxy else None

    def _max_items_limit(self) -> int:
        value = self.config.get("max_items", cfg.get("xiaohongshu", "max_items", 20))
        try:
            return max(1, min(int(value), 9999))
        except (TypeError, ValueError):
            return 20

    def _search_max_pages(self) -> int:
        value = self.config.get("search_max_pages", cfg.get("xiaohongshu", "search_max_pages", 5))
        try:
            return max(1, min(int(value), 100))
        except (TypeError, ValueError):
            return 5

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
        except Exception:
            pass
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
        launch_kwargs: dict[str, Any] = {"headless": False}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
            self.log(f"🌍 使用代理: {proxy}")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            self._playwright_pw = playwright
            self._playwright_browser = browser
            try:
                context = browser.new_context(user_agent=self._user_agent())
                if os.path.exists(self.auth_file):
                    try:
                        self.auth_service.restore_playwright_cookies(context, self.auth_file)
                        self.log("📂 已尝试恢复本地小红书 Cookie")
                    except Exception:
                        self.log("⚠️ 本地小红书 Cookie 恢复失败，继续使用新会话")
                page = context.new_page()
                target = entry_url or self.HOME_URL
                baseline_web_session = self._current_web_session(context.cookies())
                page.goto(target, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                if self._page_shows_logged_in_state(page, context=context, baseline_web_session=baseline_web_session):
                    cookie_str = self._save_context_cookies(context)
                    if cookie_str:
                        self.log("✅ 检测到已登录的小红书会话，Cookie 已保存")
                    return cookie_str

                self.log("🔑 若页面要求登录，请在浏览器中完成登录；程序会继续等待会话稳定")
                for _ in range(120):
                    if not self.is_running:
                        return ""
                    page.wait_for_timeout(1000)
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
                try:
                    browser.close()
                except Exception:
                    pass
                self._playwright_browser = None
                self._playwright_pw = None

    def _ensure_cookie_string(self, entry_url: str) -> str:
        cookie_str = self._load_saved_cookie_string()
        if cookie_str:
            self.log(f"👤 已加载本地小红书 Cookie: {self.auth_file}")
            return cookie_str
        return self._bootstrap_cookie_string(entry_url)

    def _build_client(self, cookie_str: str) -> XiaohongshuClient:
        return XiaohongshuClient(
            user_agent=self._user_agent(),
            cookie_str=cookie_str,
            proxy=self._proxy(),
            timeout=int(self.config.get("timeout", 30) or 30),
        )

    def _fetch_note_detail(self, client: XiaohongshuClient, ref: dict[str, str]) -> dict[str, Any] | None:
        note_id = ref.get("note_id", "")
        xsec_source = ref.get("xsec_source", "")
        xsec_token = ref.get("xsec_token", "")
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
            self.sig_item_found.emit(item)
        return len(items)

    def _handle_note_url(self, client: XiaohongshuClient, note_info: NoteUrlInfo, cookie_str: str) -> None:
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
        count = self._emit_note_items(note, cookie_str, referer=self.keyword)
        self.log(f"✅ 已生成 {count} 个小红书下载任务")

    def _collect_search_refs(self, client: XiaohongshuClient) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        limit = self._max_items_limit()
        page_size = min(20, limit)
        max_pages = self._search_max_pages()
        for page in range(1, max_pages + 1):
            if not self.is_running or len(refs) >= limit:
                break
            self.log(f"🔎 正在搜索小红书，第 {page} 页...")
            data = client.search_notes(
                keyword=self.keyword,
                page=page,
                page_size=page_size,
                sort=str(self.config.get("sort") or cfg.get("xiaohongshu", "sort", "general")),
                note_type=int(self.config.get("note_type", cfg.get("xiaohongshu", "note_type", 0))),
            )
            items = data.get("items") or []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                if entry.get("model_type") in {"rec_query", "hot_query"}:
                    continue
                note_id = str(entry.get("id") or "")
                if not note_id or note_id in seen:
                    continue
                seen.add(note_id)
                refs.append(
                    {
                        "note_id": note_id,
                        "xsec_source": str(entry.get("xsec_source") or "pc_search"),
                        "xsec_token": str(entry.get("xsec_token") or ""),
                    }
                )
                if len(refs) >= limit:
                    break
            if not data.get("has_more", False):
                break
        return refs

    def _collect_creator_refs(self, client: XiaohongshuClient, creator: CreatorUrlInfo) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        cursor = ""
        limit = self._max_items_limit()
        while self.is_running and len(refs) < limit:
            self.log("👤 正在读取小红书作者笔记列表...")
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
                refs.append(
                    {
                        "note_id": note_id,
                        "xsec_source": str(entry.get("xsec_source") or creator.xsec_source or "pc_feed"),
                        "xsec_token": str(entry.get("xsec_token") or creator.xsec_token or ""),
                    }
                )
                if len(refs) >= limit:
                    break
            if len(refs) >= limit or not data.get("has_more", False):
                break
            cursor = str(data.get("cursor") or "")
            if not cursor:
                break
        return refs

    def _handle_multi_refs(self, client: XiaohongshuClient, refs: list[dict[str, str]], cookie_str: str) -> None:
        if not refs:
            self.log("⚠️ 未找到可处理的小红书结果")
            return

        notes: list[dict[str, Any]] = []
        selection_entries: list[dict[str, Any]] = []
        for ref in refs:
            if not self.is_running:
                return
            detail = self._fetch_note_detail(client, ref)
            if not detail:
                continue
            notes.append(detail)
            selection_entries.append(self.parser.build_selection_entry(detail))

        if not notes:
            self.log("⚠️ 未能成功解析任何小红书笔记详情")
            return

        if len(selection_entries) == 1:
            selected = [0]
        else:
            self.log(f"🧾 共发现 {len(selection_entries)} 条小红书候选笔记，等待选择...")
            selected = self.ask_user_selection(selection_entries)
        if selected is None:
            self.log("⚠️ 用户取消了小红书选择流程")
            return

        emitted = 0
        for idx in selected:
            if not isinstance(idx, int) or idx < 0 or idx >= len(notes):
                continue
            referer = f"{self.HOME_URL}explore/{notes[idx].get('note_id', '')}"
            emitted += self._emit_note_items(notes[idx], cookie_str, referer=referer)
        self.log(f"✅ 小红书任务准备完成，共生成 {emitted} 个下载项")

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
            entry_url = self.keyword if self.keyword.startswith("http") else self.HOME_URL
            cookie_str = self._ensure_cookie_string(entry_url)
            if not cookie_str:
                raise SpiderAuthError("无法获取小红书会话 Cookie（至少需要 a1）")

            client = self._build_client(cookie_str)
            if not client.check_cookie_ready():
                raise SpiderAuthError("小红书 Cookie 缺少 a1，无法进行签名请求")
            login_status = client.probe_login_status()
            if login_status is False:
                raise SpiderAuthError("小红书 Cookie 无有效登录态，请重新登录后再试")
            if login_status is None:
                self.log("⚠️ 小红书登录态探活失败，继续尝试使用当前浏览器确认过的会话")

            if is_note_url(self.keyword):
                self._handle_note_url(client, parse_note_info_from_note_url(self.keyword), cookie_str)
            elif is_creator_url(self.keyword) or (
                len(self.keyword.strip()) == 24 and self.keyword.strip().isalnum()
            ):
                creator = parse_creator_info_from_url(self.keyword)
                refs = self._collect_creator_refs(client, creator)
                self._handle_multi_refs(client, refs, cookie_str)
            else:
                refs = self._collect_search_refs(client)
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
            self.debug_state(
                action="run_finish",
                message="小红书爬虫任务结束",
                status_code="XHS_SPIDER_FINISH",
            )
            self.sig_finished.emit()
