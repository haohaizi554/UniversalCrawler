"""测试模块，覆盖 `tests/test_main_entry.py` 对应功能的行为与回归场景。"""

import io
import unittest
from unittest.mock import Mock, patch

import main


class MainEntryTests(unittest.TestCase):
    """验证应用入口初始化、异常记录与平台兼容分支。"""

    @patch("main.ApplicationController")
    @patch("main._set_windows_app_user_model_id")
    @patch("main.multiprocessing.freeze_support")
    def test_main_initializes_controller_and_runs_application(
        self,
        mocked_freeze_support,
        mocked_set_app_id,
        mocked_controller_cls,
    ):
        """验证 `test_main_initializes_controller_and_runs_application` 对应场景是否符合预期，供 `MainEntryTests` 使用。"""
        controller = mocked_controller_cls.return_value

        main.main()

        mocked_freeze_support.assert_called_once()
        mocked_set_app_id.assert_called_once()
        mocked_controller_cls.assert_called_once()
        controller.run.assert_called_once()

    @patch("main.ApplicationController")
    @patch("main._set_windows_app_user_model_id")
    @patch("main.multiprocessing.freeze_support")
    def test_main_logs_error_message_and_reraises_startup_failure(
        self,
        _mocked_freeze_support,
        _mocked_set_app_id,
        mocked_controller_cls,
    ):
        """验证 `test_main_logs_error_message_and_reraises_startup_failure` 对应场景是否符合预期，供 `MainEntryTests` 使用。"""
        mocked_controller_cls.side_effect = RuntimeError("boom")
        stderr = io.StringIO()

        with patch.object(main, "debug_logger") as mocked_logger, patch("sys.stderr", stderr):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                main.main()

        mocked_logger.log_exception.assert_called_once()
        self.assertIn("应用启动失败", stderr.getvalue())

    @patch("main.os.name", "posix")
    def test_set_windows_app_user_model_id_is_noop_on_non_windows(self):
        """验证 `test_set_windows_app_user_model_id_is_noop_on_non_windows` 对应场景是否符合预期，供 `MainEntryTests` 使用。"""
        self.assertIsNone(main._set_windows_app_user_model_id())

    @patch("main.os.name", "nt")
    def test_set_windows_app_user_model_id_swallows_ctypes_errors(self):
        """验证 `test_set_windows_app_user_model_id_swallows_ctypes_errors` 对应场景是否符合预期，供 `MainEntryTests` 使用。"""
        fake_ctypes = Mock()
        fake_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.side_effect = OSError("missing shell32")

        with patch.dict("sys.modules", {"ctypes": fake_ctypes}):
            self.assertIsNone(main._set_windows_app_user_model_id())


if __name__ == "__main__":
    unittest.main()
