"""Kuaishou spider with browser-driven scan and realtime stream capture."""

import json
import os
import random
import re
import threading
import urllib.parse

import requests
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg, get_setting_default
from app.spiders.base import BaseSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.services.auth_service import AuthService

class KuaishouSpider(BaseSpider):
    """快手爬虫，负责页面滚动扫描、任务选择和流监听。"""

    def __init__(self, keyword: str, config: dict):
        """初始化当前实例并准备运行所需的状态，供 `KuaishouSpider` 使用。"""
        super().__init__(keyword, config)
        self.parser = KuaishouParser()
        self.task_builder = KuaishouTaskBuilder()
        self.auth_service = AuthService()
        self._selected_indices: list[int] = []
        self._lock = threading.Lock()

    def _max_items_limit(self) -> int:
        """提供 `_max_items_limit` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        default_limit = get_setting_default("kuaishou", "max_items")
        limit = self.config.get("max_items", cfg.get("kuaishou", "max_items", default_limit))
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return int(default_limit)

    def _build_proxy_cfg(self) -> dict[str, str] | None:
        """提供 `_build_proxy_cfg` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        proxy = self.config.get("proxy")
        if not proxy:
            return None
        self.log(f"🌍 使用代理: {proxy}")
        return {"server": proxy}

    def _load_saved_cookies(self, context, auth_file: str) -> None:
        """提供 `_load_saved_cookies` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if not os.path.exists(auth_file):
            return
        try:
            if self.auth_service.restore_playwright_cookies(context, auth_file):
                self.log("📂 加载本地 Cookie 成功")
        except (OSError, TypeError, ValueError, PlaywrightError):
            self.log("⚠️ 本地 Cookie 加载失败，继续尝试页面登录")

    def _goto_with_retry(self, page, url: str, *, description: str, attempts: int = 2) -> bool:
        """提供 `_goto_with_retry` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        target_url = url.strip().strip("`")
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=60000,
                    wait_until="domcontentloaded",
                ):
                    return False
                self.interruptible_page_wait(page, 1500)
                return True
            except PlaywrightError as exc:
                last_error = exc
                self.log(f"⚠️ {description}失败，第 {attempt}/{attempts} 次重试: {exc}")
                self.interruptible_page_wait(page, 1000)
        if last_error:
            self.log(f"❌ {description}失败: {last_error}")
        return False

    def _extract_first_url(self, raw_text: str) -> str:
        """从分享文案中提取第一个 URL；没有则回退原始输入。"""
        raw = str(raw_text or "").strip()
        match = re.search(r"https?://[^\s`，。！？；;,)）\]'\"]+", raw)
        candidate = match.group(0) if match else raw
        return candidate.rstrip("，。！？；;,.!?)）]}'\"")

    def _is_kuaishou_url(self, raw_text: str) -> bool:
        """判断输入是否为快手相关 URL。"""
        lowered = str(raw_text or "").lower()
        return any(domain in lowered for domain in ("kuaishou.com", "chenzhongtech.com"))

    def _is_detail_url(self, raw_text: str) -> bool:
        """识别快手单条作品详情链接。"""
        lowered = str(raw_text or "").lower()
        return any(
            marker in lowered
            for marker in ("/short-video/", "/fw/photo/", "photoid=", "chenzhongtech.com/fw/photo/")
        )

    def _resolve_short_share_url(self, url: str) -> str:
        """将快手短分享链解析为最终详情或主页链接。"""
        if not self._is_kuaishou_url(url):
            return url
        lowered = url.lower()
        if "v.kuaishou.com" not in lowered and "kuaishou.com/f/" not in lowered:
            return url
        try:
            response = requests.get(
                url,
                headers={"User-Agent": cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT)},
                timeout=cfg.get("kuaishou", "timeout", get_setting_default("kuaishou", "timeout")),
                allow_redirects=True,
            )
            resolved = response.url or url
            self.log(f"🔗 [分享链接解析] {url} -> {resolved}")
            return resolved
        except requests.RequestException as exc:
            self.log(f"⚠️ [分享链接解析失败] {exc}")
            return url

    def _normalize_keyword(self, raw_text: str) -> str:
        """兼容分享文案、短链和完整快手链接。"""
        extracted = self._extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _build_detail_request_headers(self) -> dict[str, str]:
        """构建分享详情页直连请求头。"""
        return {
            "User-Agent": cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
            "Referer": "https://www.kuaishou.com/",
        }

    def _extract_detail_id(self, url: str) -> str:
        """从快手详情链接中提取作品 ID。"""
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "photoId" in params:
            return params.get("photoId", [""])[0]
        path = parsed.path.rstrip("/")
        if "/short-video/" in path or "/fw/photo/" in path:
            return path.split("/")[-1]
        return ""

    def _extract_state_blob(self, html: str, prefix: str, suffix: str = "</script>") -> str:
        """从 HTML 中抽取指定状态脚本文本。"""
        if not html or prefix not in html:
            return ""
        start = html.find(prefix)
        if start < 0:
            return ""
        start += len(prefix)
        end = html.find(suffix, start)
        blob = html[start:end] if end >= 0 else html[start:]
        return blob.strip()

    def _load_json_blob(self, blob: str) -> dict:
        """尽量用 JSON 解析页面状态；失败时返回空字典。"""
        if not blob:
            return {}
        cleaned = blob.replace(
            ";(function(){var s;(s=document.currentScript||document.scripts[document.scripts.length-1]).parentNode.removeChild(s);}());",
            "",
        ).rstrip(" ;")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}

    def _extract_apollo_video_detail(self, payload: dict, detail_id: str) -> tuple[str, str]:
        """从 __APOLLO_STATE__ 中提取标题和直链。"""
        client = payload.get("defaultClient", {}) if isinstance(payload, dict) else {}
        detail = client.get(f"VisionVideoDetailPhoto:{detail_id}", {}) if isinstance(client, dict) else {}
        if not isinstance(detail, dict):
            return "", ""
        title = str(detail.get("caption") or "").strip()
        media_url = str(detail.get("photoUrl") or "").strip()
        return title, media_url

    def _fetch_share_detail_via_http(self, detail_url: str) -> tuple[str, str]:
        """通过纯 HTTP 抓取快手分享/详情页，避免弹浏览器。"""
        try:
            response = requests.get(
                detail_url,
                headers=self._build_detail_request_headers(),
                timeout=cfg.get("kuaishou", "timeout", get_setting_default("kuaishou", "timeout")),
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self.log(f"⚠️ 快手分享详情页请求失败: {exc}")
            return "", ""

        detail_id = self._extract_detail_id(response.url or detail_url)
        if not detail_id:
            return "", ""

        apollo_blob = self._extract_state_blob(response.text, "window.__APOLLO_STATE__=")
        if apollo_blob:
            title, media_url = self._extract_apollo_video_detail(self._load_json_blob(apollo_blob), detail_id)
            if media_url:
                return title or "快手分享作品", media_url

        self.log("⚠️ 快手分享页未解析到 __APOLLO_STATE__ 视频直链，将回退浏览器链路")
        return "", ""

    def _try_direct_share_download(self) -> bool:
        """分享/详情链接优先走纯 HTTP 快路，成功则不再打开浏览器。"""
        if not self._is_detail_url(self.keyword):
            return False
        self.log("🎯 检测到快手分享/详情链接，优先尝试无浏览器直连解析...")
        title, media_url = self._fetch_share_detail_via_http(self.keyword)
        if not media_url:
            return False
        trace_id = self.new_trace_id("share")
        self.debug_state(
            action="emit_share_task_http",
            message="快手分享链接已通过 HTTP 直连解析并提交到下载队列",
            status_code="KUAISHOU_SHARE_TASK_HTTP_EMIT",
            context={"trace_id": trace_id},
            details={"title": title, "stream_url": media_url, "referer": self.keyword},
        )
        self.emit_video(
            url=media_url,
            title=title,
            source="kuaishou",
            meta=self.task_builder.build_download_meta(trace_id, self.keyword, media_url),
        )
        self.log(f"✨ 已无浏览器解析分享作品: {title[:24]}...")
        return True

    def _is_logged_in(self, page) -> bool:
        """提供 `_is_logged_in` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        selectors = (
            ".header-user-avatar",
            ".user-avatar",
            ".down-box.login .user-item",
            ".down-box.login .user-item img[src]",
            ".down-box.login .text-fold",
            ".sidebar .down-box.login",
            "[class*='avatar']",
            "[class*='user-avatar']",
        )
        for selector in selectors:
            try:
                if self._locator_visible(page.locator(selector).first):
                    return True
            except PlaywrightError:
                continue
        return False

    def _refresh_logged_in_state(self, page, target_url: str) -> bool:
        """提供 `_refresh_logged_in_state` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        try:
            page.reload(wait_until="domcontentloaded", timeout=5000)
            self.interruptible_page_wait(page, 1500)
            if self._is_logged_in(page):
                return True
        except PlaywrightError:
            pass
        if target_url != "https://www.kuaishou.com/":
            try:
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=60000,
                    wait_until="domcontentloaded",
                ):
                    return False
                self.interruptible_page_wait(page, 1500)
                return self._is_logged_in(page)
            except PlaywrightError:
                return False
        return False

    def _user_cookie_values(self, context) -> set[str]:
        """提供 `_user_cookie_values` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        values: set[str] = set()
        try:
            for cookie in context.cookies():
                if cookie.get("name") == "userId" and cookie.get("value"):
                    values.add(str(cookie["value"]))
        except PlaywrightError:
            return set()
        return values

    def _wait_for_manual_login(self, page, context, auth_file: str) -> bool:
        """提供 `_wait_for_manual_login` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        initial_user_ids = self._user_cookie_values(context)
        for _ in range(120):
            if not self.is_running:
                return False
            current_user_ids = self._user_cookie_values(context)
            has_new_user_cookie = bool(current_user_ids - initial_user_ids)
            if current_user_ids and (has_new_user_cookie or self._is_logged_in(page)):
                self.auth_service.save_json_file(auth_file, context.storage_state())
                return True
            self.interruptible_page_wait(page, 1000)
        return False

    def _ensure_login(self, page, context, auth_file: str, entry_url: str | None = None) -> bool:
        """提供 `_ensure_login` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        target_url = entry_url.strip().strip("`") if entry_url else "https://www.kuaishou.com/"
        self.log("🔗 访问快手首页..." if target_url == "https://www.kuaishou.com/" else f"🔗 访问快手页面: {target_url}")
        has_loaded_cookie = bool(self._user_cookie_values(context))
        try:
            if not self._goto_with_retry(page, target_url, description="页面访问"):
                raise PlaywrightError(f"cannot open {target_url}")
            if not self._is_logged_in(page):
                if has_loaded_cookie:
                    self.log("ℹ️ 已加载本地 Cookie，尝试刷新页面重新校验登录态")
                    if self._refresh_logged_in_state(page, target_url):
                        self.log("✅ 刷新后检测到登录状态")
                        return True
                raise PlaywrightError("not logged in")
            self.log("✅ 检测到登录状态")
            return True
        except PlaywrightError:
            self.log("⚠️ 首页访问或登录态检查失败，继续尝试在当前页面恢复登录")
            if os.path.exists(auth_file):
                self.log("⚠️ 本地 Cookie 已加载，但当前页面未识别为已登录，可能已失效")
            self.log("🔑 请在当前快手页面手动登录或扫码，登录成功后程序会自动继续")
            self._open_login_entry(page)

            success = self._wait_for_manual_login(page, context, auth_file)
            if success:
                self.log("✅ 登录成功，Cookie 已保存")
                try:
                    if not self.interruptible_playwright_goto(page, "https://www.kuaishou.com/", timeout=60000):
                        return False
                except PlaywrightError:
                    pass
                return True
        return self.is_running

    def _open_login_entry(self, page) -> None:
        """提供 `_open_login_entry` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        selectors = (
            ".login-btn",
            "text=登录",
            "[class*='login']",
            "button:has-text('登录')",
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    locator.click()
                    self.interruptible_page_wait(page, 1200)
                    if self._has_login_qr(page):
                        self.log("📱 已自动打开快手扫码登录弹窗")
                    return
            except PlaywrightError:
                continue
        self.log("📱 未能自动弹出登录框，请直接在当前快手页面手动登录")

    def _has_login_qr(self, page) -> bool:
        """提供 `_has_login_qr` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        qr_selectors = (
            "canvas",
            "img[alt*='二维码']",
            "img[class*='qr']",
            "[class*='qrcode'] img",
            "[class*='qrcode'] canvas",
            "[class*='scan'] canvas",
        )
        for selector in qr_selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    return True
            except PlaywrightError:
                continue
        return False

    def _locator_visible(self, locator) -> bool:
        """提供 `_locator_visible` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        try:
            return bool(locator.is_visible())
        except (PlaywrightError, AttributeError, TypeError, ValueError):
            return False

    def _has_video_list(self, page, *, timeout: int = 15000) -> bool:
        """提供 `_has_video_list` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        try:
            page.wait_for_selector(".photo-card, .video-card", timeout=timeout)
            return True
        except PlaywrightError:
            return False

    def _search_user_via_site(self, page, context, keyword: str):
        """提供 `_search_user_via_site` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        if not self._goto_with_retry(page, "https://www.kuaishou.com/", description="打开快手搜索页"):
            return None

        input_selectors = (
            "input[type='search']",
            "input[placeholder*='搜索']",
            "input[placeholder*='快手号']",
            "input[placeholder*='作者']",
        )
        search_input = None
        for selector in input_selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    search_input = locator
                    break
            except PlaywrightError:
                continue

        if search_input is None:
            self.log("❌ 未找到快手搜索框")
            return None

        try:
            search_input.click()
            search_input.fill(keyword)
            search_input.press("Enter")
            self.interruptible_page_wait(page, 2500)
        except PlaywrightError:
            self.log("❌ 无法执行快手站内搜索")
            return None

        return self._open_profile_from_search_results(page, context, keyword)

    def _search_keyword_via_site(self, page, keyword: str):
        """提供 `_search_keyword_via_site` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        if not self._goto_with_retry(page, "https://www.kuaishou.com/", description="打开快手搜索页"):
            return None

        input_selectors = (
            "input[type='search']",
            "input[placeholder*='搜索']",
            "input[placeholder*='快手号']",
            "input[placeholder*='作者']",
        )
        for selector in input_selectors:
            try:
                locator = page.locator(selector).first
                if not self._locator_visible(locator):
                    continue
                locator.click()
                locator.fill(keyword)
                locator.press("Enter")
                self.interruptible_page_wait(page, 2500)
                if self._has_video_list(page, timeout=5000):
                    self.log(f"✅ 已进入搜索结果视频列表: {keyword}")
                    return page
            except PlaywrightError:
                continue
        self.log("❌ 无法执行快手关键词搜索")
        return None

    def _switch_search_to_user_tab(self, page) -> None:
        """提供 `_switch_search_to_user_tab` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        selectors = (
            "text=用户",
            "text=账号",
            "[role='tab']:has-text('用户')",
            "[role='tab']:has-text('账号')",
            "[class*='tab']:has-text('用户')",
            "[class*='tab']:has-text('账号')",
        )
        for selector in selectors:
            try:
                tab = page.locator(selector).first
                if self._locator_visible(tab):
                    tab.click()
                    self.interruptible_page_wait(page, 1500)
                    return
            except PlaywrightError:
                continue

    def _normalize_kuaishou_url(self, href: str) -> str:
        """提供 `_normalize_kuaishou_url` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urllib.parse.urljoin("https://www.kuaishou.com/", href)

    def _profile_url_from_locator(self, locator) -> str | None:
        """提供 `_profile_url_from_locator` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        for target in (locator, getattr(locator, "locator", lambda *_: None)("xpath=ancestor-or-self::a[1]")):
            if target is None:
                continue
            try:
                href = target.get_attribute("href")
            except (AttributeError, PlaywrightError):
                href = None
            if href and "/profile/" in href:
                return self._normalize_kuaishou_url(href)
        return None

    def _open_profile_from_search_results(self, page, context, keyword: str):
        """提供 `_open_profile_from_search_results` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        self._switch_search_to_user_tab(page)
        name_selectors = (
            ".name-wrap .name",
            ".name-wrap [class*='name']",
            ".info .name",
            ".detail-user-name",
            ".user-card .name",
            ".card-item [class*='name']",
        )
        for selector in name_selectors:
            try:
                name_link = page.locator(selector).first
                if not self._locator_visible(name_link):
                    continue
                self.log(f"👉 点击搜索结果名字进入主页: {keyword}")
                name_link.click()
                self.interruptible_page_wait(page, 3000)
                if len(context.pages) > 1:
                    page = context.pages[-1]
                    page.bring_to_front()
                if self._has_video_list(page, timeout=5000):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return page
            except PlaywrightError:
                continue

        avatar_selectors = (
            "a[href*='/profile/'] img",
            ".card-item img",
            "[class*='avatar'] img",
            "[class*='user'] img",
        )
        for selector in avatar_selectors:
            try:
                avatar = page.locator(selector).first
                if not self._locator_visible(avatar):
                    continue
                self.log(f"👉 点击搜索结果头像进入主页: {keyword}")
                avatar.click()
                self.interruptible_page_wait(page, 3000)
                if len(context.pages) > 1:
                    page = context.pages[-1]
                    page.bring_to_front()
                if self._has_video_list(page, timeout=5000):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return page
            except PlaywrightError:
                continue

        link_selectors = (
            ".card-item .detail-user-name",
            "a[href*='/profile/']",
            "[class*='user-name']",
            "[class*='author'] a",
        )
        for selector in link_selectors:
            try:
                user_link = page.locator(selector).first
                if not self._locator_visible(user_link):
                    continue
                try:
                    name = user_link.inner_text().strip()
                except PlaywrightError:
                    name = keyword
                self.log(f"👉 点击用户卡片进入主页: {name or keyword}")
                user_link.click()
                self.interruptible_page_wait(page, 2000)
                return self._open_profile_from_search_results(page, context, keyword)
            except PlaywrightError:
                continue
        self.log("❌ 未找到匹配的快手账号主页")
        return None

    def _resolve_active_page(self, page, context):
        """提供 `_resolve_active_page` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        try:
            if page and not page.is_closed():
                return page
        except PlaywrightError:
            pass
        for candidate in reversed(list(getattr(context, "pages", []) or [])):
            try:
                if candidate and not candidate.is_closed():
                    candidate.bring_to_front()
                    return candidate
            except PlaywrightError:
                continue
        return None

    def _navigate_to_target_page(self, page, context):
        """提供 `_navigate_to_target_page` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if self._is_kuaishou_url(self.keyword):
            target_url = self.keyword.strip().strip("`")
            if not self._goto_with_retry(page, target_url, description="打开快手目标页"):
                return None
            return page

        if self.keyword.isdigit():
            self.log("ℹ️ 当前输入为纯数字，按快手号优先进入用户搜索结果")
            return self._search_user_via_site(page, context, self.keyword)
        return self._search_keyword_via_site(page, self.keyword)

    def _extract_detail_title(self, page) -> str:
        """从单条详情页提取作品标题。"""
        selectors = (
            "[class*='caption']",
            "[class*='title']",
            "meta[property='og:title']",
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if not self._locator_visible(locator):
                    continue
                title = locator.inner_text().strip()
                if title:
                    return title
            except PlaywrightError:
                try:
                    content = page.locator(selector).first.get_attribute("content")
                except PlaywrightError:
                    content = None
                if content:
                    return content.strip()
        try:
            title = page.title().strip()
        except PlaywrightError:
            title = ""
        return title or "快手分享作品"

    def _extract_detail_dom_media_url(self, page) -> str:
        """优先从详情页 DOM 中直接提取 video src。"""
        try:
            media_url = page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (!video) return '';
                    return video.currentSrc || video.src || video.querySelector('source')?.src || '';
                }"""
            )
        except PlaywrightError:
            media_url = ""
        return str(media_url or "").strip()

    def _capture_single_detail_page(self, page) -> bool:
        """处理快手分享/详情链接，直接捕获单条作品并入队。"""
        if not self._is_detail_url(getattr(page, "url", "")):
            return False

        self.log("🎯 检测到快手分享/详情链接，直接解析单条作品...")
        emitted = False
        title = self._extract_detail_title(page)

        def submit_stream(stream_url: str) -> bool:
            nonlocal emitted
            stream_url = str(stream_url or "").strip()
            if emitted or not stream_url:
                return False
            emitted = True
            trace_id = self.new_trace_id("share")
            self.debug_state(
                action="emit_share_task",
                message="快手分享链接已解析并提交到下载队列",
                status_code="KUAISHOU_SHARE_TASK_EMIT",
                context={"trace_id": trace_id},
                details={"title": title, "stream_url": stream_url, "referer": page.url},
            )
            self.emit_video(
                url=stream_url,
                title=title,
                source="kuaishou",
                meta=self.task_builder.build_download_meta(trace_id, page.url, stream_url),
            )
            self.log(f"✨ 已解析分享作品: {title[:24]}...")
            return True

        def handle_response(response):
            ctype = response.headers.get("content-type", "")
            if not (
                response.request.resource_type == "media"
                or "video/mp4" in ctype
                or "mpegurl" in ctype.lower()
                or ".m3u8" in response.url
            ):
                return
            submit_stream(response.url)

        page.on("response", handle_response)
        if submit_stream(self._extract_detail_dom_media_url(page)):
            return True

        for _ in range(2):
            if emitted or not self.is_running:
                break
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                self.interruptible_page_wait(page, 2500)
            except PlaywrightError:
                break
            try:
                page.locator("video").first.click(timeout=1500)
            except PlaywrightError:
                pass
            if submit_stream(self._extract_detail_dom_media_url(page)):
                break

        if emitted:
            return True
        self.log("❌ 未能从快手分享链接中解析出可下载视频")
        return False

    def _wait_for_video_list(self, page) -> bool:
        """提供 `_wait_for_video_list` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if self._has_video_list(page, timeout=15000):
            return True
        try:
            self.log("❌ 无法加载视频列表")
        except RuntimeError:
            pass
        return False

    def _scan_video_cards(self, page) -> int:
        """滚动页面直到内容加载完成或用户主动停止。"""
        self.log("\n📜 开始滚动加载列表... (点击【停止】生成清单)")
        scroll_count = 0
        last_card_count = 0
        no_new_content_count = 0
        max_items = self._max_items_limit()
        while self.is_running:
            scroll_count += 1
            try:
                vp = page.viewport_size
                if vp:
                    page.mouse.move(vp["width"] / 2, vp["height"] / 2)
            except PlaywrightError:
                pass

            page.evaluate("window.scrollBy(0, 800)")
            self.interruptible_page_wait(page, 500)
            page.mouse.wheel(0, 500)
            self.interruptible_page_wait(page, 1000)

            cards = page.locator(".photo-card, .video-card")
            current_card_count = cards.count()
            if max_items < 9999 and current_card_count >= max_items:
                self.log(f"✅ 已达到视频数上限 {max_items}")
                last_card_count = current_card_count
                break
            no_more = False
            try:
                no_more_el = page.locator("text='没有更多了'")
                if no_more_el.count() > 0 and no_more_el.first.is_visible():
                    no_more = True
            except PlaywrightError:
                pass

            if no_more:
                self.log("✅ 已加载全部视频")
                break
            if current_card_count == last_card_count:
                no_new_content_count += 1
                if no_new_content_count >= 5:
                    self.log("🔄 似乎卡住了，尝试回滚刷新...")
                    page.evaluate("window.scrollBy(0, -1000)")
                    self.interruptible_page_wait(page, 1000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    no_new_content_count = 0
            else:
                no_new_content_count = 0
                last_card_count = current_card_count

            if scroll_count % 3 == 0:
                self.log(f"⬇️ 加载中... (已扫描 {current_card_count} 个)")
        return last_card_count

    def _extract_items_for_dialog(self, page) -> tuple[list[dict[str, int | str]], dict[int, set[str]]]:
        """提供 `_extract_items_for_dialog` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        self.log("🧠 解析视频信息...")
        video_titles = page.evaluate("""() => {
            const cards = document.querySelectorAll('.photo-card, .video-card');
            return Array.from(cards).map(c => {
                const titleEl = c.querySelector('[class*="caption"]');
                return titleEl ? titleEl.innerText : '';
            });
        }""")
        video_imgs = page.evaluate("""() => {
            const cards = document.querySelectorAll('.photo-card, .video-card');
            return Array.from(cards).map(c => {
                const imgEl = c.querySelector('img.cover-img');
                return imgEl ? imgEl.src : '';
            });
        }""")

        max_items = self._max_items_limit()
        items_for_dialog: list[dict[str, int | str]] = []
        target_fingerprints_map: dict[int, set[str]] = {}
        for idx, raw_title in enumerate(video_titles):
            if max_items < 9999 and idx >= max_items:
                break
            clean_title = raw_title.replace("\n", " ").strip() or f"未命名视频_{idx + 1}"
            items_for_dialog.append({"title": clean_title, "index": idx})
            if idx < len(video_imgs):
                target_fingerprints_map[idx] = self.parser.extract_all_possible_ids(video_imgs[idx])
        return items_for_dialog, target_fingerprints_map

    def _collect_selected_indices(self, items_for_dialog: list[dict[str, int | str]]):
        """提供 `_collect_selected_indices` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if not items_for_dialog:
            self.log("❌ 未扫描到有效视频")
            return None
        self.log(f"🔔 扫描完成，共 {len(items_for_dialog)} 个，请选择下载...")
        selected_indices = self.ask_user_selection(items_for_dialog)
        if not selected_indices:
            self.log("❌ 用户取消了下载任务")
            return None
        self.debug_state(
            action="selection_confirmed",
            message="快手任务选择已确认",
            status_code="KUAISHOU_SELECTION_OK",
            details={"total_items": len(items_for_dialog), "selected_count": len(selected_indices)},
        )
        return selected_indices

    def _capture_scroll_budget(self, items_for_dialog: list[dict[str, int | str]]) -> int:
        """提供 `_capture_scroll_budget` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        if not items_for_dialog:
            return 0
        base_count = len(items_for_dialog)
        return max(base_count, base_count * 2)

    def _run_capture_pipeline(self, page, items_for_dialog: list[dict[str, int | str]], target_fingerprints_map: dict[int, set[str]]) -> None:
        """提供 `_run_capture_pipeline` 对应的内部辅助逻辑，供 `KuaishouSpider` 使用。"""
        page = self._resolve_active_page(page, getattr(page, "context", None) or None) or page
        target_indices_set = set(self._selected_indices)
        submitted_indices: set[int] = set()
        current_focus_index = 0
        total_scrolls = self._capture_scroll_budget(items_for_dialog)

        def handle_response(response):
            
            if not self.is_running:
                return
            ctype = response.headers.get("content-type", "")
            if not (
                response.request.resource_type == "media"
                or "video/mp4" in ctype
                or "mpegurl" in ctype.lower()
                or ".m3u8" in response.url
            ):
                return
            try:
                if ".mp4" in response.url:
                    try:
                        if int(response.headers.get("content-length", 0)) < 5000:
                            return
                    except (TypeError, ValueError):
                        pass
                url = response.url
                vid_ids = self.parser.extract_all_possible_ids(url)
                matched_idx = -1
                with self._lock:
                    if vid_ids:
                        for idx in target_indices_set:
                            if idx in submitted_indices:
                                continue
                            cover_ids = target_fingerprints_map.get(idx, set())
                            if not cover_ids.isdisjoint(vid_ids):
                                matched_idx = idx
                                break
                    if matched_idx == -1 and current_focus_index in target_indices_set and current_focus_index not in submitted_indices:
                        matched_idx = current_focus_index
                        self.log(f"   🎯 [焦点匹配] {items_for_dialog[matched_idx]['title'][:10]}...")
                    elif matched_idx == -1 and "pkey" in url:
                        if current_focus_index in target_indices_set and current_focus_index not in submitted_indices:
                            matched_idx = current_focus_index
                            self.log(f"   🔒 [加密流] 匹配焦点: {items_for_dialog[matched_idx]['title'][:10]}...")
                    if matched_idx != -1:
                        submitted_indices.add(matched_idx)
                        title = str(items_for_dialog[matched_idx]["title"])
                        is_m3u8 = ".m3u8" in url
                        trace_id = self.new_trace_id("stream")
                        self.log(f"   ✨ [捕获] {title[:15]}... -> 加入下载队列")
                        self.debug_state(
                            action="emit_download_task",
                            message="快手视频流已捕获并提交到下载队列",
                            status_code="KUAISHOU_TASK_EMIT",
                            context={"trace_id": trace_id, "target_index": matched_idx},
                            details={
                                "title": title,
                                "stream_url": url,
                                "download_strategy": "m3u8" if is_m3u8 else "http",
                                "referer": page.url,
                            },
                        )
                        self.emit_video(
                            url=url,
                            title=title,
                            source="kuaishou",
                            meta=self.task_builder.build_download_meta(trace_id, page.url, url),
                        )
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
                pass

        context = page.context
        page.on("response", handle_response)
        page = self._resolve_active_page(page, context)
        if not page:
            self.log("❌ 详情页已关闭，无法启动捕获流水线")
            return
        page.evaluate("window.scrollTo(0, 0)")
        self.interruptible_page_wait(page, 1000)
        cards = page.locator(".photo-card, .video-card")
        try:
            first_card = cards.first
            if not first_card.is_visible():
                first_card.scroll_into_view_if_needed()
            first_card.click()
            self.interruptible_page_wait(page, 3000)
            try:
                page.mouse.click(200, 200)
            except PlaywrightError:
                pass
        except PlaywrightError:
            self.log("❌ 无法进入详情页")
            return

        self.log(f"🔄 生产者工作开始 (0 - {total_scrolls})...")
        while current_focus_index < total_scrolls and self.is_running:
            page = self._resolve_active_page(page, context)
            if not page:
                self.log("⚠️ 详情页已关闭，提前结束当前捕获流程")
                break
            with self._lock:
                if len(submitted_indices) >= len(target_indices_set):
                    self.log("🎉 所有任务已实时捕获，提前结束！")
                    break
            if (current_focus_index + 1) % 5 == 0:
                self.log(f"🔄 刷屏进度: {current_focus_index + 1}/{total_scrolls}")
            page.keyboard.press("ArrowDown")
            with self._lock:
                current_focus_index += 1
            wait_ms = random.randint(1500, 2500) if current_focus_index in target_indices_set else random.randint(600, 1000)
            page.wait_for_timeout(wait_ms)
            try:
                if page.locator(".close-icon").is_visible():
                    page.locator(".close-icon").click()
            except PlaywrightError:
                pass

        self.log(f"\n📊 流程结束。")
        self.debug_state(
            action="capture_pipeline_finish",
            message="快手流捕获流水线结束",
            status_code="KUAISHOU_CAPTURE_DONE",
            details={
                "scroll_budget": total_scrolls,
                "selected_count": len(target_indices_set),
                "submitted_count": len(submitted_indices),
                "not_found_count": len(target_indices_set - submitted_indices),
            },
        )
        not_found = target_indices_set - submitted_indices
        if not_found:
            self.log(f"⚠️ {len(not_found)} 个视频未捕获:")
            for idx in sorted(list(not_found)):
                self.log(f"   - [{idx + 1}] {items_for_dialog[idx]['title'][:20]}...")
        else:
            self.log("✅ 全部任务完成！")

    def run(self):
        """执行当前对象或脚本的主流程，供 `KuaishouSpider` 使用。"""
        auth_file = cfg.get("auth", "kuaishou_cookie_file", "ks_auth.json")
        proxy_cfg = self._build_proxy_cfg()
        self.keyword = self._normalize_keyword(self.keyword)
        self.log(f"🚀 启动快手任务 | 目标: {self.keyword}")
        if self._try_direct_share_download():
            self.sig_finished.emit()
            return
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    proxy=proxy_cfg,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                self._track_playwright_browser(browser)
                context = browser.new_context(
                    # 快手浏览器上下文优先使用本平台 UA，避免复制粘贴到抖音配置导致行为漂移。
                    user_agent=cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
                    viewport={"width": 1280, "height": 800},
                )
                self._load_saved_cookies(context, auth_file)
                page = context.new_page()
                entry_url = self.keyword if self._is_kuaishou_url(self.keyword) and not self._is_detail_url(self.keyword) else None
                if not self._ensure_login(page, context, auth_file, entry_url=entry_url):
                    return

                page = self._navigate_to_target_page(page, context)
                if not page:
                    return
                if self._capture_single_detail_page(page):
                    self._close_tracked_playwright_browser(browser)
                    return
                if not self._wait_for_video_list(page):
                    return

                last_card_count = self._scan_video_cards(page)
                if not self.revive_for_partial_selection(last_card_count, "个候选作品"):
                    self._close_tracked_playwright_browser(browser)
                    return

                items_for_dialog, target_fingerprints_map = self._extract_items_for_dialog(page)
                selected_indices = self._collect_selected_indices(items_for_dialog)
                if not selected_indices:
                    return
                self.is_running = True
                self._selected_indices = selected_indices
                self.log(f"✅ 选中 {len(selected_indices)} 个任务，流水线启动...")
                self._run_capture_pipeline(page, items_for_dialog, target_fingerprints_map)
                self._close_tracked_playwright_browser(browser)
        except (PlaywrightError, OSError, ValueError, RuntimeError) as e:
            self.log(f"💥 爬虫错误: {e}")
        finally:
            browser = self._tracked_playwright_browser()
            if browser is not None:
                try:
                    self._close_tracked_playwright_browser(browser)
                except PlaywrightError:
                    pass
            self._clear_playwright_browser(browser)
            self.sig_finished.emit()
