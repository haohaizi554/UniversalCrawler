"""提供本地视频播放与图片预览。"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from PyQt6.QtCore import QSizeF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
try:
    from PyQt6.QtMultimedia import QMediaMetaData
except ImportError:  # pragma: no cover - 取决于 PyQt6 构建内容
    QMediaMetaData = None
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.debug_logger import debug_logger
from app.services.mkv_repair_service import MkvPlaybackRepairService
from app.services.playback_position_service import PlaybackPositionService
from shared.localization import normalize_language, tr
from app.ui.task_runtime import LongTaskRunner, ShortTaskRunner, TaskCancelToken

@dataclass(slots=True)
class _RepairUiState:
    source_path: str
    phase: str
    percent: int
    message: str
    repaired_path: str = ""


class _ClickableImageLabel(QLabel):
    sig_double_click = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.sig_double_click.emit()
        super().mouseDoubleClickEvent(event)


class _VideoGraphicsView(QGraphicsView):
    sig_double_click = pyqtSignal()

    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None) -> None:
        super().__init__(scene, parent)
        self._video_item = video_item
        self.setObjectName("VideoSurface")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = self.viewport().size()
        self.scene().setSceneRect(0, 0, size.width(), size.height())
        self._video_item.setSize(QSizeF(size.width(), size.height()))

    def mouseDoubleClickEvent(self, event) -> None:
        self.sig_double_click.emit()
        super().mouseDoubleClickEvent(event)


class _MediaFullscreenWindow(QWidget):
    def __init__(self, panel: "MediaPreviewPanel") -> None:
        super().__init__(None)
        self.panel = panel
        self._allow_close = False
        self.setObjectName("MediaFullscreenWindow")
        self.setWindowTitle("Universal Crawler Pro - Media")
        self.setWindowFlag(Qt.WindowType.Window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.panel.exit_media_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._allow_close:
            super().closeEvent(event)
            return
        event.ignore()
        self.panel.exit_media_fullscreen()

    def allow_close(self) -> None:
        self._allow_close = True


class MediaPreviewPanel(QFrame):
    """预览本地媒体，仅在确认播放不可 seek 时触发修复。"""

    sig_toggle_fullscreen = pyqtSignal()
    sig_switch_preview = pyqtSignal(int)
    sig_auto_next_preview = pyqtSignal()
    sig_repair_progress = pyqtSignal(str, int, str)
    sig_repair_finished = pyqtSignal(str, str, str, bool, str)
    sig_repair_commit_progress = pyqtSignal(str, int, str)
    sig_repair_commit_finished = pyqtSignal(str, str, bool, str)
    sig_media_metadata_detected = pyqtSignal(str, dict)
    sig_playback_position_ready = pyqtSignal(str, int)
    sig_cached_playable_path_ready = pyqtSignal(str, str, str)

    def __init__(
        self,
        style_provider,
        repair_service: MkvPlaybackRepairService | None = None,
        playback_position_service: PlaybackPositionService | None = None,
    ):
        super().__init__(style_provider if isinstance(style_provider, QWidget) else None)
        self._style_provider = style_provider
        self._owns_repair_service = repair_service is None
        self._repair_service = repair_service or MkvPlaybackRepairService(cleanup_on_init=False)
        self._playback_position_service = playback_position_service or PlaybackPositionService(load_on_init=False)
        self._active_video_source: str | None = None
        self._active_source_path: str | None = None
        self._repair_candidate_path: str | None = None
        self._repair_candidate_key: str | None = None
        self._repairing_sources: set[str] = set()
        self._committing_sources: set[str] = set()
        self._repair_states: dict[str, _RepairUiState] = {}
        self._pending_cache_cleanup: set[str] = set()
        self._pending_cached_playable_lookups: set[str] = set()
        self._pending_repair_after_cache_lookup: set[str] = set()
        self._repair_lock = threading.Lock()
        self._cleanup_requested = threading.Event()
        self._cleanup_done = False
        self._long_task_runner = LongTaskRunner(self)
        self._short_task_runner = ShortTaskRunner(self, max_thread_count=2)
        self._playback_position_task_runner = ShortTaskRunner(self, max_thread_count=1)
        self._pending_cleanup_token: TaskCancelToken | None = None
        self.current_image_path: str | None = None
        self.is_slider_pressed = False
        self._end_emitted_for_source = False
        self._last_metadata_emit_signature: tuple | None = None
        self._fullscreen_window: _MediaFullscreenWindow | None = None
        self._fullscreen_restore: tuple[QWidget | None, QVBoxLayout | None, int, int] | None = None
        self._remember_position_enabled = True
        self._autoplay_next_enabled = True
        self._manual_image_switch = True
        self._image_auto_advance_interval_ms = 5000
        self._saved_positions: dict[str, int] = {}
        self._last_position_flush_at: dict[str, float] = {}
        self._language = "zh-CN"

        self.setObjectName("ContentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.vid_container = QFrame()
        self.vid_container.setObjectName("VideoContainer")
        vid_layout = QVBoxLayout(self.vid_container)
        vid_layout.setContentsMargins(0, 0, 0, 0)
        vid_layout.setSpacing(0)

        self.video_scene = QGraphicsScene(self)
        self.video_scene.setBackgroundBrush(QColor(0, 0, 0, 0))
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_scene.addItem(self.video_item)
        self.vid_w = _VideoGraphicsView(self.video_scene, self.video_item)
        self.vid_w.sig_double_click.connect(self.toggle_media_fullscreen)
        vid_layout.addWidget(self.vid_w)

        self.img_lbl = _ClickableImageLabel()
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setObjectName("ImageLabel")
        self.img_lbl.setMinimumSize(1, 1)
        self.img_lbl.sig_double_click.connect(self.toggle_media_fullscreen)
        self.img_lbl.hide()

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_item)

        # 宿主关闭时显式调用 `cleanup()`；`deleteLater()` 也先执行同一幂等清理，当前不依赖 `QObject.destroyed`。

        self.repair_panel = QFrame()
        self.repair_panel.setObjectName("RepairPanel")
        self.repair_panel.setFixedHeight(34)
        repair_layout = QHBoxLayout(self.repair_panel)
        repair_layout.setContentsMargins(12, 4, 12, 4)
        repair_layout.setSpacing(10)

        self.lbl_repair = QLabel(self._t("正在修复播放进度，不影响当前播放"))
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
        self.btn_prev.setToolTip(self._t("上一个资源"))
        self.btn_prev.clicked.connect(lambda: self.sig_switch_preview.emit(-1))

        self.btn_next = QPushButton()
        self.btn_next.setFixedSize(32, 32)
        self.btn_next.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.setObjectName("NextBtn")
        self.btn_next.setToolTip(self._t("下一个资源"))
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

        self._image_auto_advance_timer = QTimer(self)
        self._image_auto_advance_timer.setSingleShot(True)
        self._image_auto_advance_timer.setInterval(self._image_auto_advance_interval_ms)
        self._image_auto_advance_timer.timeout.connect(self._on_image_auto_advance_timeout)

        self.lbl_time = QLabel("00:00")
        self.lbl_time.setObjectName("TimeLabel")

        self.btn_fullscreen = QPushButton(self._fullscreen_button_text(False))
        self.btn_fullscreen.setFixedHeight(32)
        self.btn_fullscreen.setObjectName("FullscreenBtn")
        self.btn_fullscreen.setToolTip(self._t("媒体全屏（双击画面）"))
        self.btn_fullscreen.clicked.connect(self.toggle_media_fullscreen)

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
        self.sig_playback_position_ready.connect(self._on_playback_position_ready, Qt.ConnectionType.QueuedConnection)
        self.sig_cached_playable_path_ready.connect(
            self._on_cached_playable_path_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        if self._owns_repair_service:
            self._submit_repair_cache_startup_cleanup()

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.btn_prev.setToolTip(self._t("上一个资源"))
        self.btn_next.setToolTip(self._t("下一个资源"))
        self.btn_fullscreen.setToolTip(self._t("媒体全屏（双击画面）"))
        self.btn_fullscreen.setText(self._fullscreen_button_text(self._fullscreen_window is not None))
        if not self.repair_panel.isVisible():
            self.lbl_repair.setText(self._t("正在修复播放进度，不影响当前播放"))

    def _t(self, text: object) -> str:
        return tr(str(text or ""), self._language)

    def _fullscreen_button_text(self, active: bool) -> str:
        label = self._t("退出") if active else self._t("全屏")
        return f"[ {label} ]"

    def _on_slider_pressed(self) -> None:
        self.is_slider_pressed = True

    def apply_playback_settings(self, settings: dict | None) -> None:
        settings = settings or {}
        self._remember_position_enabled = bool(settings.get("remember_position", True))
        self._autoplay_next_enabled = bool(settings.get("autoplay_next", True))
        self._manual_image_switch = bool(settings.get("manual_image_switch", True))
        try:
            interval_seconds = int(settings.get("image_auto_advance_interval_seconds", 5) or 5)
        except (TypeError, ValueError):
            interval_seconds = 5
        if interval_seconds not in {1, 3, 5, 10}:
            interval_seconds = 5
        self._image_auto_advance_interval_ms = interval_seconds * 1000
        self._image_auto_advance_timer.setInterval(self._image_auto_advance_interval_ms)
        if not self._remember_position_enabled:
            self._saved_positions.clear()
            self._last_position_flush_at.clear()
            self._submit_playback_position_clear()
        self._refresh_image_auto_advance_timer()

    def show_image(self, image_path: str) -> None:
        self.vid_container.hide()
        self.img_lbl.show()
        self.release_media()
        self.current_image_path = image_path
        self.scale_image_to_fit()
        self._refresh_image_auto_advance_timer()

    def play_video(self, video_path: str) -> None:
        self._image_auto_advance_timer.stop()
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
        self._active_source_path = video_path
        self._last_metadata_emit_signature = None
        self._prune_repair_states(source_key)
        self._end_emitted_for_source = False
        self._repair_candidate_path = None
        self._repair_candidate_key = None

        self._remember_repair_candidate(video_path, video_path, source_key)
        self.player.setSource(QUrl.fromLocalFile(video_path))
        self._submit_cached_playable_path_lookup(source_key, video_path)
        self._schedule_pending_cache_cleanup()
        self._restore_repair_status(source_key)
        self.player.setVideoOutput(self.video_item)
        self.player.play()
        self._restore_playback_position_later(source_key)
        self._set_play_button_paused()

    def stop_playback(self) -> None:
        self._persist_current_playback_position(force=True)
        self.player.stop()
        self._set_play_button_stopped()

    def release_media(self) -> None:
        self.exit_media_fullscreen()
        self._persist_current_playback_position(force=True)
        self._active_video_source = None
        self._active_source_path = None
        self._end_emitted_for_source = False
        self._last_metadata_emit_signature = None
        self._repair_candidate_path = None
        self._repair_candidate_key = None
        self._duration_probe_timer.stop()
        self._image_auto_advance_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setVideoOutput(None)
        self._set_play_button_stopped()
        self._hide_repair_status()
        self._schedule_pending_cache_cleanup()
        self._refresh_image_auto_advance_timer()

    def toggle_media_fullscreen(self) -> None:
        if self._fullscreen_window is not None:
            self.exit_media_fullscreen()
        else:
            self.enter_media_fullscreen()

    def enter_media_fullscreen(self) -> None:
        if self._fullscreen_window is not None:
            return
        parent = self.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        index = parent_layout.indexOf(self) if parent_layout is not None else -1
        stretch = parent_layout.stretch(index) if parent_layout is not None and index >= 0 and hasattr(parent_layout, "stretch") else 0
        if parent_layout is not None:
            parent_layout.removeWidget(self)
        window = _MediaFullscreenWindow(self)
        window.layout().addWidget(self)
        self._fullscreen_restore = (parent, parent_layout if isinstance(parent_layout, QVBoxLayout) else None, index, stretch)
        self._fullscreen_window = window
        self.btn_fullscreen.setText(self._fullscreen_button_text(True))
        window.showFullScreen()
        self.resize_media()
        self._resize_video_surface()

    def exit_media_fullscreen(self) -> None:
        window = self._fullscreen_window
        restore = self._fullscreen_restore
        if window is None:
            return
        window.layout().removeWidget(self)
        parent, parent_layout, index, stretch = restore or (None, None, -1, 0)
        self.setParent(parent)
        if parent_layout is not None:
            if index >= 0:
                parent_layout.insertWidget(index, self, stretch)
            else:
                parent_layout.addWidget(self, stretch)
        self.show()
        self._fullscreen_window = None
        self._fullscreen_restore = None
        self.btn_fullscreen.setText(self._fullscreen_button_text(False))
        window.allow_close()
        window.close()
        window.deleteLater()
        self.resize_media()
        self._resize_video_surface()

    def cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self.exit_media_fullscreen()
        self._cleanup_requested.set()
        self.current_image_path = None
        player = getattr(self, "player", None)
        if player is not None:
            for signal, slot in (
                (player.positionChanged, self.on_player_position_changed),
                (player.durationChanged, self.on_player_duration_changed),
                (player.mediaStatusChanged, self.on_player_media_status_changed),
                (player.errorOccurred, self.on_player_error),
            ):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            self.release_media()
        short_runner = getattr(self, "_short_task_runner", None)
        if short_runner is not None:
            short_runner.cancel_all(timeout_ms=5000)
        playback_position_runner = getattr(self, "_playback_position_task_runner", None)
        if playback_position_runner is not None:
            playback_position_runner.cancel_all(timeout_ms=5000)
        long_runner = getattr(self, "_long_task_runner", None)
        if long_runner is not None:
            long_runner.cancel_all(timeout_ms=10000)
        repair_lock = getattr(self, "_repair_lock", None)
        if repair_lock is not None:
            with repair_lock:
                self._repair_states.clear()
                self._pending_cache_cleanup.clear()
                self._pending_cached_playable_lookups.clear()
                self._pending_repair_after_cache_lookup.clear()

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
        QTimer.singleShot(10, self._resize_video_surface)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_video_surface()

    def _resize_video_surface(self) -> None:
        if not hasattr(self, "vid_w") or not hasattr(self, "video_scene") or not hasattr(self, "video_item"):
            return
        size = self.vid_w.viewport().size()
        self.video_scene.setSceneRect(0, 0, size.width(), size.height())
        self.video_item.setSize(QSizeF(size.width(), size.height()))

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
            self._emit_current_media_metadata(duration_ms=duration)

    def on_player_position_changed(self, pos: int) -> None:
        if not self.is_slider_pressed:
            self.slider.setValue(pos)
        self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")
        self._remember_current_playback_position(pos)
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
        if status in loaded_statuses:
            self._emit_current_media_metadata()
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._set_play_button_stopped()
            if self._active_video_source:
                self._saved_positions.pop(self._active_video_source, None)
                self._submit_playback_position_delete(self._active_video_source)
            if self._autoplay_next_enabled and self._active_video_source and not self._end_emitted_for_source:
                self._end_emitted_for_source = True
                self.sig_auto_next_preview.emit()

    def _remember_current_playback_position(self, position_ms: int) -> None:
        if not self._remember_position_enabled or not self._active_video_source:
            return
        duration_ms = max(0, int(self.player.duration() or 0))
        position_ms = max(0, int(position_ms or 0))
        if duration_ms > 0 and position_ms >= duration_ms - 1500:
            self._saved_positions.pop(self._active_video_source, None)
            return
        if position_ms >= 1000:
            self._saved_positions[self._active_video_source] = position_ms
            self._persist_current_playback_position(position_ms=position_ms, duration_ms=duration_ms)

    def _restore_playback_position_later(self, source_key: str) -> None:
        if not self._remember_position_enabled or not source_key:
            return
        position_ms = int(self._saved_positions.get(source_key) or 0)
        if position_ms <= 0:
            self._submit_playback_position_restore(source_key)
            return
        QTimer.singleShot(350, lambda key=source_key, pos=position_ms: self._restore_playback_position(key, pos))

    def _on_playback_position_ready(self, source_key: str, position_ms: int) -> None:
        if self._cleanup_requested.is_set() or not self._remember_position_enabled:
            return
        if self._active_video_source != source_key:
            return
        position_ms = max(0, int(position_ms or 0))
        if position_ms <= 0:
            return
        self._saved_positions[source_key] = position_ms
        QTimer.singleShot(350, lambda key=source_key, pos=position_ms: self._restore_playback_position(key, pos))

    def _restore_playback_position(self, source_key: str, position_ms: int) -> None:
        if self._active_video_source != source_key or not self._remember_position_enabled:
            return
        self.player.setPosition(max(0, int(position_ms)))

    def _submit_cached_playable_path_lookup(self, source_key: str, source_path: str) -> None:
        if self._cleanup_requested.is_set() or not source_key or not source_path:
            return
        with self._repair_lock:
            self._pending_cached_playable_lookups.add(source_key)

        def task(token: TaskCancelToken) -> None:
            if token.is_cancelled():
                return
            resolver = getattr(self._repair_service, "cached_playable_path", None)
            playable_path = str(source_path)
            if callable(resolver):
                try:
                    playable_path = str(resolver(source_path) or source_path)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    debug_logger.log_exception(
                        "MediaPreviewPanel",
                        "cached_playable_path_lookup",
                        exc,
                        details={"source_path": source_path},
                    )
                    playable_path = str(source_path)
            if token.is_cancelled():
                return
            self.sig_cached_playable_path_ready.emit(source_key, source_path, playable_path)

        self._short_task_runner.submit(name="cached-playable-path", fn=task)

    def _on_cached_playable_path_ready(self, source_key: str, source_path: str, playable_path: str) -> None:
        with self._repair_lock:
            self._pending_cached_playable_lookups.discard(source_key)
            repair_after_lookup = source_key in self._pending_repair_after_cache_lookup
            self._pending_repair_after_cache_lookup.discard(source_key)
        if self._cleanup_requested.is_set() or self._active_video_source != source_key:
            return
        if not playable_path:
            return
        if self._normalize_path(playable_path) == source_key:
            self._remember_repair_candidate(source_path, playable_path, source_key)
            if repair_after_lookup:
                QTimer.singleShot(0, lambda key=source_key: self._retry_repair_after_cache_lookup(key))
            return
        if self._is_busy(source_key):
            return
        self._repair_candidate_path = None
        self._repair_candidate_key = None
        self._set_repair_state(
            source_key,
            source_path,
            "committing",
            0,
            "已找到修复缓存，正在写回原文件",
            playable_path,
        )
        if self._normalize_path(self._current_player_path()) != self._normalize_path(playable_path):
            self._switch_to_repaired_source(playable_path)
        QTimer.singleShot(500, lambda: self._start_commit_to_source(source_key, source_path, playable_path))

    def _persist_current_playback_position(
        self,
        *,
        position_ms: int | None = None,
        duration_ms: int | None = None,
        force: bool = False,
    ) -> None:
        if not self._remember_position_enabled or not self._active_video_source:
            return
        if position_ms is None:
            position_ms = int(self.player.position() or 0)
        if duration_ms is None:
            duration_ms = int(self.player.duration() or 0)
        position_ms = max(0, int(position_ms or 0))
        duration_ms = max(0, int(duration_ms or 0))
        now = time.monotonic()
        last_flush = self._last_position_flush_at.get(self._active_video_source, 0.0)
        if not force and now - last_flush < 5.0:
            return
        self._last_position_flush_at[self._active_video_source] = now
        self._submit_playback_position_save(self._active_video_source, position_ms, duration_ms)

    def _submit_playback_position_restore(self, source_key: str) -> None:
        if self._cleanup_requested.is_set() or not source_key:
            return

        def task(token: TaskCancelToken) -> None:
            if token.is_cancelled():
                return
            position_ms = self._playback_position_service.get(source_key)
            if token.is_cancelled():
                return
            self.sig_playback_position_ready.emit(source_key, int(position_ms or 0))

        self._playback_position_task_runner.submit(name="restore-playback-position", fn=task)

    def _submit_playback_position_save(self, source_key: str, position_ms: int, duration_ms: int) -> None:
        if self._cleanup_requested.is_set() or not source_key:
            return

        def task(token: TaskCancelToken) -> None:
            if token.is_cancelled():
                return
            self._playback_position_service.save(
                source_key,
                position_ms,
                duration_ms=duration_ms,
            )

        self._playback_position_task_runner.submit(name="save-playback-position", fn=task)

    def _submit_playback_position_delete(self, source_key: str) -> None:
        if self._cleanup_requested.is_set() or not source_key:
            return

        def task(token: TaskCancelToken) -> None:
            if not token.is_cancelled():
                self._playback_position_service.delete(source_key)

        self._playback_position_task_runner.submit(name="delete-playback-position", fn=task)

    def _submit_playback_position_clear(self) -> None:
        if self._cleanup_requested.is_set():
            return

        def task(token: TaskCancelToken) -> None:
            if not token.is_cancelled():
                self._playback_position_service.clear()

        self._playback_position_task_runner.submit(name="clear-playback-position", fn=task)

    def _refresh_image_auto_advance_timer(self) -> None:
        if not hasattr(self, "_image_auto_advance_timer"):
            return
        self._image_auto_advance_timer.stop()
        if self.current_image_path and not self._manual_image_switch and self.img_lbl.isVisible():
            self._image_auto_advance_timer.start()

    def _on_image_auto_advance_timeout(self) -> None:
        if self.current_image_path and not self._manual_image_switch:
            self.sig_switch_preview.emit(1)

    def on_player_error(self, _error, _message: str = "") -> None:
        self._start_repair_if_seek_unavailable(force=True, defer_for_cache=True)

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

    def _start_repair_if_seek_unavailable(self, force: bool = False, *, defer_for_cache: bool = False) -> None:
        if not self._repair_candidate_path or not self._repair_candidate_key:
            return
        if self._active_video_source != self._repair_candidate_key:
            return
        if defer_for_cache:
            with self._repair_lock:
                if self._repair_candidate_key in self._pending_cached_playable_lookups:
                    self._pending_repair_after_cache_lookup.add(self._repair_candidate_key)
                    return
        if not force and not self._seek_is_unavailable():
            return
        self._start_background_repair(self._repair_candidate_path, self._repair_candidate_key)

    def _retry_repair_after_cache_lookup(self, source_key: str) -> None:
        if self._cleanup_requested.is_set() or self._active_video_source != source_key:
            return
        self._start_repair_if_seek_unavailable(force=True)

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

    def _repair_video_worker(
        self,
        video_path: str,
        source_key: str,
        *,
        cancel_token: TaskCancelToken | None = None,
    ) -> None:
        def is_cancelled() -> bool:
            return self._cleanup_requested.is_set() or bool(cancel_token and cancel_token.is_cancelled())

        def progress(percent: int, message: str) -> None:
            if is_cancelled():
                return
            self.sig_repair_progress.emit(source_key, percent, message)

        try:
            result = self._repair_service.repair_for_playback(
                video_path,
                progress_callback=progress,
                cancel_check=is_cancelled,
            )
            if not is_cancelled():
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

    def _commit_repair_worker(
        self,
        source_key: str,
        source_path: str,
        repaired_path: str,
        *,
        cancel_token: TaskCancelToken | None = None,
    ) -> None:
        def is_cancelled() -> bool:
            return self._cleanup_requested.is_set() or bool(cancel_token and cancel_token.is_cancelled())

        def progress(percent: int, message: str) -> None:
            if is_cancelled():
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
                cancel_check=is_cancelled,
            )
            if not is_cancelled():
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
        self.lbl_repair.setText(self._t("正在修复播放进度，不影响当前播放"))
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

    def _submit_repair_cache_startup_cleanup(self) -> None:
        if self._cleanup_requested.is_set():
            return

        def task(token: TaskCancelToken) -> None:
            if not token.is_cancelled():
                self._repair_service.cleanup_stale_cache_files()

        self._short_task_runner.submit(name="cleanup-stale-repair-cache", fn=task)

    def _current_player_path(self) -> str:
        source = self.player.source()
        if source.isLocalFile():
            return source.toLocalFile()
        return ""

    def _emit_current_media_metadata(self, *, duration_ms: int | None = None) -> None:
        source_path = self._active_source_path or self._current_player_path()
        if not source_path:
            return
        metadata: dict[str, str] = {}
        if duration_ms is None:
            try:
                duration_ms = int(self.player.duration())
            except (TypeError, ValueError, RuntimeError):
                duration_ms = 0
        if duration_ms and duration_ms > 0:
            duration = self.format_clock_time(duration_ms)
            if duration:
                metadata["duration"] = duration
        resolution = self._current_video_resolution()
        if resolution:
            metadata["resolution"] = resolution
        if not metadata:
            return
        signature = (self._normalize_path(source_path), tuple(sorted(metadata.items())))
        if signature == self._last_metadata_emit_signature:
            return
        self._last_metadata_emit_signature = signature
        self.sig_media_metadata_detected.emit(source_path, metadata)

    def _current_video_resolution(self) -> str:
        for size in (self._video_item_native_size(), self._player_metadata_resolution()):
            resolution = self._size_to_resolution(size)
            if resolution:
                return resolution
        return ""

    def _video_item_native_size(self):
        getter = getattr(self.video_item, "nativeSize", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except RuntimeError:
            return None

    def _player_metadata_resolution(self):
        if QMediaMetaData is None:
            return None
        metadata_getter = getattr(self.player, "metaData", None)
        if not callable(metadata_getter):
            return None
        try:
            metadata = metadata_getter()
            key = QMediaMetaData.Key.Resolution
            value_getter = getattr(metadata, "value", None)
            return value_getter(key) if callable(value_getter) else None
        except (AttributeError, RuntimeError, TypeError):
            return None

    @staticmethod
    def _size_to_resolution(size) -> str:
        if size is None:
            return ""
        width_getter = getattr(size, "width", None)
        height_getter = getattr(size, "height", None)
        try:
            width = int(round(width_getter() if callable(width_getter) else 0))
            height = int(round(height_getter() if callable(height_getter) else 0))
        except (TypeError, ValueError):
            return ""
        if width <= 0 or height <= 0:
            return ""
        return f"{width} x {height}"

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

    @staticmethod
    def format_clock_time(ms: int) -> str:
        try:
            total_seconds = int(ms // 1000)
        except (TypeError, ValueError):
            return ""
        if total_seconds <= 0:
            return ""
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
