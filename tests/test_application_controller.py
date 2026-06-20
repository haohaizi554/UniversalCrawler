"""测试模块，覆盖 `tests/test_application_controller.py` 对应功能的行为与回归场景。"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call
from unittest.mock import Mock
from unittest.mock import patch

from app.controllers.application_controller import ApplicationController
from app.exceptions import FileOperationError
from app.models import VideoItem
from app.services.file_service import ScanResult

class ApplicationControllerTests(unittest.TestCase):
    
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
        controller.window.remove_video_row.assert_called_once_with(2)
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

            controller.play_video(item.id)

            controller.window.play_video.assert_called_once_with(video_path)
            controller.window.show_image.assert_not_called()
        controller.app_state.set_current_playing_id.assert_called_once_with(item.id)

    def test_register_file_associations_skips_settings_when_defaults_are_applied(self):
        controller = self._make_controller()
        with patch.object(controller, "_current_executable_path", return_value=r"C:\App\UniversalCrawlerPro.exe"), \
             patch("app.services.windows_file_association_service.WindowsFileAssociationService") as service_cls:
            service = service_cls.return_value
            service.register_current_user.return_value = SimpleNamespace(registered=True, message="")
            service.set_current_user_defaults.return_value = SimpleNamespace(
                applied=True,
                defaulted_extensions=(".mp4",),
                failed_extensions=(),
                message="",
            )
            service.diagnose_current_user.return_value = SimpleNamespace(
                available=True,
                pending_extensions=(),
            )
            service.open_default_apps_settings.return_value = True

            controller.on_register_file_associations(True, False)

        service.register_current_user.assert_called_once_with(
            r"C:\App\UniversalCrawlerPro.exe",
            include_video=True,
            include_image=False,
        )
        service.set_current_user_defaults.assert_called_once_with(include_video=True, include_image=False)
        service.diagnose_current_user.assert_called_once_with(include_video=True, include_image=False)
        service.open_default_apps_settings.assert_not_called()
        self.assertTrue(any(".mp4" in call_.args[0] for call_ in controller.window.append_log.call_args_list))
        self.assertTrue(
            any("默认打开方式已生效" in call_.args[0] for call_ in controller.window.append_log.call_args_list)
        )

    def test_register_file_associations_opens_settings_when_extensions_remain_pending(self):
        controller = self._make_controller()
        with patch.object(controller, "_current_executable_path", return_value=r"C:\App\UniversalCrawlerPro.exe"), \
             patch("app.services.windows_file_association_service.WindowsFileAssociationService") as service_cls:
            service = service_cls.return_value
            service.register_current_user.return_value = SimpleNamespace(registered=True, message="")
            service.set_current_user_defaults.return_value = SimpleNamespace(
                applied=False,
                defaulted_extensions=(".mp4",),
                failed_extensions=(".mkv",),
                message="",
            )
            service.diagnose_current_user.return_value = SimpleNamespace(
                available=True,
                pending_extensions=(".mkv",),
            )
            service.open_default_apps_settings.return_value = True

            controller.on_register_file_associations(True, False)

        service.open_default_apps_settings.assert_called_once_with()
        self.assertTrue(any(".mkv" in call_.args[0] for call_ in controller.window.append_log.call_args_list))

    def test_register_file_associations_rejects_empty_choice(self):
        controller = self._make_controller()

        controller.on_register_file_associations(False, False)

        controller.window.append_log.assert_called_once_with("未选择需要注册的资源类型")

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
        controller.window.append_log.assert_called_with("❌ 创建爬虫失败: boom")

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
        controller.window.append_log.assert_any_call("❌ 启动爬虫失败: thread start failed")
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

        controller.window.append_log.assert_called_once_with("📂 目录已变更: D:/downloads")
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
