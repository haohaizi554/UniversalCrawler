import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


def _signal():
    return SimpleNamespace(connect=Mock())


class WebControllerRuntimeTests(unittest.TestCase):
    def test_init_does_not_create_download_manager_until_needed(self):
        from app.web.controller import WebController

        fake_manager = SimpleNamespace(
            task_started=_signal(),
            task_progress=_signal(),
            task_finished=_signal(),
            task_error=_signal(),
        )

        with patch("app.web.controller.DownloadManager", return_value=fake_manager) as mocked_manager, patch(
            "app.web.controller.SpiderSession", return_value=Mock()
        ):
            controller = WebController(None, lambda *_args, **_kwargs: None)

            self.assertIsNone(controller._dl_manager)
            mocked_manager.assert_not_called()

            manager = controller.dl_manager

        self.assertIs(manager, fake_manager)
        mocked_manager.assert_called_once()
        fake_manager.task_started.connect.assert_called_once_with(controller._on_task_started)
        fake_manager.task_progress.connect.assert_called_once_with(controller._on_task_progress)
        fake_manager.task_finished.connect.assert_called_once_with(controller._on_task_finished)
        fake_manager.task_error.connect.assert_called_once_with(controller._on_task_error)

    def test_shutdown_does_not_create_download_manager_for_idle_session(self):
        from app.web.controller import WebController

        with patch("app.web.controller.DownloadManager") as mocked_manager, patch(
            "app.web.controller.SpiderSession", return_value=Mock()
        ):
            controller = WebController(None, lambda *_args, **_kwargs: None)
            controller.shutdown()

        mocked_manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
