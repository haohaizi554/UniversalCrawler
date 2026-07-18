"""MissAV 两遍列表扫描与 m3u8 嗅探实现。"""

import re
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT
from app.spiders.base import BaseSpider
from app.spiders.missav.challenge_session import (
    ChallengeWaitCancelled,
    ChallengeWaitTimeout,
    ExternalChromeChallengeSession,
    SystemBrowserUnavailable,
)
from app.spiders.missav.parser import MissAVParser
from app.spiders.missav.task_builder import MissAVTaskBuilder
from shared.runtime_options import DomainPolicyViolation


@dataclass
class _ChallengeBrowserRuntime:
    """记录一次 MissAV 扫描当前可用的浏览器接管对象。"""

    playwright: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    external_session: ExternalChromeChallengeSession | None = None

    def bind(
        self,
        playwright: Any,
        browser: Any,
        context: Any,
        page: Any,
    ) -> None:
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page


class MissAVSpider(BaseSpider):
    """MissAV 爬虫，先扫列表再进入详情页嗅探 m3u8。"""

    ALLOW_SYSTEM_PROXY_FALLBACK = True

    GRID_READY_TIMEOUT_MS = 30000
    PLAYER_READY_TIMEOUT_MS = 30000
    M3U8_SNIFF_SECONDS = 45
    PAGE_HOSTS = ("missav.ai",)
    URL_TRAILING_PUNCTUATION = " \t\r\n`'\"，。！？；：、,.!?;:)]}）】》>"
    CLOUDFLARE_MIN_WAIT_MS = 120000
    SYSTEM_BROWSER_CHANNELS = (("chrome", "Chrome"), ("msedge", "Edge"))
    CLOUDFLARE_UNSUPPORTED_MARKERS = (
        "浏览器不支持",
        "browser not supported",
        "browser is not supported",
        "unsupported browser",
        "update your browser",
    )
    CLOUDFLARE_PENDING_MARKERS = (
        "just a moment",
        "请稍候",
        "正在进行安全验证",
        "checking your browser",
        "security verification",
        "attention required",
    )

    def __init__(self, keyword: str, config: dict):
        """配置候选解析器和 HLS 下载任务装配器。"""
        super().__init__(keyword, config)
        self.parser = MissAVParser()
        self.task_builder = MissAVTaskBuilder()

    def _require_missav_page_url(self, url: str) -> str:
        """拒绝指向 MissAV 站点之外的用户浏览器入口。"""
        if not self._url_matches_hosts(url, self.PAGE_HOSTS):
            raise DomainPolicyViolation("MissAV 页面链接不属于受支持的平台域名")
        return self._public_domain_policy_engine().require_public_url(url)

    def _launch_challenge_browser(self, playwright, *, headless: bool):
        """人工验证优先使用系统稳定版浏览器，缺失时再退回随包内核。"""
        launch_kwargs = self._playwright_launch_kwargs(
            headless=headless,
            proxy=(getattr(self, "config", {}) or {}).get("proxy"),
            args=["--disable-blink-features=AutomationControlled"],
        )
        if not headless:
            for channel, label in self.SYSTEM_BROWSER_CHANNELS:
                try:
                    browser = playwright.chromium.launch(**launch_kwargs, channel=channel)
                except PlaywrightError:
                    continue
                self.log(f"🌐 MissAV 人工验证使用系统 {label} {browser.version}")
                return browser

        browser = playwright.chromium.launch(**launch_kwargs)
        if not headless:
            self.log(
                f"⚠️ 未找到可用的系统 Chrome/Edge，改用内置浏览器 {browser.version}；"
                "Cloudflare 可能拒绝过旧内核"
            )
        return browser

    def _create_challenge_context(self, browser):
        """保留浏览器原生 UA/Web API，避免挑战看到互相矛盾的伪装指纹。"""
        context_kwargs = self._playwright_context_kwargs(
            user_agent="",
            referer="https://missav.ai/",
            viewport={"width": 1280, "height": 800},
        )
        # 通用构造器会生成轮换 UA；MissAV 的 Cloudflare 挑战要求它与真实内核一致。
        context_kwargs.pop("user_agent", None)
        # 不注入全局 stealth.js：其中 Canvas/WebGL 改写会让挑战环境失去官方支持。
        return browser.new_context(**context_kwargs)

    def _wait_for_external_challenge(
        self,
        session: ExternalChromeChallengeSession,
        target_url: str,
        *,
        timeout_ms: int,
    ) -> bool:
        """在不连接 CDP 的前提下等待系统浏览器离开挑战页。"""

        def report_challenge(_title: str) -> None:
            self.log("🛡️ 检测到 Cloudflare，请在浏览器中完成人工验证...")

        try:
            session.wait_for_ready_page(
                target_url,
                timeout_seconds=max(
                    self.CLOUDFLARE_MIN_WAIT_MS,
                    int(timeout_ms or 0),
                )
                / 1000,
                cancelled=lambda: not self.is_running or self.interrupt_requested,
                on_challenge=report_challenge,
            )
        except ChallengeWaitCancelled:
            return False
        except ChallengeWaitTimeout as exc:
            self.log(f"❌ Cloudflare 验证等待超时: {exc}")
            return False
        self.log("✅ Cloudflare 验证已通过")
        return True

    def _attach_external_browser(
        self,
        runtime: _ChallengeBrowserRuntime,
        target_url: str,
    ) -> bool:
        """挑战结束后才启动 Playwright，并接管目标标签页。"""
        session = runtime.external_session
        if session is None:
            return False
        playwright = sync_playwright().start()
        self._track_playwright_instance(playwright)
        try:
            attachment = session.attach(playwright, target_url)
        except Exception:
            self._stop_tracked_playwright_instance(playwright)
            raise
        runtime.bind(
            playwright,
            attachment.browser,
            attachment.context,
            attachment.page,
        )
        self._track_playwright_browser(attachment.browser)
        self.log(f"🌐 MissAV 已接管系统浏览器 {attachment.browser.version}")
        return True

    def _disconnect_external_browser(
        self,
        runtime: _ChallengeBrowserRuntime,
    ) -> None:
        """仅断开 Playwright/CDP，保留系统 Chrome 进程和用户目录。"""
        playwright = runtime.playwright
        browser = runtime.browser
        runtime.bind(None, None, None, None)
        if browser is not None:
            self._clear_playwright_browser(browser)
        if playwright is not None:
            self._stop_tracked_playwright_instance(playwright)

    def _navigate_external_challenge(
        self,
        runtime: _ChallengeBrowserRuntime,
        target_url: str,
        *,
        timeout_ms: int,
    ) -> bool:
        """断开控制后在同一浏览器资料中打开 URL，通过挑战后再接管。"""
        session = runtime.external_session
        if session is None:
            return False
        self._disconnect_external_browser(runtime)
        session.open_url(target_url)
        if not self._wait_for_external_challenge(
            session,
            target_url,
            timeout_ms=timeout_ms,
        ):
            return False
        return self._attach_external_browser(runtime, target_url)

    def _release_challenge_browser_runtime(
        self,
        runtime: _ChallengeBrowserRuntime,
    ) -> None:
        """按所有权释放直连浏览器或外部系统浏览器会话。"""
        if runtime.external_session is not None:
            self._disconnect_external_browser(runtime)
            runtime.external_session.close()
            runtime.external_session = None
            return
        browser = runtime.browser
        playwright = runtime.playwright
        runtime.bind(None, None, None, None)
        if browser is not None:
            self._close_tracked_playwright_browser(browser)
        if playwright is not None:
            self._stop_tracked_playwright_instance(playwright)

    @contextmanager
    def _challenge_browser_runtime(
        self,
        target_url: str,
        proxy_server: str | None,
    ) -> Iterator[_ChallengeBrowserRuntime]:
        """创建挑战安全的浏览器运行时，退出时统一回收资源。"""
        runtime = _ChallengeBrowserRuntime()
        browser_timeout_ms = self._configured_timeout_ms(default=60)
        try:
            if not self._browser_headless():
                try:
                    runtime.external_session = ExternalChromeChallengeSession(
                        proxy_server=proxy_server,
                    )
                except SystemBrowserUnavailable:
                    self.log("⚠️ 未找到系统 Chrome/Edge，改用 Playwright 浏览器")
                else:
                    runtime.external_session.start(target_url)
                    if self._wait_for_external_challenge(
                        runtime.external_session,
                        target_url,
                        timeout_ms=browser_timeout_ms,
                    ):
                        self._attach_external_browser(runtime, target_url)

            if runtime.external_session is None:
                playwright = sync_playwright().start()
                self._track_playwright_instance(playwright)
                browser = self._launch_challenge_browser(
                    playwright,
                    headless=self._browser_headless(),
                )
                self._track_playwright_browser(browser)
                context = self._create_challenge_context(browser)
                page = context.new_page()
                runtime.bind(playwright, browser, context, page)
                self.log("🚀 正在访问页面...")
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=browser_timeout_ms,
                ) or not self._wait_for_cloudflare_challenge(
                    page,
                    timeout_ms=browser_timeout_ms,
                ):
                    runtime.page = None

            yield runtime
        finally:
            self._release_challenge_browser_runtime(runtime)

    def _cloudflare_challenge_state(self, page) -> str:
        """区分正常页面、等待中的挑战和明确拒绝当前浏览器的页面。"""
        try:
            title = str(page.title() or "")
        except (PlaywrightError, TypeError, AttributeError):
            title = ""
        try:
            body_text = str(page.locator("body").inner_text(timeout=1000) or "")
        except (PlaywrightError, TypeError, AttributeError):
            body_text = ""
        title_text = title.lower()
        body_text = body_text.lower()
        challenge_text = f"{title_text}\n{body_text}"
        pending = any(
            marker in challenge_text for marker in self.CLOUDFLARE_PENDING_MARKERS
        )
        challenge_evidence = (
            pending
            or "cloudflare" in challenge_text
            or "ray id" in challenge_text
        )
        if challenge_evidence and any(
            marker in challenge_text
            for marker in self.CLOUDFLARE_UNSUPPORTED_MARKERS
        ):
            return "unsupported"
        if pending:
            return "pending"
        return "clear"

    def _wait_for_cloudflare_challenge(self, page, *, timeout_ms: int) -> bool:
        """可中断地等待人工/自动验证完成，并对不支持页给出明确诊断。"""
        state = self._cloudflare_challenge_state(page)
        if state == "clear":
            return True
        if state == "unsupported":
            self.log("❌ Cloudflare 不支持当前浏览器环境，请更新系统 Chrome/Edge 后重试")
            return False

        self.log("🛡️ 检测到 Cloudflare，请在浏览器中完成人工验证...")
        remaining_ms = max(self.CLOUDFLARE_MIN_WAIT_MS, int(timeout_ms or 0))
        while remaining_ms > 0:
            if not self.interruptible_sleep(1):
                return False
            remaining_ms -= 1000
            state = self._cloudflare_challenge_state(page)
            if state == "clear":
                self.log("✅ Cloudflare 验证已通过")
                return True
            if state == "unsupported":
                self.log("❌ Cloudflare 不支持当前浏览器环境，请更新系统 Chrome/Edge 后重试")
                return False
        self.log("❌ Cloudflare 验证等待超时")
        return False

    def run(self):
        """执行候选扫描、版本筛选、用户选择和详情页 HLS 嗅探。"""
        try:
            proxy_server = self._effective_proxy_server()
            if proxy_server:
                self.log(f"🌍 使用代理: {proxy_server}")
            enable_individual = self.config.get('individual_only', False)
            priority_text = self.config.get('priority', "中文字幕优先")
            priority_map = {
                "中文字幕优先": ["中文字幕", "无码流出", "英文字幕", "普通版"],
                "无码流出优先": ["无码流出", "中文字幕", "英文字幕", "普通版"]
            }
            self.priority_list = priority_map.get(priority_text, priority_map["中文字幕优先"])
            self.log(f"⚙️ 偏好设置: 单体={enable_individual}, 优先级={self.priority_list}")
            my_ua = DEFAULT_USER_AGENT
            target_url = ""
            is_single_video_mode = False
            is_search_mode = False
            raw_input = self._normalize_keyword(self.keyword)
            if raw_input != self.keyword.strip():
                self.log(f"🔗 MissAV 输入已归一化: {raw_input}")
            if "http" in raw_input:
                parsed = urllib.parse.urlparse(raw_input)
                path_parts = parsed.path.strip('/').split('/')
                keywords_list = ['search', 'actresses', 'tags', 'series', 'makers', 'directors', 'labels']
                if not any(k in parsed.path for k in keywords_list) and re.search(r'\w+-\d+', path_parts[-1]):
                    is_single_video_mode = True
                    target_url = raw_input
                    self.log("🔗 识别为单体视频链接")
                else:
                    target_url = raw_input
                    self.log("🔗 识别为列表/分类链接")
            else:
                is_search_mode = True
                encoded_kw = urllib.parse.quote(raw_input)
                target_url = f"https://missav.ai/cn/search/{encoded_kw}"
                self.log(f"🔍 构造搜索链接: {target_url}")
            if not is_single_video_mode:
                target_url = self.parser.inject_url_params(target_url, enable_individual)
                self.log(f"🔧 修正后 URL: {target_url}")
            self._require_missav_page_url(target_url)
            if not self.is_running:
                return
            with self._challenge_browser_runtime(
                target_url,
                proxy_server,
            ) as runtime:
                browser = runtime.browser
                context = runtime.context
                page = runtime.page
                if page is None:
                    return
                try:
                    try:
                        my_ua = str(page.evaluate("navigator.userAgent") or my_ua)
                    except (PlaywrightError, TypeError, AttributeError):
                        pass
                    browser_timeout_ms = self._configured_timeout_ms(default=60)
                    # 搜索页可能优先返回演员卡片，转入其主页后才能扫描完整作品列表。
                    if is_search_mode and self.is_running:
                        try:
                            self.interruptible_sleep(2)
                            links = page.query_selector_all('a[href*="/actresses/"]')
                            valid_actress_link = None
                            for link in links:
                                href = link.get_attribute("href")
                                if href and "ranking" not in href and "search" not in href:
                                    if link.is_visible():
                                        valid_actress_link = link
                                        break
                            if valid_actress_link:
                                href = valid_actress_link.get_attribute("href")
                                self.log(f"✨ 发现演员主页，自动跳转: {href}")
                                valid_actress_link.click()
                                if not self.interruptible_wait_for_load_state(
                                    page,
                                    "domcontentloaded",
                                    timeout=browser_timeout_ms,
                                ):
                                    return
                                current_url = page.url
                                new_url = self.parser.inject_url_params(current_url, enable_individual)
                                if new_url != current_url:
                                    if not self.interruptible_playwright_goto(page, new_url, timeout=browser_timeout_ms):
                                        return
                                    if not self._wait_for_cloudflare_challenge(page, timeout_ms=browser_timeout_ms):
                                        return
                        except PlaywrightError:
                            pass
                    if not self.is_running:
                        self._close_tracked_playwright_browser(browser)
                        return
                    final_tasks = []
                    if is_single_video_mode:
                        title = page.title().replace('| MissAV', '').strip()
                        final_tasks.append({'title': title, 'url': page.url})
                    else:
                        scraped_data = {}
                        verified_chinese = set()
                        base_url = page.url
                        # 第一遍收集全部候选，用户中途停止时仍可保留已经得到的部分结果。
                        self.log("📜 开始第一遍扫描 (获取所有视频)...")
                        self._scan_pages(page, scraped_data, is_chinese_pass=False)

                        if not self.is_running:
                            self.log("⏸️ 扫描被中断，跳过中文校验，准备生成清单...")
                        if not scraped_data:
                            self.log("❌ 未找到任何视频")
                            self._close_tracked_playwright_browser(browser)
                            return
                        # 第二遍只校验中文字幕；停止后跳过，避免为补充标签继续发起页面请求。
                        if self.is_running:
                            self.log("🇨🇳 开始第二遍扫描 (校验中文字幕)...")
                            chinese_url = self.parser.add_chinese_filter(base_url)

                            if chinese_url != base_url:
                                self.log(f"   跳转校验: {chinese_url}")
                                try:
                                    chinese_url_no_page = re.sub(r'[?&]page=\d+', '', chinese_url)
                                    if runtime.external_session is not None:
                                        if not self._navigate_external_challenge(
                                            runtime,
                                            chinese_url_no_page,
                                            timeout_ms=browser_timeout_ms,
                                        ):
                                            return
                                        browser = runtime.browser
                                        context = runtime.context
                                        page = runtime.page
                                    else:
                                        if not self.interruptible_playwright_goto(
                                            page,
                                            chinese_url_no_page,
                                            timeout=browser_timeout_ms,
                                        ):
                                            return
                                        if not self._wait_for_cloudflare_challenge(
                                            page,
                                            timeout_ms=browser_timeout_ms,
                                        ):
                                            return

                                    chinese_data = {}
                                    self._scan_pages(page, chinese_data, is_chinese_pass=True)
                                    verified_chinese = set(chinese_data.keys())
                                    scraped_data.update(chinese_data)
                                except PlaywrightError as e:
                                    self.log(f"   ⚠️ 中文校验异常: {e}")

                        if not self.revive_for_partial_selection(len(scraped_data), "个候选结果"):
                            self._close_tracked_playwright_browser(browser)
                            return
                        # 同番号的不同版本先分组再打分，最终只保留用户偏好最高的一项。
                        self.log(f"🧠 智能筛选中 (共 {len(scraped_data)} 个候选)...")
                        grouped = self.parser.group_candidates(scraped_data)

                        for _code, items in grouped.items():
                            sorted_items = sorted(
                                items,
                                key=lambda x: self.parser.calculate_score(x[0], x[1], verified_chinese, self.priority_list),
                                reverse=True
                            )
                            best_url, best_title = sorted_items[0]
                            final_title = self.parser.generate_display_title(best_url, best_title, verified_chinese)
                            final_tasks.append({'title': final_title, 'url': best_url})

                    if not final_tasks:
                        self.log("❌ 筛选后无有效结果")
                        self._close_tracked_playwright_browser(browser)
                        return
                    final_tasks = self._trim_final_tasks(final_tasks)
                    self.log(f"🔔 扫描完成，共 {len(final_tasks)} 个最佳版本")

                    selected_indices = self.ask_user_selection(final_tasks)
                    if not selected_indices:
                        self.log("❌ 用户取消下载")
                        self._close_tracked_playwright_browser(browser)
                        return
                    self.log(f"✅ 选中 {len(selected_indices)} 个，开始嗅探 m3u8...")

                    # 每个选择项单独进入详情页嗅探 playlist.m3u8，避免跨作品复用过期流地址。
                    success_count = 0
                    for i, idx in enumerate(selected_indices):
                        if not self.is_running:
                            break
                        task = final_tasks[idx]
                        target_page_url = task['url']
                        title = task['title']
                        self.log(f"🕵️ [{i + 1}/{len(selected_indices)}] 嗅探: {title[:15]}...")
                        m3u8_url = None
                        m3u8_headers = {}
                        m3u8_status = None
                        m3u8_ready = False
                        m3u8_playlist_cache = {}
                        # 监听器闭包只归属当前详情页，并在 finally 中移除，防止迟到响应污染下一项。
                        def handle_request(req):
                            
                            nonlocal m3u8_url, m3u8_headers
                            if "playlist.m3u8" in req.url:
                                m3u8_url = req.url
                                m3u8_headers = self._headers_from_request(req)
                        def handle_response(resp, playlist_cache=m3u8_playlist_cache):
                            nonlocal m3u8_url, m3u8_headers, m3u8_status, m3u8_ready
                            try:
                                req = resp.request
                                req_url = req.url
                            except (PlaywrightError, TypeError, AttributeError):
                                return
                            if "playlist.m3u8" not in req_url:
                                return
                            try:
                                status = int(resp.status)
                            except (TypeError, ValueError):
                                status = 0
                            m3u8_url = req_url
                            m3u8_status = status
                            m3u8_headers = self._headers_from_request(req)
                            if status in (200, 206):
                                try:
                                    playlist_text = resp.text()
                                except (PlaywrightError, UnicodeDecodeError, TypeError, ValueError):
                                    playlist_text = ""
                                if self._looks_like_hls_playlist(playlist_text):
                                    playlist_cache[req_url] = playlist_text
                                    m3u8_ready = True
                        def on_popup(popup):
                            
                            if popup != page:
                                try:
                                    popup.close()
                                except PlaywrightError:
                                    pass
                        context.on("page", on_popup)
                        page.on("request", handle_request)
                        page.on("response", handle_response)
                        try:
                            if not self.interruptible_playwright_goto(page, target_page_url, timeout=browser_timeout_ms):
                                break
                            if not self._wait_for_cloudflare_challenge(page, timeout_ms=browser_timeout_ms):
                                break
                            try:
                                self.interruptible_wait_for_selector(page, ".plyr", timeout=self.PLAYER_READY_TIMEOUT_MS)
                                if not self.is_running or self.interrupt_requested:
                                    break
                                page.mouse.click(400, 300)
                                self.interruptible_sleep(2)
                                if not m3u8_url:
                                    page.mouse.click(400, 300)
                            except PlaywrightError:
                                pass
                            for _ in range(self.M3U8_SNIFF_SECONDS):
                                if m3u8_ready or not self.is_running:
                                    break
                                self.interruptible_sleep(1)
                            if not self.is_running:
                                break
                            if m3u8_url and m3u8_ready:
                                trace_id = self.new_trace_id("m3u8")
                                download_headers = self._download_headers_for_context(
                                    context,
                                    target_page_url,
                                    my_ua,
                                    stream_url=m3u8_url,
                                    request_headers=m3u8_headers,
                                )
                                cookie_header = download_headers.get("Cookie", "")
                                browser_storage_state = {}
                                try:
                                    browser_storage_state = context.storage_state()
                                except (PlaywrightError, TypeError, AttributeError):
                                    browser_storage_state = {}
                                self.log("   ✨ 嗅探成功")
                                self.debug_state(
                                    action="emit_download_task",
                                    message="MissAV m3u8 嗅探成功并提交下载",
                                    status_code="MISSAV_TASK_EMIT",
                                    context={"trace_id": trace_id},
                                    details={
                                        "title": title,
                                        "stream_url": m3u8_url,
                                        "referer": target_page_url,
                                        "proxy": proxy_server,
                                        "has_cookie": bool(cookie_header),
                                        "m3u8_status": m3u8_status,
                                        "header_names": sorted(download_headers),
                                    },
                                )
                                self.emit_video(
                                    url=m3u8_url,
                                    title=title,
                                    source="missav",
                                    meta=self.task_builder.build_video_meta(
                                        trace_id,
                                        target_page_url,
                                        my_ua,
                                        proxy_server,
                                        headers=download_headers,
                                        cookie=cookie_header,
                                        include_cookies=bool(cookie_header),
                                        use_browser_headers=True,
                                        browser_storage_state=browser_storage_state,
                                        playlist_cache=m3u8_playlist_cache,
                                    )
                                )
                                success_count += 1
                            else:
                                self.log("   ⚠️ 嗅探超时 (未找到 playlist.m3u8)")
                                self.debug_state(
                                    action="sniff_m3u8_timeout",
                                    message="MissAV 详情页嗅探超时，未发现 playlist.m3u8",
                                    status_code="MISSAV_SNIFF_TIMEOUT",
                                    details={
                                        "title": title,
                                        "target_page_url": target_page_url,
                                        "selected_index": idx,
                                        "stream_url": m3u8_url,
                                        "m3u8_status": m3u8_status,
                                        "m3u8_ready": m3u8_ready,
                                    },
                                    level="WARNING",
                                )
                        except PlaywrightError as e:
                            self.log(f"   ❌ 页面加载错误: {e}")
                            self.debug_state(
                                action="sniff_page_error",
                                message="MissAV 详情页加载失败",
                                status_code="MISSAV_PAGE_ERROR",
                                details={
                                    "title": title,
                                    "target_page_url": target_page_url,
                                    "error": str(e),
                                },
                                level="ERROR",
                            )
                        finally:
                            try:
                                page.remove_listener("request", handle_request)
                            except PlaywrightError:
                                pass
                            try:
                                page.remove_listener("response", handle_response)
                            except PlaywrightError:
                                pass
                            try:
                                context.remove_listener("page", on_popup)
                            except PlaywrightError:
                                pass
                        self.interruptible_sleep(1)
                    if self.is_running:
                        self.log(f"🎉 任务结束，成功提交: {success_count}")
                    else:
                        self.log("🛑 任务强制中止")
                finally:
                    self._release_challenge_browser_runtime(runtime)
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
            self._stop_tracked_playwright_instance()
            self._emit_finished()

    @classmethod
    def _strip_url_trailing_punctuation(cls, value: str) -> str:
        return str(value or "").strip().strip("`").rstrip(cls.URL_TRAILING_PUNCTUATION)

    @classmethod
    def _extract_first_url(cls, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        match = re.search(r"https?://[^\s`'\"<>，。！？；;,)）\]}]+", text)
        if match:
            return cls._strip_url_trailing_punctuation(match.group(0))
        match = re.search(r"(?://)?(?:www\.)?missav\.[^\s`'\"<>，。！？；;,)）\]}]+/[^\s`'\"<>，。！？；;,)）\]}]+", text, re.I)
        if match:
            candidate = match.group(0)
            if "://" not in candidate:
                candidate = f"https://{candidate.lstrip('/')}"
            return cls._strip_url_trailing_punctuation(candidate)
        return text.strip().strip("`")

    def _normalize_keyword(self, raw_text: str) -> str:
        return self._extract_first_url(raw_text)

    def _scan_pages(self, page, data_dict, is_chinese_pass=False):
        """列表扫描允许局部页失败，但尽量保住已抓到的候选数据。"""
        current_page = 1
        max_pages = self._max_scan_pages()
        max_items = self._max_items_limit()
        base_url = page.url
        while self.is_running and current_page <= max_pages:
            self.log(f"   📄 扫描第 {current_page} 页...")
            try:
                self.interruptible_wait_for_selector(page, "div.grid", timeout=self.GRID_READY_TIMEOUT_MS)
                if not self.is_running or self.interrupt_requested:
                    break
                items = page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('div.grid a')).map(a => {
                        const img = a.querySelector('img');
                        const title = img ? img.getAttribute('alt') : a.textContent.trim();
                        return {
                            url: a.href,
                            title: title || "" 
                        };
                    });
                }''')

                code_pattern = re.compile(r'/cn/.*[a-zA-Z]+-\d+')
                new_count = 0
                for item in items:
                    if len(data_dict) >= max_items:
                        break
                    url = item['url']
                    title = item['title']
                    if "/cn/" in url and code_pattern.search(url):
                        if not any(x in url for x in ['contact', 'dmca']):
                            if url not in data_dict:
                                data_dict[url] = title
                                new_count += 1

                if len(data_dict) >= max_items:
                    self.log(f"   ✅ 已达到视频数上限 {max_items}，停止翻页")
                    break
                if not page.query_selector("a[rel='next']"):
                    break
                current_page += 1
                if "page=" in base_url:
                    next_url = re.sub(r'page=\d+', f'page={current_page}', base_url)
                else:
                    sep = "&" if "?" in base_url else "?"
                    next_url = f"{base_url}{sep}page={current_page}"
                try:
                    if not self.interruptible_playwright_goto(
                        page,
                        next_url,
                        timeout=self._configured_timeout_ms(default=60),
                    ):
                        break
                except PlaywrightError:
                    break
            except (PlaywrightError, ValueError, TypeError) as e:
                self.log(f"   ⚠️ 页面扫描异常: {e}")
                break

    def _max_items_limit(self) -> int:
        config = getattr(self, "config", {}) or {}
        try:
            value = int(config.get("max_items") or config.get("limit") or 20)
        except (TypeError, ValueError):
            value = 20
        return max(1, value)

    def _max_scan_pages(self) -> int:
        config = getattr(self, "config", {}) or {}
        try:
            value = int(config.get("search_max_pages") or config.get("max_pages") or 100)
        except (TypeError, ValueError):
            value = 100
        return max(1, value)

    def _trim_final_tasks(self, tasks):
        limit = self._max_items_limit()
        if len(tasks) <= limit:
            return list(tasks)
        self.log(f"   ✂️ 按视频数上限裁剪: {len(tasks)} -> {limit}")
        return list(tasks)[:limit]

    @staticmethod
    def _looks_like_hls_playlist(text: str | None) -> bool:
        return "#EXTM3U" in str(text or "")

    def _headers_from_request(self, request) -> dict[str, str]:
        try:
            raw_headers = request.all_headers()
        except (PlaywrightError, TypeError, AttributeError):
            try:
                raw_headers = request.headers
            except (PlaywrightError, TypeError, AttributeError):
                raw_headers = {}
        return self._sanitize_download_headers(raw_headers)

    def _download_headers_for_context(
        self,
        context,
        referer: str,
        user_agent: str,
        *,
        stream_url: str = "",
        request_headers: dict | None = None,
    ) -> dict[str, str]:
        has_browser_request_headers = bool(request_headers)
        headers = self._sanitize_download_headers(request_headers or {})
        headers.setdefault("User-Agent", user_agent or DEFAULT_USER_AGENT)
        headers.setdefault("Referer", referer)
        self._apply_browser_download_header_defaults(headers, referer, preserve_captured=has_browser_request_headers)
        if self._is_surrit_stream_url(stream_url):
            headers.setdefault("Range", "bytes=0-")
        if "Cookie" not in headers:
            cookie_header = self._cookie_header_for_context(context, stream_url, referer)
            if cookie_header:
                headers["Cookie"] = cookie_header
        return headers

    @staticmethod
    def _is_surrit_stream_url(stream_url: str) -> bool:
        try:
            host = urllib.parse.urlparse(str(stream_url or "")).netloc.lower()
        except (TypeError, ValueError):
            return False
        return host == "surrit.com" or host.endswith(".surrit.com")

    def _cookie_header_for_context(self, context, stream_url: str, referer: str) -> str:
        urls = [url for url in (stream_url, referer) if url][:1]
        try:
            cookies = context.cookies(urls) if urls else context.cookies()
        except TypeError:
            try:
                cookies = context.cookies()
            except (PlaywrightError, TypeError, AttributeError):
                cookies = []
        except (PlaywrightError, AttributeError):
            cookies = []
        return "; ".join(
            f"{cookie.get('name')}={cookie.get('value')}"
            for cookie in cookies
            if isinstance(cookie, dict) and cookie.get("name") and cookie.get("value") is not None
        )

    @staticmethod
    def _sanitize_download_headers(raw_headers: dict | None) -> dict[str, str]:
        blocked = {
            "host",
            "content-length",
            "connection",
            "transfer-encoding",
        }
        headers: dict[str, str] = {}
        for key, value in (raw_headers or {}).items():
            key_text = str(key or "").strip()
            value_text = str(value or "").strip()
            if not key_text or not value_text:
                continue
            lowered = key_text.lower()
            if lowered.startswith(":") or lowered in blocked:
                continue
            canonical = "-".join(part[:1].upper() + part[1:].lower() for part in lowered.split("-"))
            headers[canonical] = value_text
        return headers

    @classmethod
    def _apply_browser_download_header_defaults(
        cls,
        headers: dict[str, str],
        referer: str,
        *,
        preserve_captured: bool = False,
    ) -> None:
        headers.setdefault("Accept", "*/*")
        headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9,en-CN;q=0.8,en;q=0.7")
        headers.setdefault("Cache-Control", "no-cache")
        headers.setdefault("Pragma", "no-cache")
        headers.setdefault("Priority", "u=1, i")
        if preserve_captured:
            return
        origin = cls._origin_from_referer(referer)
        if origin:
            headers.setdefault("Origin", origin)
        headers.setdefault("Sec-Fetch-Dest", "empty")
        headers.setdefault("Sec-Fetch-Mode", "cors")
        headers.setdefault("Sec-Fetch-Site", "cross-site")
        headers.setdefault("Sec-Ch-Ua-Mobile", "?0")
        headers.setdefault("Sec-Ch-Ua-Platform", '"Windows"')

    @staticmethod
    def _origin_from_referer(referer: str) -> str:
        try:
            parsed = urllib.parse.urlparse(str(referer or ""))
        except (TypeError, ValueError):
            return ""
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"

    def _effective_proxy_server(
        self,
        configured: object = None,
        *,
        allow_system_fallback: bool | None = None,
    ) -> str | None:
        if configured is None:
            configured = (getattr(self, "config", {}) or {}).get("proxy")
        # MissAV 默认继承系统代理，但仍需遵守基类调用方的显式关闭请求。
        fallback = True if allow_system_fallback is None else bool(allow_system_fallback)
        return super()._effective_proxy_server(configured, allow_system_fallback=fallback)

    @classmethod
    def _proxy_from_environment(cls) -> str | None:
        return BaseSpider._proxy_from_environment()

    @classmethod
    def _proxy_from_windows_settings(cls) -> str | None:
        return BaseSpider._proxy_from_windows_settings()

    @classmethod
    def _proxy_from_proxy_server_string(cls, value: str | None) -> str | None:
        return BaseSpider._proxy_from_proxy_server_string(value)

    @staticmethod
    def _normalize_proxy_server(value: object) -> str | None:
        return BaseSpider._normalize_proxy_server(value)
