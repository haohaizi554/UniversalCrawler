"""各平台 Spider 共用的线程、停止、选择和浏览器辅助逻辑。"""

from __future__ import annotations

import threading
import time
import os
import urllib.parse
from collections.abc import Callable

from app.debug_logger import debug_logger
from shared.playwright_network_guard import install_public_network_guard
from app.core.guardrails import BudgetExhausted, CrawlBudget, RateLimiter, sanitize
from app.core.guardrails.crawl_budget import RateLimitCancelled
from app.models import VideoItem
from app.utils.callback_signal import CallbackSignal
from shared.runtime_options import PUBLIC_DOMAIN_POLICY, DomainPolicyEngine, DomainPolicyViolation

class BaseSpider(threading.Thread):
    """平台 Spider 的线程基类，统一承接 UI 回调、中断语义和防护栏。"""

    ALLOW_SYSTEM_PROXY_FALLBACK = False

    def __init__(self, keyword: str, config: dict):
        """初始化一次采集任务运行时状态，子类只需要实现平台采集细节。"""
        super().__init__(daemon=True, name=self.__class__.__name__)
        self.keyword = keyword
        self.config = config
        self._running_lock = threading.RLock()
        self._is_running = True
        self.sig_log = CallbackSignal()
        self.sig_item_found = CallbackSignal()
        self.sig_items_found = CallbackSignal()
        self.sig_finished = CallbackSignal()
        self.sig_select_tasks = CallbackSignal()
        self.trace_prefix = self.__class__.__name__.replace("Spider", "").lower() or "spider"
        self.budget = self._build_crawl_budget(config)
        self.rate_limiter = self._build_rate_limiter(config)
        # UI 展示选择框时 Spider 线程在此等待，停止路径也必须置位该事件才能完成收尾。
        self._resume_event = threading.Event()
        self._selection_result = None
        self._selection_emit_perf_ms = 0.0
        self._selection_emit_wall_ms = 0
        # Playwright 同步调用可能卡在页面加载里；保留 browser 引用便于 stop() 立即关闭。
        self._playwright_lock = threading.RLock()
        self._playwright_browser = None
        self._playwright_owner_thread_id: int | None = None
        self._playwright_pw = None
        self._selection_epoch = 0
        self._interrupt_requested = False

    @staticmethod
    def _url_matches_hosts(
        url: str,
        allowed_hosts: tuple[str, ...] | set[str] | frozenset[str],
        *,
        allow_subdomains: bool = True,
    ) -> bool:
        """仅匹配解析后的主机名，拒绝路径或查询参数中的伪装域名。"""
        try:
            parsed = urllib.parse.urlsplit(str(url or "").strip())
            if parsed.scheme.lower() not in {"http", "https"}:
                return False
            host = (parsed.hostname or "").lower().rstrip(".")
        except (TypeError, ValueError):
            return False
        normalized_hosts = {str(item).lower().rstrip(".") for item in allowed_hosts if item}
        if host in normalized_hosts:
            return True
        return allow_subdomains and any(host.endswith(f".{item}") for item in normalized_hosts)

    def _restricted_public_request_kwargs(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...] | set[str] | frozenset[str],
    ) -> dict[str, object]:
        """在 Requests 跟随前校验平台初始 URL 及每一次重定向。"""
        if not self._url_matches_hosts(url, allowed_hosts):
            raise DomainPolicyViolation("url 主机不属于目标平台")
        policy = self._public_domain_policy_engine()
        policy.require_public_url(url)

        def validate_platform_redirect(response, *args, **kwargs):
            status_code = int(getattr(response, "status_code", 0) or 0)
            headers = getattr(response, "headers", {}) or {}
            location = headers.get("Location") or headers.get("location")
            if status_code in policy.REDIRECT_STATUS_CODES and location:
                current_url = str(getattr(response, "url", "") or url)
                target_url = urllib.parse.urljoin(current_url, str(location))
                if not self._url_matches_hosts(target_url, allowed_hosts):
                    raise DomainPolicyViolation("重定向目标不属于目标平台")
            return policy.validate_redirect_response(response, *args, **kwargs)

        return {"hooks": {"response": validate_platform_redirect}}

    def _public_domain_policy_engine(self) -> DomainPolicyEngine:
        policy = getattr(self, "_public_domain_policy", PUBLIC_DOMAIN_POLICY)
        return policy if isinstance(policy, DomainPolicyEngine) else PUBLIC_DOMAIN_POLICY

    @property
    def interrupt_requested(self) -> bool:
        return bool(getattr(self, "_interrupt_requested", False))

    @property
    def is_running(self) -> bool:
        with self._running_guard():
            return bool(getattr(self, "_is_running", False))

    @is_running.setter
    def is_running(self, value: bool) -> None:
        with self._running_guard():
            self._is_running = bool(value)

    def _running_guard(self) -> threading.RLock:
        lock = getattr(self, "_running_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._running_lock = lock
        return lock

    def stop(self):
        """请求线程尽快停止，并唤醒选择等待/关闭被跟踪的浏览器。"""
        self.is_running = False
        self._interrupt_requested = True
        # 推进选择代次后再唤醒，避免停止信号被误判为一次正常的 UI 选择结果。
        with self._running_guard():
            self._selection_epoch += 1
        self._resume_event.set()
        self._close_tracked_playwright_browser()
        self._stop_tracked_playwright_instance()
        self.sig_log.emit("🛑 正在停止任务...")

    def _track_playwright_browser(self, browser) -> None:
        """记录当前线程创建的浏览器，供外部取消时做强制清理。"""
        with self._playwright_guard():
            self._playwright_browser = browser
            self._playwright_owner_thread_id = threading.get_ident()

    def _clear_playwright_browser(self, browser=None) -> None:
        with self._playwright_guard():
            if browser is None or self._playwright_browser is browser:
                self._playwright_browser = None
                self._playwright_owner_thread_id = None

    def _tracked_playwright_browser(self):
        with self._playwright_guard():
            return self._playwright_browser

    def _track_playwright_instance(self, playwright) -> None:
        with self._playwright_guard():
            self._playwright_pw = playwright

    def _clear_playwright_instance(self, playwright=None) -> None:
        with self._playwright_guard():
            if playwright is None or self._playwright_pw is playwright:
                self._playwright_pw = None

    def _close_tracked_playwright_browser(self, browser=None) -> None:
        """在 stop 路径中关闭浏览器；异常只记录，不阻断线程收尾。"""
        with self._playwright_guard():
            browser = browser or self._playwright_browser
            if browser is None:
                return
        try:
            browser.close()
        except Exception as exc:
            debug_logger.log_exception(
                self.__class__.__name__,
                "close_tracked_playwright_browser",
                exc,
            )
        finally:
            self._clear_playwright_browser(browser)

    def _stop_tracked_playwright_instance(self, playwright=None) -> None:
        """停止受跟踪的 Playwright 驱动，防止其辅助进程泄漏。"""
        with self._playwright_guard():
            playwright = playwright or self._playwright_pw
            if playwright is None:
                return
        try:
            playwright.stop()
        except Exception as exc:
            debug_logger.log_exception(
                self.__class__.__name__,
                "stop_tracked_playwright_instance",
                exc,
            )
        finally:
            self._clear_playwright_instance(playwright)

    def is_playwright_browser_tracked(self) -> bool:
        """判断当前是否有等待清理的 Playwright 浏览器。"""
        return self._tracked_playwright_browser() is not None

    def _playwright_guard(self) -> threading.RLock:
        lock = getattr(self, "_playwright_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._playwright_lock = lock
        return lock

    def interruptible_sleep(self, seconds: float, step: float = 0.5):
        """可中断 sleep：长等待被切成小段，用户停止后不再卡完整超时时间。"""
        import time as _time
        deadline = _time.time() + seconds
        while _time.time() < deadline:
            if not self.is_running or self.interrupt_requested:
                return False
            remaining = deadline - _time.time()
            _time.sleep(min(step, remaining))
        return self.is_running

    def interruptible_page_wait(self, page, timeout_ms: int, *, step_ms: int = 500) -> bool:
        """切分 ``page.wait_for_timeout``，使每个时间片之间都能响应 ``stop()``。"""
        remaining_ms = max(0, int(timeout_ms))
        step_ms = max(50, int(step_ms))
        while remaining_ms > 0:
            if not self.is_running or self.interrupt_requested:
                return False
            chunk_ms = min(step_ms, remaining_ms)
            page.wait_for_timeout(chunk_ms)
            remaining_ms -= chunk_ms
        return self.is_running

    def interruptible_wait_for_selector(self, page, selector: str, *, timeout: int = 30000, step_ms: int = 500):
        """分段等待选择器，以便及时响应停止请求。"""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        remaining_ms = max(0, int(timeout))
        step_ms = max(50, int(step_ms))
        last_timeout: Exception | None = None
        while remaining_ms > 0 and self.is_running and not self.interrupt_requested:
            chunk_ms = min(step_ms, remaining_ms)
            try:
                return page.wait_for_selector(selector, timeout=chunk_ms)
            except PlaywrightTimeoutError as exc:
                last_timeout = exc
                remaining_ms -= chunk_ms
            except Exception as exc:
                if exc.__class__.__name__ == "TimeoutError":
                    last_timeout = exc
                    remaining_ms -= chunk_ms
                    continue
                raise
        if not self.is_running or self.interrupt_requested:
            return None
        if last_timeout is not None:
            raise last_timeout
        return None

    def interruptible_wait_for_load_state(
        self,
        page,
        state: str = "load",
        *,
        timeout: int = 30000,
        step_ms: int = 500,
    ) -> bool:
        """分段等待 Playwright 加载状态，避免停止请求被长超时遮蔽。"""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        remaining_ms = max(0, int(timeout))
        step_ms = max(50, int(step_ms))
        last_timeout: Exception | None = None
        while remaining_ms > 0 and self.is_running and not self.interrupt_requested:
            chunk_ms = min(step_ms, remaining_ms)
            try:
                page.wait_for_load_state(state, timeout=chunk_ms)
                return True
            except PlaywrightTimeoutError as exc:
                last_timeout = exc
                remaining_ms -= chunk_ms
            except Exception as exc:
                if exc.__class__.__name__ == "TimeoutError":
                    last_timeout = exc
                    remaining_ms -= chunk_ms
                    continue
                raise
        if not self.is_running or self.interrupt_requested:
            return False
        if last_timeout is not None:
            raise last_timeout
        return False

    def interruptible_playwright_goto(
        self,
        page,
        url: str,
        *,
        timeout: int = 60000,
        slice_ms: int = 1000,
        **kwargs,
    ) -> bool:
        """只发起一次导航，并允许停止请求通过清理受跟踪浏览器来中断等待。

        ``page.goto`` 不是可轮询等待；短超时后再次调用会启动新导航，让较慢的 SPA
        页面看起来不断刷新。因此这里只保留一次完整导航，需要重试时由调用方显式控制。
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if not self.is_running or self.interrupt_requested:
            return False
        self._public_domain_policy_engine().require_public_url(url)
        self._ensure_playwright_public_route(page)
        try:
            self.guard_request(cancel_check=lambda: not self.is_running)
        except BudgetExhausted as exc:
            self.sig_log.emit(f"Guardrail stopped navigation: {exc}")
            raise
        before_url = str(getattr(page, "url", "") or "")
        try:
            page.goto(url, timeout=max(1, int(timeout)), **kwargs)
            self._validate_playwright_page_url(page)
            return True
        except PlaywrightTimeoutError:
            if not self.is_running or self.interrupt_requested:
                return False
            self._validate_playwright_page_url(page)
            return self._playwright_navigation_has_started(
                before_url,
                str(getattr(page, "url", "") or ""),
                url,
            )
        except Exception as exc:
            if not self.is_running or self.interrupt_requested:
                return False
            if exc.__class__.__name__ == "TimeoutError":
                self._validate_playwright_page_url(page)
                return self._playwright_navigation_has_started(
                    before_url,
                    str(getattr(page, "url", "") or ""),
                    url,
                )
            raise
        return False

    def interruptible_playwright_reload(
        self,
        page,
        *,
        timeout: int = 60000,
        **kwargs,
    ) -> bool:
        """按完整超时只刷新一次，并保持一致的停止语义。

        部分平台在有效 DOM 就绪后仍会持续加载 SPA 资源。短超时重试会造成循环刷新，
        因此这里与 ``interruptible_playwright_goto`` 一样只尝试一次；只要页面已经启动且
        用户未停止任务，超时后仍按可用页面处理。
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if not self.is_running or self.interrupt_requested:
            return False
        self._validate_playwright_page_url(page)
        self._ensure_playwright_public_route(page)
        try:
            self.guard_request(cancel_check=lambda: not self.is_running)
        except BudgetExhausted as exc:
            self.sig_log.emit(f"Guardrail stopped reload: {exc}")
            raise
        try:
            page.reload(timeout=max(1, int(timeout)), **kwargs)
            self._validate_playwright_page_url(page)
            return True
        except PlaywrightTimeoutError:
            if not self.is_running or self.interrupt_requested:
                return False
            self._validate_playwright_page_url(page)
            current_url = str(getattr(page, "url", "") or "")
            return bool(current_url and current_url != "about:blank")
        except Exception as exc:
            if not self.is_running or self.interrupt_requested:
                return False
            if exc.__class__.__name__ == "TimeoutError":
                self._validate_playwright_page_url(page)
                current_url = str(getattr(page, "url", "") or "")
                return bool(current_url and current_url != "about:blank")
            raise

    def _ensure_playwright_public_route(self, page) -> None:
        """安装覆盖 HTTP 资源、WebSocket 和页面脚本的请求防护。"""
        context = getattr(page, "context", None)
        policy = self._public_domain_policy_engine()
        try:
            if context is not None:
                install_public_network_guard(context, policy)
            context_has_http = callable(getattr(context, "route", None))
            context_has_websocket = callable(getattr(context, "route_web_socket", None))
            context_has_script = callable(getattr(context, "add_init_script", None))
            if context is None or not (context_has_http and context_has_websocket and context_has_script):
                install_public_network_guard(
                    page,
                    policy,
                    install_http=not context_has_http,
                    install_websocket=not context_has_websocket,
                    install_script=not context_has_script,
                )
        except DomainPolicyViolation as exc:
            debug_logger.log_exception(
                "BaseSpider",
                "install_playwright_network_guard",
                exc,
            )
            raise

    def _validate_playwright_page_url(self, page) -> None:
        current_url = str(getattr(page, "url", "") or "").strip()
        if not current_url or current_url == "about:blank":
            return
        if urllib.parse.urlsplit(current_url).scheme.lower() in {"http", "https"}:
            self._public_domain_policy_engine().require_public_url(current_url)

    @staticmethod
    def _playwright_navigation_has_started(before_url: str, current_url: str, target_url: str) -> bool:
        current = str(current_url or "").strip()
        before = str(before_url or "").strip()
        if not current or current == "about:blank":
            return False
        if current != before:
            return True
        try:
            current_parsed = urllib.parse.urlparse(current)
            target_parsed = urllib.parse.urlparse(str(target_url or ""))
        except (TypeError, ValueError):
            return False
        if not current_parsed.netloc or not target_parsed.netloc:
            return False
        return (
            current_parsed.netloc.lower() == target_parsed.netloc.lower()
            and current_parsed.path.rstrip("/") == target_parsed.path.rstrip("/")
        )

    @classmethod
    def _normalize_proxy_server(cls, value: object) -> str | None:
        """把 UI 标签、预设值和 host:port 统一为浏览器代理地址。"""
        text = str(value or "").strip()
        if not text:
            return None
        lowered = text.lower()
        if lowered in {"system", "system proxy", "auto", "none", "direct"}:
            return None
        if text in {"系统代理", "直连", "自定义"}:
            return None
        try:
            from app.core.plugins.run_options import PROXY_PRESET_URLS

            if text in PROXY_PRESET_URLS:
                return PROXY_PRESET_URLS[text] or None
        except (ImportError, AttributeError) as exc:
            debug_logger.log_exception("BaseSpider", "load_proxy_presets", exc)
        if lowered.startswith(("http://", "https://", "socks5://", "socks4://")):
            parsed = urllib.parse.urlparse(text)
            return text if parsed.hostname and parsed.port else None
        if ":" in text:
            return f"http://{text}"
        return None

    @classmethod
    def _proxy_from_environment(cls) -> str | None:
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            proxy = cls._normalize_proxy_server(os.environ.get(name))
            if proxy:
                return proxy
        return None

    @classmethod
    def _proxy_from_windows_settings(cls) -> str | None:
        if os.name != "nt":
            return None
        try:
            import winreg
        except ImportError:
            return None
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if not enabled:
                    return None
                raw_proxy, _ = winreg.QueryValueEx(key, "ProxyServer")
        except OSError:
            return None
        return cls._proxy_from_proxy_server_string(raw_proxy)

    @classmethod
    def _proxy_from_proxy_server_string(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if ";" not in text and "=" not in text:
            return cls._normalize_proxy_server(text)
        entries: dict[str, str] = {}
        for part in text.split(";"):
            if "=" not in part:
                continue
            key, raw_proxy = part.split("=", 1)
            entries[key.strip().lower()] = raw_proxy.strip()
        for key in ("https", "http", "socks", "socks5"):
            raw_proxy = entries.get(key)
            if key.startswith("socks") and raw_proxy and "://" not in raw_proxy:
                raw_proxy = f"socks5://{raw_proxy}"
            proxy = cls._normalize_proxy_server(raw_proxy)
            if proxy:
                return proxy
        return None

    def _effective_proxy_server(
        self,
        configured: object = None,
        *,
        allow_system_fallback: bool | None = None,
    ) -> str | None:
        configured_text = str(configured or "").strip()
        if configured_text.lower() in {"none", "direct"} or configured_text == "直连":
            return None
        configured_proxy = self._normalize_proxy_server(configured)
        if configured_proxy:
            return configured_proxy
        if allow_system_fallback is None:
            allow_system_fallback = bool(getattr(self, "ALLOW_SYSTEM_PROXY_FALLBACK", False))
        if not allow_system_fallback:
            return None
        env_proxy = self._proxy_from_environment()
        if env_proxy:
            return env_proxy
        return self._proxy_from_windows_settings()

    def _configured_timeout_seconds(self, *, default: int = 60, key: str = "timeout") -> int:
        """返回单任务爬取超时，并迁移旧版过短配置。"""
        config = getattr(self, "config", {}) or {}
        try:
            timeout = int(config.get(key, default) or default)
        except (TypeError, ValueError):
            timeout = int(default)
        if timeout <= 10:
            timeout = int(default)
        return max(30, min(timeout, 300))

    def _configured_timeout_ms(self, *, default: int = 60, key: str = "timeout") -> int:
        return self._configured_timeout_seconds(default=default, key=key) * 1000

    @staticmethod
    def _coerce_bool_setting(value: object, *, default: bool = True) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on", "show", "visible"}:
                return True
            if text in {"0", "false", "no", "off", "hide", "silent", "headless"}:
                return False
        return bool(value)

    def _should_show_browser_window(self) -> bool:
        config = getattr(self, "config", {}) or {}
        if isinstance(config, dict):
            for key in ("show_browser_window", "browser_visible", "visible_browser"):
                if key in config:
                    return self._coerce_bool_setting(config.get(key), default=True)
        try:
            from app.config import cfg

            return self._coerce_bool_setting(cfg.get("common", "show_browser_window", True), default=True)
        except Exception:
            return True

    def _browser_headless(self, *, login_window: bool = False) -> bool:
        if login_window:
            return False
        return not self._should_show_browser_window()

    def _playwright_launch_kwargs(
        self,
        *,
        headless: bool,
        proxy: object = None,
        args: list[str] | None = None,
        **extra,
    ) -> dict:
        """集中生成 browser.launch 参数，确保所有平台共享反自动化启动参数。"""
        from app.core.anti_detection.models import AUTOMATION_CONTROLLED_ARG

        kwargs = {"headless": headless, **extra}
        launch_args = list(args or [])
        if AUTOMATION_CONTROLLED_ARG not in launch_args:
            launch_args.append(AUTOMATION_CONTROLLED_ARG)
        kwargs["args"] = launch_args
        proxy_server = self._effective_proxy_server(proxy)
        if proxy_server:
            kwargs["proxy"] = {"server": proxy_server}
        return kwargs

    def _playwright_context_kwargs(
        self,
        *,
        user_agent: str = "",
        referer: str = "",
        viewport: dict[str, int] | None = None,
        **extra,
    ) -> dict:
        """集中生成 browser.new_context 参数，避免 UA/语言/时区策略在各平台漂移。"""
        from app.config import DEFAULT_USER_AGENT
        from app.core.anti_detection import build_browser_anti_detection

        anti_context = build_browser_anti_detection(
            getattr(self, "trace_prefix", "") or self.__class__.__name__.replace("Spider", "").lower() or "browser",
            {**(getattr(self, "config", {}) or {}), "ua": user_agent or "random"},
            referer=referer,
            default_user_agent=user_agent or DEFAULT_USER_AGENT,
            viewport=viewport,
        )
        kwargs = anti_context.browser_context_kwargs()
        kwargs.update(extra)
        # Service Worker 的请求可能绕过 page.route；禁用后所有浏览器请求都受 URL 策略约束。
        kwargs["service_workers"] = "block"
        return kwargs

    def _apply_stealth_to_context(self, context) -> None:
        from app.core.anti_detection import apply_stealth_to_context

        apply_stealth_to_context(context)

    def run(self):
        """线程入口：执行子类 `_run_impl()`，并保证任何退出路径都会通知宿主。"""
        try:
            self._run_impl()
        except BudgetExhausted:
            import logging
            logging.getLogger(__name__).info("Spider budget exhausted, stopping gracefully.")
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Spider _run_impl failed")
        finally:
            self._emit_finished()

    def _emit_finished(self) -> None:
        """先标记 Spider 已停止，再通知宿主爬取结束。"""
        self.is_running = False
        self.sig_finished.emit()

    def _run_impl(self):
        """子类必须重写此方法实现爬取逻辑。"""
        raise NotImplementedError("Subclasses must implement _run_impl().")

    def isRunning(self) -> bool:
        """兼容旧的 QThread 风格运行态判断。"""
        return self.is_alive()

    def wait(self, timeout_ms: int | None = None) -> bool:
        """兼容旧的 QThread 风格等待接口。"""
        timeout = None if timeout_ms is None else max(timeout_ms, 0) / 1000
        self.join(timeout=timeout)
        return not self.is_alive()

    def log(self, msg: str):
        """统一经信号输出日志，让 CLI/UI/Web 宿主各自决定展示方式。"""
        self.sig_log.emit(msg)

    def debug_state(
        self,
        action: str,
        message: str = "",
        status_code=None,
        context=None,
        details=None,
        trace_id=None,
        level: str = "INFO",
    ):
        """写入结构化调试日志，并尽量从上下文中继承 trace_id。"""
        if isinstance(context, dict):
            trace_id = trace_id or context.get("trace_id")
        if not trace_id and isinstance(details, dict):
            trace_id = details.get("trace_id")
        debug_logger.log(
            component=self.__class__.__name__,
            action=action,
            level=level,
            message=message,
            status_code=status_code,
            context=context,
            details=details,
            trace_id=trace_id,
        )

    def debug_api(self, api_name: str, request=None, response_summary=None, message: str = "", status_code=None):
        """记录一次平台 API 调用摘要，避免把完整响应直接刷进 UI 日志。"""
        trace_id = None
        if isinstance(request, dict):
            trace_id = request.get("trace_id")
        if not trace_id and isinstance(response_summary, dict):
            trace_id = response_summary.get("trace_id")
        debug_logger.log_api(
            component=self.__class__.__name__,
            api_name=api_name,
            request=request,
            response_summary=response_summary,
            message=message,
            status_code=status_code,
            trace_id=trace_id,
        )

    def new_trace_id(self, suffix: str = "task") -> str:
        """按平台前缀生成 trace_id，便于失败列表和日志中心串联同一任务。"""
        return debug_logger.new_trace_id(f"{self.trace_prefix}-{suffix}")

    def ensure_trace_id(self, meta: dict | None = None, suffix: str = "task") -> str:
        """确保下载 meta 带 trace_id；已有值必须保留，避免日志链路断裂。"""
        if meta is None:
            return self.new_trace_id(suffix)
        trace_id = meta.get("trace_id")
        if not trace_id:
            trace_id = self.new_trace_id(suffix)
            meta["trace_id"] = trace_id
        return trace_id

    def _platform_key(self, source: str | None = None) -> str:
        raw = source
        config = getattr(self, "config", {})
        if raw is None and isinstance(config, dict):
            raw = config.get("platform") or config.get("source")
        if raw is None:
            raw = self.__class__.__name__.replace("Spider", "")
        return str(raw or "spider").strip().lower() or "spider"

    @staticmethod
    def _guardrail_config(config: dict) -> dict:
        if not isinstance(config, dict):
            return {}
        guardrails = config.get("guardrails") or config.get("crawl_guardrails") or {}
        return guardrails if isinstance(guardrails, dict) else {}

    @staticmethod
    def _positive_int(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(1, parsed)

    @staticmethod
    def _positive_float(value: object, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.01, parsed)

    def _build_crawl_budget(self, config: dict) -> CrawlBudget:
        """把配置中的爬取预算归一化，防止异常配置让平台请求无限增长。"""
        guardrails = self._guardrail_config(config)
        budget_config = guardrails.get("budget") if isinstance(guardrails.get("budget"), dict) else guardrails
        return CrawlBudget(
            max_requests_per_platform=self._positive_int(
                budget_config.get("max_requests_per_platform"),
                1000,
            ),
            max_total=self._positive_int(budget_config.get("max_total"), 5000),
        )

    def _build_rate_limiter(self, config: dict) -> RateLimiter:
        """构建平台请求限速器；没有显式配置时使用平台默认速率。"""
        guardrails = self._guardrail_config(config)
        rate_config = guardrails.get("rate_limiter") if isinstance(guardrails.get("rate_limiter"), dict) else {}
        if "rate_per_second" not in rate_config and "rate" not in rate_config:
            return RateLimiter.for_platform(self._platform_key())
        rate_per_second = self._positive_float(
            rate_config.get("rate_per_second", rate_config.get("rate")),
            1.0,
        )
        burst = self._positive_float(rate_config.get("capacity", rate_config.get("burst")), max(1.0, rate_per_second))
        return RateLimiter(tokens_per_second=rate_per_second, burst=burst)

    def guard_request(self, source: str | None = None, *, cancel_check: Callable[[], bool] | None = None) -> None:
        platform = self._platform_key(source)
        config = getattr(self, "config", {})
        if not isinstance(config, dict):
            config = {}
        budget = getattr(self, "budget", None)
        if budget is None:
            budget = self._build_crawl_budget(config)
            self.budget = budget
        rate_limiter = getattr(self, "rate_limiter", None)
        if rate_limiter is None:
            rate_limiter = self._build_rate_limiter(config)
            self.rate_limiter = rate_limiter
        budget.consume(platform)
        allowed = rate_limiter.acquire(
            cancel_check=cancel_check or (lambda: not self.is_running or self.interrupt_requested),
        )
        if allowed is False:
            raise RateLimitCancelled(f"Request cancelled before rate-limit permit for {platform}.")

    def emit_video(self, url: str, title: str, source: str, meta: dict | None = None):
        # Spider 发现的资源都会进入网络下载层；统一在发射边界标记公网策略，
        # 防止某个平台 task builder 漏字段后绕过下载器的逐跳校验。
        clean_meta = sanitize(meta or {})
        item = VideoItem(
            url=str(sanitize(url)),
            title=str(sanitize(title)),
            source=str(sanitize(source)),
        )
        if isinstance(clean_meta, dict):
            item.meta = clean_meta
        elif clean_meta:
            item.meta = {"raw_meta": clean_meta}
        item.meta["_network_policy"] = "public"
        self.ensure_trace_id(item.meta, suffix=item.source)
        self.sig_item_found.emit(item)

    def emit_videos(self, items: list[VideoItem]) -> int:
        """用一次回调发射已装配的下载项，降低宿主事件队列压力。"""
        ready_items: list[VideoItem] = []
        for item in items:
            if not isinstance(item, VideoItem):
                continue
            clean_meta = sanitize(getattr(item, "meta", {}) or {})
            if isinstance(clean_meta, dict):
                item.meta = clean_meta
            elif clean_meta:
                item.meta = {"raw_meta": clean_meta}
            item.meta["_network_policy"] = "public"
            self.ensure_trace_id(item.meta, suffix=item.source)
            item.url = str(sanitize(item.url))
            item.title = str(sanitize(item.title))
            item.source = str(sanitize(item.source))
            ready_items.append(item)
        if not ready_items:
            return 0
        self.sig_items_found.emit(ready_items)
        return len(ready_items)

    # 暂停 Spider 线程，把候选项交给 UI/CLI/Web 选择，再等宿主回填结果。
    def ask_user_selection(self, items: list) -> list | None:
        # Spider 线程会阻塞在这里，直到宿主调用 resume_from_ui。
        self._resume_event.clear()
        self._selection_result = None
        self._selection_emit_perf_ms = time.perf_counter() * 1000
        self._selection_emit_wall_ms = int(time.time() * 1000)
        with self._running_guard():
            selection_epoch = self._selection_epoch
        self.sig_select_tasks.emit(items)
        while self.is_running and not self.interrupt_requested:
            if self._resume_event.wait(timeout=0.2):
                break
        with self._running_guard():
            selection_cancelled = selection_epoch != self._selection_epoch
        if not self.is_running or self.interrupt_requested or selection_cancelled:
            return None
        return self._selection_result

    def resume_from_ui(self, selected_indices):
        """UI 收集选择结果后恢复 Spider 线程。"""
        self._selection_result = selected_indices
        self._resume_event.set()

    def get_selection_emit_trace(self) -> dict[str, float | int]:
        """返回最近一次选择框事件的发射时间，供可观测性记录使用。"""
        return {
            "spider_emit_perf_ms": self._selection_emit_perf_ms,
            "spider_emit_wall_ms": self._selection_emit_wall_ms,
        }

    def revive_for_partial_selection(
        self,
        collected_count: int,
        label: str = "结果",
        *,
        requires_browser: bool = False,
    ) -> bool:
        """停止后若已有候选结果，短暂恢复运行态以完成“选择并生成任务”。"""
        if self.is_running:
            return True
        if collected_count <= 0:
            self.log("🛑 任务已终止")
            return False
        if requires_browser and not self.is_playwright_browser_tracked():
            self.log("🛑 浏览器已关闭，无法继续需要网页的操作")
            return False
        self.log(f"⏸️ 抓取已停止，已保留 {collected_count} 个{label}，准备生成清单...")
        self._interrupt_requested = False
        self.is_running = True
        return True
