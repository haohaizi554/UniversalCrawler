"""BaseSpider 纯 Python 线程与信号契约测试。"""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
