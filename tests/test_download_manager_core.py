"""纯 Python 下载调度内核测试。"""

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.download_manager_core import DownloadManagerCore, PendingDownloadQueue
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
    """最小 worker 替身：同步触发信号，避免测试依赖真实线程调度时序。"""

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
    """测试用 DownloadManagerCore 子类，只记录事件，不接入 Qt/前端适配层。"""

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
    def test_pending_download_queue_removes_item_without_private_queue_state(self):
        pending = PendingDownloadQueue()
        first = VideoItem(url="https://example.com/1.mp4", title="first", source="douyin")
        second = VideoItem(url="https://example.com/2.mp4", title="second", source="douyin")
        third = VideoItem(url="https://example.com/3.mp4", title="third", source="douyin")
        pending.put((first, "downloads"))
        pending.put((second, "downloads"))
        pending.put((third, "downloads"))

        removed = pending.remove_video(second.id)

        self.assertIs(removed, second)
        self.assertEqual(pending.snapshot_video_ids(), {first.id, third.id})
        self.assertEqual(pending.get_nowait()[0].id, first.id)
        self.assertEqual(pending.get_nowait()[0].id, third.id)

    def test_video_only_mode_skips_image_before_queue(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager.video_only = True
        image = VideoItem(url="https://example.com/cover.jpg", title="cover", source="xiaohongshu")
        image.meta["content_type"] = "image/jpeg"

        queued = manager.add_task(image, "downloads")

        self.assertFalse(queued)
        self.assertTrue(manager.queue.empty())
        self.assertEqual(image.status, "\u5df2\u8df3\u8fc7")
        self.assertEqual(image.progress, 100)
        self.assertTrue(image.meta["skipped_by_video_only"])

    def test_startup_sweep_removes_non_hls_orphan_download_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.core.download_manager_core.cfg.get",
            return_value=temp_dir,
        ):
            # 同时覆盖 B站分流缓存和 HTTP `.downloading`，确认启动清扫不会误删成品。
            audio_temp = Path(temp_dir) / "demo_audio.m4s"
            http_temp = Path(temp_dir) / "demo.mp4.downloading"
            keep_file = Path(temp_dir) / "demo.mp4"
            for path in (audio_temp, http_temp, keep_file):
                path.write_bytes(b"test")
            manager = DownloadManagerCore.__new__(DownloadManagerCore)

            manager._sweep_m3u8_orphan_workspaces_on_startup()

            self.assertFalse(audio_temp.exists())
            self.assertFalse(http_temp.exists())
            self.assertTrue(keep_file.exists())

    def test_pending_download_queue_removes_many_items_in_one_pass(self):
        pending = PendingDownloadQueue()
        first = VideoItem(url="https://example.com/1.mp4", title="first", source="douyin")
        second = VideoItem(url="https://example.com/2.mp4", title="second", source="douyin")
        third = VideoItem(url="https://example.com/3.mp4", title="third", source="douyin")
        pending.put((first, "downloads"))
        pending.put((second, "downloads"))
        pending.put((third, "downloads"))

        removed = pending.remove_videos({first.id, third.id})

        self.assertEqual([item.id for item in removed], [first.id, third.id])
        self.assertEqual(pending.snapshot_video_ids(), {second.id})
        self.assertEqual(pending.get_nowait()[0].id, second.id)

    def test_add_tasks_batches_pending_queue_wakeup(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager.video_only = False
        manager.is_running = True
        first = VideoItem(url="https://example.com/1.mp4", title="first", source="douyin")
        second = VideoItem(url="https://example.com/2.mp4", title="second", source="douyin")

        queued = manager.add_tasks([first, second], "downloads")

        self.assertEqual(queued, 2)
        self.assertEqual(manager.queue.snapshot_video_ids(), {first.id, second.id})
        self.assertEqual(manager.queue.get_nowait()[0].id, first.id)
        self.assertEqual(manager.queue.get_nowait()[0].id, second.id)

    def test_cancel_tasks_batches_queued_and_running_items(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager._workers_lock = threading.Lock()
        manager.workers = []
        queued = VideoItem(url="https://example.com/q.mp4", title="queued", source="douyin")
        keep = VideoItem(url="https://example.com/k.mp4", title="keep", source="douyin")
        running = VideoItem(url="https://example.com/r.mp4", title="running", source="douyin")
        worker = _FakeWorker(running, "downloads")
        manager.workers = [worker]
        manager.queue.put((queued, "downloads"))
        manager.queue.put((keep, "downloads"))

        result = manager.cancel_tasks({queued.id, running.id, "missing"})

        self.assertEqual(result[queued.id], "queued")
        self.assertEqual(result[running.id], "running")
        self.assertIsNone(result["missing"])
        self.assertEqual(manager.queued_video_ids(), {keep.id})
        worker.stop.assert_called_once()
        self.assertTrue(queued.meta["user_cancel_requested"])
        self.assertTrue(running.meta["user_cancel_requested"])

    def test_cancel_task_stops_running_duplicate_even_when_same_id_is_queued(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager._workers_lock = threading.RLock()
        manager.workers = []
        queued = VideoItem(url="https://example.com/q.mp4", title="queued", source="douyin")
        running = VideoItem(url="https://example.com/r.mp4", title="running", source="douyin")
        running.id = queued.id
        worker = _FakeWorker(running, "downloads")
        manager.workers = [worker]
        manager.queue.put((queued, "downloads"))

        result = manager.cancel_task(queued.id)

        self.assertEqual(result, "running")
        self.assertTrue(queued.meta["user_cancel_requested"])
        self.assertTrue(running.meta["user_cancel_requested"])
        worker.stop.assert_called_once()

    def test_pending_work_counts_includes_dequeued_dispatching_tasks(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager._workers_lock = threading.RLock()
        manager.workers = []
        dispatching = VideoItem(url="https://example.com/d.mp4", title="dispatching", source="douyin")
        manager._dispatching_tasks = [(dispatching, "downloads")]

        active, queued = manager.pending_work_counts()

        self.assertEqual((active, queued), (1, 0))

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

    def test_dispatch_loop_releases_slot_when_worker_start_fails(self):
        class FailingWorker(_FakeWorker):
            def start(self):
                raise RuntimeError("start failed")

        class FailingManager(DownloadManagerCore):
            def _create_worker(self, video, save_dir):
                return FailingWorker(video, save_dir)

            def _emit_task_started(self, video_id: str) -> None:
                raise AssertionError("worker should not start")

            def _emit_task_progress(self, video_id: str, progress: int) -> None:
                raise AssertionError("worker should not report progress")

            def _emit_task_finished(self, video_id: str) -> None:
                raise AssertionError("worker should not finish")

            def _emit_task_error(self, video_id: str, error: str) -> None:
                self.errors.append((video_id, error))
                self.is_running = False

        manager = FailingManager.__new__(FailingManager)
        manager.queue = queue.Queue()
        manager.workers = []
        manager._workers_lock = threading.Lock()
        manager.is_running = True
        manager.errors = []
        manager.max_concurrent = 1
        manager.slot_semaphore = Mock()
        manager.slot_semaphore.acquire.return_value = True
        item = VideoItem(url="https://example.com/video.mp4", title="demo", source="douyin")
        manager.queue.put((item, "downloads"))

        # worker.start 抛错时，dispatcher 已经占用的并发槽必须释放，否则后续任务会永久阻塞。
        manager._dispatch_loop()

        self.assertEqual(manager.workers, [])
        self.assertEqual(manager.errors[0][0], item.id)
        manager.slot_semaphore.release.assert_called_once()

    def test_dispatch_requeues_dequeued_task_when_manager_stops(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager.workers = []
        manager._workers_lock = threading.RLock()
        manager._start_stop_lock = threading.RLock()
        manager.max_concurrent = 1
        manager.is_running = True
        manager.slot_semaphore = threading.Semaphore(1)
        item = VideoItem(url="https://example.com/x", title="demo", source="douyin")
        manager.queue.put((item, "downloads"))
        manager._create_worker = Mock(side_effect=AssertionError("worker should not start"))

        original_get = manager.queue.get

        def get_and_stop(timeout=1):
            video, save_dir = original_get(timeout=timeout)
            manager.is_running = False
            return video, save_dir

        manager.queue.get = get_and_stop
        # 模拟“刚取出队列项，管理器随即停止”的竞态，任务必须放回队列而不是丢失。
        manager._dispatch_loop()

        self.assertEqual(manager.queue.snapshot_video_ids(), {item.id})
        self.assertEqual(manager.workers, [])
        manager._create_worker.assert_not_called()

    def test_stop_all_fallback_drains_queue_without_empty_probe(self):
        class QueueWithoutReliableEmpty:
            def __init__(self):
                self.items = [object(), object()]

            def empty(self):
                raise AssertionError("stop_all must not rely on Queue.empty()")

            def get_nowait(self):
                if not self.items:
                    raise queue.Empty
                return self.items.pop()

        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = QueueWithoutReliableEmpty()
        manager.workers = []
        manager._workers_lock = threading.RLock()
        manager._start_stop_lock = threading.RLock()
        manager._dispatch_slot_gate = threading.Event()
        manager.dispatcher_thread = Mock()
        manager.dispatcher_thread.join.return_value = True
        manager.is_running = True

        manager.stop_all()

        self.assertEqual(manager.queue.items, [])
        manager.dispatcher_thread.join.assert_called_once_with(timeout=2)

    def test_cancel_task_uses_pending_queue_public_remove_api(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager._workers_lock = threading.Lock()
        manager.workers = []
        keep_item = VideoItem(url="https://example.com/1.mp4", title="keep", source="douyin")
        cancel_item = VideoItem(url="https://example.com/2.mp4", title="cancel", source="douyin")
        manager.queue.put((keep_item, "downloads"))
        manager.queue.put((cancel_item, "downloads"))

        result = manager.cancel_task(cancel_item.id)

        self.assertEqual(result, "queued")
        self.assertEqual(manager.queued_video_ids(), {keep_item.id})

    def test_set_max_concurrent_rebuilds_capacity_and_preserves_in_use_slots(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.max_concurrent = 2
        manager.slot_semaphore = threading.BoundedSemaphore(2)
        manager.slot_semaphore.acquire(blocking=False)
        manager._start_stop_lock = threading.RLock()

        result = manager.set_max_concurrent(5)

        self.assertEqual(result, 5)
        self.assertEqual(manager.max_concurrent, 5)
        acquired = 0
        while manager.slot_semaphore.acquire(blocking=False):
            acquired += 1
        self.assertEqual(acquired, DownloadManagerCore.LIGHTWEIGHT_MIN_CONCURRENT - 1)
        self.assertEqual(manager._slot_semaphore_capacity, DownloadManagerCore.LIGHTWEIGHT_MIN_CONCURRENT)

    def test_set_max_concurrent_caps_regular_workers_but_keeps_image_fast_lane(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.max_concurrent = 5
        manager.image_respects_concurrency = False
        manager.image_fast_lane_limit = 10
        manager.slot_semaphore = threading.BoundedSemaphore(5)
        manager._start_stop_lock = threading.RLock()

        result = manager.set_max_concurrent(32)

        self.assertEqual(result, 5)
        self.assertEqual(manager.max_concurrent, 5)
        self.assertEqual(manager._slot_semaphore_capacity, 10)

    def test_dispatch_capacity_uses_live_max_concurrent(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.max_concurrent = 2
        manager._workers_lock = threading.RLock()
        manager.workers = [object(), object()]

        self.assertFalse(manager._has_dispatch_capacity())

        manager.max_concurrent = 3

        self.assertTrue(manager._has_dispatch_capacity())

    def test_stale_finished_workers_do_not_keep_concurrency_slots(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.queue = PendingDownloadQueue()
        manager.max_concurrent = 3
        manager.image_respects_concurrency = True
        manager._workers_lock = threading.RLock()
        manager._slot_semaphore_lock = threading.RLock()
        manager._dispatch_slot_gate = threading.Event()
        manager.slot_semaphore = threading.BoundedSemaphore(3)
        manager.workers = []

        stale_workers = []
        for index in range(3):
            video = VideoItem(url=f"https://example.com/{index}.mp4", title="done", source="douyin")
            video.meta["content_type"] = "video"
            worker = SimpleNamespace(
                video=video,
                ident=index + 1,
                is_alive=lambda: False,
                _slot_released=False,
            )
            stale_workers.append(worker)
            manager.workers.append(worker)
            self.assertTrue(manager.slot_semaphore.acquire(blocking=False))

        next_video = VideoItem(url="https://example.com/next.mp4", title="next", source="douyin")
        next_video.meta["content_type"] = "video"

        self.assertTrue(manager._has_capacity_for(next_video))
        self.assertEqual(manager.workers, [])
        self.assertTrue(all(worker._slot_released for worker in stale_workers))

        available_tokens = 0
        while manager.slot_semaphore.acquire(blocking=False):
            available_tokens += 1
        self.assertEqual(available_tokens, 3)

    def test_lightweight_downloads_can_dispatch_above_video_limit(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.max_concurrent = 3
        manager.image_respects_concurrency = False
        manager._workers_lock = threading.RLock()
        manager.workers = []
        for index in range(3):
            video = VideoItem(url=f"https://example.com/{index}.mp4", title="video", source="douyin")
            video.meta["content_type"] = "video"
            manager.workers.append(SimpleNamespace(video=video))

        image = VideoItem(url="https://example.com/image.jpg", title="image", source="douyin")
        image.meta["content_type"] = "image"
        heavy_video = VideoItem(url="https://example.com/next.mp4", title="next", source="douyin")
        heavy_video.meta["content_type"] = "video"

        self.assertFalse(manager._has_dispatch_capacity())
        self.assertTrue(manager._has_any_dispatch_capacity())
        self.assertTrue(manager._has_capacity_for(image))
        self.assertFalse(manager._has_capacity_for(heavy_video))

    def test_lightweight_downloads_can_respect_regular_concurrency_when_enabled(self):
        manager = DownloadManagerCore.__new__(DownloadManagerCore)
        manager.max_concurrent = 3
        manager.image_respects_concurrency = True
        manager._workers_lock = threading.RLock()
        manager.workers = []
        for index in range(3):
            image_worker = VideoItem(url=f"https://example.com/{index}.jpg", title="image", source="xiaohongshu")
            image_worker.meta["content_type"] = "image"
            manager.workers.append(SimpleNamespace(video=image_worker))

        next_image = VideoItem(url="https://example.com/next.jpg", title="next", source="xiaohongshu")
        next_image.meta["content_type"] = "image"

        self.assertEqual(manager._slot_capacity(), 3)
        self.assertFalse(manager._has_any_dispatch_capacity())
        self.assertFalse(manager._has_capacity_for(next_image))

if __name__ == "__main__":
    unittest.main()
