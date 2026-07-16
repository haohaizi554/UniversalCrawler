"""ApplicationController 的单元行为与回归测试。"""

import os
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from app.controllers import application_controller as application_controller_module
from app.controllers.application_controller import ApplicationController
from app.core.event_bus import EventBus
from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.app_state import AppState
from app.services.file_service import ScanResult

class ApplicationControllerTests(unittest.TestCase):

    def test_background_rename_never_targets_same_id_replacement(self):
        cache_service = Mock()
        cache_service.get.return_value = "queue"
        state = AppState(event_bus=EventBus(), cache_service=cache_service)
        controller = ApplicationController.__new__(ApplicationController)
        controller.app_state = state
        controller.videos = state.videos
        controller.current_playing_id = None
        controller.host = Mock()
        controller.host.current_save_dir = "D:/media"
        controller.file_service = Mock()
        controller._should_rename_media_in_background = Mock(return_value=True)

        submitted = []

        class DeferredRunner:
            def submit(self, *, name, fn):
                submitted.append((name, fn))
                return SimpleNamespace(is_cancelled=lambda: False)

        controller._ensure_short_task_runner = Mock(return_value=DeferredRunner())
        controller._ensure_ui_callback_invoker = Mock(
            return_value=SimpleNamespace(invoke=lambda callback: callback())
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old.mp4"
            old_path.write_bytes(b"old")
            old = VideoItem(url="", title="old", source="local")
            old.local_path = str(old_path)
            replacement = VideoItem(url="", title="replacement", source="local")
            replacement.id = old.id
            replacement.local_path = str(old_path)
            state.upsert_video(old)

            table_item = Mock()
            table_item.column.return_value = 0
            table_item.data.return_value = old.id
            table_item.text.return_value = "renamed-old"
            controller.file_service.rename_media.return_value = (
                str(old_path),
                str(Path(temp_dir) / "renamed-old.mp4"),
            )

            controller.on_rename_video(table_item)
            state.upsert_video(replacement)
            submitted[0][1](SimpleNamespace(is_cancelled=lambda: False))

        controller.file_service.rename_media.assert_not_called()
        self.assertIs(state.videos[old.id], replacement)
        self.assertEqual(replacement.title, "replacement")
        controller.host.reorder_video_row.assert_not_called()
        controller.host.report_rename_error.assert_not_called()

    def test_gui_and_web_share_core_image_extension_contract(self):
        from app.core.media_filter import IMAGE_EXTENSIONS
        from app.web.controller import WebController

        self.assertIn(".avif", IMAGE_EXTENSIONS)
        self.assertEqual(ApplicationController.IMAGE_EXTENSIONS, IMAGE_EXTENSIONS)
        self.assertEqual(WebController.IMAGE_EXTENSIONS, IMAGE_EXTENSIONS)

    @staticmethod
    def _signal_double(name: str):
        return SimpleNamespace(connect=Mock(name=f"{name}.connect"))

    def _start_controller_with_doubles(self, launch_args):
        """Run the real composition root while replacing only external boundaries."""
        module = application_controller_module
        previous_excepthook = sys.excepthook
        cfg_had_event_bus = hasattr(module.cfg, "event_bus")
        previous_cfg_event_bus = getattr(module.cfg, "event_bus", None)

        self.addCleanup(setattr, sys, "excepthook", previous_excepthook)

        def _restore_cfg_event_bus() -> None:
            if cfg_had_event_bus:
                module.cfg.event_bus = previous_cfg_event_bus
            elif hasattr(module.cfg, "event_bus"):
                delattr(module.cfg, "event_bus")

        self.addCleanup(_restore_cfg_event_bus)

        app = SimpleNamespace(
            setApplicationName=Mock(name="app.setApplicationName"),
            setOrganizationName=Mock(name="app.setOrganizationName"),
            setWindowIcon=Mock(name="app.setWindowIcon"),
            aboutToQuit=self._signal_double("app.aboutToQuit"),
        )
        file_service = object()
        debug_service = object()
        spider_session = object()
        event_bus = SimpleNamespace(
            publish=Mock(name="event_bus.publish"),
            subscribe=Mock(name="event_bus.subscribe"),
            subscribe_async=Mock(name="event_bus.subscribe_async"),
        )
        cache_service = object()
        app_state = SimpleNamespace(
            event_bus=event_bus,
            cache_service=cache_service,
            videos={},
            set_current_playing_id=Mock(name="app_state.set_current_playing_id"),
        )
        window = SimpleNamespace(
            show=Mock(name="window.show"),
            set_frontend_state_service=Mock(name="window.set_frontend_state_service"),
            sig_start_crawl=self._signal_double("window.sig_start_crawl"),
            sig_stop_crawl=self._signal_double("window.sig_stop_crawl"),
            sig_change_dir=self._signal_double("window.sig_change_dir"),
            sig_play_video=self._signal_double("window.sig_play_video"),
            sig_delete_video=self._signal_double("window.sig_delete_video"),
            sig_clear_queue=self._signal_double("window.sig_clear_queue"),
            sig_copy_trace_id=self._signal_double("window.sig_copy_trace_id"),
            sig_switch_preview=self._signal_double("window.sig_switch_preview"),
            sig_auto_next_preview=self._signal_double("window.sig_auto_next_preview"),
            bind_video_rename=Mock(name="window.bind_video_rename"),
        )
        host = SimpleNamespace(current_save_dir="D:/downloads")
        spider_bridge = SimpleNamespace(sig_event=self._signal_double("spider_bridge.sig_event"))
        download_bridge = SimpleNamespace(sig_event=self._signal_double("download_bridge.sig_event"))
        download_manager = SimpleNamespace(
            task_started=self._signal_double("download_manager.task_started"),
            task_progress=self._signal_double("download_manager.task_progress"),
            task_finished=self._signal_double("download_manager.task_finished"),
            task_error=self._signal_double("download_manager.task_error"),
        )
        frontend_state_service = object()
        gui_runtime_adapter = object()
        media_release_timer = SimpleNamespace(
            setInterval=Mock(name="media_release_timer.setInterval"),
            timeout=self._signal_double("media_release_timer.timeout"),
            start=Mock(name="media_release_timer.start"),
        )
        timer_factory = Mock(name="QTimer", return_value=media_release_timer)
        timer_factory.singleShot = Mock(name="QTimer.singleShot")
        project_root = Path("D:/test-project")
        icon = object()

        with ExitStack() as stack:
            app_factory = stack.enter_context(patch.object(module, "QApplication", return_value=app))
            install_root = stack.enter_context(patch.object(module, "install_root", return_value=project_root))
            file_service_factory = stack.enter_context(
                patch.object(module, "MediaLibraryService", return_value=file_service)
            )
            debug_service_factory = stack.enter_context(
                patch.object(module, "DebugArtifactsService", return_value=debug_service)
            )
            spider_session_factory = stack.enter_context(
                patch.object(module, "SpiderSession", return_value=spider_session)
            )
            event_bus_factory = stack.enter_context(patch.object(module, "EventBus", return_value=event_bus))
            cache_service_factory = stack.enter_context(
                patch.object(module, "CacheService", return_value=cache_service)
            )
            app_state_factory = stack.enter_context(patch.object(module, "AppState", return_value=app_state))
            window_factory = stack.enter_context(patch.object(module, "MainWindow", return_value=window))
            host_factory = stack.enter_context(patch.object(module, "DesktopHostAdapter", return_value=host))
            spider_bridge_factory = stack.enter_context(
                patch.object(module, "DomainEventBridge", return_value=spider_bridge)
            )
            download_bridge_factory = stack.enter_context(
                patch.object(ApplicationController, "EVENT_BRIDGE_CLASS", return_value=download_bridge)
            )
            download_manager_factory = stack.enter_context(
                patch.object(module, "DownloadManager", return_value=download_manager)
            )
            frontend_service_factory = stack.enter_context(
                patch.object(module, "FrontendStateService", return_value=frontend_state_service)
            )
            gui_runtime_adapter_factory = stack.enter_context(
                patch.object(module, "QtGuiRuntimeAdapter", return_value=gui_runtime_adapter)
            )
            stack.enter_context(patch.object(module, "QTimer", timer_factory))
            ensure_app_id = stack.enter_context(patch.object(module, "ensure_windows_app_user_model_id"))
            load_icon = stack.enter_context(patch.object(module, "load_qt_icon", return_value=icon))
            debug_log = stack.enter_context(patch.object(module.debug_logger, "log"))
            cfg_get = stack.enter_context(patch.object(module.cfg, "get", return_value=6))

            controller = ApplicationController(launch_args)

            install_root.assert_called_once_with()
            app_factory.assert_called_once_with(module.sys.argv)
            file_service_factory.assert_called_once_with(
                ApplicationController.VIDEO_EXTENSIONS,
                ApplicationController.IMAGE_EXTENSIONS,
            )
            debug_service_factory.assert_called_once_with()
            spider_session_factory.assert_called_once_with(module.registry)
            event_bus_factory.assert_called_once_with()
            cache_service_factory.assert_called_once_with(namespace="frontend_state")
            app_state_factory.assert_called_once_with(event_bus=event_bus, cache_service=cache_service)
            self.assertIs(module.cfg.event_bus, event_bus)
            self.assertIs(controller.event_bus, event_bus)
            self.assertIs(controller.app_state, app_state)

            app.setApplicationName.assert_called_once_with("Universal Crawler Pro")
            app.setOrganizationName.assert_called_once_with("UCP")
            ensure_app_id.assert_called_once_with(module.MAIN_APP_USER_MODEL_ID)
            load_icon.assert_called_once_with(["favicon.ico"], fallback_names=["Web.ico"])
            app.setWindowIcon.assert_called_once_with(icon)

            window_factory.assert_called_once_with(app_state=app_state, event_bus=event_bus)
            window.show.assert_called_once_with()
            host_factory.assert_called_once_with(window)
            app.aboutToQuit.connect.assert_called_once_with(controller.shutdown)

            spider_bridge_factory.assert_called_once_with()
            download_bridge_factory.assert_called_once_with()
            self.assertEqual(spider_bridge.sig_event.connect.call_count, 1)
            self.assertEqual(download_bridge.sig_event.connect.call_count, 1)
            self.assertEqual(
                spider_bridge.sig_event.connect.call_args.args[1],
                module.Qt.ConnectionType.QueuedConnection,
            )
            self.assertEqual(
                download_bridge.sig_event.connect.call_args.args[1],
                module.Qt.ConnectionType.QueuedConnection,
            )
            self.assertEqual(
                [call_.args[0] for call_ in event_bus.subscribe_async.call_args_list],
                ["spider.domain_event", "download.domain_event"],
            )
            self.assertEqual(
                [call_.args[1] for call_ in event_bus.subscribe_async.call_args_list],
                [controller._spider_domain_event_handler, controller._download_domain_event_handler],
            )
            event_bus.subscribe.assert_not_called()

            app_state.set_current_playing_id.assert_called_once_with(None)
            self.assertIs(controller.videos, app_state.videos)
            self.assertIsNone(controller.current_spider)
            timer_factory.assert_called_once_with()
            media_release_timer.setInterval.assert_called_once_with(
                ApplicationController.MEDIA_RELEASE_POLL_INTERVAL_MS
            )
            media_release_timer.timeout.connect.assert_called_once_with(
                controller._poll_external_media_release_requests
            )
            media_release_timer.start.assert_called_once_with()

            cfg_get.assert_called_once_with("download", "max_concurrent", 3)
            download_manager_factory.assert_called_once_with(max_concurrent=6)
            frontend_service_factory.assert_called_once_with(
                controller,
                app_state=app_state,
                cache_service=cache_service,
                gui_runtime_adapter=gui_runtime_adapter,
            )
            gui_runtime_adapter_factory.assert_called_once_with()
            window.set_frontend_state_service.assert_called_once_with(frontend_state_service)

            for signal_name, handler_name in (
                ("task_started", "_emit_task_started_event"),
                ("task_progress", "_emit_task_progress_event"),
                ("task_finished", "_emit_task_finished_event"),
                ("task_error", "_emit_task_error_event"),
            ):
                getattr(download_manager, signal_name).connect.assert_called_once_with(
                    getattr(controller, handler_name)
                )

            for signal_name, handler_name in (
                ("sig_start_crawl", "on_start_crawl"),
                ("sig_stop_crawl", "on_stop_crawl"),
                ("sig_change_dir", "on_dir_changed"),
                ("sig_play_video", "play_video"),
                ("sig_delete_video", "on_delete_video"),
                ("sig_clear_queue", "on_clear_queue"),
                ("sig_copy_trace_id", "copy_trace_id_for_video"),
                ("sig_switch_preview", "switch_preview"),
                ("sig_auto_next_preview", "autoplay_next_preview"),
            ):
                getattr(window, signal_name).connect.assert_called_once_with(
                    getattr(controller, handler_name)
                )
            window.bind_video_rename.assert_called_once_with(controller.on_rename_video)
            self.assertEqual(debug_log.call_count, 2)

        return SimpleNamespace(
            controller=controller,
            timer_factory=timer_factory,
            project_root=project_root,
        )
    
    def _make_controller(self) -> ApplicationController:
        """提供 `_make_controller` 对应的内部辅助逻辑，供 `ApplicationControllerTests` 使用。"""
        controller = ApplicationController.__new__(ApplicationController)
        controller.window = Mock()
        controller.file_service = Mock()
        controller.dl_manager = Mock()
        controller.debug_service = Mock()
        controller.app = Mock()
        controller.videos = {}
        controller.current_playing_id = None
        controller.app_state = Mock()
        controller.app_state.videos = controller.videos
        controller.app_state._lock = threading.RLock()
        controller.app_state.upsert_video.side_effect = lambda item: controller.videos.__setitem__(item.id, item)
        controller.app_state.clear_videos.side_effect = lambda: controller.videos.clear()
        controller.app_state.snapshot_videos.side_effect = lambda: dict(controller.videos)
        controller.app_state.replace_videos.side_effect = lambda videos: (
            controller.videos.clear(),
            controller.videos.update(videos),
        )

        def _update_video_state(video_id, *, status=None, progress=None):
            item = controller.videos.get(video_id)
            if item is None:
                return None
            if status is not None:
                item.status = status
            if progress is not None:
                item.progress = progress
            return item

        controller.app_state.update_video_state.side_effect = _update_video_state
        controller.app_state._publish_change = Mock()
        controller.app_state.current_playing_id = None
        controller.app_state.set_current_playing_id.side_effect = lambda video_id: setattr(
            controller.app_state,
            "current_playing_id",
            video_id,
        )
        controller.current_spider = None
        return controller

    def test_init_without_launch_media_wires_runtime_and_schedules_scan(self):
        runtime = self._start_controller_with_doubles([])

        self.assertEqual(runtime.controller.project_root, runtime.project_root)
        self.assertEqual(runtime.controller.launch_media_paths, [])
        self.assertIsNone(runtime.controller._pending_launch_media_path)
        runtime.timer_factory.singleShot.assert_called_once_with(
            200,
            runtime.controller.scan_local_dir,
        )

    def test_init_with_launch_media_wires_runtime_and_schedules_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "launch.mp4"
            media_path.write_bytes(b"video")

            runtime = self._start_controller_with_doubles([str(media_path)])

        self.assertEqual(runtime.controller.launch_media_paths, [str(media_path.resolve())])
        self.assertIsNone(runtime.controller._pending_launch_media_path)
        runtime.timer_factory.singleShot.assert_called_once_with(
            800,
            runtime.controller._open_first_launch_media,
        )

    def test_collect_launch_media_paths_filters_flags_and_unsupported_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "demo.mp4")
            text_path = os.path.join(temp_dir, "notes.txt")
            with open(media_path, "wb") as handle:
                handle.write(b"video")
            with open(text_path, "w", encoding="utf-8") as handle:
                handle.write("text")

            paths = ApplicationController._collect_launch_media_paths(
                ["--mode", "gui", media_path, text_path, media_path]
            )

        self.assertEqual(paths, [str(Path(media_path).resolve())])

    def test_pending_launch_video_switches_to_completed_and_plays_in_app(self):
        controller = self._make_controller()
        controller.host = Mock()
        controller._window_media_ready = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "demo.mp4")
            Path(media_path).write_bytes(b"video")
            item = controller._video_item_for_launch_path(media_path)
            controller._store_video_item(item)
            controller._pending_launch_media_path = media_path

            controller._play_pending_launch_media(item.id)

        controller.host.show_completed_item.assert_called_once_with(item.id)
        controller.host.play_video.assert_called_once_with(media_path)
        controller.host.show_image.assert_not_called()
        self.assertEqual(controller.app_state.current_playing_id, item.id)
        self.assertIsNone(controller._pending_launch_media_path)

    def test_pending_launch_image_switches_to_completed_and_opens_preview(self):
        controller = self._make_controller()
        controller.host = Mock()
        controller._window_media_ready = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "cover.jpg")
            Path(media_path).write_bytes(b"image")
            item = controller._video_item_for_launch_path(media_path)
            controller._store_video_item(item)
            controller._pending_launch_media_path = media_path

            controller._play_pending_launch_media(item.id)

        controller.host.show_completed_item.assert_called_once_with(item.id)
        controller.host.show_image.assert_called_once_with(media_path)
        controller.host.play_video.assert_not_called()
        self.assertEqual(controller.app_state.current_playing_id, item.id)
        self.assertIsNone(controller._pending_launch_media_path)

    def test_clear_local_items_uses_window_api(self):
        """验证 `test_clear_local_items_uses_window_api` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        item = VideoItem(url="https://example.com", title="demo", source="local")
        controller._store_video_item(item)

        controller._clear_local_items()

        controller.window.clear_video_rows.assert_called_once()
        self.assertEqual(controller.videos, {})

    def test_on_delete_video_releases_preview_and_removes_row(self):
        """删除当前播放项时必须先释放播放器 source，再执行本地删除。"""
        controller = self._make_controller()
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="local")
        item.local_path = r"C:\temp\demo.mp4"
        controller.videos[item.id] = item
        controller.app_state.current_playing_id = item.id
        controller.current_playing_id = item.id
        controller.file_service.delete_media.return_value = True
        controller.dl_manager.cancel_task.return_value = "running"

        controller.on_delete_video(2, item.id)

        controller.dl_manager.cancel_task.assert_called_once_with(item.id)
        controller.window.release_media_playback.assert_called_once()
        controller.window.stop_media_playback.assert_not_called()
        controller.window.remove_video_row.assert_called_once_with(2, item.id)
        controller.window.refresh_table_bindings.assert_called_once()
        self.assertNotIn(item.id, controller.videos)
        self.assertIsNone(controller.current_playing_id)

    def test_on_delete_video_keeps_row_when_file_delete_fails(self):
        """验证 `test_on_delete_video_keeps_row_when_file_delete_fails` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        item = VideoItem(url="https://example.com/demo.mp4", title="demo", source="local")
        item.local_path = r"C:\temp\demo.mp4"
        controller.videos[item.id] = item
        controller.app_state.current_playing_id = item.id
        controller.current_playing_id = item.id
        controller.file_service.delete_media.side_effect = FileOperationError("权限不足")
        controller.dl_manager.cancel_task.return_value = "queued"

        controller.on_delete_video(2, item.id)

        controller.window.release_media_playback.assert_called_once()
        controller.window.remove_video_row.assert_not_called()
        controller.window.refresh_table_bindings.assert_not_called()
        self.assertIn(item.id, controller.videos)
        self.assertIsNone(controller.current_playing_id)
        log_messages = [call.args[0] for call in controller.window.append_log.call_args_list]
        self.assertTrue(any("删除文件失败" in msg for msg in log_messages))

    def test_play_video_routes_images_to_image_preview(self):
        """验证 `test_play_video_routes_images_to_image_preview` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "demo.jpg")
            with open(image_path, "wb") as fp:
                fp.write(b"image")
            item = VideoItem(url="", title="image", source="local")
            item.local_path = image_path
            controller.videos[item.id] = item

            with patch("app.controllers.media_host_controller_mixin.cfg.get") as cfg_get:
                cfg_get.side_effect = lambda section, key, default=None: (
                    "builtin_player" if (section, key) == ("playback", "default_player")
                    else True if (section, key) == ("playback", "builtin_player_enabled")
                    else default
                )
                controller.play_video(item.id)

            controller.window.show_image.assert_called_once_with(image_path)
            controller.window.play_video.assert_not_called()

    def test_play_video_routes_videos_to_media_panel(self):
        """验证 `test_play_video_routes_videos_to_media_panel` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "demo.mp4")
            with open(video_path, "wb") as fp:
                fp.write(b"video")
            item = VideoItem(url="", title="video", source="local")
            item.local_path = video_path
            controller.videos[item.id] = item

            with patch("app.controllers.media_host_controller_mixin.cfg.get") as cfg_get:
                cfg_get.side_effect = lambda section, key, default=None: (
                    "builtin_player" if (section, key) == ("playback", "default_player")
                    else True if (section, key) == ("playback", "builtin_player_enabled")
                    else default
                )
                controller.play_video(item.id)

            controller.window.play_video.assert_called_once_with(video_path)
            controller.window.show_image.assert_not_called()
        controller.app_state.set_current_playing_id.assert_called_once_with(item.id)

    def test_file_association_registration_is_not_bound_to_controller_sync_slot(self):
        controller = self._make_controller()
        controller.window.sig_register_file_associations = Mock()

        controller._connect_window_signals()

        self.assertFalse(hasattr(ApplicationController, "on_register_file_associations"))
        controller.window.sig_register_file_associations.connect.assert_not_called()

    def test_on_start_crawl_rejects_duplicate_running_spider(self):
        """验证 `test_on_start_crawl_rejects_duplicate_running_spider` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.current_spider = Mock()
        controller.current_spider.isRunning.return_value = True
        controller._create_spider = Mock()

        controller.on_start_crawl("关键词", "douyin", {})

        controller.window.append_log.assert_called_once()
        controller._create_spider.assert_not_called()

    def test_create_spider_logs_and_returns_none_when_constructor_fails(self):
        """爬虫构造失败时，GUI 必须收到可见错误日志，而不是像无响应。"""
        controller = self._make_controller()
        plugin = Mock()
        spider_cls = Mock(side_effect=RuntimeError("boom"))
        plugin.get_spider_class.return_value = spider_cls

        with patch("app.controllers.application_controller.registry.get_plugin", return_value=plugin):
            returned_plugin, spider = controller._create_spider("bilibili", "BV1demo", {})

        self.assertIs(returned_plugin, plugin)
        self.assertIsNone(spider)
        controller.window.append_log.assert_called_with("❌ 创建爬虫失败: boom", trace_id=None, source="GUI", level="INFO")

    def test_on_start_crawl_resets_running_state_when_start_raises(self):
        """爬虫 start 抛错时，界面必须恢复可操作状态。"""
        controller = self._make_controller()
        controller._has_active_spider = Mock(return_value=False)
        spider = Mock()
        spider.start.side_effect = RuntimeError("thread start failed")
        controller._create_spider = Mock(return_value=(Mock(name="plugin", name_attr="Bilibili"), spider))
        controller._bind_spider_signals = Mock()
        controller._log_crawl_start = Mock()

        plugin = Mock()
        plugin.name = "Bilibili"
        controller._create_spider.return_value = (plugin, spider)

        controller.on_start_crawl("BV1demo", "bilibili", {})

        controller.window.set_crawl_running_state.assert_any_call(True)
        controller.window.set_crawl_running_state.assert_any_call(False)
        controller.window.append_log.assert_any_call("❌ 启动爬虫失败: thread start failed", trace_id=None, source="GUI", level="INFO")
        self.assertIsNone(controller.current_spider)

    def test_on_start_crawl_does_not_set_running_state_when_spider_create_fails(self):
        """spider 创建失败时，控制器不应把界面切到运行中。"""
        controller = self._make_controller()
        controller._has_active_spider = Mock(return_value=False)
        controller._create_spider = Mock(return_value=(Mock(name="plugin"), None))

        controller.on_start_crawl("BV1demo", "bilibili", {})

        controller.window.set_crawl_running_state.assert_not_called()
        self.assertIsNone(controller.current_spider)

    def test_scan_local_dir_populates_rows_and_reports_truncation(self):
        """验证 `test_scan_local_dir_populates_rows_and_reports_truncation` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "downloads"
        video = VideoItem(url="", title="video", source="local")
        image = VideoItem(url="", title="image", source="local")
        controller.file_service.scan_directory.return_value = ScanResult(
            items=[video, image],
            total_count=2,
            video_count=1,
            image_count=1,
            truncated=True,
            original_count=5,
        )

        controller.scan_local_dir()

        controller.window.clear_video_rows.assert_called_once()
        self.assertEqual(len(controller.videos), 2)
        self.assertIn(video.id, controller.videos)
        self.assertIn(image.id, controller.videos)
        log_messages = [call.args[0] for call in controller.window.append_log.call_args_list]
        self.assertTrue(any("仅加载最新的 2 个" in msg for msg in log_messages))
        self.assertTrue(any("已加载 2 个本地文件" in msg for msg in log_messages))

    def test_scan_local_dir_reports_empty_directory(self):
        """验证 `test_scan_local_dir_reports_empty_directory` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "downloads"
        controller.file_service.scan_directory.return_value = ScanResult(
            items=[],
            total_count=0,
            video_count=0,
            image_count=0,
        )

        controller.scan_local_dir()

        controller.window.add_video_row.assert_not_called()
        log_messages = [call.args[0] for call in controller.window.append_log.call_args_list]
        self.assertTrue(any("没有找到视频或图片" in msg for msg in log_messages))

    def test_on_spider_item_found_enqueues_download_and_updates_ui_state(self):
        """验证 `test_on_spider_item_found_enqueues_download_and_updates_ui_state` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "downloads"
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        controller._on_spider_item_found(item)

        self.assertEqual(item.status, "⏳ 等待中")
        self.assertEqual(item.progress, 0)
        self.assertIs(controller.videos[item.id], item)
        controller.window.add_video_row.assert_called_once_with(item)
        controller.dl_manager.add_task.assert_called_once_with(item, "downloads")

    def test_on_spider_item_found_skips_image_when_video_only_enabled(self):
        controller = self._make_controller()
        controller.dl_manager.video_only = True
        controller.window.current_save_dir = "downloads"
        item = VideoItem(url="https://example.com/cover.jpg", title="cover", source="xiaohongshu")
        item.meta["content_type"] = "image/jpeg"

        controller._on_spider_item_found(item)

        self.assertNotIn(item.id, controller.videos)
        controller.window.add_video_row.assert_not_called()
        controller.dl_manager.add_task.assert_not_called()
        controller.window.append_log.assert_called_once()


    def test_on_spider_select_tasks_resumes_spider_with_dialog_selection(self):
        """验证 `test_on_spider_select_tasks_resumes_spider_with_dialog_selection` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.current_spider = Mock()
        controller.window.show_selection_dialog.return_value = [0, 2]

        controller._on_spider_select_tasks([{"title": "A"}, {"title": "B"}])

        controller.window.show_selection_dialog.assert_called_once()
        controller.current_spider.resume_from_ui.assert_called_once_with([0, 2])

    def test_download_callbacks_update_ui_state_and_logs(self):
        """验证 `test_download_callbacks_update_ui_state_and_logs` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        controller.videos[item.id] = item

        controller._on_download_finished(item.id)
        controller._on_download_error(item.id, "网络超时")

        self.assertEqual(item.status, "❌ 失败")
        self.assertEqual(item.progress, 100)
        controller.window.update_video_status.assert_not_called()
        log_messages = [call_.args[0] for call_ in controller.window.append_log.call_args_list]
        self.assertTrue(any("下载完成" in msg for msg in log_messages))
        self.assertTrue(any("下载失败" in msg for msg in log_messages))

    def test_on_dir_changed_logs_and_rescans_directory(self):
        """验证 `test_on_dir_changed_logs_and_rescans_directory` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "D:/downloads"
        controller.scan_local_dir = Mock()

        controller.on_dir_changed()

        controller.window.append_log.assert_called_once_with("📂 目录已变更: D:/downloads", trace_id=None, source="GUI", level="INFO")
        controller.scan_local_dir.assert_called_once()

    def test_on_rename_video_resets_text_when_file_missing(self):
        """验证 `test_on_rename_video_resets_text_when_file_missing` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = r"C:\missing.mp4"
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"

        controller.on_rename_video(table_item)

        table_item.setText.assert_called_once_with("旧标题")
        controller.file_service.rename_media.assert_not_called()

    def test_on_rename_video_updates_title_path_and_tooltip_on_success(self):
        """验证 `test_on_rename_video_updates_title_path_and_tooltip_on_success` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "downloads"
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller.file_service.rename_media.return_value = ("old.mp4", os.path.join("downloads", "新标题.mp4"))

        controller.on_rename_video(table_item)

        self.assertEqual(item.title, "新标题")
        self.assertEqual(item.local_path, os.path.join("downloads", "新标题.mp4"))
        table_item.setToolTip.assert_called_once_with("新标题")

    def test_on_rename_video_releases_preview_for_current_playing_item(self):
        """当前播放项重命名前必须先释放播放器占用。"""
        controller = self._make_controller()
        controller.window.current_save_dir = "downloads"
        item = VideoItem(url="", title="旧标题", source="local")
        item.local_path = __file__
        controller.videos[item.id] = item
        controller.app_state.current_playing_id = item.id
        controller.current_playing_id = item.id
        table_item = Mock()
        table_item.column.return_value = 0
        table_item.data.return_value = item.id
        table_item.text.return_value = "新标题"
        controller.file_service.rename_media.return_value = ("old.mp4", os.path.join("downloads", "新标题.mp4"))

        controller.on_rename_video(table_item)

        controller.window.release_media_playback.assert_called_once()
        self.assertIsNone(controller.current_playing_id)

    def test_copy_trace_id_for_video_delegates_to_debug_action(self):
        """验证 `test_copy_trace_id_for_video_delegates_to_debug_action` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        item.meta["trace_id"] = "trace-123"
        controller.videos[item.id] = item
        controller._run_debug_action = Mock()

        controller.copy_trace_id_for_video(item.id)

        message, action_name, callback = controller._run_debug_action.call_args.args
        self.assertEqual(message, "📋 已复制 trace_id: trace-123")
        self.assertEqual(action_name, "复制 trace_id")
        callback()
        controller.debug_service.copy_trace_id.assert_called_once_with(
            controller.app.clipboard(),
            "trace-123",
        )

    def test_shutdown_stops_active_spider_and_download_manager(self):
        """验证 `test_shutdown_stops_active_spider_and_download_manager` 对应场景是否符合预期，供 `ApplicationControllerTests` 使用。"""
        controller = self._make_controller()
        controller.current_spider = Mock()
        controller.current_spider.isRunning.return_value = True

        controller.shutdown()

        controller.window.cleanup_media.assert_called_once()
        controller.current_spider.stop.assert_called_once()
        controller.current_spider.wait.assert_called_once_with(2000)
        controller.dl_manager.stop_all.assert_called_once()

    def test_domain_event_dispatch_uses_host_ui_queue(self):
        controller = self._make_controller()
        dispatcher = Mock()
        event = object()
        callbacks = []
        controller.host = Mock()
        controller.host._queue_on_ui.side_effect = callbacks.append

        controller._queue_domain_event_dispatch(dispatcher, event)

        controller.host._queue_on_ui.assert_called_once()
        dispatcher.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        dispatcher.assert_called_once_with(event)

    def test_cleanup_dead_spider_clears_stale_reference(self):
        controller = self._make_controller()
        dead_spider = Mock()
        dead_spider.isRunning.return_value = False
        controller.current_spider = dead_spider
        controller._active_spider_bindings = Mock()
        controller._host().finish_crawl = Mock()

        controller._cleanup_dead_spider()

        self.assertIsNone(controller.current_spider)
        controller._host().finish_crawl.assert_called_once()

if __name__ == "__main__":
    unittest.main()
