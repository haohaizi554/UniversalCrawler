"""纯 Python 下载调度内核测试。"""

import queue
import threading
import unittest
from unittest.mock import Mock

from app.core.download_manager_core import DownloadManagerCore
from app.models import VideoItem


class _CallbackSignal:
    def __init__(self):
        self.targets = []

    def connect(self, target, *_args):
        self.targets.append(target)

    def emit(self, *args):
        for target in list(self.targets):
            target(*args)


class _FakeWorker:
    def __init__(self, video, save_dir):
        self.video = video
        self.save_dir = save_dir
        self.sig_start = _CallbackSignal()
        self.sig_progress = _CallbackSignal()
        self.sig_finished = _CallbackSignal()
        self.sig_error = _CallbackSignal()
        self.finished = _CallbackSignal()
        self._slot_released = False
        self._completion_callback = None
        self.stop = Mock()
        self.wait = Mock(return_value=True)
        self.deleted = False

    def start(self):
        self.sig_start.emit(self.video.id)
        self.sig_progress.emit(self.video.id, 50)
        self.sig_finished.emit(self.video.id)
        if callable(self._completion_callback):
            self._completion_callback(self, "task_finished")
        self.finished.emit()

    def deleteLater(self):
        self.deleted = True


class _CoreManager(DownloadManagerCore):
    def __init__(self):
        self.started = []
        self.progress = []
        self.finished = []
        self.errors = []
        super().__init__(max_concurrent=1)

    def _create_worker(self, video, save_dir):
        return _FakeWorker(video, save_dir)

    def _emit_task_started(self, video_id: str) -> None:
        self.started.append(video_id)

    def _emit_task_progress(self, video_id: str, progress: int) -> None:
        self.progress.append((video_id, progress))

    def _emit_task_finished(self, video_id: str) -> None:
        self.finished.append(video_id)

    def _emit_task_error(self, video_id: str, error: str) -> None:
        self.errors.append((video_id, error))

    def _on_worker_thread_finished(self, worker):
        worker.deleteLater()


class DownloadManagerCoreTests(unittest.TestCase):
    def test_dispatch_loop_runs_without_qt_adapter(self):
        manager = _CoreManager()
        manager.is_running = False
        manager.dispatcher_thread.join(timeout=2)
        manager.queue = queue.Queue()
        manager.workers = []
        manager._workers_lock = threading.Lock()
        manager.is_running = True
        manager.slot_semaphore = Mock()
        manager.slot_semaphore.acquire.return_value = True
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        manager.queue.put((item, "downloads"))

        def stop_after_release():
            manager.is_running = False

        manager.slot_semaphore.release.side_effect = stop_after_release

        manager._dispatch_loop()

        self.assertEqual(manager.started, [item.id])
        self.assertEqual(manager.progress, [(item.id, 50)])
        self.assertEqual(manager.finished, [item.id])
        self.assertEqual(manager.errors, [])
        self.assertEqual(manager.workers, [])
        manager.slot_semaphore.release.assert_called_once()

