"""测试模块，覆盖 `tests/test_debug_service.py` 对应功能的行为与回归场景。"""

import tempfile
import unittest
from unittest.mock import Mock, patch

from app.exceptions import DebugActionError
from app.services.debug_service import DebugArtifactsService


class DebugArtifactsServiceTests(unittest.TestCase):
    """封装 `DebugArtifactsServiceTests` 在 `tests/test_debug_service.py` 中承担的核心逻辑。"""
    def setUp(self):
        """执行 `setUp` 对应的业务逻辑，供 `DebugArtifactsServiceTests` 使用。"""
        self.service = DebugArtifactsService()

    def test_open_path_raises_when_file_is_missing(self):
        """验证 `test_open_path_raises_when_file_is_missing` 对应场景是否符合预期，供 `DebugArtifactsServiceTests` 使用。"""
        with self.assertRaises(DebugActionError):
            self.service.open_path("missing.log")

    @patch("app.services.debug_service.os.name", "nt")
    @patch("app.services.debug_service.os.startfile")
    def test_open_path_uses_startfile_on_windows(self, mocked_startfile):
        """验证 `test_open_path_uses_startfile_on_windows` 对应场景是否符合预期，供 `DebugArtifactsServiceTests` 使用。"""
        with tempfile.NamedTemporaryFile(suffix=".log") as fp:
            self.service.open_path(fp.name)

        mocked_startfile.assert_called_once()

    @patch("app.services.debug_service.os.name", "posix")
    @patch("app.services.debug_service.subprocess.Popen")
    def test_open_path_uses_xdg_open_on_non_windows(self, mocked_popen):
        """验证 `test_open_path_uses_xdg_open_on_non_windows` 对应场景是否符合预期，供 `DebugArtifactsServiceTests` 使用。"""
        with tempfile.NamedTemporaryFile(suffix=".log") as fp:
            self.service.open_path(fp.name)

        mocked_popen.assert_called_once()

    def test_copy_trace_id_raises_for_missing_value(self):
        """验证 `test_copy_trace_id_raises_for_missing_value` 对应场景是否符合预期，供 `DebugArtifactsServiceTests` 使用。"""
        with self.assertRaises(DebugActionError):
            self.service.copy_trace_id(Mock(), None)

    def test_copy_trace_id_writes_to_clipboard(self):
        """验证 `test_copy_trace_id_writes_to_clipboard` 对应场景是否符合预期，供 `DebugArtifactsServiceTests` 使用。"""
        clipboard = Mock()

        self.service.copy_trace_id(clipboard, "trace-123")

        clipboard.setText.assert_called_once_with("trace-123")


if __name__ == "__main__":
    unittest.main()
