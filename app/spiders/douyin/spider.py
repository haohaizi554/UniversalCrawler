"""爬虫实现模块，负责 `app/spiders/douyin/spider.py` 对应平台的采集、解析或任务装配逻辑。"""

import os
import json
import asyncio
import math
import queue as queue_module
import re
import time
import httpx
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

# Playwright 用于扫码登录
from playwright.sync_api import Error as PlaywrightError, sync_playwright

# UCP 基础类
from app.config import cfg, get_setting_default
from app.debug_logger import debug_logger
from app.exceptions import InvalidCookieStateError, LoginCancelledError, LoginTimeoutError, SpiderAuthError
from app.spiders.base import BaseSpider
from app.spiders.douyin.parser import DouyinItemParser
from app.spiders.douyin.task_builder import DouyinTaskBuilder
from app.models import VideoItem
from app.services.auth_service import AuthService
from app.core.anti_detection import build_browser_anti_detection

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

def _run_login_process(auth_file, user_agent, result_queue, proxy_server=None, timeout_ms=60000):
    """在独立进程中运行 Playwright，避免与 PyQt 线程冲突"""
    import os
    import traceback
    browser = None
    try:
        auth_service = AuthService()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            anti_context = build_browser_anti_detection(
                "douyin",
                {"ua": user_agent, "proxy": proxy_server},
                referer="https://www.douyin.com/",
                default_user_agent=user_agent,
                viewport={"width": 1280, "height": 800},
            )
            launch_kwargs = anti_context.browser_launch_kwargs(headless=False)
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(**anti_context.browser_context_kwargs())
            anti_context.apply_to_context(context)
            page = context.new_page()

            page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=timeout_ms)

            try:
                login_btn = page.locator("header div:has-text('登录')").last
                if login_btn.is_visible():
                    login_btn.click()
            except PlaywrightError:
                pass

            # 轮询检查登录态，一旦拿到核心 Cookie 就立即持久化并返回主进程。
            for _ in range(120):
                cookies = context.cookies()
                if auth_service.has_cookie(cookies, "sessionid_ss"):
                    try:
                        # 确保目录存在
                        directory = os.path.dirname(auth_file)
                        if directory:
                            os.makedirs(directory, exist_ok=True)
                        auth_service.save_json_file(auth_file, cookies)
                        result_queue.put("success")
                    except Exception as save_err:
                        err_msg = f"Cookie保存失败: {save_err} (路径: {auth_file})"
                        result_queue.put(err_msg)
                    finally:
                        if browser:
                            browser.close()
                    return
                time.sleep(1)

            result_queue.put("timeout")
            if browser:
                browser.close()
    except Exception as e:
        err_msg = f"登录进程异常: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        result_queue.put(err_msg)
    finally:
        if browser:
            try:
                browser.close()
            except (PlaywrightError, RuntimeError, AttributeError) as exc:
                debug_logger.log_exception("DouyinLoginProcess", "close_browser", exc)
# ================= 适配器类 =================

class MockSettings:
    """模拟 DouK 的 Settings 类，用于欺骗 Parameter 初始化"""

    def __init__(self):
        """提供最小化的设置对象占位符，满足底层参数对象初始化。"""
        pass

class MockCookie:
    """模拟 DouK 的 Cookie 类，实际 cookie 通过参数注入"""

    def __init__(self):
        """声明 DouK 侧登录态检查依赖的关键 Cookie 名称。"""
        self.STATE_KEY = "sessionid_ss"

    def extract(self, *args, **kwargs):
        """返回空结果，真实 Cookie 由外部参数直接注入。"""
        return {}

class MockLogger:
    """将 DouK 的日志重定向到 UCP 的信号系统"""

    def __init__(self, root, console):
        """保存控制台适配器，供底层库把日志转发到 UI。"""
        self.root = root
        self.console = console

    def run(self):
        """兼容底层库的调用约定，这里无需额外启动动作。"""
        pass

    def info(self, msg, output=True, **kwargs):
        # 只有当 output=True 时才发送到 UI，避免刷屏
        """把普通日志按需转发到界面，避免高频无效输出刷屏。"""
        if output and self.console:
            self.console.print(str(msg))

    def warning(self, msg, output=True, **kwargs):
        """把警告日志转发到界面。"""
        if output and self.console:
            self.console.warning(str(msg))

    def error(self, msg, output=True, **kwargs):
        """把错误日志转发到界面。"""
        if output and self.console:
            self.console.error(str(msg))

    def debug(self, msg, **kwargs):
        # 调试信息默认不发送到 UI，防止卡死
        """保留调试方法签名，但默认不把细碎日志推给界面。"""
        pass

