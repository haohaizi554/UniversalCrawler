import unittest
from unittest.mock import Mock, patch

from app.controllers.application_lifecycle_mixin import ApplicationLifecycleMixin

class _DummyLifecycleController(ApplicationLifecycleMixin):
    def __init__(self):
        self.host = Mock()
        self.current_spider = None
        self.dl_manager = Mock()
        self.app = Mock()

    def _host(self):
        return self.host

class ApplicationLifecycleMixinTests(unittest.TestCase):
    def test_stop_active_spider_ignores_missing_or_idle_spider(self):
        controller = _DummyLifecycleController()

        controller._stop_active_spider()

        controller.current_spider = Mock()
        controller.current_spider.isRunning.return_value = False
        controller._stop_active_spider()

        controller.current_spider.stop.assert_not_called()
        controller.current_spider.wait.assert_not_called()

    def test_stop_active_spider_stops_running_spider(self):
        controller = _DummyLifecycleController()
        controller.current_spider = Mock()
        controller.current_spider.isRunning.return_value = True

        controller._stop_active_spider()

        controller.current_spider.stop.assert_called_once()
        controller.current_spider.wait.assert_called_once_with(2000)

    def test_shutdown_cleans_media_spider_and_downloads(self):
        controller = _DummyLifecycleController()
        controller._stop_active_spider = Mock()

        fake_logger = Mock()
        with patch("app.controllers.application_lifecycle_mixin.debug_logger", fake_logger):
            controller.shutdown()

        fake_logger.log.assert_called_once()
        controller.host.cleanup_media.assert_called_once()
        controller._stop_active_spider.assert_called_once()
        controller.dl_manager.stop_all.assert_called_once()

    def test_shutdown_releases_frontend_state_and_cache_resources(self):
        controller = _DummyLifecycleController()
        controller._stop_active_spider = Mock()
        controller.frontend_state_service = Mock()
        controller.app_state = Mock()
        controller.cache_service = Mock()

        fake_logger = Mock()
        with patch("app.controllers.application_lifecycle_mixin.debug_logger", fake_logger):
            controller.shutdown()

        controller.frontend_state_service.destroy.assert_called_once()
        controller.app_state.shutdown.assert_called_once()
        controller.cache_service.close.assert_called_once()
        controller.host.cleanup_media.assert_called_once()

    def test_shutdown_unsubscribes_deferred_domain_event_handlers(self):
        controller = _DummyLifecycleController()
        controller._stop_active_spider = Mock()
        controller.event_bus = Mock()
        controller._spider_domain_event_handler = Mock()
        controller._download_domain_event_handler = Mock()

        fake_logger = Mock()
        with patch("app.controllers.application_lifecycle_mixin.debug_logger", fake_logger):
            controller.shutdown()

        controller.event_bus.unsubscribe.assert_any_call(
            "spider.domain_event",
            controller._spider_domain_event_handler,
        )
        controller.event_bus.unsubscribe.assert_any_call(
            "download.domain_event",
            controller._download_domain_event_handler,
        )

    def test_run_exits_with_app_exec_code(self):
        controller = _DummyLifecycleController()
        controller.app.exec.return_value = 7

        with patch("app.controllers.application_lifecycle_mixin.sys.exit") as exit_mock:
            controller.run()

        controller.app.exec.assert_called_once()
        exit_mock.assert_called_once_with(7)

if __name__ == "__main__":
    unittest.main()
