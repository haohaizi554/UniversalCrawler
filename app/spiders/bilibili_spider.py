# app/spiders/bilibili_spider.py

import os
import re
import time
import json
import requests
import urllib.parse
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
from app.spiders.base_spider import BaseSpider

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com'
}

class BiliAPI:
    def __init__(self, cookie_path):
        self.sess = requests.Session()
        self.sess.headers.update(HEADERS)
        self.cookie_path = cookie_path
        self.load_cookies()

    def load_cookies(self):
        if os.path.exists(self.cookie_path):
            try:
                with open(self.cookie_path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                    if isinstance(cookies, list):
                        for c in cookies:
                            self.sess.cookies.set(c['name'], c['value'], domain=c['domain'])
                    elif isinstance(cookies, dict):
                        for k, v in cookies.items():
                            self.sess.cookies.set(k, v, domain=".bilibili.com")
            except:
                pass

    def check_login(self):
        try:
            url = "https://api.bilibili.com/x/web-interface/nav"
            resp = self.sess.get(url, timeout=10).json()
            return resp['code'] == 0 and resp['data']['isLogin']
        except:
            return False

    def get_video_info(self, bvid):
        """获取视频详情，返回结构化数据"""
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            resp = self.sess.get(url, timeout=10).json()
            if resp['code'] != 0: return None
            data = resp['data']

            info = {
                'bvid': data['bvid'],
                'title': data['title'],
                'owner': data['owner']['name'],
                'is_season': False,
                'season_id': None,
                'season_title': "",
                'episodes': []
            }
            # 合集判断
            if 'ugc_season' in data and data['ugc_season']:
                info['is_season'] = True
                info['season_id'] = data['ugc_season']['id']
                info['season_title'] = data['ugc_season']['title']
                ep_counter = 1
                for section in data['ugc_season']['sections']:
                    for ep in section['episodes']:
                        info['episodes'].append({
                            'title': ep['title'],
                            'bvid': ep['bvid'],
                            'cid': ep['cid'],
                            'page_num': ep_counter
                        })
                        ep_counter += 1
            else:
                info['season_title'] = data['title']
                for page in data['pages']:
                    info['episodes'].append({
                        'title': page['part'],
                        'bvid': data['bvid'],
                        'cid': page['cid'],
                        'page_num': page['page']
                    })
            return info
        except Exception as e:
            return None

    def get_play_url(self, bvid, cid):
        def _request(fnval):
            url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=120&fnval={fnval}&fourk=1"
            return self.sess.get(url, timeout=10).json()
        resp = _request(4048)
        if resp['code'] != 0 or 'data' not in resp or 'dash' not in resp['data']:
            resp = _request(80)
        if resp['code'] == 0 and 'data' in resp and 'dash' in resp['data']:
            dash = resp['data']['dash']
            video_url = dash['video'][0]['baseUrl']
            audio_url = dash['audio'][0]['baseUrl'] if dash.get('audio') else None
            quality_id = dash['video'][0]['id']
            return video_url, audio_url, quality_id
        return None, None, 0

class BilibiliSpider(BaseSpider):
    def run(self):
        try:
            cookie_file = "bili_auth.json"
            self.api = BiliAPI(cookie_file)
            if not self.api.check_login():
                self.log("🔒 未检测到登录，启动浏览器扫码...")
                if not self._perform_login_scan(cookie_file):
                    self.log("⚠️ 登录失败，以游客身份爬取")
            else:
                self.log("👤 已登录，Cookie 有效")
            self.log(f"🚀 启动 Bilibili 任务 | 目标: {self.keyword}")
            # --- 流水线队列 ---
            self.raw_bv_queue = queue.Queue()
            self.parsed_info_queue = queue.Queue()
            # --- 线程同步标志 ---
            self.browser_finished = threading.Event()
            self.api_pool_finished = threading.Event()
            # 1. 启动【生产者线程】(浏览器扫描)
            browser_thread = threading.Thread(target=self._producer_browser_task)
            browser_thread.start()
            # 2. 启动【加工者线程池】(API 解析)
            api_pool_thread = threading.Thread(target=self._worker_api_pool)
            api_pool_thread.start()
            # 3. 【主控循环】(装配者)
            display_items = []
            cached_data = {}
            seen_season_ids = set()
            seen_bvid_singles = set()
            valid_idx = 0
            self.log("⚡ 流水线已建立: 扫描 -> 解析 -> 聚合 同时进行中...")
            while True:
                # 退出条件：API 线程池完成且队列为空
                if self.api_pool_finished.is_set() and self.parsed_info_queue.empty():
                    break
                if not self.is_running: break
                try:
                    info = self.parsed_info_queue.get(timeout=0.5)
                    # --- 实时聚合逻辑 ---
                    if info['is_season']:
                        sid = info['season_id']
                        if sid not in seen_season_ids:
                            seen_season_ids.add(sid)
                            count = len(info['episodes'])
                            title_str = f"【合集】{info['season_title']} (共 {count} 集) - {info['owner']}"
                            display_items.append({'title': title_str, 'index': valid_idx})
                            cached_data[valid_idx] = {'type': 'season', 'info': info}
                            valid_idx += 1
                    else:
                        if info['bvid'] not in seen_bvid_singles:
                            seen_bvid_singles.add(info['bvid'])
                            count = len(info['episodes'])
                            if count > 1:
                                title_str = f"【多P】{info['title']} (共 {count} P) - {info['owner']}"
                                item_type = 'multi_p'
                            else:
                                title_str = f"【视频】{info['title']} - {info['owner']}"
                                item_type = 'single'
                            display_items.append({'title': title_str, 'index': valid_idx})
                            cached_data[valid_idx] = {'type': item_type, 'info': info}
                            valid_idx += 1
                    if valid_idx % 5 == 0:
                        self.log(f"   📊 已聚合 {valid_idx} 个有效资源...")
                except queue.Empty:
                    continue
            browser_thread.join()
            api_pool_thread.join()
            if not display_items:
                self.log("❌ 未找到任何有效视频")
                return
            # ================= 4. 第一层交互 =================
            self.log(f"🔔 扫描结束，共 {len(display_items)} 个项目，请选择...")
            stage1_indices = self.ask_user_selection(display_items)
            if not stage1_indices:
                self.log("❌ 用户取消下载")
                return
            # ================= 5. 第二层交互 & 下载 =================
            final_download_queue = []
            for idx in stage1_indices:
                if not self.is_running: break
                item = cached_data[idx]
                info = item['info']
                episodes = info['episodes']
                item_type = item['type']
                if item_type == 'single':
                    ep = episodes[0]
                    final_download_queue.append({
                        'bvid': ep['bvid'],
                        'cid': ep['cid'],
                        'file_name': self._clean_name(ep['title']) + ".mp4",
                        'folder_name': None,
                        'referer': f"https://www.bilibili.com/video/{ep['bvid']}"
                    })
                    continue
                sub_dialog_items = []
                for i, ep in enumerate(episodes):
                    num_str = str(ep.get('page_num', i + 1)).zfill(2)
                    sub_dialog_items.append({
                        'title': f"[{num_str}] {ep['title']}",
                        'index': i
                    })
                self.log(f"🔔 正在展开: {info.get('season_title') or info['title']}")
                sub_indices = self.ask_user_selection(sub_dialog_items)
                if not sub_indices:
                    continue
                for sub_idx in sub_indices:
                    ep = episodes[sub_idx]
                    folder_name = self._clean_name(info.get('season_title') or info['title'])
                    num_str = str(ep.get('page_num', sub_idx + 1)).zfill(2)
                    safe_title = self._clean_name(ep['title'])
                    file_name = f"P{num_str}_{safe_title}.mp4"
                    final_download_queue.append({
                        'bvid': ep['bvid'],
                        'cid': ep['cid'],
                        'file_name': file_name,
                        'folder_name': folder_name,
                        'referer': f"https://www.bilibili.com/video/{ep['bvid']}"
                    })
            self.log(f"✅ 最终确认 {len(final_download_queue)} 个任务，开始下载...")
            success_count = 0
            for task in final_download_queue:
                if not self.is_running: break
                self.log(f"🎬 解析流: {task['file_name'][:15]}...")
                v_url, a_url, q_id = self.api.get_play_url(task['bvid'], task['cid'])
                if v_url:
                    q_map = {127: "8K", 120: "4K", 116: "1080P60", 80: "1080P", 64: "720P"}
                    q_text = q_map.get(q_id, "高清")
                    self.log(f"   ✨ 获取成功 [{q_text}]")
                    meta = {
                        "audio_url": a_url,
                        "ua": HEADERS['User-Agent'],
                        "referer": task['referer']
                    }
                    if task['folder_name']:
                        meta["folder_name"] = task['folder_name']
                    self.emit_video(
                        url=v_url,
                        title=task['file_name'],
                        source="bilibili",
                        meta=meta
                    )
                    success_count += 1
                else:
                    self.log(f"   ❌ 获取流失败")
                time.sleep(0.5)
            self.log(f"🎉 全部完成: {success_count}/{len(final_download_queue)}")
        finally:
            self.sig_finished.emit()
    # --- 线程任务：浏览器生产者 ---
    def _producer_browser_task(self):
        """只负责翻页和提取 BV，扔进队列"""
        try:
            max_pages = self.config.get('max_pages', 1)
            target_url = self.keyword
            is_search = False
            is_space = False
            # 模式 A: 纯数字 -> UP主 ID
            if re.match(r'^\d+$', self.keyword):
                self.log(f"🔍 [识别结果] UP主 UID (纯数字) -> 准备爬取主页视频")
                target_url = f"https://space.bilibili.com/{self.keyword}/video"
                # UP主模式强制全量
                self._scan_with_browser_queue(target_url, max_pages=9999, is_search=False, is_space=True)
            # 模式 B: 纯 BV 号
            elif re.match(r'(?i)^BV\w+$', self.keyword):
                self.log("🔗 [识别结果] 单个视频 (BV号)")
                self.raw_bv_queue.put(self.keyword)
            # 模式 C: URL
            elif "http" in self.keyword:
                single_bv = re.search(r'(BV\w+)', self.keyword)
                # 情况 C-1: 视频详情页
                if "/video/BV" in self.keyword and single_bv and "list" not in self.keyword and "space" not in self.keyword:
                    self.log("🔗 [识别结果] 单个视频 (URL)")
                    self.raw_bv_queue.put(single_bv.group(1))
                else:
                    # 情况 C-2: 空间页/合集/列表
                    is_space = "space.bilibili.com" in self.keyword
                    if is_space:
                        # 主页链接修正逻辑
                        # 检查是否包含 /video，如果没有，尝试提取 UID 并构造
                        if "/video" not in self.keyword:
                            # 提取 UID: space.bilibili.com/1513751793?spm... -> 1513751793
                            uid_match = re.search(r'space\.bilibili\.com/(\d+)', self.keyword)
                            if uid_match:
                                uid = uid_match.group(1)
                                target_url = f"https://space.bilibili.com/{uid}/video"
                                self.log(f"🔧 [自动修正] 空间主页 -> 视频投稿页: {target_url}")
                            else:
                                self.log(f"🔍 [识别结果] 空间页 (未匹配到UID，保持原样)")
                        else:
                            self.log(f"🔍 [识别结果] UP主视频投稿页 URL")
                        # 空间页强制全量，忽略 max_pages
                        self._scan_with_browser_queue(target_url, max_pages=9999, is_search=False, is_space=True)
                    else:
                        # 搜索页 URL (直接粘贴的)
                        is_search_url = "search.bilibili.com" in self.keyword
                        self.log(f"🔍 [识别结果] 列表/搜索页 URL")
                        # 如果是搜索页 URL，必须开启 is_search=True 以便正确翻页
                        self._scan_with_browser_queue(self.keyword, max_pages, is_search=is_search_url, is_space=False)
            # 模式 D: 搜索关键词
            else:
                self.log(f"🔍 [识别结果] 关键词搜索")
                search_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(self.keyword)}"
                self._scan_with_browser_queue(search_url, max_pages, is_search=True, is_space=False)
        except Exception as e:
            self.log(f"❌ 浏览器线程异常: {e}")
        finally:
            self.browser_finished.set()
            # --- 线程任务：API 加工者 ---

    def _worker_api_pool(self):
        def process_one(bvid):
            if not self.is_running: return None
            return self.api.get_video_info(bvid)
        with ThreadPoolExecutor(max_workers=8) as executor:
            while True:
                if self.browser_finished.is_set() and self.raw_bv_queue.empty():
                    break
                if not self.is_running: break
                try:
                    bvid = self.raw_bv_queue.get(timeout=0.5)
                    future = executor.submit(process_one, bvid)
                    def callback(f):
                        try:
                            res = f.result()
                            if res: self.parsed_info_queue.put(res)
                        except:
                            pass
                    future.add_done_callback(callback)
                except queue.Empty:
                    continue
            pass
        self.api_pool_finished.set()

    # --- 浏览器扫描逻辑 ---
    def _scan_with_browser_queue(self, url, max_pages=1, is_search=False, is_space=False):
        bv_set = set()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                current_url = url
                page.goto(url, timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                # UP 主拦截 (仅针对关键词搜索模式)
                if is_search and "search.bilibili.com" in url:
                    try:
                        up_link = page.locator(".user-list .b-user-video-card .user-name").first
                        if up_link.is_visible():
                            up_name = up_link.inner_text()
                            up_href = up_link.get_attribute("href")
                            if up_href:
                                uid_match = re.search(r'space\.bilibili\.com/(\d+)', up_href)
                                if uid_match:
                                    uid = uid_match.group(1)
                                    self.log(f"✨ 检测到 UP 主: {up_name}...")
                                    target_video_url = f"https://space.bilibili.com/{uid}/video"
                                    page.goto(target_video_url)
                                    page.wait_for_load_state("domcontentloaded")
                                    current_url = page.url
                                    is_search = False
                                    is_space = True
                                    max_pages = 9999
                    except Exception:
                        pass
                page_count = 0
                while self.is_running and page_count < max_pages:
                    page_count += 1
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 1000)")
                        time.sleep(0.3)
                    hrefs = page.evaluate('''() => {
                        const anchors = document.querySelectorAll('a[href*="/video/BV"]');
                        return Array.from(anchors).map(a => a.href);
                    }''')
                    new_count = 0
                    for href in hrefs:
                        match = re.search(r'video/(BV\w+)', href)
                        if match:
                            bvid = match.group(1)
                            if bvid not in bv_set:
                                bv_set.add(bvid)
                                self.raw_bv_queue.put(bvid)
                                new_count += 1
                    self.log(f"   📄 第 {page_count} 页: 发现 {new_count} 个")
                    if new_count == 0:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1)
                        if new_count == 0: break
                    if page_count < max_pages:
                        next_url = None
                        if is_search:
                            base_search = re.sub(r'&page=\d+', '', current_url)
                            base_search = re.sub(r'&o=\d+', '', base_search)
                            next_page = page_count + 1
                            offset = (next_page - 1) * 30
                            next_url = f"{base_search}&page={next_page}&o={offset}"
                        elif is_space:
                            try:
                                next_btn = page.locator("button:has-text('下一页')").first
                                if next_btn.is_visible() and next_btn.is_enabled():
                                    next_btn.click()
                                    page.wait_for_timeout(2000)
                                    continue
                                else:
                                    break
                            except:
                                break
                        else:
                            try:
                                next_btn = page.locator("button.next-page, li.next").first
                                if next_btn.is_visible():
                                    next_btn.click()
                                    page.wait_for_timeout(2000)
                                    continue
                                else:
                                    break
                            except:
                                break
                        if next_url:
                            page.goto(next_url)
                            page.wait_for_timeout(2000)
                        else:
                            break
                browser.close()
        except Exception as e:
            self.log(f"⚠️ 扫描异常: {e}")

    def _clean_name(self, name):
        return re.sub(r'[\\/:*?"<>|]', '_', str(name)).strip()

    def _perform_login_scan(self, save_path):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://passport.bilibili.com/login", timeout=60000)
                self.log("⏳ 请在弹出的窗口中扫码登录...")
                for _ in range(60):
                    if not self.is_running:
                        browser.close()
                        return False
                    cookies = context.cookies()
                    if any(c['name'] == 'SESSDATA' for c in cookies):
                        with open(save_path, 'w') as f:
                            json.dump(cookies, f, indent=4, ensure_ascii=False)
                        self.log("✅ 扫码成功，Cookie 已保存")
                        browser.close()
                        self.api.load_cookies()
                        return True
                    time.sleep(1)
                browser.close()
                return False
        except Exception:
            return False