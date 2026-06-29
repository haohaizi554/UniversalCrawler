"""Bilibili spider built as a scan -> parse -> assemble pipeline."""

import os
import re
import time
import json
import requests
import urllib.parse
import threading
import queue
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright
from app.config import DEFAULT_USER_AGENT, cfg, get_setting_default
from app.exceptions import (
    InvalidCookieStateError,
    LoginCancelledError,
    LoginCheckError,
    LoginTimeoutError,
    SpiderAuthError,
    SpiderParseError,
    StreamResolveError,
)
from app.spiders.base import BaseSpider
from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.bilibili.task_builder import BilibiliTaskBuilder
from app.debug_logger import debug_logger
from app.services.auth_service import AuthService

HEADERS = {
    'User-Agent': DEFAULT_USER_AGENT,
    'Referer': 'https://www.bilibili.com'
}

@dataclass(frozen=True, slots=True)
class BilibiliInputRoute:
    """Normalized Bilibili input route used by the browser producer."""

    kind: str
    value: str
    scan_kwargs: dict[str, object] | None = None

class BiliAPI:
    """B 站 API 访问层，负责登录态检查、详情读取和取流。"""

    def __init__(self, cookie_path, parser: BilibiliParser):
        """初始化当前实例并准备运行所需的状态，供 `BiliAPI` 使用。"""
        self.sess = requests.Session()#创建一个持久化的 HTTP 会话对象
        self._session_lock = threading.RLock()
        with self._session_guard():
            self.sess.headers.update(HEADERS)
        self.cookie_path = cookie_path#保存 Cookie 文件的本地路径
        self.parser = parser#注入页面解析器依赖
        self.auth_service = AuthService()#初始化认证服务实例
        self.request_timeout = cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout"))
        self._video_info_errors: dict[str, dict[str, object]] = {}
        self.load_cookies()

    def _request_timeout(self):
        """兼容直接 `__new__` 构造的测试对象，延迟读取超时配置。"""
        return getattr(self, "request_timeout", cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout")))

    def close(self) -> None:
        with self._session_guard():
            close = getattr(getattr(self, "sess", None), "close", None)
            if callable(close):
                close()

    def _session_guard(self) -> threading.RLock:
        lock = getattr(self, "_session_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._session_lock = lock
        return lock

    def _remember_video_info_error(self, target: str, resp: dict, http_status: int) -> None:
        errors = getattr(self, "_video_info_errors", None)
        if not isinstance(errors, dict):
            errors = {}
            self._video_info_errors = errors
        errors[str(target)] = {
            "code": resp.get("code"),
            "message": resp.get("message") or resp.get("msg") or "",
            "http_status": http_status,
        }

    def consume_video_info_error(self, target: object) -> dict[str, object] | None:
        errors = getattr(self, "_video_info_errors", None)
        if not isinstance(errors, dict):
            return None
        return errors.pop(str(target), None)

    def load_cookies(self):
        """加载 `cookies` 对应的数据、配置或资源，供 `BiliAPI` 使用。"""
        cookies = self.auth_service.load_json_file(self.cookie_path)
        cookie_dict = self.auth_service.extract_cookie_dict(cookies)
        with self._session_guard():
            if cookie_dict:
                for key, value in cookie_dict.items():
                    self.sess.cookies.set(key, value, domain=".bilibili.com")
            elif cookies is not None:
                raise InvalidCookieStateError("Bilibili Cookie 格式非法")

    def snapshot_cookies(self) -> dict[str, str]:
        with self._session_guard():
            return {c.name: c.value for c in self.sess.cookies if c.name}

    def check_login(self):
        
        try:
            url = "https://api.bilibili.com/x/web-interface/nav"
            with self._session_guard():
                response = self.sess.get(url, timeout=self._request_timeout())
            resp = response.json()
            debug_logger.log_api(
                component="BiliAPI",
                api_name="check_login",
                request={"url": url},
                response_summary={
                    "api_code": resp.get("code"),
                    "is_login": resp.get("data", {}).get("isLogin", False),
                    "mid": resp.get("data", {}).get("mid"),
                    "uname": resp.get("data", {}).get("uname"),
                },
                message="检查 Bilibili 登录状态",
                status_code=response.status_code,
            )
            return resp['code'] == 0 and resp['data']['isLogin']
        except (requests.RequestException, ValueError, KeyError) as e:
            debug_logger.log_exception("BiliAPI", "check_login", e, context={"cookie_path": self.cookie_path})
            raise LoginCheckError("Bilibili 登录状态校验失败") from e

    def get_video_info(self, bvid: str | None = None, trace_id=None, *, aid: str | int | None = None):
        """Fetch Bilibili video detail by bvid, or by aid for legacy av links."""
        target = str(aid if aid is not None else bvid or "").strip()
        if not target:
            raise SpiderParseError("missing Bilibili video id")
        query_key = "aid" if aid is not None else "bvid"
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?{query_key}={urllib.parse.quote(target)}"
            with self._session_guard():
                response = self.sess.get(url, timeout=self._request_timeout())
            resp = response.json()
            data = resp.get('data') or {}
            debug_logger.log_api(
                component="BiliAPI",
                api_name="get_video_info",
                request={"trace_id": trace_id, "url": url, "bvid": bvid, "aid": aid},
                response_summary={
                    "api_code": resp.get("code"),
                    "title": data.get("title"),
                    "owner": data.get("owner", {}).get("name"),
                    "pages": len(data.get("pages", [])),
                    "is_season": bool(data.get("ugc_season")),
                    "season_title": (data.get("ugc_season") or {}).get("title"),
                },
                message="fetch video detail",
                status_code=response.status_code,
                trace_id=trace_id,
            )
            if resp.get('code') != 0:
                self._remember_video_info_error(target, resp, response.status_code)
                return None
            self.consume_video_info_error(target)
            return self.parser.parse_video_info_response(data)
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            debug_logger.log_exception(
                "BiliAPI",
                "get_video_info",
                e,
                context={"bvid": bvid, "aid": aid},
                trace_id=trace_id,
            )
            raise SpiderParseError(f"failed to fetch Bilibili video info: {query_key}={target}") from e

    def get_play_url(self, bvid, cid, trace_id=None):
        
        def _request(fnval):
            """提供 `_request` 对应的内部辅助逻辑。"""
            url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=120&fnval={fnval}&fourk=1"
            with self._session_guard():
                response = self.sess.get(url, timeout=self._request_timeout())
            return url, response.status_code, response.json()
        request_url, http_status, resp = _request(4048)
        request_mode = 4048
        if resp['code'] != 0 or 'data' not in resp or 'dash' not in resp['data']:
            request_url, http_status, resp = _request(80)
            request_mode = 80
        if resp.get("code") != 0 or "data" not in resp:
            raise StreamResolveError(f"B站取流失败: code={resp.get('code')}")
        dash = resp.get('data', {}).get('dash', {})
        video_stream = dash.get('video', [{}])[0] if dash.get('video') else {}
        audio_stream = dash.get('audio', [{}])[0] if dash.get('audio') else {}
        debug_logger.log_api(
            component="BiliAPI",
            api_name="get_play_url",
            request={"trace_id": trace_id, "url": request_url, "bvid": bvid, "cid": cid, "fnval": request_mode},
            response_summary={
                "api_code": resp.get("code"),
                "accept_quality": resp.get("data", {}).get("accept_quality", []),
                "video_quality_id": video_stream.get("id"),
                "video_bandwidth": video_stream.get("bandwidth"),
                "has_audio": bool(dash.get("audio")),
                "video_url": video_stream.get("baseUrl"),
                "audio_url": audio_stream.get("baseUrl"),
            },
            message="获取播放流地址",
            status_code=http_status,
            trace_id=trace_id,
        )
        return self.parser.parse_play_url_response(resp)

class BilibiliSpider(BaseSpider):
    """Bilibili 爬虫，采用浏览器扫描和 API 解析并行的流水线模型。"""

    def __init__(self, keyword: str, config: dict):
        """初始化当前实例并准备运行所需的状态，供 `BilibiliSpider` 使用。"""
        super().__init__(keyword, config)
        self.parser = BilibiliParser()
        self.task_builder = BilibiliTaskBuilder(self.parser)
        self.auth_service = AuthService()
        self._browser_thread: threading.Thread | None = None
        self._api_pool_thread: threading.Thread | None = None

    def _max_items_limit(self) -> int:
        default_limit = get_setting_default("bilibili", "max_items")
        value = (getattr(self, "config", {}) or {}).get(
            "max_items",
            cfg.get("bilibili", "max_items", default_limit),
        )
        try:
            return max(1, min(int(value), 9999))
        except (TypeError, ValueError):
            return int(default_limit)

    def _effective_scan_pages(self) -> int:
        try:
            configured_pages = int((getattr(self, "config", {}) or {}).get("max_pages", 1) or 1)
        except (TypeError, ValueError):
            configured_pages = 1
        item_budget_pages = max(1, (self._max_items_limit() + 29) // 30)
        return max(1, min(max(configured_pages, item_budget_pages), 9999))

    def _collected_bvid_count(self, bv_set: set[str], excluded_bvids: set[str] | None = None) -> int:
        excluded = {self._normalize_bvid(value) for value in (excluded_bvids or set()) if value}
        return sum(1 for bvid in bv_set if bvid and bvid not in excluded)

    def _has_bvid_capacity(self, bv_set: set[str], excluded_bvids: set[str] | None = None) -> bool:
        return self._collected_bvid_count(bv_set, excluded_bvids) < self._max_items_limit()

    @staticmethod
    def _format_episode_choice(parent_title: str, episode: dict, fallback_index: int) -> str:
        """格式化第二层候选，保留父级标题，避免只剩 `[01] xxx` 的裸信息。"""
        parent = parent_title or "未命名项目"
        num_str = str(episode.get("page_num", fallback_index + 1)).zfill(2)
        episode_title = episode.get("title") or f"第 {fallback_index + 1} 集"
        return f"{parent} · P{num_str} · {episode_title}"

    def _process_download_task(self, task: dict) -> bool:
        """逐条取流并提交下载，单条失败不影响后续任务继续执行。"""
        self.log(f"🎬 解析流: {task['file_name'][:15]}...")
        try:
            v_url, a_url, q_id = self.api.get_play_url(task['bvid'], task['cid'], trace_id=task['trace_id'])
            if not v_url:
                self.log("   ❌ 获取流失败")
                self.debug_state(
                    action="resolve_stream_empty",
                    message="Bilibili 播放流响应为空",
                    status_code="BILI_STREAM_EMPTY",
                    context={"trace_id": task["trace_id"], "bvid": task["bvid"], "cid": task["cid"]},
                    details={
                        "file_name": task["file_name"],
                        "audio_url": a_url,
                        "quality_id": q_id,
                    },
                    level="WARNING",
                    trace_id=task["trace_id"],
                )
                return False

            q_map = {127: "8K", 120: "4K", 116: "1080P60", 80: "1080P", 64: "720P"}
            q_text = q_map.get(q_id, "高清")
            self.log(f"   ✨ 获取成功 [{q_text}]")
            folder_name = task.get("folder_name")
            proxy_str = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
            cookie_dict = self.api.snapshot_cookies()
            meta = {
                "trace_id": task["trace_id"],
                "content_type": "video",
                "media_label": "视频",
                "audio_url": a_url,
                "ua": HEADERS['User-Agent'],
                "referer": task['referer'],
                "use_subdir": bool(folder_name),
                "bvid": task["bvid"],
                "cid": task["cid"],
                "preferred_filename": task["file_name"],
                "cookies": cookie_dict,
            }
            if proxy_str:
                meta["proxy"] = proxy_str
            if folder_name:
                meta["folder_name"] = folder_name
            self.emit_video(
                url=v_url,
                title=os.path.splitext(task["file_name"])[0],
                source="bilibili",
                meta=meta
            )
            self.debug_state(
                action="emit_download_task",
                message="Bilibili 下载任务已提交到下载队列",
                status_code="BILI_TASK_EMIT",
                context={"trace_id": task["trace_id"], "bvid": task["bvid"], "cid": task["cid"]},
                details={
                    "file_name": task["file_name"],
                    "folder_name": folder_name,
                    "quality_id": q_id,
                    "video_url": v_url,
                    "audio_url": a_url,
                },
                trace_id=task["trace_id"],
            )
            return True
        except Exception as exc:
            self.log(f"   ❌ 获取流失败: {exc}")
            self.debug_state(
                action="resolve_stream_failed",
                message="Bilibili 获取播放流失败",
                status_code="BILI_STREAM_FAIL",
                context={"trace_id": task["trace_id"], "bvid": task["bvid"], "cid": task["cid"]},
                details={
                    "file_name": task["file_name"],
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                level="ERROR",
                trace_id=task["trace_id"],
            )
            return False
        finally:
            self.interruptible_sleep(0.5)

    #完整流程控制器
    def run(self):
        """执行当前对象或脚本的主流程，供 `BilibiliSpider` 使用。"""
        try:
            self.debug_state(
                action="run_start",
                message="启动 Bilibili 爬虫任务",
                status_code="BILI_SPIDER_START",
                context={"keyword": self.keyword},
                details={"config": self.config},
            )
            cookie_file = cfg.get(
                "auth",
                "bilibili_cookie_file",
                cfg.get("bilibili", "auth_file", get_setting_default("bilibili", "auth_file")),
            )
            self.api = BiliAPI(cookie_file, parser=self.parser)
            self.api.request_timeout = self._configured_timeout_seconds(
                default=cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout"))
            )
            try:
                is_logged_in = self.api.check_login()
            except LoginCheckError as exc:
                self.log(f"⚠️ 登录状态校验失败，尝试继续执行: {exc}")
                is_logged_in = False
            if not is_logged_in:
                self.log("🔒 未检测到登录，启动浏览器扫码...")
                try:
                    self._perform_login_scan(cookie_file)
                except SpiderAuthError as exc:
                    self.log(f"⚠️ 登录失败，以游客身份爬取: {exc}")
                else:
                    self.log("✅ 已完成扫码登录")
            else:
                self.log("👤 已登录，Cookie 有效")
            self.log(f"🚀 启动 Bilibili 任务 | 目标: {self.keyword}")
            # 原始 BV 队列由浏览器线程生产，结构化详情队列由 API 线程消费后再回流主线程。
            self.raw_bv_queue = queue.Queue()
            self.parsed_info_queue = queue.Queue()
            self.browser_finished = threading.Event()
            self.api_pool_finished = threading.Event()
            self.api_failure_queue = queue.Queue()
            # 生产者线程负责翻页找 BV，加工线程负责打 API，主线程负责聚合和交互。
            self._browser_thread = threading.Thread(target=self._producer_browser_task, name="bilibili-browser")
            self._browser_thread.start()
            self._api_pool_thread = threading.Thread(target=self._worker_api_pool, name="bilibili-api")
            self._api_pool_thread.start()
            display_items = []
            cached_data = {}
            seen_season_ids = set()
            seen_bvid_singles = set()
            valid_idx = 0
            self.log("⚡ 流水线已建立: 扫描 -> 解析 -> 聚合 同时进行中...")
            while True:
                if not self.is_running: break
                try:
                    info = self.parsed_info_queue.get(timeout=0.5)
                    # 主线程只维护展示项和二次选择所需缓存，避免后台线程直接碰 UI 数据。
                    valid_idx = self._append_bilibili_info_for_selection(
                        info,
                        display_items,
                        cached_data,
                        seen_season_ids,
                        seen_bvid_singles,
                        valid_idx,
                    )
                    if valid_idx % 5 == 0:
                        self.log(f"   📊 已聚合 {valid_idx} 个有效资源...")
                except queue.Empty:
                    if self.api_pool_finished.is_set():
                        break
                    continue
            self._join_worker_thread(self._browser_thread, "browser")
            self._join_worker_thread(self._api_pool_thread, "api")
            if not self.is_running:
                self.log("⏹️ Bilibili 爬虫已停止，跳过结果选择")
                return
            if not display_items:
                api_failures = self._collect_api_failures(limit=20)
                valid_idx = self._try_api_failure_browser_fallback(
                    api_failures,
                    display_items,
                    cached_data,
                    seen_season_ids,
                    seen_bvid_singles,
                    valid_idx,
                    max_pages=self._effective_scan_pages(),
                )
                if not display_items:
                    self._log_api_failure_summary(failures=api_failures)
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
            max_download_items = self._max_items_limit()
            for idx in stage1_indices:
                if not self.is_running or len(final_download_queue) >= max_download_items:
                    break
                item = cached_data[idx]
                info = item['info']
                episodes = info['episodes']
                item_type = item['type']
                if item_type == 'single':
                    ep = episodes[0]
                    final_download_queue.append(
                        self.task_builder.build_single_task(
                            ep,
                            referer=f"https://www.bilibili.com/video/{ep['bvid']}",
                            video_title=info.get("title"),
                        )
                    )
                    continue
                sub_dialog_items = []
                remaining_slots = max_download_items - len(final_download_queue)
                parent_label = info.get('season_title') or info.get('title') or "未命名项目"
                for i, ep in enumerate(episodes[:remaining_slots]):
                    sub_dialog_items.append({
                        'title': ep.get('title') or f"第 {i + 1} 集",
                        'subtitle': f"P{str(ep.get('page_num', i + 1)).zfill(2)}",
                        'group_title': parent_label,
                        'index': i
                    })
                if len(episodes) > remaining_slots:
                    self.log(f"ℹ️ 已按视频数上限 {max_download_items} 裁剪可选分集")
                self.log(f"🔔 正在展开: {info.get('season_title') or info['title']}")
                sub_indices = self.ask_user_selection(sub_dialog_items)
                if not sub_indices:
                    continue
                for sub_idx in sub_indices:
                    if len(final_download_queue) >= max_download_items:
                        break
                    ep = episodes[sub_idx]
                    final_download_queue.append(self.task_builder.build_episode_task(info, ep, sub_idx))
            if len(final_download_queue) >= max_download_items:
                self.log(f"ℹ️ 已达到视频数上限 {max_download_items}，剩余选择不会进入下载队列")
            self.log(f"✅ 最终确认 {len(final_download_queue)} 个任务，开始下载...")
            self.debug_state(
                action="download_queue_ready",
                message="Bilibili 下载任务已装配完成",
                status_code="BILI_QUEUE_READY",
                details={
                    "task_count": len(final_download_queue),
                    "sample_tasks": [task["file_name"] for task in final_download_queue[:5]],
                },
            )
            success_count = 0
            failure_count = 0
            for task in final_download_queue:
                if not self.is_running: break
                if self._process_download_task(task):
                    success_count += 1
                else:
                    failure_count += 1
            self.log(f"🎉 全部完成: 成功 {success_count}/{len(final_download_queue)} | 失败 {failure_count}")
        finally:
            api = getattr(self, "api", None)
            if api is not None:
                api.close()
            self._join_worker_thread(self._browser_thread, "browser")
            self._join_worker_thread(self._api_pool_thread, "api")
            self._browser_thread = None
            self._api_pool_thread = None
            self.debug_state(
                action="run_finish",
                message="Bilibili 爬虫任务结束",
                status_code="BILI_SPIDER_FINISH",
            )
            self._emit_finished()

    def _join_worker_thread(self, thread: threading.Thread | None, label: str, timeout: float = 5.0) -> None:
        """等待后台线程退出，避免 stop() 因无超时 join 导致主流程长期卡住。"""
        if thread is None:
            return
        thread.join(timeout=timeout)
        if thread.is_alive():
            self.log(f"⚠️ {label} 线程未在 {timeout:.0f}s 内退出，跳过继续收尾")
    # --- 线程任务：浏览器生产者 ---
    def _producer_browser_task(self):
        """Route the raw user input and enqueue bvid/aid items or browser scans."""
        try:
            max_pages = self._effective_scan_pages()
            route = self._classify_input(self.keyword)
            self._execute_input_route(route, max_pages=max_pages)
        except (PlaywrightError, ValueError, RuntimeError) as e:
            self.log(f"Bilibili browser producer error: {e}")
        finally:
            self.browser_finished.set()

    URL_TRAILING_PUNCTUATION = " \t\r\n`'\"\uFF0C\u3002\uFF01\uFF1F\uFF1B\uFF1A\u3001,.!?;:)]}\uFF09\u3011\u300B>"
    COLLECTION_PATH_MARKERS = (
        "/list/",
        "/lists/",
        "/medialist/",
        "/playlist/",
        "/channel/collectiondetail",
        "/cheese/",
        "/bangumi/",
    )
    COLLECTION_QUERY_KEYS = {
        "list",
        "playlist",
        "season_id",
        "series_id",
        "sid",
        "collection_id",
        "media_id",
    }
    UID_LABEL_PATTERN = re.compile(r"(?i)^(?:uid|mid|up主|up主id|用户id)[:：\s]+(\d+)$")
    BVID_TEXT_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])")
    AVID_TEXT_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])")
    SHORT_LINK_HOSTS = ("b23.tv", "bili2233.cn", "bili22.cn")
    MIN_PLAIN_UID_DIGITS = 5

    def _execute_input_route(self, route: BilibiliInputRoute, *, max_pages: int) -> None:
        if route.kind == "bvid":
            self.log("Bilibili route: direct BV video")
            self.raw_bv_queue.put(route.value)
            return
        if route.kind == "bvid_with_fallback":
            self.log("Bilibili route: direct BV video with search fallback")
            self.raw_bv_queue.put(route.value)
            kwargs = dict(route.scan_kwargs or {})
            exclude_bvids = set(kwargs.pop("exclude_bvids", set()) or set())
            exclude_bvids.add(route.value)
            fallback_urls = kwargs.pop("fallback_urls", None)
            fallback_url = str(kwargs.pop("fallback_url", "") or "").strip()
            if not fallback_urls and fallback_url:
                fallback_urls = [fallback_url]
            for fallback_url in fallback_urls or []:
                fallback_url = str(fallback_url or "").strip()
                if not fallback_url:
                    continue
                scan_kwargs = dict(kwargs)
                if "search.bilibili.com" in fallback_url:
                    scan_kwargs["is_search"] = True
                self._scan_with_browser_queue(
                    fallback_url,
                    max_pages=max_pages,
                    exclude_bvids=exclude_bvids,
                    **scan_kwargs,
                )
            return
        if route.kind == "aid":
            self.log("Bilibili route: direct av video")
            self.raw_bv_queue.put({"aid": route.value})
            return
        if route.kind == "keyword":
            self.log("Bilibili route: keyword search")
            self._scan_with_browser_queue(route.value, max_pages, is_search=True, is_space=False)
            return
        kwargs = dict(route.scan_kwargs or {})
        self.log(f"Bilibili route: browser scan {route.value}")
        self._scan_with_browser_queue(route.value, max_pages=max_pages, **kwargs)

    def _extract_first_url(self, raw_text: str) -> str:
        """Extract and clean the first URL from copied share text."""
        text = str(raw_text or "").strip()
        match = re.search(r"https?://[^\s`'\"<>]+", text)
        if match:
            return self._strip_url_trailing_punctuation(match.group(0))
        match = re.search(
            r"(?://)?(?:www\.)?bilibili\.com/[^\s`'\"<>]+",
            text,
            re.I,
        )
        if match:
            candidate = match.group(0)
            if "://" not in candidate:
                candidate = f"https://{candidate.lstrip('/')}"
            return self._strip_url_trailing_punctuation(candidate)
        for host in self.SHORT_LINK_HOSTS:
            match = re.search(rf"(?i)\b{re.escape(host)}/[^\s`'\"<>]+", text)
            if match:
                return self._strip_url_trailing_punctuation(f"https://{match.group(0)}")
        return text.strip().strip("`")

    @classmethod
    def _strip_url_trailing_punctuation(cls, value: str) -> str:
        return str(value or "").strip().strip("`").rstrip(cls.URL_TRAILING_PUNCTUATION)

    def _resolve_short_share_url(self, url: str) -> str:
        """Resolve Bilibili short share links to their final destination URL."""
        candidate = str(url or "").strip()
        if candidate and not candidate.lower().startswith(("http://", "https://")):
            if any(host in candidate.lower() for host in self.SHORT_LINK_HOSTS):
                candidate = f"https://{candidate.lstrip('/')}"
            elif candidate.lower().startswith(("www.bilibili.com/", "bilibili.com/")):
                candidate = f"https://{candidate.lstrip('/')}"
        lowered = candidate.lower()
        if not any(host in lowered for host in self.SHORT_LINK_HOSTS):
            return candidate
        try:
            request_timeout = getattr(
                getattr(self, "api", None),
                "request_timeout",
                self._configured_timeout_seconds(
                    default=cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout"))
                ),
            )
            proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
            proxies = {"http": proxy, "https": proxy} if proxy else None
            response = requests.get(
                candidate,
                headers=HEADERS,
                timeout=request_timeout,
                allow_redirects=True,
                proxies=proxies,
            )
            resolved = response.url or candidate
            if hasattr(self, "sig_log"):
                self.log(f"🔗 [短链解析] {candidate} -> {resolved}")
            return resolved
        except requests.RequestException as exc:
            if hasattr(self, "sig_log"):
                self.log(f"⚠️ [短链解析失败] {exc}")
            return candidate

    def _normalize_keyword(self, raw_text: str) -> str:
        """Normalize share text and short links before route classification."""
        extracted = self._extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _classify_input(self, raw_text: str) -> BilibiliInputRoute:
        raw = str(raw_text or "").strip()
        normalized = self._normalize_keyword(raw)
        value = str(normalized or "").strip()
        if not value:
            return self._keyword_route("")

        uid_label = self.UID_LABEL_PATTERN.match(raw)
        if uid_label:
            uid = uid_label.group(1)
            return BilibiliInputRoute(
                "scan",
                f"https://space.bilibili.com/{uid}/video",
                {"is_search": False, "is_space": True},
            )

        if re.fullmatch(r"\d+", value):
            if len(value) < self.MIN_PLAIN_UID_DIGITS:
                return self._keyword_route(value)
            return BilibiliInputRoute(
                "scan",
                f"https://space.bilibili.com/{value}/video",
                {"is_search": False, "is_space": True},
            )
        if re.fullmatch(r"(?i)BV[0-9A-Za-z]{10}", value):
            return BilibiliInputRoute("bvid", "BV" + value[2:])
        if re.fullmatch(r"(?i)av\d+", value):
            return BilibiliInputRoute("aid", value[2:])

        if value.lower().startswith(("http://", "https://")):
            return self._route_url(value)

        bvid = self._bvid_from_text(value)
        if bvid:
            if self._looks_like_collection_bvid_hint(raw):
                fallback_url = f"https://www.bilibili.com/video/{bvid}"
                fallback_urls = self._collection_bvid_fallback_urls(bvid, raw)
                scan_kwargs = {
                    "is_search": False,
                    "is_space": False,
                    "fallback_url": fallback_url,
                    "fallback_urls": list(dict.fromkeys(fallback_urls)),
                }
                return BilibiliInputRoute("bvid_with_fallback", bvid, scan_kwargs)
            return BilibiliInputRoute("bvid", bvid)
        aid = self._aid_from_text(value)
        if aid:
            return BilibiliInputRoute("aid", aid)
        return self._keyword_route(value)

    def _keyword_route(self, keyword: str) -> BilibiliInputRoute:
        search_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(str(keyword or ''))}"
        return BilibiliInputRoute("keyword", search_url, {"is_search": True, "is_space": False})

    @classmethod
    def _looks_like_collection_bvid_hint(cls, raw_text: str) -> bool:
        lowered = str(raw_text or "").lower()
        if any(marker in lowered for marker in ("合集", "系列", "列表", "收藏", "collection", "season", "series")):
            return True
        return bool(cls.BVID_TEXT_PATTERN.search(str(raw_text or ""))) and str(raw_text or "").upper().count("BV") > 1

    def _collection_bvid_fallback_urls(self, bvid: str, raw_text: str = "") -> list[str]:
        """Build browser fallbacks for "BV + collection hint" inputs.

        Users often paste phrases such as ``BVxxx合集BV号``. The plain BV may be an
        unavailable representative entry, while the searchable collection result is
        found by separating the BV and the collection keyword.
        """
        normalized_bvid = self._normalize_bvid(bvid)
        raw = str(raw_text or "").strip()
        search_terms = [
            normalized_bvid,
            f"{normalized_bvid} 合集",
            raw,
        ]
        urls = [self._keyword_route(term).value for term in search_terms if term]
        urls.append(f"https://www.bilibili.com/video/{normalized_bvid}")
        return list(dict.fromkeys(urls))

    def _record_api_failure(self, raw_id, error: dict[str, object] | None) -> None:
        if not isinstance(error, dict) or not error:
            return
        failure_queue = getattr(self, "api_failure_queue", None)
        if failure_queue is None:
            return
        try:
            failure_queue.put_nowait(
                {
                    "raw_id": raw_id,
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "http_status": error.get("http_status"),
                }
            )
        except queue.Full:
            pass

    def _collect_api_failures(self, *, limit: int = 5) -> list[dict[str, object]]:
        failure_queue = getattr(self, "api_failure_queue", None)
        if failure_queue is None:
            return []
        failures = []
        while len(failures) < max(1, limit):
            try:
                failures.append(failure_queue.get_nowait())
            except queue.Empty:
                break
        return failures

    def _log_api_failure_summary(self, *, limit: int = 5, failures: list[dict[str, object]] | None = None) -> None:
        if failures is None:
            failures = self._collect_api_failures(limit=limit)
        if not failures:
            return
        parts = []
        for failure in failures:
            raw_id = failure.get("raw_id")
            code = failure.get("code")
            message = failure.get("message") or "unknown"
            status = failure.get("http_status")
            status_part = f", http={status}" if status else ""
            parts.append(f"{raw_id}: code={code}{status_part}, message={message}")
        self.log("Bilibili API did not return usable video details: " + " | ".join(parts))

    def _append_bilibili_info_for_selection(
        self,
        info: dict,
        display_items: list[dict],
        cached_data: dict,
        seen_season_ids: set,
        seen_bvid_singles: set,
        valid_idx: int,
    ) -> int:
        """Append one parsed Bilibili info object to the two-stage selection cache."""
        if len(display_items) >= self._max_items_limit():
            return valid_idx
        if info.get("is_season"):
            sid = info.get("season_id")
            if sid in seen_season_ids:
                return valid_idx
            seen_season_ids.add(sid)
            count = len(info.get("episodes") or [])
            title_str = f"【合集】{info.get('season_title') or info.get('title')} (共 {count} 集) - {info.get('owner')}"
            display_items.append({"title": title_str, "index": valid_idx})
            cached_data[valid_idx] = {"type": "season", "info": info}
            return valid_idx + 1

        bvid = info.get("bvid")
        if bvid in seen_bvid_singles:
            return valid_idx
        seen_bvid_singles.add(bvid)
        count = len(info.get("episodes") or [])
        if count > 1:
            title_str = f"【多P】{info.get('title')} (共 {count} P) - {info.get('owner')}"
            item_type = "multi_p"
        else:
            title_str = f"【视频】{info.get('title')} - {info.get('owner')}"
            item_type = "single"
        display_items.append({"title": title_str, "index": valid_idx})
        cached_data[valid_idx] = {"type": item_type, "info": info}
        return valid_idx + 1

    def _fallback_scan_urls_for_api_failure(self, raw_id: object) -> list[str]:
        if isinstance(raw_id, dict):
            raw_id = raw_id.get("bvid") or raw_id.get("aid") or ""
        bvid = self._bvid_from_text(str(raw_id or ""))
        if not bvid:
            return []
        return self._collection_bvid_fallback_urls(bvid, str(getattr(self, "keyword", "") or bvid))

    def _try_api_failure_browser_fallback(
        self,
        failures: list[dict[str, object]],
        display_items: list[dict],
        cached_data: dict,
        seen_season_ids: set,
        seen_bvid_singles: set,
        valid_idx: int,
        *,
        max_pages: int,
    ) -> int:
        """Use browser extraction only after the direct BV API path returned no usable item."""
        if not failures or not self.is_running:
            return valid_idx
        candidate_bvids: list[str] = []
        seen_candidates: set[str] = set()
        failed_bvids = {
            bvid
            for failure in failures
            for bvid in [self._bvid_from_text(str(failure.get("raw_id") or ""))]
            if bvid
        }
        for failure in failures:
            raw_id = failure.get("raw_id")
            for url in self._fallback_scan_urls_for_api_failure(raw_id):
                if not self.is_running:
                    return valid_idx
                self.log(f"↩️ Bilibili API 失败，尝试网页兜底扫描: {url}")
                scan_kwargs = {"is_search": "search.bilibili.com" in url, "is_space": False}
                for bvid in self._scan_with_browser_queue(
                    url,
                    max_pages=max_pages,
                    enqueue=False,
                    exclude_bvids=failed_bvids,
                    **scan_kwargs,
                ):
                    if bvid in seen_candidates:
                        continue
                    seen_candidates.add(bvid)
                    candidate_bvids.append(bvid)
        if not candidate_bvids:
            self.log(
                "Bilibili browser fallback did not find additional BV candidates; "
                "the source BV may be unavailable/private, or the collection/UP homepage link is required."
            )
            return valid_idx
        for bvid in candidate_bvids:
            if not self.is_running:
                break
            if bvid in seen_bvid_singles:
                continue
            try:
                info = self.api.get_video_info(bvid, trace_id=f"bilibili_fallback_{bvid}")
            except SpiderParseError as exc:
                self.log(f"⚠️ Bilibili 网页兜底解析失败: {bvid} | {exc}")
                continue
            if not info:
                continue
            valid_idx = self._append_bilibili_info_for_selection(
                info,
                display_items,
                cached_data,
                seen_season_ids,
                seen_bvid_singles,
                valid_idx,
            )
        return valid_idx

    def _route_url(self, url: str) -> BilibiliInputRoute:
        url = self._strip_url_trailing_punctuation(url)
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path or ""
        if "bilibili.com" not in host and "b23.tv" not in host:
            return self._keyword_route(url)
        if "space.bilibili.com" in host:
            if self._is_collection_like_url(parsed):
                return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})
            uid_match = re.search(r"/(\d+)(?:/|$)", path)
            target_url = url
            if uid_match and not re.search(r"/(video|lists?)(?:/|$)", path):
                target_url = f"https://space.bilibili.com/{uid_match.group(1)}/video"
            return BilibiliInputRoute("scan", target_url, {"is_search": False, "is_space": True})
        if "search.bilibili.com" in host:
            return BilibiliInputRoute("scan", url, {"is_search": True, "is_space": False})
        bvid = self._bvid_from_url(url)
        if bvid and self._is_bvid_ugc_season_entry_url(parsed):
            return BilibiliInputRoute(
                "bvid_with_fallback",
                bvid,
                {"is_search": False, "is_space": False, "fallback_url": url},
            )
        if self._is_collection_like_url(parsed):
            return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})
        if bvid:
            return BilibiliInputRoute("bvid", bvid)
        aid = self._aid_from_url(url)
        if aid:
            return BilibiliInputRoute("aid", aid)
        return BilibiliInputRoute("scan", url, {"is_search": False, "is_space": False})

    @classmethod
    def _is_collection_like_url(cls, parsed: urllib.parse.ParseResult) -> bool:
        path = (parsed.path or "").lower()
        if any(marker in path for marker in cls.COLLECTION_PATH_MARKERS):
            return True
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        return any(key.lower() in cls.COLLECTION_QUERY_KEYS for key in query)

    @staticmethod
    def _is_bvid_ugc_season_entry_url(parsed: urllib.parse.ParseResult) -> bool:
        """Bilibili UGC season entries are best resolved through the BV detail API."""
        if not re.search(r"(?i)/video/BV[0-9A-Za-z]{10}", parsed.path or ""):
            return False
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        query_keys = {str(key).lower() for key in query}
        if {"ugc_season_id", "section_id", "season_id", "series_id"} & query_keys:
            return True
        spm_values = [value for key, values in query.items() if str(key).lower() in {"spm_id_from", "from_spmid"} for value in values]
        return any("videopod.sections" in str(value).lower() or "ugc_season" in str(value).lower() for value in spm_values)

    @staticmethod
    def _normalize_bvid(value: str) -> str:
        text = str(value or "").strip()
        if len(text) >= 2 and text[:2].upper() == "BV":
            return "BV" + text[2:]
        return text

    @classmethod
    def _bvid_from_url(cls, url: str) -> str:
        match = re.search(r"(?i)video/(BV[0-9A-Za-z]{10})", str(url or ""))
        if not match:
            match = cls.BVID_TEXT_PATTERN.search(str(url or ""))
        return cls._normalize_bvid(match.group(1)) if match else ""

    @classmethod
    def _bvid_from_text(cls, text: str) -> str:
        match = cls.BVID_TEXT_PATTERN.search(str(text or ""))
        return cls._normalize_bvid(match.group(1)) if match else ""

    @classmethod
    def _aid_from_text(cls, text: str) -> str:
        match = cls.AVID_TEXT_PATTERN.search(str(text or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _aid_from_url(url: str) -> str:
        match = re.search(r"(?i)(?:/video/av|[?&](?:aid|av)=)(\d+)", str(url or ""))
        return match.group(1) if match else ""

    def _worker_api_pool(self):
        """提供 `_worker_api_pool` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        def process_one(raw_id):
            """Resolve one queued bvid/aid into structured video info."""
            if not self.is_running:
                return None
            if isinstance(raw_id, dict):
                aid = str(raw_id.get("aid") or "").strip()
                if aid:
                    return self.api.get_video_info(None, trace_id=f"bilibili_av{aid}", aid=aid)
                bvid = str(raw_id.get("bvid") or "").strip()
            else:
                bvid = str(raw_id or "").strip()
            if not bvid:
                return None
            return self.api.get_video_info(bvid, trace_id=f"bilibili_{bvid}")

        try:
            api_workers = int(
                (getattr(self, "config", {}) or {}).get(
                    "api_workers",
                    cfg.get("bilibili", "api_workers", get_setting_default("bilibili", "api_workers")),
                )
            )
        except (TypeError, ValueError):
            api_workers = int(get_setting_default("bilibili", "api_workers"))
        executor = ThreadPoolExecutor(max_workers=max(1, min(api_workers, 16)))
        try:
            while True:
                if not self.is_running: break
                try:
                    bvid = self.raw_bv_queue.get(timeout=0.5)
                    future = executor.submit(process_one, bvid)
                    def callback(f, raw_id=bvid):
                        
                        if not self.is_running:
                            return
                        try:
                            res = f.result()
                            if res:
                                self.parsed_info_queue.put(res)
                            else:
                                error_key = raw_id
                                if isinstance(raw_id, dict):
                                    error_key = raw_id.get("aid") or raw_id.get("bvid") or raw_id
                                error = getattr(self.api, "consume_video_info_error", lambda _key: None)(error_key)
                                if isinstance(error, dict) and error:
                                    self._record_api_failure(raw_id, error)
                                    self.log(
                                        f"⚠️ Bilibili API 未返回可用视频信息: {raw_id} "
                                        f"(code={error.get('code')}, message={error.get('message')})"
                                    )
                                else:
                                    self.log(f"⚠️ Bilibili API 未返回可用视频信息: {raw_id}")
                        except SpiderParseError as exc:
                            self.log(f"⚠️ 视频信息解析失败: {exc}")
                        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                            self.log(f"⚠️ API 处理异常: {exc}")
                    future.add_done_callback(callback)
                except queue.Empty:
                    if self.browser_finished.is_set():
                        break
                    continue
        finally:
            if self.is_running:
                executor.shutdown(wait=True, cancel_futures=False)
            else:
                executor.shutdown(wait=True, cancel_futures=True)
            self.api_pool_finished.set()

    def _restore_scan_cookies(self, page) -> None:
        context = getattr(page, "context", None)
        if context is None:
            return
        try:
            cookie_file = cfg.get(
                "auth",
                "bilibili_cookie_file",
                cfg.get("bilibili", "auth_file", get_setting_default("bilibili", "auth_file")),
            )
            auth_service = getattr(self, "auth_service", None) or AuthService()
            auth_service.restore_playwright_cookies(context, cookie_file)
        except Exception as exc:
            self.log(f"⚠️ Bilibili 扫描 Cookie 恢复失败，继续匿名扫描: {exc}")

    # --- 浏览器扫描逻辑 ---
    def _is_bilibili_error_page(self, page) -> bool:
        """Return True before Bilibili's unavailable-video page redirects away."""
        try:
            return bool(
                page.evaluate(
                    r"""() => {
                    const initialState = window.__INITIAL_STATE__;
                    if (initialState && initialState.error && (initialState.error.code || initialState.error.trueCode)) {
                        return true;
                    }
                    const title = String(document.title || '');
                    const bodyText = String((document.body && document.body.innerText) || '').slice(0, 1200);
                    return /视频去哪了|视频不见了|稿件不可见|已被UP主删除|无法观看/.test(`${title}\n${bodyText}`);
                }"""
                )
            )
        except (PlaywrightError, TypeError, ValueError):
            return False

    def _scan_with_browser_queue(
        self,
        url,
        max_pages=1,
        is_search=False,
        is_space=False,
        enqueue: bool = True,
        exclude_bvids: set[str] | None = None,
    ):
        """提供 `_scan_with_browser_queue` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        excluded = {self._normalize_bvid(value) for value in (exclude_bvids or set()) if value}
        bv_set = set(excluded)
        def _scan_result() -> list[str]:
            return [bvid for bvid in bv_set if bvid not in excluded]
        if is_search or "search.bilibili.com" in str(url or "").lower():
            static_count = self._scan_static_bilibili_candidates(
                url,
                max_pages=max_pages,
                bv_set=bv_set,
                enqueue=enqueue,
                excluded_bvids=excluded,
            )
            if static_count > 0:
                self.log(f"   📄 静态搜索页: 发现 {static_count} 个")
                return _scan_result()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    **self._playwright_launch_kwargs(
                        headless=False,
                        proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                    )
                )
                self._track_playwright_browser(browser)
                page = browser.new_page()
                self._restore_scan_cookies(page)
                current_url = url
                browser_timeout_ms = self._configured_timeout_ms(default=60)
                if not self.interruptible_playwright_goto(page, url, timeout=browser_timeout_ms):
                    return _scan_result()
                if not self.interruptible_wait_for_load_state(
                    page,
                    "domcontentloaded",
                    timeout=browser_timeout_ms,
                ):
                    return _scan_result()
                if self._is_bilibili_error_page(page):
                    self.log(f"⚠️ Bilibili page is unavailable, skip browser candidate scan: {url}")
                    return _scan_result()
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
                                    if not self.interruptible_playwright_goto(page, target_video_url, timeout=browser_timeout_ms):
                                        return _scan_result()
                                    if not self.interruptible_wait_for_load_state(
                                        page,
                                        "domcontentloaded",
                                        timeout=browser_timeout_ms,
                                    ):
                                        return _scan_result()
                                    current_url = page.url
                                    is_search = False
                                    is_space = True
                    except (PlaywrightError, ValueError):
                        pass
                page_count = 0
                while self.is_running and page_count < max_pages:
                    page_count += 1
                    if page_count == 1:
                        self._wait_for_bilibili_candidates(
                            page,
                            timeout_ms=self._configured_timeout_ms(default=60),
                        )
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 1000)")
                        if not self.interruptible_sleep(0.3):
                            break
                    # 某些列表页会在滚动到底部后才补全卡片，因此空页时需要重新抓取一次。
                    new_count = self._scan_page_for_new_bvids(
                        page,
                        bv_set,
                        enqueue=enqueue,
                        excluded_bvids=excluded,
                    )
                    self.log(f"   📄 第 {page_count} 页: 发现 {new_count} 个")
                    if not self._has_bvid_capacity(bv_set, excluded):
                        self.log(f"   ✅ 已达到视频数上限 {self._max_items_limit()}，停止继续抓取")
                        break
                    if new_count == 0:
                        break
                    if page_count < max_pages:
                        if is_search:
                            next_page = page_count + 1
                            next_url = self._build_search_page_url(page.url, next_page)
                            current_url = next_url
                            if not self.interruptible_playwright_goto(page, next_url, timeout=browser_timeout_ms):
                                break
                            if not self.interruptible_page_wait(page, 2000):
                                break
                            continue
                        elif is_space:
                            try:
                                next_btn = page.locator("button:has-text('下一页')").first
                                if next_btn.is_visible() and next_btn.is_enabled():
                                    next_btn.click()
                                    if not self.interruptible_page_wait(page, 2000):
                                        break
                                    current_url = page.url
                                    continue
                                else:
                                    break
                            except PlaywrightError:
                                break
                        else:
                            try:
                                next_btn = page.locator("button.next-page, li.next").first
                                if next_btn.is_visible():
                                    next_btn.click()
                                    if not self.interruptible_page_wait(page, 2000):
                                        break
                                    current_url = page.url
                                    continue
                                else:
                                    break
                            except PlaywrightError:
                                break
                self._close_tracked_playwright_browser(browser)
        except (PlaywrightError, ValueError, RuntimeError) as e:
            self.log(f"⚠️ 扫描异常: {e}")
        finally:
            browser = self._tracked_playwright_browser()
            if browser is not None:
                try:
                    self._close_tracked_playwright_browser(browser)
                except PlaywrightError:
                    pass
            self._clear_playwright_browser(browser)
        return _scan_result()

    def _scan_page_for_new_bvids(
        self,
        page,
        bv_set: set[str],
        *,
        enqueue: bool = True,
        excluded_bvids: set[str] | None = None,
    ) -> int:
        """提取当前页新增 BV；若首轮为空则补滚动一次再重试。"""
        new_count = self._enqueue_new_bvids(
            self._extract_video_hrefs(page),
            bv_set,
            enqueue=enqueue,
            excluded_bvids=excluded_bvids,
        )
        if new_count > 0:
            return new_count
        if not self._has_bvid_capacity(bv_set, excluded_bvids):
            return new_count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        if not self.interruptible_sleep(1):
            return new_count
        return self._enqueue_new_bvids(
            self._extract_video_hrefs(page),
            bv_set,
            enqueue=enqueue,
            excluded_bvids=excluded_bvids,
        )

    def _scan_static_bilibili_candidates(
        self,
        url: str,
        *,
        max_pages: int,
        bv_set: set[str],
        enqueue: bool = True,
        excluded_bvids: set[str] | None = None,
    ) -> int:
        """Extract BV candidates from Bilibili's server-rendered search HTML.

        Bilibili collection-style BV inputs often point to an unavailable
        representative BV. The search result HTML still includes alternative
        playable BVs, so collect those before falling back to the slower browser
        scan.
        """
        total = 0
        try:
            page_count = max(1, int(max_pages or 1))
        except (TypeError, ValueError):
            page_count = 1
        request_timeout = self._configured_timeout_seconds(
            default=cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout"))
        )
        proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
        proxies = {"http": proxy, "https": proxy} if proxy else None
        headers = {
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        for page_num in range(1, page_count + 1):
            if not self.is_running or not self._has_bvid_capacity(bv_set, excluded_bvids):
                break
            page_url = str(url or "")
            if page_num > 1:
                page_url = self._build_search_page_url(page_url, page_num)
            try:
                response = requests.get(
                    page_url,
                    headers=headers,
                    timeout=request_timeout,
                    allow_redirects=True,
                    proxies=proxies,
                )
                if response.status_code >= 400:
                    break
            except requests.RequestException as exc:
                self.log(f"⚠️ Bilibili 静态搜索页解析失败: {exc}")
                break
            page_new_count = self._enqueue_new_bvids(
                self._extract_video_hrefs_from_text(response.text),
                bv_set,
                enqueue=enqueue,
                excluded_bvids=excluded_bvids,
            )
            total += page_new_count
            if page_new_count == 0 or not self._has_bvid_capacity(bv_set, excluded_bvids):
                break
        return total

    @classmethod
    def _extract_video_hrefs_from_text(cls, text: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"(?i)BV[0-9A-Za-z]{10}", str(text or "")):
            bvid = cls._normalize_bvid(match.group(0))
            if bvid in seen:
                continue
            seen.add(bvid)
            values.append(f"https://www.bilibili.com/video/{bvid}")
        return values

    def _wait_for_bilibili_candidates(self, page, *, timeout_ms: int = 15000) -> bool:
        """Wait briefly for Bilibili SPA video cards before extracting links."""
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        while self.is_running and not self.interrupt_requested and time.monotonic() < deadline:
            try:
                count = page.evaluate(
                    """() => document.querySelectorAll(
                        'a[href*="/video/BV"], [data-bvid], .bili-video-card, .video-card'
                    ).length"""
                )
                if int(count or 0) > 0:
                    return True
            except (PlaywrightError, TypeError, ValueError):
                return False
            if not self.interruptible_page_wait(page, 500):
                return False
        return False

    def _extract_video_hrefs(self, page) -> list[str]:
        """提供 `_extract_video_hrefs` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        try:
            hrefs = page.evaluate(r'''() => {
            const initialState = window.__INITIAL_STATE__;
            if (initialState && initialState.error && (initialState.error.code || initialState.error.trueCode)) {
                return [];
            }
            const values = new Set();
            const addBvid = (value) => {
                if (!value) return;
                const text = String(value);
                const matches = text.match(/BV[0-9A-Za-z]{10}/g) || [];
                for (const bvid of matches) values.add(`https://www.bilibili.com/video/${bvid}`);
            };
            const addSemanticBvids = (value) => {
                if (!value) return;
                const text = String(value);
                const patterns = [
                    /(?:href|src)=["'][^"']*\/video\/(BV[0-9A-Za-z]{10})/gi,
                    /\/video\/(BV[0-9A-Za-z]{10})/gi,
                    /player\.html\?[^"'<>]*[?&]bvid=(BV[0-9A-Za-z]{10})/gi,
                    /(?:^|[?"'&])bvid(?:["'\s:=]|%3D)+["']?(BV[0-9A-Za-z]{10})/gi,
                    /(?:bvid|bv_id)["']?\s*[:=]\s*["'](BV[0-9A-Za-z]{10})/gi,
                ];
                for (const pattern of patterns) {
                    let match;
                    while ((match = pattern.exec(text)) !== null) addBvid(match[1]);
                }
            };
            const semanticKey = (key) => {
                const lowered = String(key || '').toLowerCase();
                return /(bvid|bv_id|aid|arcurl|jump_url|url|href|link|uri|redirect|share)/.test(lowered);
            };
            const addBvidFromSemanticString = (key, value) => {
                if (!value) return;
                const text = String(value);
                if (semanticKey(key)) {
                    addBvid(text);
                    return;
                }
                if (/\/video\/BV[0-9A-Za-z]{10}/i.test(text) || /player\.html\?[^"'<>]*[?&]bvid=/i.test(text)) {
                    addBvid(text);
                }
            };
            const walk = (value, depth = 0, keyHint = '') => {
                if (!value || depth > 8) return;
                if (typeof value === 'string') {
                    addBvidFromSemanticString(keyHint, value);
                    return;
                }
                if (Array.isArray(value)) {
                    for (const entry of value) walk(entry, depth + 1, keyHint);
                    return;
                }
                if (typeof value !== 'object') return;
                for (const [key, entry] of Object.entries(value)) {
                    if (semanticKey(key)) {
                        addBvid(entry);
                    }
                    if (entry && typeof entry === 'object') walk(entry, depth + 1, key);
                    else if (typeof entry === 'string') addBvidFromSemanticString(key, entry);
                }
            };
            for (const anchor of document.querySelectorAll('a[href*="/video/BV"]')) {
                values.add(anchor.href);
            }
            for (const node of document.querySelectorAll('[data-bvid]')) {
                addBvid(node.getAttribute('data-bvid'));
            }
            walk(window.__INITIAL_STATE__);
            walk(window.__playinfo__);
            walk(window.__NEXT_DATA__);
            walk(window.__RENDER_DATA__);
            addSemanticBvids(document.documentElement.innerHTML);
            return Array.from(values);
        }''')
        except PlaywrightError:
            return []
        return hrefs or []

    def _enqueue_new_bvids(
        self,
        hrefs: list[str],
        bv_set: set[str],
        *,
        enqueue: bool = True,
        excluded_bvids: set[str] | None = None,
    ) -> int:
        """提供 `_enqueue_new_bvids` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        new_count = 0
        for href in hrefs:
            if not self._has_bvid_capacity(bv_set, excluded_bvids):
                break
            bvid = self._bvid_from_url(href)
            if not bvid:
                continue
            if bvid in bv_set:
                continue
            bv_set.add(bvid)
            if enqueue:
                self.raw_bv_queue.put(bvid)
            new_count += 1
        return new_count

    def _clean_name(self, name):
        """提供 `_clean_name` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        return self.parser.clean_name(name)

    def _build_search_page_url(self, current_url: str, page_num: int) -> str:
        """提供 `_build_search_page_url` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        parsed = urllib.parse.urlparse(current_url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["page"] = str(page_num)
        query["o"] = str((page_num - 1) * 30)
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))

    def _perform_login_scan(self, save_path):
        """提供 `_perform_login_scan` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    **self._playwright_launch_kwargs(
                        headless=False,
                        proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                    )
                )
                self._track_playwright_browser(browser)
                context = browser.new_context()
                page = context.new_page()
                if not self.interruptible_playwright_goto(
                    page,
                    "https://passport.bilibili.com/login",
                    timeout=self._configured_timeout_ms(default=60),
                ):
                    raise LoginCancelledError("用户在登录过程中终止任务")
                self.log("⏳ 请在弹出的窗口中扫码登录...")
                success = self.auth_service.wait_for_cookie_and_persist(
                    context=context,
                    cookie_name="SESSDATA",
                    save_path=save_path,
                    stop_check=lambda: not self.is_running,
                    max_attempts=60,
                )
                if success:
                    self.log("✅ 扫码成功，Cookie 已保存")
                    self._close_tracked_playwright_browser(browser)
                    self.api.load_cookies()
                    return
                if not self.is_running:
                    self._close_tracked_playwright_browser(browser)
                    raise LoginCancelledError("用户在登录过程中终止任务")
                self._close_tracked_playwright_browser(browser)
                raise LoginTimeoutError("等待 Bilibili 扫码登录超时")
        except (PlaywrightError, OSError) as exc:
            raise SpiderAuthError(f"Bilibili 登录失败: {exc}") from exc
        finally:
            browser = self._tracked_playwright_browser()
            if browser is not None:
                try:
                    self._close_tracked_playwright_browser(browser)
                except PlaywrightError:
                    pass
            self._clear_playwright_browser(browser)
