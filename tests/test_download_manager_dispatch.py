"""测试模块，覆盖 `tests/test_download_manager_dispatch.py` 对应功能的行为与回归场景。"""

import queue
import threading
import unittest
from unittest.mock import Mock, patch

from app.core.download_manager import DownloadManager
from app.models import VideoItem

class FakeSignal:
    
    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `FakeSignal` 使用。"""
        self.targets = []
        self.emit = Mock()

    def connect(self, target, *_args):
        
        self.targets.append(target)

class DownloadManagerDispatchTests(unittest.TestCase):
    
    def _make_manager(self) -> DownloadManager:
        """提供 `_make_manager` 对应的内部辅助逻辑，供 `DownloadManagerDispatchTests` 使用。"""
        manager = DownloadManager.__new__(DownloadManager)
        manager.queue = queue.Queue()
        manager.workers = []
        manager._workers_lock = threading.Lock()
        manager.is_running = True
        manager.max_concurrent = 2
        manager.slot_semaphore = Mock()
        manager.task_started = Mock()
        manager.task_progress = Mock()
        manager.task_finished = Mock()
        manager.task_error = FakeSignal()
        manager._download_recovery_store = Mock()
        return manager

    def test_add_task_rejects_new_work_when_manager_is_stopped(self):
        """验证 `test_add_task_rejects_new_work_when_manager_is_stopped` 对应场景是否符合预期，供 `DownloadManagerDispatchTests` 使用。"""
        manager = self._make_manager()
        manager.is_running = False
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")

        with self.assertRaisesRegex(RuntimeError, "已停止"):
            manager.add_task(item, "downloads")

    @patch("app.core.download_manager.DownloadWorker")
    def test_dispatch_loop_creates_worker_and_connects_signals(self, mocked_worker_cls):
        """验证 `test_dispatch_loop_creates_worker_and_connects_signals` 对应场景是否符合预期，供 `DownloadManagerDispatchTests` 使用。"""
        manager = self._make_manager()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        manager.queue.put((item, "downloads"))
        manager._wait_for_dispatch_slot = Mock(return_value=True)

        worker = Mock()
        worker.video = item
        worker.sig_start = FakeSignal()
        worker.sig_progress = FakeSignal()
        worker.sig_finished = FakeSignal()
        worker.sig_error = FakeSignal()
        worker.finished = FakeSignal()

        def stop_after_start():
            
            manager.is_running = False

        worker.start.side_effect = stop_after_start
        mocked_worker_cls.return_value = worker

        manager._dispatch_loop()

        mocked_worker_cls.assert_called_once_with(item, "downloads")
        self.assertEqual(manager.workers, [worker])
        self.assertIs(worker._completion_callback.__self__, manager)
        self.assertEqual(worker._completion_callback.__func__, manager._handle_worker_completion.__func__)
        self.assertFalse(worker._slot_released)
        self.assertEqual(worker.sig_start.targets, [manager._emit_task_started])
        self.assertEqual(worker.sig_progress.targets, [manager._emit_task_progress])
        self.assertEqual(worker.sig_finished.targets[1:], [manager._emit_task_finished])
        self.assertEqual(worker.sig_error.targets[1:], [manager._emit_task_error])
        worker.sig_finished.targets[0](item.id)
        manager._download_recovery_store.delete_task.assert_called_once_with(item.id)
        worker.sig_error.targets[0](item.id, "network")
        manager._download_recovery_store.handoff_failed_task.assert_called_once_with(item.id)
        self.assertEqual(len(worker.finished.targets), 1)
        worker.start.assert_called_once()

    @patch("app.core.download_manager.DownloadWorker")
    def test_dispatch_loop_emits_task_error_when_worker_creation_fails(self, mocked_worker_cls):
        """验证 `test_dispatch_loop_emits_task_error_when_worker_creation_fails` 对应场景是否符合预期，供 `DownloadManagerDispatchTests` 使用。"""
        manager = self._make_manager()
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        manager.queue.put((item, "downloads"))
        manager._wait_for_dispatch_slot = Mock(return_value=True)

        def raise_and_stop(*_args, **_kwargs):
            
            manager.is_running = False
            raise ValueError("坏任务")

        mocked_worker_cls.side_effect = raise_and_stop

        manager._dispatch_loop()

        manager.task_error.emit.assert_called_once_with(item.id, "调度失败: 坏任务")

if __name__ == "__main__":
    unittest.main()
