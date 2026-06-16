from __future__ import annotations

import unittest

from PyQt6.QtWidgets import QApplication

from app.ui.components.log_panel import LogPanel


class LogPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_log_panel_sets_maximum_block_count(self):
        panel = LogPanel()

        self.assertEqual(panel.document().maximumBlockCount(), panel.MAX_LOG_BLOCK_COUNT)

    def test_append_log_trims_old_lines_when_over_limit(self):
        panel = LogPanel()
        panel.setMaximumBlockCount(3)

        for index in range(5):
            panel.append_log(f"line-{index}")

        self.assertEqual(panel.blockCount(), 3)
        self.assertEqual(panel.toPlainText().splitlines(), ["line-2", "line-3", "line-4"])


if __name__ == "__main__":
    unittest.main()
