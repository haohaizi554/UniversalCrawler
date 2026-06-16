import unittest
from unittest.mock import Mock

from app.controllers.debug_controller_mixin import DebugControllerMixin
from app.models import VideoItem
from shared.controller_session import ControllerSessionMixin


class _DummyDebugController(DebugControllerMixin, ControllerSessionMixin):
    def __init__(self):
        self.debug_service = Mock()
        self.app = Mock()
        self.videos = {}
        self._run_debug_action = Mock()


class DebugControllerMixinTests(unittest.TestCase):
    def test_open_latest_log_delegates_to_run_debug_action(self):
        controller = _DummyDebugController()

        controller.open_latest_log()

        message, action_name, callback = controller._run_debug_action.call_args.args
        self.assertEqual(message, "📄 已打开最新调试日志")
        self.assertEqual(action_name, "打开最新日志")
        callback()
        controller.debug_service.open_latest_log.assert_called_once()

    def test_open_latest_error_summary_delegates_to_run_debug_action(self):
        controller = _DummyDebugController()

        controller.open_latest_error_summary()

        message, action_name, callback = controller._run_debug_action.call_args.args
        self.assertEqual(message, "🚨 已打开最近错误摘要")
        self.assertEqual(action_name, "打开错误摘要")
        callback()
        controller.debug_service.open_latest_error_summary.assert_called_once()

    def test_copy_trace_id_for_video_uses_clipboard_and_trace_id(self):
        controller = _DummyDebugController()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["trace_id"] = "trace-123"
        controller.videos[item.id] = item
        clipboard = Mock()
        controller.app.clipboard.return_value = clipboard

        controller.copy_trace_id_for_video(item.id)

        message, action_name, callback = controller._run_debug_action.call_args.args
        self.assertEqual(message, "📋 已复制 trace_id: trace-123")
        self.assertEqual(action_name, "复制 trace_id")
        callback()
        controller.debug_service.copy_trace_id.assert_called_once_with(clipboard, "trace-123")

    def test_copy_trace_id_for_unknown_video_passes_none(self):
        controller = _DummyDebugController()
        clipboard = Mock()
        controller.app.clipboard.return_value = clipboard

        controller.copy_trace_id_for_video("missing")

        message, action_name, callback = controller._run_debug_action.call_args.args
        self.assertEqual(message, "📋 已复制 trace_id: None")
        self.assertEqual(action_name, "复制 trace_id")
        callback()
        controller.debug_service.copy_trace_id.assert_called_once_with(clipboard, None)


if __name__ == "__main__":
    unittest.main()
