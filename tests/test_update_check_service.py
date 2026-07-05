import os
import sys
import unittest

from app.services.update_check_service import (
    UPDATE_STATUS_AVAILABLE,
    UPDATE_STATUS_CURRENT,
    UPDATE_STATUS_LOCAL_NEWER,
    UpdateCheckError,
    check_for_update,
    compare_versions,
    normalize_version,
)


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
        self.assertIn("检查", widget.lbl_version.toolTip())

        widget.set_update_checking(False)
        self.assertTrue(widget.lbl_version.isEnabled())
