# app/core/download_manager.py

import os
import threading
import queue
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QSemaphore
from app.models import VideoItem
from app.core.downloaders import KuaishouDownloader, MissAVDownloader, BilibiliDownloader

class DownloadWorker(QThread):
    sig_start = pyqtSignal(str)
    sig_progress = pyqtSignal(str, int)
    sig_finished = pyqtSignal(str)
    sig_error = pyqtSignal(str, str)

    def __init__(self, video: VideoItem, save_dir: str, semaphore: QSemaphore):
        super().__init__()
        self.video = video
        self.save_dir = save_dir
        self.semaphore = semaphore
        self.is_running = True

    def run(self):
        self.semaphore.acquire()
        try:
            if not self.is_running: return
            self.sig_start.emit(self.video.id)
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir, exist_ok=True)
            # 获取文件名
            filename = self.video.get_safe_filename("mp4")
            filepath = os.path.join(self.save_dir, filename)
            self.video.local_path = filepath
            # 策略选择
            downloader = None
            if self.video.source == "kuaishou":
                downloader = KuaishouDownloader()
            elif self.video.source == "missav":
                downloader = MissAVDownloader()
            elif self.video.source == "bilibili":
                downloader = BilibiliDownloader()
            else:
                raise ValueError(f"Unknown source: {self.video.source}")
            # 执行下载 (传入回调和停止检查)
            downloader.download(
                video_item=self.video,
                save_path=filepath,
                progress_callback=lambda p: self.sig_progress.emit(self.video.id, p),
                check_stop_func=lambda: not self.is_running
            )
            if self.is_running:
                self.sig_finished.emit(self.video.id)
        except InterruptedError:
            self.sig_error.emit(self.video.id, "用户已停止")
        except Exception as e:
            self.sig_error.emit(self.video.id, str(e))
        finally:
            self.semaphore.release()
    def stop(self):
        self.is_running = False

class DownloadManager(QObject):
    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int)
    task_finished = pyqtSignal(str)
    task_error = pyqtSignal(str, str)
    def __init__(self, max_concurrent=3):
        super().__init__()
        self.queue = queue.Queue()
        self.workers = []
        self.max_concurrent = max_concurrent
        self.semaphore = QSemaphore(max_concurrent)
        self.is_running = True
        self.dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatcher_thread.start()
    def add_task(self, video: VideoItem, save_dir: str):
        self.queue.put((video, save_dir))
    def _dispatch_loop(self):
        while self.is_running:
            try:
                video, save_dir = self.queue.get(timeout=1)
                self.workers = [w for w in self.workers if w.isRunning()]
                worker = DownloadWorker(video, save_dir, self.semaphore)
                worker.sig_start.connect(self.task_started)
                worker.sig_progress.connect(self.task_progress)
                worker.sig_finished.connect(self.task_finished)
                worker.sig_error.connect(self.task_error)
                self.workers.append(worker)
                worker.start()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Dispatcher Error: {e}")
    def stop_all(self):
        self.is_running = False
        # 清空队列
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                pass
        # 停止所有正在运行的工兵
        for w in self.workers:
            w.stop()
            w.wait()