"""下载队列、工作线程分发及前端状态投影的主协调器。"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from app.core.download_manager_core import DownloadManagerCore
from app.core.download_path_policy import resolve_task_save_directory
from app.core.downloaders import BaseDownloader
from app.core.downloaders.registry import downloader_registry
from app.exceptions import DownloaderStoppedError
from app.models import VideoItem
from app.utils import sanitize_filename
from app.utils.callback_signal import CallbackSignal
from app.debug_logger import debug_logger

class DownloadWorker(threading.Thread):
    """执行单个下载任务，并把进度、完成、失败事件回传给管理器。"""

    FILE_SIGNATURES = {
        b'\x89PNG': '.png',
        b'\xff\xd8\xff': '.jpg',
        b'GIF89a': '.gif',
        b'GIF87a': '.gif',
        b'RIFF': '.webp',  # webp 以 RIFF 开头
        b'\x00\x00\x00\x1cftyp': '.mp4',
        b'\x00\x00\x00\x20ftyp': '.mp4',
        b'ID3': '.mp3',
        b'\xff\xfb': '.mp3',  # MPEG 音频
        b'\xff\xf3': '.mp3',
        b'\xff\xf2': '.mp3',
        b'OggS': '.ogg',
        b'fLaC': '.flac',
        b'RIFF....AVI': '.avi',
    }

    def __init__(self, video: VideoItem, save_dir: str):
        super().__init__(daemon=True, name=f"DownloadWorker-{video.id}")
        self.video = video
        self.save_dir = save_dir
        self._running_event = threading.Event()
        self._running_event.set()
        self.sig_start = CallbackSignal()
        self.sig_progress = CallbackSignal()
        self.sig_finished = CallbackSignal()
        self.sig_error = CallbackSignal()
        self.finished = CallbackSignal()
        self._final_ext = ".mp4"
        self._completion_callback: Callable[[DownloadWorker, str], None] | None = None
        self._path_reservations: list[str] = []

    def _trace_id(self) -> str | None:
        return self.video.meta.get("trace_id")

    @property
    def is_running(self) -> bool:
        return self._running_event.is_set()

    @is_running.setter
    def is_running(self, value: bool) -> None:
        if value:
            self._running_event.set()
        else:
            self._running_event.clear()

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
            self._remember_output_path(filepath)
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
                progress_callback=self._emit_progress_if_changed(),
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
                        self._remember_output_path(new_filepath)
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
                self.is_running = False
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
            self.is_running = False
            self.sig_error.emit(self.video.id, "用户已停止")
        except Exception as e:
            completion_reason = "task_error"
            debug_logger.log_exception(
                "DownloadWorker",
                "download_error",
                e,
                context=self._log_context(),
                details=self._log_details(filepath if 'filepath' in locals() else None, download_strategy if 'download_strategy' in locals() else None),
                trace_id=self._trace_id(),
            )
            self.is_running = False
            self.sig_error.emit(self.video.id, str(e))
        finally:
            from app.services.download_telemetry import get_download_telemetry_service

            self.is_running = False
            get_download_telemetry_service().clear(self.video.id)
            self._release_output_path_reservations()
            try:
                if callable(self._completion_callback):
                    self._completion_callback(self, completion_reason)
            finally:
                self.finished.emit()

    def _select_downloader(self) -> BaseDownloader:
        cls = downloader_registry.resolve(self.video)
        if cls is not None:
            return cls()
        raise ValueError(f"Unknown source: {self.video.source}")

    def _emit_progress_if_changed(self):
        """合并相同百分比，避免高频进度回调反复触发前端重绘。"""
        from app.services.download_telemetry import get_download_telemetry_service

        telemetry = get_download_telemetry_service()
        last_progress: int | None = None
        last_speed_bps = 0
        last_emit_at = 0.0
        last_phase_signature: tuple[str, str, str, str] | None = None

        def emit(
            progress: int,
            *,
            bytes_downloaded: int | None = None,
            bytes_total: int | None = None,
            phase: str | None = None,
            phase_message: str | None = None,
            write_status: str | None = None,
            merge_status: str | None = None,
        ) -> None:
            nonlocal last_progress, last_speed_bps, last_emit_at, last_phase_signature
            if not self.is_running:
                return
            try:
                normalized = max(0, min(100, int(progress)))
            except (TypeError, ValueError):
                return
            phase_signature = (
                str(phase or ""),
                str(phase_message or ""),
                str(write_status or ""),
                str(merge_status or ""),
            )
            self._apply_download_phase(
                phase=phase,
                phase_message=phase_message,
                write_status=write_status,
                merge_status=merge_status,
            )
            snapshot = telemetry.record(
                self.video,
                progress=normalized,
                bytes_downloaded=bytes_downloaded,
                bytes_total=bytes_total,
            )
            now = time.monotonic()
            should_emit = normalized != last_progress
            if not should_emit and phase_signature != last_phase_signature and any(phase_signature):
                should_emit = True
            if not should_emit and snapshot.speed_bps != last_speed_bps:
                should_emit = now - last_emit_at >= telemetry.MIN_SAMPLE_INTERVAL_SECONDS
            if not should_emit:
                return
            last_progress = normalized
            last_speed_bps = snapshot.speed_bps
            last_phase_signature = phase_signature
            last_emit_at = now
            if not self.is_running:
                return
            self.sig_progress.emit(self.video.id, normalized)

        return emit

    def _apply_download_phase(
        self,
        *,
        phase: str | None = None,
        phase_message: str | None = None,
        write_status: str | None = None,
        merge_status: str | None = None,
    ) -> None:
        """记录下载阶段元数据，供前端适配器生成实时任务快照。"""
        with self.video.meta_guard():
            meta = self.video.meta
            changed = False
            updates = {
                "download_phase": phase,
                "phase_message": phase_message,
                "write_status": write_status,
                "merge_status": merge_status,
            }
            for key, value in updates.items():
                if value is None:
                    continue
                text = str(value)
                if meta.get(key) != text:
                    meta[key] = text
                    changed = True
            if phase_message:
                events = list(meta.get("events") or [])
                event = {
                    "time": time.strftime("%H:%M:%S"),
                    "message": str(phase_message),
                }
                if not events or events[-1].get("message") != event["message"]:
                    events.append(event)
                    meta["events"] = events[-6:]
                    changed = True
            if changed:
                meta["phase_updated_at"] = time.time()

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
        return resolve_task_save_directory(self.video, self.save_dir)

    def _infer_extension(self) -> str:
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
        """按已持久化的前端命名规则生成文件名。"""
        from datetime import datetime

        from app.config import cfg
        from app.config.settings import CURRENT_FILENAME_TEMPLATE

        preferred_name = self.video.meta.get("preferred_filename")
        current_name = str(preferred_name or self.video.title or "").strip()
        template = str(cfg.get("common", "filename_template", CURRENT_FILENAME_TEMPLATE) or CURRENT_FILENAME_TEMPLATE).strip()
        raw_name = current_name
        if template and template != CURRENT_FILENAME_TEMPLATE:
            now = datetime.now()
            context = {
                "title": current_name,
                "platform": str(self.video.source or ""),
                "source": str(self.video.source or ""),
                "id": str(self.video.id or ""),
                "date": now.strftime("%Y%m%d"),
                "datetime": now.strftime("%Y%m%d_%H%M%S"),
                "index": str(
                    self.video.meta.get("index")
                    or self.video.meta.get("sequence")
                    or self.video.meta.get("part_index")
                    or ""
                ),
            }

            class _Missing(dict):
                def __missing__(self, key):
                    return ""

            try:
                raw_name = template.format_map(_Missing(context)).strip() or current_name
            except (KeyError, ValueError, IndexError):
                raw_name = current_name
        desc = sanitize_filename(raw_name)
        base_name, current_ext = os.path.splitext(desc)
        safe_name = base_name if current_ext.lower() == ext.lower() else desc
        safe_name = safe_name[:200] or f"{self.video.source}_{self.video.id}"
        return f"{safe_name}{ext}"

    def _remember_output_path(self, filepath: str) -> None:
        """保存当前输出文件名，使前端阶段快照与实际落盘目标一致。"""
        if not isinstance(getattr(self.video, "meta", None), dict):
            self.video.meta = {}
        filename = os.path.basename(filepath)
        self.video.meta["output_filename"] = filename
        self.video.meta["filename"] = filename
        self.video.meta["save_dir"] = os.path.dirname(filepath)

    def _ensure_unique_path(self, filepath: str) -> str:
        """原子预留一个未占用路径，避免并发任务选中同一目标文件。"""
        base, ext = os.path.splitext(filepath)
        index = 0
        while True:
            candidate = filepath if index == 0 else f"{base}_{index}{ext}"
            reservation = os.path.join(
                os.path.dirname(candidate),
                f".{os.path.basename(candidate)}.ucrawl-reserve",
            )
            try:
                descriptor = os.open(reservation, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                index += 1
                continue
            try:
                os.write(descriptor, str(os.getpid()).encode("ascii", errors="ignore"))
            finally:
                os.close(descriptor)
            if os.path.exists(candidate):
                try:
                    os.remove(reservation)
                except OSError:
                    pass
                index += 1
                continue
            self._path_reservations.append(reservation)
            return candidate

    def _release_output_path_reservations(self) -> None:
        reservations, self._path_reservations = self._path_reservations, []
        for reservation in reservations:
            try:
                os.remove(reservation)
            except FileNotFoundError:
                continue
            except OSError as exc:
                debug_logger.log_exception(
                    "DownloadWorker",
                    "release_output_path_reservation",
                    exc,
                    details={"reservation": reservation},
                    trace_id=self._trace_id(),
                )

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
    def __init__(self, max_concurrent: int | None = None):
        self.task_started = CallbackSignal()
        self.task_progress = CallbackSignal()
        self.task_finished = CallbackSignal()
        self.task_error = CallbackSignal()
        DownloadManagerCore.__init__(self, max_concurrent=max_concurrent)

    def _create_worker(self, video: VideoItem, save_dir: str):
        return DownloadWorker(video, save_dir)

    def _connect_worker_callbacks(self, worker) -> None:
        super()._connect_worker_callbacks(worker)

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
        for signal_name in ("sig_start", "sig_progress", "sig_finished", "sig_error", "finished"):
            signal = getattr(worker, signal_name, None)
            disconnect = getattr(signal, "disconnect", None)
            if callable(disconnect):
                disconnect()
        worker._completion_callback = None
        worker.deleteLater()
