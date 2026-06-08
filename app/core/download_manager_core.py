"""Pure-Python download dispatch core."""

from __future__ import annotations

import queue
import threading
from typing import Any

from app.config import cfg
from app.debug_logger import debug_logger
from app.exceptions import AppError
from app.models import VideoItem


class DownloadManagerCore:
    """Maintain queueing, concurrency slots, cancellation, and worker lifecycle."""

    WORKER_STOP_TIMEOUT_MS = 2000

    def __init__(self, max_concurrent: int | None = None):
        self.queue = queue.Queue()
        self.workers: list[Any] = []
        self.max_concurrent = max_concurrent or cfg.get("download", "max_concurrent", 3)
        self.slot_semaphore = threading.Semaphore(self.max_concurrent)
        self._workers_lock = threading.Lock()
        self.is_running = True
        self.dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatcher_thread.start()

    def add_task(self, video: VideoItem, save_dir: str):
        """Add a video item into the download queue."""
        if not self.is_running:
            raise RuntimeError("DownloadManager 已停止，无法继续添加任务")
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
        self.queue.put((video, save_dir))

    def cancel_task(self, video_id: str) -> str | None:
        """Cancel a queued or running task."""
        if self._remove_queued_task(video_id):
            return "queued"

        worker = self._find_worker(video_id)
        if worker is None:
            return None

        worker.stop()
        return "running"

    def _dispatch_loop(self):
        """Dispatcher thread acquires a slot before starting a worker."""
        while self.is_running:
            try:
                video, save_dir = self.queue.get(timeout=1)
                if not self._wait_for_dispatch_slot():
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
                with self._workers_lock:
                    self.workers.append(worker)
                worker.start()
            except queue.Empty:
                continue
            except (AppError, OSError, RuntimeError, ValueError) as e:
                failed_video = locals().get("video")
                debug_logger.log_exception(
                    "DownloadManager",
                    "dispatch_loop",
                    e,
                    details={"queued_tasks": self.queue.qsize(), "active_workers": len(self.workers)},
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

    def _remove_queued_task(self, video_id: str) -> bool:
        removed = False
        with self.queue.mutex:
            retained_tasks = []
            removed_count = 0
            for queued_video, save_dir in self.queue.queue:
                if queued_video.id == video_id and not removed:
                    removed = True
                    removed_count += 1
                    continue
                retained_tasks.append((queued_video, save_dir))
            if removed:
                self.queue.queue.clear()
                self.queue.queue.extend(retained_tasks)
                if self.queue.unfinished_tasks >= removed_count:
                    self.queue.unfinished_tasks -= removed_count
                if self.queue.unfinished_tasks == 0:
                    self.queue.all_tasks_done.notify_all()
                self.queue.not_full.notify_all()
        return removed

    def _wait_for_dispatch_slot(self) -> bool:
        while self.is_running:
            if self.slot_semaphore.acquire(timeout=0.5):
                return True
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
        self.is_running = False
        debug_logger.log(
            component="DownloadManager",
            action="stop_all",
            level="WARN",
            message="开始停止所有下载任务",
            status_code="DL_STOP_ALL",
            details={"active_workers": len(self.workers)},
        )
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
        with self._workers_lock:
            workers_snapshot = list(self.workers)
        for worker in workers_snapshot:
            worker.stop()
            _wait_ok = worker.wait(self.WORKER_STOP_TIMEOUT_MS)
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
        self.dispatcher_thread.join(timeout=2)
