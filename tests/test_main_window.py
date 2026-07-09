"""测试模块，覆盖 `tests/test_main_window.py` 对应功能的行为与回归场景。"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.frontend_state_service import FrontendStateService
from app.ui.main_window import MainWindow
from app.ui.viewmodels.frontend_action_worker import FrontendActionRequest, FrontendActionResult
from app.ui.viewmodels.frontend_snapshot_worker import FrontendSnapshotResult, build_frontend_snapshot

class MainWindowTests(unittest.TestCase):

    class CapturingSnapshotWorker:
        def __init__(self):
            self.requests = []

        def submit(self, request):
            self.requests.append(request)

    class CapturingActionWorker:
        def __init__(self):
            self.requests = []

        def submit(self, request):
            self.requests.append(request)

    class CapturingUpdateCheckWorker:
        def __init__(self):
            self.requests = []
            self.shutdown_called = False

        def submit(self, request):
            self.requests.append(request)

        def shutdown(self):
            self.shutdown_called = True

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

    class FakeShellWidget:
        def __init__(self, *, visible: bool = True, updates_enabled: bool = True, object_name: str = "FakeWidget"):
            self._visible = visible
            self._updates_enabled = updates_enabled
            self._object_name = object_name
            self.set_updates_enabled_calls: list[bool] = []
            self.set_visible_calls: list[bool] = []
            self.show_calls = 0
            self.update_calls = 0
            self.update_geometry_calls = 0
            self.pages = {}

        def isVisible(self):
            return self._visible

        def isHidden(self):
            return not self._visible

        def updatesEnabled(self):
            return self._updates_enabled

        def setUpdatesEnabled(self, enabled):
            self._updates_enabled = bool(enabled)
            self.set_updates_enabled_calls.append(bool(enabled))

        def setVisible(self, visible):
            self._visible = bool(visible)
            self.set_visible_calls.append(bool(visible))

        def show(self):
            self._visible = True
            self.show_calls += 1

        def updateGeometry(self):
            self.update_geometry_calls += 1

        def update(self):
            self.update_calls += 1

        def geometry(self):
            return "QRect(0, 0, 100, 100)"

        def objectName(self):
            return self._object_name

        def apply_theme(self, _is_dark):
            self.update_calls += 1

    def _install_snapshot_worker(self, window: MainWindow) -> "MainWindowTests.CapturingSnapshotWorker":
        worker = self.CapturingSnapshotWorker()
        window._frontend_snapshot_worker = worker
        window._frontend_snapshot_sequence = 0
        window._frontend_section_signatures = {}
        return worker

    def test_app_state_subscription_prefers_async_event_bus_handler(self):
        class FakeBus:
            def __init__(self):
                self.async_calls = []
                self.sync_calls = []

            def subscribe_async(self, topic, handler):
                self.async_calls.append((topic, handler))
                return "async-handler"

            def subscribe(self, topic, handler):
                self.sync_calls.append((topic, handler))
                return "sync-handler"

        window = self._make_window()
        bus = FakeBus()
        window.event_bus = bus
        window._queue_app_state_changed = Mock()

        handler = MainWindow._subscribe_app_state_changed(window)

        self.assertEqual(handler, "async-handler")
        self.assertEqual(bus.async_calls, [("app_state.changed", window._queue_app_state_changed)])
        self.assertEqual(bus.sync_calls, [])

    def test_set_frontend_state_service_injects_cache_service_into_app_shell(self):
        window = self._make_window()
        bus = SimpleNamespace()
        cache_service = object()
        app_state = SimpleNamespace(event_bus=bus)
        service = SimpleNamespace(app_state=app_state, cache_service=cache_service)
        window.event_bus = bus
        window._owns_frontend_state_service = False
        window.app_shell = Mock()
        window.refresh_frontend_state = Mock()

        MainWindow.set_frontend_state_service(window, service)

        window.app_shell.set_cache_service.assert_called_once_with(cache_service)
        window.refresh_frontend_state.assert_called_once_with(force=True)

    @staticmethod
    def _snapshot_result(request, snapshot, *, changed_sections=None, skip_render=False, signatures=None):
        return FrontendSnapshotResult(
            sequence=request.sequence,
            service_token=request.service_token,
            snapshot=snapshot,
            changed_sections=changed_sections,
            section_signatures=signatures or {},
            skip_render=skip_render,
            build_duration_ms=1.0,
        )

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
        window.refresh_frontend_state.assert_called_once_with(topics={"videos.remove"})

    def test_video_operation_refreshes_are_topic_scoped(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()

        MainWindow.refresh_table_bindings(window)

        window.refresh_frontend_state.assert_called_once_with(topics={"videos.replace"})

    def test_reorder_video_row_refreshes_without_force_full_snapshot(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()
        window.app_shell = Mock()
        window.app_shell.row_for_video_id.return_value = 4
        video_item = SimpleNamespace(id="video-1")

        row = MainWindow.reorder_video_row(window, video_item)

        window._frontend_state_service.upsert_video.assert_called_once_with(video_item)
        window.refresh_frontend_state.assert_called_once_with(topics={"videos.replace"})
        self.assertEqual(row, 4)

    def test_retry_failed_item_refreshes_without_force_full_snapshot(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        MainWindow._retry_failed_item(window, "video-1")

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "retry_failed")
        self.assertEqual(request.payload, {"video_id": "video-1"})
        window.refresh_frontend_state.assert_not_called()

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="retry_failed",
                payload=dict(request.payload),
                result={"status": "ok", "message": "retry queued"},
            ),
        )

        window.refresh_frontend_state.assert_called_once_with(topics={"videos.replace"})

    def test_pause_download_item_refreshes_without_force_full_snapshot(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        MainWindow._pause_download_item(window, "video-1")

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "pause_download")
        self.assertEqual(request.payload, {"video_id": "video-1"})
        window.refresh_frontend_state.assert_not_called()

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="pause_download",
                payload=dict(request.payload),
                result={"status": "ok", "message": "paused"},
            ),
        )

        window.append_log.assert_called_once_with("paused")
        window.refresh_frontend_state.assert_called_once_with(topics={"videos.update"})

    def test_copy_trace_click_requires_selected_video(self):
        """验证 `test_copy_trace_click_requires_selected_video` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.get_selected_video_id = Mock(return_value=None)

        window._on_copy_trace_clicked()

        window.append_log.assert_called_once()
        window.sig_copy_trace_id.emit.assert_not_called()

    def test_file_association_click_submits_selected_groups_to_action_worker(self):
        window = self._make_window()
        window._submit_frontend_action = Mock(return_value=True)
        window.show_file_association_dialog = Mock(
            return_value=SimpleNamespace(include_video=True, include_image=False)
        )

        window.on_btn_file_association_clicked()

        window._submit_frontend_action.assert_called_once_with(
            "register_file_associations",
            {"include_video": True, "include_image": False},
        )

    def test_file_association_click_ignores_cancel(self):
        window = self._make_window()
        window._submit_frontend_action = Mock(return_value=True)
        window.show_file_association_dialog = Mock(return_value=None)

        window.on_btn_file_association_clicked()

        window._submit_frontend_action.assert_not_called()

    def test_update_check_request_uses_latest_worker(self):
        window = self._make_window()
        worker = self.CapturingUpdateCheckWorker()
        window._update_check_worker = worker
        window._update_check_sequence = 0
        window._update_check_running = False
        window._update_check_lock = threading.RLock()
        window._set_status_bar_update_checking = Mock()
        window._show_basic_message = Mock()
        window._show_update_check_error = Mock()
        window._current_status_version = Mock(return_value="v3.6.17")

        MainWindow._on_update_check_requested(window, "")

        self.assertTrue(window._update_check_running)
        window._set_status_bar_update_checking.assert_called_once_with(True)
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(worker.requests[0].sequence, 1)
        self.assertEqual(worker.requests[0].local_version, "v3.6.17")
        window._show_basic_message.assert_not_called()
        window._show_update_check_error.assert_not_called()

    def test_update_check_worker_is_created_lazily(self):
        window = self._make_window()

        self.assertIsNone(window.__dict__.get("_update_check_worker"))

    def test_update_check_worker_result_emits_existing_signals(self):
        from app.services.update_check_service import UPDATE_STATUS_CURRENT, UpdateCheckResult
        from app.ui.main_window import _UpdateCheckOutcome

        window = self._make_window()
        window._update_check_sequence = 2
        window._update_check_finished = Mock()
        window._update_check_failed = Mock()
        result = UpdateCheckResult(
            status=UPDATE_STATUS_CURRENT,
            local_version="3.6.17",
            latest_version="3.6.17",
            tag_name="v3.6.17",
            release_name="v3.6.17",
            html_url="https://example.test/release",
        )

        MainWindow._on_update_check_worker_result(window, _UpdateCheckOutcome(sequence=1, result=result))
        window._update_check_finished.emit.assert_not_called()

        MainWindow._on_update_check_worker_result(window, _UpdateCheckOutcome(sequence=2, result=result))
        window._update_check_finished.emit.assert_called_once_with(result)
        window._update_check_failed.emit.assert_not_called()

        window._update_check_finished.emit.reset_mock()
        MainWindow._on_update_check_worker_result(window, _UpdateCheckOutcome(sequence=2, error="boom"))
        window._update_check_failed.emit.assert_called_once_with("boom")
        window._update_check_finished.emit.assert_not_called()

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
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0
        mock_get_plugin.return_value = plugin

        window.combo_source = Mock()
        window.combo_source.currentData.return_value = "douyin"
        window.top_bar = Mock()

        window.on_source_changed(0)

        window.inp_search.setPlaceholderText.assert_not_called()
        window.top_bar.configure_for_platform.assert_called_once()
        mock_defaults.assert_called_once_with("douyin")
        mock_cfg_set.assert_not_called()
        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_basic_setting")
        self.assertEqual(request.payload, {"key": "last_source", "value": "douyin"})

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
        worker = self._install_snapshot_worker(window)

        MainWindow.refresh_frontend_state(window)
        MainWindow.refresh_frontend_state(window)

        self.assertEqual(window._ui_update_scheduler.calls, ["frontend", "frontend"])
        window._frontend_state_service.get_snapshot.assert_not_called()

        MainWindow._flush_frontend_state(window)

        window._frontend_state_service.get_snapshot.assert_not_called()
        self.assertEqual(len(worker.requests), 1)
        self.assertIs(worker.requests[0].service, window._frontend_state_service)
        self.assertFalse(worker.requests[0].mock)
        self.assertIsNone(worker.requests[0].sections)
        self.assertFalse(worker.requests[0].use_delta)
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(worker.requests[0], {"app_status": {}}, changed_sections=None),
        )
        window.app_shell.render.assert_called_once_with({"app_status": {}}, changed_sections=None)

    def test_cached_frontend_refresh_submits_delta_request(self):
        class FakeScheduler:
            def __init__(self):
                self.calls: list[str] = []

            def schedule(self, topic):
                self.calls.append(topic)

        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        window._ui_update_scheduler = FakeScheduler()
        window._frontend_refresh_pending_mock = False
        window._cached_snapshot = {"version": 0, "queue_items": [], "app_status": {}}
        worker = self._install_snapshot_worker(window)

        MainWindow.refresh_frontend_state(window)
        MainWindow._flush_frontend_state(window)

        self.assertEqual(len(worker.requests), 1)
        self.assertTrue(worker.requests[0].use_delta)
        self.assertEqual(worker.requests[0].base_version, 0)
        self.assertIsNone(worker.requests[0].sections)
        window._frontend_state_service.get_snapshot.assert_not_called()

    def test_frontend_refresh_force_submits_snapshot_without_scheduler(self):
        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        window._frontend_state_service.get_snapshot.return_value = {"app_status": {}}
        window._ui_update_scheduler = Mock()
        worker = self._install_snapshot_worker(window)

        MainWindow.refresh_frontend_state(window, force=True)

        window._ui_update_scheduler.schedule.assert_not_called()
        window._frontend_state_service.get_snapshot.assert_not_called()
        self.assertEqual(len(worker.requests), 1)
        self.assertIsNone(worker.requests[0].sections)
        self.assertFalse(worker.requests[0].use_delta)
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(worker.requests[0], {"app_status": {}}, changed_sections=None),
        )
        window.app_shell.render.assert_called_once_with({"app_status": {}}, changed_sections=None)

    def test_stale_frontend_snapshot_result_seeds_delta_cache_without_rendering(self):
        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        worker = self._install_snapshot_worker(window)

        MainWindow._render_frontend_state(window)
        MainWindow._render_frontend_state(window)

        self.assertEqual(len(worker.requests), 2)
        self.assertFalse(worker.requests[0].use_delta)
        self.assertFalse(worker.requests[1].use_delta)

        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"version": 7, "queue_items": [], "app_status": {"queue_count": 0}},
                changed_sections=None,
                signatures={"queue_items": "seed"},
            ),
        )

        window.app_shell.render.assert_not_called()
        self.assertEqual(window._cached_snapshot["version"], 7)
        self.assertEqual(window._frontend_section_signatures, {"queue_items": "seed"})

        MainWindow._render_frontend_state(window)

        self.assertEqual(len(worker.requests), 3)
        self.assertTrue(worker.requests[2].use_delta)
        self.assertEqual(worker.requests[2].base_version, 7)

    def test_stale_frontend_snapshot_result_does_not_overwrite_newer_cache(self):
        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        worker = self._install_snapshot_worker(window)
        window._cached_snapshot = {"version": 9, "queue_items": [{"id": "new"}]}
        window._frontend_section_signatures = {"queue_items": "new"}

        MainWindow._render_frontend_state(window)

        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"version": 8, "queue_items": [{"id": "old"}]},
                changed_sections=None,
                signatures={"queue_items": "old"},
            ),
        )

        self.assertEqual(window._cached_snapshot, {"version": 9, "queue_items": [{"id": "new"}]})
        self.assertEqual(window._frontend_section_signatures, {"queue_items": "new"})

    def test_stale_partial_frontend_snapshot_does_not_seed_empty_cache(self):
        window = self._make_window()
        window.app_shell = Mock()
        window._frontend_state_service = Mock()
        worker = self._install_snapshot_worker(window)

        MainWindow._render_frontend_state(window, topics={"videos.update"})
        MainWindow._render_frontend_state(window, topics={"videos.update"})

        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"version": 3, "active_downloads": [], "app_status": {}},
                changed_sections={"active_downloads", "app_status"},
            ),
        )

        self.assertNotIn("_cached_snapshot", window.__dict__)
        window.app_shell.render.assert_not_called()

    def test_frontend_slow_render_warning_is_rate_limited(self):
        window = self._make_window()
        window._ui_update_scheduler = Mock()
        window._ui_update_scheduler.metrics.return_value = {"interval_ms": MainWindow.FRONTEND_REFRESH_INTERVAL_MS}

        with patch("app.ui.main_window.time.monotonic", side_effect=[100.0, 100.1, 111.0]), patch(
            "app.ui.main_window.debug_logger.log"
        ) as log:
            MainWindow._record_frontend_render_duration(window, MainWindow.FRONTEND_RENDER_WARN_MS + 1)
            MainWindow._record_frontend_render_duration(window, MainWindow.FRONTEND_RENDER_WARN_MS + 2)
            MainWindow._record_frontend_render_duration(window, MainWindow.FRONTEND_RENDER_WARN_MS + 3)

        self.assertEqual(log.call_count, 2)
        self.assertEqual(window._last_frontend_render_warn_ms, 111000)

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
        worker = self._install_snapshot_worker(window)

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
        window._frontend_state_service.get_snapshot.assert_not_called()
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(worker.requests[0].sections, expected_sections)
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"active_downloads": [], "log_items": [], "app_status": {}},
                changed_sections={"active_downloads", "log_items", "app_status"},
            ),
        )
        window.app_shell.render.assert_called_once_with(
            {"active_downloads": [], "log_items": [], "app_status": {}},
            changed_sections={"active_downloads", "log_items", "app_status"},
        )

    def test_frontend_refresh_skips_render_when_requested_sections_are_unchanged(self):
        window = self._make_window()
        window.app_shell = Mock()
        window.app_shell.current_page_id = "failed"
        window._frontend_state_service = Mock()
        snapshot = {
            "failed_items": [{"id": "f1", "title": "失败任务", "reason": "network"}],
            "app_status": {"failed_count": 1},
        }
        window._frontend_state_service.get_snapshot.return_value = dict(snapshot)
        worker = self._install_snapshot_worker(window)

        MainWindow._render_frontend_state(window, topics={"page.visible.failed"})
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[-1],
                snapshot,
                changed_sections={"failed_items", "app_status"},
                signatures={"failed_items": "a", "app_status": "b"},
            ),
        )
        MainWindow._render_frontend_state(window, topics={"task_error"})
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[-1],
                snapshot,
                changed_sections=set(),
                skip_render=True,
                signatures={"failed_items": "a", "app_status": "b"},
            ),
        )

        window.app_shell.render.assert_called_once_with(
            snapshot,
            changed_sections={"failed_items", "app_status"},
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
        worker = self._install_snapshot_worker(window)
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
        window._frontend_state_service.get_snapshot.assert_not_called()
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(worker.requests[0].sections, expected_sections)
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"active_downloads": [], "log_items": [], "app_status": {}},
                changed_sections={"active_downloads", "log_items", "app_status"},
            ),
        )
        window.app_shell.render.assert_called_once()

    def test_settings_update_topic_refreshes_download_options_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"settings.update"})

        self.assertEqual(sections, frozenset({"settings_snapshot", "settings_contract", "download_options", "app_status"}))

    def test_platform_auth_topic_refreshes_settings_sections(self):
        sections = MainWindow._sections_for_topics(self._make_window(), {"settings.platform_auth"})

        self.assertEqual(sections, frozenset({"settings_snapshot", "settings_contract"}))


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
        worker = self._install_snapshot_worker(window)

        MainWindow._render_frontend_state(window, topics={"videos.terminal"})

        service.get_delta.assert_not_called()
        service.get_snapshot.assert_not_called()
        self.assertEqual(worker.requests[0].sections, frozenset({"active_downloads", "app_status"}))
        self.assertTrue(worker.requests[0].use_delta)
        self.assertEqual(worker.requests[0].base_version, 1)
        MainWindow._on_frontend_snapshot_finished(
            window,
            self._snapshot_result(
                worker.requests[0],
                {"active_downloads": [], "app_status": {}, "version": 2},
                changed_sections={"active_downloads", "app_status"},
            ),
        )
        window.app_shell.render.assert_called_once()

    def test_cached_progress_event_builds_worker_delta_without_snapshot_fetch(self):
        class FakeScheduler:
            def __init__(self):
                self.calls: list[str] = []

            def schedule(self, topic):
                self.calls.append(topic)

        class FakeService:
            def __init__(self):
                self.delta_calls: list[dict] = []
                self.snapshot_calls: list[dict] = []

            def get_delta(self, since_version=0, sections=None):
                self.delta_calls.append({"since_version": since_version, "sections": sections})
                return {
                    "version": 6,
                    "base_version": since_version,
                    "full": False,
                    "changed_sections": ["active_downloads", "app_status"],
                    "sections": {
                        "active_downloads": [{"id": "v1", "progress": 42}],
                        "app_status": {"active_count": 1},
                    },
                }

            def get_snapshot(self, *, mock=False, sections=None):
                self.snapshot_calls.append({"mock": mock, "sections": sections})
                return {"version": 99, "active_downloads": [{"id": "fallback"}]}

        window = self._make_window()
        window.app_shell = Mock()
        window.app_shell.current_page_id = "active"
        window.app_shell.render = Mock()
        service = FakeService()
        window._frontend_state_service = service
        window._ui_update_scheduler = FakeScheduler()
        window._frontend_refresh_pending_mock = False
        window._cached_snapshot = {
            "version": 5,
            "active_downloads": [{"id": "v1", "progress": 1}],
            "app_status": {"active_count": 1},
            "queue_items": [{"id": "q1"}],
        }
        worker = self._install_snapshot_worker(window)

        MainWindow._on_app_state_changed(
            window,
            {"topic": "videos.update", "video_id": "v1", "status": "downloading", "progress": 42},
        )
        MainWindow._flush_frontend_state(window)

        self.assertEqual(window._ui_update_scheduler.calls, ["frontend"])
        self.assertEqual(len(worker.requests), 1)
        request = worker.requests[0]
        self.assertTrue(request.use_delta)
        self.assertEqual(request.base_version, 5)
        self.assertEqual(request.sections, frozenset({"active_downloads", "app_status"}))

        result = build_frontend_snapshot(request)

        self.assertEqual(
            service.delta_calls,
            [{"since_version": 5, "sections": frozenset({"active_downloads", "app_status"})}],
        )
        self.assertEqual(service.snapshot_calls, [])
        self.assertEqual(result.snapshot["queue_items"], [{"id": "q1"}])
        self.assertEqual(result.snapshot["active_downloads"], [{"id": "v1", "progress": 42}])
        self.assertEqual(result.changed_sections, {"active_downloads", "app_status"})

        MainWindow._on_frontend_snapshot_finished(window, result)

        window.app_shell.render.assert_called_once_with(
            result.snapshot,
            changed_sections={"active_downloads", "app_status"},
        )

    def test_update_basic_setting_updates_current_directory_and_refreshes(self):
        window = self._make_window()
        window.sig_change_dir = Mock()
        window.refresh_frontend_state = Mock()
        window.is_dark_theme = False
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        def _get_dir(obj):
            return obj.__dict__.get("_test_current_save_dir", "")

        def _set_dir(obj, value):
            obj.__dict__["_test_current_save_dir"] = value

        with patch.object(MainWindow, "current_save_dir", new=property(_get_dir, _set_dir)):
            window.current_save_dir = "D:/old"
            MainWindow._update_basic_setting(window, "common", "download_directory", '"D:/Videos/Downloads/file.mp4"')

            window._frontend_state_service.handle_action.assert_not_called()
            request = window._frontend_action_worker.requests[0]
            self.assertEqual(request.action, "update_basic_setting")
            self.assertEqual(request.payload, {"key": "download_directory", "value": '"D:/Videos/Downloads/file.mp4"'})
            window.refresh_frontend_state.assert_not_called()

            MainWindow._on_frontend_action_finished(
                window,
                FrontendActionResult(
                    sequence=request.sequence,
                    service_token=id(window._frontend_state_service),
                    action="update_basic_setting",
                    payload=dict(request.payload),
                    result={
                        "status": "ok",
                        "data": {
                            "section": "common",
                            "config_key": "save_directory",
                            "directory": "D:\\Videos\\Downloads",
                            "value": "D:\\Videos\\Downloads",
                        },
                    },
                ),
            )

            self.assertEqual(window.current_save_dir, "D:\\Videos\\Downloads")

        window.sig_change_dir.emit.assert_called_once()
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_setting_applies_playback_runtime_hook(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window.app_shell = SimpleNamespace(apply_playback_settings=Mock())
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        MainWindow._update_basic_setting(window, "playback", "autoplay_next", False)

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_setting")
        self.assertEqual(request.payload, {"key": "autoplay_next", "value": False, "section": "playback"})

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="update_setting",
                payload=dict(request.payload),
                result={"status": "ok", "data": {"section": "playback", "key": "autoplay_next", "value": False}},
            ),
        )
        window.app_shell.apply_playback_settings.assert_called_once()
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_setting_refreshes_logs_for_logging_runtime_hook(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        MainWindow._update_basic_setting(window, "logging", "retention_days", 3)

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_setting")
        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="update_setting",
                payload=dict(request.payload),
                result={"status": "ok", "data": {"section": "logging", "key": "retention_days", "value": 3}},
            ),
        )

        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update", "logs.append"})

    def test_log_refresh_action_coalesces_without_writing_a_new_log(self):
        window = self._make_window()
        window._pending_refresh_topics = set()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = Mock()
        window._frontend_action_sequence = 0
        window._ui_update_scheduler = Mock()

        MainWindow._handle_log_action(window, "refresh")

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.submit.call_args.args[0]
        self.assertIsInstance(request, FrontendActionRequest)
        self.assertEqual(request.action, "log_operation")
        self.assertEqual(request.payload, {"operation": "refresh"})
        window.append_log.assert_not_called()
        self.assertEqual(window._pending_refresh_topics, set())
        window._ui_update_scheduler.schedule.assert_not_called()

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="log_operation",
                payload={"operation": "refresh"},
                result={"status": "ok", "message": "日志缓存已刷新"},
            ),
        )

        window.append_log.assert_not_called()
        self.assertEqual(window._pending_refresh_topics, {"logs.append"})
        window._ui_update_scheduler.schedule.assert_called_once_with("logs.append", force=False)

    def test_log_file_open_actions_run_through_action_worker(self):
        for operation in ("open_latest", "open_error_summary"):
            with self.subTest(operation=operation):
                window = self._make_window()
                window._frontend_state_service = Mock()
                window._frontend_action_worker = self.CapturingActionWorker()
                window._frontend_action_sequence = 0
                window.sig_open_latest_log = Mock()
                window.sig_open_error_summary = Mock()

                MainWindow._handle_log_action(window, operation)

                window._frontend_state_service.handle_action.assert_not_called()
                request = window._frontend_action_worker.requests[0]
                self.assertIsInstance(request, FrontendActionRequest)
                self.assertEqual(request.action, "log_operation")
                self.assertEqual(request.payload, {"operation": operation})
                window.sig_open_latest_log.emit.assert_not_called()
                window.sig_open_error_summary.emit.assert_not_called()

    def test_log_refresh_action_throttles_rapid_repeated_clicks(self):
        window = self._make_window()
        window._pending_refresh_topics = set()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = Mock()
        window._frontend_action_sequence = 0
        window._ui_update_scheduler = Mock()

        with patch("app.ui.main_window.time.monotonic", side_effect=[100.0, 100.1]):
            MainWindow._handle_log_action(window, "refresh")
            MainWindow._handle_log_action(window, "refresh")

        window._frontend_state_service.handle_action.assert_not_called()
        window._frontend_action_worker.submit.assert_called_once()
        request = window._frontend_action_worker.submit.call_args.args[0]
        self.assertEqual(request.action, "log_operation")
        self.assertEqual(request.payload, {"operation": "refresh"})
        window.append_log.assert_not_called()
        self.assertEqual(window._pending_refresh_topics, {"logs.append"})
        window._ui_update_scheduler.schedule.assert_called_once_with("logs.append", force=False)

    def test_log_action_result_appends_non_refresh_feedback_and_refreshes_logs(self):
        window = self._make_window()
        window._pending_refresh_topics = set()
        window._frontend_state_service = Mock()
        window._ui_update_scheduler = Mock()

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=1,
                service_token=id(window._frontend_state_service),
                action="log_operation",
                payload={"operation": "export"},
                result={"status": "ok", "message": "日志已导出"},
            ),
        )

        window.append_log.assert_called_once_with("日志已导出")
        self.assertEqual(window._pending_refresh_topics, {"logs.append"})
        window._ui_update_scheduler.schedule.assert_called_once_with("logs.append", force=False)

    def test_settings_theme_update_runs_through_action_worker(self):
        window = self._make_window()
        window.refresh_frontend_state = Mock()
        window.is_dark_theme = False
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0
        window._apply_runtime_setting_after_update = Mock(return_value=set())

        MainWindow._update_basic_setting(window, "common", "theme", "dark")

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_basic_setting")
        self.assertEqual(request.payload, {"key": "theme", "value": "dark"})

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="update_basic_setting",
                payload=dict(request.payload),
                result={"status": "ok", "data": {"section": "common", "key": "theme", "value": "dark"}},
            ),
        )
        window.sig_theme_changed.emit.assert_called_once_with(True)
        window._apply_runtime_setting_after_update.assert_called_once_with("common", "theme", "dark")
        window.refresh_frontend_state.assert_called_once_with(topics={"settings.update"})

    def test_update_download_options_refreshes_effective_options_immediately(self):
        window = self._make_window()
        window._cached_snapshot = {"version": 1, "download_options": {"max_concurrent": 3}}
        window._frontend_state_service = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0
        window._render_frontend_state = Mock()
        window.refresh_frontend_state = Mock()

        MainWindow._update_download_options(window, {"max_concurrent": 6})

        window._frontend_state_service.handle_action.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_download_options")
        self.assertEqual(request.payload, {"max_concurrent": 6})
        window._render_frontend_state.assert_not_called()

        MainWindow._on_frontend_action_finished(
            window,
            FrontendActionResult(
                sequence=request.sequence,
                service_token=id(window._frontend_state_service),
                action="update_download_options",
                payload=dict(request.payload),
                result={"status": "ok", "data": {"auto_retry": True, "max_retries": 3, "max_concurrent": 5}},
            ),
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
        controller = MainWindow._chrome_controller(window)
        controller.frameless_resize_margins = Mock(return_value=(8, 14))

        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(100, 100)), MainWindow.HTTOPLEFT)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(599, 499)), MainWindow.HTBOTTOMRIGHT)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(320, 88)), MainWindow.HTTOP)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(320, 512)), MainWindow.HTBOTTOM)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(180, 116)), MainWindow.HTCAPTION)
        self.assertIsNone(MainWindow._frameless_hit_test(window, QPoint(250, 250)))

    def test_frameless_hit_test_exposes_native_title_button_regions(self):
        from PyQt6.QtCore import QPoint, QRect

        class FakeTitleBar:
            def __init__(self, kind):
                self.kind = kind

            def isVisible(self):
                return True

            def mapFromGlobal(self, pos):
                return QPoint(pos.x() - 100, pos.y() - 100)

            def rect(self):
                return QRect(0, 0, 500, 28)

            def chrome_button_kind_at(self, _pos):
                return self.kind

            def is_interactive_at(self, _pos):
                return self.kind is not None

        window = self._make_window()
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        controller = MainWindow._chrome_controller(window)
        controller.frameless_resize_margins = Mock(return_value=(8, 8))

        window.window_title_bar = FakeTitleBar("minimize")
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(560, 116)), MainWindow.HTMINBUTTON)
        window.window_title_bar = FakeTitleBar("maximize")
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(560, 116)), MainWindow.HTMAXBUTTON)
        window.window_title_bar = FakeTitleBar("close")
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(560, 116)), MainWindow.HTCLOSE)

    def test_frameless_hit_test_prioritizes_title_buttons_over_top_resize_border(self):
        from PyQt6.QtCore import QPoint, QRect

        class FakeTitleBar:
            def isVisible(self):
                return True

            def mapFromGlobal(self, pos):
                return QPoint(pos.x() - 100, pos.y() - 100)

            def rect(self):
                return QRect(0, 0, 500, 28)

            def chrome_button_kind_at(self, _pos):
                return "maximize"

            def is_interactive_at(self, _pos):
                return True

        window = self._make_window()
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        window.window_title_bar = FakeTitleBar()
        controller = MainWindow._chrome_controller(window)
        controller.frameless_resize_margins = Mock(return_value=(8, 14))

        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(560, 104)), MainWindow.HTMAXBUTTON)

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
        self.assertEqual(MainWindow.FRAMELESS_RESIZE_BORDER_PX, 8)

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
        self.assertEqual(roomy_minimum, QSize(1500, 760))

    def test_auto_hide_taskbar_reserves_shell_activation_edge(self):
        monitor = SimpleNamespace(left=0, top=0, right=1920, bottom=1080)
        work = SimpleNamespace(left=0, top=0, right=1920, bottom=1080)

        self.assertEqual(
            MainWindow._adjust_work_area_for_auto_hide_taskbar(monitor, work, MainWindow.ABE_BOTTOM),
            (0, 0, 1920, 1078),
        )
        self.assertEqual(
            MainWindow._adjust_work_area_for_auto_hide_taskbar(monitor, work, MainWindow.ABE_TOP),
            (0, 2, 1920, 1080),
        )
        self.assertEqual(
            MainWindow._adjust_work_area_for_auto_hide_taskbar(monitor, work, MainWindow.ABE_LEFT),
            (2, 0, 1920, 1080),
        )
        self.assertEqual(
            MainWindow._adjust_work_area_for_auto_hide_taskbar(monitor, work, MainWindow.ABE_RIGHT),
            (0, 0, 1918, 1080),
        )

    def test_nc_calc_size_reserve_adjusts_native_client_rect(self):
        rect = SimpleNamespace(left=0, top=0, right=1920, bottom=1080)
        window = self._make_window()

        MainWindow._apply_auto_hide_taskbar_reserve_to_rect(window, rect, MainWindow.ABE_BOTTOM)

        self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (0, 0, 1920, 1078))

    def test_resize_border_thickness_uses_frame_plus_padded_border(self):
        window = self._make_window()
        controller = MainWindow._chrome_controller(window)
        controller._system_metric_for_hwnd = Mock(side_effect=lambda metric, hwnd: {
            MainWindow.SM_CXSIZEFRAME: 8,
            MainWindow.SM_CYSIZEFRAME: 9,
            MainWindow.SM_CXPADDEDBORDER: 4,
        }[metric])

        self.assertEqual(MainWindow._resize_border_thickness_for_hwnd(window, 1001, horizontal=True), 12)
        self.assertEqual(MainWindow._resize_border_thickness_for_hwnd(window, 1001, horizontal=False), 13)

    def test_frameless_resize_margins_use_windows_system_metrics(self):
        window = self._make_window()
        window.winId = Mock(return_value=1001)
        controller = MainWindow._chrome_controller(window)
        controller._resize_border_thickness_for_hwnd = Mock(side_effect=lambda _hwnd, *, horizontal: 12 if horizontal else 14)

        with patch("app.ui.layout.window_chrome_controller.sys.platform", "win32"):
            self.assertEqual(MainWindow._frameless_resize_margins(window), (12, 14))

    def test_windows_native_hit_test_uses_vertical_margin_for_top_and_bottom(self):
        from PyQt6.QtCore import QPoint, QRect, Qt

        window = self._make_window()
        window.isFullScreen = Mock(return_value=False)
        window.isMaximized = Mock(return_value=False)
        window.windowState = Mock(return_value=Qt.WindowState.WindowNoState)
        window.frameGeometry = Mock(return_value=QRect(100, 100, 500, 400))
        window.window_title_bar = None
        controller = MainWindow._chrome_controller(window)
        controller.frameless_resize_margins = Mock(return_value=(8, 14))

        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(320, 113)), MainWindow.HTTOP)
        self.assertEqual(MainWindow._frameless_hit_test(window, QPoint(320, 486)), MainWindow.HTBOTTOM)
        self.assertIsNone(MainWindow._frameless_hit_test(window, QPoint(320, 115)))


    def test_win32_hit_test_prioritizes_native_caption_buttons(self):
        from types import SimpleNamespace
        from PyQt6.QtCore import QPoint

        title_bar = SimpleNamespace(
            isVisible=Mock(return_value=True),
            btn_close=object(),
            btn_maximize=object(),
            btn_minimize=object(),
        )
        window = self._make_window()
        window.window_title_bar = title_bar
        window._native_client_pos_from_lparam = Mock(return_value=QPoint(940, 14))
        window._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        window._is_effectively_maximized = Mock(return_value=False)
        window.isFullScreen = Mock(return_value=False)
        controller = MainWindow._chrome_controller(window)
        controller._native_client_pos_from_lparam = Mock(return_value=QPoint(940, 14))
        controller._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        controller.frameless_resize_margins = Mock(return_value=(12, 12))
        def rect_for(widget):
            if widget is title_bar.btn_close:
                return (962, 0, 1000, 28)
            if widget is title_bar.btn_maximize:
                return (924, 0, 962, 28)
            if widget is title_bar.btn_minimize:
                return (886, 0, 924, 28)
            if widget is title_bar:
                return (0, 0, 1000, 28)
            return None

        controller._widget_rect_client_px = Mock(side_effect=rect_for)

        self.assertEqual(MainWindow._win32_hit_test(window, SimpleNamespace(hWnd=1001, lParam=0)), MainWindow.HTMAXBUTTON)

    def test_win32_hit_test_keeps_minimize_and_close_as_qt_client_buttons(self):
        from types import SimpleNamespace
        from PyQt6.QtCore import QPoint

        title_bar = SimpleNamespace(
            isVisible=Mock(return_value=True),
            btn_close=object(),
            btn_maximize=object(),
            btn_minimize=object(),
        )
        window = self._make_window()
        window.window_title_bar = title_bar
        window._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        window._is_effectively_maximized = Mock(return_value=False)
        window.isFullScreen = Mock(return_value=False)
        controller = MainWindow._chrome_controller(window)
        controller._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        controller.frameless_resize_margins = Mock(return_value=(12, 12))

        def rect_for(widget):
            if widget is title_bar.btn_close:
                return (962, 0, 1000, 28)
            if widget is title_bar.btn_maximize:
                return (924, 0, 962, 28)
            if widget is title_bar.btn_minimize:
                return (886, 0, 924, 28)
            if widget is title_bar:
                return (0, 0, 1000, 28)
            return None

        controller._widget_rect_client_px = Mock(side_effect=rect_for)
        controller._native_client_pos_from_lparam = Mock(return_value=QPoint(900, 14))
        self.assertEqual(MainWindow._win32_hit_test(window, SimpleNamespace(hWnd=1001, lParam=0)), MainWindow.HTCLIENT)

        controller._native_client_pos_from_lparam = Mock(return_value=QPoint(980, 14))
        self.assertEqual(MainWindow._win32_hit_test(window, SimpleNamespace(hWnd=1001, lParam=0)), MainWindow.HTCLIENT)

    def test_win32_hit_test_uses_client_edges_for_native_resize(self):
        from types import SimpleNamespace
        from PyQt6.QtCore import QPoint

        window = self._make_window()
        window.window_title_bar = None
        window._native_client_pos_from_lparam = Mock(return_value=QPoint(3, 300))
        window._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        window._is_effectively_maximized = Mock(return_value=False)
        window.isFullScreen = Mock(return_value=False)
        controller = MainWindow._chrome_controller(window)
        controller._native_client_pos_from_lparam = Mock(return_value=QPoint(3, 300))
        controller._native_client_size_for_hwnd = Mock(return_value=(1000, 760))
        controller.frameless_resize_margins = Mock(return_value=(12, 12))

        self.assertEqual(MainWindow._win32_hit_test(window, SimpleNamespace(hWnd=1001, lParam=0)), MainWindow.HTLEFT)

    def test_nc_calc_size_leaves_real_fullscreen_rect_unreserved(self):
        import ctypes
        from ctypes import wintypes
        from app.ui import main_window as main_window_module

        params = main_window_module._NCCALCSIZE_PARAMS()
        params.rgrc[0] = wintypes.RECT(0, 0, 1920, 1080)
        msg = SimpleNamespace(wParam=1, lParam=ctypes.addressof(params), hWnd=1001)
        window = self._make_window()
        window._monitor_info_for_hwnd = Mock(return_value=SimpleNamespace(rcMonitor=wintypes.RECT(0, 0, 1920, 1080)))
        window._is_hwnd_maximized = Mock(return_value=True)
        window._is_effectively_maximized = Mock(return_value=True)
        window.isFullScreen = Mock(return_value=True)
        window._resize_border_thickness_for_hwnd = Mock(return_value=8)
        window._auto_hide_taskbar_edge_for_monitor = Mock(return_value=MainWindow.ABE_BOTTOM)

        result = MainWindow._handle_nc_calc_size(window, msg)

        self.assertEqual(result, 0)
        rect = params.rgrc[0]
        self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (0, 0, 1920, 1080))
        window._resize_border_thickness_for_hwnd.assert_not_called()
        window._auto_hide_taskbar_edge_for_monitor.assert_not_called()

    def test_nc_calc_size_always_hides_native_caption_without_taskbar_adjustment(self):
        import ctypes
        from ctypes import wintypes
        from app.ui import main_window as main_window_module

        params = main_window_module._NCCALCSIZE_PARAMS()
        params.rgrc[0] = wintypes.RECT(0, 0, 1920, 1080)
        msg = SimpleNamespace(wParam=1, lParam=ctypes.addressof(params), hWnd=1001)
        window = self._make_window()
        window._monitor_info_for_hwnd = Mock(return_value=SimpleNamespace(rcMonitor=wintypes.RECT(0, 0, 1920, 1080)))
        window._is_hwnd_maximized = Mock(return_value=True)
        window._is_effectively_maximized = Mock(return_value=True)
        window.isFullScreen = Mock(return_value=False)
        window._resize_border_thickness_for_hwnd = Mock(return_value=12)
        window._auto_hide_taskbar_edge_for_monitor = Mock(return_value=MainWindow.ABE_BOTTOM)

        result = MainWindow._handle_nc_calc_size(window, msg)

        self.assertEqual(result, 0)
        rect = params.rgrc[0]
        self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (0, 0, 1920, 1080))
        window._resize_border_thickness_for_hwnd.assert_not_called()
        window._auto_hide_taskbar_edge_for_monitor.assert_not_called()

    def test_constrain_window_geometry_keeps_window_inside_available_screen(self):
        from PyQt6.QtCore import QRect

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

    def test_mouse_press_on_frameless_edge_accepts_started_resize_for_qt_fallback(self):
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
        window._uses_windows_native_resize = Mock(return_value=False)
        controller = MainWindow._chrome_controller(window)
        controller._start_frameless_system_resize = Mock(return_value=True)
        event = _MouseEvent()

        MainWindow.mousePressEvent(window, event)

        event.accept.assert_called_once()
        controller._start_frameless_system_resize.assert_called_once_with(QPoint(599, 300))

    def test_mouse_press_uses_system_resize_fallback_on_windows_too(self):
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
        window._uses_windows_native_resize = Mock(return_value=True)
        controller = MainWindow._chrome_controller(window)
        controller._start_frameless_system_resize = Mock(return_value=True)
        event = _MouseEvent()

        MainWindow.mousePressEvent(window, event)

        event.accept.assert_called_once()
        controller._start_frameless_system_resize.assert_called_once_with(QPoint(599, 300))

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

    def test_maximize_uses_native_state_for_taskbar_auto_hide_compatibility(self):
        from PyQt6.QtCore import QRect

        window = self._make_window()
        window._qt_initialized = True
        window._custom_maximized = False
        normal_geometry = QRect(10, 20, 900, 600)
        window.geometry = Mock(return_value=normal_geometry)
        window.setGeometry = Mock()
        window.isMaximized = Mock(return_value=False)
        window.isFullScreen = Mock(return_value=False)
        window.showMaximized = Mock()
        window.showNormal = Mock()
        window._safe_is_native_maximized = Mock(return_value=False)
        window._apply_native_maximized_state = Mock()

        MainWindow._maximize_to_work_area(window)

        self.assertFalse(window._custom_maximized)
        self.assertEqual(window._pre_custom_maximize_geometry, normal_geometry)
        window._apply_native_maximized_state.assert_called_once_with(True)
        window.showMaximized.assert_not_called()
        window.setGeometry.assert_not_called()

        window._safe_is_native_maximized.return_value = True
        MainWindow._restore_from_custom_or_native_maximized(window)

        window._apply_native_maximized_state.assert_called_with(False)
        window.showNormal.assert_not_called()
        self.assertFalse(window._custom_maximized)
        self.assertIsNone(window._pre_custom_maximize_geometry)
        window.setGeometry.assert_not_called()

    def test_stale_maximize_request_flag_does_not_drive_effective_state(self):
        window = self._make_window()
        window._custom_maximized = False
        window._native_maximize_requested = True
        window._safe_is_native_maximized = Mock(return_value=False)

        self.assertFalse(MainWindow._is_effectively_maximized(window))

    def test_windows_is_zoomed_false_overrides_stale_qt_maximized_state(self):
        window = self._make_window()
        window._custom_maximized = False
        window._windows_hwnd_is_zoomed = Mock(return_value=False)
        window._qt_reports_native_maximized = Mock(return_value=True)

        self.assertFalse(MainWindow._is_effectively_maximized(window))
        window._qt_reports_native_maximized.assert_not_called()

    def test_toggle_maximized_uses_native_action_from_real_state(self):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window._safe_is_fullscreen = Mock(return_value=False)
        window._is_effectively_maximized = Mock(return_value=False)
        window._apply_native_maximized_state = Mock()
        window._set_window_title_bar_maximized = Mock()

        with patch("app.ui.main_window.QTimer.singleShot") as single_shot:
            MainWindow._toggle_maximized(window)

        self.assertTrue(window._native_maximize_requested)
        window._apply_native_maximized_state.assert_called_once_with(True)
        window._set_window_title_bar_maximized.assert_called_once_with(True)
        self.assertEqual(single_shot.call_count, 2)

    def test_toggle_restore_uses_native_action_from_real_state(self):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window._safe_is_fullscreen = Mock(return_value=False)
        window._is_effectively_maximized = Mock(return_value=True)
        window._apply_native_maximized_state = Mock()
        window._set_window_title_bar_maximized = Mock()

        with patch("app.ui.main_window.QTimer.singleShot"):
            MainWindow._toggle_maximized(window)

        self.assertFalse(window._native_maximize_requested)
        window._apply_native_maximized_state.assert_called_once_with(False)
        window._set_window_title_bar_maximized.assert_called_once_with(False)

    def test_apply_native_maximized_state_uses_windows_show_window_controller(self):
        window = self._make_window()
        controller = Mock()
        controller.set_hwnd_maximized.return_value = True
        window._chrome_controller = Mock(return_value=controller)
        window.winId = Mock(return_value=1001)
        window.showMaximized = Mock()
        window.showNormal = Mock()

        with patch("app.ui.main_window.sys.platform", "win32"):
            MainWindow._apply_native_maximized_state(window, True)

        controller.set_hwnd_maximized.assert_called_once_with(1001, True)
        window.showMaximized.assert_not_called()
        window.showNormal.assert_not_called()

    def test_apply_native_maximized_state_falls_back_to_qt_when_native_action_fails(self):
        window = self._make_window()
        controller = Mock()
        controller.set_hwnd_maximized.return_value = False
        window._chrome_controller = Mock(return_value=controller)
        window.winId = Mock(return_value=1001)
        window.showMaximized = Mock()
        window.showNormal = Mock()

        with patch("app.ui.main_window.sys.platform", "win32"):
            MainWindow._apply_native_maximized_state(window, True)

        window.showMaximized.assert_called_once()
        window.showNormal.assert_not_called()

    def test_windows_is_zoomed_keeps_titlebar_restore_state(self):
        window = self._make_window()
        window._custom_maximized = False
        window._native_maximize_requested = False
        window._windows_hwnd_is_zoomed = Mock(return_value=True)
        window._qt_reports_native_maximized = Mock(return_value=False)
        window.window_title_bar = Mock()

        MainWindow._sync_chrome_maximized_state(window)

        self.assertTrue(window._native_maximize_requested)
        window.window_title_bar.set_maximized.assert_called_once_with(True)

    @patch("app.ui.main_window.cfg.save_ui_state")
    def test_close_event_never_persists_legacy_main_fullscreen_state(self, mock_save_ui_state):
        window = self._make_window()
        window._connections = Mock()
        window._remove_frameless_resize_event_filter = Mock()
        window._remove_windows_native_frame_filter = Mock()
        window.cleanup_media = Mock()
        window._ui_update_scheduler = Mock()
        window.event_bus = Mock()
        window._app_state_handler = object()
        window.saveGeometry = Mock(return_value=b"geometry")
        window.saveState = Mock(return_value=b"state")
        window.is_fullscreen_mode = True
        window._update_check_worker = self.CapturingUpdateCheckWorker()
        event = Mock()

        MainWindow.closeEvent(window, event)

        window._remove_frameless_resize_event_filter.assert_called_once()
        window._remove_windows_native_frame_filter.assert_called_once()
        self.assertTrue(window._update_check_worker.shutdown_called)
        self.assertFalse(mock_save_ui_state.call_args.kwargs["is_fs"])
        event.accept.assert_called_once()

    def test_native_event_unhandled_returns_false_without_super_call(self):
        window = self._make_window()
        window._handle_frameless_native_event = Mock(return_value=None)

        handled, result = MainWindow.nativeEvent(window, "windows_generic_MSG", object())

        self.assertFalse(handled)
        self.assertEqual(result, 0)

    def test_windows_native_resize_does_not_install_qt_resize_event_filter(self):
        window = self._make_window()
        window._uses_windows_native_resize = Mock(return_value=True)

        with patch("app.ui.main_window.QApplication.instance") as app_instance:
            MainWindow._install_frameless_resize_event_filter(window)

        app_instance.assert_not_called()
        self.assertFalse(window.__dict__.get("_frameless_resize_event_filter_installed", False))

    def test_windows_native_frame_filter_installs_application_filter(self):
        window = self._make_window()
        window.winId = Mock(return_value=1001)
        app = Mock()
        controller = MainWindow._chrome_controller(window)

        with patch("app.ui.layout.window_chrome_controller.sys.platform", "win32"), patch(
            "app.ui.layout.window_chrome_controller.QApplication.instance",
            return_value=app,
        ):
            MainWindow._install_windows_native_frame_filter(window)

        app.installNativeEventFilter.assert_called_once()
        self.assertEqual(controller._windows_hwnd, 1001)
        self.assertTrue(controller._windows_native_frame_filter_installed)
        self.assertIsNotNone(controller._windows_native_frame_filter)

    def test_windows_native_frame_filter_delegates_to_window_handler(self):
        from app.ui.layout.window_chrome_controller import _ChromeNativeEventFilter

        window = self._make_window()
        controller = MainWindow._chrome_controller(window)
        controller.handle_native_event = Mock(return_value=MainWindow.HTMAXBUTTON)
        native_filter = _ChromeNativeEventFilter(controller)

        handled, result = native_filter.nativeEventFilter("windows_generic_MSG", object())

        self.assertTrue(handled)
        self.assertEqual(result, MainWindow.HTMAXBUTTON)

    def test_chrome_controller_prefers_windows_is_zoomed_over_qt_state(self):
        from PyQt6.QtCore import Qt
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController

        host = Mock()
        host.winId.return_value = 1001
        host.windowState.return_value = Qt.WindowState.WindowMaximized
        host.isMaximized.return_value = True
        controller = FramelessWindowChromeController(host, title_bar_getter=lambda: None)
        controller._is_hwnd_maximized = Mock(return_value=False)

        with patch("app.ui.layout.window_chrome_controller.sys.platform", "win32"):
            self.assertFalse(controller._is_effectively_maximized())
        controller._is_hwnd_maximized.assert_called_once_with(1001)

    def test_chrome_controller_toggle_uses_windows_show_window_without_callback(self):
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController

        host = Mock()
        host.winId.return_value = 1001
        host.showMaximized = Mock()
        host.showNormal = Mock()
        controller = FramelessWindowChromeController(host, title_bar_getter=lambda: None)
        controller._is_hwnd_maximized = Mock(return_value=False)
        controller.set_hwnd_maximized = Mock(return_value=True)

        with patch("app.ui.layout.window_chrome_controller.sys.platform", "win32"), patch(
            "app.ui.layout.window_chrome_controller.QTimer.singleShot"
        ):
            controller._toggle_maximized()

        controller.set_hwnd_maximized.assert_called_once_with(1001, True)
        host.showMaximized.assert_not_called()
        host.showNormal.assert_not_called()

    def test_fullscreen_mode_compatibility_forwards_to_media_panel(self):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window.isFullScreen = Mock(return_value=False)
        window.showFullScreen = Mock()
        window.media_panel = Mock()

        MainWindow.toggle_fullscreen_mode(window)

        window.media_panel.toggle_media_fullscreen.assert_called_once()
        window.showFullScreen.assert_not_called()

    def test_legacy_main_fullscreen_state_exits_without_entering_media_fullscreen(self):
        from PyQt6.QtCore import Qt

        window = self._make_window()
        window.is_fullscreen_mode = True
        window.isFullScreen = Mock(return_value=True)
        window.showNormal = Mock()
        window._set_shell_widgets_visible = Mock()
        window.windowState = Mock(return_value=Qt.WindowState.WindowNoState)
        window._sync_window_title_bar_state = Mock()
        window.btn_fullscreen = Mock()
        window.media_panel = Mock()

        MainWindow.toggle_fullscreen_mode(window)

        window.showNormal.assert_called_once()
        window._set_shell_widgets_visible.assert_called_once_with(True)
        window.media_panel.toggle_media_fullscreen.assert_not_called()
        self.assertFalse(window.is_fullscreen_mode)
        self.assertIsNone(window._pre_fullscreen_geometry)
        self.assertFalse(window._native_maximize_requested)
    @patch("app.ui.main_window.QTimer.singleShot")
    @patch("app.ui.main_window.apply_application_theme")
    def test_toggle_theme_persists_state_and_emits_signal(self, mock_apply_theme, mock_single_shot):
        """验证 `test_toggle_theme_persists_state_and_emits_signal` 对应场景是否符合预期，供 `MainWindowTests` 使用。"""
        window = self._make_window()
        window.is_dark_theme = True
        window._last_applied_theme_is_dark = True
        window._theme_transition_in_progress = False
        window._queued_theme_is_dark = None
        window._theme_transition_target_is_dark = None
        window._theme_transition_sequence = 0
        window.top_bar = Mock()
        window.setPalette = Mock()
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window.refresh_frontend_state = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        window.toggle_theme()

        self.assertTrue(window.is_dark_theme)
        mock_single_shot.assert_called_once()
        self.assertEqual(mock_single_shot.call_args.args[0], 0)
        mock_apply_theme.assert_not_called()
        window.top_bar.set_theme_button_busy.assert_called_once_with(True)
        window.top_bar.set_theme_preview_icon.assert_not_called()
        window.top_bar.set_theme_icon.assert_not_called()
        window.sig_theme_changed.emit.assert_not_called()
        self.assertEqual(window._frontend_action_worker.requests, [])

        mock_single_shot.call_args.args[1]()

        self.assertFalse(window.is_dark_theme)
        mock_apply_theme.assert_called_once_with(False)
        window.top_bar.set_theme_icon.assert_not_called()
        window.top_bar.set_theme_preview_icon.assert_called_once_with(False)
        window.top_bar.set_theme_button_busy.assert_any_call(False)
        window.sig_theme_changed.emit.assert_called_once_with(False)
        window._frontend_state_service.handle_action.assert_not_called()
        window.refresh_frontend_state.assert_not_called()
        request = window._frontend_action_worker.requests[0]
        self.assertEqual(request.action, "update_basic_setting")
        self.assertEqual(
            request.payload,
            {
                "key": "theme",
                "value": "light",
                "source": "theme_toggle",
                "ui_applied": True,
                "theme_sequence": 1,
            },
        )

    @patch("app.ui.main_window.QTimer.singleShot")
    @patch("app.ui.main_window.apply_application_theme")
    def test_theme_toggle_coalesces_rapid_clicks_to_latest_state(self, mock_apply_theme, mock_single_shot):
        window = self._make_window()
        window.is_dark_theme = True
        window._last_applied_theme_is_dark = True
        window._theme_transition_in_progress = False
        window._queued_theme_is_dark = None
        window._theme_transition_target_is_dark = None
        window._theme_transition_sequence = 0
        window.top_bar = Mock()
        window.setPalette = Mock()
        window.sig_theme_changed = Mock()
        window._frontend_state_service = Mock()
        window.refresh_frontend_state = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        window.toggle_theme()
        window.toggle_theme()
        window.toggle_theme()

        self.assertTrue(window.is_dark_theme)
        mock_single_shot.assert_called_once()
        mock_apply_theme.assert_not_called()
        self.assertEqual(window._frontend_action_worker.requests, [])
        window.top_bar.set_theme_icon.assert_not_called()

        mock_single_shot.call_args.args[1]()

        self.assertFalse(window.is_dark_theme)
        mock_apply_theme.assert_called_once_with(False)
        window.top_bar.set_theme_icon.assert_not_called()
        window.top_bar.set_theme_preview_icon.assert_called_once_with(False)
        self.assertEqual(len(window._frontend_action_worker.requests), 1)
        self.assertEqual(
            window._frontend_action_worker.requests[0].payload,
            {
                "key": "theme",
                "value": "light",
                "source": "theme_toggle",
                "ui_applied": True,
                "theme_sequence": 1,
            },
        )
        window.sig_theme_changed.emit.assert_called_once_with(False)

    @patch("app.ui.main_window.QTimer.singleShot")
    @patch("app.ui.main_window.apply_application_theme")
    def test_theme_toggle_can_cancel_before_first_repaint(self, mock_apply_theme, mock_single_shot):
        window = self._make_window()
        window.is_dark_theme = True
        window._last_applied_theme_is_dark = True
        window._theme_transition_in_progress = False
        window._queued_theme_is_dark = None
        window._theme_transition_target_is_dark = None
        window._theme_transition_sequence = 0
        window.top_bar = Mock()
        window.sig_theme_changed = Mock()
        window._frontend_action_worker = self.CapturingActionWorker()
        window._frontend_action_sequence = 0

        window.toggle_theme()
        window.toggle_theme()
        mock_single_shot.call_args.args[1]()

        self.assertTrue(window.is_dark_theme)
        mock_apply_theme.assert_not_called()
        self.assertEqual(window._frontend_action_worker.requests, [])
        window.sig_theme_changed.emit.assert_not_called()
        window.top_bar.set_theme_preview_icon.assert_called_once_with(True)

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
        window._frontend_state_service = Mock()
        window.refresh_frontend_state = Mock()

        window._apply_theme_stylesheet()

        settings_page.sync_external_theme.assert_called_once_with(True, follow_system=False)
        window.refresh_frontend_state.assert_not_called()

    @patch("app.ui.main_window.apply_application_theme")
    def test_apply_theme_never_freezes_window_root(self, _mock_apply_theme):
        window = self._make_window()
        window.is_dark_theme = True
        window._qt_initialized = True
        window.is_fullscreen_mode = False
        window.isFullScreen = Mock(return_value=False)
        window.update = Mock()
        window._media_panel_is_fullscreen = Mock(return_value=False)
        window._debug_shell_visibility = Mock()
        window._close_transient_popups_before_theme = Mock()
        window._apply_root_background = Mock()
        window._finalize_theme_repaint = Mock()
        window.setPalette = Mock()
        window.window_root = self.FakeShellWidget(object_name="WindowRoot")
        window.window_title_bar = self.FakeShellWidget(object_name="WindowTitleBar")
        window.top_bar = Mock()
        window.app_shell = self.FakeShellWidget(object_name="AppShell")
        window.app_shell.control_island = self.FakeShellWidget(object_name="ControlIsland")
        window.app_shell.top_bar = self.FakeShellWidget(object_name="TopBar")
        window.app_shell.sidebar = self.FakeShellWidget(object_name="Sidebar")
        window.app_shell.stack = self.FakeShellWidget(object_name="PageStack")
        window.app_shell.status_island = self.FakeShellWidget(object_name="StatusIsland")
        window.app_shell.status_bar = self.FakeShellWidget(object_name="StatusBar")

        window._apply_theme_stylesheet(freeze_updates=True)

        self.assertIn(False, window.app_shell.set_updates_enabled_calls)
        self.assertNotIn(False, window.window_root.set_updates_enabled_calls)
        self.assertTrue(window.window_root.updatesEnabled())

    def test_repair_black_shell_restores_shell_chrome_widgets(self):
        window = self._make_window()
        window.is_fullscreen_mode = False
        window.isFullScreen = Mock(return_value=False)
        window._media_panel_is_fullscreen = Mock(return_value=False)
        window._debug_shell_visibility = Mock()
        shell = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="AppShell")
        shell.control_island = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="ControlIsland")
        shell.top_bar = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="TopBar")
        shell.sidebar = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="Sidebar")
        shell.stack = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="PageStack")
        shell.status_island = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="StatusIsland")
        shell.status_bar = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="StatusBar")
        window.app_shell = shell
        window.top_bar = shell.top_bar
        window.window_title_bar = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="WindowTitleBar")
        window.window_root = self.FakeShellWidget(visible=False, updates_enabled=False, object_name="WindowRoot")

        window._repair_black_shell_if_needed("unit")

        for widget in (
            window.window_title_bar,
            shell.control_island,
            shell.top_bar,
            shell.sidebar,
            shell.stack,
            shell.status_island,
            shell.status_bar,
            shell,
            window.window_root,
        ):
            self.assertTrue(widget.isVisible())
            self.assertTrue(widget.updatesEnabled())

    def test_theme_toggle_action_result_skips_redundant_runtime_refresh(self):
        window = self._make_window()
        window.is_dark_theme = False
        window._theme_transition_sequence = 3
        window._apply_runtime_setting_after_update = Mock(return_value={"settings.update"})
        window._apply_theme_stylesheet = Mock()
        window.sig_theme_changed = Mock()
        window.refresh_frontend_state = Mock()

        MainWindow._finish_setting_update(
            window,
            {
                "key": "theme",
                "value": "light",
                "source": "theme_toggle",
                "ui_applied": True,
                "theme_sequence": 3,
            },
            {"status": "ok", "data": {"section": "common", "key": "theme", "value": "light"}},
        )

        window._apply_runtime_setting_after_update.assert_not_called()
        window._apply_theme_stylesheet.assert_not_called()
        window.sig_theme_changed.emit.assert_not_called()
        window.refresh_frontend_state.assert_not_called()

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
    def test_theme_setting_echo_skips_redundant_repolish(self, mock_cfg_get):
        def fake_get(section, key, default=None):
            values = {
                ("appearance", "follow_system"): False,
                ("common", "theme"): "dark",
            }
            return values.get((section, key), default)

        mock_cfg_get.side_effect = fake_get
        window = self._make_window()
        window._applying_appearance = False
        window.is_dark_theme = True
        window._last_applied_theme_is_dark = True
        window._apply_theme_stylesheet = Mock()
        window.setPalette = Mock()
        window.top_bar = Mock()

        MainWindow._apply_appearance_runtime_settings(window, "theme")

        window._apply_theme_stylesheet.assert_not_called()
        window.setPalette.assert_not_called()
        window.top_bar.set_theme_preview_icon.assert_called_once_with(True)
        window.top_bar.set_theme_icon.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()

