"""Central download queue and worker dispatch logic."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from app.core.download_manager_core import DownloadManagerCore
from app.core.downloaders import (
    BaseDownloader,
    BilibiliDownloader,
    DouyinDownloader,
    KuaishouDownloader,
    MissAVDownloader,
    XiaohongshuDownloader,
)
from app.exceptions import AppError, DownloaderStoppedError
from app.models import VideoItem
from app.utils import sanitize_filename
from app.utils.callback_signal import CallbackSignal
from app.debug_logger import debug_logger

#下载器注册表
DOWNLOADER_REGISTRY: tuple[type[BaseDownloader], ...] = (
    DouyinDownloader,
    XiaohongshuDownloader,
    KuaishouDownloader,
    MissAVDownloader,
    BilibiliDownloader,
)


class DownloadWorker(threading.Thread):
    """执行单个下载任务，并把进度、完成、失败事件回传给管理器。"""

    # 文件类型签名映射
    FILE_SIGNATURES = {
        b'\x89PNG': '.png',
        b'\xff\xd8\xff': '.jpg',
        b'GIF89a': '.gif',
        b'GIF87a': '.gif',
        b'RIFF': '.webp',  # webp 以 RIFF 开头
        b'\x00\x00\x00 ftyp': '.mp4',
        b'\x00\x00\x00\x1cftyp': '.mp4',
        b'\x00\x00\x00\x20ftyp': '.mp4',
        b'ID3': '.mp3',
        b'\xff\xfb': '.mp3',  # MPEG audio
        b'\xff\xf3': '.mp3',
        b'\xff\xf2': '.mp3',
        b'OggS': '.ogg',
        b'fLaC': '.flac',
        b'RIFF....AVI': '.avi',
    }

    def __init__(self, video: VideoItem, save_dir: str):
        """保存任务对象与目标目录，并初始化线程控制状态。"""
        super().__init__(daemon=True, name=f"DownloadWorker-{video.id}")
        self.video = video
        self.save_dir = save_dir
        self.is_running = True
        self.sig_start = CallbackSignal()
        self.sig_progress = CallbackSignal()
        self.sig_finished = CallbackSignal()
        self.sig_error = CallbackSignal()
        self.finished = CallbackSignal()
        self._final_ext = ".mp4"
        self._completion_callback: Callable[[DownloadWorker, str], None] | None = None

    def _trace_id(self) -> str | None:
        """读取当前任务的 trace_id，便于串联调试日志。"""
        return self.video.meta.get("trace_id")

    def _log_context(self, save_dir: str | None = None) -> dict:
        """生成下载日志上下文，统一附带视频 ID、平台与保存目录。"""
        return debug_logger.pick_used(
            {
                "trace_id": self._trace_id(),
                "video_id": self.video.id,
                "source": self.video.source,
                "save_dir": save_dir,
            },
            "trace_id", "video_id", "source", "save_dir",
        )

    def _log_details(self, filepath: str | None = None, strategy: str | None = None) -> dict:
        """提取下载日志详情字段，避免每次手写同一批元数据。"""
        return debug_logger.pick_used(
            {
                "title": self.video.title,
                "url": self.video.url,
                "target_path": filepath,
                "strategy": strategy,
                "content_type": self.video.meta.get("content_type"),
                "folder_name": self.video.meta.get("folder_name"),
                "audio_url": self.video.meta.get("audio_url"),
                "aweme_id": self.video.meta.get("aweme_id"),
                "bvid": self.video.meta.get("bvid"),
                "cid": self.video.meta.get("cid"),
            },
            "title", "url", "target_path", "strategy", "content_type", "folder_name", "audio_url", "aweme_id", "bvid", "cid",
        )

    def run(self):
        """完成下载前的路径准备、下载执行以及结束后的收尾工作。"""
        completion_reason = "thread_finished"
        try:
            if not self.is_running:
                return

            # 先把保存目录和目标文件名计算清楚，下载器只负责真正的传输逻辑。
            save_dir = self._resolve_save_dir()

            if not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            ext = self._infer_extension()
            filename = self._generate_filename(ext)
            filepath = self._ensure_unique_path(os.path.join(save_dir, filename))
            # 先设置 local_path，再 emit sig_start
            # 这样 sig_start 信号携带的 local_path 是有效的（Web 端依赖此路径播放视频）
            self.video.local_path = filepath
            self._final_ext = ext
            self.sig_start.emit(self.video.id)
            downloader = self._select_downloader()
            download_strategy = self.video.meta.get("download_strategy")
            debug_logger.log(
                component="DownloadWorker",
                action="start_download",
                message="下载任务开始执行",
                status_code="DL_START",
                context=self._log_context(save_dir),
                details=self._log_details(filepath, download_strategy or self.video.source),
                trace_id=self._trace_id(),
            )
            downloader.download(
                video_item=self.video,
                save_path=filepath,
                progress_callback=lambda p: self.sig_progress.emit(self.video.id, p),
                check_stop_func=lambda: not self.is_running
            )
            if self.is_running and os.path.exists(filepath):
                # 某些站点返回的资源扩展名并不可信，下载完成后再按文件签名二次校正。
                actual_ext = self._detect_actual_file_type(filepath)
                if actual_ext and actual_ext != self._final_ext:
                    new_filepath = self._ensure_unique_path(filepath.rsplit('.', 1)[0] + actual_ext)
                    try:
                        os.rename(filepath, new_filepath)
                        self.video.local_path = new_filepath
                        debug_logger.log(
                            component="DownloadWorker",
                            action="normalize_extension",
                            message="下载完成后已按文件签名修正扩展名",
                            status_code="DL_EXT_NORMALIZED",
                            context=self._log_context(),
                            details={
                                "old_name": os.path.basename(filepath),
                                "new_name": os.path.basename(new_filepath),
                            },
                            trace_id=self._trace_id(),
                        )
                    except OSError as e:
                        debug_logger.log_exception(
                            "DownloadWorker",
                            "normalize_extension",
                            e,
                            context=self._log_context(),
                            details={"old_path": filepath, "new_path": new_filepath},
                            trace_id=self._trace_id(),
                        )

            if self.is_running:
                debug_logger.log(
                    component="DownloadWorker",
                    action="download_finished",
                    message="下载任务完成",
                    status_code="DL_FINISH",
                    context=self._log_context(),
                    details=debug_logger.pick_used(
                        {"title": self.video.title, "local_path": self.video.local_path},
                        "title", "local_path",
                    ),
                    trace_id=self._trace_id(),
                )
                completion_reason = "task_finished"
                self.sig_finished.emit(self.video.id)
        except DownloaderStoppedError:
            completion_reason = "task_error"
            debug_logger.log(
                component="DownloadWorker",
                action="download_stopped",
                level="WARN",
                message="下载任务被用户停止",
                status_code="DL_STOPPED",
                context=self._log_context(),
                details=debug_logger.pick_used({"title": self.video.title}, "title"),
                trace_id=self._trace_id(),
            )
            self.sig_error.emit(self.video.id, "用户已停止")
        except (AppError, OSError, RuntimeError, ValueError) as e:
            completion_reason = "task_error"
            debug_logger.log_exception(
                "DownloadWorker",
                "download_error",
                e,
                context=self._log_context(),
                details=self._log_details(filepath if 'filepath' in locals() else None, download_strategy if 'download_strategy' in locals() else None),
                trace_id=self._trace_id(),
            )
            self.sig_error.emit(self.video.id, str(e))
        finally:
            try:
                if callable(self._completion_callback):
                    self._completion_callback(self, completion_reason)
            finally:
                self.finished.emit()

    def _select_downloader(self) -> BaseDownloader:
        """统一从注册表中选择平台下载器，避免在 run() 中继续堆 if/elif。"""
        for downloader_cls in DOWNLOADER_REGISTRY:
            if downloader_cls.can_handle(self.video):
                return downloader_cls()
        raise ValueError(f"Unknown source: {self.video.source}")

    def stop(self):
        """通知下载器在下一次检查时尽快停止当前任务。"""
        self.is_running = False

    def isRunning(self) -> bool:
        """兼容旧 QThread 调用方。"""
        return self.is_alive()

    def wait(self, timeout_ms: int | None = None) -> bool:
        """兼容旧 QThread 调用方。"""
        timeout = None if timeout_ms is None else max(timeout_ms, 0) / 1000
        self.join(timeout=timeout)
        return not self.is_alive()

    def deleteLater(self) -> None:
        """兼容旧 Qt 适配层清理调用，纯 Python worker 无需延迟销毁。"""
        return None

    def _resolve_save_dir(self) -> str:
        """图集/合集类任务单独落到子目录，避免主目录被大量切碎文件污染。"""
        save_dir = self.save_dir
        content_type = self.video.meta.get("content_type", "")
        is_gallery = self.video.meta.get("is_gallery", False)
        is_mix = self.video.meta.get("is_mix", False)
        use_subdir = self.video.meta.get("use_subdir", False)
        folder_name = sanitize_filename(self.video.meta.get("folder_name", ""))

        if folder_name and (is_gallery or content_type == "gallery" or is_mix or use_subdir):
            return os.path.join(save_dir, folder_name)
        return save_dir

    def _infer_extension(self) -> str:
        """根据内容类型和 URL 后缀推断初始扩展名。"""
        content_type = self.video.meta.get("content_type", "")
        if content_type == "gallery":
            return ".jpeg"
        if content_type == "video":
            return ".mp4"

        url_lower = self.video.url.lower()
        if ".gif" in url_lower:
            return ".gif"
        if ".webp" in url_lower:
            return ".webp"
        if ".png" in url_lower:
            return ".png"
        if ".jpeg" in url_lower or ".jpg" in url_lower:
            return ".jpg"
        return ".mp4"

    def _generate_filename(self, ext):
        """生成文件名，避免重复扩展名和空文件名。"""
        preferred_name = self.video.meta.get("preferred_filename")
        desc = sanitize_filename(preferred_name or self.video.title)
        base_name, current_ext = os.path.splitext(desc)
        safe_name = base_name if current_ext.lower() == ext.lower() else desc
        safe_name = safe_name[:200] or f"{self.video.source}_{self.video.id}"
        return f"{safe_name}{ext}"

    def _ensure_unique_path(self, filepath: str) -> str:
        """若目标文件已存在，则为文件名追加递增后缀以避免覆盖。"""
        if not os.path.exists(filepath):
            return filepath

        base, ext = os.path.splitext(filepath)
        index = 1
        while True:
            candidate = f"{base}_{index}{ext}"
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _detect_actual_file_type(self, filepath: str) -> str:
        """根据文件头检测实际文件类型，避免错误扩展名影响播放。"""
        try:
            with open(filepath, "rb") as f:
                header = f.read(32)

            for signature, ext in self.FILE_SIGNATURES.items():
                if signature == b"RIFF....AVI":
                    if header.startswith(b"RIFF") and b"AVI " in header[:12]:
                        return ext
                    continue
                if signature in (b"\x00\x00\x00 ftyp", b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x20ftyp"):
                    if b"ftyp" in header[:12]:
                        return ext
                    continue
                if header.startswith(signature):
                    if signature == b"RIFF" and b"WEBP" not in header[:12]:
                        continue
                    return ext

            if header.startswith(b"\x1aE\xdf\xa3"):
                return ".mkv"
            if b"FLV" in header[:5]:
                return ".flv"
            return None
        except OSError as e:
            debug_logger.log_exception(
                "DownloadWorker",
                "detect_actual_file_type",
                e,
                context=self._log_context(),
                details={"file_path": filepath},
                trace_id=self._trace_id(),
            )
            return None

class DownloadManager(DownloadManagerCore):
    """维护下载队列、并发槽位以及工作线程生命周期。"""

    def __init__(self, max_concurrent: int | None = None):
        """初始化任务队列，并启动后台派发线程。"""
        self.task_started = CallbackSignal()
        self.task_progress = CallbackSignal()
        self.task_finished = CallbackSignal()
        self.task_error = CallbackSignal()
        DownloadManagerCore.__init__(self, max_concurrent=max_concurrent)

    def _create_worker(self, video: VideoItem, save_dir: str):
        return DownloadWorker(video, save_dir)

    def _connect_worker_callbacks(self, worker) -> None:
        worker.sig_start.connect(self._emit_task_started)
        worker.sig_progress.connect(self._emit_task_progress)
        worker.sig_finished.connect(self._emit_task_finished)
        worker.sig_error.connect(self._emit_task_error)
        worker.finished.connect(lambda w=worker: self._on_worker_thread_finished(w))

    def _emit_task_started(self, video_id: str) -> None:
        self.task_started.emit(video_id)

    def _emit_task_progress(self, video_id: str, progress: int) -> None:
        self.task_progress.emit(video_id, progress)

    def _emit_task_finished(self, video_id: str) -> None:
        self.task_finished.emit(video_id)

    def _emit_task_error(self, video_id: str, error: str) -> None:
        self.task_error.emit(video_id, error)

    def _on_worker_thread_finished(self, worker):
        """线程真正退出后的兼容清理钩子。"""
        worker.deleteLater()
