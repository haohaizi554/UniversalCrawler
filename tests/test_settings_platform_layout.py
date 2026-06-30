import unittest

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication

from app.ui.viewmodels.settings_platform_layout import (
    PLATFORM_DETAIL_COL_WIDTHS,
    platform_column_widths,
)


class SettingsPlatformLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _widths(self, rows, *, content_width=620):
        return platform_column_widths(
            rows,
            content_width=content_width,
            translate=str,
            metrics=QFontMetrics(self.app.font()),
            count_options=["10", "20 videos recommended", "30", "50", "max"],
            timeout_options=["30 s", "60 s recommended", "90 s", "120 s"],
            label_padding=38,
        )

    def test_platform_column_widths_fit_limited_content_width(self):
        widths = self._widths([], content_width=620)

        self.assertEqual(set(widths), set(PLATFORM_DETAIL_COL_WIDTHS))
        self.assertLessEqual(sum(widths.values()), 620)
        self.assertGreaterEqual(widths["timeout"], 132)

    def test_platform_column_widths_expand_for_long_platform_options(self):
        rows = [
            {
                "count_options": ["10", "20 videos recommended", "unlimited platform results"],
                "default_count": "unlimited platform results",
                "timeout_options": ["30 s", "60 s recommended"],
                "default_timeout": "60 s recommended",
            }
        ]

        widths = self._widths(rows, content_width=1200)

        self.assertGreaterEqual(widths["count"], PLATFORM_DETAIL_COL_WIDTHS["count"])
        self.assertGreaterEqual(widths["timeout"], PLATFORM_DETAIL_COL_WIDTHS["timeout"])
        self.assertLessEqual(sum(widths.values()), 1200)


if __name__ == "__main__":
    unittest.main()
