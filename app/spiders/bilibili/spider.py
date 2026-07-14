"""Bilibili spider built as a scan -> parse -> assemble pipeline."""

import os
import re
import time
import requests
import urllib.parse
import threading
import queue
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import Error as PlaywrightError, sync_playwright
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
from shared.runtime_options import DomainPolicyViolation
from app.spiders.base import BaseSpider
from app.spiders.bilibili import input_router
from app.spiders.bilibili.input_router import BilibiliInputRoute
from app.spiders.bilibili.parser import BilibiliParser
from app.spiders.bilibili.task_builder import BilibiliTaskBuilder
from app.debug_logger import debug_logger
from app.models import VideoItem
from app.services.auth_service import AuthService
from app.utils.bilibili_wbi import BILIBILI_WBI_SIGNER
from app.utils.user_agents import resolve_user_agent

HEADERS = {
    'User-Agent': resolve_user_agent(
        "bilibili",
        None,
        configured_user_agent=cfg.get("bilibili", "user_agent", DEFAULT_USER_AGENT),
        default_user_agent=DEFAULT_USER_AGENT,
    ),
    'Referer': 'https://www.bilibili.com'
}


@dataclass(frozen=True)
class BilibiliBrowserPageState:
    kind: str
    reason: str = ""
    terminal: bool = False

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
            BILIBILI_WBI_SIGNER.update_from_nav_data(resp.get("data") if isinstance(resp, dict) else None)
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

    def _signed_api_get(
        self,
        endpoint: str,
        params: dict[str, object],
        *,
        unsigned_endpoint: str | None = None,
    ) -> tuple[requests.Response, bool, str]:
        headers = getattr(self.sess, "headers", None)
        if not isinstance(headers, dict):
            headers = HEADERS
        with self._session_guard():
            signed_params, signed = BILIBILI_WBI_SIGNER.sign_params(
                params,
                request_get=self.sess.get,
                headers=headers,
                timeout=self._request_timeout(),
            )
            request_endpoint = endpoint if signed or not unsigned_endpoint else unsigned_endpoint
            response = self.sess.get(request_endpoint, params=signed_params, timeout=self._request_timeout())
        response_url = getattr(response, "url", None)
        if not isinstance(response_url, str) or not response_url:
            response_url = f"{request_endpoint}?{urllib.parse.urlencode(signed_params)}"
        return response, signed, response_url

    def _unsigned_api_get(
        self,
        endpoint: str,
        params: dict[str, object],
    ) -> tuple[requests.Response, str]:
        with self._session_guard():
            response = self.sess.get(endpoint, params=params, timeout=self._request_timeout())
        response_url = getattr(response, "url", None)
        if not isinstance(response_url, str) or not response_url:
            response_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        return response, response_url

    def get_video_info(self, bvid: str | None = None, trace_id=None, *, aid: str | int | None = None):
        """Fetch Bilibili video detail by bvid, or by aid for legacy av links."""
        target = str(aid if aid is not None else bvid or "").strip()
        if not target:
            raise SpiderParseError("missing Bilibili video id")
        query_key = "aid" if aid is not None else "bvid"
        try:
            endpoint = "https://api.bilibili.com/x/web-interface/view"
            response, signed, request_url = self._signed_api_get(endpoint, {query_key: target})
            resp = response.json()
            if not isinstance(resp, dict):
                raise ValueError("unexpected Bilibili video detail response")
            unsigned_retry_attempted = False
            unsigned_retry_used = False
            if signed and resp.get("code") != 0:
                unsigned_retry_attempted = True
                try:
                    retry_response, retry_url = self._unsigned_api_get(endpoint, {query_key: target})
                    retry_resp = retry_response.json()
                    if not isinstance(retry_resp, dict):
                        raise ValueError("unexpected unsigned Bilibili video detail response")
                    if retry_resp.get("code") == 0:
                        response = retry_response
                        resp = retry_resp
                        request_url = retry_url
                        signed = False
                        unsigned_retry_used = True
                except (requests.RequestException, ValueError, TypeError) as retry_exc:
                    debug_logger.log_exception(
                        "BiliAPI",
                        "get_video_info_unsigned_retry",
                        retry_exc,
                        context={"bvid": bvid, "aid": aid},
                        trace_id=trace_id,
                    )
            data = resp.get('data') or {}
            debug_logger.log_api(
                component="BiliAPI",
                api_name="get_video_info",
                request={
                    "trace_id": trace_id,
                    "url": request_url,
                    "bvid": bvid,
                    "aid": aid,
                    "wbi_signed": signed,
                    "unsigned_retry_attempted": unsigned_retry_attempted,
                    "unsigned_retry_used": unsigned_retry_used,
                },
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
            endpoint = "https://api.bilibili.com/x/player/wbi/playurl"
            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": 120,
                "fnval": fnval,
                "fourk": 1,
                "platform": "pc",
            }
            response, signed, request_url = self._signed_api_get(
                endpoint,
                params,
                unsigned_endpoint="https://api.bilibili.com/x/player/playurl",
            )
            return request_url, response.status_code, response.json(), signed
        request_url, http_status, resp, signed = _request(4048)
        request_mode = 4048
        if resp['code'] != 0 or 'data' not in resp or 'dash' not in resp['data']:
            request_url, http_status, resp, signed = _request(80)
            request_mode = 80
        if resp.get("code") != 0 or "data" not in resp:
            raise StreamResolveError(f"B站取流失败: code={resp.get('code')}")
        dash = resp.get('data', {}).get('dash', {})
        video_stream = dash.get('video', [{}])[0] if dash.get('video') else {}
        audio_stream = dash.get('audio', [{}])[0] if dash.get('audio') else {}
        debug_logger.log_api(
            component="BiliAPI",
            api_name="get_play_url",
            request={
                "trace_id": trace_id,
                "url": request_url,
                "bvid": bvid,
                "cid": cid,
                "fnval": request_mode,
                "wbi_signed": signed,
            },
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

    BROWSER_EMPTY_TEXT_MARKERS = (
        "空间主人还没投过视频",
        "这里什么也没有",
        "暂无视频",
        "暂无投稿",
        "没有相关数据",
        "没有找到相关结果",
        "没有更多内容",
        "还没有发布任何视频",
        "未找到相关内容",
    )
    BROWSER_RISK_TEXT_MARKERS = (
        "安全验证",
        "验证码",
        "请完成验证",
        "访问过于频繁",
        "网络环境存在异常",
        "账号存在风险",
        "风控",
        "滑块验证",
        "人机验证",
    )
    BROWSER_LOGIN_TEXT_MARKERS = (
        "扫码登录",
        "密码登录",
        "请先登录",
        "登录后继续",
        "请登录后",
    )

    def __init__(self, keyword: str, config: dict):
        """初始化当前实例并准备运行所需的状态，供 `BilibiliSpider` 使用。"""
        super().__init__(keyword, config)
        self.parser = BilibiliParser()
        self.task_builder = BilibiliTaskBuilder(self.parser)
        self.auth_service = AuthService()
        self.user_agent = resolve_user_agent(
            "bilibili",
            self.config,
            configured_user_agent=cfg.get("bilibili", "user_agent", DEFAULT_USER_AGENT),
            default_user_agent=DEFAULT_USER_AGENT,
        )
        HEADERS["User-Agent"] = self.user_agent
        self._browser_thread: threading.Thread | None = None
        self._api_pool_thread: threading.Thread | None = None
        self._worker_api_local = threading.local()
        self._worker_apis: list[BiliAPI] = []
        self._worker_apis_lock = threading.RLock()

    def _bilibili_cookie_file(self) -> str:
        return cfg.get(
            "auth",
            "bilibili_cookie_file",
            cfg.get("bilibili", "auth_file", get_setting_default("bilibili", "auth_file")),
        )

    def _bilibili_request_timeout_seconds(self) -> int:
        return self._configured_timeout_seconds(
            default=cfg.get("bilibili", "timeout", get_setting_default("bilibili", "timeout"))
        )

    def _bilibili_api_worker_count(self, total: int | None = None) -> int:
        try:
            configured = int(
                (getattr(self, "config", {}) or {}).get(
                    "api_workers",
                    cfg.get("bilibili", "api_workers", get_setting_default("bilibili", "api_workers")),
                )
            )
        except (TypeError, ValueError):
            configured = int(get_setting_default("bilibili", "api_workers"))
        count = max(1, min(configured, 16))
        if total is not None:
            count = min(count, max(1, int(total)))
        return count

    def _worker_api_guard(self) -> threading.RLock:
        lock = getattr(self, "_worker_apis_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._worker_apis_lock = lock
        return lock

    def _worker_api_for_thread(self) -> BiliAPI:
        local = getattr(self, "_worker_api_local", None)
        if local is None:
            local = threading.local()
            self._worker_api_local = local
        api = getattr(local, "api", None)
        if api is not None:
            return api
        parser = getattr(self, "parser", None) or BilibiliParser()
        api = BiliAPI(self._bilibili_cookie_file(), parser=parser)
        api.request_timeout = self._bilibili_request_timeout_seconds()
        local.api = api
        with self._worker_api_guard():
            apis = getattr(self, "_worker_apis", None)
            if apis is None:
                apis = []
                self._worker_apis = apis
            apis.append(api)
        return api

    def _close_worker_apis(self) -> None:
        with self._worker_api_guard():
            apis = list(getattr(self, "_worker_apis", []) or [])
            self._worker_apis = []
        for api in apis:
            try:
                api.close()
            except Exception as exc:
                debug_logger.log_exception("BilibiliSpider", "close_worker_api", exc)

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
        default_pages = get_setting_default("bilibili", "max_pages")
        value = (getattr(self, "config", {}) or {}).get(
            "max_pages",
            cfg.get("bilibili", "max_pages", default_pages),
        )
        if str(value).strip().lower() in {"max", "unlimited"}:
            return 9999
        try:
            return max(1, min(int(value), 9999))
        except (TypeError, ValueError):
            return int(default_pages)

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

    def _resolve_download_item(self, task: dict, api: BiliAPI | None = None) -> VideoItem | None:
        """Resolve one Bilibili task into a download item without emitting it."""
        self.log(f"🎬 解析流: {task['file_name'][:15]}...")
        try:
            api = api or self.api
            v_url, a_url, q_id = api.get_play_url(task['bvid'], task['cid'], trace_id=task['trace_id'])
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
            cookie_dict = api.snapshot_cookies()
            meta = {
                "trace_id": task["trace_id"],
                "content_type": "video",
                "media_label": "视频",
                "audio_url": a_url,
                "ua": getattr(self, "user_agent", HEADERS["User-Agent"]),
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
            item = VideoItem(url=v_url, title=os.path.splitext(task["file_name"])[0], source="bilibili")
            item.meta = meta
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
            return item
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
            return None

    def _process_download_task(self, task: dict) -> bool:
        """逐条取流并提交下载，单条失败不影响后续任务继续执行。"""
        item = self._resolve_download_item(task, api=getattr(self, "api", None))
        if item is None:
            self.interruptible_sleep(0.5)
            return False
        self.emit_video(url=item.url, title=item.title, source=item.source, meta=item.meta)
        self.interruptible_sleep(0.5)
        return True

    def _process_download_tasks_async(self, tasks: list[dict]) -> tuple[int, int]:
        """Resolve Bilibili play URLs concurrently, then emit ready items in batches."""
        task_list = list(tasks or [])
        if not task_list:
            return 0, 0
        worker_count = self._bilibili_api_worker_count(len(task_list))
        if worker_count <= 1 or len(task_list) == 1:
            success_count = 0
            failure_count = 0
            for task in task_list:
                if not self.is_running:
                    break
                if self._process_download_task(task):
                    success_count += 1
                else:
                    failure_count += 1
            return success_count, failure_count

        self.debug_state(
            action="download_submit_pool_start",
            message="Bilibili 并发解析播放流并批量提交下载项",
            status_code="BILI_SUBMIT_POOL_START",
            details={"task_count": len(task_list), "worker_count": worker_count},
        )
        success_count = 0
        failure_count = 0
        ready_items: list[VideoItem] = []

        def resolve_one(task: dict) -> VideoItem | None:
            if not self.is_running:
                return None
            return self._resolve_download_item(task, api=self._worker_api_for_thread())

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="bili-submit") as executor:
            future_map = {executor.submit(resolve_one, task): task for task in task_list}
            for future in as_completed(future_map):
                if not self.is_running:
                    break
                try:
                    item = future.result()
                except Exception as exc:
                    task = future_map[future]
                    failure_count += 1
                    self.log(f"   ❌ 获取流失败: {exc}")
                    self.debug_state(
                        action="resolve_stream_worker_failed",
                        message="Bilibili 并发取流线程失败",
                        status_code="BILI_STREAM_WORKER_FAIL",
                        context={
                            "trace_id": task.get("trace_id"),
                            "bvid": task.get("bvid"),
                            "cid": task.get("cid"),
                        },
                        details={"file_name": task.get("file_name"), "error": str(exc)},
                        level="ERROR",
                        trace_id=task.get("trace_id"),
                    )
                    continue
                if item is None:
                    failure_count += 1
                    continue
                ready_items.append(item)
                success_count += 1

        emitted = self.emit_videos(ready_items)
        if emitted != len(ready_items):
            failure_count += len(ready_items) - emitted
            success_count = max(0, success_count - (len(ready_items) - emitted))
        return success_count, failure_count

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
            cookie_file = self._bilibili_cookie_file()
            self.api = BiliAPI(cookie_file, parser=self.parser)
            self.api.request_timeout = self._bilibili_request_timeout_seconds()
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
                if not self.is_running:
                    break
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
            success_count, failure_count = self._process_download_tasks_async(final_download_queue)
            self.log(f"🎉 全部完成: 成功 {success_count}/{len(final_download_queue)} | 失败 {failure_count}")
        finally:
            self._close_worker_apis()
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

    URL_TRAILING_PUNCTUATION = input_router.URL_TRAILING_PUNCTUATION
    COLLECTION_PATH_MARKERS = input_router.COLLECTION_PATH_MARKERS
    COLLECTION_QUERY_KEYS = input_router.COLLECTION_QUERY_KEYS
    UID_LABEL_PATTERN = input_router.UID_LABEL_PATTERN
    BVID_TEXT_PATTERN = input_router.BVID_TEXT_PATTERN
    AVID_TEXT_PATTERN = input_router.AVID_TEXT_PATTERN
    SHORT_LINK_HOSTS = input_router.SHORT_LINK_HOSTS
    MIN_PLAIN_UID_DIGITS = input_router.MIN_PLAIN_UID_DIGITS

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
        return input_router.extract_first_url(raw_text)

    @classmethod
    def _strip_url_trailing_punctuation(cls, value: str) -> str:
        return input_router.strip_url_trailing_punctuation(value)

    def _resolve_short_share_url(self, url: str) -> str:
        """Resolve Bilibili short share links to their final destination URL."""
        candidate = str(url or "").strip()
        if candidate and not candidate.lower().startswith(("http://", "https://")):
            if any(host in candidate.lower() for host in self.SHORT_LINK_HOSTS):
                candidate = f"https://{candidate.lstrip('/')}"
            elif candidate.lower().startswith(("www.bilibili.com/", "bilibili.com/")):
                candidate = f"https://{candidate.lstrip('/')}"
        if not self._url_matches_hosts(candidate, self.SHORT_LINK_HOSTS, allow_subdomains=False):
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
            request_kwargs = self._restricted_public_request_kwargs(
                candidate,
                allowed_hosts=(*self.SHORT_LINK_HOSTS, "bilibili.com"),
            )
            response = requests.get(
                candidate,
                headers=HEADERS,
                timeout=request_timeout,
                allow_redirects=True,
                proxies=proxies,
                **request_kwargs,
            )
            resolved = response.url or candidate
            if hasattr(self, "sig_log"):
                self.log(f"🔗 [短链解析] {candidate} -> {resolved}")
            return resolved
        except (requests.RequestException, DomainPolicyViolation) as exc:
            if hasattr(self, "sig_log"):
                self.log(f"⚠️ [短链解析失败] {exc}")
            return candidate

    def _normalize_keyword(self, raw_text: str) -> str:
        """Normalize share text and short links before route classification."""
        extracted = self._extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _classify_input(self, raw_text: str) -> BilibiliInputRoute:
        return input_router.classify_input(raw_text, normalize_keyword=self._normalize_keyword)

    def _keyword_route(self, keyword: str) -> BilibiliInputRoute:
        return input_router.keyword_route(keyword)

    @classmethod
    def _looks_like_collection_bvid_hint(cls, raw_text: str) -> bool:
        return input_router.looks_like_collection_bvid_hint(raw_text)

    def _collection_bvid_fallback_urls(self, bvid: str, raw_text: str = "") -> list[str]:
        return input_router.collection_bvid_fallback_urls(bvid, raw_text)

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
        return input_router.route_url(url)

    @classmethod
    def _is_collection_like_url(cls, parsed: urllib.parse.ParseResult) -> bool:
        return input_router.is_collection_like_url(parsed)

    @staticmethod
    def _is_bvid_ugc_season_entry_url(parsed: urllib.parse.ParseResult) -> bool:
        return input_router.is_bvid_ugc_season_entry_url(parsed)

    @staticmethod
    def _normalize_bvid(value: str) -> str:
        return input_router.normalize_bvid(value)

    @classmethod
    def _bvid_from_url(cls, url: str) -> str:
        return input_router.bvid_from_url(url)

    @classmethod
    def _bvid_from_text(cls, text: str) -> str:
        return input_router.bvid_from_text(text)

    @classmethod
    def _aid_from_text(cls, text: str) -> str:
        return input_router.aid_from_text(text)

    @staticmethod
    def _aid_from_url(url: str) -> str:
        return input_router.aid_from_url(url)

    def _worker_api_pool(self):
        """提供 `_worker_api_pool` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        def process_one(raw_id):
            """Resolve one queued bvid/aid into structured video info."""
            if not self.is_running:
                return None, None
            api = self._worker_api_for_thread()
            if isinstance(raw_id, dict):
                aid = str(raw_id.get("aid") or "").strip()
                if aid:
                    result = api.get_video_info(None, trace_id=f"bilibili_av{aid}", aid=aid)
                    error = None if result else api.consume_video_info_error(aid)
                    return result, error
                bvid = str(raw_id.get("bvid") or "").strip()
            else:
                bvid = str(raw_id or "").strip()
            if not bvid:
                return None, None
            result = api.get_video_info(bvid, trace_id=f"bilibili_{bvid}")
            error = None if result else api.consume_video_info_error(bvid)
            return result, error

        try:
            api_workers = self._bilibili_api_worker_count()
        except (TypeError, ValueError):
            api_workers = 1
        executor = ThreadPoolExecutor(max_workers=api_workers, thread_name_prefix="bili-detail")
        try:
            while True:
                if not self.is_running:
                    break
                try:
                    bvid = self.raw_bv_queue.get(timeout=0.5)
                    future = executor.submit(process_one, bvid)
                    def callback(f, raw_id=bvid):
                        
                        if not self.is_running:
                            return
                        try:
                            res, error = f.result()
                            if res:
                                self.parsed_info_queue.put(res)
                            else:
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

    @classmethod
    def _classify_bilibili_page_snapshot(cls, snapshot: dict | None) -> BilibiliBrowserPageState:
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        ready_state = str(snapshot.get("ready_state") or "").lower()
        url = str(snapshot.get("url") or "")
        title = str(snapshot.get("title") or "")
        body_text = str(snapshot.get("body_text") or "")
        combined_text = f"{title}\n{body_text}"
        try:
            candidate_count = int(snapshot.get("candidate_count") or 0)
        except (TypeError, ValueError):
            candidate_count = 0
        try:
            risk_marker_count = int(snapshot.get("risk_marker_count") or 0)
        except (TypeError, ValueError):
            risk_marker_count = 0
        try:
            login_marker_count = int(snapshot.get("login_marker_count") or 0)
        except (TypeError, ValueError):
            login_marker_count = 0

        if ready_state not in {"interactive", "complete"}:
            return BilibiliBrowserPageState("not_loaded", f"readyState={ready_state or 'unknown'}")
        if candidate_count > 0:
            return BilibiliBrowserPageState("ready", f"candidates={candidate_count}")
        if risk_marker_count > 0 or any(marker in combined_text for marker in cls.BROWSER_RISK_TEXT_MARKERS):
            return BilibiliBrowserPageState("risk", "检测到安全验证或风控提示", terminal=True)
        if login_marker_count > 0 or any(marker in combined_text for marker in cls.BROWSER_LOGIN_TEXT_MARKERS):
            return BilibiliBrowserPageState("login", "检测到登录拦截提示", terminal=True)
        has_empty_marker = any(marker in combined_text for marker in cls.BROWSER_EMPTY_TEXT_MARKERS)
        has_nonzero_video_counter = bool(re.search(r"(?:视频|投稿)\s*(?:999\+|[1-9]\d*)", combined_text))
        if has_empty_marker and has_nonzero_video_counter:
            return BilibiliBrowserPageState("risk", "页面空态与非零视频计数矛盾，疑似风控或接口拦截", terminal=True)
        if has_empty_marker:
            return BilibiliBrowserPageState("empty", "页面明确返回空结果", terminal=True)
        if url and url != "about:blank" and not body_text.strip():
            return BilibiliBrowserPageState("not_loaded", "页面主体为空")
        return BilibiliBrowserPageState("unknown", "页面已加载但暂未发现候选视频")

    def _read_bilibili_browser_page_state(self, page) -> BilibiliBrowserPageState:
        try:
            snapshot = page.evaluate(
                r"""() => {
                const riskSelector = [
                    'iframe[src*="captcha"]',
                    'iframe[src*="geetest"]',
                    '[class*="captcha"]',
                    '[class*="geetest"]',
                    '[id*="captcha"]',
                    '[id*="geetest"]'
                ].join(',');
                const loginSelector = [
                    '.login-panel',
                    '.bili-mini-mask',
                    '.bili-login',
                    '.login-scan-box',
                    '[class*="login"] [class*="scan"]'
                ].join(',');
                return {
                    ready_state: document.readyState || '',
                    title: document.title || '',
                    url: location.href || '',
                    body_text: String((document.body && document.body.innerText) || '').slice(0, 3000),
                    candidate_count: document.querySelectorAll(
                        'a[href*="/video/BV"], [data-bvid], .bili-video-card, .video-card'
                    ).length,
                    risk_marker_count: document.querySelectorAll(riskSelector).length,
                    login_marker_count: document.querySelectorAll(loginSelector).length
                };
            }"""
            )
        except (PlaywrightError, TypeError, ValueError):
            return BilibiliBrowserPageState("unknown", "无法读取页面状态")
        return self._classify_bilibili_page_snapshot(snapshot)

    def _log_bilibili_terminal_page_state(
        self,
        state: BilibiliBrowserPageState,
        *,
        url: str,
        page_count: int | None = None,
    ) -> None:
        if state.kind == "empty":
            message = "⚠️ Bilibili 页面已加载，但当前页面明确没有可采集视频"
            level = "WARN"
            status_code = "BILI_PAGE_EMPTY"
        elif state.kind == "risk":
            message = "⛔ Bilibili 页面已加载，但疑似触发安全验证或风控"
            level = "ERROR"
            status_code = "BILI_RISK_CONTROL"
        elif state.kind == "login":
            message = "🔒 Bilibili 页面已加载，但被登录提示拦截"
            level = "WARN"
            status_code = "BILI_LOGIN_REQUIRED"
        else:
            return
        self.log(f"{message}: {state.reason}")
        self.debug_state(
            "browser_page_terminal_state",
            message=message,
            status_code=status_code,
            details={"url": url, "page": page_count, "state": state.kind, "reason": state.reason},
            level=level,
        )

    @staticmethod
    def _space_video_url_from_href(href: str) -> str:
        href_text = str(href or "").strip()
        if href_text.startswith("//"):
            href_text = f"https:{href_text}"
        uid_match = re.search(r"space\.bilibili\.com/(\d+)", href_text)
        if not uid_match:
            return ""
        return f"https://space.bilibili.com/{uid_match.group(1)}/video"

    @classmethod
    def _should_use_static_search_shortcut(cls, url: str) -> bool:
        parsed = urllib.parse.urlparse(str(url or ""))
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        keyword = " ".join(query.get("keyword", []))
        decoded = urllib.parse.unquote(f"{keyword} {url}")
        lowered = decoded.lower()
        collection_markers = (
            "collection",
            "season",
            "series",
            "\u5408\u96c6",
            "\u7cfb\u5217",
            "\u5217\u8868",
        )
        return bool(cls._bvid_from_text(decoded) or any(marker in lowered for marker in collection_markers))

    def _extract_search_up_space_video_url(self, page) -> tuple[str, str]:
        try:
            candidate = page.evaluate(
                r"""() => {
                const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
                const classChain = (node) => {
                    const parts = [];
                    let current = node;
                    for (let depth = 0; current && depth < 5; depth += 1, current = current.parentElement) {
                        parts.push(`${current.id || ''} ${current.className || ''}`);
                    }
                    return parts.join(' ').toLowerCase();
                };
                const userContextRe = /(user-list|b-user-video-card|user-card|search-user|upuser|user-item|bili-user)/;
                const videoContextRe = /(bili-video-card|video-card|video-list)/;
                const nameOrAvatarRe = /(avatar|face|user-name|username|name|up-name|author)/;
                const profileHintRe = /(\u7c89\u4e1d|\u6295\u7a3f|\u89c6\u9891|\u5173\u6ce8|UP\u4e3b|\u7a7a\u95f4)/;
                const scored = [];
                for (const anchor of document.querySelectorAll('a[href*="space.bilibili.com"]')) {
                    const href = anchor.href || anchor.getAttribute('href') || '';
                    if (!/space\.bilibili\.com\/\d+/.test(href)) continue;
                    const context = anchor.closest(
                        '.user-list, .b-user-video-card, [class*="user-card"], [class*="search-user"], ' +
                        '[class*="upuser"], [class*="user-item"], [class*="bili-user"]'
                    ) || anchor.parentElement;
                    const chain = classChain(context || anchor);
                    const anchorClass = String(anchor.className || '').toLowerCase();
                    const contextText = clean((context && context.innerText) || '');
                    let score = 0;
                    if (userContextRe.test(chain)) score += 8;
                    if (nameOrAvatarRe.test(anchorClass)) score += 3;
                    if (profileHintRe.test(contextText)) score += 3;
                    if (videoContextRe.test(chain) && !userContextRe.test(chain)) score -= 8;
                    if (score >= 5) {
                        scored.push({
                            href,
                            name: clean(anchor.innerText || anchor.getAttribute('title') || anchor.getAttribute('aria-label') || ''),
                            score,
                        });
                    }
                }
                scored.sort((a, b) => b.score - a.score);
                return scored[0] || null;
            }"""
            )
        except (PlaywrightError, TypeError, ValueError):
            return "", ""
        if not isinstance(candidate, dict):
            return "", ""
        return self._space_video_url_from_href(str(candidate.get("href") or "")), str(candidate.get("name") or "").strip()

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
        if (is_search or "search.bilibili.com" in str(url or "").lower()) and self._should_use_static_search_shortcut(url):
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
                        headless=self._browser_headless(),
                        proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                    )
                )
                self._track_playwright_browser(browser)
                context = browser.new_context(
                    **self._playwright_context_kwargs(
                        user_agent=HEADERS.get("User-Agent", DEFAULT_USER_AGENT),
                        referer="https://www.bilibili.com/",
                        viewport={"width": 1280, "height": 800},
                    )
                )
                self._apply_stealth_to_context(context)
                page = context.new_page()
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
                initial_state = self._read_bilibili_browser_page_state(page)
                if initial_state.terminal:
                    self._log_bilibili_terminal_page_state(initial_state, url=str(getattr(page, "url", url) or url))
                    return _scan_result()
                # UP 主拦截 (仅针对关键词搜索模式)
                if is_search and "search.bilibili.com" in url:
                    try:
                        target_video_url, up_name = self._extract_search_up_space_video_url(page)
                        if target_video_url:
                            name_suffix = f": {up_name}" if up_name else ""
                            self.log(f"✨ 检测到 UP 主{name_suffix}")
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
                            redirected_state = self._read_bilibili_browser_page_state(page)
                            if redirected_state.terminal:
                                self._log_bilibili_terminal_page_state(
                                    redirected_state,
                                    url=str(getattr(page, "url", target_video_url) or target_video_url),
                                )
                                return _scan_result()
                    except (PlaywrightError, ValueError):
                        pass
                page_count = 0
                while self.is_running and page_count < max_pages:
                    page_count += 1
                    if page_count == 1:
                        page_state = self._wait_for_bilibili_candidates(
                            page,
                            timeout_ms=self._configured_timeout_ms(default=60),
                        )
                        if page_state.terminal:
                            self._log_bilibili_terminal_page_state(
                                page_state,
                                url=str(getattr(page, "url", current_url) or current_url),
                                page_count=page_count,
                            )
                            break
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

    def _wait_for_bilibili_candidates(self, page, *, timeout_ms: int = 15000) -> BilibiliBrowserPageState:
        """Wait briefly for Bilibili SPA video cards or a clear terminal page state."""
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        last_state = BilibiliBrowserPageState("unknown", "尚未读取页面状态")
        while self.is_running and not self.interrupt_requested and time.monotonic() < deadline:
            last_state = self._read_bilibili_browser_page_state(page)
            if last_state.kind == "ready" or last_state.terminal:
                return last_state
            if not self.interruptible_page_wait(page, 500):
                return BilibiliBrowserPageState("stopped", "用户停止或页面等待被中断")
        return last_state

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
        return input_router.build_search_page_url(current_url, page_num)

    def _perform_login_scan(self, save_path):
        """提供 `_perform_login_scan` 对应的内部辅助逻辑，供 `BilibiliSpider` 使用。"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    **self._playwright_launch_kwargs(
                        headless=self._browser_headless(login_window=True),
                        proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                    )
                )
                self._track_playwright_browser(browser)
                context = browser.new_context(
                    **self._playwright_context_kwargs(
                        user_agent=HEADERS.get("User-Agent", DEFAULT_USER_AGENT),
                        referer="https://www.bilibili.com/",
                        viewport={"width": 1280, "height": 800},
                    )
                )
                self._apply_stealth_to_context(context)
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
