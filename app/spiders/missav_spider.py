# app/spiders/missav_spider.py

import re
import time
import urllib.parse
from collections import defaultdict
from playwright.sync_api import sync_playwright
from app.spiders.base_spider import BaseSpider

class MissAVSpider(BaseSpider):

    def run(self):
        try:
            # 配置解析 (保持不变)
            proxy_server = None
            if self.config.get('proxy'):
                proxy_server = self.config['proxy']
                self.log(f"🌍 使用代理: {proxy_server}")
            enable_individual = self.config.get('individual_only', False)
            priority_text = self.config.get('priority', "中文字幕优先")
            priority_map = {
                "中文字幕优先": ["中文字幕", "无码流出", "英文字幕", "普通版"],
                "无码流出优先": ["无码流出", "中文字幕", "英文字幕", "普通版"]
            }
            self.priority_list = priority_map.get(priority_text, priority_map["中文字幕优先"])
            self.log(f"⚙️ 偏好设置: 单体={enable_individual}, 优先级={self.priority_list}")
            my_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            # 路由解析 (保持不变)
            target_url = ""
            is_single_video_mode = False
            is_search_mode = False
            raw_input = self.keyword.strip()
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
                target_url = self._inject_url_params(target_url, enable_individual)
                self.log(f"🔧 修正后 URL: {target_url}")
            if not self.is_running: return
            # 启动浏览器
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    proxy={"server": proxy_server} if proxy_server else None,
                    args=['--disable-blink-features=AutomationControlled']
                )
                context = browser.new_context(user_agent=my_ua)
                page = context.new_page()
                self.log("🚀 正在访问页面...")
                page.goto(target_url, timeout=60000)
                if "Just a moment" in page.title():
                    self.log("🛡️ 检测到 Cloudflare，等待通过...")
                    page.wait_for_timeout(5000)
                    page.wait_for_load_state("domcontentloaded")
                # 头像跳转
                if is_search_mode and self.is_running:
                    try:
                        time.sleep(2)
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
                            page.wait_for_load_state('domcontentloaded')
                            current_url = page.url
                            new_url = self._inject_url_params(current_url, enable_individual)
                            if new_url != current_url:
                                page.goto(new_url)
                    except:
                        pass
                if not self.is_running:
                    browser.close()
                    return
                # 数据采集
                final_tasks = []
                if is_single_video_mode:
                    title = page.title().replace('| MissAV', '').strip()
                    final_tasks.append({'title': title, 'url': page.url})
                else:
                    scraped_data = {}
                    verified_chinese = set()
                    base_url = page.url
                    # --- Pass 1: 主遍历 ---
                    self.log("📜 开始第一遍扫描 (获取所有视频)...")
                    self._scan_pages(page, scraped_data, is_chinese_pass=False)

                    if not self.is_running:
                        self.log("⏸️ 扫描被中断，跳过中文校验，准备生成清单...")
                    if not scraped_data:
                        self.log("❌ 未找到任何视频")
                        browser.close()
                        return
                    # --- Pass 2: 中文校验 (仅当未停止时执行) ---
                    # 只有当还在运行时，才去扫第二遍
                    if self.is_running:
                        self.log("🇨🇳 开始第二遍扫描 (校验中文字幕)...")
                        chinese_url = self._add_chinese_filter(base_url)

                        if chinese_url != base_url:
                            self.log(f"   跳转校验: {chinese_url}")
                            try:
                                chinese_url_no_page = re.sub(r'[?&]page=\d+', '', chinese_url)
                                page.goto(chinese_url_no_page, timeout=60000)

                                chinese_data = {}
                                self._scan_pages(page, chinese_data, is_chinese_pass=True)
                                verified_chinese = set(chinese_data.keys())
                                scraped_data.update(chinese_data)
                            except Exception as e:
                                self.log(f"   ⚠️ 中文校验异常: {e}")

                    if not self.is_running and scraped_data:
                        self.is_running = True
                    # --- 智能分组打分 ---
                    self.log(f"🧠 智能筛选中 (共 {len(scraped_data)} 个候选)...")
                    grouped = defaultdict(list)
                    code_pattern = re.compile(r'/cn/.*?([a-zA-Z]+-\d+)')

                    for url, title in scraped_data.items():
                        code = None
                        match = code_pattern.search(url)
                        if match: code = match.group(1).upper()

                        if code:
                            grouped[code].append((url, title))
                        else:
                            grouped[url].append((url, title))

                    for code, items in grouped.items():
                        sorted_items = sorted(
                            items,
                            key=lambda x: self._calculate_score(x[0], x[1], verified_chinese),
                            reverse=True
                        )
                        best_url, best_title = sorted_items[0]
                        final_title = self._generate_display_title(best_url, best_title, verified_chinese)
                        final_tasks.append({'title': final_title, 'url': best_url})

                # ================= 4. 用户交互 =================
                if not final_tasks:
                    self.log("❌ 筛选后无有效结果")
                    browser.close()
                    return
                self.log(f"🔔 扫描完成，共 {len(final_tasks)} 个最佳版本")

                # 确保复活，否则弹窗逻辑会立即退出
                self.is_running = True
                # 弹窗选择
                selected_indices = self.ask_user_selection(final_tasks)
                # 如果此时返回 None，说明用户在弹窗里点了“取消”
                if not selected_indices:
                    self.log("❌ 用户取消下载")
                    browser.close()
                    return
                self.log(f"✅ 选中 {len(selected_indices)} 个，开始嗅探 m3u8...")

                # ================= 5. 详情页嗅探 (playlist.m3u8) =================
                success_count = 0
                for i, idx in enumerate(selected_indices):
                    if not self.is_running: break
                    task = final_tasks[idx]
                    target_page_url = task['url']
                    title = task['title']
                    self.log(f"🕵️ [{i + 1}/{len(selected_indices)}] 嗅探: {title[:15]}...")
                    m3u8_url = None
                    def handle_request(req):
                        nonlocal m3u8_url
                        if "playlist.m3u8" in req.url:
                            m3u8_url = req.url
                    def on_popup(popup):
                        if popup != page:
                            try:
                                popup.close()
                            except:
                                pass
                    context.on("page", on_popup)
                    page.on("request", handle_request)
                    try:
                        page.goto(target_page_url, timeout=60000)
                        if "Just a moment" in page.title():
                            time.sleep(10)
                        try:
                            page.wait_for_selector(".plyr", timeout=5000)
                            page.mouse.click(400, 300)
                            time.sleep(2)
                            if not m3u8_url: page.mouse.click(400, 300)
                        except:
                            pass
                        for _ in range(15):
                            if m3u8_url or not self.is_running: break
                            time.sleep(1)
                        if not self.is_running: break
                        if m3u8_url:
                            self.log("   ✨ 嗅探成功")
                            self.emit_video(
                                url=m3u8_url,
                                title=title,
                                source="missav",
                                meta={
                                    "referer": target_page_url,
                                    "ua": my_ua,
                                    "proxy": proxy_server
                                }
                            )
                            success_count += 1
                        else:
                            self.log("   ⚠️ 嗅探超时 (未找到 playlist.m3u8)")
                    except Exception as e:
                        self.log(f"   ❌ 页面加载错误: {e}")
                    page.remove_listener("request", handle_request)
                    context.remove_listener("page", on_popup)
                    time.sleep(1)
                if self.is_running:
                    self.log(f"🎉 任务结束，成功提交: {success_count}")
                else:
                    self.log("🛑 任务强制中止")
                browser.close()
        except Exception as e:
            self.log(f"💥 爬虫错误: {e}")
        finally:
            self.sig_finished.emit()

    def _inject_url_params(self, url, individual_only):
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if individual_only:
            filters = qs.get('filters', [''])[0]
            parts = filters.split(',') if filters else []
            if 'individual' not in parts:
                parts.append('individual')
                new_filters = ",".join([p for p in parts if p])
                qs['filters'] = [new_filters]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def _add_chinese_filter(self, url):
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        filters = qs.get('filters', [''])[0]
        parts = filters.split(',') if filters else []
        if 'chinese-subtitle' not in parts:
            parts.append('chinese-subtitle')
            qs['filters'] = [",".join([p for p in parts if p])]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def _scan_pages(self, page, data_dict, is_chinese_pass=False):
        current_page = 1
        max_pages = 100
        base_url = page.url
        while self.is_running and current_page <= max_pages:
            self.log(f"   📄 扫描第 {current_page} 页...")
            try:
                page.wait_for_selector("div.grid", timeout=10000)
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
                    url = item['url']
                    title = item['title']
                    if "/cn/" in url and code_pattern.search(url):
                        if not any(x in url for x in ['contact', 'dmca']):
                            if url not in data_dict:
                                data_dict[url] = title
                                new_count += 1

                if not page.query_selector("a[rel='next']"):
                    break
                current_page += 1
                if "page=" in base_url:
                    next_url = re.sub(r'page=\d+', f'page={current_page}', base_url)
                else:
                    sep = "&" if "?" in base_url else "?"
                    next_url = f"{base_url}{sep}page={current_page}"
                try:
                    page.goto(next_url, timeout=60000)
                except:
                    break
            except Exception as e:
                self.log(f"   ⚠️ 页面扫描异常: {e}")
                break

    def _calculate_score(self, url, title, verified_chinese):
        url_lower = url.lower()
        title_lower = title.lower()
        is_uncensored = "uncensored" in url_lower or "leak" in url_lower or "无码" in title_lower
        is_english = "english" in url_lower or "英文字幕" in title_lower
        is_chinese = (url in verified_chinese) or ("chinese" in url_lower) or ("中文字幕" in title_lower)
        if is_uncensored: is_chinese = False
        feature_map = {
            "中文字幕": is_chinese,
            "英文字幕": is_english,
            "无码流出": is_uncensored,
            "普通": (not is_chinese and not is_english and not is_uncensored)
        }
        total = len(self.priority_list)
        for idx, name in enumerate(self.priority_list):
            score = (total - idx) * 20
            for key, satisfies in feature_map.items():
                if key in name and satisfies: return score
        return 0

    def _generate_display_title(self, url, title, verified_chinese):
        tags = []
        url_lower = url.lower()
        is_uncensored = "uncensored" in url_lower or "leak" in url_lower or "无码" in title.lower()
        is_chinese = (url in verified_chinese) or ("chinese" in url_lower) or ("中文字幕" in title.lower())
        if is_uncensored:
            tags.append("[无码]")
            is_chinese = False
        if is_chinese: tags.append("[中字]")
        if "english" in url_lower: tags.append("[英字]")
        tag_str = "".join(tags)
        return f"{tag_str} {title}" if tag_str else title