class SignalConsole:
    """
    [CRITICAL FIX]
    完全重写的控制台适配器。
    绝不能继承 rich.console.Console，否则在 QThread 中会导致 0xC0000409 栈溢出崩溃。
    这里只实现 Parameter 类需要的接口。
    """

    def __init__(self, signal_func):
        """保存一个可直接写入 UI 的信号函数。"""
        self.signal_func = signal_func

    def print(self, *args, **kwargs):
        # 过滤掉 rich 的样式参数，只保留内容
        """把控制台普通输出转换成纯文本并发送给界面。"""
        msg = " ".join(str(a) for a in args)
        self.signal_func(msg)

    def info(self, *args, **kwargs):
        """输出带信息前缀的日志。"""
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"[INFO] {msg}")

    def warning(self, *args, **kwargs):
        """输出带警告前缀的日志。"""
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"⚠️ {msg}")

    def error(self, *args, **kwargs):
        """输出带错误前缀的日志。"""
        msg = " ".join(str(a) for a in args)
        self.signal_func(f"❌ {msg}")

    def debug(self, *args, **kwargs):
        """保留调试输出接口，但默认不额外向界面发送内容。"""
        pass

    def input(self, prompt="", **kwargs):
        # 爬虫模式下不支持控制台输入，直接返回空
        """兼容底层交互接口，爬虫线程中始终返回空输入。"""
        return ""

