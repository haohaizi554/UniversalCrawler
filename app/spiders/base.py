"""Base spider helpers used by all platforms."""

from __future__ import annotations

import threading
import time
import urllib.parse

from app.debug_logger import debug_logger
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
            owner_id = self._playwright_owner_thread_id
        if owner_id is not None and owner_id != threading.get_ident():
            return
        try:
            browser.close()
        except Exception:
            pass
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

    def interruptible_playwright_goto(
        self,
        page,
        url: str,
        *,
        timeout: int = 60000,
        slice_ms: int = 15000,
        **kwargs,
    ) -> bool:
        """Navigate without repeatedly refreshing slow pages, while still observing stop()."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        deadline = time.monotonic() + max(0, timeout) / 1000
        last_timeout: Exception | None = None
        while self.is_running and not self.interrupt_requested:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                if last_timeout is not None:
                    raise last_timeout
                return False
            try:
                before_url = str(getattr(page, "url", "") or "")
                page.goto(url, timeout=max(1, min(slice_ms, remaining_ms)), **kwargs)
                return True
            except PlaywrightTimeoutError as exc:
                if not self.is_running or self.interrupt_requested:
                    return False
                if self._playwright_navigation_has_started(before_url, str(getattr(page, "url", "") or ""), url):
                    return True
                last_timeout = exc
            except Exception as exc:
                if not self.is_running or self.interrupt_requested:
                    return False
                if exc.__class__.__name__ == "TimeoutError":
                    if self._playwright_navigation_has_started(
                        before_url,
                        str(getattr(page, "url", "") or ""),
                        url,
                    ):
                        return True
                    last_timeout = exc
                    continue
                raise
        return False

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

    def run(self):
        """执行当前对象或脚本的主流程，供 `BaseSpider` 使用。

        子类应重写 ``_run_impl()`` 而非此方法。run() 保证无论
        _run_impl 是否抛异常，都会 emit sig_finished。
        异常被捕获并记录，不会传播到调用者。
        """
        try:
            self._run_impl()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Spider _run_impl failed")
        finally:
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

    #视频发现与分发
    def emit_video(self, url: str, title: str, source: str, meta: dict | None = None):
        
        item = VideoItem(url=url, title=title, source=source)
        if meta:
            item.meta = meta
        self.ensure_trace_id(item.meta, suffix=source)
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
