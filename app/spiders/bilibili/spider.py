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
                return None
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
            proxy_str = self.config.get("proxy", "")
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
                if self.api_pool_finished.is_set() and self.parsed_info_queue.empty():
                    break
                if not self.is_running: break
                try:
                    info = self.parsed_info_queue.get(timeout=0.5)
                    # 主线程只维护展示项和二次选择所需缓存，避免后台线程直接碰 UI 数据。
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
            self._join_worker_thread(self._browser_thread, "browser")
            self._join_worker_thread(self._api_pool_thread, "api")
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
                    final_download_queue.append(
                        self.task_builder.build_single_task(ep, referer=f"https://www.bilibili.com/video/{ep['bvid']}")
                    )
                    continue
                sub_dialog_items = []
                parent_label = info.get('season_title') or info.get('title') or "未命名项目"
                for i, ep in enumerate(episodes):
                    sub_dialog_items.append({
                        'title': ep.get('title') or f"第 {i + 1} 集",
                        'subtitle': f"P{str(ep.get('page_num', i + 1)).zfill(2)}",
                        'group_title': parent_label,
                        'index': i
                    })
                self.log(f"🔔 正在展开: {info.get('season_title') or info['title']}")
                sub_indices = self.ask_user_selection(sub_dialog_items)
                if not sub_indices:
                    continue
                for sub_idx in sub_indices:
                    ep = episodes[sub_idx]
                    final_download_queue.append(self.task_builder.build_episode_task(info, ep, sub_idx))
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
            self.sig_finished.emit()

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
            max_pages = int(self.config.get('max_pages', 1) or 1)
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

    def _execute_input_route(self, route: BilibiliInputRoute, *, max_pages: int) -> None:
        if route.kind == "bvid":
            self.log("Bilibili route: direct BV video")
            self.raw_bv_queue.put(route.value)
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
                cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout")),
            )
            response = requests.get(candidate, headers=HEADERS, timeout=request_timeout, allow_redirects=True)
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
                return self._keyword_route(bvid)
            return BilibiliInputRoute("bvid", bvid)
        aid = self._aid_from_text(value)
        if aid:
            return BilibiliInputRoute("aid", aid)
        return self._keyword_route(value)

    def _keyword_route(self, keyword: str) -> BilibiliInputRoute:
        search_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(str(keyword or ''))}"
        return BilibiliInputRoute("keyword", search_url, {"is_search": True, "is_space": False})

    @staticmethod
    def _looks_like_collection_bvid_hint(raw_text: str) -> bool:
        lowered = str(raw_text or "").lower()
        return any(marker in lowered for marker in ("合集", "系列", "列表", "收藏", "collection", "season", "series"))

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
            return BilibiliInputRoute("bvid", bvid)
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

        executor = ThreadPoolExecutor(
            max_workers=cfg.get("bilibili", "api_workers", get_setting_default("bilibili", "api_workers"))
        )
        try:
            while True:
                if self.browser_finished.is_set() and self.raw_bv_queue.empty():
                    break
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
                                self.log(f"⚠️ Bilibili API 未返回可用视频信息: {raw_id}")
                        except SpiderParseError as exc:
                            self.log(f"⚠️ 视频信息解析失败: {exc}")
                        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                            self.log(f"⚠️ API 处理异常: {exc}")
                    future.add_done_callback(callback)
                except queue.Empty:
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
    def _scan_with_browser_queue(self, url, max_pages=1, is_search=False, is_space=False):
        """提供 `_scan_with_browser_queue` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        bv_set = set()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                self._track_playwright_browser(browser)
                page = browser.new_page()
                self._restore_scan_cookies(page)
                current_url = url
                if not self.interruptible_playwright_goto(page, url, timeout=60000):
                    return
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
                                    if not self.interruptible_playwright_goto(page, target_video_url, timeout=60000):
                                        return
                                    page.wait_for_load_state("domcontentloaded")
                                    current_url = page.url
                                    is_search = False
                                    is_space = True
                    except (PlaywrightError, ValueError):
                        pass
                page_count = 0
                while self.is_running and page_count < max_pages:
                    page_count += 1
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 1000)")
                        if not self.interruptible_sleep(0.3):
                            break
                    # 某些列表页会在滚动到底部后才补全卡片，因此空页时需要重新抓取一次。
                    new_count = self._scan_page_for_new_bvids(page, bv_set)
                    self.log(f"   📄 第 {page_count} 页: 发现 {new_count} 个")
                    if new_count == 0:
                        break
                    if page_count < max_pages:
                        if is_search:
                            next_page = page_count + 1
                            next_url = self._build_search_page_url(page.url, next_page)
                            current_url = next_url
                            if not self.interruptible_playwright_goto(page, next_url, timeout=60000):
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

    def _scan_page_for_new_bvids(self, page, bv_set: set[str]) -> int:
        """提取当前页新增 BV；若首轮为空则补滚动一次再重试。"""
        new_count = self._enqueue_new_bvids(self._extract_video_hrefs(page), bv_set)
        if new_count > 0:
            return new_count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        if not self.interruptible_sleep(1):
            return new_count
        return self._enqueue_new_bvids(self._extract_video_hrefs(page), bv_set)

    def _extract_video_hrefs(self, page) -> list[str]:
        """提供 `_extract_video_hrefs` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        hrefs = page.evaluate('''() => {
            const anchors = document.querySelectorAll('a[href*="/video/BV"]');
            return Array.from(anchors).map(a => a.href);
        }''')
        return hrefs or []

    def _enqueue_new_bvids(self, hrefs: list[str], bv_set: set[str]) -> int:
        """提供 `_enqueue_new_bvids` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        new_count = 0
        for href in hrefs:
            bvid = self._bvid_from_url(href)
            if not bvid:
                continue
            if bvid in bv_set:
                continue
            bv_set.add(bvid)
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
                browser = p.chromium.launch(headless=False)
                self._track_playwright_browser(browser)
                context = browser.new_context()
                page = context.new_page()
                if not self.interruptible_playwright_goto(page, "https://passport.bilibili.com/login", timeout=60000):
                    raise LoginCancelledError("鐢ㄦ埛鍦ㄧ櫥褰曡繃绋嬩腑缁堟浠诲姟")
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
