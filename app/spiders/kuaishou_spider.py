# app/spiders/kuaishou_spider.py

import os
import time
import random
import json
import re
import urllib.parse
import base64
import threading
from playwright.sync_api import sync_playwright
from app.spiders.base_spider import BaseSpider

class KuaishouSpider(BaseSpider):

    def run(self):
        auth_file = "ks_auth.json"
        # 线程同步锁
        self._lock = threading.Lock()
        # 代理配置
        proxy_cfg = None
        if self.config.get('proxy'):
            proxy_cfg = {"server": self.config['proxy']}
            self.log(f"🌍 使用代理: {self.config['proxy']}")
        self.log(f"🚀 启动快手任务 | 目标: {self.keyword}")
        try:
            with sync_playwright() as p:
                # 1. 启动浏览器
                browser = p.chromium.launch(
                    headless=False,
                    proxy=proxy_cfg,
                    args=['--disable-blink-features=AutomationControlled']
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                if os.path.exists(auth_file):
                    try:
                        with open(auth_file, 'r', encoding='utf-8') as f:
                            cookies = json.load(f)
                        if isinstance(cookies, dict) and 'cookies' in cookies:
                            # 兼容 playwright storage_state 格式
                            context.add_cookies(cookies['cookies'])
                        elif isinstance(cookies, list):
                            context.add_cookies(cookies)
                        self.log("📂 加载本地 Cookie 成功")
                    except:
                        pass
                page = context.new_page()
                # ================= 阶段一：登录与导航 =================
                self.log("🔗 访问快手首页...")
                page.goto("https://www.kuaishou.com/", timeout=60000)
                try:
                    page.wait_for_selector(".header-user-avatar, .user-avatar", timeout=5000)
                    self.log("✅ 检测到登录状态")
                except:
                    self.log("🔑 未登录，尝试自动触发登录弹窗...")
                    try:
                        page.locator(".login-btn, text=登录").first.click()
                    except:
                        pass

                    for _ in range(120):
                        if not self.is_running: return
                        cookies = context.cookies()
                        if any(c['name'] == 'userId' for c in cookies):
                            # 保存为易读格式
                            storage = context.storage_state()
                            with open(auth_file, 'w', encoding='utf-8') as f:
                                json.dump(storage, f, indent=4, ensure_ascii=False)
                            self.log("✅ 登录成功，Cookie 已保存")
                            break
                        page.wait_for_timeout(1000)
                if not self.is_running: return
                if "kuaishou.com" in self.keyword:
                    page.goto(self.keyword)
                else:
                    search_url = f"https://www.kuaishou.com/search/author?source=NewReco&searchKey={self.keyword}"
                    page.goto(search_url)
                    page.wait_for_timeout(2000)
                    try:
                        user_card = page.locator(".card-item .detail-user-name").first
                        if user_card.is_visible():
                            name = user_card.inner_text()
                            self.log(f"👉 进入主播主页: {name}")
                            user_card.click()
                            page.wait_for_timeout(3000)
                            if len(context.pages) > 1:
                                page = context.pages[-1]
                                page.bring_to_front()
                        else:
                            self.log("❌ 未找到主播")
                            return
                    except:
                        return
                try:
                    page.wait_for_selector(".photo-card, .video-card", timeout=15000)
                except:
                    self.log("❌ 无法加载视频列表")
                    return
                # ================= 阶段二：滚动扫描 =================
                self.log("\n📜 开始滚动加载列表... (点击【停止】生成清单)")
                scroll_count = 0
                last_card_count = 0
                no_new_content_count = 0
                while self.is_running:
                    scroll_count += 1
                    # 1. 模拟人类鼠标移动 (防风控)
                    try:
                        vp = page.viewport_size
                        if vp:
                            page.mouse.move(vp['width'] / 2, vp['height'] / 2)
                    except:
                        pass
                    # 2. 混合滚动策略
                    page.evaluate("window.scrollBy(0, 800)")
                    page.wait_for_timeout(500)
                    page.mouse.wheel(0, 500)  # 模拟滚轮，这很重要
                    page.wait_for_timeout(1000)
                    # 3. 检查数量
                    cards = page.locator(".photo-card, .video-card")
                    current_card_count = cards.count()
                    # 4. 检查"没有更多"
                    no_more = False
                    try:
                        no_more_el = page.locator("text='没有更多了'")
                        if no_more_el.count() > 0 and no_more_el.first.is_visible(): no_more = True
                    except:
                        pass
                    if no_more:
                        self.log("✅ 已加载全部视频")
                        break
                    # 5. 死锁检测与激活
                    if current_card_count == last_card_count:
                        no_new_content_count += 1
                        if no_new_content_count >= 5:
                            self.log("🔄 似乎卡住了，尝试回滚刷新...")
                            # 回滚策略：往上滑一点，再狠滑到底
                            page.evaluate("window.scrollBy(0, -1000)")
                            page.wait_for_timeout(1000)
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            no_new_content_count = 0
                    else:
                        no_new_content_count = 0
                        last_card_count = current_card_count
                    if scroll_count % 3 == 0:
                        self.log(f"⬇️ 加载中... (已扫描 {current_card_count} 个)")
                if not self.is_running:
                    if last_card_count > 0:
                        self.log("⏸️ 扫描被中断，准备生成清单...")
                        self.is_running = True  # 复活线程
                    else:
                        self.log("🛑 任务已终止")
                        browser.close()
                        return
                    # ================= 阶段三：提取特征 & 弹窗 =================
                self.log("🧠 解析视频信息...")
                # 1. 提取标题
                video_titles = page.evaluate("""() => {
                    const cards = document.querySelectorAll('.photo-card, .video-card');
                    return Array.from(cards).map(c => {
                        const titleEl = c.querySelector('[class*="caption"]');
                        return titleEl ? titleEl.innerText : '';
                    });
                }""")
                # 2. 提取封面图 URL
                video_imgs = page.evaluate("""() => {
                    const cards = document.querySelectorAll('.photo-card, .video-card');
                    return Array.from(cards).map(c => {
                        const imgEl = c.querySelector('img.cover-img');
                        return imgEl ? imgEl.src : '';
                    });
                }""")
                items_for_dialog = []
                target_fingerprints_map = {}
                for idx, raw_title in enumerate(video_titles):
                    clean_title = raw_title.replace('\n', ' ').strip()
                    if not clean_title: clean_title = f"未命名视频_{idx + 1}"
                    items_for_dialog.append({'title': clean_title, 'index': idx})
                    if idx < len(video_imgs):
                        img_url = video_imgs[idx]
                        ids = self._extract_all_possible_ids(img_url)
                        target_fingerprints_map[idx] = ids
                if not items_for_dialog:
                    self.log("❌ 未扫描到有效视频")
                    return
                self.log(f"🔔 扫描完成，共 {len(items_for_dialog)} 个，请选择下载...")
                selected_indices = self.ask_user_selection(items_for_dialog)
                if not selected_indices:
                    self.log("❌ 用户取消了下载任务")
                    browser.close()
                    return
                self.is_running = True
                target_indices_set = set(selected_indices)
                submitted_indices = set()
                encrypted_queue = []
                max_target_idx = max(selected_indices)
                self.log(f"✅ 选中 {len(target_indices_set)} 个任务，流水线启动...")
                # ================= 阶段四：实时流水线 =================
                current_focus_index = 0
                # 1. 消费者：网络监听器
                def handle_response(response):
                    ctype = response.headers.get("content-type", "")
                    if response.request.resource_type == "media" or \
                            "video/mp4" in ctype or \
                            "mpegurl" in ctype.lower() or \
                            ".m3u8" in response.url:
                        try:
                            if ".mp4" in response.url:
                                try:
                                    if int(response.headers.get("content-length", 0)) < 5000: return
                                except:
                                    pass
                            url = response.url
                            vid_ids = self._extract_all_possible_ids(url)
                            matched_idx = -1
                            with self._lock:
                                # A. 精确 ID 匹配
                                if vid_ids:
                                    for idx in target_indices_set:
                                        if idx in submitted_indices: continue
                                        cover_ids = target_fingerprints_map.get(idx, set())
                                        if not cover_ids.isdisjoint(vid_ids):
                                            matched_idx = idx
                                            break
                                # B. 时序焦点匹配 (兜底)
                                if matched_idx == -1 and "pkey" in url:
                                    if current_focus_index in target_indices_set and current_focus_index not in submitted_indices:
                                        matched_idx = current_focus_index
                                        self.log(
                                            f"   🔒 [加密流] 匹配焦点: {items_for_dialog[matched_idx]['title'][:10]}...")
                                # 提交下载
                                if matched_idx != -1:
                                    submitted_indices.add(matched_idx)
                                    title = items_for_dialog[matched_idx]['title']
                                    source_type = "kuaishou"
                                    if ".m3u8" in url: source_type = "missav"
                                    self.log(f"   ✨ [捕获] {title[:15]}... -> 加入下载队列")
                                    self.emit_video(
                                        url=url,
                                        title=title,
                                        source=source_type,
                                        meta={"referer": page.url}
                                    )
                        except Exception as e:
                            pass
                page.on("response", handle_response)
                # 2. 生产者：刷屏
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1000)
                cards = page.locator(".photo-card, .video-card")
                try:
                    first_card = cards.first
                    if not first_card.is_visible(): first_card.scroll_into_view_if_needed()
                    first_card.click()
                    page.wait_for_timeout(3000)
                    try:
                        page.mouse.click(200, 200)
                    except:
                        pass
                except:
                    self.log("❌ 无法进入详情页")
                    return
                current_focus_index = 0
                total_scrolls = len(items_for_dialog)
                self.log(f"🔄 生产者工作开始 (0 - {total_scrolls})...")
                while current_focus_index < total_scrolls and self.is_running:
                    # 提前结束检查
                    with self._lock:
                        if len(submitted_indices) >= len(target_indices_set):
                            self.log("🎉 所有任务已实时捕获，提前结束！")
                            break
                    if (current_focus_index + 1) % 5 == 0:
                        self.log(f"🔄 刷屏进度: {current_focus_index + 1}/{total_scrolls}")
                    page.keyboard.press("ArrowDown")
                    with self._lock:
                        current_focus_index += 1
                    is_target = current_focus_index in target_indices_set
                    if is_target:
                        wait_ms = random.randint(1500, 2500)
                    else:
                        wait_ms = random.randint(600, 1000)
                    page.wait_for_timeout(wait_ms)
                    try:
                        if page.locator(".close-icon").is_visible():
                            page.locator(".close-icon").click()
                    except:
                        pass
                # 结束汇报
                self.log(f"\n📊 流程结束。")
                not_found = target_indices_set - submitted_indices
                if not_found:
                    self.log(f"⚠️ {len(not_found)} 个视频未捕获:")
                    for idx in sorted(list(not_found)):
                        self.log(f"   - [{idx + 1}] {items_for_dialog[idx]['title'][:20]}...")
                else:
                    self.log("✅ 全部任务完成！")
                browser.close()
        except Exception as e:
            self.log(f"💥 爬虫错误: {e}")
        self.sig_finished.emit()
    def _extract_all_possible_ids(self, url):
        # 保持之前的多模态算法不变，因为它很强
        if not url: return set()
        ids = set()
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(urllib.parse.unquote(parsed.query))
            path = parsed.path
            filename = path.split('/')[-1]
            # 1. clientCacheKey
            if 'clientCacheKey' in qs:
                key = qs['clientCacheKey'][0]
                key_no_ext = key.rsplit('.', 1)[0]
                match = re.match(r'^([a-zA-Z0-9]+)', key_no_ext)
                if match: ids.add(match.group(1))
            # 2. x-ks-ptid
            if 'x-ks-ptid' in qs:
                ids.add(qs['x-ks-ptid'][0])
            # 3. Base64
            b64_match = re.search(r'(BMj[a-zA-Z0-9+/]+)', path)
            if not b64_match: b64_match = re.search(r'(BMj[a-zA-Z0-9+/]+)', urllib.parse.unquote(parsed.query))
            if b64_match:
                b64_str = b64_match.group(1)
                try:
                    missing_padding = len(b64_str) % 4
                    if missing_padding: b64_str += '=' * (4 - missing_padding)
                    decoded_bytes = base64.b64decode(b64_str)
                    decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                    parts = decoded_str.split('_')
                    if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) >= 10:
                        ids.add(parts[2])
                    nums = re.findall(r'\d{10,}', decoded_str)
                    ids.update(nums)
                except:
                    pass
            # 4. 路径回退
            name_no_ext = filename.rsplit('.', 1)[0]
            ids.add(name_no_ext)
            if '_b_B' in name_no_ext: ids.add(name_no_ext.split('_b_B')[0])
        except:
            pass
        return ids