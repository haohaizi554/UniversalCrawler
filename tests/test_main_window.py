"""测试模块，覆盖 `tests/test_main_window.py` 对应功能的行为与回归场景。"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.frontend_state_service import FrontendStateService
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
        window._pending_delete_video_ids = []
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

    def test_start_click_bilibili_uses_page_count_limit(self):
        window = self._make_window()
        plugin = Mock()
        plugin.id = "bilibili"
        window.current_plugin = plugin
        window.plugin_widget = object()
        window.inp_search.text.return_value = "BV19nRWBtEnF"
        window.top_bar = Mock()
        window.top_bar.current_video_count.return_value = 5

        with patch("app.ui.main_window.read_plugin_run_options", return_value={"max_pages": 2}):
            window.on_btn_start_clicked()

        window.sig_start_crawl.emit.assert_called_once_with(
            "BV19nRWBtEnF",
            "bilibili",
            {"max_pages": 5, "max_items": 9999},
        )
        window.top_bar.current_video_count.assert_called_once()

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
        self.assertEqual(window._pending_delete_video_ids, ["video-1"])

    def test_emit_delete_for_video_keeps_backend_signal_when_row_is_stale(self):
        window = self._make_window()
        window.left_panel.find_row_by_video_id.return_value = -1

        window._emit_delete_for_video("video-1")

        window.sig_delete_video.emit.assert_called_once_with(-1, "video-1")
        self.assertEqual(window._pending_delete_video_ids, ["video-1"])

    def test_remove_video_row_uses_completed_video_id_for_burst_deletes(self):
        window = self._make_window()
        window._frontend_state_service = Mock()
        window.refresh_frontend_state = Mock()
        window._pending_delete_video_ids = ["video-1", "video-2", "video-3"]

        MainWindow.remove_video_row(window, 0, "video-2")

        window._frontend_state_service.remove_video.assert_called_once_with("video-2")
        self.assertEqual(window._pending_delete_video_ids, ["video-1", "video-3"])
        window.refresh_frontend_state.assert_called_once_with(force=True)

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

    def test_error_log_auto_copy_trace_uses_queued_clipboard_signal(self):
        window = self._make_window()
        window._frontend_state_service = SimpleNamespace(
            record_log=Mock(),
            app_state=SimpleNamespace(should_auto_copy_trace_on_error=lambda: True),
        )
        window._clipboard_copy_requested = Mock()

        MainWindow.append_log(window, "boom", trace_id="trace-1", level="ERROR")

        window._frontend_state_service.record_log.assert_called_once_with(
            "boom",
            source="GUI",
            level="ERROR",
            trace_id="trace-1",
        )
        window._clipboard_copy_requested.emit.assert_called_once_with("trace-1")

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

    def test_page_changed_updates_visibility_and_requests_visible_page_section(self):
        window = self._make_window()
        window.app_state = Mock()
        window.refresh_frontend_state = Mock()
        window.app_shell = Mock()
        window.app_shell.pages = {"queue": Mock(), "logs": Mock()}

        MainWindow._on_page_changed(window, "logs")

        window.app_state.set_visible_page.assert_called_once_with("logs", ["queue", "logs"], emit_change=False)
        window.refresh_frontend_state.assert_called_once_with(topics={"page.visible.logs"})

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

    def test_app_state_log_append_uses_thread_safe_scheduler(self):
        window = self._make_window()
        window._pending_refresh_topics = set()
        window._ui_update_scheduler = Mock()
        window._log_refresh_timer = Mock()

        MainWindow._on_app_state_changed(window, {"topic": "logs.append"})

        self.assertEqual(window._pending_refresh_topics, {"logs.append"})
        window._ui_update_scheduler.schedule.assert_called_once_with("logs.append")
        window._log_refresh_timer.isActive.assert_not_called()
        window._log_refresh_timer.start.assert_not_called()

    def test_app_state_event_storm_batches_until_scheduler_flush(self):
        class FakeScheduler:
            def __init__(self):
                self.calls: list[str] = []

            def schedule(self, topic="frontend", *, force=False):
                self.calls.append(topic)

        window = self._make_window()
        window._pending_refresh_topics = set()
        window._frontend_refresh_pending_mock = False
        window._ui_update_scheduler = FakeScheduler()
        window._frontend_state_service = Mock()
        window._frontend_state_service.get_snapshot.return_value = {
            "active_downloads": [],
            "log_items": [],
            "app_status": {},
        }
        window.app_shell = Mock()

        for index in range(500):
            MainWindow._on_app_state_changed(
                window,
                {"topic": "videos.update", "video_id": "v1", "progress": index % 99},
            )
            MainWindow._on_app_state_changed(window, {"topic": "logs.append", "count": index})

        window._frontend_state_service.get_snapshot.assert_not_called()
        window.app_shell.render.assert_not_called()
        self.assertEqual(window._pending_refresh_topics, {"videos.update", "logs.append"})
        self.assertEqual(len(window._ui_update_scheduler.calls), 1000)

        MainWindow._flush_frontend_state(window)

        expected_sections = frozenset({"active_downloads", "log_items", "app_status"})
        window._frontend_state_service.get_snapshot.assert_called_once_with(
            mock=False,
            sections=expected_sections,
        )
        window.app_shell.render.assert_called_once_with(
            {"active_downloads": [], "log_items": [], "app_status": {}},
            changed_sections={"active_downloads", "log_items", "app_status"},
        )

    def test_app_state_concurrent_event_storm_keeps_pending_topics_thread_safe(self):
        class FakeScheduler:
            def __init__(self):
                self.calls: list[str] = []
                self.lock = threading.Lock()

            def schedule(self, topic="frontend", *, force=False):
                with self.lock:
                    self.calls.append(topic)

        window = self._make_window()
        window._pending_refresh_topics = set()
        window._frontend_refresh_pending_mock = False
        window._ui_update_scheduler = FakeScheduler()
        window._frontend_state_service = Mock()
        window._frontend_state_service.get_snapshot.return_value = {
            "active_downloads": [],
            "log_items": [],
            "app_status": {},
        }
        window.app_shell = Mock()
        errors: list[BaseException] = []

        def publish_many(thread_index: int) -> None:
            try:
                for index in range(200):
                    MainWindow._on_app_state_changed(
                        window,
                        {
                            "topic": "videos.update",
                            "video_id": f"v{thread_index}",
                            "progress": index % 100,
                        },
                    )
                    MainWindow._on_app_state_changed(window, {"topic": "logs.append", "count": index})
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publish_many, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(window._pending_refresh_topics, {"videos.update", "logs.append"})
        window._frontend_state_service.get_snapshot.assert_not_called()
        window.app_shell.render.assert_not_called()

        MainWindow._flush_frontend_state(window)

        expected_sections = frozenset({"active_downloads", "log_items", "app_status"})
        window._frontend_state_service.get_snapshot.assert_called_once_with(
            mock=False,
            sections=expected_sections,
        )
        window.app_shell.render.assert_called_once()

    def test_settings_update_topic_refreshes_download_options_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"settings.update"})

        self.assertEqual(sections, frozenset({"settings_snapshot", "settings_contract", "download_options", "app_status"}))

    def test_metadata_topic_refreshes_completed_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"videos.metadata"})

        self.assertEqual(sections, frozenset({"completed_items", "app_status"}))

    def test_terminal_video_topic_refreshes_completed_and_failed_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"videos.terminal"})

        self.assertEqual(
            sections,
            frozenset({"queue_items", "active_downloads", "completed_items", "failed_items", "app_status"}),
        )

    def test_main_window_topic_sections_follow_frontend_aggregator_contract(self):
        cases = {
            "task_progress": frozenset({"active_downloads", "app_status"}),
            "video_state_changed": frozenset({"active_downloads", "app_status"}),
            "scan_result": frozenset({"queue_items", "app_status"}),
            "crawl_state_changed": frozenset({"app_status"}),
            "platforms": frozenset({"settings_snapshot"}),
            "log": frozenset({"log_items", "app_status"}),
        }

        for topic, expected in cases.items():
            with self.subTest(topic=topic):
                self.assertEqual(MainWindow._sections_for_topics(self._make_window(), {topic}), expected)

    def test_video_topics_only_request_visible_page_section(self):
        window = self._make_window()
        window.app_shell = SimpleNamespace(current_page_id="completed")

        self.assertEqual(
            MainWindow._sections_for_topics(window, {"videos.terminal"}),
            frozenset({"completed_items", "app_status"}),
        )
        self.assertEqual(
            MainWindow._sections_for_topics(window, {"task_progress"}),
            frozenset({"app_status"}),
        )

    def test_visible_active_page_keeps_active_progress_section(self):
        window = self._make_window()
        window.app_shell = SimpleNamespace(current_page_id="active")

        self.assertEqual(
            MainWindow._sections_for_topics(window, {"task_progress"}),
            frozenset({"active_downloads", "app_status"}),
        )

    def test_hidden_log_append_only_updates_status(self):
        window = self._make_window()
        window.app_shell = SimpleNamespace(current_page_id="active")

        self.assertEqual(MainWindow._sections_for_topics(window, {"logs.append"}), frozenset({"app_status"}))

    def test_page_visibility_topic_requests_page_section_without_full_refresh(self):
        window = self._make_window()
        window.app_shell = SimpleNamespace(current_page_id="active")

        self.assertEqual(
            MainWindow._sections_for_topics(window, {"page.visible.failed"}),
            frozenset({"failed_items", "app_status"}),
        )

    def test_topic_scoped_render_uses_exact_snapshot_sections_not_delta_union(self):
        window = self._make_window()
        window.app_shell = Mock()
        window.app_shell.current_page_id = "active"
        window.app_shell.render = Mock()
        service = FrontendStateService()
        service.get_snapshot = Mock(return_value={"active_downloads": [], "app_status": {}, "version": 2})
        service.get_delta = Mock()
        window._frontend_state_service = service
        window._cached_snapshot = {"version": 1, "active_downloads": [], "app_status": {}}

        MainWindow._render_frontend_state(window, topics={"videos.terminal"})

        service.get_delta.assert_not_called()
        service.get_snapshot.assert_called_once_with(
            mock=False,
            sections=frozenset({"active_downloads", "app_status"}),
        )
        window.app_shell.render.assert_called_once()

    def test_update_basic_setting_updates_current_directory_and_refreshes(self):
        window = self._make_window()
        window.sig_change_dir = Mock()
        window.refresh_frontend_state = Mock()
        window.is_dark_theme = False
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {
                "config_key": "save_directory",
                "directory": "D:\\Videos\\Downloads",
                "value": "D:\\Videos\\Downloads",
            },
        }

        def _get_dir(obj):
            return obj.__dict__.get("_test_current_save_dir", "")

        def _set_dir(obj, value):
            obj.__dict__["_test_current_save_dir"] = value

        with patch.object(MainWindow, "current_save_dir", new=property(_get_dir, _set_dir)):
            window.current_save_dir = "D:/old"
            MainWindow._update_basic_setting(window, "common", "download_directory", '"D:/Videos/Downloads/file.mp4"')

            self.assertEqual(window.current_save_dir, "D:\\Videos\\Downloads")

        window._frontend_state_service.handle_action.assert_called_once_with(
            "update_basic_setting",
            {"key": "download_directory", "value": '"D:/Videos/Downloads/file.mp4"'},
        )
        window.sig_change_dir.emit.assert_called_once()
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_setting_applies_playback_runtime_hook(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window.app_shell = SimpleNamespace(apply_playback_settings=Mock())
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {"section": "playback", "key": "autoplay_next", "value": False},
        }

        MainWindow._update_basic_setting(window, "playback", "autoplay_next", False)

        window._frontend_state_service.handle_action.assert_called_once_with(
            "update_setting",
            {"key": "autoplay_next", "value": False, "section": "playback"},
        )
        window.app_shell.apply_playback_settings.assert_called_once()
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_setting_refreshes_logs_for_logging_runtime_hook(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {"section": "logging", "key": "retention_days", "value": 3},
        }

        MainWindow._update_basic_setting(window, "logging", "retention_days", 3)

        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update", "logs.append"})

    @patch("app.ui.main_window.cfg.set")
    @patch("app.ui.main_window.cfg.get", return_value=True)
    def test_settings_theme_update_disables_follow_system_first(self, _mock_cfg_get, mock_cfg_set):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window.is_dark_theme = False
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {"section": "common", "key": "theme", "value": "dark"},
        }
        window._apply_runtime_setting_after_update = Mock(return_value=set())

        MainWindow._update_basic_setting(window, "common", "theme", "dark")

        mock_cfg_set.assert_called_once_with("appearance", "follow_system", False)
        window._frontend_state_service.handle_action.assert_called_once_with(
            "update_basic_setting",
            {"key": "theme", "value": "dark"},
        )
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_download_options_refreshes_effective_options_immediately(self):
        window = self._make_window()
        window._cached_snapshot = {"version": 1, "download_options": {"max_concurrent": 3}}
        window._frontend_state_service = Mock()
        window._frontend_state_service.handle_action.return_value = {
            "status": "ok",
            "data": {"auto_retry": True, "max_retries": 3, "max_concurrent": 5},
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

    def test_resize_media_panel_before_exposed_is_safe(self):
        window = self._make_window()

        MainWindow._resize_media_panel_if_ready(window)

        window.media_panel = Mock()
        MainWindow._resize_media_panel_if_ready(window)

        window.media_panel.resize_media.assert_called_once()

    def test_frameless_hit_test_keeps_native_resize_and_drag_regions(self):
        from PyQt6.QtCore import QPoint, QRect

        class FakeTitleBar:
            def isVisible(self):
                return True

            def mapFromGlobal(self, pos):
                return QPoint(pos.x() - 100, pos.y() - 100)

            def rect(self):
                return QRect(0, 0, 500, 34)

            def is_interactive_at(self, _pos):
                return False

        window = self._make_window()
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        window.window_title_bar = FakeTitleBar()

        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(100, 100)), MainWindow.HTTOPLEFT)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(599, 499)), MainWindow.HTBOTTOMRIGHT)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(180, 116)), MainWindow.HTCAPTION)
        self.assertIsNone(MainWindow._frameless_hit_test(window, QPoint(250, 250)))

    def test_frameless_resize_fallback_uses_system_resize(self):
        from PyQt6.QtCore import QPoint, QRect

        window = self._make_window()
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window._custom_maximized = False
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        handle = Mock()
        handle.startSystemResize.return_value = True
        window.windowHandle = Mock(return_value=handle)

        started = MainWindow._start_frameless_system_resize(window, QPoint(599, 499))

        self.assertTrue(started)
        handle.startSystemResize.assert_called_once()

    def test_frameless_resize_edges_use_native_cursor_shapes(self):
        from PyQt6.QtCore import Qt

        self.assertEqual(
            MainWindow._cursor_for_resize_edges(Qt.Edge.TopEdge),
            Qt.CursorShape.SizeVerCursor,
        )
        self.assertEqual(
            MainWindow._cursor_for_resize_edges(Qt.Edge.RightEdge),
            Qt.CursorShape.SizeHorCursor,
        )
        self.assertEqual(
            MainWindow._cursor_for_resize_edges(Qt.Edge.TopEdge | Qt.Edge.LeftEdge),
            Qt.CursorShape.SizeFDiagCursor,
        )
        self.assertEqual(
            MainWindow._cursor_for_resize_edges(Qt.Edge.TopEdge | Qt.Edge.RightEdge),
            Qt.CursorShape.SizeBDiagCursor,
        )

    def test_custom_title_bar_uses_compact_native_like_height(self):
        from app.ui.layout.window_title_bar import WindowChromeButton, WindowTitleBar

        self.assertEqual(WindowTitleBar.HEIGHT, 28)
        self.assertEqual(WindowChromeButton.WIDTH, 38)

    def test_default_window_size_is_bounded_by_available_screen(self):
        from PyQt6.QtCore import QRect, QSize

        available = QRect(0, 0, 1366, 768)

        size = MainWindow._default_window_size_for_available(available)
        minimum = MainWindow._minimum_window_size_for_available(available)

        self.assertLessEqual(size.width(), available.width())
        self.assertLessEqual(size.height(), available.height())
        self.assertGreaterEqual(size.width(), minimum.width())
        self.assertGreaterEqual(size.height(), minimum.height())

        roomy = MainWindow._default_window_size_for_available(QRect(0, 0, 2560, 1440))
        self.assertEqual(roomy, QSize(1500, 880))
        roomy_minimum = MainWindow._minimum_window_size_for_available(QRect(0, 0, 2560, 1440))
        self.assertEqual(roomy_minimum, QSize(1360, 760))

    def test_constrain_window_geometry_keeps_window_inside_available_screen(self):
        from PyQt6.QtCore import QRect, QSize

        window = self._make_window()
        window._available_geometry_for_rect = Mock(return_value=QRect(0, 0, 1280, 720))
        window.geometry = Mock(return_value=QRect(-200, -120, 1800, 1000))
        window.frameGeometry = Mock(return_value=QRect(-200, -120, 1800, 1000))
        window.setMinimumSize = Mock()
        window.setGeometry = Mock()

        MainWindow._constrain_window_geometry_to_screen(window)

        window.setMinimumSize.assert_called_once()
        constrained = window.setGeometry.call_args.args[0]
        self.assertGreaterEqual(constrained.x(), 0)
        self.assertGreaterEqual(constrained.y(), 0)
        self.assertLessEqual(constrained.right(), 1279)
        self.assertLessEqual(constrained.bottom(), 719)

    def test_mouse_press_on_frameless_edge_accepts_started_resize(self):
        from PyQt6.QtCore import QPoint, Qt

        class _PointWrapper:
            def toPoint(self):
                return QPoint(599, 300)

        class _MouseEvent:
            def __init__(self):
                self.accept = Mock()

            def button(self):
                return Qt.MouseButton.LeftButton

            def globalPosition(self):
                return _PointWrapper()

        window = self._make_window()
        window._start_frameless_system_resize = Mock(return_value=True)
        event = _MouseEvent()

        MainWindow.mousePressEvent(window, event)

        event.accept.assert_called_once()
        window._start_frameless_system_resize.assert_called_once_with(QPoint(599, 300))

    def test_custom_maximized_window_does_not_expose_resize_edges(self):
        from PyQt6.QtCore import QPoint, QRect, Qt

        window = self._make_window()
        window._custom_maximized = True
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window.windowState = Mock(return_value=Qt.WindowState.WindowNoState)
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        window.window_title_bar = None

        self.assertIsNone(MainWindow._frameless_hit_test(window, QPoint(599, 300)))

    def test_work_area_maximize_restores_saved_geometry_without_qt_maximize_state(self):
        from PyQt6.QtCore import QRect

        window = self._make_window()
        window._qt_initialized = True
        window._custom_maximized = False
        normal_geometry = QRect(10, 20, 900, 600)
        work_area = QRect(0, 0, 1440, 960)
        window.geometry = Mock(return_value=normal_geometry)
        window._current_work_area_geometry = Mock(return_value=work_area)
        window.setGeometry = Mock()
        window.isMaximized = Mock(return_value=False)
        window.isFullScreen = Mock(return_value=False)
        window.showNormal = Mock()

        MainWindow._maximize_to_work_area(window)

        self.assertTrue(window._custom_maximized)
        self.assertEqual(window._pre_custom_maximize_geometry, normal_geometry)
        window.setGeometry.assert_called_once_with(work_area)

        window.setGeometry.reset_mock()
        MainWindow._restore_from_custom_or_native_maximized(window)

        self.assertFalse(window._custom_maximized)
        window.setGeometry.assert_called_once_with(normal_geometry)

    def test_native_event_unhandled_returns_false_without_super_call(self):
        window = self._make_window()
        window._handle_frameless_native_event = Mock(return_value=None)

        handled, result = MainWindow.nativeEvent(window, "windows_generic_MSG", object())

        self.assertFalse(handled)
        self.assertEqual(result, 0)

    @patch("app.ui.main_window.cfg.get", return_value=None)
    def test_fullscreen_mode_restores_previous_normal_geometry(self, _mock_cfg_get):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window.saveGeometry = Mock(return_value="saved-geometry")
        window.isMaximized = Mock(return_value=False)
        window.showFullScreen = Mock()
        window.showNormal = Mock()
        window.showMaximized = Mock()
        window.restoreGeometry = Mock()
        window.restoreState = Mock()
        window._set_shell_widgets_visible = Mock()
        window._sync_window_title_bar_state = Mock()
        window.btn_fullscreen = Mock()

        MainWindow.toggle_fullscreen_mode(window)

        window._set_shell_widgets_visible.assert_called_once_with(False)
        window.showFullScreen.assert_called_once()
        self.assertTrue(window.is_fullscreen_mode)
        self.assertEqual(window._pre_fullscreen_geometry, "saved-geometry")

        window._set_shell_widgets_visible.reset_mock()
        MainWindow.toggle_fullscreen_mode(window)

        window._set_shell_widgets_visible.assert_called_once_with(True)
        window.showNormal.assert_called_once()
        window.showMaximized.assert_not_called()
        window.restoreGeometry.assert_called_once_with("saved-geometry")
        self.assertFalse(window.is_fullscreen_mode)
        self.assertIsNone(window._pre_fullscreen_geometry)

    @patch("app.ui.main_window.cfg.get", return_value=None)
    def test_fullscreen_mode_restores_previous_maximized_state(self, _mock_cfg_get):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window.saveGeometry = Mock(return_value="saved-geometry")
        window.isMaximized = Mock(return_value=True)
        window.showFullScreen = Mock()
        window.showNormal = Mock()
        window.showMaximized = Mock()
        window.restoreGeometry = Mock()
        window.restoreState = Mock()
        window._set_shell_widgets_visible = Mock()
        window._sync_window_title_bar_state = Mock()
        window.btn_fullscreen = Mock()

        MainWindow.toggle_fullscreen_mode(window)
        MainWindow.toggle_fullscreen_mode(window)

        window.showNormal.assert_called_once()
        window.showMaximized.assert_called_once()
        window.restoreGeometry.assert_not_called()
        self.assertFalse(window.is_fullscreen_mode)

    @patch("app.ui.main_window.apply_application_theme")
    @patch("app.ui.main_window.cfg.set")
    @patch("app.ui.main_window.cfg.set_many")
    def test_toggle_theme_persists_state_and_emits_signal(self, mock_set_many, mock_cfg_set, mock_apply_theme):
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
        mock_set_many.assert_called_once_with("common", {"theme": "light", "dark_theme": False})
        mock_cfg_set.assert_called_once_with("appearance", "follow_system", False)

    @patch("app.ui.main_window.cfg.get", return_value=False)
    @patch("app.ui.main_window.apply_application_theme")
    def test_apply_theme_syncs_settings_page_theme_segment(self, _mock_apply_theme, _mock_cfg_get):
        window = self._make_window()
        window.is_dark_theme = True
        window.top_bar = Mock()
        window.setPalette = Mock()
        settings_page = Mock()
        window.app_shell = Mock()
        window.app_shell.pages = {"settings": settings_page}

        window._apply_theme_stylesheet()

        settings_page.sync_external_theme.assert_called_once_with(True, follow_system=False)

    @patch("app.ui.main_window.cfg.get")
    def test_language_appearance_update_skips_theme_repolish(self, mock_cfg_get):
        def fake_get(section, key, default=None):
            values = {
                ("appearance", "follow_system"): False,
                ("common", "theme"): "light",
            }
            return values.get((section, key), default)

        mock_cfg_get.side_effect = fake_get
        window = self._make_window()
        window._applying_appearance = False
        window.is_dark_theme = False
        window._apply_theme_stylesheet = Mock()
        window.setPalette = Mock()

        MainWindow._apply_appearance_runtime_settings(window, "language")

        window._apply_theme_stylesheet.assert_not_called()
        window.setPalette.assert_not_called()

    @patch("app.ui.main_window.cfg.get")
    def test_font_size_appearance_update_skips_sidebar_theme_refresh(self, mock_cfg_get):
        def fake_get(section, key, default=None):
            values = {
                ("appearance", "follow_system"): False,
                ("common", "theme"): "light",
            }
            return values.get((section, key), default)

        mock_cfg_get.side_effect = fake_get
        window = self._make_window()
        window._applying_appearance = False
        window.is_dark_theme = False
        window._apply_theme_stylesheet = Mock()
        window.setPalette = Mock()

        MainWindow._apply_appearance_runtime_settings(window, "font_size")

        window._apply_theme_stylesheet.assert_called_once_with(
            refresh_shell_theme=False,
            sync_settings_theme=False,
        )
        window.setPalette.assert_called_once()

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
