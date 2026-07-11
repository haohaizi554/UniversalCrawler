"""Themed update-check result dialog."""

from __future__ import annotations

from html import escape
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from app.ui.dialogs.chromed_dialog import ChromedDialog
from app.ui.localization import normalize_language, tr


class UpdateStatusIcon(QWidget):
    """Compact painted status icon used by the update dialog."""

    def __init__(self, *, status: str, colors: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._status = status
        self._colors = dict(colors)
        self.setObjectName("UpdateStatusIcon")
        self.setFixedSize(46, 46)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_status(self, status: str, colors: dict[str, str]) -> None:
        self._status = status
        self._colors = dict(colors)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self._status_color())
        soft = QColor(color)
        soft.setAlpha(34)
        painter.setPen(QPen(color, 1.6))
        painter.setBrush(soft)
        painter.drawEllipse(3, 3, 40, 40)

        pen = QPen(color, 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        status = self._status
        if status == "current":
            painter.drawLine(15, 24, 21, 30)
            painter.drawLine(21, 30, 32, 17)
        elif status == "available":
            painter.drawLine(23, 32, 23, 15)
            painter.drawLine(23, 15, 16, 22)
            painter.drawLine(23, 15, 30, 22)
            painter.drawLine(16, 34, 30, 34)
        elif status == "local_newer":
            painter.drawLine(15, 28, 23, 16)
            painter.drawLine(23, 16, 31, 28)
            painter.drawLine(18, 30, 28, 30)
        elif status == "error":
            painter.drawLine(23, 14, 23, 27)
            painter.drawPoint(23, 34)
        else:
            painter.drawLine(23, 21, 23, 32)
            painter.drawPoint(23, 15)

    def _status_color(self) -> str:
        if self._status == "current":
            return self._colors["success"]
        if self._status == "available":
            return self._colors["accent"]
        if self._status == "local_newer":
            return self._colors["warning"]
        if self._status == "error":
            return self._colors["danger"]
        return self._colors["muted"]


class UpdateCheckDialog(ChromedDialog):
    """Detailed themed dialog for update-check outcomes."""

    SKIP_CODE = 2

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        message: str,
        details: str = "",
        primary_text: str = "确定",
        secondary_text: str = "",
        skip_text: str = "",
        status: str = "info",
        local_version: str = "",
        latest_version: str = "",
        release_url: str = "",
        candidates: tuple[Any, ...] = (),
        language: str = "zh-CN",
    ) -> None:
        self._language = normalize_language(language)
        super().__init__(
            parent,
            title=self._tr(title),
            object_name="UpdateCheckDialog",
            body_margins=(24, 22, 24, 20),
            body_spacing=16,
        )
        self.setMinimumWidth(620)
        self.setMaximumWidth(720)
        self._status = status or "info"
        self._release_url = str(release_url or "").strip()
        self._initial_details = str(details or "")
        self._candidate_options = self._normalize_candidates(candidates, latest_version=latest_version, release_url=release_url)
        self._selected_version = self._candidate_options[0]["version"] if self._candidate_options else str(latest_version or "")
        self.details_label: QLabel | None = None
        self.release_link: QLabel | None = None

        layout = self.content_layout
        layout.addWidget(self._build_header(self._tr(title), self._tr(message)))
        layout.addWidget(self._build_version_panel(local_version, latest_version))
        if len(self._candidate_options) > 1:
            layout.addWidget(self._build_candidate_selector())
        if details or self._release_url:
            layout.addWidget(self._build_detail_card(details))
        layout.addLayout(self._build_button_row(primary_text, secondary_text, skip_text))

    def _build_header(self, title: str, message: str) -> QWidget:
        hero = QFrame()
        hero.setObjectName("UpdateHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(14)

        self.status_icon = UpdateStatusIcon(status=self._status, colors=self._colors, parent=hero)
        hero_layout.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_row.addWidget(title_label, 1)

        self.status_badge = QLabel(self._status_badge_text())
        self.status_badge.setObjectName("UpdateStatusBadge")
        self.status_badge.setProperty("tone", self._status_tone())
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        text_col.addLayout(title_row)

        message_label = QLabel(message)
        message_label.setObjectName("DialogBody")
        message_label.setWordWrap(True)
        text_col.addWidget(message_label)
        hero_layout.addLayout(text_col, 1)
        return hero

    def _build_version_panel(self, local_version: str, latest_version: str) -> QWidget:
        panel = QFrame()
        panel.setObjectName("UpdateVersionPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.local_version_label = self._make_version_label(self._tr("当前版本"))
        self.local_version_value = self._make_version_value(local_version or "-")
        self.remote_version_label = self._make_version_label(self._tr("Release 版本"))
        self.remote_version_value = self._make_version_value(latest_version or "-")
        self.remote_version_value.setProperty("tone", self._status_tone())
        arrow = QLabel("→")
        arrow.setObjectName("UpdateVersionArrow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)

        grid.addWidget(self.local_version_label, 0, 0)
        grid.addWidget(self.local_version_value, 1, 0)
        grid.addWidget(arrow, 1, 1)
        grid.addWidget(self.remote_version_label, 0, 2)
        grid.addWidget(self.remote_version_value, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        return panel

    def _build_candidate_selector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("UpdateCandidatePanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        label = QLabel(self._tr("选择要安装的版本"))
        label.setObjectName("UpdateDetailTitle")
        panel_layout.addWidget(label)

        self.version_combo = QComboBox()
        self.version_combo.setObjectName("UpdateVersionCombo")
        self.version_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for option in self._candidate_options:
            self.version_combo.addItem(self._candidate_label(option), option["version"])
        self.version_combo.currentIndexChanged.connect(self._on_candidate_changed)
        panel_layout.addWidget(self.version_combo)
        return panel

    def _build_detail_card(self, details: str) -> QWidget:
        card = QFrame()
        card.setObjectName("UpdateDetailCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(7)

        detail_title = QLabel(self._detail_title())
        detail_title.setObjectName("UpdateDetailTitle")
        card_layout.addWidget(detail_title)

        self.details_label = QLabel(self._detail_text(details))
        self.details_label.setObjectName("DialogStatus")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self.details_label)

        if self._release_url:
            link_text = self._tr("打开 GitHub Release 页面")
            self.release_link = QLabel(
                f'<a href="{escape(self._release_url, quote=True)}">{escape(link_text)}</a>'
            )
            self.release_link.setObjectName("UpdateReleaseLink")
            self.release_link.setOpenExternalLinks(True)
            self.release_link.setTextFormat(Qt.TextFormat.RichText)
            self.release_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            card_layout.addWidget(self.release_link)
        return card

    def _build_button_row(self, primary_text: str, secondary_text: str, skip_text: str) -> QHBoxLayout:
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)
        button_row.addStretch(1)

        if skip_text:
            self.skip_button = QPushButton(self._tr(skip_text))
            self.skip_button.setObjectName("DialogNeutralButton")
            self.skip_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.skip_button.clicked.connect(lambda: self.done(self.SKIP_CODE))
            button_row.addWidget(self.skip_button)
        else:
            self.skip_button = None

        if secondary_text:
            self.secondary_button = QPushButton(self._tr(secondary_text))
            self.secondary_button.setObjectName("DialogNeutralButton")
            self.secondary_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.secondary_button.clicked.connect(self.reject)
            button_row.addWidget(self.secondary_button)
        else:
            self.secondary_button = None

        self.primary_button = QPushButton(self._tr(primary_text))
        self.primary_button.setObjectName("DialogPrimaryButton")
        self.primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_button.clicked.connect(self.accept)
        self.primary_button.setDefault(True)
        button_row.addWidget(self.primary_button)
        return button_row

    def apply_chrome_theme(self, is_dark: bool) -> None:
        super().apply_chrome_theme(is_dark)
        if hasattr(self, "status_icon"):
            self.status_icon.set_status(self._status, self._colors)

    def selected_update_version(self) -> str:
        return str(self._selected_version or "")

    def _on_candidate_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._candidate_options):
            return
        option = self._candidate_options[index]
        self._selected_version = option["version"]
        self._release_url = option["release_url"]
        self.remote_version_value.setText(self._display_version(option["version"]))
        if self.details_label is not None:
            self.details_label.setText(self._detail_text(option["notes"] or self._initial_details))
        if self.release_link is not None and self._release_url:
            link_text = self._tr("打开 GitHub Release 页面")
            self.release_link.setText(f'<a href="{escape(self._release_url, quote=True)}">{escape(link_text)}</a>')

    @staticmethod
    def _display_version(version: str) -> str:
        text = str(version or "").strip()
        if text and not text.lower().startswith("v"):
            return f"v{text}"
        return text or "-"

    @classmethod
    def _normalize_candidates(cls, candidates: tuple[Any, ...], *, latest_version: str, release_url: str) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        for candidate in candidates or ():
            version = str(cls._candidate_value(candidate, "version") or "").strip()
            if not version:
                continue
            options.append(
                {
                    "version": version,
                    "tag": str(cls._candidate_value(candidate, "tag_name") or ""),
                    "name": str(cls._candidate_value(candidate, "release_name") or ""),
                    "release_url": str(cls._candidate_value(candidate, "html_url") or release_url or ""),
                    "notes": str(cls._candidate_value(candidate, "notes") or ""),
                    "asset": str(cls._candidate_value(candidate, "asset_name") or ""),
                }
            )
        if not options and latest_version:
            options.append(
                {
                    "version": str(latest_version),
                    "tag": str(latest_version),
                    "name": str(latest_version),
                    "release_url": str(release_url or ""),
                    "notes": "",
                    "asset": "",
                }
            )
        return options

    @staticmethod
    def _candidate_value(candidate: Any, key: str) -> Any:
        if isinstance(candidate, dict):
            return candidate.get(key)
        return getattr(candidate, key, "")

    def _candidate_label(self, option: dict[str, str]) -> str:
        version = self._display_version(option["version"])
        name = option["name"] or option["tag"]
        asset = option["asset"]
        parts = [version]
        if name and name not in {version, option["version"]}:
            parts.append(name)
        if asset:
            parts.append(asset)
        return "  |  ".join(parts)

    @staticmethod
    def _make_version_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("UpdateVersionLabel")
        return label

    @staticmethod
    def _make_version_value(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("UpdateVersionValue")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _status_tone(self) -> str:
        if self._status == "current":
            return "success"
        if self._status == "available":
            return "accent"
        if self._status == "local_newer":
            return "warning"
        if self._status == "error":
            return "danger"
        return "muted"

    def _tr(self, text: str) -> str:
        return tr(text, self._language)

    def _status_badge_text(self) -> str:
        return self._tr({
            "current": "已是最新",
            "available": "发现更新",
            "local_newer": "本地构建",
            "error": "检测失败",
        }.get(self._status, "提示"))

    def _detail_title(self) -> str:
        return self._tr({
            "current": "检查结果",
            "available": "更新说明",
            "local_newer": "为什么会这样",
            "error": "错误详情",
        }.get(self._status, "补充信息"))

    def _detail_text(self, details: str) -> str:
        text = str(details or "").strip()
        if text:
            return self._tr(text)
        if self._status == "available":
            return self._tr("更新前建议关闭正在运行的采集任务。安装包会先完成更新清单签名、大小和 SHA-256 校验。")
        if self._status == "current":
            return self._tr("本地版本与 GitHub 最新 Release 一致，无需更新。")
        if self._status == "local_newer":
            return self._tr("通常表示你正在使用本地构建或预发布构建，无需更新。")
        return self._tr("暂无更多信息。")


class UpdateDownloadDialog(ChromedDialog):
    """Modal progress surface for the verified updater download/install handoff."""

    cancel_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    install_requested = pyqtSignal()
    view_log_requested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        version: str,
        asset_name: str = "",
        release_url: str = "",
        language: str = "zh-CN",
    ) -> None:
        self._language = normalize_language(language)
        self._terminal_state = False
        self._release_url = str(release_url or "").strip()
        super().__init__(
            parent,
            title=self._tr("下载更新"),
            object_name="UpdateDownloadDialog",
            body_margins=(24, 22, 24, 20),
            body_spacing=16,
        )
        self.setMinimumWidth(620)
        self.setMaximumWidth(720)

        layout = self.content_layout
        layout.addWidget(self._build_header(version, asset_name))
        layout.addWidget(self._build_progress_panel())
        layout.addLayout(self._build_button_row())

    def _build_header(self, version: str, asset_name: str) -> QWidget:
        hero = QFrame()
        hero.setObjectName("UpdateHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(14)

        self.status_icon = UpdateStatusIcon(status="available", colors=self._colors, parent=hero)
        hero_layout.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(8)
        title_label = QLabel(self._tr("正在下载更新"))
        title_label.setObjectName("DialogTitle")
        text_col.addWidget(title_label)
        message = self._tr("正在下载并校验版本 {version}。").format(version=version or "-")
        if asset_name:
            message = f"{message}\n{asset_name}"
        message_label = QLabel(message)
        message_label.setObjectName("DialogBody")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_col.addWidget(message_label)
        hero_layout.addLayout(text_col, 1)
        return hero

    def _build_progress_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("UpdateDetailCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(10)

        self.state_label = QLabel(self._tr("准备下载..."))
        self.state_label.setObjectName("UpdateDetailTitle")
        panel_layout.addWidget(self.state_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("UpdateDownloadProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        panel_layout.addWidget(self.progress_bar)

        self.detail_label = QLabel(self._tr("安装包会先完成更新清单签名、大小和 SHA-256 校验。"))
        self.detail_label.setObjectName("DialogStatus")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel_layout.addWidget(self.detail_label)
        return panel

    def _build_button_row(self) -> QHBoxLayout:
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)

        self.view_log_button = QPushButton(self._tr("查看日志"))
        self.view_log_button.setObjectName("DialogNeutralButton")
        self.view_log_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_log_button.clicked.connect(self.view_log_requested.emit)
        button_row.addWidget(self.view_log_button)

        button_row.addStretch(1)

        self.retry_button = QPushButton(self._tr("重试"))
        self.retry_button.setObjectName("DialogNeutralButton")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self.retry_requested.emit)
        self.retry_button.hide()
        button_row.addWidget(self.retry_button)

        self.cancel_button = QPushButton(self._tr("取消下载"))
        self.cancel_button.setObjectName("DialogNeutralButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        button_row.addWidget(self.cancel_button)

        self.install_button = QPushButton(self._tr("安装并重启"))
        self.install_button.setObjectName("DialogPrimaryButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.clicked.connect(self.install_requested.emit)
        self.install_button.hide()
        button_row.addWidget(self.install_button)
        return button_row

    def set_progress(self, progress: dict) -> None:
        percent = max(0, min(100, int(float(progress.get("percent") or 0))))
        self.progress_bar.setValue(percent)
        downloaded = int(progress.get("bytesDownloaded") or 0)
        total = int(progress.get("totalBytes") or 0)
        self.state_label.setText(self._tr("正在下载更新"))
        if total > 0:
            self.detail_label.setText(
                self._tr("已下载 {downloaded} / {total} MB").format(
                    downloaded=f"{downloaded / 1024 / 1024:.1f}",
                    total=f"{total / 1024 / 1024:.1f}",
                )
            )

    def set_error(self, message: str) -> None:
        self._terminal_state = True
        self.status_icon.set_status("error", self._colors)
        self.state_label.setText(self._tr("更新下载失败"))
        self.detail_label.setText(self._tr(str(message or "未知错误")))
        self.cancel_button.hide()
        self.install_button.hide()
        self.retry_button.show()

    def set_cancelling(self) -> None:
        self._terminal_state = True
        self.state_label.setText(self._tr("正在取消下载"))
        self.detail_label.setText(self._tr("正在等待下载线程停止，请稍候。"))
        self.cancel_button.hide()
        self.retry_button.hide()
        self.install_button.hide()

    def set_cancelled(self) -> None:
        self.set_error(self._tr("已取消下载。"))

    def set_ready(self, installer_path: str) -> None:
        self._terminal_state = True
        self.status_icon.set_status("current", self._colors)
        self.progress_bar.setValue(100)
        self.state_label.setText(self._tr("更新已准备好"))
        self.detail_label.setText(self._tr("安装包已下载并通过校验：{path}").format(path=installer_path))
        self.cancel_button.hide()
        self.retry_button.hide()
        self.install_button.show()
        self.install_button.setDefault(True)

    def reject(self) -> None:
        if not self._terminal_state:
            self.cancel_requested.emit()
        super().reject()

    def _tr(self, text: str) -> str:
        return tr(text, self._language)
