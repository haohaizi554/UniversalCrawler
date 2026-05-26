"""Kuaishou spider with browser-driven scan and realtime stream capture."""

import os
import random
import threading
import urllib.parse

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg
from app.spiders.base import BaseSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.services.auth_service import AuthService


class KuaishouSpider(BaseSpider):
    """快手爬虫，负责页面滚动扫描、任务选择和流监听。"""

    def __init__(self, keyword: str, config: dict):
        super().__init__(keyword, config)
        self.parser = KuaishouParser()
        self.task_builder = KuaishouTaskBuilder()
        self.auth_service = AuthService()
        self._selected_indices: list[int] = []
        self._lock = threading.Lock()

    def _build_proxy_cfg(self) -> dict[str, str] | None:
        proxy = self.config.get("proxy")
        if not proxy:
            return None
        self.log(f"🌍 使用代理: {proxy}")
        return {"server": proxy}

    def _load_saved_cookies(self, context, auth_file: str) -> None:
        if not os.path.exists(auth_file):
            return
        try:
            if self.auth_service.restore_playwright_cookies(context, auth_file):
                self.log("📂 加载本地 Cookie 成功")
        except (OSError, TypeError, ValueError, PlaywrightError):
            self.log("⚠️ 本地 Cookie 加载失败，继续尝试页面登录")

    def _ensure_login(self, page, context, auth_file: str) -> bool:
        self.log("🔗 访问快手首页...")
        page.goto("https://www.kuaishou.com/", timeout=60000)
        try:
            page.wait_for_selector(".header-user-avatar, .user-avatar", timeout=5000)
            self.log("✅ 检测到登录状态")
            return True
        except PlaywrightError:
            self.log("🔑 未登录，尝试自动触发登录弹窗...")
            try:
                page.locator(".login-btn, text=登录").first.click()
            except PlaywrightError:
                pass

            success = self.auth_service.wait_for_cookie_and_persist(
                context=context,
                cookie_name="userId",
                save_path=auth_file,
                save_mode="storage_state",
                stop_check=lambda: not self.is_running,
                wait_callback=lambda: page.wait_for_timeout(1000),
            )
            if success:
                self.log("✅ 登录成功，Cookie 已保存")
                return True
        return self.is_running

    def _navigate_to_target_page(self, page, context):
        if "kuaishou.com" in self.keyword:
            page.goto(self.keyword)
            return page

        encoded_keyword = urllib.parse.quote(self.keyword, safe="")
        search_url = f"https://www.kuaishou.com/search/author?source=NewReco&searchKey={encoded_keyword}"
        page.goto(search_url)
        page.wait_for_timeout(2000)
        try:
            user_card = page.locator(".card-item .detail-user-name").first
            if not user_card.is_visible():
                self.log("❌ 未找到主播")
                return None
            name = user_card.inner_text()
            self.log(f"👉 进入主播主页: {name}")
            user_card.click()
            page.wait_for_timeout(3000)
            if len(context.pages) > 1:
                page = context.pages[-1]
                page.bring_to_front()
            return page
        except PlaywrightError:
            self.log("❌ 无法进入主播主页")
            return None

    def _wait_for_video_list(self, page) -> bool:
        try:
            page.wait_for_selector(".photo-card, .video-card", timeout=15000)
            return True
        except PlaywrightError:
            self.log("❌ 无法加载视频列表")
            return False

    def _scan_video_cards(self, page) -> int:
        """滚动页面直到内容加载完成或用户主动停止。"""
        self.log("\n📜 开始滚动加载列表... (点击【停止】生成清单)")
        scroll_count = 0
        last_card_count = 0
        no_new_content_count = 0
        while self.is_running:
            scroll_count += 1
            try:
                vp = page.viewport_size
                if vp:
                    page.mouse.move(vp["width"] / 2, vp["height"] / 2)
            except PlaywrightError:
                pass

            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(500)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(1000)

            cards = page.locator(".photo-card, .video-card")
            current_card_count = cards.count()
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
                    page.wait_for_timeout(1000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    no_new_content_count = 0
            else:
                no_new_content_count = 0
                last_card_count = current_card_count

            if scroll_count % 3 == 0:
                self.log(f"⬇️ 加载中... (已扫描 {current_card_count} 个)")
        return last_card_count

    def _extract_items_for_dialog(self, page) -> tuple[list[dict[str, int | str]], dict[int, set[str]]]:
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

        items_for_dialog: list[dict[str, int | str]] = []
        target_fingerprints_map: dict[int, set[str]] = {}
        for idx, raw_title in enumerate(video_titles):
            clean_title = raw_title.replace("\n", " ").strip() or f"未命名视频_{idx + 1}"
            items_for_dialog.append({"title": clean_title, "index": idx})
            if idx < len(video_imgs):
                target_fingerprints_map[idx] = self.parser.extract_all_possible_ids(video_imgs[idx])
        return items_for_dialog, target_fingerprints_map

    def _collect_selected_indices(self, items_for_dialog: list[dict[str, int | str]]):
        if not items_for_dialog:
            self.log("❌ 未扫描到有效视频")
            return None
        self.log(f"🔔 扫描完成，共 {len(items_for_dialog)} 个，请选择下载...")
        selected_indices = self.ask_user_selection(items_for_dialog)
        if not selected_indices:
            self.log("❌ 用户取消了下载任务")
            return None
        return selected_indices

    def _run_capture_pipeline(self, page, items_for_dialog: list[dict[str, int | str]], target_fingerprints_map: dict[int, set[str]]) -> None:
        target_indices_set = set(self._selected_indices)
        submitted_indices: set[int] = set()
        current_focus_index = 0
        total_scrolls = len(items_for_dialog)

        def handle_response(response):
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
                    if matched_idx == -1 and "pkey" in url:
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

        page.on("response", handle_response)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        cards = page.locator(".photo-card, .video-card")
        try:
            first_card = cards.first
            if not first_card.is_visible():
                first_card.scroll_into_view_if_needed()
            first_card.click()
            page.wait_for_timeout(3000)
            try:
                page.mouse.click(200, 200)
            except PlaywrightError:
                pass
        except PlaywrightError:
            self.log("❌ 无法进入详情页")
            return

        self.log(f"🔄 生产者工作开始 (0 - {total_scrolls})...")
        while current_focus_index < total_scrolls and self.is_running:
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
        not_found = target_indices_set - submitted_indices
        if not_found:
            self.log(f"⚠️ {len(not_found)} 个视频未捕获:")
            for idx in sorted(list(not_found)):
                self.log(f"   - [{idx + 1}] {items_for_dialog[idx]['title'][:20]}...")
        else:
            self.log("✅ 全部任务完成！")

    def run(self):
        auth_file = cfg.get("auth", "kuaishou_cookie_file", "ks_auth.json")
        proxy_cfg = self._build_proxy_cfg()
        self.log(f"🚀 启动快手任务 | 目标: {self.keyword}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    proxy=proxy_cfg,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    # 快手浏览器上下文优先使用本平台 UA，避免复制粘贴到抖音配置导致行为漂移。
                    user_agent=cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
                    viewport={"width": 1280, "height": 800},
                )
                self._load_saved_cookies(context, auth_file)
                page = context.new_page()
                if not self._ensure_login(page, context, auth_file):
                    return

                page = self._navigate_to_target_page(page, context)
                if not page or not self._wait_for_video_list(page):
                    return

                last_card_count = self._scan_video_cards(page)
                if not self.is_running:
                    if last_card_count > 0:
                        self.log("⏸️ 扫描被中断，准备生成清单...")
                        self.is_running = True
                    else:
                        self.log("🛑 任务已终止")
                        browser.close()
                        return

                items_for_dialog, target_fingerprints_map = self._extract_items_for_dialog(page)
                selected_indices = self._collect_selected_indices(items_for_dialog)
                if not selected_indices:
                    return
                self.is_running = True
                self._selected_indices = selected_indices
                self.log(f"✅ 选中 {len(selected_indices)} 个任务，流水线启动...")
                self._run_capture_pipeline(page, items_for_dialog, target_fingerprints_map)
                browser.close()
        except (PlaywrightError, OSError, ValueError, RuntimeError) as e:
            self.log(f"💥 爬虫错误: {e}")
        finally:
            self.sig_finished.emit()
