"""桌面宿主适配层测试。"""

import threading
import time
import unittest
from unittest.mock import Mock, call

from app.controllers.application_controller import ApplicationController
from app.controllers.desktop_host import DesktopHostAdapter
from app.models import VideoItem

class DesktopHostAdapterTests(unittest.TestCase):
    def test_host_adapter_delegates_window_calls(self):
        window = Mock()
        adapter = DesktopHostAdapter(window)
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        adapter.append_log("hello")
        adapter.set_crawl_running_state(True)
        adapter.add_video_row(item)
        adapter.update_video_status(item.id, "✅ 完成", 100)
        adapter.clear_video_rows()
        adapter.remove_video_row(2)
        adapter.refresh_table_bindings()
        adapter.show_selection_dialog([item])
        adapter.release_media_playback()
        adapter.cleanup_media()
        adapter.show_image("demo.jpg")
        adapter.play_video("demo.mp4")

        window.append_log.assert_called_once_with("hello", trace_id=None, source="GUI", level="INFO")
        window.set_crawl_running_state.assert_called_once_with(True)
        window.add_video_row.assert_called_once_with(item)
        window.update_video_status.assert_called_once_with(item.id, "✅ 完成", 100)
        window.clear_video_rows.assert_called_once_with()
        window.remove_video_row.assert_called_once_with(2)
        window.refresh_table_bindings.assert_called_once_with()
        window.show_selection_dialog.assert_called_once_with([item])
        window.release_media_playback.assert_called_once_with()
        window.cleanup_media.assert_called_once_with()
        window.show_image.assert_called_once_with("demo.jpg")
        window.play_video.assert_called_once_with("demo.mp4")

    def test_host_adapter_lifecycle_helpers_keep_desktop_contract(self):
        window = Mock()
        adapter = DesktopHostAdapter(window)

        adapter.notify_crawl_already_running()
        adapter.notify_unknown_source()
        adapter.notify_spider_create_failed(RuntimeError("boom"))
        adapter.begin_crawl("Bilibili")
        adapter.fail_crawl_start(RuntimeError("thread start failed"))
        adapter.finish_crawl()
        adapter.notify_crawl_stop_requested()
        adapter.announce_scan_start("downloads")
        adapter.report_scan_error(RuntimeError("scan failed"))
        adapter.announce_directory_changed("downloads")
        adapter.report_rename_error("权限不足")
        adapter.report_delete_error("文件占用")
        adapter.report_missing_media()
        adapter.announce_playback("demo")

        log_messages = [call.args[0] for call in window.append_log.call_args_list]
        self.assertIn("⚠️ 当前已有任务在运行，请先停止或等待结束", log_messages)
        self.assertIn("❌ 未知的爬虫源", log_messages)
        self.assertIn("❌ 创建爬虫失败: boom", log_messages)
        self.assertIn("🟢 启动任务 | 模式: Bilibili", log_messages)
        self.assertIn("❌ 启动爬虫失败: thread start failed", log_messages)
        self.assertIn("✅ 爬虫任务结束", log_messages)
        self.assertIn("🛑 正在停止任务...", log_messages)
        self.assertIn("📂 正在扫描目录: downloads", log_messages)
        self.assertIn("❌ 扫描目录出错: scan failed", log_messages)
        self.assertIn("📂 目录已变更: downloads", log_messages)
        self.assertIn("❌ 重命名失败: 权限不足", log_messages)
        self.assertIn("❌ 删除文件失败: 文件占用", log_messages)
        self.assertIn("❌ 文件不存在或已被删除", log_messages)
        self.assertIn("▶️ 播放: demo", log_messages)
        self.assertEqual(
            window.set_crawl_running_state.call_args_list,
            [call(True), call(False), call(False)],
        )

    def test_host_adapter_queues_void_window_calls_from_worker_thread(self):
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        window = Mock()
        adapter = DesktopHostAdapter(window)
        delivered = threading.Event()
        observed: dict[str, object] = {}

        def append_log(*args, **kwargs):
            observed["args"] = args
            observed["kwargs"] = kwargs
            observed["is_main_thread"] = QThread.currentThread() == app.thread()
            delivered.set()

        window.append_log.side_effect = append_log

        worker = threading.Thread(target=lambda: adapter.append_log("hello"), name="host-adapter-worker")
        worker.start()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertFalse(delivered.is_set())

        deadline = time.time() + 2
        while not delivered.is_set() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)

        self.assertTrue(delivered.is_set())
        self.assertEqual(observed["args"], ("hello",))
        self.assertEqual(observed["kwargs"], {"trace_id": None, "source": "GUI", "level": "INFO"})
        self.assertTrue(observed["is_main_thread"])

    def test_host_adapter_queue_on_ui_always_defers_when_qt_app_exists(self):
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        adapter = DesktopHostAdapter(Mock())
        delivered = threading.Event()

        adapter._queue_on_ui(delivered.set)

        self.assertFalse(delivered.is_set())
        deadline = time.time() + 2
        while not delivered.is_set() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)

        self.assertTrue(delivered.is_set())

    def test_application_controller_host_is_lazy_and_cached(self):
        controller = ApplicationController.__new__(ApplicationController)
        controller.window = Mock()

        host1 = controller._host()
        host2 = controller._host()

        self.assertIs(host1, host2)
        self.assertIsInstance(host1, DesktopHostAdapter)
        self.assertIs(host1.window, controller.window)

if __name__ == "__main__":
    unittest.main()
