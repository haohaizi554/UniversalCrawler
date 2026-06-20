"""测试测试套件启动器的最小 UI 构造行为。"""

from __future__ import annotations

import os
import sys
import unittest

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
        from tests import test_launcher as launcher

        window = launcher._build_gui()
        try:
            self.assertEqual(window.windowTitle(), "UCrawl 测试套件")
            self.assertEqual(window.btn_run.text(), "运行测试")
            self.assertEqual(window.run_status.text(), "待命中")
            self.assertEqual(window.progress_percent.text(), "0%")
        finally:
            window.close()

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
