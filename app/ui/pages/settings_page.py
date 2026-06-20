from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QApplication,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.pages.common import PageFrame

class SettingsPage(PageFrame):
    """Configuration center with real controls instead of key-value text."""

    file_association_requested = pyqtSignal(bool, bool)

    GROUP_ORDER = ("基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置")

    def __init__(self) -> None:
        super().__init__("配置中心", "自定义应用行为，打造专属于你的下载体验", use_island=True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QGridLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setHorizontalSpacing(14)
        self.content_layout.setVerticalSpacing(14)
        self.scroll.setWidget(self.content)
        self.root_layout.addWidget(self.scroll, 1)
        self._render_signature: tuple | None = None

    def render(self, snapshot: dict) -> None:
        settings = snapshot.get("settings_snapshot") or {}
        signature = self._settings_signature(settings)
        if signature == self._render_signature:
            return
        if self._render_signature is not None and self._has_editor_focus():
            return
        self._clear_content()
        for index, group_name in enumerate(self.GROUP_ORDER):
            group = self._build_group(group_name, settings.get(group_name, {}))
            row = index // 2
            col = index % 2
            self.content_layout.addWidget(group, row, col)
        self.content_layout.setColumnStretch(0, 1)
        self.content_layout.setColumnStretch(1, 1)
        self.content_layout.setRowStretch(3, 1)
        self._render_signature = signature

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _has_editor_focus(self) -> bool:
        focused = QApplication.focusWidget()
        return bool(
            focused is not None
            and self.isAncestorOf(focused)
            and isinstance(focused, (QLineEdit, QComboBox, QSpinBox))
        )

    @staticmethod
    def _settings_signature(settings: dict) -> tuple:
        def freeze(value: Any):
            if isinstance(value, dict):
                return tuple(sorted((str(key), freeze(item)) for key, item in value.items()))
            if isinstance(value, list):
                return tuple(freeze(item) for item in value)
            return str(value)

        return freeze(settings)

    def _build_group(self, group_name: str, value: Any) -> QGroupBox:
        group = QGroupBox(group_name)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        if group_name == "基础设置":
            self._add_text_row(layout, "下载目录", self._dict_value(value, "download_directory"))
            self._add_text_row(layout, "文件命名", self._dict_value(value, "filename_template"))
            self._add_combo_row(layout, "默认打开方式", self._dict_value(value, "default_open_mode"), ["系统默认播放器", "内置播放器", "打开目录"])
            self._add_check_row(layout, "下载后自动打开", bool(self._dict_value(value, "open_after_download", True)))
            button = QPushButton("绑定默认打开方式")
            button.clicked.connect(lambda: self.file_association_requested.emit(True, False))
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        elif group_name == "下载设置":
            self._add_spin_row(layout, "并发数", self._dict_value(value, "max_concurrent", 3), 1, 16)
            self._add_spin_row(layout, "请求超时", self._dict_value(value, "request_timeout", 60), 10, 300, suffix=" 秒")
            self._add_spin_row(layout, "最大重试", self._dict_value(value, "max_retries", 3), 0, 10)
            self._add_spin_row(layout, "速度限制", self._dict_value(value, "speed_limit_kb", 0), 0, 999999, suffix=" KB/s")
            self._add_check_row(layout, "断点续传", bool(self._dict_value(value, "resume_enabled", True)))
            self._add_check_row(layout, "仅下载视频", bool(self._dict_value(value, "video_only", False)))
        elif group_name == "平台设置":
            rows = value if isinstance(value, list) else []
            for row in rows:
                title = str(row.get("name") or row.get("id") or "平台")
                line = QWidget()
                line_layout = QHBoxLayout(line)
                line_layout.setContentsMargins(0, 0, 0, 0)
                line_layout.setSpacing(8)
                title_label = QLabel(title)
                title_label.setMinimumWidth(72)
                title_label.setToolTip(title)
                line_layout.addWidget(title_label, 1)
                auth = QComboBox()
                auth.addItems(["未认证", "已认证"])
                auth.setCurrentText(str(row.get("auth_status") or "未认证"))
                auth.setMinimumWidth(82)
                line_layout.addWidget(auth)
                count = self._spin(int(row.get("default_count") or 20), 1, 9999)
                count.setFixedWidth(82)
                line_layout.addWidget(count)
                proxy = QLineEdit(str(row.get("proxy") or "系统代理"))
                proxy.setMinimumWidth(110)
                proxy.setToolTip(proxy.text())
                line_layout.addWidget(proxy, 2)
                layout.addWidget(line)
        elif group_name == "播放设置":
            self._add_combo_row(layout, "默认播放器", self._dict_value(value, "default_player"), ["内置播放器", "系统默认播放器"])
            self._add_check_row(layout, "记住播放位置", bool(self._dict_value(value, "remember_position", True)))
            self._add_check_row(layout, "硬件加速", bool(self._dict_value(value, "hardware_acceleration", True)))
            self._add_check_row(layout, "自动播放下一项", bool(self._dict_value(value, "autoplay_next", True)))
            self._add_check_row(layout, "手动切换图片", bool(self._dict_value(value, "manual_image_switch", True)))
        elif group_name == "日志设置":
            self._add_spin_row(layout, "保留天数", self._dict_value(value, "retention_days", 30), 1, 365, suffix=" 天")
            self._add_combo_row(layout, "日志级别", self._dict_value(value, "level"), ["调试", "信息", "警告", "错误"])
            self._add_check_row(layout, "错误时自动复制 Trace", bool(self._dict_value(value, "auto_copy_trace_on_error", True)))
            self._add_check_row(layout, "启动时清理旧日志", bool(self._dict_value(value, "cleanup_old_logs_on_start", False)))
        elif group_name == "外观设置":
            self._add_check_row(layout, "跟随系统", bool(self._dict_value(value, "follow_system", False)))
            self._add_combo_row(layout, "主题", self._dict_value(value, "theme", "light"), ["light", "dark"])
            self._add_text_row(layout, "强调色", self._dict_value(value, "accent", "#1677ff"))
            self._add_combo_row(layout, "界面缩放", self._dict_value(value, "scale", "100%"), ["90%", "100%", "110%", "125%"])
            self._add_combo_row(layout, "字体大小", self._dict_value(value, "font_size", "中"), ["小", "中", "大"])
        layout.addStretch(1)
        return group

    def _add_text_row(self, layout: QVBoxLayout, label: str, value: Any) -> None:
        row = self._row(label)
        editor = QLineEdit(str(value or ""))
        editor.setMinimumWidth(160)
        editor.setToolTip(editor.text())
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.layout().addWidget(editor, 1)
        layout.addWidget(row)

    def _add_combo_row(self, layout: QVBoxLayout, label: str, value: Any, options: list[str]) -> None:
        row = self._row(label)
        editor = QComboBox()
        editor.addItems(options)
        text = str(value or options[0])
        index = editor.findText(text)
        editor.setCurrentIndex(index if index >= 0 else 0)
        row.layout().addWidget(editor, 1)
        layout.addWidget(row)

    def _add_spin_row(self, layout: QVBoxLayout, label: str, value: Any, minimum: int, maximum: int, *, suffix: str = "") -> None:
        row = self._row(label)
        row.layout().addWidget(self._spin(int(value or minimum), minimum, maximum, suffix=suffix), 1)
        layout.addWidget(row)

    def _add_check_row(self, layout: QVBoxLayout, label: str, checked: bool) -> None:
        row = self._row(label)
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        row.layout().addWidget(checkbox, 1)
        layout.addWidget(row)

    @staticmethod
    def _row(label: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        label_widget = QLabel(label)
        label_widget.setMinimumWidth(96)
        row_layout.addWidget(label_widget)
        return row

    @staticmethod
    def _spin(value: int, minimum: int, maximum: int, *, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(max(minimum, min(value, maximum)))
        spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _dict_value(value: Any, key: str, default: Any = "") -> Any:
        return value.get(key, default) if isinstance(value, dict) else default
