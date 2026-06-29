"""Playwright stop/resume helper tests."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.spiders.base import BaseSpider

class _StopSpider(BaseSpider):
    def _run_impl(self):
        return None

class SpiderStopPlaywrightTests(unittest.TestCase):
    def test_interruptible_page_wait_returns_false_after_stop(self):
        spider = _StopSpider("kw", {})
        page = Mock()

        def wait_side_effect(ms):
            spider.stop()

        page.wait_for_timeout.side_effect = wait_side_effect
        result = spider.interruptible_page_wait(page, 3000, step_ms=100)
        self.assertFalse(result)

    def test_revive_requires_browser_when_requested(self):
        spider = _StopSpider("kw", {})
        spider.stop()
        self.assertFalse(spider.revive_for_partial_selection(3, requires_browser=True))

if __name__ == "__main__":
    unittest.main()
