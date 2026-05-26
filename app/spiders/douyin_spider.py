import os
import json
import asyncio
import re
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

# Playwright 用于扫码登录
from playwright.sync_api import sync_playwright

# UCP 基础类
from app.spiders.base_spider import BaseSpider
from app.models import VideoItem

# ================= DouK-Downloader 核心库引入 =================
# 1. 工具与配置
from app.core.lib.douyin.tools.parameter import Parameter
# 注意：这里我们不再需要 ColorfulConsole 的实际逻辑，只需要 Parameter 引用它
from app.core.lib.douyin.tools import USERAGENT

# 2. 接口 (策略模式)
from app.core.lib.douyin.interface.search import Search
from app.core.lib.douyin.interface.detail import Detail
from app.core.lib.douyin.interface.account import Account
from app.core.lib.douyin.interface.mix import Mix
from app.core.lib.douyin.extract.extractor import Extractor
from app.core.lib.douyin.link.extractor import Extractor as LinkExtractor
from multiprocessing import Process, Queue

def _run_login_process(auth_file, user_agent, result_queue):
    """在独立进程中运行 Playwright，避免与 PyQt 线程冲突"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()

            page.goto("https://www.douyin.com/", timeout=60000)

            try:
                login_btn = page.locator("header div:has-text('登录')").last
                if login_btn.is_visible():
                    login_btn.click()
            except:
                pass

            # 轮询检测
            for _ in range(120):
                cookies = context.cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                if 'sessionid_ss' in cookie_dict:
                    # 保存文件
                    with open(auth_file, 'w', encoding='utf-8') as f:
                        json.dump(cookies, f, indent=4)
                    result_queue.put("success")
                    browser.close()
                    return
                time.sleep(1)

            result_queue.put("timeout")
            browser.close()
    except Exception as e:
        result_queue.put(str(e))
# ================= 适配器类 =================

class MockSettings:
    """模拟 DouK 的 Settings 类，用于欺骗 Parameter 初始化"""

    def __init__(self):
        pass


class MockCookie:
    """模拟 DouK 的 Cookie 类，实际 cookie 通过参数注入"""

    def __init__(self):
        self.STATE_KEY = "sessionid_ss"

    def extract(self, *args, **kwargs):
        return {}


class MockLogger:
    """将 DouK 的日志重定向到 UCP 的信号系统"""

    def __init__(self, root, console):
        self.root = root
        self.console = console

    def run(self):
        pass

    def info(self, msg, output=True, **kwargs):
        # 只有当 output=True 时才发送到 UI，避免刷屏
        if output and self.console:
            self.console.print(str(msg))

    def warning(self, msg, output=True, **kwargs):
        if output and self.console:
            self.console.warning(str(msg))

    def error(self, msg, output=True, **kwargs):
        if output and self.console:
            self.console.error(str(msg))

    def debug(self, msg, **kwargs):
        # 调试信息默认不发送到 UI，防止卡死
        pass


class SignalConsole:
    """
    [CRITICAL FIX]
    完全重写的控制台适配器。
    绝不能继承 rich.console.Console，否则在 QThread 中会导致 0xC0000409 栈溢出崩溃。
    这里只实现 Parameter 类需要的接口。
    """

    def __init__(self, signal_func):
        self.signal_func = signal_func

    def print(self, *args, **kwargs):
        # 过滤掉 rich 的样式参数，只保留内容
        msg = " ".join(str(a) for a in args)
        self.signal_func(msg)

    def info(self, *args, **kwargs):
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"[INFO] {msg}")

    def warning(self, *args, **kwargs):
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"⚠️ {msg}")

    def error(self, *args, **kwargs):
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"❌ {msg}")

    def debug(self, *args, **kwargs):
        pass

    def input(self, prompt="", **kwargs):
        # 爬虫模式下不支持控制台输入，直接返回空
        return ""


class DouyinSpider(BaseSpider):
    AUTH_FILE = "dy_auth.json"

    def run(self):
        # [修改] 确保 multiprocessing 支持打包环境
        # try:
        #     from multiprocessing import freeze_support
        #     freeze_support()
        # except: pass

        self.log(f"🚀 启动抖音任务 | 目标: {self.keyword}")

        cookie_str = self._load_or_login()
        if not self.is_running: return
        if not cookie_str:
            self.log("❌ 无法获取 Cookie，任务终止")
            self.sig_finished.emit()
            return

        try:
            asyncio.run(self._async_main(cookie_str))
        except Exception as e:
            self.log(f"💥 运行时异常: {e}")
            import traceback
            print(traceback.format_exc())
        finally:
            self.sig_finished.emit()

    def _load_or_login(self) -> str:
        if os.path.exists(self.AUTH_FILE):
            try:
                with open(self.AUTH_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                    cookie_dict = {c['name']: c['value'] for c in cookies}
                    if 'sessionid_ss' in cookie_dict:
                        self.log("👤 加载本地 Cookie 成功")
                        return self._cookies_to_str(cookies)
            except:
                pass

        self.log("🔒 未登录或 Cookie 失效，启动扫码...")
        return self._perform_scan_login()

    def _perform_scan_login(self) -> str:
        # [修改] 使用多进程隔离 Playwright
        self.log("🔗 正在启动独立登录进程...")

        result_queue = Queue()
        # 注意：这里不能传递 self.log 或 self，因为它们包含 PyQt 对象，无法被 pickle
        p = Process(target=_run_login_process, args=(self.AUTH_FILE, USERAGENT, result_queue))
        p.start()

        # 等待进程结束，同时保持响应停止信号
        while p.is_alive():
            if not self.is_running:
                p.terminate()
                return ""
            p.join(timeout=1)

        # 获取结果
        if not result_queue.empty():
            res = result_queue.get()
            if res == "success":
                self.log("✅ 登录成功！")
                # 重新读取文件
                try:
                    with open(self.AUTH_FILE, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                    return self._cookies_to_str(cookies)
                except:
                    return ""
            else:
                self.log(f"❌ 登录失败: {res}")
                return ""
        else:
            self.log("❌ 登录进程异常退出")
            return ""

    def _cookies_to_str(self, cookies_list: list) -> str:
        return "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
    
    async def _async_main(self, cookie_str: str):
        # 1. 初始化 DouK Parameter (上帝对象)
        console_adapter = SignalConsole(self.log)
        settings_mock = MockSettings()

        proxy_str = self.config.get("proxy", "")

        # [优化] 提供符合校验规则的默认值，消除 Warning
        params = Parameter(
            settings=settings_mock,
            cookie_object=MockCookie(),
            logger=MockLogger,
            console=console_adapter,
            cookie=cookie_str,
            cookie_tiktok="",
            root="",
            accounts_urls=[], accounts_urls_tiktok=[], mix_urls=[], mix_urls_tiktok=[],
            folder_name="Download",  # 有效文件夹名
            name_format="create_time type nickname desc",  # 有效格式
            desc_length=64,  # >= 16
            name_length=128,  # >= 32
            date_format="%Y-%m-%d %H:%M:%S",
            split="-",
            music=False, folder_mode=False,
            truncate=50,  # >= 25
            storage_format="",
            dynamic_cover=False, static_cover=False,
            proxy=proxy_str, proxy_tiktok="", twc_tiktok="",
            download=False, max_size=0,
            chunk=1024 * 1024,  # >= 128KB
            max_retry=3, max_pages=9999,  # max_pages > 0
            run_command="", owner_url={}, owner_url_tiktok={},
            live_qualities="", ffmpeg="", recorder=None,
            browser_info={}, browser_info_tiktok={}
        )

        # 更新参数 (获取 ttwid, msToken)
        await params.update_params()

        # 2. 智能路由解析
        raw_text = self.keyword.strip()
        link_extractor = LinkExtractor(params)

        resolved_links = []
        if "http" in raw_text:
            self.log("🔍 正在解析链接重定向...")

            if "user/" in raw_text:
                res = await link_extractor.run(raw_text, type_="user")
                if res:
                    for sec_uid in res:
                        await self._process_user(params, sec_uid)
                return

            elif "collection/" in raw_text or "mix/" in raw_text:
                # 合集
                is_mix, ids = link_extractor.mix(await link_extractor.requester.run(raw_text))
                if is_mix and ids:
                    mix_id = ids[0]
                    await self._process_mix(params, mix_id)
                return

            elif "modal_id=" in raw_text:
                # 可能是搜索页/发现页带 modal_id 的链接
                # 先尝试作为作品解析
                res = await link_extractor.run(raw_text, type_="detail")
                if res:
                    await self._process_detail(params, res)
                else:
                    # 如果解析失败，可能是合集链接，尝试提取 modal_id 作为 mix_id
                    import re
                    match = re.search(r'modal_id=(\d{19})', raw_text)
                    if match:
                        modal_id = match.group(1)
                        self.log(f"🔍 尝试将 modal_id {modal_id} 作为合集解析...")
                        await self._process_mix(params, modal_id)
                    else:
                        self.log("⚠️ 无法识别的链接格式")
                return

            else:
                # 默认为作品 (Video/Note)
                res = await link_extractor.run(raw_text, type_="detail")
                if res:
                    await self._process_detail(params, res)
                else:
                    self.log("⚠️ 无法识别的链接格式")
                return

        else:
            # 智能判断输入类型
            if raw_text.isdigit():
                self.log(f"⚠️ 纯数字 UID 暂不支持直接搜索")
                self.log("💡 请使用以下格式：")
                self.log("   • 用户主页链接: https://www.douyin.com/user/MS4w...")
                self.log("   • 视频链接: https://www.douyin.com/video/1234567890")
                self.log("   • 合集链接: https://www.douyin.com/collection/1234567890")
                self.log("   • 分享链接: https://v.douyin.com/xxxxx")
                self.log("   • 用户昵称（中文/英文）")
                return
            elif raw_text.isalnum() and len(raw_text) <= 20 and ' ' not in raw_text:
                self.log(f"👤 识别为可能的抖音号: {raw_text}，尝试搜索...")
                await self._process_user_search(params, raw_text)
            else:
                # 关键词搜索
                await self._process_search(params, raw_text)

    async def _process_detail(self, params, ids: list):
        self.log(f"🎬 识别到 {len(ids)} 个作品 ID，开始获取详情...")
        api = Detail(params, detail_id=ids[0])

        all_items = []
        for vid in ids:
            if not self.is_running: break
            api.detail_id = vid
            data = await api.run(single_page=True, data_key="aweme_detail")
            if data:
                item = self._extract_to_video_item(data)
                if item:
                    all_items.append(item)

        if not all_items:
            self.log("❌ 获取作品详情失败")
            return

        # 单个作品直接下载，多个作品让用户选择
        if len(all_items) == 1:
            self._submit_tasks(all_items)
        else:
            self._handle_selection(all_items, "分享链接作品")

    async def _process_user(self, params, sec_uid: str):
        self.log(f"👤 识别到用户 SecUID: {sec_uid}，开始爬取主页...")
        account_api = Account(params, sec_user_id=sec_uid)

        all_data = []
        page = 0
        # [修复] 使用 finished 属性判断循环，而不是 has_more
        while self.is_running and not account_api.finished:
            page += 1
            self.log(f"📄 正在获取第 {page} 页...")

            await account_api.run_single()

            if not account_api.response:
                break

            raw_list = account_api.response
            account_api.response = []

            batch_items = []
            for aweme in raw_list:
                item = self._extract_to_video_item(aweme)
                if item: batch_items.append(item)

            all_data.extend(batch_items)
            await asyncio.sleep(1)

        if not all_data:
            self.log("❌ 未找到公开作品")
            return

        self._handle_selection(all_data, f"用户 {sec_uid} 的作品")

    async def _process_mix(self, params, mix_id: str):
        self.log(f"📀 识别到合集 ID: {mix_id}")
        mix_api = Mix(params, mix_id=mix_id)

        # [DEBUG] 保存第一页原始数据（调试时取消注释）
        # debug_saved = False

        all_data = []
        mix_title = None

        # [修复] 使用 finished 属性判断循环，调用 run_single 时传入 data_key
        while self.is_running and not mix_api.finished:
            await mix_api.run_single(data_key="aweme_list")
            raw_list = mix_api.response

            # [DEBUG] 保存第一页原始响应，并提取合集名称（调试时取消注释）
            # if not debug_saved and raw_list:
            #     try:
            #         import json
            #         debug_file = f"debug_mix_{mix_id}.json"
            #         with open(debug_file, 'w', encoding='utf-8') as f:
            #             json.dump(raw_list, f, ensure_ascii=False, indent=2)
            #         self.log(f"📝 [DEBUG] 已保存合集原始数据: {debug_file}")
            #         debug_saved = True
            #     except Exception as e:
            #         self.log(f"⚠️ [DEBUG] 保存失败: {e}")

            # 提取合集名称
            if mix_title is None and raw_list and isinstance(raw_list, list) and len(raw_list) > 0:
                first_item = raw_list[0]
                mix_info = first_item.get('mix_info') or first_item.get('aweme_mix_info', {})
                if mix_info:
                    mix_title = mix_info.get('mix_name') or mix_info.get('name')

            mix_api.response = []

            for aweme in raw_list:
                item = self._extract_to_video_item(aweme)
                if item:
                    # 标记为合集作品，设置合集名称作为文件夹名
                    item.meta['is_mix'] = True
                    item.meta['mix_title'] = mix_title or f"合集_{mix_id}"
                    item.meta['folder_name'] = mix_title or f"合集_{mix_id}"
                    all_data.append(item)

            await asyncio.sleep(0.5)

        if not all_data:
            self.log(f"❌ 合集 {mix_id} 未找到作品或ID无效")
            return

        self._handle_selection(all_data, f"合集 {mix_title or mix_id}")

    async def _process_search(self, params, keyword: str):
        max_pages = self.config.get("search_max_pages", 1)
        self.log(f"🔍 搜索关键词: {keyword} (最大 {max_pages} 页)")

        search_api = Search(params, keyword=keyword, type=0)  # 0=综合

        all_data = []
        for i in range(max_pages):
            if not self.is_running: break
            self.log(f"   📄 搜索第 {i + 1} 页...")

            await search_api.run_single(data_key="data")

            raw_list = search_api.response
            search_api.response = []

            if not raw_list: break

            for item in raw_list:
                if 'aweme_info' in item:
                    vid = self._extract_to_video_item(item['aweme_info'])
                    if vid: all_data.append(vid)

            # [修复] 使用 finished 属性判断
            if search_api.finished: break
            await asyncio.sleep(1)

        self._handle_selection(all_data, f"搜索: {keyword}")

    async def _process_user_search(self, params, user_id: str):
        """通过用户ID/抖音号搜索用户，然后获取用户主页作品"""
        from app.core.lib.douyin.interface.search import Search
        from app.core.lib.douyin.interface.user import User
        from app.core.lib.douyin.link.extractor import Extractor as LinkExtractor
        
        self.log(f"🔍 正在搜索用户: {user_id}")
        
        # 方法1: 尝试直接访问用户主页 (抖音号)
        # 抖音用户主页格式: https://www.douyin.com/user/MS4wLjABAAAA... (sec_user_id)
        # 或者: https://v.douyin.com/xxx/ (短链)
        
        # 方法2: 使用用户搜索
        try:
            search_api = Search(params, keyword=user_id, channel=2)  # 2=用户搜索
            await search_api.run(single_page=True)
        except Exception as e:
            import traceback
            self.log(f"❌ 搜索异常: {e}")
            traceback.print_exc()
            return
        
        raw_list = search_api.response
        
        # [DEBUG] 保存搜索 API 返回的原始数据（调试时取消注释）
        # try:
        #     import json
        #     debug_file = f"debug_search_{user_id}.json"
        #     with open(debug_file, 'w', encoding='utf-8') as f:
        #         json.dump({
        #             'user_id': user_id,
        #             'response': raw_list,
        #             'response_type': str(type(raw_list)),
        #             'response_len': len(raw_list) if raw_list else 0
        #         }, f, ensure_ascii=False, indent=2)
        #     self.log(f"📝 [DEBUG] 已保存搜索 API 返回: {debug_file}")
        # except Exception as e:
        #     self.log(f"⚠️ [DEBUG] 保存失败: {e}")
        
        # 检查是否有搜索结果
        if raw_list and len(raw_list) > 0 and raw_list[0]:
            # 有搜索结果，解析用户信息
            self.log(f"✅ 找到 {len(raw_list)} 个匹配用户")
            
            users = []
            for item in raw_list:
                if 'user_info' in item:
                    user_info = item['user_info']
                    users.append({
                        'sec_uid': user_info.get('sec_uid'),
                        'nickname': user_info.get('nickname', 'Unknown'),
                        'uid': user_info.get('uid', ''),
                        'follower_count': user_info.get('follower_count', 0),
                        'aweme_count': user_info.get('aweme_count', 0),
                    })
            
            if users:
                # 如果只找到一个用户，直接获取其作品
                if len(users) == 1:
                    user = users[0]
                    self.log(f"👤 找到用户: {user['nickname']} (粉丝: {user['follower_count']}, 作品: {user['aweme_count']})")
                    await self._process_user(params, user['sec_uid'])
                else:
                    # 多个用户，让用户选择
                    display_items = []
                    for i, u in enumerate(users[:10]):
                        display_items.append({
                            'title': f"{u['nickname']} (粉丝: {u['follower_count']}, 作品: {u['aweme_count']})",
                            'index': i
                        })
                    
                    self.log(f"🔔 找到多个用户，请选择...")
                    selected_indices = self.ask_user_selection(display_items)
                    
                    if not selected_indices:
                        self.log("❌ 用户取消选择")
                        return
                    
                    for idx in selected_indices:
                        user = users[idx]
                        self.log(f"👤 获取用户: {user['nickname']}")
                        await self._process_user(params, user['sec_uid'])
                return
        
        # 搜索无结果，尝试其他方法
        self.log("⚠️ 用户搜索无结果，尝试其他方法...")
        
        # 方法3: 尝试通过 User API 直接获取 (如果输入的是 sec_user_id)
        if len(user_id) > 30:  # sec_user_id 通常较长
            self.log(f"🔑 尝试作为 sec_user_id 访问...")
            await self._process_user(params, user_id)
            return
        
        # 方法4: 尝试通过请求用户主页 HTML 提取 sec_user_id
        # 注意：抖音是 SPA，纯 HTTP 请求拿不到渲染数据，此方法仅对短链有效
        try:
            self.log(f"🔑 尝试请求用户主页获取 sec_user_id...")
            import httpx
            test_url = f"https://www.douyin.com/user/{user_id}"
            
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.douyin.com/",
                    "Cookie": params.cookie_str
                },
                timeout=30,
                follow_redirects=True
            ) as client:
                resp = await client.get(test_url)
                resp.raise_for_status()
                html = resp.text
            
            # 从 HTML 中提取 sec_user_id（仅对包含 RENDER_DATA 的页面有效）
            import re
            match = re.search(r'"secUid":"([^"]+)"', html)
            if match:
                sec_uid = match.group(1)
                self.log(f"✅ 从 HTML 提取到 sec_user_id: {sec_uid[:20]}...")
                await self._process_user(params, sec_uid)
                return
                    
        except Exception as e:
            self.log(f"⚠️ 主页请求失败: {e}")
        
        self.log(f"❌ 无法找到用户 '{user_id}'")
        self.log("💡 抖音纯数字 UID 无法直接搜索，请使用以下方式：")
        self.log("   1. 输入用户主页链接（如 https://www.douyin.com/user/MS4w...）")
        self.log("   2. 输入用户昵称进行搜索")
        self.log("   3. 在抖音 APP 中复制分享链接")

    def _extract_to_video_item(self, data: dict) -> Optional[VideoItem]:
        """将 Douyin 原始 JSON 转换为 VideoItem
        
        支持三种内容类型：
        1. 视频 (aweme_type=0, media_type=4): video.play_addr 是 MP4
        2. 图集 (aweme_type=68, media_type=2): images 数组，纯静态图片
        3. 实况/轮播 (aweme_type=68, media_type=42): images 数组，部分图片 clip_type=3（实况=短视频+静态图）
        """
        try:
            # 1. 基础信息
            aweme_id = data.get('aweme_id', 'unknown')
            desc = data.get('desc', aweme_id)
            create_time = data.get('create_time', 0)
            author = data.get('author', {}).get('nickname', 'Unknown')

            # 2. 视频地址 (无水印)
            video_url = ""
            if 'video' in data and 'play_addr' in data['video']:
                url_list = data['video']['play_addr'].get('url_list', [])
                if url_list:
                    video_url = url_list[-1]

            # 3. 检查 video_url 是否是真正的视频（不是MP3音频）
            is_real_video = video_url and '.mp3' not in video_url.lower()

            # 4. 解析 images 数组（图集/实况）
            images_data = []
            has_live_photo = False
            if 'images' in data and data['images']:
                for img in data['images']:
                    clip_type = img.get('clip_type', 2)
                    # 获取图片URL - 优先 url_list 中的 ~noop 链接（无水印）
                    # download_url_list 带水印，url_list 中的 ~noop 无水印
                    img_url = ""
                    url_list = img.get('url_list') or []
                    for url in url_list:
                        if '~noop' in url:
                            img_url = url
                            break
                    # 如果没有 noop 链接，取 url_list 最后一个
                    if not img_url and url_list:
                        img_url = url_list[-1]

                    # 获取实况视频URL（clip_type=3 表示实况照片）
                    live_video_url = ""
                    if clip_type == 3 and 'video' in img:
                        live_addr = img['video'].get('play_addr_h264') or img['video'].get('play_addr')
                        if live_addr:
                            live_urls = live_addr.get('url_list', [])
                            if live_urls:
                                live_video_url = live_urls[-1]
                                has_live_photo = True

                    images_data.append({
                        'image_url': img_url,
                        'live_video_url': live_video_url,
                        'clip_type': clip_type,
                    })

            # 5. 提取视频时长（毫秒）
            duration_ms = 0
            if 'video' in data:
                duration_ms = data['video'].get('duration', 0)

            # 6. 构建对象
            if is_real_video and not images_data:
                # ====== 类型1: 纯视频 ======
                item = VideoItem(url=video_url, title=desc, source="douyin")
                item.meta = {
                    "content_type": "video",
                    "media_label": "视频",
                    "aweme_id": aweme_id,
                    "create_time": create_time,
                    "author": author,
                    "folder_name": author,
                    "duration": duration_ms // 1000,  # 转换为秒
                }
                return item

            elif images_data:
                # ====== 类型2/3: 图集 或 实况轮播 ======
                media_label = "实况" if has_live_photo else "图集"

                item = VideoItem(url=images_data[0]['image_url'], title=desc, source="douyin")
                item.meta = {
                    "content_type": "gallery",
                    "media_label": media_label,
                    "is_gallery": True,
                    "has_live_photo": has_live_photo,
                    "images_data": images_data,  # 完整的图片数据（含实况视频URL）
                    "aweme_id": aweme_id,
                    "create_time": create_time,
                    "author": author,
                    "folder_name": author,
                }
                return item

        except Exception:
            import traceback
            traceback.print_exc()
        return None

    def _handle_selection(self, items: list[VideoItem], title_hint: str):
        if not items:
            self.log("❌ 未找到有效视频")
            return

        display_items = []
        for i, vid in enumerate(items):
            display_items.append({
                'title': vid.title,
                'index': i
            })

        self.log(f"🔔 {title_hint} - 扫描完成，共 {len(items)} 个，请选择...")

        selected_indices = self.ask_user_selection(display_items)

        if not selected_indices:
            self.log("❌ 用户取消下载")
            return

        self.log(f"✅ 选中 {len(selected_indices)} 个任务")

        final_items = [items[i] for i in selected_indices]
        self._submit_tasks(final_items)

    def _submit_tasks(self, items: list[VideoItem]):
        for item in items:
            if item.meta.get("is_gallery"):
                # 使用新的 images_data 字段
                images_data = item.meta.get('images_data', [])
                base_title = item.title
                for idx, img_info in enumerate(images_data):
                    img_url = img_info.get('image_url', '')
                    live_url = img_info.get('live_video_url', '')
                    seq = idx + 1

                    # 实况照片：只下载视频
                    if live_url:
                        live_item = VideoItem(
                            url=live_url,
                            title=f"{base_title}_{seq}",
                            source="douyin"
                        )
                        live_item.meta = item.meta.copy()
                        live_item.meta['is_gallery'] = False
                        live_item.meta['content_type'] = 'video'
                        live_item.meta['media_label'] = '实况'
                        self.sig_item_found.emit(live_item)
                    # 普通图集：只下载图片
                    elif img_url:
                        sub_item = VideoItem(
                            url=img_url,
                            title=f"{base_title}_{seq}",
                            source="douyin"
                        )
                        sub_item.meta = item.meta.copy()
                        sub_item.meta['is_gallery'] = False
                        sub_item.meta['content_type'] = 'image'
                        sub_item.meta['media_label'] = '图集'
                        self.sig_item_found.emit(sub_item)
            else:
                self.sig_item_found.emit(item)