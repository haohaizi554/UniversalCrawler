"""BaseSpider 纯 Python 线程与信号契约测试。"""

from __future__ import annotations

import unittest
import threading
from unittest.mock import patch

from app.spiders.base import BaseSpider
from app.utils.callback_signal import CallbackSignal

class _DummySpider(BaseSpider):
    def run(self):
        self.log("started")
        self.emit_video(
            url="https://cdn.example.com/demo.mp4",
            title="demo",
            source="douyin",
            meta={"trace_id": "trace-spider-base"},
        )
        self.sig_finished.emit()

class _RunImplSpider(BaseSpider):
    def _run_impl(self):
        self.log("impl")

class BaseSpiderTests(unittest.TestCase):
    def test_base_spider_runs_without_qt_and_emits_callbacks(self):
        logs: list[str] = []
        items = []
        finished = []

        spider = _DummySpider(keyword="demo", config={})
        spider.sig_log.connect(logs.append)
        spider.sig_item_found.connect(items.append)
        spider.sig_finished.connect(lambda: finished.append(True))

        spider.start()

        self.assertTrue(spider.wait(1000))
        self.assertFalse(spider.isRunning())
        self.assertEqual(logs, ["started"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "demo")
        self.assertEqual(finished, [True])

    def test_base_run_marks_internal_running_state_false_before_finish_signal(self):
        observed: list[bool] = []
        spider = _RunImplSpider(keyword="demo", config={})
        spider.sig_finished.connect(lambda: observed.append(spider.is_running))

        spider.start()

        self.assertTrue(spider.wait(1000))
        self.assertEqual(observed, [False])
        self.assertFalse(spider.is_running)

    def test_callback_signal_disconnect_clears_subscribers(self):
        logs: list[str] = []
        spider = _DummySpider(keyword="demo", config={})
        spider.sig_log.connect(logs.append)
        spider.sig_log.disconnect()

        spider.log("ignored")

        self.assertEqual(logs, [])

    def test_callback_signal_isolates_failing_subscribers(self):
        signal = CallbackSignal()
        calls: list[tuple[str, str]] = []

        def broken(value: str) -> None:
            calls.append(("broken", value))
            raise RuntimeError("boom")

        def healthy(value: str) -> None:
            calls.append(("healthy", value))

        signal.connect(broken)
        signal.connect(healthy)

        with self.assertLogs("app.utils.callback_signal", level="ERROR") as logs:
            signal.emit("payload")

        self.assertEqual(calls, [("broken", "payload"), ("healthy", "payload")])
        self.assertTrue(any("subscriber failed" in line for line in logs.output))

    def test_callback_signal_warns_for_slow_subscribers(self):
        signal = CallbackSignal()
        signal.SLOW_CALLBACK_SECONDS = 0.01
        signal.connect(lambda: None)

        with (
            patch("app.utils.callback_signal.time.perf_counter", side_effect=[10.0, 10.2]),
            self.assertLogs("app.utils.callback_signal", level="WARNING") as logs,
        ):
            signal.emit()

        self.assertTrue(any("subscriber was slow" in line for line in logs.output))

    def test_is_running_property_tolerates_concurrent_reads_and_writes(self):
        spider = _DummySpider(keyword="demo", config={})
        errors: list[Exception] = []

        def writer(value: bool) -> None:
            try:
                for _ in range(100):
                    spider.is_running = value
                    self.assertIsInstance(spider.is_running, bool)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(value,)) for value in (False, True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        spider.is_running = False

        self.assertEqual(errors, [])
        self.assertFalse(spider.is_running)

    def test_browser_headless_follows_visibility_setting_except_login(self):
        spider = _DummySpider(keyword="demo", config={"show_browser_window": False})

        self.assertTrue(spider._browser_headless())
        self.assertFalse(spider._browser_headless(login_window=True))

        spider.config = {"show_browser_window": "visible"}
        self.assertFalse(spider._browser_headless())

        spider.config = {"show_browser_window": "headless"}
        self.assertTrue(spider._browser_headless())

    def test_stop_closes_tracked_playwright_browser_from_control_thread(self):
        spider = _DummySpider(keyword="demo", config={})

        class FakeBrowser:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        browser = FakeBrowser()
        spider._track_playwright_browser(browser)

        worker = threading.Thread(target=spider.stop)
        worker.start()
        worker.join(timeout=1)

        self.assertTrue(browser.closed)
        self.assertFalse(spider.is_playwright_browser_tracked())
        self.assertFalse(spider.is_running)

    def test_interruptible_playwright_goto_returns_when_stopped_during_timeout_slice(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            def goto(self, *_args, **_kwargs):
                calls.append(1)
                spider.is_running = False
                raise PlaywrightLikeTimeoutError("timeout")

        result = spider.interruptible_playwright_goto(FakePage(), "https://example.com", timeout=60000, slice_ms=10)

        self.assertFalse(result)
        self.assertEqual(len(calls), 1)

    def test_interruptible_playwright_goto_uses_one_full_timeout_navigation(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            url = "about:blank"

            def goto(self, url, *_args, **_kwargs):
                calls.append(_kwargs["timeout"])
                self.url = url
                raise PlaywrightLikeTimeoutError("slow load")

        result = spider.interruptible_playwright_goto(
            FakePage(),
            "https://example.com/slow",
            timeout=60000,
            slice_ms=15000,
        )

        self.assertTrue(result)
        self.assertEqual(calls, [60000])

    def test_interruptible_playwright_reload_uses_one_full_timeout_reload(self):
        spider = _DummySpider(keyword="demo", config={})
        calls: list[int] = []

        class PlaywrightLikeTimeoutError(Exception):
            pass

        PlaywrightLikeTimeoutError.__name__ = "TimeoutError"

        class FakePage:
            url = "https://example.com/current"

            def reload(self, *_args, **_kwargs):
                calls.append(_kwargs["timeout"])
                raise PlaywrightLikeTimeoutError("slow reload")

        result = spider.interruptible_playwright_reload(
            FakePage(),
            timeout=60000,
            wait_until="domcontentloaded",
        )

        self.assertTrue(result)
        self.assertEqual(calls, [60000])

    def test_guard_request_lazily_initializes_guardrails_for_minimal_test_doubles(self):
        spider = _DummySpider.__new__(_DummySpider)
        spider.config = {}
        spider.is_running = True

        spider.guard_request("douyin")

        self.assertEqual(spider.budget.snapshot()["total"], 1)

    def test_emit_video_is_local_dispatch_not_rate_limited(self):
        spider = _DummySpider(keyword="demo", config={})
        emitted = []
        guard_calls = []

        def guard_request(*args, **kwargs):
            guard_calls.append((args, kwargs))
            raise AssertionError("emit_video must not rate-limit local item dispatch")

        spider.guard_request = guard_request
        spider.sig_item_found.connect(emitted.append)

        spider.emit_video(
            url="https://cdn.example.com/one.jpg",
            title="one",
            source="xiaohongshu",
            meta={"trace_id": "xhs_emit_test", "content_type": "image"},
        )

        self.assertEqual(guard_calls, [])
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].source, "xiaohongshu")
        self.assertEqual(emitted[0].meta["content_type"], "image")

if __name__ == "__main__":
    unittest.main()
