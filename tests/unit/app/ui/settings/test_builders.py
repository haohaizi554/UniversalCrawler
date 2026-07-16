"""设置控件构建器的字段映射与布局测试。"""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from app.ui.plugin_settings import (
    MissAVSettingsWidget,
    PageLimitSettingsWidget,
    read_bilibili_run_options,
    read_douyin_run_options,
    read_missav_run_options,
    read_xiaohongshu_run_options,
)

class SettingsBuildersTests(unittest.TestCase):
    """验证平台设置控件和运行参数读取逻辑。"""

    @classmethod
    def setUpClass(cls):
        
        cls.app = QApplication.instance() or QApplication([])

    def test_page_limit_widget_caps_values_to_max_entry(self):
        """验证 `test_page_limit_widget_caps_values_to_max_entry` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=9999,
            default_pages=9999,
            tooltip="demo",
        )

        self.assertEqual(widget.current_value(), 9999)
        self.assertEqual(widget.combo_pages.currentText(), "max")

    def test_page_limit_widget_falls_back_to_one_for_unknown_small_value(self):
        """验证 `test_page_limit_widget_falls_back_to_one_for_unknown_small_value` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=20,
            default_pages=4,
            tooltip="demo",
        )

        self.assertEqual(widget.current_value(), 1)

    def test_page_limit_widget_falls_back_to_recommended_count_for_stale_video_value(self):
        widget = PageLimitSettingsWidget(
            label_text="视频数",
            max_pages=9999,
            default_pages=100,
            tooltip="demo",
            preset_values=[10, 20, 30, 50, 9999],
        )

        self.assertEqual(widget.current_value(), 20)

    @patch("app.ui.plugin_settings.cfg.set")
    def test_read_bilibili_run_options_reads_selected_pages_without_persisting(self, mocked_set):
        """验证 `test_read_bilibili_run_options_persists_selected_pages` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = PageLimitSettingsWidget(
            label_text="页数:",
            max_pages=9999,
            default_pages=1,
            tooltip="demo",
            preset_values=[1, 2, 3, 5, 9999],
        )
        widget.set_current_value(3, 9999)

        result = read_bilibili_run_options(widget)

        self.assertEqual(result, {"max_pages": 3, "max_items": 9999})
        mocked_set.assert_not_called()

    def test_read_douyin_run_options_returns_defaults_for_invalid_widget(self):
        """验证 `test_read_douyin_run_options_returns_defaults_for_invalid_widget` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        result = read_douyin_run_options(None)

        self.assertEqual(result, {"max_items": 20, "timeout": 60})

    def test_read_xiaohongshu_run_options_returns_defaults_for_invalid_widget(self):
        """验证小红书运行参数读取在无控件时使用默认值。"""
        result = read_xiaohongshu_run_options(None)

        self.assertEqual(
            result,
            {
                "max_items": 20,
                "search_max_pages": 5,
                "timeout": 30,
                "request_interval": 0.15,
                "detail_request_interval": 0.0,
            },
        )

    @patch("app.ui.plugin_settings.cfg.update_missav_proxy")
    @patch("app.ui.plugin_settings.cfg.set")
    def test_read_missav_run_options_reads_form_without_persisting(self, mocked_set, mocked_update_proxy):
        """验证 `test_read_missav_run_options_updates_config_and_normalizes_proxy` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        widget = MissAVSettingsWidget()
        widget.chk_individual.setChecked(True)
        widget.combo_priority.setCurrentText("无码流出优先")
        widget.combo_timeout.setCurrentIndex(widget.combo_timeout.findData(120))
        widget.combo_proxy.setCurrentText("127.0.0.1:9001")

        result = read_missav_run_options(widget)

        self.assertEqual(
            result,
            {
                "individual_only": True,
                "priority": "无码流出优先",
                "timeout": 120,
                "proxy": "http://127.0.0.1:9001",
            },
        )
        mocked_set.assert_not_called()
        mocked_update_proxy.assert_not_called()

    def test_read_missav_run_options_returns_defaults_for_invalid_widget(self):
        """验证 `test_read_missav_run_options_returns_defaults_for_invalid_widget` 对应场景是否符合预期，供 `SettingsBuildersTests` 使用。"""
        result = read_missav_run_options(None)

        self.assertEqual(
            result,
            {
                "individual_only": False,
                "priority": "中文字幕优先",
                "timeout": 60,
                "proxy": "http://127.0.0.1:7890",
            },
        )

if __name__ == "__main__":
    unittest.main()
