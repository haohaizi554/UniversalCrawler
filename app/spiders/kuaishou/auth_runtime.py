"""Kuaishou browser-context and authentication runtime helpers."""

import json
import os
import time

from playwright.sync_api import Error as PlaywrightError

from app.exceptions import CookieLoadError, CookieSaveError
from app.services.auth_service import AuthService


class KuaishouAuthRuntimeMixin:
    """Own browser context creation and authenticated-state persistence."""

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
        self._loaded_storage_state = storage_state
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
            self._loaded_storage_state = None
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

    def _persist_authenticated_state(
        self,
        context,
        auth_file: str,
        *,
        allow_auth_replacement: bool = False,
    ) -> bool:
        """在关闭当前浏览器前原子发布最新 Cookie 与 origin/localStorage。"""
        try:
            try:
                # 快手登录完成后可能把令牌写入 IndexedDB；默认 storage_state 不会包含它。
                storage_state = context.storage_state(indexed_db=True)
            except TypeError:
                # 兼容 Playwright 1.51 之前尚无 indexed_db 参数的运行环境。
                storage_state = context.storage_state()
            previous_state = (
                None
                if allow_auth_replacement
                else getattr(self, "_loaded_storage_state", None)
            )
            if not self._authenticated_snapshot_is_safe(previous_state, storage_state):
                self.log("⚠️ 快手登录态快照缺少既有认证 Cookie，已保留原登录文件")
                return False
            self.auth_service.save_json_file(auth_file, storage_state)
            self._loaded_storage_state = storage_state
            return True
        except (CookieSaveError, OSError, TypeError, ValueError, PlaywrightError) as exc:
            self.log(f"⚠️ 快手登录态保存失败: {exc}")
            return False

    @classmethod
    def _authentication_cookie_families(cls, storage_state) -> set[str]:
        """把可轮换的长期 Cookie 名归一到稳定认证家族。"""
        cookies = AuthService.extract_cookie_dict_for_url(
            storage_state,
            "https://www.kuaishou.com/",
        )
        families: set[str] = set()
        if "userId" in cookies:
            families.add("user")
        if set(cookies).intersection(cls.LONG_LIVED_AUTH_COOKIE_NAMES):
            families.add("long_lived_session")
        return families

    @classmethod
    def _authenticated_snapshot_is_safe(cls, previous_state, current_state) -> bool:
        """拒绝缺少主身份或丢失既有长期认证项的缩水快照。"""
        current_families = cls._authentication_cookie_families(current_state)
        if "user" not in current_families:
            return False
        previous_families = cls._authentication_cookie_families(previous_state)
        return previous_families.issubset(current_families)

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

    def _profile_session_valid(
        self,
        page,
        *,
        timeout_ms: int | None = None,
    ) -> bool | None:
        """用隔离请求上下文确认 Cookie 是否被快手服务端接受。

        ``True``/``False`` 表示服务端给出了明确结果；网络或响应格式异常返回
        ``None``，由调用方退回保守 DOM 判断，避免短暂网络抖动强制用户重登。
        """
        response = None
        request_context = None
        probe_timeout_ms = max(
            250,
            min(
                self.PROFILE_SESSION_TIMEOUT_MS,
                int(timeout_ms or self.PROFILE_SESSION_TIMEOUT_MS),
            ),
        )
        try:
            self._public_domain_policy_engine().require_public_url(self.PROFILE_SESSION_URL)
            request_api = getattr(self, "_profile_request_api", None)
            context = getattr(page, "context", None)
            if request_api is None or context is None:
                return None
            cookies = context.cookies(self.PROFILE_SESSION_URL)
            request_context_kwargs = {
                "storage_state": {"cookies": cookies, "origins": []},
                "user_agent": self._user_agent(),
                "timeout": probe_timeout_ms,
            }
            proxy = self._effective_proxy_server(
                (getattr(self, "config", {}) or {}).get("proxy")
            )
            if proxy:
                request_context_kwargs["proxy"] = {"server": proxy}
            request_context = request_api.new_context(
                **request_context_kwargs
            )
            response = request_context.get(
                self.PROFILE_SESSION_URL,
                headers={"Referer": "https://www.kuaishou.com/"},
                timeout=probe_timeout_ms,
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
            dispose_context = getattr(request_context, "dispose", None)
            if callable(dispose_context):
                try:
                    dispose_context()
                except PlaywrightError:
                    pass

    def _refresh_logged_in_state(
        self,
        page,
        target_url: str,
    ) -> tuple[bool, bool | None]:
        """不改变可见页面，只在短暂稳定窗口后重新校验已加载的登录态。"""
        del target_url
        try:
            if not self.interruptible_page_wait(page, 300):
                return False, None
            server_state = self._profile_session_valid(page)
            logged_in = server_state is True or (
                server_state is None and self._is_logged_in(page)
            )
            return logged_in, server_state
        except PlaywrightError:
            return False, None

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
        deadline = time.monotonic() + self.MANUAL_LOGIN_TIMEOUT_MS / 1000
        for _ in range(120):
            if not self.is_running:
                return False
            remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                return False
            current_user_ids = self._user_cookie_values(context)
            if current_user_ids and not self._login_prompt_visible(page):
                server_state = self._profile_session_valid(
                    page,
                    timeout_ms=min(self.PROFILE_SESSION_TIMEOUT_MS, remaining_ms),
                )
                logged_in = server_state is True or (server_state is None and self._is_logged_in(page))
                if logged_in:
                    # 让登录重定向、短期会话 Cookie 和 IndexedDB 写入全部落稳后再取快照。
                    remaining_ms = int(
                        max(0, (deadline - time.monotonic()) * 1000)
                    )
                    if remaining_ms <= 0 or not self.interruptible_page_wait(
                        page,
                        min(1000, remaining_ms),
                    ):
                        return False
                    remaining_ms = int(
                        max(0, (deadline - time.monotonic()) * 1000)
                    )
                    if remaining_ms <= 0:
                        return False
                    confirmed = self._profile_session_valid(
                        page,
                        timeout_ms=min(
                            self.PROFILE_SESSION_TIMEOUT_MS,
                            remaining_ms,
                        ),
                    )
                    if confirmed is True or (confirmed is None and self._is_logged_in(page)):
                        allow_replacement = (
                            confirmed is True
                            or getattr(self, "_loaded_storage_state", None) is None
                        )
                        return self._persist_authenticated_state(
                            context,
                            auth_file,
                            allow_auth_replacement=allow_replacement,
                        )
            remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0 or not self.interruptible_page_wait(
                page,
                min(1000, remaining_ms),
            ):
                return False
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
        """依次尝试现有 Cookie、无导航复检和可选的手工登录回退。"""
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
                if has_loaded_cookie and server_state is None:
                    self.log("ℹ️ 已加载本地 Cookie，短暂等待后重新校验登录态")
                    rechecked, rechecked_server_state = self._refresh_logged_in_state(
                        page,
                        target_url,
                    )
                    if rechecked and self._user_cookie_values(context):
                        self.log("✅ 复检后检测到登录状态")
                        if rechecked_server_state is True:
                            self._persist_authenticated_state(context, auth_file)
                        else:
                            self.log("ℹ️ 服务端暂未确认登录态，保留原登录文件")
                        return True
                raise PlaywrightError("not logged in")
            self.log("✅ 检测到登录状态")
            if server_state is True:
                self._persist_authenticated_state(context, auth_file)
            else:
                self.log("ℹ️ 服务端暂未确认登录态，保留原登录文件")
            return True
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

    def _has_video_list(self, page, *, timeout: int | None = None) -> bool:
        """可中断地等待视频卡片列表出现。"""
        try:
            return self.interruptible_wait_for_selector(
                page,
                ".photo-card, .video-card",
                timeout=timeout if timeout is not None else self.LIST_READY_TIMEOUT_MS,
            ) is not None
        except PlaywrightError:
            return False
