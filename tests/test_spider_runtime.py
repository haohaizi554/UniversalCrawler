import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.spiders.base import BaseSpider
from shared.spider_session_runtime import SpiderSession, SpiderSessionBindings


class _FakeSignal:
    def __init__(self):
        self.targets = []

    def connect(self, target):
        self.targets.append(target)


class _FakeSpider:
    def __init__(self):
        self.sig_log = _FakeSignal()
        self.sig_item_found = _FakeSignal()
        self.sig_select_tasks = _FakeSignal()
        self.sig_finished = _FakeSignal()
        self.start = Mock()
        self.stop = Mock()


class SpiderSessionTests(unittest.TestCase):
    def test_create_spider_raises_for_unknown_source(self):
        session = SpiderSession(plugin_registry=SimpleNamespace(get_plugin=lambda _source: None))

        with self.assertRaisesRegex(ValueError, "未知的爬虫源"):
            session.create_spider("missing", "kw", {})

    def test_start_session_creates_binds_and_starts_spider(self):
        spider = _FakeSpider()
        plugin = SimpleNamespace(get_spider_class=lambda: lambda keyword, config: spider)
        registry = SimpleNamespace(get_plugin=lambda _source: plugin)
        session = SpiderSession(plugin_registry=registry)
        patch_spider = Mock()
        bindings = SpiderSessionBindings(
            on_log=Mock(),
            on_item_found=Mock(),
            on_select_tasks=Mock(),
            on_finished=Mock(),
            patch_spider=patch_spider,
        )

        returned_plugin, returned_spider = session.start_session("douyin", "kw", {"max_items": 1}, bindings)

        self.assertIs(returned_plugin, plugin)
        self.assertIs(returned_spider, spider)
        patch_spider.assert_called_once_with(spider)
        spider.start.assert_called_once()
        self.assertEqual(spider.sig_log.targets, [bindings.on_log])
        self.assertEqual(spider.sig_item_found.targets, [bindings.on_item_found])
        self.assertEqual(spider.sig_select_tasks.targets, [bindings.on_select_tasks])
        self.assertEqual(spider.sig_finished.targets, [bindings.on_finished])

    def test_activate_spider_binds_and_starts_existing_instance(self):
        spider = _FakeSpider()
        bindings = SpiderSessionBindings(
            on_log=Mock(),
            on_item_found=Mock(),
            on_select_tasks=Mock(),
            on_finished=Mock(),
            patch_spider=Mock(),
        )

        returned = SpiderSession.activate_spider(spider, bindings)

        self.assertIs(returned, spider)
        bindings.patch_spider.assert_called_once_with(spider)
        spider.start.assert_called_once()
        self.assertEqual(spider.sig_log.targets, [bindings.on_log])
        self.assertEqual(spider.sig_item_found.targets, [bindings.on_item_found])
        self.assertEqual(spider.sig_select_tasks.targets, [bindings.on_select_tasks])
        self.assertEqual(spider.sig_finished.targets, [bindings.on_finished])

    def test_stop_session_forwards_stop_request(self):
        spider = _FakeSpider()

        SpiderSession.stop_session(spider)

        spider.stop.assert_called_once()


class _LifecycleSpider(BaseSpider):
    def __init__(self, steps: list[str], *, should_fail: bool = False):
        super().__init__("kw", {})
        self.steps = steps
        self.should_fail = should_fail

    def _run_impl(self):
        self.steps.append("run_impl")
        if self.should_fail:
            raise RuntimeError("boom")


class BaseSpiderLifecycleTests(unittest.TestCase):
    def test_run_emits_finished_after_run_impl(self):
        steps: list[str] = []
        spider = _LifecycleSpider(steps)
        spider.sig_finished.connect(lambda: steps.append("finished"))

        spider.run()

        self.assertEqual(steps, ["run_impl", "finished"])

    def test_run_still_emits_finished_when_run_impl_raises(self):
        steps: list[str] = []
        spider = _LifecycleSpider(steps, should_fail=True)
        spider.sig_finished.connect(lambda: steps.append("finished"))

        spider.run()

        self.assertEqual(steps, ["run_impl", "finished"])

