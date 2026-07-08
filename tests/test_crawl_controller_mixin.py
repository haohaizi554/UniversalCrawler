import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.controllers.crawl_controller_mixin import CrawlControllerMixin
from app.core.events import (
    build_crawl_state_event,
    build_item_found_event,
    build_items_found_event,
    build_selection_required_event,
)
from app.core.state import CrawlStatus
from app.models import VideoItem
from shared.controller_session import ControllerSessionMixin

class _DummyCrawlController(CrawlControllerMixin, ControllerSessionMixin):
    DOWNLOAD_LOG_COMPONENT = "DummyCrawlController"
    DOWNLOAD_FINISHED_STATUS_CODE = "DUMMY_OK"
    DOWNLOAD_ERROR_STATUS_CODE = "DUMMY_ERR"
    DOWNLOAD_FINISHED_MESSAGE = "dummy finished"
    DOWNLOAD_ERROR_MESSAGE = "dummy error"

    def __init__(self):
        self.host = Mock()
        self._spider_bridge = Mock()
        self.spider_session = Mock()
        self.dl_manager = Mock()
        self.videos = {}
        self.current_spider = None

    def _host(self):
        return self.host

    @staticmethod
    def _event_payload(event):
        return event.to_payload()

    @staticmethod
    def _item_details(item: VideoItem) -> dict:
        return {"title": item.title}

    @staticmethod
    def _prepare_pending_item(item: VideoItem) -> VideoItem:
        item.status = "⏳ 等待中"
        item.progress = 0
        return item

    def _store_video_item(self, item: VideoItem) -> None:
        self.videos[item.id] = item

