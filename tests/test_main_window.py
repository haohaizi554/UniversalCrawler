"""测试模块，覆盖 `tests/test_main_window.py` 对应功能的行为与回归场景。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ui.main_window import MainWindow

class MainWindowTests(unittest.TestCase):
    
    def _make_window(self) -> MainWindow:
        """提供 `_make_window` 对应的内部辅助逻辑，供 `MainWindowTests` 使用。"""
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
        """验证 `test_start_click_emits_crawl_request` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        plugin = Mock()
        plugin.id = "douyin"
        window.current_plugin = plugin
        window.plugin_widget = object()
        window.inp_search.text.return_value = "测试关键词"

        with patch("app.ui.main_window.read_plugin_run_options", return_value={"max_pages": 5}):
            window.on_btn_start_clicked()

        window.sig_start_crawl.emit.assert_called_once_with(
            "测试关键词",
            "douyin",
            {"max_pages": 5, "max_items": 20},
        )
        window.set_crawl_running_state.assert_not_called()

    def test_start_click_rejects_empty_keyword(self):
        """验证 `test_start_click_rejects_empty_keyword` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.current_plugin = Mock(id="douyin")
        window.inp_search.text.return_value = "   "

        window.on_btn_start_clicked()

        window.append_log.assert_called_once()
        window.sig_start_crawl.emit.assert_not_called()

    def test_start_click_reports_run_option_error(self):
        """验证 `test_start_click_reports_run_option_error` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        plugin = Mock()
        plugin.id = "douyin"
        window.current_plugin = plugin
        window.plugin_widget = object()
        window.inp_search.text.return_value = "测试关键词"

        with patch("app.ui.main_window.read_plugin_run_options", side_effect=ValueError("bad config")):
            window.on_btn_start_clicked()

        window.append_log.assert_called_once()
        window.sig_start_crawl.emit.assert_not_called()
        window.set_crawl_running_state.assert_not_called()

    def test_emit_delete_for_video_uses_left_panel_lookup(self):
        """验证 `test_emit_delete_for_video_uses_left_panel_lookup` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.left_panel.find_row_by_video_id.return_value = 3

        window._emit_delete_for_video("video-1")

        window.sig_delete_video.emit.assert_called_once_with(3, "video-1")

    def test_copy_trace_click_requires_selected_video(self):
        """验证 `test_copy_trace_click_requires_selected_video` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.get_selected_video_id = Mock(return_value=None)

        window._on_copy_trace_clicked()

        window.append_log.assert_called_once()
        window.sig_copy_trace_id.emit.assert_not_called()

    def test_file_association_click_emits_selected_groups(self):
        window = self._make_window()
        window.sig_register_file_associations = Mock()
        window.show_file_association_dialog = Mock(
            return_value=SimpleNamespace(include_video=True, include_image=False)
        )

        window.on_btn_file_association_clicked()

        window.sig_register_file_associations.emit.assert_called_once_with(True, False)

    def test_file_association_click_ignores_cancel(self):
        window = self._make_window()
        window.sig_register_file_associations = Mock()
        window.show_file_association_dialog = Mock(return_value=None)

        window.on_btn_file_association_clicked()

        window.sig_register_file_associations.emit.assert_not_called()

    @patch("app.ui.main_window.get_platform_runtime_defaults", return_value={"max_items": 12})
    @patch("app.ui.main_window.cfg.set")
    @patch("app.ui.main_window.registry.get_plugin")
    def test_source_changed_updates_top_bar_fields(self, mock_get_plugin, mock_cfg_set, mock_defaults):
        """切换平台时更新统一顶部栏字段，不再重建平台专属动态控件。"""
        window = self._make_window()
        plugin = Mock()
        plugin.id = "douyin"
        plugin.get_search_placeholder.return_value = "输入分享链接"
        mock_get_plugin.return_value = plugin

        window.combo_source = Mock()
        window.combo_source.currentData.return_value = "douyin"
        window.top_bar = Mock()

        window.on_source_changed(0)

        window.inp_search.setPlaceholderText.assert_called_once_with("输入分享链接")
        window.top_bar.configure_for_platform.assert_called_once()
        mock_defaults.assert_called_once_with("douyin")
        mock_cfg_set.assert_called_once_with("common", "last_source", "douyin")

    @patch("app.ui.main_window.registry.get_plugin", return_value=None)
    def test_source_changed_ignores_unknown_plugin(self, _mock_get_plugin):
        """验证 `test_source_changed_ignores_unknown_plugin` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.combo_source = Mock()
        window.combo_source.currentData.return_value = "unknown"
        window.layout_dynamic = Mock()
        window.container_dynamic = Mock()

        window.on_source_changed(0)

        window.inp_search.setPlaceholderText.assert_not_called()

    def test_frontend_refresh_is_coalesced_by_timer(self):
        class FakeScheduler:
            def __init__(self):
                self.calls: list[str] = []

            def schedule(self, topic):
                self.calls.append(topic)

        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.get_snapshot.return_value = {"app_status": {}}
        window._ui_update_scheduler = FakeScheduler()
        window._frontend_refresh_pending_mock = False

        MainWindow.refresh_frontend_state(window)
        MainWindow.refresh_frontend_state(window)

        self.assertEqual(window._ui_update_scheduler.calls, ["frontend", "frontend"])
        window._frontend_state_service.get_snapshot.assert_not_called()

        MainWindow._flush_frontend_state(window)

        window._frontend_state_service.get_snapshot.assert_called_once_with(mock=False, sections=None)
        window.app_shell.render.assert_called_once_with({"app_status": {}}, changed_sections=None)

    def test_frontend_refresh_force_renders_immediately(self):
        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.get_snapshot.return_value = {"app_status": {}}
        window._ui_update_scheduler = Mock()

        MainWindow.refresh_frontend_state(window, force=True)

        window._ui_update_scheduler.schedule.assert_not_called()
        window._frontend_state_service.get_snapshot.assert_called_once_with(mock=False, sections=None)
        window.app_shell.render.assert_called_once_with({"app_status": {}}, changed_sections=None)

    def test_page_changed_updates_visibility_without_forcing_extra_render(self):
        window = self._make_window()
        window.app_state = Mock()
        window.refresh_frontend_state = Mock()
        window.app_shell = Mock()
        window.app_shell.pages = {"queue": Mock(), "logs": Mock()}

        MainWindow._on_page_changed(window, "logs")

        window.app_state.set_visible_page.assert_called_once_with("logs", ["queue", "logs"], emit_change=False)
        window.refresh_frontend_state.assert_not_called()

    def test_app_state_videos_update_schedules_frontend_refresh(self):
        window = self._make_window()

        class FakeScheduler:
            def __init__(self):
                self.calls = []

            def schedule(self, topic="frontend", *, force=False):
                self.calls.append(topic)

        window._ui_update_scheduler = FakeScheduler()
        window.refresh_frontend_state = Mock()

        MainWindow._on_app_state_changed(window, {"topic": "videos.update"})

        window.refresh_frontend_state.assert_not_called()
        self.assertEqual(window._ui_update_scheduler.calls, ["frontend"])

    def test_settings_update_topic_refreshes_download_options_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"settings.update"})

        self.assertEqual(sections, frozenset({"settings_snapshot", "download_options", "app_status"}))

    def test_metadata_topic_refreshes_completed_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"videos.metadata"})

        self.assertEqual(sections, frozenset({"completed_items", "app_status"}))

    def test_terminal_video_topic_refreshes_completed_and_failed_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"videos.terminal"})

        self.assertEqual(
            sections,
            frozenset({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"}),
        )

    def test_update_download_options_refreshes_effective_options_immediately(self):
        window = self._make_window()
        window._cached_snapshot = {"version": 1, "download_options": {"max_concurrent": 3}}
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {"auto_retry": True, "max_retries": 3, "max_concurrent": 6},
        }
        window._render_frontend_state = Mock()
        window.refresh_frontend_state = Mock()

        MainWindow._update_download_options(window, {"max_concurrent": 6})

        window._frontend_state_service.handle_action.assert_called_once_with(
            "update_download_options",
            {"max_concurrent": 6},
        )
        window._render_frontend_state.assert_called_once_with(topics={"settings.update"})
        window.refresh_frontend_state.assert_not_called()

    def test_cleanup_media_delegates_to_media_panel(self):
        """验证 `test_cleanup_media_delegates_to_media_panel` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.media_panel = Mock()

        window.cleanup_media()

        window.media_panel.cleanup.assert_called_once()

    def test_release_media_playback_delegates_to_media_panel(self):
        """删除前的媒体释放必须委托到预览面板，确保文件句柄被真正释放。"""
        window = self._make_window()
        window.media_panel = Mock()

        window.release_media_playback()

        window.media_panel.release_media.assert_called_once()

    @patch("app.ui.main_window.apply_application_theme")
    @patch("app.ui.main_window.cfg.set")
    def test_toggle_theme_persists_state_and_emits_signal(self, mock_cfg_set, mock_apply_theme):
        """验证 `test_toggle_theme_persists_state_and_emits_signal` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.is_dark_theme = True
        window.top_bar = Mock()
        window.setPalette = Mock()
        window.sig_theme_changed = Mock()

        window.toggle_theme()

        self.assertFalse(window.is_dark_theme)
        mock_apply_theme.assert_called_once_with(False)
        window.top_bar.set_theme_icon.assert_called_once_with(False)
        window.sig_theme_changed.emit.assert_called_once_with(False)
        mock_cfg_set.assert_any_call("common", "dark_theme", False)
        mock_cfg_set.assert_any_call("common", "theme", "light")

    @patch("app.ui.main_window.QByteArray")
    @patch("app.ui.main_window.cfg.get", return_value="aa55")
    def test_toggle_fullscreen_mode_restores_state_when_exiting(self, mock_cfg_get, mock_qbytearray):
        """验证 `test_toggle_fullscreen_mode_restores_state_when_exiting` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
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
