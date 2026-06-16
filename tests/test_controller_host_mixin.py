import unittest
from unittest.mock import Mock, patch

from app.controllers.controller_host_mixin import ControllerHostMixin
from app.exceptions import DebugActionError
from app.models import VideoItem


class _DummyHostController(ControllerHostMixin):
    def __init__(self):
        self.window = Mock()


class ControllerHostMixinTests(unittest.TestCase):
    def test_host_is_cached_after_first_adapter_creation(self):
        controller = _DummyHostController()
        adapter = Mock()

        with patch("app.controllers.controller_host_mixin.DesktopHostAdapter", return_value=adapter) as adapter_cls:
            first = controller._host()
            second = controller._host()

        self.assertIs(first, adapter)
        self.assertIs(second, adapter)
        adapter_cls.assert_called_once_with(controller.window)

    def test_item_details_uses_debug_logger_pick_used(self):
        controller = _DummyHostController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.local_path = "D:/downloads/demo.mp4"
        item.meta.update({"content_type": "video", "folder_name": "alice"})

        fake_logger = Mock()
        fake_logger.pick_used.return_value = {"title": "demo", "content_type": "video"}
        with patch("app.controllers.controller_host_mixin.debug_logger", fake_logger):
            details = controller._item_details(item)

        self.assertEqual(details, {"title": "demo", "content_type": "video"})
        fake_logger.pick_used.assert_called_once()

    def test_build_download_error_details_merges_error(self):
        controller = _DummyHostController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with patch.object(controller, "_item_details", return_value={"title": "demo"}):
            details = controller._build_download_error_log_details(item, "网络超时")

        self.assertEqual(details, {"title": "demo", "error": "网络超时"})

    def test_run_debug_action_logs_success(self):
        controller = _DummyHostController()
        controller.host = Mock()
        callback = Mock()

        controller._run_debug_action("done", "debug action", callback)

        callback.assert_called_once()
        controller.host.append_log.assert_called_once_with("done")

    def test_run_debug_action_routes_debug_errors(self):
        controller = _DummyHostController()
        callback = Mock(side_effect=DebugActionError("boom"))

        with patch.object(controller, "_report_debug_action_error") as report_error:
            controller._run_debug_action("done", "复制 trace_id", callback)

        report_error.assert_called_once()
        action, exc = report_error.call_args.args
        self.assertEqual(action, "复制 trace_id")
        self.assertIsInstance(exc, DebugActionError)


if __name__ == "__main__":
    unittest.main()
