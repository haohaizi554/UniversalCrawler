"""Media preview panel for video playback and image preview."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QVBoxLayout

from app.ui.widgets import ClickableVideoWidget


#媒体预览面板，统一封装视频播放、图片预览及播放控件的交互逻辑
class MediaPreviewPanel(QFrame):
    """媒体预览面板，统一封装视频/图片预览与播放控件状态。"""

    sig_toggle_fullscreen = pyqtSignal()

    def __init__(self, style_provider):
        """初始化当前实例并准备运行所需的状态，供 `MediaPreviewPanel` 使用。"""
        super().__init__()
        self._style_provider = style_provider
        self.current_image_path: str | None = None
        self.is_slider_pressed = False

        self.setObjectName("ContentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 修复: 用 QFrame 包裹 QVideoWidget，让样式表能控制背景色
        # QVideoWidget 是原生渲染控件，样式表无法直接覆盖其内部表面
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

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.vid_w)

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

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.player.positionChanged.connect(self.on_player_position_changed)
        self.player.durationChanged.connect(lambda duration: self.slider.setRange(0, duration))

        self.lbl_time = QLabel("00:00")
        self.lbl_time.setObjectName("TimeLabel")

        self.btn_fullscreen = QPushButton("[ 全屏 ]")
        self.btn_fullscreen.setFixedHeight(32)
        self.btn_fullscreen.setObjectName("FullscreenBtn")
        self.btn_fullscreen.setToolTip("沉浸模式 (双击画面)")
        self.btn_fullscreen.clicked.connect(self.sig_toggle_fullscreen.emit)

        controls_layout.addWidget(self.btn_play)
        controls_layout.addWidget(self.slider)
        controls_layout.addWidget(self.lbl_time)
        controls_layout.addWidget(self.btn_fullscreen)

        layout.addWidget(self.vid_container)
        layout.addWidget(self.img_lbl)
        layout.addWidget(self.ctrls)

    def _on_slider_pressed(self) -> None:
        """处理 `slider_pressed` 触发后的回调逻辑，供 `MediaPreviewPanel` 使用。"""
        self.is_slider_pressed = True

    def show_image(self, image_path: str) -> None:
        # Stop the player first so image mode stays isolated from video state.
        """执行 `show_image` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        self.vid_container.hide()
        self.img_lbl.show()
        self.player.stop()
        self.current_image_path = image_path
        self.scale_image_to_fit()

    def play_video(self, video_path: str) -> None:
        """执行 `play_video` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        self.img_lbl.hide()
        self.vid_container.show()
        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.player.play()
        self._set_play_button_paused()

    def stop_playback(self) -> None:
        """执行 `stop_playback` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        self.player.stop()
        self._set_play_button_stopped()

    def cleanup(self) -> None:
        """退出前显式停止播放器，降低 QtMultimedia/FFmpeg 原生崩溃风险。"""
        self.current_image_path = None
        self.player.stop()
        self.player.setSource(QUrl())
        self._set_play_button_stopped()

    def scale_image_to_fit(self) -> None:
        """执行 `scale_image_to_fit` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
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
        """执行 `resize_media` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        QTimer.singleShot(10, self.scale_image_to_fit)

    def toggle_play(self) -> None:
        """执行 `toggle_play` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._set_play_button_stopped()
        else:
            self.player.play()
            self._set_play_button_paused()

    def on_slider_released(self) -> None:
        """执行 `on_slider_released` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        self.is_slider_pressed = False
        self.player.setPosition(self.slider.value())

    def on_player_position_changed(self, pos: int) -> None:
        # Avoid slider jitter while the user is actively dragging it.
        """执行 `on_player_position_changed` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        if not self.is_slider_pressed:
            self.slider.setValue(pos)
        self.lbl_time.setText(f"{self.format_time(pos)} / {self.format_time(self.player.duration())}")

    def _set_play_button_stopped(self) -> None:
        """提供 `_set_play_button_stopped` 对应的内部辅助逻辑，供 `MediaPreviewPanel` 使用。"""
        self.btn_play.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _set_play_button_paused(self) -> None:
        """提供 `_set_play_button_paused` 对应的内部辅助逻辑，供 `MediaPreviewPanel` 使用。"""
        self.btn_play.setIcon(self._style_provider.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    @staticmethod
    def format_time(ms: int) -> str:
        """执行 `format_time` 对应的业务逻辑，供 `MediaPreviewPanel` 使用。"""
        seconds = (ms // 1000) % 60
        minutes = ms // 60000
        return f"{minutes:02}:{seconds:02}"
