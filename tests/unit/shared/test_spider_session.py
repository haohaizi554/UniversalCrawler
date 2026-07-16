"""Spider session bind/unbind lifecycle tests."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from shared.spider_session_runtime import SpiderSession, SpiderSessionBindings

class SpiderSessionUnbindTests(unittest.TestCase):
    def test_unbind_removes_registered_callbacks(self):
        spider = Mock()
        spider.sig_log = Mock()
        spider.sig_item_found = Mock()
        spider.sig_items_found = Mock()
        spider.sig_select_tasks = Mock()
        spider.sig_finished = Mock()

        bindings = SpiderSessionBindings(
            on_log=Mock(),
            on_item_found=Mock(),
            on_items_found=Mock(),
            on_select_tasks=Mock(),
            on_finished=Mock(),
        )
        SpiderSession.bind_spider(spider, bindings)
        SpiderSession.unbind_spider(spider, bindings)

        spider.sig_log.disconnect.assert_called_once_with(bindings.on_log)
        spider.sig_item_found.disconnect.assert_called_once_with(bindings.on_item_found)
        spider.sig_items_found.disconnect.assert_called_once_with(bindings.on_items_found)
        spider.sig_select_tasks.disconnect.assert_called_once_with(bindings.on_select_tasks)
        spider.sig_finished.disconnect.assert_called_once_with(bindings.on_finished)

if __name__ == "__main__":
    unittest.main()