class CrawlControllerMixinTests(unittest.TestCase):
    def test_create_spider_reports_unknown_source(self):
        controller = _DummyCrawlController()
        controller.spider_session.create_spider.side_effect = ValueError("unknown")

        plugin, spider = controller._create_spider("unknown", "kw", {})

        self.assertIsNone(plugin)
        self.assertIsNone(spider)
        controller.host.notify_unknown_source.assert_called_once()

    def test_bind_spider_signals_uses_event_bridge_callbacks(self):
        controller = _DummyCrawlController()
        spider = Mock()

        controller._bind_spider_signals(spider)

        bindings = controller.spider_session.bind_spider.call_args.args[1]
        self.assertIs(bindings.on_log.__self__, controller)
        self.assertIs(bindings.on_log.__func__, controller._emit_spider_log_event.__func__)
        self.assertIs(bindings.on_item_found.__self__, controller)
        self.assertIs(bindings.on_item_found.__func__, controller._emit_spider_item_found_event.__func__)
        self.assertIs(bindings.on_items_found.__self__, controller)
        self.assertIs(bindings.on_items_found.__func__, controller._emit_spider_items_found_event.__func__)
        self.assertIs(bindings.on_select_tasks.__self__, controller)
        self.assertIs(bindings.on_select_tasks.__func__, controller._emit_spider_selection_event.__func__)
        self.assertIs(bindings.on_finished.__self__, controller)
        self.assertIs(bindings.on_finished.__func__, controller._emit_spider_finished_event.__func__)

    def test_on_start_crawl_begins_host_and_starts_spider(self):
        controller = _DummyCrawlController()
        plugin = SimpleNamespace(name="抖音")
        spider = Mock()
        controller._create_spider = Mock(return_value=(plugin, spider))
        controller._log_crawl_start = Mock()

        controller.on_start_crawl("关键词", "douyin", {"max_items": 20})

        controller.host.begin_crawl.assert_called_once_with("抖音")
        controller.spider_session.activate_spider.assert_called_once()
        activated_spider, bindings = controller.spider_session.activate_spider.call_args.args
        self.assertIs(activated_spider, spider)
        self.assertIs(bindings.on_log.__self__, controller)
        self.assertIs(bindings.on_item_found.__self__, controller)
        self.assertIs(bindings.on_items_found.__self__, controller)
        self.assertIs(bindings.on_select_tasks.__self__, controller)
        self.assertIs(bindings.on_finished.__self__, controller)
        self.assertIs(controller.current_spider, spider)

    def test_on_start_crawl_rejects_current_spider_before_thread_start(self):
        controller = _DummyCrawlController()
        controller.current_spider = Mock(is_running=True)
        controller._create_spider = Mock()

        controller.on_start_crawl("关键词", "douyin", {"max_items": 20})

        controller.host.notify_crawl_already_running.assert_called_once()
        controller._create_spider.assert_not_called()

    def test_on_stop_crawl_stops_session_and_notifies_host(self):
        controller = _DummyCrawlController()
        controller.current_spider = Mock()

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller.on_stop_crawl()

        controller.spider_session.stop_session.assert_called_once_with(
            controller.current_spider,
            getattr(controller, "_active_spider_bindings", None),
        )
        controller.host.notify_crawl_stop_requested.assert_called_once()

    def test_on_stop_crawl_keeps_bindings_until_spider_finished(self):
        controller = _DummyCrawlController()
        bindings = Mock()
        controller._active_spider_bindings = bindings
        controller.current_spider = Mock()

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller.on_stop_crawl()

        self.assertIs(controller._active_spider_bindings, bindings)
        controller.host.finish_crawl.assert_not_called()

        controller._on_spider_finished()

        controller.host.finish_crawl.assert_called_once()
        self.assertIsNone(controller._active_spider_bindings)
        self.assertIsNone(controller.current_spider)

    def test_selection_cancel_requests_spider_stop_before_resume(self):
        controller = _DummyCrawlController()
        spider = Mock()
        spider.interrupt_requested = False
        bindings = Mock()
        controller.current_spider = spider
        controller._active_spider_bindings = bindings
        controller.host.show_selection_dialog.return_value = None

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller._on_spider_select_tasks([{"title": "A"}])

        controller.spider_session.stop_session.assert_called_once_with(spider, bindings)
        controller.host.notify_crawl_stop_requested.assert_called_once()
        spider.resume_from_ui.assert_called_once_with(None)

    def test_selection_cancel_does_not_duplicate_existing_stop_request(self):
        controller = _DummyCrawlController()
        spider = Mock()
        spider.interrupt_requested = True
        controller.current_spider = spider
        controller.host.show_selection_dialog.return_value = None

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller._on_spider_select_tasks([{"title": "A"}])

        controller.spider_session.stop_session.assert_not_called()
        controller.host.notify_crawl_stop_requested.assert_not_called()
        spider.resume_from_ui.assert_called_once_with(None)

    def test_on_spider_item_found_prepares_item_and_enqueues_download(self):
        controller = _DummyCrawlController()
        controller.host.current_save_dir = "downloads"
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller._on_spider_item_found(item)

        self.assertEqual(item.status, "⏳ 等待中")
        self.assertEqual(item.progress, 0)
        self.assertIs(controller.videos[item.id], item)
        controller.host.add_video_row.assert_called_once_with(item)
        controller.dl_manager.add_task.assert_called_once_with(item, "downloads")

    def test_on_spider_items_found_batches_ui_and_download_queue(self):
        controller = _DummyCrawlController()
        controller.host.current_save_dir = "downloads"
        first = VideoItem(url="https://example.com/1.mp4", title="one", source="bilibili")
        second = VideoItem(url="https://example.com/2.mp4", title="two", source="bilibili")

        with patch("app.controllers.crawl_controller_mixin.debug_logger", Mock()):
            controller._on_spider_items_found([first, second])

        self.assertEqual(first.status, "⏳ 等待中")
        self.assertEqual(second.progress, 0)
        self.assertIs(controller.videos[first.id], first)
        self.assertIs(controller.videos[second.id], second)
        controller.host.add_video_rows.assert_called_once_with([first, second])
        controller.host.add_video_row.assert_not_called()
        controller.dl_manager.add_tasks.assert_called_once_with([first, second], "downloads")
        controller.dl_manager.add_task.assert_not_called()

    def test_dispatch_spider_event_routes_selection_and_finish(self):
        controller = _DummyCrawlController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        controller._on_spider_item_found = Mock()
        controller._on_spider_items_found = Mock()
        controller._schedule_spider_selection = Mock()
        controller._on_spider_finished = Mock()

        controller._dispatch_spider_event(build_item_found_event(item))
        controller._dispatch_spider_event(build_items_found_event([item]))
        controller._dispatch_spider_event(build_selection_required_event([item]))
        controller._dispatch_spider_event(build_crawl_state_event(CrawlStatus.FINISHED))
        controller._dispatch_spider_event(build_crawl_state_event(CrawlStatus.RUNNING, is_running=True))

        controller._on_spider_item_found.assert_called_once_with(item)
        controller._on_spider_items_found.assert_called_once_with([item])
        controller._schedule_spider_selection.assert_called_once_with([item])
        controller._on_spider_finished.assert_called_once()

    def test_selection_event_is_deferred_through_host_ui_queue(self):
        controller = _DummyCrawlController()
        controller._on_spider_select_tasks = Mock()
        callbacks = []
        controller.host._queue_on_ui.side_effect = callbacks.append

        controller._dispatch_spider_event(build_selection_required_event([{"title": "A"}]))

        controller._on_spider_select_tasks.assert_not_called()
        controller.host._queue_on_ui.assert_called_once()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        controller._on_spider_select_tasks.assert_called_once_with([{"title": "A"}])

if __name__ == "__main__":
    unittest.main()
