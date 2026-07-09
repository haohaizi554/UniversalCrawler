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
        from PyQt6.QtWidgets import QFrame, QLabel, QWidget
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
            self.assertEqual(window.footer_status_dot.objectName(), "StatusDot")
            self.assertEqual(window.footer_status_state.text(), "就绪")
            self.assertEqual(window.footer_status_metrics["scripts"].text(), "脚本 0/0")
            self.assertIsNotNone(window.findChild(QFrame, "logCard"))
            self.assertEqual(window.findChildren(type(window.stat_scope), "statHint"), [])
            self.assertIsNone(window.findChild(QFrame, "selectionSummary"))
            self.assertEqual(window.findChildren(QFrame, "statsCard"), [])
            self.assertIsNotNone(window.findChild(QWidget, "scopeMetrics"))
            self.assertGreaterEqual(len(window.findChildren(QFrame, "scopeMetricDivider")), 3)
            label_texts = {label.text() for label in window.findChildren(QLabel)}
            self.assertIn("按职责组合执行范围。", label_texts)
            self.assertIn("已选分类", label_texts)
            self.assertNotIn("总分类数", label_texts)
            self.assertEqual(window.stat_selected.text(), "0")
            self.assertFalse(hasattr(window, "stat_total"))
            self.assertFalse(window.detail_desc.wordWrap())
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

    def test_section_header_keeps_count_badge_inline(self):
        from PyQt6.QtWidgets import QLabel, QFrame
        from tests import test_launcher as launcher

        header = launcher._SectionHeader("流程层", 2)
        try:
            header.resize(360, 72)
            header.show()
            for _ in range(3):
                self.app.processEvents()

            marker = header.findChild(QFrame, "sectionMarker")
            label = next(item for item in header.findChildren(QLabel) if item.objectName() == "sectionLabel")
            pill = next(item for item in header.findChildren(QLabel) if item.objectName() == "sectionCountPill")
            meta = next(item for item in header.findChildren(QLabel) if item.objectName() == "sectionMeta")

            self.assertIsNotNone(marker)
            self.assertEqual(marker.width(), 4)
            self.assertTrue(meta.wordWrap())
            self.assertLess(pill.geometry().left(), header.width() // 2)
            self.assertGreater(pill.geometry().left(), label.geometry().right())
            self.assertLess(abs(pill.geometry().center().y() - label.geometry().center().y()), 6)
        finally:
            header.close()

    def test_category_scroll_does_not_add_blank_tail_after_last_card(self):
        from PyQt6.QtWidgets import QWidget
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window.resize(1220, 952)
            window.show()
            for _ in range(5):
                self.app.processEvents()
                window._refresh_text_minimums()

            category_viewport = window.findChild(QWidget, "categoryViewport")
            category_list = window.findChild(QWidget, "categoryList")
            cards = window.findChildren(QWidget, "categoryCard")
            self.assertIsNotNone(category_viewport)
            self.assertIsNotNone(category_list)
            self.assertGreater(len(cards), 0)

            last_card = max(cards, key=lambda card: card.geometry().bottom())
            list_tail_gap = category_list.height() - last_card.geometry().bottom() - 1
            viewport_tail_gap = category_viewport.height() - category_list.geometry().bottom() - 1

            self.assertLessEqual(list_tail_gap, 4)
            self.assertLessEqual(viewport_tail_gap, 4)
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
            self.assertTrue(window.btn_run.isVisible())
            self.assertFalse(window.hero_sub.wordWrap())
            panel_log_gap = window.log_card.geometry().top() - window.control_panel.geometry().bottom() - 1
            self.assertGreaterEqual(panel_log_gap, 0)
            self.assertLessEqual(panel_log_gap, 12)
            self.assertGreaterEqual(
                window.log_card.geometry().top(),
                window.control_panel.geometry().bottom() + 1,
            )
            btn_bottom = window.control_panel.geometry().top() + window.btn_run.geometry().bottom()
            self.assertLess(btn_bottom, window.log_card.geometry().top())

            compressed = []
            for label in window.findChildren(QLabel):
                if not label.isVisible() or not label.text().strip() or not label.minimumHeight():
                    continue
                if label.geometry().height() + 2 < label.minimumHeight():
                    compressed.append((label.objectName(), label.text()[:24]))
            self.assertEqual(compressed, [])
        finally:
            window.close()

    def test_launcher_progress_detail_keeps_completed_text_on_one_line(self):
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window._done_files = 28
            window._total_files = 126
            window._update_progress_labels()
            window.resize(980, 640)
            window.show()
            for _ in range(4):
                self.app.processEvents()

            self.assertFalse(window.progress_detail.wordWrap())
            self.assertEqual(window.progress_detail.text(), "已完成 28/126 个脚本")
            self.assertGreaterEqual(
                window.progress_detail.minimumWidth(),
                window.progress_detail.fontMetrics().horizontalAdvance(window.progress_detail.text()) + 12,
            )
            self.assertGreaterEqual(
                window.progress_detail.width(),
                window.progress_detail.fontMetrics().horizontalAdvance(window.progress_detail.text()) + 12,
            )
            self.assertLess(window.progress_detail.height(), window.progress_detail.sizeHint().height() * 2)
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
            self.assertEqual(window.stat_selected.text(), "1")
            self.assertEqual(window.detail_title.text(), "执行范围")
            self.assertIn("执行范围：全量", window.footer_status_detail.text())
            self.assertIn("全部测试", window.detail_desc.text())
        finally:
            window.close()

    def test_launcher_status_bar_uses_gui_status_light_and_result_metrics(self):
        from tests import test_launcher as launcher
        from tests.test_runner import TestResult

        window = launcher._build_gui()
        try:
            window._total_files = 126
            window.progress.setRange(0, 126)
            window.btn_stop.show()
            results = [
                TestResult(
                    category_id="all",
                    category_name="全部测试",
                    file_count=126,
                    passed=251,
                    failed=0,
                    skipped=3,
                    errors=0,
                    duration=16.03,
                )
            ]

            window._on_event("all_done", "all", "全部测试", results)

            self.assertEqual(window.footer_status_dot._state, "running")
            self.assertEqual(window.footer_status_state.text(), "全部通过")
            self.assertEqual(window.footer_status_detail.text(), "测试套件运行完成")
            self.assertEqual(window.footer_status_metrics["scripts"].text(), "脚本 126/126")
            self.assertEqual(window.footer_status_metrics["passed"].text(), "通过 251")
            self.assertEqual(window.footer_status_metrics["skipped"].text(), "跳过 3")
            self.assertEqual(window.footer_status_metrics["failed"].text(), "失败 0")
            self.assertEqual(window.footer_status_metrics["errors"].text(), "错误 0")
            self.assertEqual(window.footer_status_metrics["duration"].text(), "耗时 16.03s")
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

    def test_multi_selection_updates_scope_panel(self):
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            window.selected_ids = ["cli_sdk", "web_api"]
            window._refresh_selection_state()

            self.assertEqual(window.stat_scope.text(), "组合")
            self.assertEqual(window.stat_selected.text(), "2")
            self.assertEqual(window.detail_title.text(), "执行范围")
            self.assertIn("多分类组合", window.detail_desc.text())
            self.assertIn("共", window.detail_tags.text())
            self.assertIn("个去重脚本", window.detail_tags.text())
            self.assertFalse(hasattr(window, "left_selected_value"))
        finally:
            window.close()

if __name__ == "__main__":
    unittest.main()
