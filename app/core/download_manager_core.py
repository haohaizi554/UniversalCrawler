"""Pure-Python download dispatch core."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Iterable

from app.config import cfg
from app.debug_logger import debug_logger
from app.exceptions import AppError
from app.models import VideoItem

class PendingDownloadQueue:
    """Thread-safe FIFO queue with explicit cancellation/snapshot operations."""

    def __init__(self) -> None:
        self._items: deque[tuple[VideoItem, str]] = deque()
        self._condition = threading.Condition()
        self._queued_ids: dict[str, int] = {}

    def _track_enqueue(self, video_id: str) -> None:
        if video_id:
            self._queued_ids[video_id] = self._queued_ids.get(video_id, 0) + 1

    def _track_dequeue(self, video_id: str) -> None:
        if not video_id:
            return
        count = self._queued_ids.get(video_id, 0)
        if count <= 1:
            self._queued_ids.pop(video_id, None)
        else:
            self._queued_ids[video_id] = count - 1

    def put(self, item: tuple[VideoItem, str]) -> None:
        with self._condition:
            self._items.append(item)
            self._track_enqueue(getattr(item[0], "id", ""))
            self._condition.notify()

    def get(self, timeout: float | None = None) -> tuple[VideoItem, str]:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._items:
                if timeout is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic() if deadline is not None else 0.0
                if remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)
            item = self._items.popleft()
            self._track_dequeue(getattr(item[0], "id", ""))
            return item

    def get_nowait(self) -> tuple[VideoItem, str]:
        return self.get(timeout=0.0)

    def empty(self) -> bool:
        with self._condition:
            return not self._items

    def qsize(self) -> int:
        with self._condition:
            return len(self._items)

    def drain(self) -> list[tuple[VideoItem, str]]:
        with self._condition:
            items = list(self._items)
            self._items.clear()
            self._queued_ids.clear()
            return items

    def remove_video(self, video_id: str) -> VideoItem | None:
        removed = self.remove_videos({video_id})
        return removed[0] if removed else None

    def remove_videos(self, video_ids: Iterable[str]) -> list[VideoItem]:
        ids = {str(video_id) for video_id in video_ids if video_id}
        if not ids:
            return []
        with self._condition:
            retained: deque[tuple[VideoItem, str]] = deque()
            removed: list[VideoItem] = []
            while self._items:
                queued_video, save_dir = self._items.popleft()
                if queued_video.id in ids:
                    removed.append(queued_video)
                    self._track_dequeue(queued_video.id)
                    continue
                retained.append((queued_video, save_dir))
            self._items = retained
            return removed

    def snapshot_video_ids(self) -> set[str]:
        with self._condition:
            return set(self._queued_ids)

class DownloadManagerCore:
    """Maintain queueing, concurrency slots, cancellation, and worker lifecycle."""

    WORKER_STOP_TIMEOUT_MS = 2000
    _GUARD_INIT_LOCK = threading.RLock()

    def __init__(self, max_concurrent: int | None = None):
        self.queue = PendingDownloadQueue()
        self.workers: list[Any] = []
        self.max_concurrent = max_concurrent or cfg.get("download", "max_concurrent", 3)
        self.slot_semaphore = threading.Semaphore(self.max_concurrent)
        self._workers_lock = threading.RLock()
        self._start_stop_lock = threading.RLock()
        self.is_running = True
        self.dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatcher_thread.start()

    def set_max_concurrent(self, value: int) -> int:
        try:
            new_value = int(value)
        except (TypeError, ValueError):
            new_value = self.max_concurrent
        new_value = max(1, min(new_value, 8))
        with self._start_stop_guard():
            old_value = int(getattr(self, "max_concurrent", 1) or 1)
            self.max_concurrent = new_value
            if new_value > old_value:
                for _ in range(new_value - old_value):
                    self.slot_semaphore.release()
        return self.max_concurrent

    def _has_dispatch_capacity(self) -> bool:
        with self._workers_lock:
            return len(self.workers) < int(getattr(self, "max_concurrent", 1) or 1)

    def add_task(self, video: VideoItem, save_dir: str):
        """Add a video item into the download queue."""
        trace_id = video.meta.get("trace_id")
        debug_logger.log(
            component="DownloadManager",
            action="queue_task",
            message="下载任务已进入队列",
            status_code="DL_QUEUE",
            context=debug_logger.pick_used(
                {"trace_id": trace_id, "video_id": video.id, "source": video.source},
                "trace_id", "video_id", "source",
            ),
            details=debug_logger.pick_used(
                {"title": video.title, "save_dir": save_dir, "url": video.url, "content_type": video.meta.get("content_type")},
                "title", "save_dir", "url", "content_type",
            ),
            trace_id=trace_id,
        )
        with self._start_stop_guard():
            if not self.is_running:
                raise RuntimeError("DownloadManager 已停止，无法继续添加任务")
            self.queue.put((video, save_dir))

    def cancel_task(self, video_id: str) -> str | None:
        """Cancel a queued or running task."""
        return self.cancel_tasks({video_id}).get(video_id)

    def cancel_tasks(self, video_ids: Iterable[str]) -> dict[str, str | None]:
        """Cancel many queued or running tasks with one queue scan."""
        ids = {str(video_id) for video_id in video_ids if video_id}
        results: dict[str, str | None] = {video_id: None for video_id in ids}
        if not ids:
            return results

        queued_videos = self._remove_queued_tasks(ids)
        queued_ids = {video.id for video in queued_videos}
        for video in queued_videos:
            video.meta["frontend_status"] = '\u5f85\u4e0b\u8f7d'
            video.meta["user_cancel_requested"] = True
            results[video.id] = "queued"

        remaining_ids = ids - queued_ids
        if not remaining_ids:
            return results

        running_workers = []
        with self._workers_lock:
            for worker in list(self.workers):
                worker_id = getattr(getattr(worker, "video", None), "id", None)
                if worker_id in remaining_ids:
                    running_workers.append(worker)

        for worker in running_workers:
            video = worker.video
            video.meta["frontend_status"] = '\u5f85\u4e0b\u8f7d'
            video.meta["user_cancel_requested"] = True
            worker.stop()
            results[video.id] = "running"

        return results

    def _dispatch_loop(self):
        """Dispatcher thread acquires a slot before dequeuing a worker task."""
        while self.is_running:
            slot_acquired = False
            worker = None
            video = None
            save_dir = None
            try:
                if not self._wait_for_dispatch_slot():
                    break
                slot_acquired = True
                try:
                    video, save_dir = self.queue.get(timeout=1)
                except queue.Empty:
                    self.slot_semaphore.release()
                    slot_acquired = False
                    continue

                with self._start_stop_guard():
                    if not self.is_running:
                        self.queue.put((video, save_dir))
                        self.slot_semaphore.release()
                        slot_acquired = False
                        break

                worker = self._create_worker(video, save_dir)
                debug_logger.log(
                    component="DownloadManager",
                    action="dispatch_task",
                    message="任务已从队列分发到下载线程",
                    status_code="DL_DISPATCH",
                    context=debug_logger.pick_used(
                        {"trace_id": video.meta.get("trace_id"), "video_id": video.id, "source": video.source},
                        "trace_id", "video_id", "source",
                    ),
                    details=debug_logger.pick_used(
                        {"title": video.title, "max_concurrent": self.max_concurrent},
                        "title", "max_concurrent",
                    ),
                    trace_id=video.meta.get("trace_id"),
                )
                self._connect_worker_callbacks(worker)
                worker._slot_released = False
                worker._completion_callback = self._handle_worker_completion
                with self._start_stop_guard():
                    if not self.is_running:
                        if slot_acquired:
                            self.slot_semaphore.release()
                            slot_acquired = False
                        break
                    with self._workers_lock:
                        self.workers.append(worker)
                    worker.start()
                slot_acquired = False
            except queue.Empty:
                continue
            except Exception as e:
                failed_video = locals().get("video")
                if worker is not None:
                    with self._workers_lock:
                        if worker in self.workers:
                            self.workers.remove(worker)
                if slot_acquired:
                    self.slot_semaphore.release()
                with self._workers_lock:
                    active_workers = len(self.workers)
                debug_logger.log_exception(
                    "DownloadManager",
                    "dispatch_loop",
                    e,
                    details={"queued_tasks": self.queue.qsize(), "active_workers": active_workers},
                )
                if failed_video is not None:
                    self._emit_task_error(failed_video.id, f"调度失败: {e}")

    def _create_worker(self, video: VideoItem, save_dir: str):
        raise NotImplementedError

    def _connect_worker_callbacks(self, worker: Any) -> None:
        worker.sig_start.connect(self._emit_task_started)
        worker.sig_progress.connect(self._emit_task_progress)
        worker.sig_finished.connect(self._emit_task_finished)
        worker.sig_error.connect(self._emit_task_error)
        worker.finished.connect(lambda w=worker: self._on_worker_thread_finished(w))

    def _emit_task_started(self, video_id: str) -> None:
        raise NotImplementedError

    def _emit_task_progress(self, video_id: str, progress: int) -> None:
        raise NotImplementedError

    def _emit_task_finished(self, video_id: str) -> None:
        raise NotImplementedError

    def _emit_task_error(self, video_id: str, error: str) -> None:
        raise NotImplementedError

    def _find_worker(self, video_id: str):
        with self._workers_lock:
            for worker in self.workers:
                if worker.video.id == video_id:
                    return worker
        return None

    def _start_stop_guard(self) -> threading.RLock:
        lock = getattr(self, "_start_stop_lock", None)
        if lock is None:
            with self._GUARD_INIT_LOCK:
                lock = getattr(self, "_start_stop_lock", None)
                if lock is None:
                    lock = threading.RLock()
                    self._start_stop_lock = lock
        return lock

    def _remove_queued_task(self, video_id: str) -> VideoItem | None:
        removed = self._remove_queued_tasks({video_id})
        return removed[0] if removed else None

    def _remove_queued_tasks(self, video_ids: Iterable[str]) -> list[VideoItem]:
        remove_videos = getattr(self.queue, "remove_videos", None)
        if callable(remove_videos):
            return list(remove_videos(video_ids))
        remove_video = getattr(self.queue, "remove_video", None)
        if callable(remove_video):
            removed = []
            for video_id in video_ids:
                video = remove_video(video_id)
                if video is not None:
                    removed.append(video)
            return removed
        return []

    def queued_video_ids(self) -> set[str]:
        snapshot_video_ids = getattr(self.queue, "snapshot_video_ids", None)
        if callable(snapshot_video_ids):
            return snapshot_video_ids()
        return set()

    def _wait_for_dispatch_slot(self) -> bool:
        while self.is_running:
            if not self._has_dispatch_capacity():
                time.sleep(0.1)
                continue
            if not self.slot_semaphore.acquire(timeout=0.5):
                continue
            if self._has_dispatch_capacity():
                return True
            self.slot_semaphore.release()
            time.sleep(0.1)
        return False

    def _release_worker_slot(self, worker: Any, reason: str) -> None:
        if getattr(worker, "_slot_released", False):
            return
        worker._slot_released = True
        self.slot_semaphore.release()
        debug_logger.log(
            component="DownloadManager",
            action="release_slot",
            message="下载并发槽位已释放",
            status_code="DL_SLOT_RELEASE",
            context=debug_logger.pick_used(
                {"trace_id": worker.video.meta.get("trace_id"), "video_id": worker.video.id},
                "trace_id", "video_id",
            ),
            details={"reason": reason},
            trace_id=worker.video.meta.get("trace_id"),
        )

    def _handle_worker_completion(self, worker: Any, reason: str) -> None:
        with self._workers_lock:
            if worker in self.workers:
                self.workers.remove(worker)
        self._release_worker_slot(worker, reason)

    def _on_worker_thread_finished(self, worker: Any):
        """Adapter hook for thread-object cleanup."""

    def stop_all(self):
        with self._start_stop_guard():
            self.is_running = False
            with self._workers_lock:
                active_workers = len(self.workers)
            debug_logger.log(
                component="DownloadManager",
                action="stop_all",
                level="WARN",
                message="开始停止所有下载任务",
                status_code="DL_STOP_ALL",
                details={"active_workers": active_workers},
            )
            drain = getattr(self.queue, "drain", None)
            if callable(drain):
                drain()
            else:
                while not self.queue.empty():
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass
            with self._workers_lock:
                workers_snapshot = list(self.workers)
        for worker in workers_snapshot:
            worker.stop()
            try:
                _wait_ok = worker.wait(self.WORKER_STOP_TIMEOUT_MS)
            except RuntimeError:
                _wait_ok = True
            if not _wait_ok:
                debug_logger.log(
                    component="DownloadManager",
                    action="stop_all_worker_timeout",
                    level="WARN",
                    message="等待下载线程停止超时，继续执行退出流程",
                    status_code="DL_STOP_TIMEOUT",
                    details={"video_id": worker.video.id, "timeout_ms": self.WORKER_STOP_TIMEOUT_MS},
                    trace_id=worker.video.meta.get("trace_id"),
                )
        if not self.dispatcher_thread.join(timeout=2):
            debug_logger.log(
                component="DownloadManager",
                action="stop_all_dispatcher_timeout",
                level="WARN",
                message="下载调度线程未在 2 秒内退出",
                status_code="DL_DISPATCHER_STOP_TIMEOUT",
            )
