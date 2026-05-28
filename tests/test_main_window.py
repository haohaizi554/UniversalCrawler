import unittest
from unittest.mock import Mock, patch

from app.ui.main_window import MainWindow


class MainWindowTests(unittest.TestCase):
    def _make_window(self) -> MainWindow:
        window = MainWindow.__new__(MainWindow)
        window.append_log = Mock()
        window.set_crawl_running_state = Mock()
        window.left_panel = Mock()
        window.sig_delete_video = Mock()
        window.sig_copy_trace_id = Mock()
        window.sig_start_crawl = Mock()
        window.inp_search = Mock()
        window.current_plugin = None
        window.plugin_widget = None
        return window

    def test_start_click_emits_crawl_request(self):
        window = self._make_window()
        plugin = Mock()
        plugin.id = "douyin"
        plugin.get_run_options.return_value = {"max_pages": 5}
        window.current_plugin = plugin
        window.plugin_widget = object()
        window.inp_search.text.return_value = "测试关键词"

        window.on_btn_start_clicked()

        window.sig_start_crawl.emit.assert_called_once_with("测试关键词", "douyin", {"max_pages": 5})
        window.set_crawl_running_state.assert_called_once_with(True)

    def test_start_click_rejects_empty_keyword(self):
        window = self._make_window()
        window.current_plugin = Mock(id="douyin")
        window.inp_search.text.return_value = "   "

        window.on_btn_start_clicked()

        window.append_log.assert_called_once()
        window.sig_start_crawl.emit.assert_not_called()

    def test_start_click_reports_run_option_error(self):
        window = self._make_window()
        plugin = Mock()
        plugin.id = "douyin"
        plugin.get_run_options.side_effect = ValueError("bad config")
        window.current_plugin = plugin
        window.plugin_widget = object()
        window.inp_search.text.return_value = "测试关键词"

        window.on_btn_start_clicked()

        window.append_log.assert_called_once()
        window.sig_start_crawl.emit.assert_not_called()
        window.set_crawl_running_state.assert_not_called()

    def test_emit_delete_for_video_uses_left_panel_lookup(self):
        window = self._make_window()
        window.left_panel.find_row_by_video_id.return_value = 3

        window._emit_delete_for_video("video-1")

        window.sig_delete_video.emit.assert_called_once_with(3, "video-1")

    def test_copy_trace_click_requires_selected_video(self):
        window = self._make_window()
        window.get_selected_video_id = Mock(return_value=None)

        window._on_copy_trace_clicked()

        window.append_log.assert_called_once()
        window.sig_copy_trace_id.emit.assert_not_called()

    @patch("app.ui.main_window.cfg.set")
    @patch("app.ui.main_window.registry.get_plugin")
    def test_source_changed_rebuilds_dynamic_widget(self, mock_get_plugin, mock_cfg_set):
        window = self._make_window()
        plugin = Mock()
        plugin.get_search_placeholder.return_value = "输入 BV 号"
        plugin_widget = Mock()
        plugin.get_settings_widget.return_value = plugin_widget
        mock_get_plugin.return_value = plugin

        old_widget = Mock()
        old_item = Mock()
        old_item.widget.return_value = old_widget
        layout_dynamic = Mock()
        layout_dynamic.count.side_effect = [1, 0]
        layout_dynamic.takeAt.return_value = old_item
        window.layout_dynamic = layout_dynamic
        window.combo_source = Mock()
        window.combo_source.currentData.return_value = "bilibili"
        window.container_dynamic = Mock()

        window.on_source_changed(0)

        window.inp_search.setPlaceholderText.assert_called_once_with("输入 BV 号")
        old_widget.deleteLater.assert_called_once()
        layout_dynamic.addWidget.assert_called_once_with(plugin_widget)
        plugin_widget.show.assert_called_once()
        mock_cfg_set.assert_called_once_with("common", "last_source", "bilibili")

    @patch("app.ui.main_window.registry.get_plugin", return_value=None)
    def test_source_changed_ignores_unknown_plugin(self, _mock_get_plugin):
        window = self._make_window()
        window.combo_source = Mock()
        window.combo_source.currentData.return_value = "unknown"
        window.layout_dynamic = Mock()
        window.container_dynamic = Mock()

        window.on_source_changed(0)

        window.inp_search.setPlaceholderText.assert_not_called()

    def test_cleanup_media_delegates_to_media_panel(self):
        window = self._make_window()
        window.media_panel = Mock()

        window.cleanup_media()

        window.media_panel.cleanup.assert_called_once()

    @patch("app.ui.main_window.generate_stylesheet", return_value="style")
    @patch("app.ui.main_window.cfg.set")
    def test_toggle_theme_persists_state_and_emits_signal(self, mock_cfg_set, _mock_stylesheet):
        window = self._make_window()
        window.is_dark_theme = True
        window.top_bar = Mock()
        window.setStyleSheet = Mock()
        window.sig_theme_changed = Mock()

        window.toggle_theme()

        self.assertFalse(window.is_dark_theme)
        window.top_bar.set_theme_icon.assert_called_once_with(False)
        window.sig_theme_changed.emit.assert_called_once_with(False)
        mock_cfg_set.assert_any_call("common", "dark_theme", False)
        mock_cfg_set.assert_any_call("common", "theme", "light")

    @patch("app.ui.main_window.QByteArray")
    @patch("app.ui.main_window.cfg.get", return_value="aa55")
    def test_toggle_fullscreen_mode_restores_state_when_exiting(self, mock_cfg_get, mock_qbytearray):
        window = self._make_window()
        window.is_fullscreen_mode = True
        window.top_bar = Mock()
        window.left_panel = Mock()
        window.log_txt = Mock()
        window.btn_fullscreen = Mock()
        window._set_main_margins = Mock()
        window.showNormal = Mock()
        window.restoreState = Mock()
        mock_qbytearray.fromHex.return_value = "restored-state"

        window.toggle_fullscreen_mode()

        self.assertFalse(window.is_fullscreen_mode)
        window.showNormal.assert_called_once()
        window.btn_fullscreen.setText.assert_called_once_with("[ 全屏 ]")
        window.restoreState.assert_called_once_with("restored-state")
        mock_cfg_get.assert_called_once_with("ui", "window_state")


if __name__ == "__main__":
    unittest.main()
