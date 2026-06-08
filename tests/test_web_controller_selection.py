import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.spiders.base import BaseSpider
from app.web.controller import WebController


class _DummySpider(BaseSpider):
    def run(self):
        return


class WebControllerSelectionBridgeTests(unittest.TestCase):
    def test_bind_spider_signals_monkey_patches_web_selection_bridge(self):
        spider = _DummySpider(keyword="kw", config={})

        def on_select(items):
            self.assertEqual(items, [{"title": "A", "index": 0}, {"title": "B", "index": 1}])
            spider.resume_from_ui([1])

        controller = SimpleNamespace(
            _pending_selection_strategy=None,
            bridge=SimpleNamespace(emit=Mock()),
            _on_spider_item_found=Mock(),
            _on_spider_select_tasks=on_select,
            _on_spider_finished=Mock(),
        )

        WebController._bind_spider_signals(controller, spider)

        result = spider.ask_user_selection([{"title": "A", "index": 0}, {"title": "B", "index": 1}])

        self.assertEqual(result, [1])


if __name__ == "__main__":
    unittest.main()
