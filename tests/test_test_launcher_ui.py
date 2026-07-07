"""测试测试套件启动器的最小 UI 构造行为。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

def _pyqt6_available() -> bool:
    try:
        import PyQt6  # noqa: F401
        return True
    except ImportError:
        return False

@unittest.skipUnless(_pyqt6_available(), "PyQt6 不可用")
class TestLauncherWindowUITests(unittest.TestCase):
    """验证测试套件启动器窗口能正常构造并更新基础状态。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_build_gui_exposes_core_controls(self):
        from PyQt6.QtCore import Qt
        from app.ui.layout.window_chrome import WindowChromeFrame
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            self.assertIsInstance(window.window_chrome, WindowChromeFrame)
            self.assertIs(window.window_title_bar, window.window_chrome.title_bar)
            self.assertIsInstance(window._window_chrome_controller, FramelessWindowChromeController)
            self.assertTrue(bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint))
            self.assertEqual(window.windowTitle(), "UCrawl 测试套件")
            self.assertEqual(window.btn_run.text(), "运行测试")
            self.assertEqual(window.btn_theme.objectName(), "ThemeBtn")
            self.assertEqual(window.btn_theme.text(), "")
            self.assertFalse(window.btn_theme.icon().isNull())
            self.assertEqual(window.run_status.text(), "待命中")
            self.assertEqual(window.progress_percent.text(), "0%")
        finally:
            window.close()

    def test_launcher_minimum_size_tracks_configured_scale(self):
        from tests import test_launcher as launcher

        original_get = launcher.cfg.get

        def fake_get(section, key, default=None):
            if section == "appearance" and key == "scale":
                return "125%"
            return original_get(section, key, default)

        with patch.object(launcher.cfg, "get", side_effect=fake_get):
            window = launcher._build_gui()
            try:
                self.assertEqual(launcher._launcher_minimum_size(), (1225, 800))
                self.assertGreaterEqual(window.minimumWidth(), 1225)
                self.assertGreaterEqual(window.minimumHeight(), 800)
                self.assertGreaterEqual(window.minimumHeight(), window.centralWidget().sizeHint().height())
            finally:
                window.close()

    def test_launcher_text_refresh_does_not_inflate_or_compress_panels(self):
        from PyQt6.QtWidgets import QLabel
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window.resize(1220, 760)
            window.show()
            for _ in range(4):
                self.app.processEvents()
                window._refresh_text_minimums()

            initial_floor = window.minimumHeight()
            initial_hero_height = window.hero_panel.height()
            initial_detail_min = window.detail_panel.minimumHeight()
            initial_control_min = window.control_panel.minimumHeight()

            for _ in range(8):
                window._refresh_text_minimums()
                self.app.processEvents()

            self.assertLessEqual(window.minimumHeight(), initial_floor + 2)
            self.assertLessEqual(window.hero_panel.height(), initial_hero_height + 2)
            self.assertEqual(window.detail_panel.minimumHeight(), initial_detail_min)
            self.assertEqual(window.control_panel.minimumHeight(), initial_control_min)
            self.assertGreaterEqual(window.detail_panel.height() + 2, window.detail_panel.minimumHeight())
            self.assertGreaterEqual(window.control_panel.height() + 2, window.control_panel.minimumHeight())

            compressed = []
            for label in window.findChildren(QLabel):
                if not label.isVisible() or not label.text().strip() or not label.minimumHeight():
                    continue
                if label.geometry().height() + 2 < label.minimumHeight():
                    compressed.append((label.objectName(), label.text()[:24]))
            self.assertEqual(compressed, [])
        finally:
            window.close()

    def test_launcher_light_large_text_keeps_label_height_and_contrast(self):
        from PyQt6.QtWidgets import QLabel
        from tests import test_launcher as launcher

        original_get = launcher.cfg.get

        def fake_get(section, key, default=None):
            if section == "appearance" and key == "scale":
                return "125%"
            if section == "appearance" and key == "font_size":
                return "large"
            if section == "common" and key == "theme":
                return "light"
            return original_get(section, key, default)

        with patch.object(launcher.cfg, "get", side_effect=fake_get):
            window = launcher._build_gui()
            try:
                window.resize(1500, 900)
                window._set_theme(False, persist=False)
                window.show()
                for _ in range(4):
                    self.app.processEvents()

                compressed = []
                for label in window.findChildren(QLabel):
                    if not label.isVisible() or not label.text().strip() or not label.minimumHeight():
                        continue
                    if label.geometry().height() + 2 < label.minimumHeight():
                        compressed.append((label.objectName(), label.text()[:24]))
                self.assertEqual(compressed, [])

                light_qss = launcher._launcher_qss(False)
                section_label_index = light_qss.rfind("QLabel#sectionLabel")
                self.assertGreaterEqual(section_label_index, 0)
                section_label_block = light_qss[section_label_index : light_qss.find("}", section_label_index) + 1]
                self.assertIn("#020617", section_label_block)
                self.assertIn("#334155", light_qss)
            finally:
                window.close()

    def test_frameless_controller_converts_minimum_size_to_native_pixels(self):
        from PyQt6.QtWidgets import QWidget
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController

        host = QWidget()
        self.addCleanup(host.deleteLater)
        controller = FramelessWindowChromeController(host, title_bar_getter=lambda: None)
        controller._qt_dpr = lambda: 1.25  # type: ignore[method-assign]

        self.assertEqual(controller._logical_px_to_native_track_px(980), 1225)
        self.assertEqual(controller._logical_px_to_native_track_px(640), 800)

    def test_select_only_updates_detail_panel(self):
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window._select_only("all")
            self.assertEqual(window.stat_scope.text(), "全量")
            self.assertEqual(window.detail_title.text(), "执行范围")
            self.assertIn("执行范围：全量", window.sbar.currentMessage())
            self.assertEqual(window.left_selected_pill.text(), "全量")
            self.assertIn("全部测试", window.detail_desc.text())
        finally:
            window.close()

    def test_category_card_visual_state_priority_is_explicit(self):
        from tests import test_launcher as launcher

        category = launcher.get_category("all")
        card = launcher._CategoryCard(category, lambda _category: None)
        try:
            self.assertEqual(card.property("state"), "default")

            card._set_hovered(True)
            self.assertEqual(card.property("state"), "hover")
            self.assertEqual(card.strip.property("state"), "hover")
            self.assertEqual(card.count_pill.property("state"), "hover")

            card.set_selected(True)
            self.assertEqual(card.property("state"), "selected-hover")

            card._set_hovered(False)
            self.assertEqual(card.property("state"), "selected")

            card.set_selected(False)
            self.assertEqual(card.property("state"), "default")
        finally:
            card.close()

    def test_multi_selection_updates_left_summary(self):
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window.selected_ids = ["cli_sdk", "web_api"]
            window._refresh_selection_state()

            self.assertEqual(window.left_selected_value.text(), "2")
            self.assertEqual(window.left_selected_pill.text(), "组合")
            self.assertEqual(window.stat_scope.text(), "组合")
            self.assertEqual(window.detail_title.text(), "执行范围")
            self.assertIn("已组合 2 个分类", window.left_selected_text.text())
        finally:
            window.close()

if __name__ == "__main__":
    unittest.main()
