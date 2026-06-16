import unittest

from PyQt6.QtWidgets import QApplication, QWidget

from app.ui.components.media_preview_panel import MediaPreviewPanel


class MediaPreviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_navigation_buttons_use_icons_instead_of_emoji_text(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)

        self.assertEqual(panel.btn_prev.text(), "")
        self.assertEqual(panel.btn_next.text(), "")
        self.assertFalse(panel.btn_prev.icon().isNull())
        self.assertFalse(panel.btn_next.icon().isNull())

    def test_duration_change_updates_slider_range_and_time_label(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)

        panel.player.duration = lambda: 65000
        panel.player.isSeekable = lambda: True

        panel._on_player_duration_changed(65000)

        self.assertEqual(panel.slider.maximum(), 65000)
        self.assertTrue(panel.slider.isEnabled())
        self.assertEqual(panel.lbl_time.text(), "00:00 / 01:05")

    def test_seekable_change_disables_slider_when_backend_cannot_seek(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)

        panel.player.duration = lambda: 65000

        panel._on_player_seekable_changed(False)
        self.assertFalse(panel.slider.isEnabled())

        panel._on_player_seekable_changed(True)
        self.assertTrue(panel.slider.isEnabled())

    def test_format_time_supports_hour_based_media(self):
        self.assertEqual(MediaPreviewPanel.format_time(3_661_000), "01:01:01")

    def test_mkv_repair_needed_when_duration_is_missing(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        panel.player.duration = lambda: 0
        panel.player.isSeekable = lambda: False

        self.assertTrue(panel._mkv_playback_needs_repair())

    def test_mkv_repair_not_needed_for_seekable_media_with_duration(self):
        host = QWidget()
        panel = MediaPreviewPanel(host)
        panel.player.duration = lambda: 65_000
        panel.player.isSeekable = lambda: True

        self.assertFalse(panel._mkv_playback_needs_repair())


if __name__ == "__main__":
    unittest.main()
