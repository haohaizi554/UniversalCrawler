from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from app.config import platform_count_options, platform_note_count_options, platform_page_count_options
from app.core.plugin_registry import registry
from app.services.icon_registry import ui_icon_path
from shared.icon_contract import action_icon_file
from app.ui.components.combo_popup import PolishedComboBox, fit_combo_width_to_contents, polish_combo_popup
from app.ui.components.start_task_button import StartTaskButton
from shared.localization import normalize_language, tr
from app.ui.styles.themes import theme_colors
from app.utils.qt_runtime import load_qt_icon

MAX_QUANTITY = 9999
COUNT_UNITS = {"videos", "notes", "pages"}
COUNT_LABELS = {
    "videos": "视频数:",
    "notes": "笔记数:",
    "pages": "页数:",
}
STOP_BUTTON_MIN_WIDTH = 86
DIR_BUTTON_MIN_WIDTH = 116


class TopBarWidget(QFrame):
    """统一顶部操作栏；平台选择器由侧栏持有。"""

    def __init__(self, is_dark_theme: bool) -> None:
        super().__init__()
        self.setObjectName("TopBarInner")
        self._is_dark_theme = bool(is_dark_theme)
        self._quantity_mode = "videos"
        self._quantity_options: list[dict[str, str]] = []
        self._language = "zh-CN"
        self._platform_id = ""
        self._search_placeholder_source = "输入：主页链接、分享链接或合集链接..."
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.inp_search = QLineEdit()
        self.inp_search.setObjectName("TopSearchInput")
        self.inp_search.setFixedHeight(40)
        self._apply_search_placeholder()
        self.inp_search.setMinimumWidth(220)
        self.inp_search.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(self.inp_search, 1)

        self.video_count_label = QLabel("视频数:")
        self.layout.addWidget(self.video_count_label)

        self.combo_video_count = PolishedComboBox()
        self.combo_video_count.setObjectName("TopQuantityCombo")
        self.combo_video_count.setFixedHeight(40)
        self.combo_video_count.setMinimumWidth(96)
        self._populate_quantity_options(platform_count_options(), default=20)
        self.combo_video_count.currentIndexChanged.connect(lambda *_args: self._refresh_quantity_combo_layout())
        self.layout.addWidget(self.combo_video_count)

        self.quantity_unit_label = QLabel("个")
        self.quantity_unit_label.setObjectName("MutedLabel")
        self.quantity_unit_label.hide()
        self.layout.addWidget(self.quantity_unit_label)

        self.btn_start = StartTaskButton()
        self._set_button_icon(self.btn_start, action_icon_file("start"))
        self.layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("StopTaskBtn")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setMinimumWidth(STOP_BUTTON_MIN_WIDTH)
        self.btn_stop.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._set_button_icon(self.btn_stop, action_icon_file("stop"))
        self.layout.addWidget(self.btn_stop)

        self.btn_dir = QPushButton("更改目录")
        self.btn_dir.setObjectName("DirBtn")
        self.btn_dir.setFixedHeight(40)
        self.btn_dir.setMinimumWidth(DIR_BUTTON_MIN_WIDTH)
        self.btn_dir.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._set_button_icon(self.btn_dir, action_icon_file("change_directory"))
        self.layout.addWidget(self.btn_dir)

        self.btn_theme = QPushButton()
        self.btn_theme.setObjectName("ThemeBtn")
        self.btn_theme.setFixedHeight(36)
        self.btn_theme.setFixedWidth(48)
        self.btn_theme.setToolTip("切换主题")
        self.layout.addWidget(self.btn_theme)
        self._apply_button_styles()
        self.set_theme_icon(is_dark_theme)

        self.container_dynamic = QWidget()
        self.container_dynamic.hide()
        self.layout_dynamic = QHBoxLayout(self.container_dynamic)

    @staticmethod
    def _normalize_quantity_options(options: list[dict[str, Any]] | tuple[int, ...]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for option in options:
            if isinstance(option, dict):
                value = str(option.get("value") or "")
                label = str(option.get("label") or value)
            else:
                value = str(option)
                label = "max" if int(option) >= MAX_QUANTITY else str(option)
            if value:
                normalized.append({"value": value, "label": label})
        return normalized

    def _populate_quantity_options(self, options: list[dict[str, Any]] | tuple[int, ...], *, default: int) -> None:
        normalized = self._normalize_quantity_options(options)
        self._quantity_options = normalized
        blocked = self.combo_video_count.blockSignals(True)
        self.combo_video_count.clear()
        for option in normalized:
            value = int(option["value"])
            label = tr(option["label"], self._language)
            self.combo_video_count.addItem(self._compact_quantity_label(label), value)
            self.combo_video_count.setItemData(self.combo_video_count.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        index = self.combo_video_count.findData(default)
        if index < 0 and normalized:
            normalized_values = [int(option["value"]) for option in normalized]
            closest = min(normalized_values, key=lambda preset: abs(preset - int(default)))
            index = self.combo_video_count.findData(closest)
        self.combo_video_count.setCurrentIndex(index if index >= 0 else 0)
        self.combo_video_count.setMaxVisibleItems(max(1, self.combo_video_count.count()))
        self._refresh_quantity_combo_layout()
        self.combo_video_count.blockSignals(blocked)

    def _compact_quantity_label(self, label: str) -> str:
        text = str(label or "")
        if self._language == "en-US":
            return text.replace(" (Recommended)", " (Rec.)")
        return text

    def _fit_quantity_combo_width(self) -> None:
        fit_combo_width_to_contents(
            self.combo_video_count,
            min_width=96,
            max_width=320,
            horizontal_padding=16,
        )

    def _refresh_quantity_combo_layout(self) -> None:
        self._fit_quantity_combo_width()
        polish_combo_popup(self.combo_video_count, visible_rows=self.combo_video_count.count(), row_height=32)

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

    def configure_for_platform(
        self,
        plugin_id: str,
        defaults: dict | None = None,
        *,
        count_options: list[dict[str, Any]] | None = None,
        count_unit: str | None = None,
    ) -> None:
        defaults = defaults or {}
        self.set_platform_placeholder(plugin_id)
        inferred_unit = self._infer_count_unit(plugin_id, defaults, count_unit)
        self._quantity_mode = inferred_unit
        self.video_count_label.setText(tr(COUNT_LABELS[inferred_unit], self._language))
        self.quantity_unit_label.hide()
        count_key = "max_pages" if inferred_unit == "pages" else "max_items"
        default_count = int(defaults.get(count_key) or (1 if inferred_unit == "pages" else 20))
        self._populate_quantity_options(count_options or self._fallback_count_options(inferred_unit), default=default_count)

    @staticmethod
    def _infer_count_unit(plugin_id: str, defaults: dict, count_unit: str | None = None) -> str:
        unit = str(count_unit or "").strip().lower()
        if unit in COUNT_UNITS:
            return unit
        plugin_key = str(plugin_id or "").strip().lower()
        if plugin_key == "bilibili":
            return "pages"
        if plugin_key == "xiaohongshu":
            return "notes"
        if "max_pages" in defaults and "max_items" not in defaults:
            return "pages"
        return "videos"

    @staticmethod
    def _fallback_count_options(count_unit: str) -> list[dict[str, str]]:
        if count_unit == "pages":
            return platform_page_count_options()
        if count_unit == "notes":
            return platform_note_count_options()
        return platform_count_options()

    def quantity_mode(self) -> str:
        return self._quantity_mode

    def set_language(self, language: str | None) -> None:
        self._language = normalize_language(language)
        self._apply_search_placeholder()
        self.video_count_label.setText(tr(COUNT_LABELS.get(self._quantity_mode, "视频数:"), self._language))
        self.quantity_unit_label.hide()
        current_value = self.current_video_count()
        if self._quantity_options:
            self._populate_quantity_options(self._quantity_options, default=current_value)
        set_label = getattr(self.btn_start, "set_label", None)
        if callable(set_label):
            set_label(tr("启动任务", self._language))
        else:
            self.btn_start.setText(tr("启动任务", self._language))
        self.btn_stop.setText(tr("停止", self._language))
        self.btn_dir.setText(tr("更改目录", self._language))
        self.btn_theme.setToolTip(tr("切换主题", self._language))
        self._fit_action_buttons()

    @staticmethod
    def _placeholder_for_platform(plugin_id: str) -> str:
        plugin = registry.get_plugin(str(plugin_id or ""))
        if plugin is None:
            return "输入：主页链接、分享链接或合集链接..."
        return str(plugin.get_search_placeholder() or "输入：主页链接、分享链接或合集链接...")

    def set_platform_placeholder(self, plugin_id: str) -> None:
        self._platform_id = str(plugin_id or "")
        self._search_placeholder_source = self._placeholder_for_platform(self._platform_id)
        self._apply_search_placeholder()

    def _apply_search_placeholder(self) -> None:
        self.inp_search.setPlaceholderText(tr(self._search_placeholder_source, self._language))

    def set_theme_icon(self, is_dark_theme: bool) -> None:
        self._is_dark_theme = bool(is_dark_theme)
        self._apply_button_styles()
        self.set_theme_preview_icon(is_dark_theme)
        if self.btn_start.property("running") == "true":
            self.btn_start.set_crawl_running(True, is_dark_theme=is_dark_theme)

    def set_theme_preview_icon(self, is_dark_theme: bool) -> None:
        self.btn_theme.setText("")
        self._set_button_icon(self.btn_theme, action_icon_file("theme_dark" if is_dark_theme else "theme_light"))

    def set_theme_button_busy(self, busy: bool) -> None:
        busy = bool(busy)
        self.btn_theme.setProperty("themeBusy", "true" if busy else "false")
        self.btn_theme.setEnabled(True)
        self.btn_theme.setToolTip(
            tr("正在切换主题...", self._language) if busy else tr("切换主题", self._language)
        )
        self.btn_theme.style().unpolish(self.btn_theme)
        self.btn_theme.style().polish(self.btn_theme)
        self.btn_theme.update()

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
            padding: 0px 10px;
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
            padding: 0px 10px;
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
            min-width: 48px;
            background-color: {colors['panel']};
            border: 1px solid {colors['border']};
            border-radius: 18px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {colors['panel_soft']};
            border-color: {colors['border_strong']};
        }}
        QPushButton[themeBusy="true"],
        QPushButton:disabled {{
            background-color: {colors['panel_soft']};
            border-color: {colors['border_strong']};
        }}
        """
        self.btn_start.setStyleSheet(start_style)
        self.btn_stop.setStyleSheet(neutral_style)
        self.btn_dir.setStyleSheet(neutral_style)
        self.btn_theme.setStyleSheet(theme_style)
        self._apply_control_styles(colors)
        self._fit_action_buttons()

    @staticmethod
    def _fit_text_button(button: QPushButton, base_width: int) -> None:
        button.setMinimumWidth(base_width)
        button.ensurePolished()
        button.setMinimumWidth(max(base_width, button.sizeHint().width()))
        button.updateGeometry()

    def _fit_action_buttons(self) -> None:
        self._fit_text_button(self.btn_stop, STOP_BUTTON_MIN_WIDTH)
        self._fit_text_button(self.btn_dir, DIR_BUTTON_MIN_WIDTH)
        self.layout.invalidate()

    def _apply_control_styles(self, colors: dict[str, str]) -> None:
        search_style = f"""
        QLineEdit#TopSearchInput {{
            min-height: 40px;
            border: 1px solid {colors['border_strong']};
            border-radius: 7px;
            background-color: {colors['input']};
            color: {colors['text']};
            padding: 0px 12px;
            selection-background-color: {colors['accent']};
            selection-color: #ffffff;
        }}
        QLineEdit#TopSearchInput:focus {{
            border: 2px solid {colors['accent']};
            background-color: {colors['input']};
        }}
        """
        combo_style = f"""
        QComboBox#TopQuantityCombo {{
            min-height: 40px;
            border: 1px solid {colors['border_strong']};
            border-radius: 7px;
            background-color: {colors['input']};
            color: {colors['text']};
            padding: 0px 8px;
            selection-background-color: {colors['accent']};
            selection-color: #ffffff;
        }}
        QComboBox#TopQuantityCombo:hover {{
            border-color: {colors['accent']};
            background-color: {colors['input']};
        }}
        QComboBox#TopQuantityCombo:focus,
        QComboBox#TopQuantityCombo:on {{
            border: 2px solid {colors['accent']};
            background-color: {colors['input']};
        }}
        QComboBox#TopQuantityCombo::drop-down {{
            border: none;
            width: 0px;
        }}
        QComboBox#TopQuantityCombo::down-arrow {{
            image: none;
            border: none;
            width: 0px;
            height: 0px;
        }}
        QComboBox#TopQuantityCombo QAbstractItemView {{
            background-color: {colors['panel']};
            color: {colors['text']};
            border: 2px solid {colors['accent']};
            border-radius: 7px;
            selection-background-color: {colors['accent']};
            selection-color: #ffffff;
            padding: 0px;
        }}
        QComboBox#TopQuantityCombo QAbstractItemView::item {{
            border: none;
            min-height: 32px;
            padding: 5px 8px;
        }}
        QComboBox#TopQuantityCombo QAbstractItemView::item:selected {{
            background-color: transparent;
            border: none;
            color: #ffffff;
        }}
        QComboBox#TopQuantityCombo QAbstractItemView::item:selected:hover {{
            background-color: transparent;
            border: none;
            color: #ffffff;
        }}
        QComboBox#TopQuantityCombo QAbstractItemView::item:hover {{
            background-color: transparent;
            border: none;
            color: {colors['accent']};
        }}
        """
        self.inp_search.setStyleSheet(search_style)
        self.combo_video_count.setStyleSheet(combo_style)
        self._refresh_quantity_combo_layout()

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
