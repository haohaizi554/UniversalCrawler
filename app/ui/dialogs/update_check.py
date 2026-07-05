"""Themed update-check result dialog."""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.dialogs.chromed_dialog import ChromedDialog


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

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        message: str,
        details: str = "",
        primary_text: str = "确定",
        secondary_text: str = "",
        status: str = "info",
        local_version: str = "",
        latest_version: str = "",
        release_url: str = "",
    ) -> None:
        super().__init__(
            parent,
            title=title,
            object_name="UpdateCheckDialog",
            body_margins=(24, 22, 24, 20),
            body_spacing=16,
        )
        self.setMinimumWidth(620)
        self.setMaximumWidth(720)
        self._status = status or "info"
        self._release_url = str(release_url or "").strip()

        layout = self.content_layout
        layout.addWidget(self._build_header(title, message))
        layout.addWidget(self._build_version_panel(local_version, latest_version))
        if details or self._release_url:
            layout.addWidget(self._build_detail_card(details))
        layout.addLayout(self._build_button_row(primary_text, secondary_text))

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

        self.local_version_label = self._make_version_label("当前版本")
        self.local_version_value = self._make_version_value(local_version or "-")
        self.remote_version_label = self._make_version_label("Release 版本")
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

    def _build_detail_card(self, details: str) -> QWidget:
        card = QFrame()
        card.setObjectName("UpdateDetailCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(7)

        detail_title = QLabel(self._detail_title())
        detail_title.setObjectName("UpdateDetailTitle")
        card_layout.addWidget(detail_title)

        details_label = QLabel(self._detail_text(details))
        details_label.setObjectName("DialogStatus")
        details_label.setWordWrap(True)
        details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(details_label)

        if self._release_url:
            link = QLabel(
                f'<a href="{escape(self._release_url, quote=True)}">打开 GitHub Release 页面</a>'
            )
            link.setObjectName("UpdateReleaseLink")
            link.setOpenExternalLinks(True)
            link.setTextFormat(Qt.TextFormat.RichText)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            card_layout.addWidget(link)
        return card

    def _build_button_row(self, primary_text: str, secondary_text: str) -> QHBoxLayout:
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)
        button_row.addStretch(1)

        if secondary_text:
            self.secondary_button = QPushButton(secondary_text)
            self.secondary_button.setObjectName("DialogNeutralButton")
            self.secondary_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.secondary_button.clicked.connect(self.reject)
            button_row.addWidget(self.secondary_button)
        else:
            self.secondary_button = None

        self.primary_button = QPushButton(primary_text)
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

    def _status_badge_text(self) -> str:
        return {
            "current": "已是最新",
            "available": "发现更新",
            "local_newer": "本地构建",
            "error": "检测失败",
        }.get(self._status, "提示")

    def _detail_title(self) -> str:
        return {
            "current": "检查结果",
            "available": "更新说明",
            "local_newer": "为什么会这样",
            "error": "错误详情",
        }.get(self._status, "补充信息")

    def _detail_text(self, details: str) -> str:
        text = str(details or "").strip()
        if text:
            return text
        if self._status == "available":
            return "当前只完成版本检测与更新确认，下载和安装流程尚未接入。"
        if self._status == "current":
            return "本地版本与 GitHub 最新 Release 一致，无需更新。"
        if self._status == "local_newer":
            return "通常表示你正在使用本地构建或预发布构建，无需更新。"
        return "暂无更多信息。"
