"""Base spider helpers used by all platforms."""

from __future__ import annotations

import threading
import time
import os
import urllib.parse
from collections.abc import Callable

from app.debug_logger import debug_logger
from app.core.guardrails import BudgetExhausted, CrawlBudget, RateLimiter, sanitize
from app.core.guardrails.crawl_budget import RateLimitCancelled
from app.models import VideoItem
from app.utils.callback_signal import CallbackSignal

class BaseSpider(threading.Thread):
    """Common pure-Python spider thread base with UI selection helpers."""

    def __init__(self, keyword: str, config: dict):
        """初始化当前实例并准备运行所需的状态，供 `BaseSpider` 使用。"""
        super().__init__(daemon=True, name=self.__class__.__name__)
        self.keyword = keyword
        self.config = config
        self._running_lock = threading.RLock()
        self._is_running = True
        self.sig_log = CallbackSignal()
        self.sig_item_found = CallbackSignal()
        self.sig_finished = CallbackSignal()
        self.sig_select_tasks = CallbackSignal()
        self.trace_prefix = self.__class__.__name__.replace("Spider", "").lower() or "spider"
        self.budget = self._build_crawl_budget(config)
        self.rate_limiter = self._build_rate_limiter(config)
        # The spider thread waits on this event while the UI shows a selection dialog.
        self._resume_event = threading.Event()
        self._selection_result = None
        self._selection_emit_perf_ms = 0.0
        self._selection_emit_wall_ms = 0
        # 修复 BUG-168: 暴露 Playwright browser/context 引用，方便 controller 强制中断
        self._playwright_lock = threading.RLock()
        self._playwright_browser = None
        self._playwright_owner_thread_id: int | None = None
        self._playwright_pw = None
        self._selection_epoch = 0
        self._interrupt_requested = False

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
        
        self.is_running = False
        self._interrupt_requested = True
        self._selection_epoch += 1
        self._resume_event.set()
        self._close_tracked_playwright_browser()
        self.sig_log.emit("🛑 正在停止任务...")

    def _track_playwright_browser(self, browser) -> None:
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

    def is_playwright_browser_tracked(self) -> bool:
        """Return whether a Playwright browser is currently tracked for cleanup."""
        return self._tracked_playwright_browser() is not None

    def _playwright_guard(self) -> threading.RLock:
        lock = getattr(self, "_playwright_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._playwright_lock = lock
        return lock

    def interruptible_sleep(self, seconds: float, step: float = 0.5):
        """修复 BUG-168: 可中断的 sleep，每 step 秒检查一次 is_running。
        替代 time.sleep(seconds)，避免用户点停止后等几十秒才响应。
        """
        import time as _time
        deadline = _time.time() + seconds
        while _time.time() < deadline:
            if not self.is_running or self.interrupt_requested:
                return False
            remaining = deadline - _time.time()
            _time.sleep(min(step, remaining))
        return self.is_running

    def interruptible_page_wait(self, page, timeout_ms: int, *, step_ms: int = 500) -> bool:
        """Slice ``page.wait_for_timeout`` so ``stop()`` is observed between chunks."""
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
        """Wait for a selector in short slices so stop requests are observed quickly."""
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
        """Wait for a Playwright load state without hiding stop requests for seconds."""
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
        """Navigate once and let tracked-browser cleanup interrupt a stop request.

        ``page.goto`` is not a pollable wait: calling it again after a short timeout
        starts a new navigation and makes slow SPA pages look like they are being
        constantly refreshed.  Keep a single navigation attempt here; callers that
        need retries should wrap this method explicitly.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if not self.is_running or self.interrupt_requested:
            return False
        try:
            self.guard_request(cancel_check=lambda: not self.is_running)
        except BudgetExhausted as exc:
            self.sig_log.emit(f"Guardrail stopped navigation: {exc}")
            raise
        before_url = str(getattr(page, "url", "") or "")
        try:
            page.goto(url, timeout=max(1, int(timeout)), **kwargs)
            return True
        except PlaywrightTimeoutError:
            if not self.is_running or self.interrupt_requested:
                return False
            return self._playwright_navigation_has_started(
                before_url,
                str(getattr(page, "url", "") or ""),
                url,
            )
        except Exception as exc:
            if not self.is_running or self.interrupt_requested:
                return False
            if exc.__class__.__name__ == "TimeoutError":
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
        """Reload once with the full timeout and keep stop semantics consistent.

        Some platform pages keep loading SPA resources long after the useful DOM is
        ready. Retrying short reloads makes those pages look like they are being
        refreshed in a loop, so this helper mirrors ``interruptible_playwright_goto``:
        one reload attempt, full timeout, then treat an already-started page as
        usable unless the user stopped the task.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if not self.is_running or self.interrupt_requested:
            return False
        try:
            self.guard_request(cancel_check=lambda: not self.is_running)
        except BudgetExhausted as exc:
            self.sig_log.emit(f"Guardrail stopped reload: {exc}")
            raise
        try:
            page.reload(timeout=max(1, int(timeout)), **kwargs)
            return True
        except PlaywrightTimeoutError:
            if not self.is_running or self.interrupt_requested:
                return False
            current_url = str(getattr(page, "url", "") or "")
            return bool(current_url and current_url != "about:blank")
        except Exception as exc:
            if not self.is_running or self.interrupt_requested:
                return False
            if exc.__class__.__name__ == "TimeoutError":
                current_url = str(getattr(page, "url", "") or "")
                return bool(current_url and current_url != "about:blank")
            raise

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
        """Normalize UI labels, presets, and host:port values for browser/proxy clients."""
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

    def _effective_proxy_server(self, configured: object = None) -> str | None:
        configured_text = str(configured or "").strip()
        if configured_text.lower() in {"none", "direct"} or configured_text == "直连":
            return None
        configured_proxy = self._normalize_proxy_server(configured)
        if configured_proxy:
            return configured_proxy
        env_proxy = self._proxy_from_environment()
        if env_proxy:
            return env_proxy
        return self._proxy_from_windows_settings()

    def _configured_timeout_seconds(self, *, default: int = 60, key: str = "timeout") -> int:
        """Return the per-task crawler timeout, migrating legacy short values."""
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

    def _playwright_launch_kwargs(
        self,
        *,
        headless: bool,
        proxy: object = None,
        args: list[str] | None = None,
        **extra,
    ) -> dict:
        kwargs = {"headless": headless, **extra}
        if args:
            kwargs["args"] = args
        proxy_server = self._effective_proxy_server(proxy)
        if proxy_server:
            kwargs["proxy"] = {"server": proxy_server}
        return kwargs

    def run(self):
        """执行当前对象或脚本的主流程，供 `BaseSpider` 使用。

        子类应重写 ``_run_impl()`` 而非此方法。run() 保证无论
        _run_impl 是否抛异常，都会 emit sig_finished。
        异常被捕获并记录，不会传播到调用者。
        """
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
        """Mark the spider stopped before notifying hosts that the crawl ended."""
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
        
        return debug_logger.new_trace_id(f"{self.trace_prefix}-{suffix}")

    def ensure_trace_id(self, meta: dict | None = None, suffix: str = "task") -> str:
        
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

    # Video discovery and dispatch.
    def emit_video(self, url: str, title: str, source: str, meta: dict | None = None):
        # Emitting a local item is pipeline dispatch, not network I/O. Network
        # guardrails belong in request/navigation helpers; throttling here
        # serializes already-parsed batches such as Xiaohongshu image notes.
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
        self.ensure_trace_id(item.meta, suffix=item.source)
        self.sig_item_found.emit(item)

    #暂停爬虫线程，向 UI 发送选择请求，等待用户选择结果
    def ask_user_selection(self, items: list) -> list | None:
        # The spider thread blocks here until the UI resumes it.
        
        self._resume_event.clear()#准备进入等待状态
        self._selection_result = None
        self._selection_emit_perf_ms = time.perf_counter() * 1000
        self._selection_emit_wall_ms = int(time.time() * 1000)
        selection_epoch = self._selection_epoch
        self.sig_select_tasks.emit(items)
        while self.is_running and not self.interrupt_requested:
            if self._resume_event.wait(timeout=0.2):
                break
        if not self.is_running or self.interrupt_requested or selection_epoch != self._selection_epoch:
            return None
        return self._selection_result

    def resume_from_ui(self, selected_indices):
        """Resume a spider thread after the UI collected user choices."""
        self._selection_result = selected_indices
        self._resume_event.set()

    def get_selection_emit_trace(self) -> dict[str, float | int]:
        """Return the latest selection-dialog emission timing for observability."""
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
        """Allow selection on already collected items after the user clicks stop."""
        if self.is_running:
            return True
        if collected_count <= 0:
            self.log("🛑 任务已终止")
            return False
        if requires_browser and not self.is_playwright_browser_tracked():
            self.log("🛑 浏览器已关闭，无法继续需要网页的操作")
            return False
        self.log(f"⏸️ 抓取已停止，已保留 {collected_count} 个{label}，准备生成清单...")
        self.is_running = True
        return True
