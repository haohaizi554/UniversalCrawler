"""快手浏览器扫描与实时媒体流捕获。"""

import json
import os
import random
import re
import threading
import urllib.parse

import requests
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.config import DEFAULT_USER_AGENT, cfg, get_setting_default
from app.exceptions import CookieLoadError, CookieSaveError
from app.spiders.base import BaseSpider
from app.spiders.kuaishou.parser import KuaishouParser
from app.spiders.kuaishou.task_builder import KuaishouTaskBuilder
from app.services.auth_service import AuthService
from app.utils.user_agents import resolve_user_agent
from shared.network_proxy import requests_proxy_mapping
from shared.runtime_options import DomainPolicyViolation

class KuaishouSpider(BaseSpider):
    """快手爬虫，负责页面滚动扫描、任务选择和流监听。"""

    LIST_READY_TIMEOUT_MS = 30000
    PROFILE_SESSION_URL = "https://www.kuaishou.com/rest/v/profile/get"
    PROFILE_SESSION_TIMEOUT_MS = 8000
    NAVIGATION_ATTEMPTS = 3
    NETWORK_ERROR_MARKERS = (
        "网络异常，稍后重试",
        "网络异常",
        "请检查网络",
    )
    LOGIN_PROMPT_SELECTORS = (
        ".sidebar-login-button",
        ".login-btn",
        "button:has-text('登录')",
    )

    def __init__(self, keyword: str, config: dict):
        """配置解析器、任务装配器、认证服务和响应匹配状态。"""
        super().__init__(keyword, config)
        self.parser = KuaishouParser()
        self.task_builder = KuaishouTaskBuilder()
        self.auth_service = AuthService()
        self.user_agent = resolve_user_agent(
            "kuaishou",
            self.config,
            configured_user_agent=cfg.get("kuaishou", "user_agent", DEFAULT_USER_AGENT),
            default_user_agent=DEFAULT_USER_AGENT,
        )
        self._selected_indices: list[int] = []
        self._lock = threading.Lock()

    def _user_agent(self) -> str:
        return str(getattr(self, "user_agent", "") or DEFAULT_USER_AGENT)

    def _max_items_limit(self) -> int:
        """读取资源数量上限，并对非法配置回退默认值。"""
        default_limit = get_setting_default("kuaishou", "max_items")
        limit = self.config.get("max_items", cfg.get("kuaishou", "max_items", default_limit))
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return int(default_limit)

    def _build_proxy_cfg(self) -> dict[str, str] | None:
        """把有效代理地址转换为 Playwright 启动配置。"""
        proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
        if not proxy:
            return None
        self.log(f"🌍 使用代理: {proxy}")
        return {"server": proxy}

    def _load_saved_storage_state(self, auth_file: str) -> dict[str, list[dict]] | None:
        """读取完整 Playwright 状态，供创建有头或无头 context 时复用。"""
        if not os.path.exists(auth_file):
            return None
        try:
            storage_state = self.auth_service.load_playwright_storage_state(auth_file)
        except (CookieLoadError, OSError, TypeError, ValueError):
            self.log("⚠️ 本地登录态加载失败，继续尝试页面登录")
            return None
        if storage_state:
            self.log("📂 加载本地登录态成功")
        return storage_state

    def _create_browser_context(
        self, browser, auth_file: str, *, headless: bool = True
    ):
        """创建浏览器上下文；可见会话在首个真实页面中恢复 origin 存储。"""
        # fake-useragent 可能返回远旧于 Playwright 内核的版本，UA 与 JS 能力不一致会触发风控。
        runtime_user_agent = self._playwright_chromium_user_agent(browser, self._user_agent())
        if runtime_user_agent:
            self.user_agent = runtime_user_agent
        context_kwargs = self._playwright_context_kwargs(
            user_agent=runtime_user_agent or self._user_agent(),
            viewport={"width": 1280, "height": 800},
            referer="https://www.kuaishou.com/",
        )
        storage_state = self._load_saved_storage_state(auth_file)
        if storage_state and headless:
            # 无头会话没有闪窗问题，保留 Playwright 原生恢复以兼容 IndexedDB。
            context_kwargs["storage_state"] = storage_state
        elif storage_state:
            # Playwright 恢复 origins 时会在有头模式创建一个内部页面，逐个导航到 origin
            # 写入 localStorage 后再关闭，因此用户会看到一个一闪而过的小窗口。Cookie 可
            # 直接由 context 恢复；origin 存储改由 init script 写入首个真实页面。
            context_kwargs["storage_state"] = {
                "cookies": list(storage_state.get("cookies", []) or []),
                "origins": [],
            }
        try:
            context = browser.new_context(**context_kwargs)
        except PlaywrightError:
            if not storage_state:
                raise
            # 旧 Playwright 版本或历史 Cookie 字段可能无法被当前内核接受；清空状态后
            # 仍应允许用户重新登录，不能让模式切换直接终止整个爬虫。
            self.log("⚠️ 已保存登录态不兼容，改用空白浏览器上下文重新登录")
            context_kwargs.pop("storage_state", None)
            context = browser.new_context(**context_kwargs)
            storage_state = None
        if storage_state and not headless:
            self._install_saved_origin_storage(context, storage_state)
        self._apply_stealth_to_context(context)
        return context

    def _install_saved_origin_storage(self, context, storage_state: dict) -> None:
        """在真实页面加载前恢复快手 localStorage，避免 Playwright 创建临时恢复页。"""
        origins: dict[str, dict[str, str]] = {}
        for item in storage_state.get("origins", []) or []:
            if not isinstance(item, dict):
                continue
            origin = str(item.get("origin") or "").strip().rstrip("/")
            if not self._url_matches_hosts(
                origin, ("kuaishou.com", "chenzhongtech.com")
            ):
                continue
            values: dict[str, str] = {}
            for entry in item.get("localStorage", []) or []:
                if not isinstance(entry, dict) or entry.get("name") is None:
                    continue
                values[str(entry["name"])] = str(entry.get("value") or "")
            if values:
                origins[origin] = values
        if not origins:
            return
        encoded = json.dumps(origins, ensure_ascii=True, separators=(",", ":"))
        context.add_init_script(
            script=f"""
            (() => {{
                const savedOrigins = {encoded};
                const values = savedOrigins[location.origin];
                if (!values) return;
                for (const [name, value] of Object.entries(values)) {{
                    localStorage.setItem(name, value);
                }}
            }})();
            """
        )

    def _persist_authenticated_state(self, context, auth_file: str) -> bool:
        """在关闭当前浏览器前原子发布最新 Cookie 与 origin/localStorage。"""
        try:
            try:
                # 快手登录完成后可能把令牌写入 IndexedDB；默认 storage_state 不会包含它。
                storage_state = context.storage_state(indexed_db=True)
            except TypeError:
                # 兼容 Playwright 1.51 之前尚无 indexed_db 参数的运行环境。
                storage_state = context.storage_state()
            self.auth_service.save_json_file(auth_file, storage_state)
            return True
        except (CookieSaveError, OSError, TypeError, ValueError, PlaywrightError) as exc:
            self.log(f"⚠️ 快手登录态保存失败: {exc}")
            return False

    def _navigation_error_reason(self, page) -> str | None:
        """识别 Playwright 错误页和快手“网络异常”占位页。"""
        try:
            current_url = str(getattr(page, "url", "") or "").strip()
        except PlaywrightError:
            return "page_unavailable"
        if not current_url or current_url == "about:blank":
            return "blank_page"
        try:
            current_scheme = urllib.parse.urlsplit(current_url).scheme.lower()
        except ValueError:
            return "invalid_page_url"
        if current_scheme == "chrome-error":
            return "browser_network_error"
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
        except (PlaywrightError, AttributeError, TypeError, ValueError):
            return None
        if any(marker in str(body_text or "") for marker in self.NETWORK_ERROR_MARKERS):
            return "site_network_error"
        return None

    def _retry_network_error_in_place(self, page) -> bool:
        """优先点击快手错误页自己的刷新按钮，避免重复 goto 破坏 SPA 内部导航。"""
        for selector in ("button:has-text('刷新')", "[role='button']:has-text('刷新')"):
            try:
                refresh = page.locator(selector).first
                if not self._locator_visible(refresh):
                    continue
                refresh.click(timeout=2000)
                if not self.interruptible_page_wait(page, 2500):
                    return False
                return self._navigation_error_reason(page) is None
            except PlaywrightError:
                continue
        return False

    def _goto_with_retry(
        self,
        page,
        url: str,
        *,
        description: str,
        attempts: int = NAVIGATION_ATTEMPTS,
    ) -> bool:
        """重试导航，并把已渲染的站点网络错误页也视为失败。"""
        target_url = url.strip().strip("`")
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=self._configured_timeout_ms(default=60),
                    wait_until="domcontentloaded",
                ):
                    return False
                if not self.interruptible_page_wait(page, 1500):
                    return False
                error_reason = self._navigation_error_reason(page)
                if error_reason is None:
                    return True
                last_error = PlaywrightError(error_reason)
                self.log(
                    f"⚠️ {description}第 {attempt}/{attempts} 次加载返回网络错误页"
                )
                if attempt < attempts and self._retry_network_error_in_place(page):
                    return True
            except PlaywrightError as exc:
                last_error = exc
                self.log(f"⚠️ {description}失败，第 {attempt}/{attempts} 次重试: {exc}")
            if attempt < attempts and not self.interruptible_page_wait(page, min(1000 * attempt, 2500)):
                return False
        if last_error:
            self.log(f"❌ {description}失败: {last_error}")
        return False

    def _extract_first_url(self, raw_text: str) -> str:
        """从分享文案中提取第一个 URL；没有则回退原始输入。"""
        raw = str(raw_text or "").strip()
        match = re.search(r"https?://[^\s`，。！？；;,)）\]'\"]+", raw)
        candidate = match.group(0) if match else raw
        return candidate.rstrip("，。！？；;,.!?)）]}'\"")

    def _is_kuaishou_url(self, raw_text: str) -> bool:
        """判断输入是否为快手相关 URL。"""
        return self._url_matches_hosts(
            str(raw_text or ""),
            ("kuaishou.com", "chenzhongtech.com"),
        )

    def _is_detail_url(self, raw_text: str) -> bool:
        """识别快手单条作品详情链接。"""
        if not self._is_kuaishou_url(raw_text):
            return False
        parsed = urllib.parse.urlparse(str(raw_text or ""))
        path = parsed.path.lower()
        query_keys = {key.lower() for key in urllib.parse.parse_qs(parsed.query)}
        return "/short-video/" in path or "/fw/photo/" in path or "photoid" in query_keys

    def _resolve_short_share_url(self, url: str) -> str:
        """将快手短分享链解析为最终详情或主页链接。"""
        candidate = str(url or "").strip()
        if not self._is_kuaishou_url(candidate):
            return url
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.hostname or "").lower()
        is_short_link = host == "v.kuaishou.com" or (
            host in {"kuaishou.com", "www.kuaishou.com"}
            and parsed.path.lower().startswith("/f/")
        )
        if not is_short_link:
            return url
        try:
            proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
            proxies = requests_proxy_mapping(proxy)
            request_kwargs = self._restricted_public_request_kwargs(
                candidate,
                allowed_hosts=("kuaishou.com", "chenzhongtech.com"),
            )
            response = requests.get(
                candidate,
                headers={"User-Agent": self._user_agent()},
                timeout=self._configured_timeout_seconds(default=60),
                allow_redirects=True,
                proxies=proxies,
                **request_kwargs,
            )
            resolved = response.url or candidate
            self.log(f"🔗 [分享链接解析] {candidate} -> {resolved}")
            return resolved
        except (requests.RequestException, DomainPolicyViolation) as exc:
            self.log(f"⚠️ [分享链接解析失败] {exc}")
            return candidate

    def _normalize_keyword(self, raw_text: str) -> str:
        """兼容分享文案、短链和完整快手链接。"""
        extracted = self._extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _build_detail_request_headers(self) -> dict[str, str]:
        """构建分享详情页直连请求头。"""
        return {
            "User-Agent": self._user_agent(),
            "Referer": "https://www.kuaishou.com/",
        }

    def _extract_detail_id(self, url: str) -> str:
        """从快手详情链接中提取作品 ID。"""
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "photoId" in params:
            return params.get("photoId", [""])[0]
        path = parsed.path.rstrip("/")
        if "/short-video/" in path or "/fw/photo/" in path:
            return path.split("/")[-1]
        return ""

    def _extract_state_blob(self, html: str, prefix: str, suffix: str = "</script>") -> str:
        """从 HTML 中抽取指定状态脚本文本。"""
        if not html or prefix not in html:
            return ""
        start = html.find(prefix)
        if start < 0:
            return ""
        start += len(prefix)
        end = html.find(suffix, start)
        blob = html[start:end] if end >= 0 else html[start:]
        return blob.strip()

    def _load_json_blob(self, blob: str) -> dict:
        """尽量用 JSON 解析页面状态；失败时返回空字典。"""
        if not blob:
            return {}
        cleaned = blob.replace(
            ";(function(){var s;(s=document.currentScript||document.scripts[document.scripts.length-1]).parentNode.removeChild(s);}());",
            "",
        ).rstrip(" ;")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}

    def _extract_apollo_video_detail(self, payload: dict, detail_id: str) -> tuple[str, str]:
        """从 __APOLLO_STATE__ 中提取标题和直链。"""
        client = payload.get("defaultClient", {}) if isinstance(payload, dict) else {}
        detail = client.get(f"VisionVideoDetailPhoto:{detail_id}", {}) if isinstance(client, dict) else {}
        if not isinstance(detail, dict):
            return "", ""
        title = str(detail.get("caption") or "").strip()
        media_url = str(detail.get("photoUrl") or "").strip()
        return title, media_url

    def _fetch_share_detail_via_http(self, detail_url: str) -> tuple[str, str]:
        """通过纯 HTTP 抓取快手分享/详情页，避免弹浏览器。"""
        try:
            request_kwargs = self._restricted_public_request_kwargs(
                detail_url,
                allowed_hosts=("kuaishou.com", "chenzhongtech.com"),
            )
            proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
            proxies = requests_proxy_mapping(proxy)
            response = requests.get(
                detail_url,
                headers=self._build_detail_request_headers(),
                timeout=self._configured_timeout_seconds(default=60),
                allow_redirects=True,
                proxies=proxies,
                **request_kwargs,
            )
            response.raise_for_status()
        except (requests.RequestException, DomainPolicyViolation) as exc:
            self.log(f"⚠️ 快手分享详情页请求失败: {exc}")
            return "", ""

        detail_id = self._extract_detail_id(response.url or detail_url)
        if not detail_id:
            return "", ""

        apollo_blob = self._extract_state_blob(response.text, "window.__APOLLO_STATE__=")
        if apollo_blob:
            title, media_url = self._extract_apollo_video_detail(self._load_json_blob(apollo_blob), detail_id)
            if media_url:
                return title or "快手分享作品", media_url

        self.log("⚠️ 快手分享页未解析到 __APOLLO_STATE__ 视频直链，将回退浏览器链路")
        return "", ""

    def _try_direct_share_download(self) -> bool:
        """分享/详情链接优先走纯 HTTP 快路，成功则不再打开浏览器。"""
        if not self._is_detail_url(self.keyword):
            return False
        self.log("ℹ️ 优先尝试通过 HTTP 快速解析快手分享详情...")
        title, media_url = self._fetch_share_detail_via_http(self.keyword)
        if not media_url:
            return False
        trace_id = self.new_trace_id("share")
        self.debug_state(
            action="emit_share_task_http",
            message="快手分享链接已通过 HTTP 直连解析并提交到下载队列",
            status_code="KUAISHOU_SHARE_TASK_HTTP_EMIT",
            context={"trace_id": trace_id},
            details={"title": title, "stream_url": media_url, "referer": self.keyword},
        )
        self.emit_video(
            url=media_url,
            title=title,
            source="kuaishou",
            meta=self.task_builder.build_download_meta(trace_id, self.keyword, media_url, self._user_agent()),
        )
        self.log(f"✨ 已无浏览器解析分享作品: {title[:24]}...")
        return True

    @staticmethod
    def _share_media_response_url(response) -> str:
        """从详情页响应中筛出可提交给下载器的视频或 HLS 地址。"""
        try:
            url = str(response.url or "").strip()
            content_type = str(response.headers.get("content-type", "") or "").lower()
            resource_type = str(response.request.resource_type or "").lower()
        except (AttributeError, PlaywrightError):
            return ""
        if not url:
            return ""
        path = urllib.parse.urlsplit(url).path.lower()
        if (
            resource_type == "media"
            or content_type.startswith("video/")
            or "mpegurl" in content_type
            or path.endswith(".m3u8")
        ):
            return url
        return ""

    def _login_prompt_visible(self, page) -> bool:
        """识别明确的未登录入口；其优先级高于页面中任意内容头像。"""
        for selector in self.LOGIN_PROMPT_SELECTORS:
            try:
                if self._locator_visible(page.locator(selector).first):
                    return True
            except PlaywrightError:
                continue
        return False

    def _is_logged_in(self, page) -> bool:
        """用保守 DOM 信号兜底判断登录态，服务端接口可用时不依赖此结果。"""
        if self._login_prompt_visible(page):
            return False
        selectors = (
            ".header-user-avatar",
            ".user-avatar",
            ".down-box.login .user-item",
            ".down-box.login .user-item img[src]",
            ".down-box.login .text-fold",
            ".sidebar .down-box.login",
        )
        for selector in selectors:
            try:
                if self._locator_visible(page.locator(selector).first):
                    return True
            except PlaywrightError:
                continue
        return False

    def _profile_session_valid(self, page) -> bool | None:
        """向快手同源资料接口确认 Cookie 是否被服务端接受。

        ``True``/``False`` 表示服务端给出了明确结果；网络或响应格式异常返回
        ``None``，由调用方退回保守 DOM 判断，避免短暂网络抖动强制用户重登。
        """
        response = None
        try:
            self._public_domain_policy_engine().require_public_url(self.PROFILE_SESSION_URL)
            response = page.request.get(
                self.PROFILE_SESSION_URL,
                headers={"Referer": "https://www.kuaishou.com/"},
                timeout=self.PROFILE_SESSION_TIMEOUT_MS,
                fail_on_status_code=False,
                max_redirects=0,
            )
            if not response.ok:
                return None
            payload = response.json()
            if not isinstance(payload, dict) or "result" not in payload:
                return None
            try:
                return int(payload["result"]) == 1
            except (TypeError, ValueError):
                return None
        except (PlaywrightError, OSError, TypeError, ValueError):
            return None
        finally:
            dispose = getattr(response, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except PlaywrightError:
                    pass

    def _refresh_logged_in_state(self, page, target_url: str) -> bool:
        """刷新已加载 Cookie 的页面，并重新校验登录态。"""
        try:
            if not self.interruptible_playwright_reload(
                page,
                wait_until="domcontentloaded",
                timeout=self._configured_timeout_ms(default=60),
            ):
                return False
            self.interruptible_page_wait(page, 1500)
            server_state = self._profile_session_valid(page)
            if server_state is True or (server_state is None and self._is_logged_in(page)):
                return True
        except PlaywrightError:
            pass
        if target_url != "https://www.kuaishou.com/":
            try:
                if not self.interruptible_playwright_goto(
                    page,
                    target_url,
                    timeout=self._configured_timeout_ms(default=60),
                    wait_until="domcontentloaded",
                ):
                    return False
                self.interruptible_page_wait(page, 1500)
                server_state = self._profile_session_valid(page)
                return server_state is True or (server_state is None and self._is_logged_in(page))
            except PlaywrightError:
                return False
        return False

    def _user_cookie_values(self, context) -> set[str]:
        """只读取主站实际可携带的 userId，排除 id 子域同名 Cookie。"""
        values: set[str] = set()
        try:
            for cookie in context.cookies("https://www.kuaishou.com/"):
                if cookie.get("name") == "userId" and cookie.get("value"):
                    values.add(str(cookie["value"]))
        except PlaywrightError:
            return set()
        return values

    def _wait_for_manual_login(self, page, context, auth_file: str) -> bool:
        """等待服务端确认登录完成后再持久化，避免只拿到过渡 Cookie 就提前保存。"""
        for _ in range(120):
            if not self.is_running:
                return False
            current_user_ids = self._user_cookie_values(context)
            if current_user_ids and not self._login_prompt_visible(page):
                server_state = self._profile_session_valid(page)
                logged_in = server_state is True or (server_state is None and self._is_logged_in(page))
                if logged_in:
                    # 让登录重定向、短期会话 Cookie 和 IndexedDB 写入全部落稳后再取快照。
                    if not self.interruptible_page_wait(page, 1000):
                        return False
                    confirmed = self._profile_session_valid(page)
                    if confirmed is True or (confirmed is None and self._is_logged_in(page)):
                        return self._persist_authenticated_state(context, auth_file)
            self.interruptible_page_wait(page, 1000)
        return False

    def _ensure_login(
        self,
        page,
        context,
        auth_file: str,
        entry_url: str | None = None,
        *,
        allow_manual_login: bool = True,
    ) -> bool:
        """依次尝试现有 Cookie、页面刷新和可选的手工登录回退。"""
        target_url = entry_url.strip().strip("`") if entry_url else "https://www.kuaishou.com/"
        self.log("🔗 访问快手首页..." if target_url == "https://www.kuaishou.com/" else f"🔗 访问快手页面: {target_url}")
        has_loaded_cookie = bool(self._user_cookie_values(context))
        try:
            if not self._goto_with_retry(page, target_url, description="页面访问"):
                raise PlaywrightError(f"cannot open {target_url}")
            has_site_cookie = bool(self._user_cookie_values(context))
            server_state = self._profile_session_valid(page) if has_site_cookie else False
            logged_in = server_state is True or (server_state is None and self._is_logged_in(page))
            if not (has_site_cookie and logged_in):
                if server_state is False:
                    self.log("⚠️ 快手服务端判定本地登录态无效，需要重新登录")
                if has_loaded_cookie:
                    self.log("ℹ️ 已加载本地 Cookie，尝试刷新页面重新校验登录态")
                    if self._refresh_logged_in_state(page, target_url) and self._user_cookie_values(context):
                        self.log("✅ 刷新后检测到登录状态")
                        return self._persist_authenticated_state(context, auth_file)
                raise PlaywrightError("not logged in")
            self.log("✅ 检测到登录状态")
            return self._persist_authenticated_state(context, auth_file)
        except PlaywrightError:
            self.log("⚠️ 首页访问或登录态检查失败，继续尝试在当前页面恢复登录")
            navigation_error = self._navigation_error_reason(page)
            if navigation_error is not None:
                # 错误页上不会出现可用的登录流程，继续等待只会让用户看到空白窗口直至超时。
                self.log("❌ 快手页面连续加载失败，已停止本次登录等待；请稍后重试")
                return False
            if os.path.exists(auth_file):
                self.log("⚠️ 本地 Cookie 已加载，但当前页面未识别为已登录，可能已失效")
            if not allow_manual_login:
                self.log("🔑 静默模式检测到快手登录态不可用，将打开登录窗口；登录后会重新静默执行当前任务")
                return False
            self.log("🔑 请在当前快手页面手动登录或扫码，登录成功后程序会自动继续")
            self._open_login_entry(page)

            success = self._wait_for_manual_login(page, context, auth_file)
            if success:
                self.log("✅ 登录成功，Cookie 已保存")
                try:
                    if not self.interruptible_playwright_goto(
                        page,
                        "https://www.kuaishou.com/",
                        timeout=self._configured_timeout_ms(default=60),
                    ):
                        return False
                except PlaywrightError:
                    pass
                return True
        return False

    def _open_login_entry(self, page) -> None:
        """从多个兼容选择器中打开登录入口。"""
        selectors = (
            ".login-btn",
            "text=登录",
            "[class*='login']",
            "button:has-text('登录')",
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    locator.click()
                    self.interruptible_page_wait(page, 1200)
                    if self._has_login_qr(page):
                        self.log("📱 已自动打开快手扫码登录弹窗")
                    return
            except PlaywrightError:
                continue
        self.log("📱 未能自动弹出登录框，请直接在当前快手页面手动登录")

    def _has_login_qr(self, page) -> bool:
        """判断当前页面是否已显示扫码登录区域。"""
        qr_selectors = (
            "canvas",
            "img[alt*='二维码']",
            "img[class*='qr']",
            "[class*='qrcode'] img",
            "[class*='qrcode'] canvas",
            "[class*='scan'] canvas",
        )
        for selector in qr_selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    return True
            except PlaywrightError:
                continue
        return False

    def _locator_visible(self, locator) -> bool:
        """安全判断定位器可见性，页面切换期间异常按不可见处理。"""
        try:
            return bool(locator.is_visible())
        except (PlaywrightError, AttributeError, TypeError, ValueError):
            return False

    def _has_video_list(self, page, *, timeout: int = LIST_READY_TIMEOUT_MS) -> bool:
        """可中断地等待视频卡片列表出现。"""
        try:
            return self.interruptible_wait_for_selector(page, ".photo-card, .video-card", timeout=timeout) is not None
        except PlaywrightError:
            return False

    def _search_user_via_site(self, page, context, keyword: str):
        """通过站内搜索定位用户，并打开其主页。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        if not self._goto_with_retry(page, "https://www.kuaishou.com/", description="打开快手搜索页"):
            return None

        input_selectors = (
            "input[type='search']",
            "input[placeholder*='搜索']",
            "input[placeholder*='快手号']",
            "input[placeholder*='作者']",
        )
        search_input = None
        for selector in input_selectors:
            try:
                locator = page.locator(selector).first
                if self._locator_visible(locator):
                    search_input = locator
                    break
            except PlaywrightError:
                continue

        if search_input is None:
            self.log("❌ 未找到快手搜索框")
            return None

        try:
            search_input.click()
            search_input.fill(keyword)
            search_input.press("Enter")
            self.interruptible_page_wait(page, 2500)
        except PlaywrightError:
            self.log("❌ 无法执行快手站内搜索")
            return None

        return self._open_profile_from_search_results(page, context, keyword)

    def _search_keyword_via_site(self, page, keyword: str):
        """通过站内搜索打开关键词结果页。"""
        self.log(f"🔍 通过站内搜索查找: {keyword}")
        if not self._goto_with_retry(page, "https://www.kuaishou.com/", description="打开快手搜索页"):
            return None

        input_selectors = (
            "input[type='search']",
            "input[placeholder*='搜索']",
            "input[placeholder*='快手号']",
            "input[placeholder*='作者']",
        )
        for selector in input_selectors:
            try:
                locator = page.locator(selector).first
                if not self._locator_visible(locator):
                    continue
                locator.click()
                locator.fill(keyword)
                locator.press("Enter")
                self.interruptible_page_wait(page, 2500)
                if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
                    self.log(f"✅ 已进入搜索结果视频列表: {keyword}")
                    return page
            except PlaywrightError:
                continue
        self.log("❌ 无法执行快手关键词搜索")
        return None

    def _switch_search_to_user_tab(self, page) -> None:
        """把搜索结果切换到用户或账号标签页。"""
        selectors = (
            "text=用户",
            "text=账号",
            "[role='tab']:has-text('用户')",
            "[role='tab']:has-text('账号')",
            "[class*='tab']:has-text('用户')",
            "[class*='tab']:has-text('账号')",
        )
        for selector in selectors:
            try:
                tab = page.locator(selector).first
                if self._locator_visible(tab):
                    tab.click()
                    self.interruptible_page_wait(page, 1500)
                    return
            except PlaywrightError:
                continue

    def _normalize_kuaishou_url(self, href: str) -> str:
        """把快手相对链接补全为绝对 URL。"""
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urllib.parse.urljoin("https://www.kuaishou.com/", href)

    def _profile_url_from_locator(self, locator) -> str | None:
        """从搜索结果节点或其最近链接祖先提取用户主页 URL。"""
        for target in (locator, getattr(locator, "locator", lambda *_: None)("xpath=ancestor-or-self::a[1]")):
            if target is None:
                continue
            try:
                href = target.get_attribute("href")
            except (AttributeError, PlaywrightError):
                href = None
            if href and "/profile/" in href:
                return self._normalize_kuaishou_url(href)
        return None

    def _open_profile_from_search_results(self, page, context, keyword: str):
        """在用户搜索结果中匹配关键词并打开对应主页。"""
        self._switch_search_to_user_tab(page)
        name_selectors = (
            ".name-wrap .name",
            ".name-wrap [class*='name']",
            ".info .name",
            ".detail-user-name",
            ".user-card .name",
            ".card-item [class*='name']",
        )
        for selector in name_selectors:
            try:
                name_link = page.locator(selector).first
                if not self._locator_visible(name_link):
                    continue
                self.log(f"👉 点击搜索结果名字进入主页: {keyword}")
                name_link.click()
                self.interruptible_page_wait(page, 3000)
                if len(context.pages) > 1:
                    page = context.pages[-1]
                    page.bring_to_front()
                if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return page
            except PlaywrightError:
                continue

        avatar_selectors = (
            "a[href*='/profile/'] img",
            ".card-item img",
            "[class*='avatar'] img",
            "[class*='user'] img",
        )
        for selector in avatar_selectors:
            try:
                avatar = page.locator(selector).first
                if not self._locator_visible(avatar):
                    continue
                self.log(f"👉 点击搜索结果头像进入主页: {keyword}")
                avatar.click()
                self.interruptible_page_wait(page, 3000)
                if len(context.pages) > 1:
                    page = context.pages[-1]
                    page.bring_to_front()
                if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
                    self.log(f"👉 已从搜索结果进入主页: {keyword}")
                    return page
            except PlaywrightError:
                continue

        link_selectors = (
            ".card-item .detail-user-name",
            "a[href*='/profile/']",
            "[class*='user-name']",
            "[class*='author'] a",
        )
        for selector in link_selectors:
            try:
                user_link = page.locator(selector).first
                if not self._locator_visible(user_link):
                    continue
                try:
                    name = user_link.inner_text().strip()
                except PlaywrightError:
                    name = keyword
                self.log(f"👉 点击用户卡片进入主页: {name or keyword}")
                user_link.click()
                self.interruptible_page_wait(page, 2000)
                return self._open_profile_from_search_results(page, context, keyword)
            except PlaywrightError:
                continue
        self.log("❌ 未找到匹配的快手账号主页")
        return None

    def _resolve_active_page(self, page, context):
        """点击可能新开标签页时，解析当前仍存活的活动页面。"""
        def usable(candidate, *, allow_blank: bool = False) -> bool:
            try:
                if not candidate or candidate.is_closed():
                    return False
                if allow_blank:
                    return True
                current_url = str(getattr(candidate, "url", "") or "").strip()
                return bool(
                    current_url
                    and current_url != "about:blank"
                    and urllib.parse.urlsplit(current_url).scheme.lower() != "chrome-error"
                )
            except (PlaywrightError, AttributeError, TypeError, ValueError):
                return False

        try:
            if usable(page):
                return page
        except PlaywrightError:
            pass
        for candidate in reversed(list(getattr(context, "pages", []) or [])):
            try:
                if usable(candidate):
                    candidate.bring_to_front()
                    return candidate
            except PlaywrightError:
                continue
        # 页面尚未开始导航时仍返回原对象，调用方可在同一标签页继续 goto。
        if usable(page, allow_blank=True):
            return page
        return None

    def _navigate_to_target_page(self, page, context):
        """按 URL、快手号或关键词把浏览器导航到目标内容页。"""
        if self._is_kuaishou_url(self.keyword):
            target_url = self.keyword.strip().strip("`")
            if not self._goto_with_retry(page, target_url, description="打开快手目标页"):
                return None
            return page

        if self.keyword.isdigit():
            self.log("ℹ️ 当前输入为纯数字，按快手号优先进入用户搜索结果")
            return self._search_user_via_site(page, context, self.keyword)
        return self._search_keyword_via_site(page, self.keyword)

    def _extract_detail_title(self, page) -> str:
        """从单条详情页提取作品标题。"""
        selectors = (
            "[class*='caption']",
            "[class*='title']",
            "meta[property='og:title']",
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if not self._locator_visible(locator):
                    continue
                title = locator.inner_text().strip()
                if title:
                    return title
            except PlaywrightError:
                try:
                    content = page.locator(selector).first.get_attribute("content")
                except PlaywrightError:
                    content = None
                if content:
                    return content.strip()
        try:
            title = page.title().strip()
        except PlaywrightError:
            title = ""
        return title or "快手分享作品"

    def _extract_detail_dom_media_url(self, page) -> str:
        """优先从详情页 DOM 中直接提取 video src。"""
        try:
            media_url = page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (!video) return '';
                    return video.currentSrc || video.src || video.querySelector('source')?.src || '';
                }"""
            )
        except PlaywrightError:
            media_url = ""
        return str(media_url or "").strip()

    def _capture_single_detail_page(self, page, initial_stream_urls=()) -> bool:
        """从已打开的详情页捕获单条作品；初次导航响应可由调用方提前传入。"""
        if not self._is_detail_url(getattr(page, "url", "")):
            return False

        self.log("🌐 正在从快手分享详情页捕获单条作品...")
        emitted = False
        title = self._extract_detail_title(page)

        def submit_stream(stream_url: str) -> bool:
            nonlocal emitted
            stream_url = str(stream_url or "").strip()
            if emitted or not stream_url:
                return False
            emitted = True
            trace_id = self.new_trace_id("share")
            self.debug_state(
                action="emit_share_task",
                message="快手分享链接已解析并提交到下载队列",
                status_code="KUAISHOU_SHARE_TASK_EMIT",
                context={"trace_id": trace_id},
                details={"title": title, "stream_url": stream_url, "referer": page.url},
            )
            self.emit_video(
                url=stream_url,
                title=title,
                source="kuaishou",
                meta=self.task_builder.build_download_meta(trace_id, page.url, stream_url, self._user_agent()),
            )
            self.log(f"✨ 已解析分享作品: {title[:24]}...")
            return True

        def handle_response(response):
            submit_stream(self._share_media_response_url(response))

        page.on("response", handle_response)
        try:
            for stream_url in initial_stream_urls:
                if submit_stream(stream_url):
                    return True
            if submit_stream(self._extract_detail_dom_media_url(page)):
                return True

            # 有些详情页必须触发一次播放后才发起媒体请求，先在当前页面尝试，
            # 仍未捕获时最多刷新一次，避免旧实现重复加载同一分享页。
            try:
                page.locator("video").first.click(timeout=1500)
            except PlaywrightError:
                pass
            self.interruptible_page_wait(page, 1500)
            if emitted or submit_stream(self._extract_detail_dom_media_url(page)):
                return True

            if self.is_running:
                try:
                    if self.interruptible_playwright_reload(
                        page,
                        wait_until="domcontentloaded",
                        timeout=self._configured_timeout_ms(default=60),
                    ):
                        self.interruptible_page_wait(page, 2500)
                        try:
                            page.locator("video").first.click(timeout=1500)
                        except PlaywrightError:
                            pass
                        if emitted or submit_stream(self._extract_detail_dom_media_url(page)):
                            return True
                except PlaywrightError:
                    pass

            self.log("❌ 未能从快手分享链接中解析出可下载视频")
            return False
        finally:
            try:
                page.remove_listener("response", handle_response)
            except (AttributeError, PlaywrightError):
                pass

    def _wait_for_video_list(self, page) -> bool:
        """等待视频列表并记录无法加载的终止状态。"""
        if self._has_video_list(page, timeout=self._configured_timeout_ms(default=60)):
            return True
        try:
            self.log("❌ 无法加载视频列表")
        except RuntimeError:
            pass
        return False

    def _scan_video_cards(self, page) -> int:
        """滚动页面直到内容加载完成或用户主动停止。"""
        self.log("\n📜 开始滚动加载列表... (点击【停止】生成清单)")
        scroll_count = 0
        last_card_count = 0
        no_new_content_count = 0
        max_items = self._max_items_limit()
        while self.is_running:
            scroll_count += 1
            try:
                vp = page.viewport_size
                if vp:
                    page.mouse.move(vp["width"] / 2, vp["height"] / 2)
            except PlaywrightError:
                pass

            page.evaluate("window.scrollBy(0, 800)")
            self.interruptible_page_wait(page, 500)
            page.mouse.wheel(0, 500)
            self.interruptible_page_wait(page, 1000)

            cards = page.locator(".photo-card, .video-card")
            current_card_count = cards.count()
            if max_items < 9999 and current_card_count >= max_items:
                self.log(f"✅ 已达到视频数上限 {max_items}")
                last_card_count = current_card_count
                break
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
                    self.interruptible_page_wait(page, 1000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    no_new_content_count = 0
            else:
                no_new_content_count = 0
                last_card_count = current_card_count

            if scroll_count % 3 == 0:
                self.log(f"⬇️ 加载中... (已扫描 {current_card_count} 个)")
        return last_card_count

    def _extract_items_for_dialog(self, page) -> tuple[list[dict[str, int | str]], dict[int, set[str]]]:
        """提取选择项，并建立卡片索引到媒体指纹的映射。"""
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

        max_items = self._max_items_limit()
        items_for_dialog: list[dict[str, int | str]] = []
        target_fingerprints_map: dict[int, set[str]] = {}
        for idx, raw_title in enumerate(video_titles):
            if max_items < 9999 and idx >= max_items:
                break
            clean_title = raw_title.replace("\n", " ").strip() or f"未命名视频_{idx + 1}"
            items_for_dialog.append({"title": clean_title, "index": idx})
            if idx < len(video_imgs):
                target_fingerprints_map[idx] = self.parser.extract_all_possible_ids(video_imgs[idx])
        return items_for_dialog, target_fingerprints_map

    def _collect_selected_indices(self, items_for_dialog: list[dict[str, int | str]]):
        """展示候选列表并返回用户确认的卡片索引。"""
        if not items_for_dialog:
            self.log("❌ 未扫描到有效视频")
            return None
        self.log(f"🔔 扫描完成，共 {len(items_for_dialog)} 个，请选择下载...")
        selected_indices = self.ask_user_selection(items_for_dialog)
        if not selected_indices:
            self.log("❌ 用户取消了下载任务")
            return None
        self.debug_state(
            action="selection_confirmed",
            message="快手任务选择已确认",
            status_code="KUAISHOU_SELECTION_OK",
            details={"total_items": len(items_for_dialog), "selected_count": len(selected_indices)},
        )
        return selected_indices

    def _capture_scroll_budget(self, items_for_dialog: list[dict[str, int | str]]) -> int:
        """为详情页切换预留足够滚动次数，兼容焦点与卡片索引偏移。"""
        if not items_for_dialog:
            return 0
        base_count = len(items_for_dialog)
        return max(base_count, base_count * 2)

    def _run_capture_pipeline(self, page, items_for_dialog: list[dict[str, int | str]], target_fingerprints_map: dict[int, set[str]]) -> None:
        """滚动详情流，并把网络响应匹配到用户选择的卡片。"""
        page = self._resolve_active_page(page, getattr(page, "context", None) or None) or page
        target_indices_set = set(self._selected_indices)
        submitted_indices: set[int] = set()
        current_focus_index = 0
        total_scrolls = self._capture_scroll_budget(items_for_dialog)

        def handle_response(response):
            # 网络回调会与焦点滚动交错；锁内先认领索引，才能避免同一媒体响应重复入队。
            if not self.is_running:
                return
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
                    if matched_idx == -1 and current_focus_index in target_indices_set and current_focus_index not in submitted_indices:
                        matched_idx = current_focus_index
                        self.log(f"   🎯 [焦点匹配] {items_for_dialog[matched_idx]['title'][:10]}...")
                    elif matched_idx == -1 and "pkey" in url:
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
                            meta=self.task_builder.build_download_meta(trace_id, page.url, url, self._user_agent()),
                        )
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
                pass

        context = page.context
        page.on("response", handle_response)
        page = self._resolve_active_page(page, context)
        if not page:
            self.log("❌ 详情页已关闭，无法启动捕获流水线")
            return
        page.evaluate("window.scrollTo(0, 0)")
        self.interruptible_page_wait(page, 1000)
        cards = page.locator(".photo-card, .video-card")
        try:
            first_card = cards.first
            if not first_card.is_visible():
                first_card.scroll_into_view_if_needed()
            first_card.click()
            self.interruptible_page_wait(page, 3000)
            try:
                page.mouse.click(200, 200)
            except PlaywrightError:
                pass
        except PlaywrightError:
            self.log("❌ 无法进入详情页")
            return

        self.log(f"🔄 生产者工作开始 (0 - {total_scrolls})...")
        while current_focus_index < total_scrolls and self.is_running:
            page = self._resolve_active_page(page, context)
            if not page:
                self.log("⚠️ 详情页已关闭，提前结束当前捕获流程")
                break
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
            if not self.interruptible_page_wait(page, wait_ms):
                break
            try:
                if page.locator(".close-icon").is_visible():
                    page.locator(".close-icon").click()
            except PlaywrightError:
                pass

        self.log("\n📊 流程结束。")
        self.debug_state(
            action="capture_pipeline_finish",
            message="快手流捕获流水线结束",
            status_code="KUAISHOU_CAPTURE_DONE",
            details={
                "scroll_budget": total_scrolls,
                "selected_count": len(target_indices_set),
                "submitted_count": len(submitted_indices),
                "not_found_count": len(target_indices_set - submitted_indices),
            },
        )
        not_found = target_indices_set - submitted_indices
        if not_found:
            self.log(f"⚠️ {len(not_found)} 个视频未捕获:")
            for idx in sorted(list(not_found)):
                self.log(f"   - [{idx + 1}] {items_for_dialog[idx]['title'][:20]}...")
        else:
            self.log("✅ 全部任务完成！")

    def _entry_url_for_login(self) -> str | None:
        return self.keyword if self._is_kuaishou_url(self.keyword) and not self._is_detail_url(self.keyword) else None

    def _run_login_window_session(self, playwright, auth_file: str, entry_url: str | None) -> bool:
        self.log("🔓 正在打开快手登录窗口...")
        headless = self._browser_headless(login_window=True)
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                headless=headless,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        try:
            context = self._create_browser_context(
                browser, auth_file, headless=headless
            )
            page = context.new_page()
            return self._ensure_login(page, context, auth_file, entry_url=entry_url, allow_manual_login=True)
        finally:
            self._close_tracked_playwright_browser(browser)

    def _run_share_browser_session(self, playwright, auth_file: str) -> str:
        """用固定无头会话解析分享详情，不进入首页、登录检查或列表扫描。"""
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                # 分享链接是单资源解析入口，即使用户启用了“显示浏览器”也保持静默。
                headless=True,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        try:
            context = self._create_browser_context(browser, auth_file, headless=True)
            page = context.new_page()
            initial_stream_urls: list[str] = []

            def remember_stream(response) -> None:
                stream_url = self._share_media_response_url(response)
                if stream_url and stream_url not in initial_stream_urls:
                    initial_stream_urls.append(stream_url)

            # 监听器必须早于 goto 注册，否则首屏直接发出的媒体响应会永久错过。
            page.on("response", remember_stream)
            try:
                if not self._goto_with_retry(
                    page, self.keyword, description="静默打开快手分享详情页"
                ):
                    return "stopped" if not self.is_running else "failed"
                self.interruptible_page_wait(page, 1200)
                # 保留首屏监听器直到详情捕获完成，覆盖标题提取与二级监听器注册之间的窄窗口。
                if self._capture_single_detail_page(page, initial_stream_urls):
                    return "completed"
                if not self.is_running:
                    return "stopped"
                if self._login_prompt_visible(page):
                    return "login_required"
                return "failed"
            finally:
                try:
                    page.remove_listener("response", remember_stream)
                except (AttributeError, PlaywrightError):
                    pass
        finally:
            self._close_tracked_playwright_browser(browser)

    def _run_browser_session(
        self,
        playwright,
        auth_file: str,
        *,
        headless: bool,
        allow_manual_login: bool,
    ) -> str:
        browser = playwright.chromium.launch(
            **self._playwright_launch_kwargs(
                headless=headless,
                proxy=(getattr(self, "config", {}) or {}).get("proxy"),
                args=["--disable-blink-features=AutomationControlled"],
            )
        )
        self._track_playwright_browser(browser)
        try:
            context = self._create_browser_context(
                browser, auth_file, headless=headless
            )
            page = context.new_page()
            if not self._ensure_login(
                page,
                context,
                auth_file,
                entry_url=self._entry_url_for_login(),
                allow_manual_login=allow_manual_login,
            ):
                return "login_required" if self.is_running and not allow_manual_login else "stopped"

            page = self._navigate_to_target_page(page, context)
            if not page:
                return "stopped"
            if not self._wait_for_video_list(page):
                return "stopped"

            last_card_count = self._scan_video_cards(page)
            if not self.revive_for_partial_selection(last_card_count, "个候选作品"):
                return "stopped"

            items_for_dialog, target_fingerprints_map = self._extract_items_for_dialog(page)
            selected_indices = self._collect_selected_indices(items_for_dialog)
            if not selected_indices:
                return "stopped"
            self.is_running = True
            self._selected_indices = selected_indices
            self.log(f"✅ 选中 {len(selected_indices)} 个任务，流水线启动...")
            self._run_capture_pipeline(page, items_for_dialog, target_fingerprints_map)
            return "completed"
        finally:
            self._close_tracked_playwright_browser(browser)

    def run(self):
        """按详情链接或列表任务分流，避免同一输入重复经过两套浏览器流程。"""
        auth_file = cfg.get("auth", "kuaishou_cookie_file", "ks_auth.json")
        self.keyword = self._normalize_keyword(self.keyword)
        self.log(f"🚀 启动快手任务 | 目标: {self.keyword}")
        try:
            if self._is_detail_url(self.keyword):
                self.log("🎯 检测到快手分享/详情链接，使用静默单资源解析流程")
                if self._try_direct_share_download():
                    return
                self.log("ℹ️ HTTP 未获得视频直链，切换无头浏览器继续解析")
                with sync_playwright() as p:
                    result = self._run_share_browser_session(p, auth_file)
                    if result == "login_required" and self.is_running:
                        login_ok = self._run_login_window_session(
                            p, auth_file, self._entry_url_for_login()
                        )
                        if login_ok and self.is_running:
                            self.log("✅ 快手登录完成，重新以静默模式执行当前任务")
                            self._run_share_browser_session(p, auth_file)
                return

            with sync_playwright() as p:
                headless = self._browser_headless()
                result = self._run_browser_session(
                    p,
                    auth_file,
                    headless=headless,
                    allow_manual_login=not headless,
                )
                # 静默会话只负责探测；需要登录时先关闭它，再用可见窗口持久化 Cookie 后重跑。
                if result == "login_required" and headless and self.is_running:
                    login_ok = self._run_login_window_session(p, auth_file, self._entry_url_for_login())
                    if login_ok and self.is_running:
                        self.log("✅ 快手登录完成，重新以静默模式执行当前任务")
                        self._run_browser_session(
                            p,
                            auth_file,
                            headless=True,
                            allow_manual_login=False,
                        )
        except (PlaywrightError, OSError, ValueError, RuntimeError) as e:
            self.log(f"💥 爬虫错误: {e}")
        finally:
            # HTTP 分享直连会在创建 Playwright 之前返回；轻量调用方也可能没有
            # 执行 BaseSpider.__init__。未跟踪过浏览器时无需进入浏览器清理链路。
            browser = getattr(self, "_playwright_browser", None)
            if browser is not None:
                try:
                    self._close_tracked_playwright_browser(browser)
                except PlaywrightError:
                    pass
            self._emit_finished()