class DouyinSpider(BaseSpider):
    """抖音爬虫，负责扫码登录、路由解析和任务装配。"""

    def __init__(self, keyword: str, config: dict):
        """初始化抖音爬虫依赖的解析器、任务装配器与认证服务。"""
        super().__init__(keyword, config)
        self.parser = DouyinItemParser()
        self.task_builder = DouyinTaskBuilder()
        self.auth_service = AuthService()
        self.auth_file = cfg.get(
            "auth",
            "douyin_cookie_file",
            get_setting_default("auth", "douyin_cookie_file"),
        )

    def _max_items_limit(self) -> int:
        """读取最大资源数限制，并对非法配置做兜底。"""
        default_limit = get_setting_default("douyin", "max_items")
        limit = self.config.get("max_items", cfg.get("douyin", "max_items", default_limit))
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return int(default_limit)

    def _trim_items(self, items: list[VideoItem], title_hint: str) -> list[VideoItem]:
        """按配置裁剪候选资源数量，避免一次性把过多条目丢给 UI。"""
        limit = self._max_items_limit()
        if limit >= 9999 or len(items) <= limit:
            return items
        self.log(f"ℹ️ {title_hint} 共 {len(items)} 个，仅保留前 {limit} 个供选择")
        return items[:limit]

    def run(self):
        # [修改] 确保 multiprocessing 支持打包环境
        # try:
        #     from multiprocessing import freeze_support
        #     freeze_support()
        # except: pass

        """完成登录态准备后启动异步主流程，并在结束时统一发出完成信号。"""
        self.log(f"🚀 启动抖音任务 | 目标: {self.keyword}")
        self.debug_state(
            action="run_start",
            message="启动抖音爬虫任务",
            status_code="DOUYIN_SPIDER_START",
            context={"keyword": self.keyword},
            details={"config": self.config},
        )

        try:
            cookie_str = self._load_or_login()
        except SpiderAuthError as exc:
            self.log(f"❌ 登录失败: {exc}")
            self._emit_finished()
            return
        # 登录过程中可能已经被用户取消，这里需要在真正发请求前再次检查运行状态。
        if not self.is_running:
            self._emit_finished()
            return
        if not cookie_str:
            self.log("❌ 无法获取 Cookie，任务终止")
            self._emit_finished()
            return

        try:
            asyncio.run(self._async_main(cookie_str))
        except (RuntimeError, OSError, ValueError, TypeError, KeyError) as e:
            self.log(f"💥 运行时异常: {e}")
            self.debug_state(
                action="run_error",
                message="抖音爬虫运行异常",
                status_code="DOUYIN_RUNTIME_ERROR",
                details={"error": str(e)},
            )
            print(traceback.format_exc())
        finally:
            self.debug_state(
                action="run_finish",
                message="抖音爬虫任务结束",
                status_code="DOUYIN_SPIDER_FINISH",
            )
            self._emit_finished()

    def _load_or_login(self) -> str:
        """优先复用本地 Cookie，失效后再回退到扫码登录。"""
        self.log(f"🔍 检查本地 Cookie 文件: {self.auth_file}")
        if os.path.exists(self.auth_file):
            try:
                cookies = self.auth_service.load_json_file(self.auth_file)
                if not cookies:
                    self.log("⚠️ Cookie 文件存在但内容为空")
                    raise InvalidCookieStateError("Cookie 文件为空")
                cookie_str = self.auth_service.build_cookie_string(cookies, required_cookie="sessionid_ss")
                if cookie_str:
                    self.log(f"👤 加载本地 Cookie 成功 (sessionid_ss 有效)")
                    return cookie_str
                self.log("⚠️ 本地 Cookie 缺少 sessionid_ss，可能已过期")
                raise InvalidCookieStateError("本地抖音 Cookie 缺少 sessionid_ss")
            except SpiderAuthError:
                pass
            except Exception as exc:
                self.log(f"⚠️ 加载本地 Cookie 失败: {exc}")
        else:
            self.log(f"⚠️ Cookie 文件不存在: {self.auth_file}")

        self.log("🔒 未登录或 Cookie 失效，启动扫码...")
        return self._perform_scan_login()

    def _perform_scan_login(self) -> str:
        # 登录页单独放到子进程里跑，避免 Playwright 和 Qt 线程模型互相干扰。
        """在独立进程中执行扫码登录，并把结果回传给当前线程。"""
        self.log("🔗 正在启动独立登录进程...")
        self.log(f"📝 Cookie 将保存到: {self.auth_file}")

        result_queue = Queue()
        # 注意：这里不能传递 self.log 或 self，因为它们包含 PyQt 对象，无法被 pickle。
        proxy_server = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
        p = Process(
            target=_run_login_process,
            args=(self.auth_file, USERAGENT, result_queue, proxy_server, self._configured_timeout_ms(default=60)),
        )
        p.start()

        # 等待进程结束，同时保持响应停止信号。
        while p.is_alive():
            if not self.is_running:
                p.terminate()
                p.join(timeout=2)
                self._close_login_result_queue(result_queue)
                raise LoginCancelledError("用户在登录过程中终止任务")
            p.join(timeout=1)

        try:
            # multiprocessing.Queue.empty() is explicitly unreliable between
            # processes; read with a short timeout so a just-flushed child result
            # is not mistaken for "no return value".
            res = result_queue.get(timeout=2)
        except queue_module.Empty as exc:
            exitcode = getattr(p, "exitcode", None)
            exit_part = f", exitcode={exitcode}" if exitcode is not None else ""
            raise SpiderAuthError(f"登录进程异常退出 (无返回结果{exit_part})") from exc
        finally:
            self._close_login_result_queue(result_queue)

        if res == "success":
            self.log("✅ 扫码登录成功！")
            # 重新读取文件
            try:
                cookies = self.auth_service.load_json_file(self.auth_file)
                if not cookies:
                    self.log("⚠️ 登录成功但 Cookie 文件为空")
                    return ""
                cookie_str = self.auth_service.build_cookie_string(cookies, required_cookie="sessionid_ss")
                if cookie_str:
                    self.log("👤 Cookie 读取成功，可以开始下载")
                    return cookie_str
                self.log("⚠️ 登录成功但 Cookie 缺少 sessionid_ss")
                return ""
            except SpiderAuthError as exc:
                self.log(f"❌ 登录态读取失败: {exc}")
                return ""
        if res == "timeout":
            raise LoginTimeoutError("等待抖音扫码登录超时 (120秒)")
        # res 包含具体的错误信息
        self.log(f"❌ 登录失败详情: {res}")
        raise SpiderAuthError(f"抖音登录失败: {res}")

    @staticmethod
    def _close_login_result_queue(result_queue) -> None:
        for method_name in ("close", "join_thread"):
            method = getattr(result_queue, method_name, None)
            if not callable(method):
                continue
            try:
                method()
            except (OSError, RuntimeError, ValueError, AttributeError):
                pass

    def _cookies_to_str(self, cookies_list: list) -> str:
        """把 Cookie 列表拼接成请求头可直接使用的字符串。"""
        return "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])

    def _build_runtime_params(self, cookie_str: str):
        """构造 DouK 运行参数，统一集中在一个入口便于后续继续拆分。"""
        console_adapter = SignalConsole(self.log)
        settings_mock = MockSettings()
        proxy_str = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy")) or ""
        return Parameter(
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
            chunk=1024 * 1024,
            max_retry=3, max_pages=9999,
            run_command="", owner_url={}, owner_url_tiktok={},
            live_qualities="", ffmpeg="", recorder=None,
            browser_info={}, browser_info_tiktok={},
        )

    async def _route_input(self, params, raw_text: str, link_extractor) -> None:
        """根据输入内容选择作品、合集、用户主页或关键词搜索路径。"""
        if "http" in raw_text:
            self.log("🔍 正在解析链接重定向...")

            if "user/" in raw_text:
                res = await link_extractor.run(raw_text, type_="user")
                if res:
                    for sec_uid in res:
                        await self._process_user(params, sec_uid)
                return

            if "collection/" in raw_text or "mix/" in raw_text:
                is_mix, ids = link_extractor.mix(await link_extractor.requester.run(raw_text))
                if is_mix and ids:
                    await self._process_mix(params, ids[0])
                return

            if "modal_id=" in raw_text:
                await self._handle_modal_link(params, raw_text, link_extractor)
                return

            await self._handle_detail_link(params, raw_text, link_extractor)
            return

        if raw_text.isdigit():
            self._log_unsupported_numeric_uid()
            return

        if raw_text.isalnum() and len(raw_text) <= 20 and ' ' not in raw_text:
            self.log(f"👤 识别为可能的抖音号: {raw_text}，尝试搜索...")
            await self._process_user_search(params, raw_text)
            return

        await self._process_search(params, raw_text)

    async def _handle_modal_link(self, params, raw_text: str, link_extractor) -> None:
        """优先按作品详情解析，失败后再把 `modal_id` 当作合集 ID 处理。"""
        res = await self._resolve_detail_link(link_extractor, raw_text)
        if res:
            await self._process_detail(params, res)
            return
        match = re.search(r'modal_id=(\d{19})', raw_text)
        if match:
            modal_id = match.group(1)
            self.log(f"🔍 尝试将 modal_id {modal_id} 作为合集解析...")
            await self._process_mix(params, modal_id)
            return
        self.log("⚠️ 无法识别的链接格式")

    async def _handle_detail_link(self, params, raw_text: str, link_extractor) -> None:
        """解析普通作品详情链接，并把结果交给详情处理流程。"""
        res = await self._resolve_detail_link(link_extractor, raw_text)
        if res:
            await self._process_detail(params, res)
            return
        self.log("⚠️ 无法识别的链接格式")

    async def _resolve_detail_link(self, link_extractor, raw_text: str):
        """统一处理详情链接解析，避免 modal/detail 分支各自重复请求。"""
        return await link_extractor.run(raw_text, type_="detail")

    def _log_unsupported_numeric_uid(self) -> None:
        """提示用户当前不支持直接按纯数字 UID 抓取抖音账号。"""
        self.log("⚠️ 纯数字 UID 暂不支持直接搜索")
        self.log("💡 请使用以下格式：")
        self.log("   • 用户主页链接: https://www.douyin.com/user/MS4w...")
        self.log("   • 分享链接: https://v.douyin.com/xxxxx")

    async def _async_main(self, cookie_str: str):
        self._active_douyin_params = None
        try:
            await self._async_main_body(cookie_str)
        finally:
            params = getattr(self, "_active_douyin_params", None)
            if params is not None:
                close_result = params.close_client()
                if hasattr(close_result, "__await__"):
                    await close_result
                self._active_douyin_params = None

    async def _async_main_body(self, cookie_str: str):
        """根据输入自动分流到作品、合集、用户主页或关键词搜索。"""
        params = self._build_runtime_params(cookie_str)
        self._active_douyin_params = params
        proxy_str = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy")) or ""

        await params.update_params()
        self.debug_state(
            action="params_ready",
            message="Douyin 参数初始化完成",
            status_code="DOUYIN_PARAMS_READY",
            details={
                "has_cookie": bool(cookie_str),
                "proxy_enabled": bool(proxy_str),
                "chunk_size": params.chunk,
                "max_retry": params.max_retry,
            },
        )

        raw_text = self.keyword.strip()
        link_extractor = LinkExtractor(params)
        await self._route_input(params, raw_text, link_extractor)

    async def _process_detail(self, params, ids: list):
        """逐个拉取作品详情，并按数量决定直接入队还是弹出选择框。"""
        self.log(f"🎬 识别到 {len(ids)} 个作品 ID，开始获取详情...")
        api = Detail(params, detail_id=ids[0])

        all_items = []
        # 详情接口一次只接一个 aweme_id，这里串行拉取并逐条转换为统一的 VideoItem。
        for vid in ids:
            if not self.is_running: break
            api.detail_id = vid
            data = await api.run(single_page=True, data_key="aweme_detail")
            if data:
                trace_id = f"dy_{str(vid).replace('-', '_')}"
                self.debug_api(
                    api_name="detail",
                    request={"trace_id": trace_id, "aweme_id": vid},
                    response_summary=self.parser.summarize_aweme(data),
                    message="抖音作品详情返回",
                    status_code="DOUYIN_DETAIL_OK",
                )
                item = self.parser.parse_aweme(data)
                if item:
                    all_items.append(item)

        if not all_items:
            self.log("❌ 获取作品详情失败")
            return

        # 单个作品直接下载，多作品则交给选择对话框，避免误下整批内容。
        limited_items = self._trim_items(all_items, "分享链接作品")
        if len(limited_items) == 1:
            self._submit_tasks(limited_items)
        else:
            self._handle_selection(limited_items, "分享链接作品")

    async def _process_user(self, params, sec_uid: str):
        """分页抓取指定用户主页的公开作品，并在达到上限后停止继续翻页。"""
        self.log(f"👤 识别到用户 SecUID: {sec_uid}，开始爬取主页...")
        account_api = Account(params, sec_user_id=sec_uid)

        all_data = []
        page = 0
        # [修复] 使用 finished 属性判断循环，而不是 has_more
        # 账号主页是分页接口，需要持续拉取直到接口声明 finished 或达到条目上限。
        while self.is_running and not account_api.finished:
            page += 1
            self.log(f"📄 正在获取第 {page} 页...")

            await account_api.run_single()

            if not account_api.response:
                break

            raw_list = account_api.response
            account_api.response = []
            self.debug_api(
                api_name="account_page",
                request={"sec_user_id": sec_uid, "page": page},
                response_summary={
                    "item_count": len(raw_list or []),
                    "sample_aweme_ids": [aweme.get("aweme_id") for aweme in (raw_list or [])[:5]],
                    "finished": account_api.finished,
                },
                message="抖音用户作品分页返回",
                status_code="DOUYIN_ACCOUNT_PAGE",
            )

            batch_items = []
            for aweme in raw_list:
                item = self.parser.parse_aweme(aweme)
                if item:
                    batch_items.append(item)

            all_data.extend(batch_items)
            if self._max_items_limit() < 9999 and len(all_data) >= self._max_items_limit():
                self.log(f"ℹ️ 已达到视频数上限 {self._max_items_limit()}，停止继续抓取")
                break
            await asyncio.sleep(1)

        if not all_data:
            self.log("❌ 未找到公开作品")
            return

        self._handle_selection(all_data, f"用户 {sec_uid} 的作品")

    async def _process_mix(self, params, mix_id: str):
        """分页抓取合集内容，并把合集标题写入每个条目的元数据。"""
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
            self.debug_api(
                api_name="mix_page",
                request={"mix_id": mix_id},
                response_summary={
                    "item_count": len(raw_list or []),
                    "sample_aweme_ids": [aweme.get("aweme_id") for aweme in (raw_list or [])[:5]],
                    "finished": mix_api.finished,
                },
                message="抖音合集分页返回",
                status_code="DOUYIN_MIX_PAGE",
            )

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

            # 只要拿到第一页数据就尽量抽取合集名，后续下载器可据此创建子目录。
            if mix_title is None and raw_list and isinstance(raw_list, list) and len(raw_list) > 0:
                first_item = raw_list[0]
                mix_info = first_item.get('mix_info') or first_item.get('aweme_mix_info', {})
                if mix_info:
                    mix_title = mix_info.get('mix_name') or mix_info.get('name')

            mix_api.response = []

            for aweme in raw_list:
                item = self.parser.parse_aweme(aweme)
                if item:
                    # 标记为合集作品，设置合集名称作为文件夹名
                    item.meta['is_mix'] = True
                    item.meta['mix_title'] = mix_title or f"合集_{mix_id}"
                    item.meta['folder_name'] = mix_title or f"合集_{mix_id}"
                    all_data.append(item)
                    if self._max_items_limit() < 9999 and len(all_data) >= self._max_items_limit():
                        break

            if self._max_items_limit() < 9999 and len(all_data) >= self._max_items_limit():
                self.log(f"ℹ️ 已达到视频数上限 {self._max_items_limit()}，停止继续抓取")
                break

            await asyncio.sleep(0.5)

        if not all_data:
            self.log(f"❌ 合集 {mix_id} 未找到作品或ID无效")
            return

        self._handle_selection(all_data, f"合集 {mix_title or mix_id}")

    async def _process_search(self, params, keyword: str):
        """提供 `_process_search` 对应的内部辅助逻辑，供 `DouyinSpider` 使用。"""
        max_items = self._max_items_limit()
        max_pages = 9999 if max_items >= 9999 else max(1, min(100, math.ceil(max_items / 10)))
        self.log(f"🔍 搜索关键词: {keyword} (最多 {max_items if max_items < 9999 else 'max'} 个视频)")

        search_api = Search(params, keyword=keyword, type=0)  # 0=综合

        all_data = []
        for i in range(max_pages):
            if not self.is_running: break
            self.log(f"   📄 搜索第 {i + 1} 页...")

            await search_api.run_single(data_key="data")

            raw_list = search_api.response
            search_api.response = []
            self.debug_api(
                api_name="search_page",
                request={"keyword": keyword, "page": i + 1},
                response_summary={
                    "result_count": len(raw_list or []),
                    "aweme_count": sum(1 for item in (raw_list or []) if 'aweme_info' in item),
                    "finished": search_api.finished,
                },
                message="抖音搜索分页返回",
                status_code="DOUYIN_SEARCH_PAGE",
            )

            if not raw_list: break

            for item in raw_list:
                if 'aweme_info' in item:
                    vid = self.parser.parse_aweme(item['aweme_info'])
                    if vid:
                        all_data.append(vid)
                        if max_items < 9999 and len(all_data) >= max_items:
                            break

            # [修复] 使用 finished 属性判断
            if search_api.finished or (max_items < 9999 and len(all_data) >= max_items):
                break
            await asyncio.sleep(1)

        self._handle_selection(all_data, f"搜索: {keyword}")

    def _normalize_user_search_items(self, raw_list) -> list[dict]:
        """抖音用户搜索返回存在嵌套列表，需要在进入解析前拍平。"""
        normalized: list[dict] = []
        if not isinstance(raw_list, list):
            return normalized
        for item in raw_list:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, list):
                normalized.extend(entry for entry in item if isinstance(entry, dict))
        return normalized

    async def _process_user_search(self, params, user_id: str):
        """通过用户ID/抖音号搜索用户，然后获取用户主页作品"""
        from app.core.lib.douyin.interface.search import Search
        
        self.log(f"🔍 正在搜索用户: {user_id}")
        
        # 方法1: 尝试直接访问用户主页 (抖音号)
        # 抖音用户主页格式: https://www.douyin.com/user/MS4wLjABAAAA... (sec_user_id)
        # 或者: https://v.douyin.com/xxx/ (短链)
        
        # 方法2: 使用用户搜索
        try:
            search_api = Search(params, keyword=user_id, channel=2)  # 2=用户搜索
            await search_api.run(single_page=True)
        except (RuntimeError, ValueError, TypeError, KeyError) as e:
            import traceback
            self.log(f"❌ 搜索异常: {e}")
            debug_logger.log_exception(
                "DouyinSpider",
                "user_search",
                e,
                details={"user_id": user_id},
            )
            return
        
        raw_list = search_api.response
        normalized_items = self._normalize_user_search_items(raw_list)
        self.debug_state(
            action="user_search_response_shape",
            message="记录抖音用户搜索返回结构",
            status_code="DOUYIN_USER_SEARCH_SHAPE",
            details={
                "keyword": user_id,
                "response_type": type(raw_list).__name__,
                "top_level_count": len(raw_list) if isinstance(raw_list, list) else None,
                "first_item_type": type(raw_list[0]).__name__ if isinstance(raw_list, list) and raw_list else None,
                "normalized_count": len(normalized_items),
            },
        )
        self.debug_api(
            api_name="user_search",
            request={"keyword": user_id, "channel": 2},
            response_summary={
                "result_count": len(normalized_items),
                "users": [
                    {
                        "nickname": item.get("user_info", {}).get("nickname"),
                        "sec_uid": item.get("user_info", {}).get("sec_uid"),
                        "aweme_count": item.get("user_info", {}).get("aweme_count"),
                    }
                    for item in normalized_items[:5]
                    if item.get("user_info")
                ],
            },
            message="抖音用户搜索返回",
            status_code="DOUYIN_USER_SEARCH",
        )
        
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
        if normalized_items:
            # 有搜索结果，解析用户信息
            self.log(f"✅ 找到 {len(normalized_items)} 个匹配用户")
            
            users = []
            for item in normalized_items:
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
            test_url = f"https://www.douyin.com/user/{user_id}"
            
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": USERAGENT,
                    "Referer": "https://www.douyin.com/",
                    "Cookie": params.cookie_str
                },
                timeout=self._configured_timeout_seconds(default=60),
                follow_redirects=True,
                proxy=params.proxy or None,
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
        except (httpx.HTTPError, OSError, RuntimeError, ValueError) as e:
            self.log(f"⚠️ 主页请求失败: {e}")
        
        self.log(f"❌ 无法找到用户 '{user_id}'")
        self.log("💡 抖音纯数字 UID 无法直接搜索，请使用以下方式：")
        self.log("   1. 输入用户主页链接（如 https://www.douyin.com/user/MS4w...）")
        self.log("   2. 输入用户昵称进行搜索")
        self.log("   3. 在抖音 APP 中复制分享链接")

    def _handle_selection(self, items: list[VideoItem], title_hint: str):
        """提供 `_handle_selection` 对应的内部辅助逻辑，供 `DouyinSpider` 使用。"""
        items = self._trim_items(items, title_hint)
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
        """提供 `_submit_tasks` 对应的内部辅助逻辑，供 `DouyinSpider` 使用。"""
        self.debug_state(
            action="submit_tasks_enter",
            message="进入抖音任务提交阶段",
            status_code="DOUYIN_SUBMIT_ENTER",
            details={"item_count": len(items)},
        )
        for item in items:
            built_items = self.task_builder.build_items(item, self.new_trace_id)
            for built_item in built_items:
                self.debug_state(
                    action="emit_download_task",
                    message="抖音下载任务已提交到下载队列",
                    status_code="DOUYIN_TASK_EMIT",
                    context={
                        "trace_id": built_item.meta.get("trace_id"),
                        "aweme_id": built_item.meta.get("aweme_id"),
                    },
                    details={
                        "title": built_item.title,
                        "url": built_item.url,
                        "content_type": built_item.meta.get("content_type"),
                        "media_label": built_item.meta.get("media_label"),
                    },
                    trace_id=built_item.meta.get("trace_id"),
                )
                self.emit_video(
                    built_item.url,
                    built_item.title,
                    "douyin",
                    meta=built_item.meta,
                )
