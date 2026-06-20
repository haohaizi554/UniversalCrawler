from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from app.services.icon_registry import action_icon_file, ui_icon_path
from app.ui.components.start_task_button import StartTaskButton
from app.ui.styles.themes import theme_colors
from app.utils.qt_runtime import load_qt_icon

MAX_QUANTITY = 9999
VIDEO_COUNT_PRESETS = (10, 20, 50, MAX_QUANTITY)
PAGE_COUNT_PRESETS = (1, 5, 10, MAX_QUANTITY)

class TopBarWidget(QFrame):
    """Unified top control row (platform selector lives in the sidebar)."""

    def __init__(self, is_dark_theme: bool) -> None:
        super().__init__()
        self.setObjectName("TopBarInner")
        self._is_dark_theme = bool(is_dark_theme)
        self._quantity_mode = "count"
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(14)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.inp_search = QLineEdit()
        self.inp_search.setFixedHeight(40)
        self.inp_search.setPlaceholderText("输入：主页链接、分享链接或合集链接...")
        self.inp_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(self.inp_search, 1)

        self.video_count_label = QLabel("视频数:")
        self.layout.addWidget(self.video_count_label)

        self.combo_video_count = QComboBox()
        self.combo_video_count.setFixedHeight(40)
        self.combo_video_count.setMinimumWidth(96)
        self._populate_quantity_options(VIDEO_COUNT_PRESETS, default=20)
        self.layout.addWidget(self.combo_video_count)

        self.quantity_unit_label = QLabel("个")
        self.quantity_unit_label.setObjectName("MutedLabel")
        self.layout.addWidget(self.quantity_unit_label)

        self.btn_start = StartTaskButton()
        self._set_button_icon(self.btn_start, action_icon_file("start"))
        self.layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("StopTaskBtn")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setFixedHeight(40)
        self._set_button_icon(self.btn_stop, action_icon_file("stop"))
        self.layout.addWidget(self.btn_stop)

        self.btn_dir = QPushButton("更改目录")
        self.btn_dir.setObjectName("DirBtn")
        self.btn_dir.setFixedHeight(40)
        self._set_button_icon(self.btn_dir, action_icon_file("change_directory"))
        self.layout.addWidget(self.btn_dir)

        self.btn_theme = QPushButton()
        self.btn_theme.setObjectName("ThemeBtn")
        self.btn_theme.setFixedHeight(36)
        self.btn_theme.setFixedWidth(56)
        self.btn_theme.setToolTip("切换主题")
        self.layout.addWidget(self.btn_theme)
        self._apply_button_styles()
        self.set_theme_icon(is_dark_theme)

        self.container_dynamic = QWidget()
        self.container_dynamic.hide()
        self.layout_dynamic = QHBoxLayout(self.container_dynamic)

    @staticmethod
    def _preset_label(value: int) -> str:
        return "max" if value >= MAX_QUANTITY else str(value)

    def _populate_quantity_options(self, presets: tuple[int, ...], *, default: int) -> None:
        blocked = self.combo_video_count.blockSignals(True)
        self.combo_video_count.clear()
        for value in presets:
            self.combo_video_count.addItem(self._preset_label(value), value)
        index = self.combo_video_count.findData(default)
        self.combo_video_count.setCurrentIndex(index if index >= 0 else 0)
        self.combo_video_count.blockSignals(blocked)

    def current_video_count(self) -> int:
        return int(self.combo_video_count.currentData() or 20)

    def set_video_count(self, value: int) -> None:
        value = max(1, min(int(value), MAX_QUANTITY))
        index = self.combo_video_count.findData(value)
        if index < 0:
            closest = min(
                (self.combo_video_count.itemData(i) for i in range(self.combo_video_count.count())),
                key=lambda preset: abs(int(preset or 0) - value),
            )
            index = self.combo_video_count.findData(closest)
        if index >= 0:
            self.combo_video_count.setCurrentIndex(index)

    def configure_for_platform(self, plugin_id: str, defaults: dict | None = None) -> None:
        defaults = defaults or {}
        if plugin_id == "bilibili":
            self._quantity_mode = "page"
            self.video_count_label.setText("页数:")
            self.quantity_unit_label.setText("页")
            self._populate_quantity_options(PAGE_COUNT_PRESETS, default=int(defaults.get("max_pages") or 1))
            return
        self._quantity_mode = "count"
        self.video_count_label.setText("视频数:")
        self.quantity_unit_label.setText("个")
        default_count = int(defaults.get("max_items") or 20)
        self._populate_quantity_options(VIDEO_COUNT_PRESETS, default=default_count)

    def quantity_mode(self) -> str:
        return self._quantity_mode

    def set_theme_icon(self, is_dark_theme: bool) -> None:
        self._is_dark_theme = bool(is_dark_theme)
        self._apply_button_styles()
        self.btn_theme.setText("")
        self._set_button_icon(self.btn_theme, action_icon_file("theme_dark" if is_dark_theme else "theme_light"))
        if self.btn_start.property("running") == "true":
            self.btn_start.set_crawl_running(True, is_dark_theme=is_dark_theme)

    def _apply_button_styles(self) -> None:
        colors = theme_colors(self._is_dark_theme)
        start_style = f"""
        QPushButton {{
            min-height: 40px;
            background-color: {colors['accent']};
            border: 1px solid {colors['accent']};
            border-radius: 7px;
            color: white;
            font-weight: 700;
            padding: 0px 14px;
        }}
        QPushButton:hover:enabled {{
            background-color: {colors['accent_hover']};
            border-color: {colors['accent_hover']};
        }}
        QPushButton:disabled {{
            background-color: {colors['border_strong']};
            border-color: {colors['border_strong']};
            color: rgba(255, 255, 255, 0.72);
        }}
        """
        neutral_style = f"""
        QPushButton {{
            min-height: 40px;
            background-color: {colors['panel']};
            border: 1px solid {colors['border']};
            border-radius: 7px;
            color: {colors['text']};
            font-weight: 600;
            padding: 0px 14px;
        }}
        QPushButton:hover:enabled {{
            background-color: {colors['panel_soft']};
            border-color: {colors['border_strong']};
        }}
        QPushButton:disabled {{
            background-color: {colors['panel_soft']};
            border-color: {colors['border']};
            color: {colors['muted']};
        }}
        """
        theme_style = f"""
        QPushButton {{
            min-height: 36px;
            min-width: 56px;
            background-color: {colors['panel']};
            border: 1px solid {colors['border']};
            border-radius: 18px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {colors['panel_soft']};
            border-color: {colors['border_strong']};
        }}
        """
        self.btn_start.setStyleSheet(start_style)
        self.btn_stop.setStyleSheet(neutral_style)
        self.btn_dir.setStyleSheet(neutral_style)
        self.btn_theme.setStyleSheet(theme_style)

    def set_crawl_running_state(
        self,
        is_running: bool,
        plugin_widget: QWidget | None = None,
        *,
        combo_source: QComboBox | None = None,
    ) -> None:
        self.btn_start.set_crawl_running(is_running, is_dark_theme=self._is_dark_theme)
        self.btn_stop.setEnabled(is_running)
        self.inp_search.setEnabled(not is_running)
        self.combo_video_count.setEnabled(not is_running)
        if combo_source is not None:
            combo_source.setEnabled(not is_running)
        if plugin_widget:
            plugin_widget.setEnabled(not is_running)

    @staticmethod
    def _set_button_icon(button: QPushButton, icon_name: str) -> None:
        icon = load_qt_icon([ui_icon_path(icon_name)])
        if icon is None:
            return
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
