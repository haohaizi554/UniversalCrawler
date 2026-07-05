from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from app.services.icon_registry import action_icon_file, ui_icon_path
from app.ui.localization import normalize_language, tr
from app.ui.styles.themes import theme_colors
from app.utils.qt_runtime import load_qt_icon

class StatusDotIndicator(QWidget):
    """Painted status light: idle / running / error."""

    def __init__(self, parent: QWidget | None = None, *, is_dark: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("StatusDot")
        self.setFixedSize(10, 10)
        self._is_dark = is_dark
        self._state = "idle"

    def set_theme(self, is_dark: bool) -> None:
        if self._is_dark == is_dark:
            return
        self._is_dark = is_dark
        self.update()

    def set_state(self, state: str) -> None:
        normalized = state if state in {"idle", "running", "error"} else "idle"
        if normalized == self._state:
            return
        self._state = normalized
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        colors = theme_colors(self._is_dark)
        fill_map = {
            "idle": colors["muted"],
            "running": colors["success"],
            "error": colors["danger"],
        }
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill_map[self._state]))
        painter.drawEllipse(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

class StatusBarWidget(QFrame):
    """Unified bottom status bar."""

    PROJECT_URL = "https://github.com/haohaizi554/UniversalCrawler"
    METRIC_VALUE_WIDTH = 88

    def __init__(self, *, is_dark: bool = False) -> None:
        super().__init__()
        self.setObjectName("StatusBar")
        self.setFixedHeight(34)
        self._is_dark = is_dark
        self._status_cache: dict = {}
        self._language = "zh-CN"
        self._metric_captions: dict[str, QLabel] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.status_dot = StatusDotIndicator(self, is_dark=is_dark)
        layout.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lbl_state = QLabel("空闲中")
        self.lbl_state.setFixedWidth(56)
        layout.addWidget(self.lbl_state, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        metrics.setContentsMargins(0, 0, 0, 0)

        self.lbl_download = self._metric_label(metrics, "download", "下载速度")
        self.lbl_completed = self._metric_label(metrics, "completed", "已完成")
        self.lbl_failed = self._metric_label(metrics, "failed", "失败")

        metrics_host = QWidget()
        metrics_host.setLayout(metrics)
        layout.addWidget(metrics_host, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)

        self.lbl_version = QLabel("v3.6.16")
        self.lbl_version.setObjectName("MutedLabel")
        self.lbl_version.setFixedWidth(52)
        self.lbl_version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_version, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_help = QPushButton()
        self.btn_help.setObjectName("StatusHelpBtn")
        self.btn_help.setToolTip("打开项目主页")
        self.btn_help.setFixedSize(24, 24)
        self.btn_help.setFlat(True)
        icon = load_qt_icon([ui_icon_path(action_icon_file("help"))])
        if icon is not None:
            self.btn_help.setIcon(icon)
            self.btn_help.setIconSize(QSize(18, 18))
        else:
            self.btn_help.setText("?")
        self.btn_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.PROJECT_URL)))
        layout.addWidget(self.btn_help, 0, Qt.AlignmentFlag.AlignVCenter)

        self.status_dot.set_state("idle")

    def _metric_label(self, parent_layout: QHBoxLayout, key: str, title: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(f"{title}:")
        caption.setObjectName("StatusMetricCaption")
        self._metric_captions[key] = caption
        value = QLabel("0")
        value.setObjectName("StatusMetricValue")
        value.setFixedWidth(self.METRIC_VALUE_WIDTH)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(caption)
        row.addWidget(value)
        host = QWidget()
        host.setLayout(row)
        parent_layout.addWidget(host)
        return value

    def set_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.status_dot.set_theme(is_dark)

    def set_language(self, language: str | None) -> None:
        self._language = normalize_language(language)
        self.btn_help.setToolTip(tr("打开项目主页", self._language))
        caption_titles = {
            "download": "下载速度",
            "completed": "已完成",
            "failed": "失败",
        }
        for key, title in caption_titles.items():
            caption = self._metric_captions.get(key)
            if caption is not None:
                caption.setText(f"{tr(title, self._language)}:")
        self.render(self._status_cache or {"running_state": "空闲中"})

    def render(self, status: dict) -> None:
        if not status:
            return
        merged = dict(self._status_cache)
        merged.update(status)
        self._status_cache = merged

        raw_running_state = str(merged.get("running_state") or "空闲中")
        running_state = tr(raw_running_state, self._language)
        failed_count = int(merged.get("failed_count", 0) or 0)
        indicator = str(merged.get("status_indicator") or "").strip().lower()
        if indicator not in {"idle", "running", "error"}:
            if raw_running_state == "运行中":
                indicator = "running"
            elif failed_count > 0:
                indicator = "error"
            else:
                indicator = "idle"

        self.lbl_state.setText(running_state)
        self.status_dot.set_state(indicator)
        self.lbl_download.setText(str(merged.get("download_speed") or "0 B/s"))
        self.lbl_completed.setText(str(int(merged.get("completed_count", 0) or 0)))
        self.lbl_failed.setText(str(failed_count))
        self.lbl_version.setText(str(merged.get("version") or "v3.6.16"))
