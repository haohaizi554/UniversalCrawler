"""测试模块，覆盖 `tests/test_settings_builders.py` 对应功能的行为与回归场景。"""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from app.ui.plugin_settings import (
    MissAVSettingsWidget,
    PageLimitSettingsWidget,
    read_bilibili_run_options,
    read_douyin_run_options,
    read_missav_run_options,
)


class SettingsBuildersTests(unittest.TestCase):
    """验证平台设置控件和运行参数读取逻辑。"""

    @classmethod
    def setUpClass(cls):
        """执行 `setUpClass` 对应的业务逻辑，供 `SettingsBuildersTests` 使用。"""
        cls.app = QApplication.instance() or QApplication([])

    def test_page_limit_widget_caps_values_to_max_entry(self):
        """验证 `test_page_limit_widget_caps_values_to_max_entry` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=500,
            default_pages=9999,
            tooltip="demo",
        )

        self.assertEqual(widget.current_value(), 500)
        self.assertEqual(widget.combo_pages.currentText(), "max")

    def test_page_limit_widget_falls_back_to_one_for_unknown_small_value(self):
        """验证 `test_page_limit_widget_falls_back_to_one_for_unknown_small_value` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=20,
            default_pages=3,
            tooltip="demo",
        )

        self.assertEqual(widget.current_value(), 1)

    @patch("app.ui.plugin_settings.cfg.set")
    def test_read_bilibili_run_options_persists_selected_pages(self, mocked_set):
        """验证 `test_read_bilibili_run_options_persists_selected_pages` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=500,
            default_pages=1,
            tooltip="demo",
        )
        widget.set_current_value(10, 500)

        result = read_bilibili_run_options(widget)

        self.assertEqual(result, {"max_pages": 10})
        mocked_set.assert_called_once_with("bilibili", "max_pages", 10)

    def test_read_douyin_run_options_returns_defaults_for_invalid_widget(self):
        """验证 `test_read_douyin_run_options_returns_defaults_for_invalid_widget` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        result = read_douyin_run_options(None)

        self.assertEqual(result, {"max_items": 20, "timeout": 10})

    @patch("app.ui.plugin_settings.cfg.update_missav_proxy")
    @patch("app.ui.plugin_settings.cfg.set")
    def test_read_missav_run_options_updates_config_and_normalizes_proxy(self, mocked_set, mocked_update_proxy):
        """验证 `test_read_missav_run_options_updates_config_and_normalizes_proxy` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = MissAVSettingsWidget()
        widget.chk_individual.setChecked(True)
        widget.combo_priority.setCurrentText("无码流出优先")
        widget.combo_proxy.setCurrentText("127.0.0.1:9001")

        result = read_missav_run_options(widget)

        self.assertEqual(
            result,
            {
                "individual_only": True,
                "priority": "无码流出优先",
                "proxy": "http://127.0.0.1:9001",
            },
        )
        mocked_set.assert_any_call("missav", "individual_only", True)
        mocked_set.assert_any_call("missav", "priority", "无码流出优先")
        mocked_update_proxy.assert_called_once_with("127.0.0.1:9001", "http://127.0.0.1:9001")

    def test_read_missav_run_options_returns_defaults_for_invalid_widget(self):
        """验证 `test_read_missav_run_options_returns_defaults_for_invalid_widget` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        result = read_missav_run_options(None)

        self.assertEqual(
            result,
            {
                "individual_only": False,
                "priority": "中文字幕优先",
                "proxy": "http://127.0.0.1:7890",
            },
        )


if __name__ == "__main__":
    unittest.main()
