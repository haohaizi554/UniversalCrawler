"""BaseSpider 纯 Python 线程与信号契约测试。"""

from __future__ import annotations

import unittest
import threading

from app.spiders.base import BaseSpider

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

    def test_callback_signal_disconnect_clears_subscribers(self):
        logs: list[str] = []
        spider = _DummySpider(keyword="demo", config={})
        spider.sig_log.connect(logs.append)
        spider.sig_log.disconnect()

        spider.log("ignored")

        self.assertEqual(logs, [])

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

    def test_stop_does_not_close_playwright_browser_from_non_owner_thread(self):
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

        self.assertFalse(browser.closed)
        self.assertFalse(hasattr(spider, "_playwright_close_requested"))
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

if __name__ == "__main__":
    unittest.main()
