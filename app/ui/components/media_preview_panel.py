"""Media preview panel for video playback and image preview."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.mkv_repair_service import MkvPlaybackRepairService
from app.ui.task_runtime import LongTaskRunner, ShortTaskRunner, TaskCancelToken
from app.ui.widgets import ClickableVideoWidget

@dataclass(slots=True)
class _RepairUiState:
    source_path: str
    phase: str
    percent: int
    message: str
    repaired_path: str = ""

class MediaPreviewPanel(QFrame):
    """Preview local media and repair only when playback is actually not seekable."""

    sig_toggle_fullscreen = pyqtSignal()
    sig_switch_preview = pyqtSignal(int)
    sig_auto_next_preview = pyqtSignal()
    sig_repair_progress = pyqtSignal(str, int, str)
    sig_repair_finished = pyqtSignal(str, str, str, bool, str)
    sig_repair_commit_progress = pyqtSignal(str, int, str)
    sig_repair_commit_finished = pyqtSignal(str, str, bool, str)

    def __init__(self, style_provider, repair_service: MkvPlaybackRepairService | None = None):
        super().__init__(style_provider if isinstance(style_provider, QWidget) else None)
        self._style_provider = style_provider
        self._repair_service = repair_service or MkvPlaybackRepairService()
        self._active_video_source: str | None = None
        self._repair_candidate_path: str | None = None
        self._repair_candidate_key: str | None = None
        self._repairing_sources: set[str] = set()
        self._committing_sources: set[str] = set()
        self._repair_states: dict[str, _RepairUiState] = {}
        self._pending_cache_cleanup: set[str] = set()
        self._repair_lock = threading.Lock()
        self._cleanup_requested = threading.Event()
        self._cleanup_done = False
        self._long_task_runner = LongTaskRunner(self)
        self._short_task_runner = ShortTaskRunner(self, max_thread_count=2)
        self._pending_cleanup_token: TaskCancelToken | None = None
        self.current_image_path: str | None = None
        self.is_slider_pressed = False
        self._end_emitted_for_source = False

        self.setObjectName("ContentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.vid_container = QFrame()
        self.vid_container.setObjectName("VideoContainer")
        vid_layout = QVBoxLayout(self.vid_container)
        vid_layout.setContentsMargins(0, 0, 0, 0)
        vid_layout.setSpacing(0)

        self.vid_w = ClickableVideoWidget()
        self.vid_w.sig_double_click.connect(self.sig_toggle_fullscreen.emit)
        vid_layout.addWidget(self.vid_w)

        self.img_lbl = QLabel()
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setObjectName("ImageLabel")
        self.img_lbl.setMinimumSize(1, 1)
        self.img_lbl.hide()

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.vid_w)

        self.destroyed.connect(self._cleanup_before_destroy)

        self.repair_panel = QFrame()
        self.repair_panel.setObjectName("RepairPanel")
        self.repair_panel.setFixedHeight(34)
        repair_layout = QHBoxLayout(self.repair_panel)
        repair_layout.setContentsMargins(12, 4, 12, 4)
        repair_layout.setSpacing(10)

        self.lbl_repair = QLabel("正在修复播放进度，不影响当前播放")
        self.lbl_repair.setObjectName("RepairLabel")
        self.repair_progress = QProgressBar()
        self.repair_progress.setRange(0, 100)
        self.repair_progress.setValue(0)
        repair_layout.addWidget(self.lbl_repair)
        repair_layout.addWidget(self.repair_progress, 1)
        self.repair_panel.hide()

        self.ctrls = QFrame()
        self.ctrls.setObjectName("ControlPanel")
        self.ctrls.setFixedHeight(50)
        controls_layout = QHBoxLayout(self.ctrls)
        controls_layout.setContentsMargins(15, 0, 15, 0)
        controls_layout.setSpacing(15)

        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_play.setObjectName("PlayBtn")
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_prev = QPushButton()
        self.btn_prev.setFixedSize(32, 32)
        self.btn_prev.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.btn_prev.setObjectName("PrevBtn")
        self.btn_prev.setToolTip("上一个资源")
        self.btn_prev.clicked.connect(lambda: self.sig_switch_preview.emit(-1))

        self.btn_next = QPushButton()
        self.btn_next.setFixedSize(32, 32)
        self.btn_next.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.setObjectName("NextBtn")
        self.btn_next.setToolTip("下一个资源")
        self.btn_next.clicked.connect(lambda: self.sig_switch_preview.emit(1))

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        self.player.mediaStatusChanged.connect(self.on_player_media_status_changed)
        self.player.errorOccurred.connect(self.on_player_error)

        self._duration_probe_timer = QTimer(self)
        self._duration_probe_timer.setSingleShot(True)
        self._duration_probe_timer.setInterval(5000)
        self._duration_probe_timer.timeout.connect(self._start_repair_if_seek_unavailable)

        self._repair_hide_timer = QTimer(self)
        self._repair_hide_timer.setSingleShot(True)
        self._repair_hide_timer.timeout.connect(self._hide_repair_status)

        self.lbl_time = QLabel("00:00")
        self.lbl_time.setObjectName("TimeLabel")

        self.btn_fullscreen = QPushButton("[ 全屏 ]")
        self.btn_fullscreen.setFixedHeight(32)
        self.btn_fullscreen.setObjectName("FullscreenBtn")
        self.btn_fullscreen.setToolTip("沉浸模式 (双击画面)")
        self.btn_fullscreen.clicked.connect(self.sig_toggle_fullscreen.emit)

        controls_layout.addWidget(self.btn_play)
        controls_layout.addWidget(self.btn_prev)
        controls_layout.addWidget(self.btn_next)
        controls_layout.addWidget(self.slider)
        controls_layout.addWidget(self.lbl_time)
        controls_layout.addWidget(self.btn_fullscreen)

        layout.addWidget(self.vid_container)
        layout.addWidget(self.img_lbl)
        layout.addWidget(self.repair_panel)
        layout.addWidget(self.ctrls)

        self.sig_repair_progress.connect(self._on_repair_progress, Qt.ConnectionType.QueuedConnection)
        self.sig_repair_finished.connect(self._on_repair_finished, Qt.ConnectionType.QueuedConnection)
        self.sig_repair_commit_progress.connect(self._on_repair_commit_progress, Qt.ConnectionType.QueuedConnection)
        self.sig_repair_commit_finished.connect(self._on_repair_commit_finished, Qt.ConnectionType.QueuedConnection)

    def _on_slider_pressed(self) -> None:
        self.is_slider_pressed = True

    def show_image(self, image_path: str) -> None:
        self.vid_container.hide()
        self.img_lbl.show()
        self.release_media()
        self.current_image_path = image_path
        self.scale_image_to_fit()

    def play_video(self, video_path: str) -> None:
        self.current_image_path = None
        self.img_lbl.hide()
        self.vid_container.show()
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.lbl_time.setText("00:00")
        self._hide_repair_status()
        self._duration_probe_timer.stop()

        source_key = self._normalize_path(video_path)
        self._active_video_source = source_key
        self._prune_repair_states(source_key)
        self._end_emitted_for_source = False
        self._repair_candidate_path = None
        self._repair_candidate_key = None

        playable_path = self._repair_service.cached_playable_path(video_path)
        if self._normalize_path(playable_path) == source_key:
            self._remember_repair_candidate(video_path, playable_path, source_key)
        elif not self._is_busy(source_key):
            self._set_repair_state(
                source_key,
                video_path,
                "committing",
                0,
                "已找到修复缓存，正在写回原文件",
                playable_path,
            )
            QTimer.singleShot(500, lambda: self._start_commit_to_source(source_key, video_path, playable_path))

        self.player.setSource(QUrl.fromLocalFile(playable_path))
        self._schedule_pending_cache_cleanup()
        self._restore_repair_status(source_key)
        self.player.setVideoOutput(self.vid_w)
        self.player.play()
        self._set_play_button_paused()

    def stop_playback(self) -> None:
        self.player.stop()
        self._set_play_button_stopped()

    def release_media(self) -> None:
        self._active_video_source = None
        self._end_emitted_for_source = False
        self._repair_candidate_path = None
        self._repair_candidate_key = None
        self._duration_probe_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setVideoOutput(None)
        self._set_play_button_stopped()
        self._hide_repair_status()
        self._schedule_pending_cache_cleanup()

    def cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self._cleanup_requested.set()
        self.current_image_path = None
        for signal, slot in (
            (self.player.positionChanged, self.on_player_position_changed),
            (self.player.durationChanged, self.on_player_duration_changed),
            (self.player.mediaStatusChanged, self.on_player_media_status_changed),
            (self.player.errorOccurred, self.on_player_error),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self.release_media()
        self._short_task_runner.cancel_all(timeout_ms=5000)
        self._long_task_runner.cancel_all(timeout_ms=10000)
        with self._repair_lock:
            self._repair_states.clear()
            self._pending_cache_cleanup.clear()

    def deleteLater(self) -> None:
        self.cleanup()
        super().deleteLater()

    def _cleanup_before_destroy(self, *_args) -> None:
        self.cleanup()

    def scale_image_to_fit(self) -> None:
        if not self.current_image_path or not self.img_lbl.isVisible():
            return
        pixmap = QPixmap(self.current_image_path)
        if pixmap.isNull():
            return
        scaled_pixmap = pixmap.scaled(
            self.img_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.img_lbl.setPixmap(scaled_pixmap)

    def resize_media(self) -> None:
        QTimer.singleShot(10, self.scale_image_to_fit)

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._set_play_button_stopped()
        else:
            self.player.play()
            self._set_play_button_paused()

    def on_slider_released(self) -> None:
        self.is_slider_pressed = False
        self.player.setPosition(self.slider.value())

    def on_player_duration_changed(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        if duration > 0:
            self._duration_probe_timer.stop()

    def on_player_position_changed(self, pos: int) -> None:
        if not self.is_slider_pressed:
            self.slider.setValue(pos)
        self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")
        if pos >= 5000 and self._seek_is_unavailable():
            self._schedule_seek_repair_probe()

    def on_player_media_status_changed(self, status) -> None:
        loaded_statuses = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        }
        if status in loaded_statuses and self._seek_is_unavailable():
            self._schedule_seek_repair_probe()
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._set_play_button_stopped()
            if self._active_video_source and not self._end_emitted_for_source:
                self._end_emitted_for_source = True
                self.sig_auto_next_preview.emit()

    def on_player_error(self, _error, _message: str = "") -> None:
        self._start_repair_if_seek_unavailable(force=True)

    def _set_play_button_stopped(self) -> None:
        self.btn_play.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _set_play_button_paused(self) -> None:
        self.btn_play.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def _remember_repair_candidate(self, source_path: str, playable_path: str, source_key: str) -> None:
        if self._normalize_path(source_path) != self._normalize_path(playable_path):
            return
        is_repairable = getattr(self._repair_service, "is_repairable_path", self._repair_service.is_mkv_path)
        if not is_repairable(source_path):
            return
        self._repair_candidate_path = source_path
        self._repair_candidate_key = source_key

    def _schedule_seek_repair_probe(self) -> None:
        if not self._repair_candidate_path or not self._repair_candidate_key:
            return
        if self._active_video_source != self._repair_candidate_key:
            return
        if self._duration_probe_timer.isActive() or self._is_busy(self._repair_candidate_key):
            return
        self._duration_probe_timer.start()

    def _start_repair_if_seek_unavailable(self, force: bool = False) -> None:
        if not self._repair_candidate_path or not self._repair_candidate_key:
            return
        if self._active_video_source != self._repair_candidate_key:
            return
        if not force and not self._seek_is_unavailable():
            return
        self._start_background_repair(self._repair_candidate_path, self._repair_candidate_key)

    def _start_background_repair(self, video_path: str, source_key: str) -> None:
        if self._cleanup_requested.is_set():
            return
        with self._repair_lock:
            if source_key in self._repairing_sources:
                self._restore_repair_status(source_key)
                return
            self._repairing_sources.add(source_key)

        self._set_repair_state(source_key, video_path, "repairing", 0, "正在修复播放进度，不影响当前播放")
        try:
            started = self._start_worker_thread(
                name="playback-repair",
                target=self._repair_video_worker,
                args=(video_path, source_key),
            )
        except Exception:
            with self._repair_lock:
                self._repairing_sources.discard(source_key)
            raise
        if not started:
            with self._repair_lock:
                self._repairing_sources.discard(source_key)

    def _repair_video_worker(self, video_path: str, source_key: str) -> None:
        def progress(percent: int, message: str) -> None:
            if self._cleanup_requested.is_set():
                return
            self.sig_repair_progress.emit(source_key, percent, message)

        try:
            result = self._repair_service.repair_for_playback(
                video_path,
                progress_callback=progress,
                cancel_check=self._cleanup_requested.is_set,
            )
            if not self._cleanup_requested.is_set():
                self.sig_repair_finished.emit(
                    source_key,
                    video_path,
                    result.playable_path,
                    result.repaired,
                    result.message,
                )
        finally:
            with self._repair_lock:
                self._repairing_sources.discard(source_key)

    def _start_commit_to_source(self, source_key: str, source_path: str, repaired_path: str) -> None:
        if not source_path or not repaired_path:
            return
        if self._cleanup_requested.is_set():
            return
        with self._repair_lock:
            if source_key in self._committing_sources:
                self._restore_repair_status(source_key)
                return
            self._committing_sources.add(source_key)

        self._set_repair_state(source_key, source_path, "committing", 0, "正在写回原视频文件", repaired_path)
        try:
            started = self._start_worker_thread(
                name="playback-repair-commit",
                target=self._commit_repair_worker,
                args=(source_key, source_path, repaired_path),
            )
        except Exception:
            with self._repair_lock:
                self._committing_sources.discard(source_key)
            raise
        if not started:
            with self._repair_lock:
                self._committing_sources.discard(source_key)

    def _commit_repair_worker(self, source_key: str, source_path: str, repaired_path: str) -> None:
        def progress(percent: int, message: str) -> None:
            if self._cleanup_requested.is_set():
                return
            self.sig_repair_commit_progress.emit(source_key, percent, message)

        try:
            writer = getattr(self._repair_service, "write_repair_to_source", None)
            if writer is None:
                self.sig_repair_commit_finished.emit(
                    source_key,
                    repaired_path,
                    False,
                    "repair service does not support source commit",
                )
                return
            result = writer(
                source_path,
                repaired_path,
                progress_callback=progress,
                cancel_check=self._cleanup_requested.is_set,
            )
            if not self._cleanup_requested.is_set():
                self.sig_repair_commit_finished.emit(source_key, repaired_path, result.committed, result.message)
        finally:
            with self._repair_lock:
                self._committing_sources.discard(source_key)

    def _on_repair_progress(self, source_key: str, percent: int, message: str) -> None:
        if self._cleanup_requested.is_set():
            return
        state = self._repair_states.get(source_key)
        source_path = state.source_path if state else (self._repair_candidate_path or "")
        self._set_repair_state(
            source_key,
            source_path,
            "repairing",
            percent,
            message or "正在修复播放进度，不影响当前播放",
        )

    def _on_repair_finished(
        self,
        source_key: str,
        source_path: str,
        playable_path: str,
        repaired: bool,
        message: str,
    ) -> None:
        if self._cleanup_requested.is_set():
            return
        if repaired:
            self._set_repair_state(source_key, source_path, "repairing", 100, "修复完成，准备写回原文件", playable_path)
            if self._active_video_source == source_key and playable_path and self._seek_is_unavailable():
                self._switch_to_repaired_source(playable_path)
                self._show_repair_status(100, "修复完成，已切换到可拖动缓存")
            elif self._active_video_source == source_key:
                self._show_repair_status(100, "修复完成，准备写回原文件")
            QTimer.singleShot(800, lambda: self._start_commit_to_source(source_key, source_path, playable_path))
            return

        failure = f"修复失败: {message or '未知错误'}"
        self._set_repair_state(source_key, source_path, "failed", 0, failure)
        if self._active_video_source == source_key:
            self._schedule_repair_status_hide(8000)

    def _on_repair_commit_progress(self, source_key: str, percent: int, message: str) -> None:
        if self._cleanup_requested.is_set():
            return
        state = self._repair_states.get(source_key)
        source_path = state.source_path if state else (self._repair_candidate_path or "")
        repaired_path = state.repaired_path if state else ""
        self._set_repair_state(
            source_key,
            source_path,
            "committing",
            percent,
            message or "正在写回原视频文件",
            repaired_path,
        )

    def _on_repair_commit_finished(self, source_key: str, repaired_path: str, committed: bool, message: str) -> None:
        if self._cleanup_requested.is_set():
            return
        state = self._repair_states.get(source_key)
        source_path = state.source_path if state else (self._repair_candidate_path or "")
        if committed:
            self._set_repair_state(source_key, source_path, "done", 100, "本地视频文件已修复", repaired_path)
            self._cleanup_committed_cache(source_key, repaired_path)
            if self._active_video_source == source_key:
                self._schedule_repair_status_hide(3000)
            return

        failure = f"缓存可用，但写回原文件失败: {message or '未知错误'}"
        self._set_repair_state(source_key, source_path, "failed", 0, failure, repaired_path)
        if self._active_video_source == source_key:
            self._schedule_repair_status_hide(8000)

    def _switch_to_repaired_source(self, playable_path: str) -> None:
        position = max(self.player.position(), self.slider.value())
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.player.setSource(QUrl.fromLocalFile(playable_path))
        if was_playing:
            self.player.play()
            self._set_play_button_paused()
        if position > 0:
            QTimer.singleShot(250, lambda: self.player.setPosition(position))

    def _set_repair_state(
        self,
        source_key: str,
        source_path: str,
        phase: str,
        percent: int,
        message: str,
        repaired_path: str = "",
    ) -> None:
        state = _RepairUiState(source_path, phase, max(0, min(100, percent)), message, repaired_path)
        self._repair_states[source_key] = state
        if self._active_video_source == source_key:
            self._show_repair_status(state.percent, state.message)

    def _restore_repair_status(self, source_key: str) -> None:
        state = self._repair_states.get(source_key)
        if state is None:
            return
        self._show_repair_status(state.percent, state.message)
        if state.phase == "done":
            self._schedule_repair_status_hide(3000)
        elif state.phase == "failed":
            self._schedule_repair_status_hide(8000)

    def _show_repair_status(self, percent: int, message: str) -> None:
        self._repair_hide_timer.stop()
        self.repair_progress.setValue(max(0, min(100, percent)))
        self.lbl_repair.setText(message)
        self.repair_panel.show()

    def _schedule_repair_status_hide(self, delay_ms: int) -> None:
        self._repair_hide_timer.start(delay_ms)

    def _hide_repair_status(self) -> None:
        self._repair_hide_timer.stop()
        self.repair_progress.setValue(0)
        self.lbl_repair.setText("正在修复播放进度，不影响当前播放")
        self.repair_panel.hide()

    def _cleanup_committed_cache(self, source_key: str, repaired_path: str) -> None:
        if not repaired_path:
            return
        repaired_key = self._normalize_path(repaired_path)
        if self._active_video_source == source_key and self._normalize_path(self._current_player_path()) == repaired_key:
            self._pending_cache_cleanup.add(repaired_path)
            self._schedule_pending_cache_cleanup()
            return
        discard_cache_file = getattr(self._repair_service, "discard_cache_file", lambda _path: False)
        if not discard_cache_file(repaired_path):
            self._pending_cache_cleanup.add(repaired_path)

    def _schedule_pending_cache_cleanup(self) -> None:
        QTimer.singleShot(500, self._submit_pending_cache_cleanup)

    def _submit_pending_cache_cleanup(self) -> None:
        if self._cleanup_requested.is_set():
            return
        with self._repair_lock:
            if not self._pending_cache_cleanup:
                return
            if self._pending_cleanup_token is not None:
                self._pending_cleanup_token.cancel()
        self._pending_cleanup_token = self._short_task_runner.submit(
            name="cleanup-repair-cache",
            fn=self._cleanup_pending_cache_files,
        )

    def _cleanup_pending_cache_files(self, token: TaskCancelToken | None = None) -> None:
        with self._repair_lock:
            pending = list(self._pending_cache_cleanup)
        if not pending or (token is not None and token.is_cancelled()):
            return
        current = self._normalize_path(self._current_player_path())
        for path in pending:
            if token is not None and token.is_cancelled():
                return
            if current and self._normalize_path(path) == current:
                continue
            discard_cache_file = getattr(self._repair_service, "discard_cache_file", lambda _path: False)
            if discard_cache_file(path):
                with self._repair_lock:
                    self._pending_cache_cleanup.discard(path)

    def _current_player_path(self) -> str:
        source = self.player.source()
        if source.isLocalFile():
            return source.toLocalFile()
        return ""

    def _seek_is_unavailable(self) -> bool:
        return self.player.duration() <= 0 and self.slider.maximum() <= 0

    def _is_busy(self, source_key: str) -> bool:
        with self._repair_lock:
            return source_key in self._repairing_sources or source_key in self._committing_sources

    def _prune_repair_states(self, active_source_key: str) -> None:
        with self._repair_lock:
            stale = [key for key in self._repair_states if key != active_source_key]
            for key in stale:
                self._repair_states.pop(key, None)

    def _start_worker_thread(self, *, name: str, target, args: tuple) -> bool:
        if self._cleanup_requested.is_set():
            return False
        self._long_task_runner.submit(name=name, fn=target, args=args)
        return True

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def format_time(ms: int) -> str:
        seconds = (ms // 1000) % 60
        minutes = ms // 60000
        return f"{minutes:02}:{seconds:02}"
