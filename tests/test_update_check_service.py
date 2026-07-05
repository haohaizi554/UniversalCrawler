import os
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.services.update_check_service import (
    UPDATE_STATUS_AVAILABLE,
    UPDATE_STATUS_CURRENT,
    UPDATE_STATUS_LOCAL_NEWER,
    UpdateCheckError,
    check_for_update,
    compare_versions,
    fetch_latest_release_page_payload,
    fetch_latest_release_payload,
    normalize_version,
)


class _FakeResponse:
    def __init__(self, *, url: str, body: str = "") -> None:
        self._url = url
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, *_args):
        return self._body


def _pyqt6_available() -> bool:
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        return False
    return True


def _qt_app():
    if not _pyqt6_available():
        return None
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class UpdateCheckServiceTests(unittest.TestCase):
    def test_normalize_version_accepts_display_and_tag_values(self):
        self.assertEqual(normalize_version("v3.6.17"), "3.6.17")
        self.assertEqual(normalize_version("UniversalCrawlerPro 3.7.0"), "3.7.0")

    def test_compare_versions_uses_numeric_segments(self):
        self.assertLess(compare_versions("v3.6.17", "v3.6.18"), 0)
        self.assertEqual(compare_versions("3.6.17", "v3.6.17"), 0)
        self.assertGreater(compare_versions("3.7.0", "3.6.99"), 0)

    def test_check_for_update_reports_current_release(self):
        result = check_for_update(
            "v3.6.17",
            fetcher=lambda: {"tag_name": "v3.6.17", "html_url": "https://example.test/release"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_CURRENT)
        self.assertEqual(result.local_version, "3.6.17")
        self.assertEqual(result.latest_version, "3.6.17")

    def test_check_for_update_reports_available_release(self):
        result = check_for_update(
            "v3.6.17",
            fetcher=lambda: {"tag_name": "v3.6.18", "html_url": "https://example.test/release"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)

    def test_check_for_update_reports_local_newer_release(self):
        result = check_for_update(
            "v3.7.0",
            fetcher=lambda: {"tag_name": "v3.6.18"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_LOCAL_NEWER)

    def test_check_for_update_rejects_missing_release_version(self):
        with self.assertRaises(UpdateCheckError):
            check_for_update("v3.6.17", fetcher=lambda: {"html_url": "https://example.test/release"})

    def test_fetch_latest_release_page_payload_reads_redirect_tag(self):
        response = _FakeResponse(url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18")
        with patch("app.services.update_check_service.urllib.request.urlopen", return_value=response):
            payload = fetch_latest_release_page_payload()

        self.assertEqual(payload["tag_name"], "v3.6.18")
        self.assertEqual(payload["html_url"], "https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18")

    def test_fetch_latest_release_payload_falls_back_when_api_is_forbidden(self):
        forbidden = HTTPError(
            url="https://api.github.com/repos/haohaizi554/UniversalCrawler/releases/latest",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        response = _FakeResponse(url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.19")
        with patch("app.services.update_check_service.urllib.request.urlopen", side_effect=[forbidden, response]):
            payload = fetch_latest_release_payload()

        self.assertEqual(payload["tag_name"], "v3.6.19")


@unittest.skipUnless(_pyqt6_available(), "PyQt6 is not installed")
class StatusBarUpdateCheckInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def test_version_button_emits_current_version_text(self):
        from app.ui.layout.status_bar import StatusBarWidget

        widget = StatusBarWidget()
        self.addCleanup(widget.deleteLater)
        observed: list[str] = []
        widget.update_check_requested.connect(observed.append)

        widget.render({"version": "v9.9.9"})
        widget.lbl_version.click()

        self.assertEqual(observed, ["v9.9.9"])

    def test_version_button_is_disabled_while_checking(self):
        from app.ui.layout.status_bar import StatusBarWidget

        widget = StatusBarWidget()
        self.addCleanup(widget.deleteLater)

        widget.set_update_checking(True)
        self.assertFalse(widget.lbl_version.isEnabled())
        self.assertTrue(widget.lbl_version.toolTip())

        widget.set_update_checking(False)
        self.assertTrue(widget.lbl_version.isEnabled())

    def test_update_check_dialog_uses_scoped_theme_styles(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel, QPushButton, QFrame

        from app.ui.dialogs.chromed_dialog import ChromedDialog
        from app.ui.dialogs.update_check import UpdateCheckDialog, UpdateStatusIcon
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
        from app.ui.styles import theme_colors

        dialog = UpdateCheckDialog(
            None,
            title="检查更新",
            message="当前版本已经是最新版本。",
            details="当前版本：v3.6.17",
            status=UPDATE_STATUS_CURRENT,
            local_version="v3.6.17",
            latest_version="v3.6.17",
            release_url="https://example.test/release",
        )
        self.addCleanup(dialog.deleteLater)

        colors = theme_colors(dialog._is_dark)
        self.assertIsInstance(dialog, ChromedDialog)
        self.assertIs(dialog.window_title_bar, dialog.chrome_frame.title_bar)
        self.assertIsInstance(dialog._window_chrome_controller, FramelessWindowChromeController)
        self.assertTrue(bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint))
        self.assertIn(colors["bg"], dialog.styleSheet())
        self.assertIn(colors["text"], dialog.styleSheet())
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogTitle"))
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogBody"))
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogStatus"))
        self.assertIsNotNone(dialog.findChild(UpdateStatusIcon, "UpdateStatusIcon"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateStatusBadge"))
        self.assertIsNotNone(dialog.findChild(QFrame, "UpdateVersionPanel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateReleaseLink"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "DialogPrimaryButton"))
