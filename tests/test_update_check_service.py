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

    def test_update_check_dialog_uses_current_language(self):
        from PyQt6.QtWidgets import QLabel, QPushButton

        from app.ui.dialogs.update_check import UpdateCheckDialog

        dialog = UpdateCheckDialog(
            None,
            title="检查更新失败",
            message="暂时无法检查最新版本。",
            details="本地版本与 GitHub 最新 Release 一致，无需更新。",
            primary_text="确定",
            status="error",
            local_version="v3.6.17",
            latest_version="v3.6.17",
            language="en-US",
        )
        self.addCleanup(dialog.deleteLater)

        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        buttons = "\n".join(button.text() for button in dialog.findChildren(QPushButton))

        self.assertEqual(dialog.windowTitle(), "Update check failed")
        self.assertIn("Update check failed", labels)
        self.assertIn("Could not check the latest version right now.", labels)
        self.assertIn("Current version", labels)
        self.assertIn("Release version", labels)
        self.assertIn("Check failed", labels)
        self.assertIn("Error details", labels)
        self.assertIn("The local version matches the latest GitHub Release. No update is needed.", labels)
        self.assertIn("OK", buttons)
        for unexpected in ("检查更新失败", "暂时无法", "当前版本", "错误详情", "确定"):
            self.assertNotIn(unexpected, labels + buttons)

    def test_update_check_dialog_translates_local_newer_detail_with_prefix(self):
        from PyQt6.QtWidgets import QLabel

        from app.ui.dialogs.update_check import UpdateCheckDialog

        dialog = UpdateCheckDialog(
            None,
            title="\u68c0\u67e5\u66f4\u65b0",
            message="\u5f53\u524d\u7248\u672c v3.6.17 \u9ad8\u4e8e\u6700\u65b0 Release v3.6.14\u3002",
            details="\u8fd9\u901a\u5e38\u8868\u793a\u4f60\u6b63\u5728\u4f7f\u7528\u672c\u5730\u6784\u5efa\u6216\u9884\u53d1\u5e03\u6784\u5efa\uff0c\u65e0\u9700\u66f4\u65b0\u3002",
            status=UPDATE_STATUS_LOCAL_NEWER,
            local_version="v3.6.17",
            latest_version="v3.6.14",
            language="en-US",
        )
        self.addCleanup(dialog.deleteLater)

        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn(
            "This usually means you are using a local or pre-release build, so no update is needed.",
            labels,
        )
        self.assertNotIn("\u8fd9\u901a\u5e38\u8868\u793a", labels)
