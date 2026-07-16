import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from app.ui.components.settings_controls import UiSwitch
from app.ui.components.settings_form import SettingsFormBuilder


class SettingsFormBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _builder(self) -> SettingsFormBuilder:
        def scaled_px(value, *, minimum=0):
            return max(int(value), int(minimum or 0))

        return SettingsFormBuilder(
            translate=lambda text: f"T:{text}",
            scaled_px=scaled_px,
            content_card_width=lambda: 640,
            effective_control_width=lambda width: min(int(width), 380),
            safe_icon_pixmap=lambda _icon, _size: None,
            fallback_group_icon_text=lambda group: group[:1] or "?",
            fallback_detail_icon_style=lambda: "",
            group_icons={"基础设置": "missing.png"},
            group_descriptions={"基础设置": "基础描述"},
            default_group_descriptions={},
            group_hints={"基础设置": "基础提示"},
            setting_short_descriptions={"并发数": "同时下载数量"},
            setting_descriptions={"并发数": "同时下载任务数量"},
            switch_wrap_width=96,
        )

    def test_builds_named_form_card_and_hint(self):
        builder = self._builder()
        form, layout = builder.build_form_card()
        hint = builder.build_group_hint_card("基础设置")
        self.addCleanup(form.deleteLater)
        self.addCleanup(hint.deleteLater)

        self.assertEqual(form.objectName(), "SettingsFormCard")
        self.assertEqual(form.width(), 640)
        self.assertEqual(layout.contentsMargins().left(), 10)
        self.assertEqual(hint.objectName(), "SettingsHintCard")
        self.assertEqual(hint.width(), 640)

    def test_detail_header_uses_fallback_icon_and_translated_text(self):
        header = self._builder().build_detail_header("基础设置")
        self.addCleanup(header.deleteLater)

        self.assertEqual(header.objectName(), "SettingsDetailHeader")
        self.assertIsNotNone(header.findChild(QWidget, "SettingsDetailIcon"))

    def test_setting_row_wraps_regular_control_with_effective_width(self):
        control = QPushButton("保存")
        row = self._builder().build_setting_row("并发数", control, control_width=520)
        self.addCleanup(row.deleteLater)

        wrap = row.findChild(QWidget, "SettingsControlWrap")
        self.assertIsNotNone(wrap)
        self.assertEqual(control.width(), 380)
        self.assertEqual(wrap.width(), 380)

    def test_setting_row_reserves_switch_hit_area(self):
        control = UiSwitch()
        row = self._builder().build_setting_row("并发数", control, control_width=520)
        self.addCleanup(row.deleteLater)

        wrap = row.findChild(QWidget, "SettingsControlWrap")
        self.assertIsNotNone(wrap)
        self.assertEqual(wrap.width(), 96)
        self.assertGreaterEqual(row.height(), 60)


if __name__ == "__main__":
    unittest.main()
