"""快手浏览器扫描与实时媒体流捕获。"""

import random
import threading
import urllib.parse

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg, get_setting_default
from app.spiders.base import BaseSpider
from app.spiders.kuaishou.auth_runtime import KuaishouAuthRuntimeMixin
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.share_runtime import KuaishouShareRuntimeMixin
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.services.auth_service import AuthService
from app.utils.user_agents import resolve_user_agent


class KuaishouSpider(
    KuaishouAuthRuntimeMixin,
    KuaishouShareRuntimeMixin,
    BaseSpider,
):
    """快手爬虫，负责页面滚动扫描、任务选择和流监听。"""

    LIST_READY_TIMEOUT_MS = 30000
    PROFILE_SESSION_URL = "https://www.kuaishou.com/rest/v/profile/get"
    PROFILE_SESSION_TIMEOUT_MS = 8000
    MANUAL_LOGIN_TIMEOUT_MS = 120_000
    SHORT_LINK_CONNECT_TIMEOUT_SECONDS = 5.0
    SHORT_LINK_READ_TIMEOUT_SECONDS = 12.0
    SHORT_LINK_TOTAL_TIMEOUT_SECONDS = 15.0
    SHORT_LINK_MAX_REDIRECTS = 5
    SHARE_DETAIL_HTML_MAX_BYTES = 2 * 1024 * 1024
    DETAIL_STREAM_WAIT_MS = 8000
    DETAIL_STREAM_POLL_MS = 100
    SEARCH_POPUP_NAVIGATION_TIMEOUT_MS = 3000
    NAVIGATION_ATTEMPTS = 3
    NETWORK_ERROR_MARKERS = (
        "网络异常，稍后重试",
        "网络异常",
        "请检查网络",
    )
    LOGIN_PROMPT_SELECTORS = (
        ".sidebar-login-button",
        ".login-btn",
        "button:has-text('登录')",
    )
    LONG_LIVED_AUTH_COOKIE_NAMES = frozenset(
        {
            "kuaishou.server.web_st",
            "kuaishou.server.webday7_st",
        }
    )

    def __init__(self, keyword: str, config: dict):
        """配置解析器、任务装配器、认证服务和响应匹配状态。"""
        super().__init__(keyword, config)
        self.parser = KuaishouParser()
        self.task_builder = KuaishouTaskBuilder()
        self.auth_service = AuthService()
        self.user_agent = resolve_user_agent(
            "kuaishou",
            self.config,
            configured_user_agent=cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
            default_user_agent=DEFAULT_USER_AGENT,
        )
        self._selected_indices: list[int] = []
        self._lock = threading.Lock()
        self._pending_share_response = None

    def _user_agent(self) -> str:
        return str(getattr(self, "user_agent", "") or DEFAULT_USER_AGENT)

    def _max_items_limit(self) -> int:
        """读取资源数量上限，并对非法配置回退默认值。"""
        default_limit = get_setting_default("kuaishou", "max_items")
        limit = self.config.get("max_items", cfg.get("kuaishou", "max_items", default_limit))
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return int(default_limit)

    def _navigation_error_reason(self, page) -> str | None:
        """识别 Playwright 错误页和快手“网络异常”占位页。"""
        try:
            current_url = str(getattr(page, "url", "") or "").strip()
        except PlaywrightError:
            return "page_unavailable"
        if not current_url or current_url == "about:blank":
            return "blank_page"
        try:
            current_scheme = urllib.parse.urlsplit(current_url).scheme.lower()
        except ValueError:
            return "invalid_page_url"
        if current_scheme == "chrome-error":
            return "browser_network_error"
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
        except (PlaywrightError, AttributeError, TypeError, ValueError):
            return None
        if any(marker in str(body_text or "") for marker in self.NETWORK_ERROR_MARKERS):
            return "site_network_error"
        return None

    def _retry_network_error_in_place(self, page) -> bool:
        """优先点击快手错误页自己的刷新按钮，避免重复 goto 破坏 SPA 内部导航。"""
        for selector in ("button:has-text('刷新')", "[role='button']:has-text('刷新')"):
            try:
                refresh = page.locator(selector).first
                if not self._locator_visible(refresh):
                    continue
                refresh.click(timeout=2000)
                if not self.interruptible_page_wait(page, 2500):
                    return False
                return self._navigation_error_reason(page) is None
            except PlaywrightError:
                continue
        return False

    def _goto_with_retry(
        self,
        page,
        url: str,
        *,
        description: str,
        attempts: int = NAVIGATION_ATTEMPTS,
    ) -> bool:
        """重试导航，并把已渲染的站点网络错误页也视为失败。"""
        target_url = url.strip().strip("`")
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=self._configured_timeout_ms(default=60),
                    wait_until="domcontentloaded",
                ):
                    return False
                if not self.interruptible_page_wait(page, 1500):
                    return False
                error_reason = self._navigation_error_reason(page)
                if error_reason is None:
                    return True
                last_error = PlaywrightError(error_reason)
                self.log(
                    f"⚠️ {description}第 {attempt}/{attempts} 次加载返回网络错误页"
                )
                if attempt < attempts and self._retry_network_error_in_place(page):
                    return True
            except PlaywrightError as exc:
                last_error = exc
                self.log(f"⚠️ {description}失败，第 {attempt}/{attempts} 次重试: {exc}")
            if attempt < attempts and not self.interruptible_page_wait(page, min(1000 * attempt, 2500)):
                return False
        if last_error:
            self.log(f"❌ {description}失败: {last_error}")
        return False

    def _search_user_via_site(self, page, context, keyword: str):
        """通过站内搜索定位用户，并打开其主页。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        homepage = "https://www.kuaishou.com/"
        if not self._page_matches_target(page, homepage) and not self._goto_with_retry(
            page, homepage, description="打开快手搜索页"
        ):
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
        """通过站内搜索打开关键词结果页。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        homepage = "https://www.kuaishou.com/"
        if not self._page_matches_target(page, homepage) and not self._goto_with_retry(
            page, homepage, description="打开快手搜索页"
        ):
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
                if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
                    self.log(f"✅ 已进入搜索结果视频列表: {keyword}")
                    return page
            except PlaywrightError:
                continue
        self.log("❌ 无法执行快手关键词搜索")
        return None

    def _switch_search_to_user_tab(self, page) -> None:
        """把搜索结果切换到用户或账号标签页。"""
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
        """把快手相对链接补全为绝对 URL。"""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urllib.parse.urljoin("https://www.kuaishou.com/", href)

    @staticmethod
    def _canonical_navigation_target(url: str):
        """生成可比较的导航目标，忽略查询顺序、片段和无意义尾斜杠。"""
        try:
            parts = urllib.parse.urlsplit(str(url or "").strip())
            host = str(parts.hostname or "").lower().rstrip(".")
            if parts.scheme.lower() not in {"http", "https"} or not host:
                return None
            port = parts.port
        except (TypeError, ValueError):
            return None
        default_port = 443 if parts.scheme.lower() == "https" else 80
        authority = host if port in {None, default_port} else f"{host}:{port}"
        path = parts.path.rstrip("/") or "/"
        query = tuple(sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)))
        return parts.scheme.lower(), authority, path, query

    def _page_matches_target(self, page, target_url: str) -> bool:
        """判断当前存活页面是否已经位于目标 URL。"""
        try:
            current_url = str(getattr(page, "url", "") or "")
        except (AttributeError, PlaywrightError):
            return False
        current = self._canonical_navigation_target(current_url)
        target = self._canonical_navigation_target(target_url)
        return current is not None and current == target

    def _profile_url_from_locator(self, locator) -> str | None:
        """从搜索结果节点或其最近链接祖先提取用户主页 URL。"""
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

    @staticmethod
    def _page_has_navigable_url(candidate) -> bool:
        """排除已关闭、空白和浏览器错误页。"""
        try:
            if not candidate or candidate.is_closed():
                return False
            current_url = str(getattr(candidate, "url", "") or "").strip()
            return bool(
                current_url
                and current_url != "about:blank"
                and urllib.parse.urlsplit(current_url).scheme.lower()
                != "chrome-error"
            )
        except (PlaywrightError, AttributeError, TypeError, ValueError):
            return False

    def _page_after_search_click(
        self,
        page,
        context,
        before_pages,
        before_url: str,
    ):
        """优先选择点击后新增的可用页，忽略空白 popup。"""
        saw_new_page = False
        for candidate in reversed(list(getattr(context, "pages", []) or [])):
            if any(candidate is known for known in before_pages):
                continue
            saw_new_page = True
            if not self._page_has_navigable_url(candidate):
                try:
                    candidate.wait_for_url(
                        lambda _current: self._page_has_navigable_url(candidate),
                        timeout=self.SEARCH_POPUP_NAVIGATION_TIMEOUT_MS,
                    )
                except (PlaywrightError, AttributeError):
                    pass
            if not self._page_has_navigable_url(candidate):
                continue
            try:
                candidate.bring_to_front()
            except PlaywrightError:
                pass
            return candidate, True
        current_url = str(getattr(page, "url", "") or "").strip()
        if (
            self._page_has_navigable_url(page)
            and current_url
            and current_url != before_url
        ):
            return page, True
        return None, saw_new_page

    def _open_profile_from_search_results(self, page, context, keyword: str):
        """在用户搜索结果中匹配关键词并打开对应主页。"""
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
                before_pages = list(getattr(context, "pages", []) or [])
                before_url = str(getattr(page, "url", "") or "").strip()
                name_link.click()
                self.interruptible_page_wait(page, 3000)
                active_page, navigation_started = self._page_after_search_click(
                    page,
                    context,
                    before_pages,
                    before_url,
                )
                if active_page is not None and self._has_video_list(
                    active_page,
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return active_page
                if navigation_started:
                    return None
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
                before_pages = list(getattr(context, "pages", []) or [])
                before_url = str(getattr(page, "url", "") or "").strip()
                avatar.click()
                self.interruptible_page_wait(page, 3000)
                active_page, navigation_started = self._page_after_search_click(
                    page,
                    context,
                    before_pages,
                    before_url,
                )
                if active_page is not None and self._has_video_list(
                    active_page,
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return active_page
                if navigation_started:
                    return None
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
                before_pages = list(getattr(context, "pages", []) or [])
                before_url = str(getattr(page, "url", "") or "").strip()
                user_link.click()
                self.interruptible_page_wait(page, 2000)
                active_page, navigation_started = self._page_after_search_click(
                    page,
                    context,
                    before_pages,
                    before_url,
                )
                if active_page is not None and self._has_video_list(
                    active_page,
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    self.log(f"👉 已从搜索结果进入主页: {name or keyword}")
                    return active_page
                if navigation_started:
                    return None
            except PlaywrightError:
                continue
        self.log("❌ 未找到匹配的快手账号主页")
        return None

    def _resolve_active_page(self, page, context):
        """点击可能新开标签页时，解析当前仍存活的活动页面。"""
        def usable(candidate, *, allow_blank: bool = False) -> bool:
            try:
                if not candidate or candidate.is_closed():
                    return False
                if allow_blank:
                    return True
                current_url = str(getattr(candidate, "url", "") or "").strip()
                return bool(
                    current_url
                    and current_url != "about:blank"
                    and urllib.parse.urlsplit(current_url).scheme.lower() != "chrome-error"
                )
            except (PlaywrightError, AttributeError, TypeError, ValueError):
                return False

        try:
            if usable(page):
                return page
        except PlaywrightError:
            pass
        for candidate in reversed(list(getattr(context, "pages", []) or [])):
            try:
                if usable(candidate):
                    candidate.bring_to_front()
                    return candidate
            except PlaywrightError:
                continue
        # 页面尚未开始导航时仍返回原对象，调用方可在同一标签页继续 goto。
        if usable(page, allow_blank=True):
            return page
        return None

    def _navigate_to_target_page(self, page, context):
        """按 URL、快手号或关键词把浏览器导航到目标内容页。"""
        if self._is_kuaishou_url(self.keyword):
            target_url = self.keyword.strip().strip("`")
            if not self._page_matches_target(page, target_url) and not self._goto_with_retry(
                page, target_url, description="打开快手目标页"
            ):
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

    def _capture_single_detail_page(self, page, initial_stream_urls=()) -> bool:
        """从已打开的详情页捕获单条作品；初次导航响应可由调用方提前传入。"""
        if not self._is_detail_url(getattr(page, "url", "")):
            return False

        self.log("🌐 正在从快手分享详情页捕获单条作品...")
        emitted = False
        stream_ready = threading.Event()
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
                meta=self.task_builder.build_download_meta(trace_id, page.url, stream_url, self._user_agent()),
            )
            self.log(f"✨ 已解析分享作品: {title[:24]}...")
            stream_ready.set()
            return True

        def handle_response(response):
            submit_stream(self._share_media_response_url(response))

        page.on("response", handle_response)
        try:
            for stream_url in initial_stream_urls:
                if submit_stream(stream_url):
                    return True
            if submit_stream(self._extract_detail_dom_media_url(page)):
                return True

            # 有些详情页必须触发一次播放后才发起媒体请求。响应监听器已提前
            # 注册，因此只需短时间泵送 Playwright 事件，无需刷新整个页面。
            try:
                page.locator("video").first.click(timeout=1500)
            except PlaywrightError:
                pass
            self._wait_for_detail_stream(page, stream_ready)
            if emitted or submit_stream(self._extract_detail_dom_media_url(page)):
                return True

            self.log("❌ 未能从快手分享链接中解析出可下载视频")
            return False
        finally:
            try:
                page.remove_listener("response", handle_response)
            except (AttributeError, PlaywrightError):
                pass

    def _wait_for_detail_stream(self, page, stream_ready: threading.Event) -> bool:
        """以短时间片泵送页面事件，媒体响应到达后立即结束等待。"""
        remaining_ms = self.DETAIL_STREAM_WAIT_MS
        while remaining_ms > 0 and self.is_running and not stream_ready.is_set():
            slice_ms = min(self.DETAIL_STREAM_POLL_MS, remaining_ms)
            if not self.interruptible_page_wait(
                page,
                slice_ms,
                step_ms=slice_ms,
            ):
                break
            remaining_ms -= slice_ms
        return stream_ready.is_set()

    def _wait_for_video_list(self, page) -> bool:
        """等待视频列表并记录无法加载的终止状态。"""
        if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
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
        """提取选择项，并建立卡片索引到媒体指纹的映射。"""
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
        """展示候选列表并返回用户确认的卡片索引。"""
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
        """为详情页切换预留足够滚动次数，兼容焦点与卡片索引偏移。"""
        if not items_for_dialog:
            return 0
        base_count = len(items_for_dialog)
        return max(base_count, base_count * 2)

    def _run_capture_pipeline(self, page, items_for_dialog: list[dict[str, int | str]], target_fingerprints_map: dict[int, set[str]]) -> None:
        """滚动详情流，并把网络响应匹配到用户选择的卡片。"""
        page = self._resolve_active_page(page, getattr(page, "context", None) or None) or page
        target_indices_set = set(self._selected_indices)
        submitted_indices: set[int] = set()
        current_focus_index = 0
        total_scrolls = self._capture_scroll_budget(items_for_dialog)

        def handle_response(response):
            # 网络回调会与焦点滚动交错；锁内先认领索引，才能避免同一媒体响应重复入队。
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
                            meta=self.task_builder.build_download_meta(trace_id, page.url, url, self._user_agent()),
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
            if not self.interruptible_page_wait(page, wait_ms):
                break
            try:
                if page.locator(".close-icon").is_visible():
                    page.locator(".close-icon").click()
            except PlaywrightError:
                pass

        self.log("\n📊 流程结束。")
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

    def _entry_url_for_login(self) -> str | None:
        return self.keyword if self._is_kuaishou_url(self.keyword) and not self._is_detail_url(self.keyword) else None

    def _run_login_window_session(self, playwright, auth_file: str, entry_url: str | None) -> bool:
        self.log("🔓 正在打开快手登录窗口...")
        headless = self._browser_headless(login_window=True)
        target_url = entry_url or "https://www.kuaishou.com/"
        self._public_domain_policy_engine().require_public_url(target_url)
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                headless=headless,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        previous_request_api = getattr(self, "_profile_request_api", None)
        self._profile_request_api = playwright.request
        try:
            context = self._create_browser_context(
                browser, auth_file, headless=headless
            )
            page = context.new_page()
            return self._ensure_login(page, context, auth_file, entry_url=entry_url, allow_manual_login=True)
        finally:
            self._close_tracked_playwright_browser(browser)
            if previous_request_api is None:
                self.__dict__.pop("_profile_request_api", None)
            else:
                self._profile_request_api = previous_request_api

    def _run_share_browser_session(self, playwright, auth_file: str) -> str:
        """用固定无头会话解析分享详情，不进入首页、登录检查或列表扫描。"""
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                # 分享链接是单资源解析入口，即使用户启用了“显示浏览器”也保持静默。
                headless=True,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        try:
            context = self._create_browser_context(browser, auth_file, headless=True)
            page = context.new_page()
            initial_stream_urls: list[str] = []

            def remember_stream(response) -> None:
                stream_url = self._share_media_response_url(response)
                if stream_url and stream_url not in initial_stream_urls:
                    initial_stream_urls.append(stream_url)

            # 监听器必须早于 goto 注册，否则首屏直接发出的媒体响应会永久错过。
            page.on("response", remember_stream)
            try:
                if not self._goto_with_retry(
                    page, self.keyword, description="静默打开快手分享详情页"
                ):
                    return "stopped" if not self.is_running else "failed"
                # 保留首屏监听器直到详情捕获完成，覆盖标题提取与二级监听器注册之间的窄窗口。
                if self._capture_single_detail_page(page, initial_stream_urls):
                    return "completed"
                if not self.is_running:
                    return "stopped"
                if self._login_prompt_visible(page):
                    return "login_required"
                return "failed"
            finally:
                try:
                    page.remove_listener("response", remember_stream)
                except (AttributeError, PlaywrightError):
                    pass
        finally:
            self._close_tracked_playwright_browser(browser)

    def _run_browser_session(
        self,
        playwright,
        auth_file: str,
        *,
        headless: bool,
        allow_manual_login: bool,
    ) -> str:
        entry_url = self._entry_url_for_login()
        target_url = entry_url or "https://www.kuaishou.com/"
        self._public_domain_policy_engine().require_public_url(target_url)
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                headless=headless,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        previous_request_api = getattr(self, "_profile_request_api", None)
        self._profile_request_api = playwright.request
        try:
            context = self._create_browser_context(
                browser, auth_file, headless=headless
            )
            page = context.new_page()
            if not self._ensure_login(
                page,
                context,
                auth_file,
                entry_url=entry_url,
                allow_manual_login=allow_manual_login,
            ):
                return "login_required" if self.is_running and not allow_manual_login else "stopped"

            page = self._navigate_to_target_page(page, context)
            if not page:
                return "stopped"
            if not self._wait_for_video_list(page):
                return "stopped"

            last_card_count = self._scan_video_cards(page)
            if not self.revive_for_partial_selection(last_card_count, "个候选作品"):
                return "stopped"

            items_for_dialog, target_fingerprints_map = self._extract_items_for_dialog(page)
            selected_indices = self._collect_selected_indices(items_for_dialog)
            if not selected_indices:
                return "stopped"
            self.is_running = True
            self._selected_indices = selected_indices
            self.log(f"✅ 选中 {len(selected_indices)} 个任务，流水线启动...")
            self._run_capture_pipeline(page, items_for_dialog, target_fingerprints_map)
            return "completed"
        finally:
            self._close_tracked_playwright_browser(browser)
            if previous_request_api is None:
                self.__dict__.pop("_profile_request_api", None)
            else:
                self._profile_request_api = previous_request_api

    def run(self):
        """按详情链接或列表任务分流，避免同一输入重复经过两套浏览器流程。"""
        auth_file = cfg.get("auth", "kuaishou_cookie_file", "ks_auth.json")
        self.keyword = self._normalize_keyword(self.keyword)
        self.log(f"🚀 启动快手任务 | 目标: {self.keyword}")
        try:
            if self._is_detail_url(self.keyword) or self._is_short_share_url(
                self.keyword
            ):
                self.log("🎯 检测到快手分享/详情链接，使用静默单资源解析流程")
                if self._try_direct_share_download():
                    return
                self.log("ℹ️ HTTP 未获得视频直链，切换无头浏览器继续解析")
                with sync_playwright() as p:
                    result = self._run_share_browser_session(p, auth_file)
                    if result == "login_required" and self.is_running:
                        login_ok = self._run_login_window_session(
                            p, auth_file, self._entry_url_for_login()
                        )
                        if login_ok and self.is_running:
                            self.log("✅ 快手登录完成，重新以静默模式执行当前任务")
                            self._run_share_browser_session(p, auth_file)
                return

            with sync_playwright() as p:
                headless = self._browser_headless()
                result = self._run_browser_session(
                    p,
                    auth_file,
                    headless=headless,
                    allow_manual_login=not headless,
                )
                # 静默会话只负责探测；需要登录时先关闭它，再用可见窗口持久化 Cookie 后重跑。
                if result == "login_required" and headless and self.is_running:
                    login_ok = self._run_login_window_session(p, auth_file, self._entry_url_for_login())
                    if login_ok and self.is_running:
                        self.log("✅ 快手登录完成，重新以静默模式执行当前任务")
                        self._run_browser_session(
                            p,
                            auth_file,
                            headless=True,
                            allow_manual_login=False,
                        )
        except (PlaywrightError, OSError, ValueError, RuntimeError) as e:
            self.log(f"💥 爬虫错误: {e}")
        finally:
            self._close_pending_share_response()
            # HTTP 分享直连会在创建 Playwright 之前返回；轻量调用方也可能没有
            # 执行 BaseSpider.__init__。未跟踪过浏览器时无需进入浏览器清理链路。
            browser = getattr(self, "_playwright_browser", None)
            if browser is not None:
                try:
                    self._close_tracked_playwright_browser(browser)
                except PlaywrightError:
                    pass
            self._emit_finished()
