from __future__ import annotations

from typing import Any
from app.debug_logger import debug_logger

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import ui_icon_path
from shared.icon_contract import platform_icon_file
from app.ui.components.combo_popup import apply_themed_combo_box, polish_combo_popup
from app.ui.components.settings_controls import SettingsComboBox, SegmentedControl, UiSwitch
from app.ui.components.settings_form import SettingsFormBuilder
from app.ui.components.settings_path_picker import SettingsPathPicker
from app.ui.components.settings_platform_controls import (
    build_platform_count_combo,
    build_platform_proxy_widget,
    build_platform_timeout_combo,
)
from shared.localization import normalize_language, platform_display_name, tr
from shared.settings_metadata import (
    CONCURRENCY_OPTIONS,
    GROUP_DESCRIPTIONS,
    GROUP_HINTS,
    GROUP_ICONS,
    PLATFORM_COUNT_OPTIONS,
    PLATFORM_FALLBACK_LETTERS,
    RETENTION_OPTIONS,
    RETRY_OPTIONS,
    SETTING_DESCRIPTIONS,
    SETTING_SHORT_DESCRIPTIONS,
    SPEED_LIMIT_OPTIONS,
    TIMEOUT_OPTIONS,
    UI_LOG_MAX_DISPLAY_OPTIONS,
)
from app.ui.pages.common import PageFrame
from app.ui.styles.settings_page import generate_settings_page_stylesheet
from app.ui.styles.themes import resolve_is_dark_theme, theme_colors
from app.ui.viewmodels.settings_options import (
    current_combo_int_value,
    current_combo_value,
    normalize_combo_options,
    platform_proxy_policy,
)
from app.ui.viewmodels.settings_platform_layout import platform_column_widths
from app.utils.qt_lifecycle import guarded_qt_callback
from app.utils.qt_runtime import load_qt_icon
from app.utils.safe_slot import safe_slot

UI_TEXT: dict[str, dict[str, str]] = {}


FORM_CONTROL_WIDTH = 320
FORM_CONTROL_WIDTH_LARGE = 520
FORM_CONTROL_WIDTH_MEDIUM = 380
FORM_CONTROL_HEIGHT = 40
FORM_SWITCH_WRAP_WIDTH = 96


class SettingsPage(PageFrame):
    """采用主从布局的配置中心。"""

    file_association_requested = pyqtSignal(bool, bool)
    setting_changed = pyqtSignal(str, str, object)
    platform_settings_visible = pyqtSignal()

    GROUP_ORDER = ("基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置")

    def __init__(self) -> None:
        super().__init__("", "", use_island=True)
        self.setObjectName("SettingsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._render_signature: tuple | None = None
        self._switches: list[UiSwitch] = []
        self._segmented_controls: list[SegmentedControl] = []
        self._theme_refresh_pending = False
        self._applying_style = False
        self._last_settings_stylesheet = ""
        self._last_theme_dark: bool | None = None
        self._relayout_pending = False
        self._rendering = False
        self._settings_snapshot: dict[str, Any] = {}
        self._group_order: list[str] = list(self.GROUP_ORDER)
        self._group_descriptions: dict[str, str] = dict(GROUP_DESCRIPTIONS)
        self._current_group = "基础设置"
        self._current_language = "zh-CN"
        self._nav_buttons: dict[str, QPushButton] = {}
        self._last_proxy_emit: tuple[str, str, str] | None = None
        self._directory_dialogs: list[QFileDialog] = []

        self.scroll = None

        self.content = QWidget()
        self.content.setObjectName("SettingsContent")

        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 8, 18, 16)
        self.content_layout.setSpacing(12)

        title_box = QWidget()
        title_box.setObjectName("SettingsPageHeader")

        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.page_title = QLabel("配置中心")
        self.page_title.setObjectName("SettingsPageTitle")
        self.page_title.setFixedHeight(28)

        self.page_subtitle = QLabel("集中管理下载行为、平台状态、播放体验、日志策略与界面外观")
        self.page_subtitle.setObjectName("SettingsPageSubtitle")
        self.page_subtitle.setFixedHeight(20)
        self.page_subtitle.setWordWrap(False)

        self.action_feedback = QLabel("")
        self.action_feedback.setObjectName("SettingsActionFeedback")
        self.action_feedback.setFixedHeight(24)
        self.action_feedback.setVisible(False)
        self.action_feedback.setWordWrap(False)

        title_layout.addWidget(self.page_title)
        title_layout.addWidget(self.page_subtitle)
        title_layout.addWidget(self.action_feedback)

        self.content_layout.addWidget(title_box)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("SettingsMainPanel")
        self.main_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        panel_layout = QHBoxLayout(self.main_panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(12)

        self.nav_panel = QFrame()
        self.nav_panel.setObjectName("SettingsSideNav")
        self.nav_panel.setFixedWidth(180)
        self.nav_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.nav_layout = QVBoxLayout(self.nav_panel)
        self.nav_layout.setContentsMargins(10, 10, 10, 10)
        self.nav_layout.setSpacing(4)

        self.nav_title = QLabel("设置分类")
        self.nav_title.setObjectName("SettingsNavTitle")
        self.nav_title.setFixedHeight(26)
        self.nav_layout.addWidget(self.nav_title)
        self._rebuild_group_navigation()

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("SettingsDetailPanel")
        self.detail_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(24, 22, 24, 20)
        self.detail_layout.setSpacing(12)

        panel_layout.addWidget(self.nav_panel)
        panel_layout.addWidget(self.detail_panel, 1)

        self.content_layout.addWidget(self.main_panel, 1)
        self.root_layout.addWidget(self.content, 1)

        self._apply_settings_page_style()
        self._refresh_language_texts()
        self._sync_nav_buttons()
        self._last_theme_dark = self._is_dark()

    def _language(self) -> str:
        appearance = self._settings_snapshot.get("外观设置") if isinstance(self._settings_snapshot, dict) else {}
        value = str(self._dict_value(appearance, "language", self._current_language or "zh-CN") or "zh-CN")
        return normalize_language(value)

    def _t(self, text: str) -> str:
        value = str(text or "")
        return tr(value, self._language())

    def _refresh_language_texts(self) -> None:
        self._current_language = self._language()
        self.page_title.setText(self._t("配置中心"))
        self.page_title.setFixedHeight(self._scaled_px(28, minimum=28))
        self.page_subtitle.setText(self._t("集中管理下载行为、平台状态、播放体验、日志策略与界面外观"))
        self.page_subtitle.setFixedHeight(self._scaled_px(20, minimum=20))
        self.action_feedback.setFixedHeight(self._scaled_px(24, minimum=24))
        self.nav_title.setText(self._t("设置分类"))
        self.nav_title.setFixedHeight(self._scaled_px(26, minimum=26))
        for group_name, button in self._nav_buttons.items():
            button.setText(self._t(group_name))

    def _is_dark(self) -> bool:
        window = self.window()
        value = getattr(window, "is_dark_theme", None) if window is not None else None

        if isinstance(value, bool):
            return value

        if callable(value):
            try:
                return bool(value())
            except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
                debug_logger.log_exception("SettingsPage", "resolve_dark_callable", exc)

        return resolve_is_dark_theme(self)

    def _colors(self) -> dict[str, str]:
        return theme_colors(self._is_dark())

    def _schedule_theme_refresh(self) -> None:
        if getattr(self, "_theme_refresh_pending", False):
            return
        self._theme_refresh_pending = True
        QTimer.singleShot(0, self._refresh_theme_widgets)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)

        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        }:
            self._schedule_theme_refresh()

    def _schedule_relayout_cards(self) -> None:
        if getattr(self, "_rendering", False):
            return
        if getattr(self, "_relayout_pending", False):
            return

        self._relayout_pending = True
        QTimer.singleShot(0, self._run_pending_relayout)

    @safe_slot
    def _run_pending_relayout(self) -> None:
        self._relayout_pending = False
        if getattr(self, "_rendering", False):
            return
        previous_inner_width = getattr(self, "_last_platform_inner_width", None)
        self._sync_content_card_widths()
        current_inner_width = self._form_inner_width()
        if (
            self._current_group == self.GROUP_ORDER[2]
            and self._settings_snapshot
            and previous_inner_width is not None
            and abs(int(previous_inner_width) - int(current_inner_width)) >= 4
        ):
            self._render_current_group()

    def _content_card_width(self) -> int:
        detail_width = self.detail_panel.width() if hasattr(self, "detail_panel") else 1000
        margins = self.detail_layout.contentsMargins() if hasattr(self, "detail_layout") else None
        horizontal_margins = (margins.left() + margins.right()) if margins is not None else 48
        available = max(320, detail_width - horizontal_margins - 4)

        if getattr(self, "_current_group", "") == self.GROUP_ORDER[2]:
            desired = min(1120, max(min(available, 720), int(available * 0.96)))
        else:
            desired = min(1080, max(min(available, 520), int(available * 0.82)))

        return max(320, min(available, desired))

    def _form_inner_width(self) -> int:
        return max(300, self._content_card_width() - 20)

    def _effective_control_width(self, control_width: int) -> int:
        return min(int(control_width), max(150, self._content_card_width() - 260))

    def _settings_form_builder(self) -> SettingsFormBuilder:
        return SettingsFormBuilder(
            translate=self._t,
            scaled_px=self._scaled_px,
            content_card_width=self._content_card_width,
            effective_control_width=self._effective_control_width,
            safe_icon_pixmap=self._safe_icon_pixmap,
            fallback_group_icon_text=self._fallback_group_icon_text,
            fallback_detail_icon_style=self._fallback_detail_icon_style,
            group_icons=GROUP_ICONS,
            group_descriptions=self._group_descriptions,
            default_group_descriptions=GROUP_DESCRIPTIONS,
            group_hints=GROUP_HINTS,
            setting_short_descriptions=SETTING_SHORT_DESCRIPTIONS,
            setting_descriptions=SETTING_DESCRIPTIONS,
            switch_wrap_width=FORM_SWITCH_WRAP_WIDTH,
        )

    def _platform_col_widths(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        reserve_vertical_scrollbar: bool = False,
    ) -> dict[str, int]:
        font = self.font()
        font.setPixelSize(self._scaled_px(13, minimum=12))
        scrollbar_reserve = 0
        if reserve_vertical_scrollbar:
            scrollbar_reserve = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) + 2
        return platform_column_widths(
            rows,
            content_width=self._form_inner_width() - 28 - 40 - scrollbar_reserve,
            translate=self._t,
            metrics=QFontMetrics(font),
            count_options=PLATFORM_COUNT_OPTIONS,
            timeout_options=TIMEOUT_OPTIONS,
            label_padding=self._scaled_px(38, minimum=34),
        )

    def _scale_factor(self) -> float:
        app = QApplication.instance()
        raw = app.property("ui_scale") if app is not None else "100%"
        text = str(raw or "100%").strip()
        if text.endswith("%"):
            try:
                return max(0.85, min(1.35, float(text[:-1]) / 100.0))
            except ValueError:
                return 1.0
        try:
            return max(0.85, min(1.35, float(text)))
        except ValueError:
            return 1.0

    def _font_factor(self) -> float:
        app = QApplication.instance()
        raw = app.property("ui_font_size") if app is not None else "medium"
        return {"small": 0.92, "medium": 1.0, "large": 1.12}.get(str(raw or "medium").strip().lower(), 1.0)

    def _scaled_px(self, value: int, *, minimum: int | None = None) -> int:
        scaled = round(int(value) * self._scale_factor() * self._font_factor())
        if minimum is not None:
            return max(minimum, scaled)
        return scaled

    def _sync_content_card_widths(self) -> None:
        if not hasattr(self, "detail_panel"):
            return
        width = self._content_card_width()
        inner_width = self._form_inner_width()
        for widget in self.detail_panel.findChildren(QFrame):
            object_name = widget.objectName()
            if object_name in {"SettingsFormCard", "SettingsHintCard"}:
                widget.setFixedWidth(width)
            elif object_name in {"SettingsPlatformTablePanel", "SettingsPlatformSummaryBar"}:
                widget.setFixedWidth(inner_width)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_relayout_cards()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._settings_snapshot:
            QTimer.singleShot(0, self._repair_empty_view_if_needed)

    def _view_needs_rebuild(self) -> bool:
        if not hasattr(self, "detail_layout") or not hasattr(self, "nav_layout"):
            return False
        expected_groups = len(self._group_order)
        if expected_groups and len(self._nav_buttons) < expected_groups:
            return True
        if self.detail_layout.count() < 3:
            return True
        seen = set()
        for index in range(self.detail_layout.count()):
            item = self.detail_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                seen.add(widget.objectName())
        return not {"SettingsDetailHeader", "SettingsFormCard"}.issubset(seen)

    @safe_slot
    def _repair_empty_view_if_needed(self) -> None:
        if not self.isVisible() or self._rendering or not self._settings_snapshot:
            return
        if not self._view_needs_rebuild():
            return
        self._rebuild_group_navigation()
        self._refresh_language_texts()
        self._render_current_group()

    @safe_slot
    def _refresh_theme_widgets(self) -> None:
        self._theme_refresh_pending = False

        is_dark = self._is_dark()
        colors = self._colors()

        self._last_theme_dark = is_dark
        self._apply_settings_page_style()

        for switch in list(self._switches):
            if switch is not None:
                switch.set_theme_colors(colors)

        for control in list(self._segmented_controls):
            if control is not None:
                control.set_theme_colors(colors)

        for combo in self.findChildren(QComboBox):
            self._style_combo_popup(combo)

    def sync_external_theme(self, is_dark: bool, *, follow_system: bool | None = None) -> None:
        theme_value = "dark" if is_dark else "light"
        settings = self._settings_snapshot if isinstance(self._settings_snapshot, dict) else {}
        appearance = settings.get("外观设置")
        if isinstance(appearance, dict):
            appearance["theme"] = theme_value
            if follow_system is not None:
                appearance["follow_system"] = bool(follow_system)
            self._render_signature = None

        for control in list(self._segmented_controls):
            if control is not None and control.property("settingsRole") == "theme":
                control.set_value(theme_value)
                control.set_theme_colors(self._colors())
                control.style().unpolish(control)
                control.style().polish(control)
                control.update()

        if follow_system is not None:
            for switch in list(self._switches):
                if switch is not None and switch.property("settingsRole") == "follow_system":
                    blocked = switch.blockSignals(True)
                    try:
                        switch.setChecked(bool(follow_system))
                    finally:
                        switch.blockSignals(blocked)
                    switch.update()

    def render(self, snapshot: dict) -> None:
        settings = snapshot.get("settings_snapshot") or {}
        contract = snapshot.get("settings_contract") if isinstance(snapshot.get("settings_contract"), dict) else {}
        self._update_group_contract(settings, contract)
        signature = self._settings_signature(settings, contract)
        needs_rebuild = self._view_needs_rebuild()
        if signature == self._render_signature and not needs_rebuild:
            return
        if self._render_signature is not None and self._has_editor_focus() and not needs_rebuild:
            return

        if getattr(self, "_rendering", False):
            return

        self._rendering = True
        try:
            updates_enabled = self.updatesEnabled()
            self.setUpdatesEnabled(False)
            try:
                self._close_combo_popups()
                self._settings_snapshot = settings
                if self._current_group not in self._group_order and self._group_order:
                    self._current_group = self._group_order[0]
                self._rebuild_group_navigation()
                self._refresh_language_texts()
                self._render_signature = signature
                self._render_current_group()
                self._refresh_theme_widgets()
            finally:
                self.setUpdatesEnabled(updates_enabled)
                if updates_enabled:
                    self.update()
        except Exception as exc:
            self._render_settings_error(exc)
        finally:
            self._rendering = False

    def _render_settings_error(self, exc: Exception) -> None:
        self._clear_detail_panel()

        error_card = QFrame()
        error_card.setObjectName("SettingsCard")
        error_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(error_card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("配置中心渲染失败")
        title.setObjectName("SettingsDetailTitle")
        layout.addWidget(title)

        detail = QLabel(str(exc))
        detail.setWordWrap(True)
        detail.setObjectName("SettingsRowLabel")
        layout.addWidget(detail)

        self.detail_layout.addWidget(error_card, 0, Qt.AlignmentFlag.AlignTop)
        self._apply_settings_page_style()

    def _build_nav_button(self, group_name: str) -> QPushButton:
        button = QPushButton(self._t(group_name))
        button.setObjectName("SettingsNavButton")
        button.setProperty("groupName", group_name)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(38)

        pixmap = self._safe_icon_pixmap(GROUP_ICONS.get(group_name, "nav_settings.png"), 16)
        if pixmap is not None and not pixmap.isNull():
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(16, 16))

        button.clicked.connect(lambda _checked=False, name=group_name: self._set_current_group(name))
        return button

    def is_platform_settings_visible(self) -> bool:
        return self._current_group == self.GROUP_ORDER[2]

    def _emit_platform_settings_visible_if_needed(self) -> None:
        if self.is_platform_settings_visible():
            self.platform_settings_visible.emit()

    def _set_current_group(self, group_name: str) -> None:
        if group_name not in self._group_order:
            return
        if self._current_group == group_name:
            self._sync_nav_buttons()
            if self._view_needs_rebuild():
                self._render_current_group()
            self._emit_platform_settings_visible_if_needed()
            return

        self._current_group = group_name
        self._sync_nav_buttons()
        self._render_current_group()
        self._emit_platform_settings_visible_if_needed()

    def _update_group_contract(self, settings_snapshot: dict, settings_contract: dict) -> None:
        raw_order = settings_contract.get("group_order") if isinstance(settings_contract, dict) else None
        raw_descriptions = settings_contract.get("group_descriptions") if isinstance(settings_contract, dict) else None

        if isinstance(raw_order, (list, tuple)):
            ordered = []
            seen_order = set()
            for group in raw_order:
                name = str(group).strip()
                if not name or name in seen_order:
                    continue
                ordered.append(name)
                seen_order.add(name)
        else:
            ordered = list(self.GROUP_ORDER)

        seen = set(ordered)
        for group in settings_snapshot.keys():
            name = str(group).strip()
            if not name or name in seen:
                continue
            ordered.append(name)
            seen.add(name)

        descriptions: dict[str, str] = dict(GROUP_DESCRIPTIONS)
        if isinstance(raw_descriptions, dict):
            for key, value in raw_descriptions.items():
                descriptions[str(key)] = str(value)

        self._group_order = ordered
        self._group_descriptions = {name: str(descriptions.get(name, "")) for name in self._group_order}

    def _rebuild_group_navigation(self) -> None:
        while self.nav_layout.count() > 1:
            item = self.nav_layout.takeAt(1)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        self._nav_buttons = {}
        for group_name in self._group_order:
            button = self._build_nav_button(group_name)
            self.nav_layout.addWidget(button)
            self._nav_buttons[group_name] = button
        self.nav_layout.addStretch(1)
        self._sync_nav_buttons()

    def _sync_nav_buttons(self) -> None:
        for name, button in self._nav_buttons.items():
            active = name == self._current_group
            button.setChecked(active)
            button.setProperty("active", "true" if active else "false")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _clear_detail_panel(self) -> None:
        self._close_combo_popups()
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _close_combo_popups(self) -> None:
        for combo in self.findChildren(QComboBox):
            try:
                view = combo.view()
                if view is not None and (view.isVisible() or view.window().isVisible()):
                    combo.hidePopup()
                combo.setProperty("popupOpen", "false")
            except RuntimeError:
                continue

    def _render_current_group(self) -> None:
        if not hasattr(self, "detail_layout"):
            return

        self.detail_panel.setUpdatesEnabled(False)
        try:
            try:
                self._clear_detail_panel()
                self._switches.clear()
                self._segmented_controls.clear()

                group_name = self._current_group
                value = self._settings_snapshot.get(group_name, {})

                header = self._build_detail_header(group_name)
                self.detail_layout.addWidget(header, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

                form_card, form_layout = self._build_form_card()

                if group_name == "基础设置":
                    self._build_basic_settings(form_layout, value)
                elif group_name == "下载设置":
                    self._build_download_settings(form_layout, value)
                elif group_name == "平台设置":
                    self._build_platform_settings(form_layout, value)
                elif group_name == "播放设置":
                    self._build_playback_settings(form_layout, value)
                elif group_name == "日志设置":
                    self._build_log_settings(form_layout, value)
                elif group_name == "外观设置":
                    self._build_appearance_settings(form_layout, value)

                hint_card = self._build_group_hint_card(group_name)

                self.detail_layout.addWidget(
                    form_card,
                    0,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
                self.detail_layout.addSpacing(2)
                self.detail_layout.addWidget(
                    hint_card,
                    0,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
                self.detail_layout.addStretch(1)
            except Exception as exc:
                debug_logger.log_exception(
                    "SettingsPage",
                    "render_current_group",
                    exc,
                    details={"group": str(getattr(self, "_current_group", ""))},
                )
                self._render_settings_error(exc)
        finally:
            self.detail_panel.setUpdatesEnabled(True)
            self.detail_panel.update()

        self._refresh_theme_widgets()

    def _build_form_card(self) -> tuple[QFrame, QVBoxLayout]:
        return self._settings_form_builder().build_form_card()

    def _build_group_hint_card(self, group_name: str) -> QFrame:
        return self._settings_form_builder().build_group_hint_card(group_name)

    def _build_detail_header(self, group_name: str) -> QWidget:
        return self._settings_form_builder().build_detail_header(group_name)

    def _has_editor_focus(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            if focused is self or self.isAncestorOf(focused):
                return not focused.isReadOnly()
        for editor in self.findChildren(QLineEdit):
            if editor.hasFocus() and not editor.isReadOnly():
                return True
            original = editor.property("settingsOriginalText")
            if original is not None and not editor.isReadOnly() and editor.text() != str(original):
                return True
        return False

    @staticmethod
    def _settings_signature(settings: dict, contract: dict | None) -> tuple:
        def freeze(value: Any):
            if isinstance(value, dict):
                return tuple(sorted((str(key), freeze(item)) for key, item in value.items()))
            if isinstance(value, list):
                return tuple(freeze(item) for item in value)
            return str(value)

        return freeze((settings, contract or {}))

    @staticmethod
    def _dict_value(value: Any, key: str, default: Any = "") -> Any:
        return value.get(key, default) if isinstance(value, dict) else default

    def _safe_icon_pixmap(self, icon_file: str, size: int = 20) -> QPixmap | None:
        """安全加载图标；资源缺失时不让 SettingsPage 崩溃。"""
        candidates = [
            ui_icon_path(icon_file),
            icon_file,
            ui_icon_path("nav_settings.png"),
        ]

        icon = load_qt_icon(candidates)

        if icon is None:
            return None

        if icon.isNull():
            return None

        return icon.pixmap(size, size)

    def _fallback_group_icon_text(self, group_name: str) -> str:
        mapping = {
            "基础设置": "基",
            "下载设置": "下",
            "平台设置": "平",
            "播放设置": "播",
            "日志设置": "志",
            "外观设置": "观",
        }
        return mapping.get(group_name, "设")

    def _fallback_group_icon_style(self) -> str:
        c = self._colors()
        return f"""
        QLabel#SettingsCardIcon {{
            background: {c["accent_soft"]};
            color: {c["accent"]};
            border-radius: 11px;
            font-size: {self._scaled_px(11, minimum=10)}px;
            font-weight: 800;
        }}
        """

    def _fallback_detail_icon_style(self) -> str:
        c = self._colors()
        return f"""
        QLabel#SettingsDetailIcon {{
            background: {c["accent_soft"]};
            color: {c["accent"]};
            border-radius: 16px;
            font-size: {self._scaled_px(12, minimum=10)}px;
            font-weight: 800;
        }}
        """

    def _build_setting_row(
        self,
        label: str,
        control: QWidget,
        *,
        control_width: int = FORM_CONTROL_WIDTH,
        compact: bool = False,
    ) -> QWidget:
        return self._settings_form_builder().build_setting_row(
            label,
            control,
            control_width=control_width,
            compact=compact,
        )

    def _build_combo(self, options: list[Any], current: Any, *, width: int = 0) -> QComboBox:
        combo = SettingsComboBox()
        combo.setObjectName("SettingsCombo")
        combo.setEditable(False)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo_height = self._scaled_px(FORM_CONTROL_HEIGHT, minimum=FORM_CONTROL_HEIGHT)
        combo.setFixedHeight(combo_height)
        combo.setProperty("settingsControlHeight", combo_height)
        combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(160)
        combo.setMaximumWidth(520)
        combo.setToolTip(str(current or ""))
        if width > 0:
            combo.setFixedWidth(width)
            combo.setProperty("comboPopupMaxWidth", int(width))

        normalized_options = normalize_combo_options(options, current)
        combo.setMaxVisibleItems(max(1, min(len(normalized_options), 12)))
        for value, label in normalized_options:
            combo.addItem(self._t(label), value)

        text = str(current or "")
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index < 0:
            for option_value, option_label in normalized_options:
                if text and (text in option_label or text in option_value):
                    index = combo.findData(option_value)
                    break
        combo.setCurrentIndex(index if index >= 0 else 0)

        view = combo.view()
        if view is not None and combo.width() > 0:
            view.setObjectName("SettingsComboPopup")
            view.setMinimumWidth(combo.width())
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            if hasattr(view, "setUniformItemSizes"):
                view.setUniformItemSizes(True)
            self._style_combo_popup(combo)
        else:
            polish_combo_popup(combo)

        return combo

    def _style_combo_popup(self, combo: QComboBox) -> None:
        view = combo.view()
        if view is None:
            return
        view.setObjectName("SettingsComboPopup")
        visible_rows = max(1, min(combo.count(), 12))
        apply_themed_combo_box(
            combo,
            visible_rows=visible_rows,
            row_height=self._scaled_px(38, minimum=38),
            control_style=False,
        )
        view.setObjectName("SettingsComboPopup")
        width = combo.width() or combo.minimumWidth()
        if width > 0:
            target_width = int(width)
            combo.setProperty("comboPopupMaxWidth", target_width)
            combo.setProperty("comboPopupClampToControl", "true")
            view.setProperty("comboPopupTargetWidth", target_width)
            view.setMinimumWidth(target_width)
            view.setMaximumWidth(target_width)

    def _emit_setting_changed(self, section: str, key: str, value: Any) -> None:
        if self._rendering:
            return
        if not section or not key:
            return
        self.setting_changed.emit(section, key, value)

    def _emit_basic_setting_changed(self, key: str, value: Any) -> None:
        self._emit_setting_changed("common", key, value)

    def _emit_theme_setting_changed(self, value: str) -> None:
        for switch in list(self._switches):
            if switch is not None and switch.property("settingsRole") == "follow_system":
                blocked = switch.blockSignals(True)
                try:
                    switch.setChecked(False)
                finally:
                    switch.blockSignals(blocked)
                switch.update()
        appearance = self._settings_snapshot.get("外观设置") if isinstance(self._settings_snapshot, dict) else None
        if isinstance(appearance, dict):
            appearance["follow_system"] = False
            appearance["theme"] = str(value)
            self._render_signature = None
        self._emit_setting_changed("common", "theme", value)

    def _build_switch(self, checked: bool) -> UiSwitch:
        switch = UiSwitch(self)
        switch.setChecked(bool(checked))
        switch.set_theme_colors(self._colors())
        self._switches.append(switch)
        return switch

    def _build_path_picker(self, value: Any, *, setting_key: str = "") -> QWidget:
        picker = SettingsPathPicker(value, setting_key=setting_key, translate=self._t, parent=self)
        picker.path_committed.connect(lambda key, text: self._emit_basic_setting_changed(key, text))
        picker.browse_requested.connect(lambda editor, key: self._browse_download_directory(editor, setting_key=key))
        return picker

    def _commit_path_editor(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        text = editor.text()
        editor.setToolTip(text)
        editor.setProperty("settingsOriginalText", text)
        if setting_key:
            self._emit_basic_setting_changed(setting_key, text)

    @staticmethod
    def _scroll_path_editor_start(editor: QLineEdit) -> None:
        SettingsPathPicker.scroll_editor_start(editor)

    def _browse_download_directory(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        self._open_download_directory_dialog(editor, setting_key=setting_key)

    def _open_download_directory_dialog(self, editor: QLineEdit, *, setting_key: str = "") -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            self._t("选择下载目录"),
            editor.text() or "",
            QFileDialog.Option.ShowDirsOnly,
        )
        self._apply_browsed_download_directory(editor, directory, setting_key=setting_key)

    def _clear_directory_dialog(self, dialog: QFileDialog) -> None:
        try:
            self._directory_dialogs = [item for item in self._directory_dialogs if item is not dialog]
        except RuntimeError as exc:
            debug_logger.log_exception("SettingsPage", "clear_directory_dialog", exc)

    def _apply_browsed_download_directory(self, editor: QLineEdit, directory: str, *, setting_key: str = "") -> None:
        if not directory:
            return
        picker = editor.parentWidget()
        if isinstance(picker, SettingsPathPicker):
            if not picker.apply_directory(directory):
                return
        else:
            try:
                editor.setText(directory)
                editor.setToolTip(directory)
                editor.setProperty("settingsOriginalText", directory)
                self._scroll_path_editor_start(editor)
            except RuntimeError as exc:
                debug_logger.log_exception("SettingsPage", "apply_browsed_download_directory", exc)
                return
        if setting_key:
            self._emit_basic_setting_changed(setting_key, directory)

    def _build_basic_settings(self, layout: QVBoxLayout, value: Any) -> None:
        large_w = self._effective_control_width(FORM_CONTROL_WIDTH_LARGE)
        options = self._dict_value(value, "_options", {})
        filename_options = self._dict_value(options, "filename_template", [])
        open_mode_options = self._dict_value(options, "default_open_mode", [])

        layout.addWidget(
            self._build_setting_row(
                "\u4e0b\u8f7d\u76ee\u5f55",
                self._build_path_picker(
                    self._dict_value(value, "download_directory"),
                    setting_key="download_directory",
                ),
                control_width=large_w,
            )
        )

        naming_row = QWidget()
        naming_row.setObjectName("SettingsNamingControl")
        naming_row.setFixedWidth(large_w)
        naming_height = self._scaled_px(FORM_CONTROL_HEIGHT, minimum=FORM_CONTROL_HEIGHT)
        naming_row.setFixedHeight(naming_height)
        naming_row.setProperty("settingsControlHeight", naming_height)
        naming_layout = QHBoxLayout(naming_row)
        naming_layout.setContentsMargins(0, 0, 0, 0)
        naming_layout.setSpacing(6)
        naming_combo = self._build_combo(
            filename_options,
            self._dict_value(value, "filename_template", "current"),
            width=large_w,
        )
        naming_combo.currentIndexChanged.connect(
            lambda *_args, combo=naming_combo: self._emit_basic_setting_changed(
                "filename_template",
                current_combo_value(combo),
            )
        )
        naming_layout.addWidget(naming_combo)
        layout.addWidget(
            self._build_setting_row("\u6587\u4ef6\u547d\u540d\u89c4\u5219", naming_row, control_width=large_w),
        )

        auto_open_switch = self._build_switch(bool(self._dict_value(value, "open_after_download", False)))
        auto_open_switch.toggled.connect(
            lambda checked: self._emit_basic_setting_changed("open_after_download", bool(checked))
        )
        layout.addWidget(
            self._build_setting_row(
                "\u4e0b\u8f7d\u540e\u81ea\u52a8\u6253\u5f00",
                auto_open_switch,
            )
        )

        show_browser_switch = self._build_switch(bool(self._dict_value(value, "show_browser_window", True)))
        show_browser_switch.toggled.connect(
            lambda checked: self._emit_basic_setting_changed("show_browser_window", bool(checked))
        )
        layout.addWidget(
            self._build_setting_row(
                "\u663e\u793a\u6d4f\u89c8\u5668\u5185\u6838",
                show_browser_switch,
            )
        )

        open_mode_row = QWidget()
        open_mode_row.setObjectName("SettingsOpenBehaviorControl")
        open_mode_row.setFixedWidth(large_w)
        open_mode_height = self._scaled_px(44, minimum=44)
        open_mode_row.setFixedHeight(open_mode_height)
        open_mode_row.setProperty("settingsControlHeight", open_mode_height)
        open_mode_layout = QHBoxLayout(open_mode_row)
        open_mode_h_inset = self._scaled_px(4, minimum=4)
        open_mode_layout.setContentsMargins(open_mode_h_inset, 2, open_mode_h_inset, 2)
        open_mode_spacing = 8
        open_mode_layout.setSpacing(open_mode_spacing)
        open_mode_content_width = max(0, large_w - (open_mode_h_inset * 2))
        bind_button = QPushButton(self._t("\u7ed1\u5b9a\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f"))
        bind_button.setObjectName("SettingsActionButton")
        bind_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_width = min(self._scaled_px(118, minimum=108), max(96, open_mode_content_width - 180))
        bind_button.setFixedWidth(bind_width)
        bind_button.setFixedHeight(self._scaled_px(38, minimum=38))
        bind_button.clicked.connect(lambda: self.file_association_requested.emit(True, True))
        open_mode_combo = self._build_combo(
            open_mode_options,
            self._dict_value(value, "default_open_mode", "builtin_player"),
            width=max(96, open_mode_content_width - bind_width - open_mode_spacing),
        )
        open_mode_combo.currentIndexChanged.connect(
            lambda *_args, combo=open_mode_combo: self._emit_basic_setting_changed(
                "default_open_mode",
                current_combo_value(combo),
            )
        )
        open_mode_layout.addWidget(open_mode_combo)
        open_mode_layout.addWidget(bind_button)
        layout.addWidget(
            self._build_setting_row("\u4e0b\u8f7d\u5b8c\u6210\u6253\u5f00\u65b9\u5f0f", open_mode_row, control_width=large_w),
        )

    def _build_download_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        max_concurrent = self._build_combo(
            self._dict_value(options, "max_concurrent", CONCURRENCY_OPTIONS),
            self._dict_value(value, "max_concurrent", 3),
            width=FORM_CONTROL_WIDTH,
        )
        max_concurrent.currentIndexChanged.connect(
            lambda *_args, combo=max_concurrent: self._emit_setting_changed(
                "download",
                "max_concurrent",
                current_combo_int_value(combo, 3),
            )
        )
        layout.addWidget(self._build_setting_row("并发数", max_concurrent))

        image_concurrency_switch = self._build_switch(
            self._dict_value(value, "image_respects_concurrency", False)
        )
        image_concurrency_switch.toggled.connect(
            lambda checked: self._emit_setting_changed(
                "download",
                "image_respects_concurrency",
                bool(checked),
            )
        )
        layout.addWidget(self._build_setting_row("图片受并发数限制", image_concurrency_switch))

        request_timeout = self._build_combo(
            self._dict_value(options, "request_timeout", TIMEOUT_OPTIONS),
            self._dict_value(value, "request_timeout", 60),
            width=FORM_CONTROL_WIDTH,
        )
        request_timeout.currentIndexChanged.connect(
            lambda *_args, combo=request_timeout: self._emit_setting_changed(
                "download",
                "request_timeout",
                current_combo_int_value(combo, 60),
            )
        )
        layout.addWidget(self._build_setting_row("请求超时（秒）", request_timeout))

        max_retries = self._build_combo(
            self._dict_value(options, "max_retries", RETRY_OPTIONS),
            self._dict_value(value, "max_retries", 3),
            width=FORM_CONTROL_WIDTH,
        )
        max_retries.currentIndexChanged.connect(
            lambda *_args, combo=max_retries: self._emit_setting_changed(
                "download",
                "max_retries",
                current_combo_int_value(combo, 3),
            )
        )
        layout.addWidget(self._build_setting_row("重试次数", max_retries))

        resume_switch = self._build_switch(self._dict_value(value, "resume_enabled", True))
        resume_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("download", "resume_enabled", bool(checked))
        )
        layout.addWidget(self._build_setting_row("断点续传", resume_switch))

        speed_limit = self._build_combo(
            self._dict_value(options, "speed_limit_kb", SPEED_LIMIT_OPTIONS),
            self._dict_value(value, "speed_limit_kb", 0),
            width=FORM_CONTROL_WIDTH,
        )
        speed_limit.currentIndexChanged.connect(
            lambda *_args, combo=speed_limit: self._emit_setting_changed(
                "download",
                "speed_limit_kb",
                current_combo_int_value(combo, 0),
            )
        )
        layout.addWidget(self._build_setting_row("下载速度限制（KB/s）", speed_limit))

        video_only_switch = self._build_switch(self._dict_value(value, "video_only", False))
        video_only_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("download", "video_only", bool(checked))
        )
        layout.addWidget(self._build_setting_row("仅下载视频", video_only_switch))

    def _platform_icon_label(self, platform_id: str, platform_name: str) -> QLabel:
        label = QLabel()
        label.setObjectName("SettingsPlatformIcon")
        label.setFixedSize(24, 24)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pid = str(platform_id or "").strip().lower()
        icon_file = platform_icon_file(pid) if pid else "platform_web.png"
        pixmap = self._safe_icon_pixmap(icon_file, 20)

        if pixmap is not None and not pixmap.isNull():
            label.setPixmap(pixmap)
            return label

        letter = PLATFORM_FALLBACK_LETTERS.get(pid, (platform_name or "?")[:1].upper())
        label.setText(letter)
        colors = self._colors()
        label.setStyleSheet(
            f"""
            QLabel#SettingsPlatformIcon {{
                background: {colors["accent_soft"]};
                color: {colors["accent"]};
                border-radius: 12px;
                font-size: {self._scaled_px(11, minimum=10)}px;
                font-weight: 700;
            }}
            """
        )
        return label

    def _auth_badge(self, auth_status: str, *, fixed_width: int | None = None) -> QWidget:
        authenticated = str(auth_status or "").strip() == "已认证"
        badge = QLabel(self._t("已认证" if authenticated else "未认证"))
        badge.setObjectName("SettingsAuthBadge")
        badge.setProperty("authenticated", "true" if authenticated else "false")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(28)
        if fixed_width is not None:
            badge.setFixedWidth(fixed_width)
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        return badge

    def _platform_header_cell(self, text: str, width: int) -> QLabel:
        label = QLabel(self._t(text))
        label.setObjectName("SettingsPlatformHeaderCell")
        label.setFixedWidth(width)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _platform_count_combo(self, row: dict[str, Any], *, width: int | None = None) -> QComboBox:
        return build_platform_count_combo(
            row,
            build_combo=self._build_combo,
            emit_setting_changed=self._emit_setting_changed,
            translate=self._t,
            width=width,
        )

    def _platform_timeout_combo(self, row: dict[str, Any], *, width: int | None = None) -> QComboBox:
        return build_platform_timeout_combo(
            row,
            build_combo=self._build_combo,
            emit_setting_changed=self._emit_setting_changed,
            translate=self._t,
            width=width,
        )

    def _platform_proxy_widget(
        self,
        row: dict[str, Any],
        policy: dict[str, Any],
        *,
        row_container: QWidget | None = None,
        width: int | None = None,
    ) -> QWidget:
        return build_platform_proxy_widget(
            row,
            policy,
            build_combo=self._build_combo,
            emit_proxy_setting_changed=self._emit_proxy_setting_changed,
            translate=self._t,
            scaled_px=self._scaled_px,
            row_container=row_container,
            width=width,
        )

    def _emit_proxy_setting_changed(self, platform_id: str, key: str, value: str) -> None:
        signature = (str(platform_id), str(key), str(value))
        if self._last_proxy_emit == signature:
            return
        self._last_proxy_emit = signature
        self._emit_setting_changed(platform_id, key, value)

    def _elided_platform_name(self, platform_name: str, max_width: int) -> str:
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(platform_name, Qt.TextElideMode.ElideRight, max(24, max_width))

    def _build_platform_summary_chip(self, label: str, value: str, kind: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName("SettingsPlatformSummaryChip")
        chip.setProperty("kind", kind)
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setFixedHeight(30)

        layout = QHBoxLayout(chip)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        label_widget = QLabel(self._t(label))
        label_widget.setObjectName("SettingsPlatformSummaryLabel")

        value_widget = QLabel(value)
        value_widget.setObjectName("SettingsPlatformSummaryValue")
        value_widget.setProperty("kind", kind)

        layout.addWidget(label_widget)
        layout.addWidget(value_widget)

        chip.style().unpolish(chip)
        chip.style().polish(chip)
        value_widget.style().unpolish(value_widget)
        value_widget.style().polish(value_widget)

        return chip

    def _build_platform_summary_bar(self, rows: list[dict[str, Any]]) -> QFrame:
        total = len(rows)
        authed = sum(1 for row in rows if str(row.get("auth_status") or "") == "已认证")
        unauth = max(0, total - authed)
        proxy_editable = sum(
            1
            for row in rows
            if platform_proxy_policy(
                str(row.get("id") or ""),
                str(row.get("name") or row.get("id") or ""),
            ).get("editable")
        )

        bar = QFrame()
        bar.setObjectName("SettingsPlatformSummaryBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedWidth(self._form_inner_width())
        bar.setFixedHeight(48)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_platform_summary_chip("平台总数", str(total), "neutral"))
        layout.addWidget(self._build_platform_summary_chip("已认证", str(authed), "success"))
        layout.addWidget(self._build_platform_summary_chip("未认证", str(unauth), "warning"))
        layout.addWidget(self._build_platform_summary_chip("可配置代理", str(proxy_editable), "accent"))
        layout.addStretch(1)

        return bar

    def _build_platform_table_header(
        self,
        rows: list[dict[str, Any]],
        col_widths: dict[str, int] | None = None,
    ) -> QWidget:
        col_widths = col_widths or self._platform_col_widths(rows)
        header = QWidget()
        header.setObjectName("SettingsPlatformHeader")
        header.setFixedHeight(38)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(self._platform_header_cell("平台", col_widths["name"]))
        header_layout.addWidget(self._platform_header_cell("认证状态", col_widths["auth"]))
        header_layout.addWidget(self._platform_header_cell("爬取数量", col_widths["count"]))
        header_layout.addWidget(self._platform_header_cell("超时", col_widths["timeout"]))
        header_layout.addWidget(self._platform_header_cell("代理入口", col_widths["proxy"]))
        header_layout.addStretch(1)
        return header

    def _build_platform_table_body(self, rows: list[dict[str, Any]], col_widths: dict[str, int]) -> QWidget:
        body = QWidget()
        body.setObjectName("SettingsPlatformTable")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        for row in rows:
            body_layout.addWidget(self._build_platform_row(row, col_widths))

        return body

    @staticmethod
    def _platform_row_height(row: dict[str, Any]) -> int:
        return 48

    def _build_platform_settings(self, layout: QVBoxLayout, value: Any) -> None:
        rows = value if isinstance(value, list) else []
        self._last_platform_inner_width = self._form_inner_width()

        layout.addWidget(self._build_platform_summary_bar(rows), 0, Qt.AlignmentFlag.AlignTop)
        layout.addSpacing(8)

        table = QFrame()
        table.setObjectName("SettingsPlatformTablePanel")
        table.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        table.setFixedWidth(self._form_inner_width())

        table_layout = QVBoxLayout(table)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        body_height = sum(self._platform_row_height(row) for row in rows) or 48
        uses_scroll_area = len(rows) > 6 or body_height > 340
        col_widths = self._platform_col_widths(rows, reserve_vertical_scrollbar=uses_scroll_area)
        table_layout.addWidget(self._build_platform_table_header(rows, col_widths=col_widths))

        header_divider = QFrame()
        header_divider.setObjectName("SettingsCardDivider")
        header_divider.setFixedHeight(1)
        table_layout.addWidget(header_divider)

        table_body = self._build_platform_table_body(rows, col_widths)

        if uses_scroll_area:
            scroll = QScrollArea()
            scroll.setObjectName("SettingsPlatformScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFixedHeight(min(360, body_height))
            scroll.setWidget(table_body)
            table_layout.addWidget(scroll, 0, Qt.AlignmentFlag.AlignTop)
            table.setFixedHeight(38 + 1 + scroll.height())
        else:
            table_layout.addWidget(table_body, 0, Qt.AlignmentFlag.AlignTop)
            table.setFixedHeight(38 + 1 + body_height)

        layout.addWidget(table, 0, Qt.AlignmentFlag.AlignTop)

    def _build_platform_row(self, row: dict[str, Any], col_widths: dict[str, int] | None = None) -> QWidget:
        platform_id = str(row.get("id") or "")
        raw_platform_name = str(row.get("name") or row.get("id") or "平台")
        platform_name = platform_display_name(platform_id, self._language(), fallback=raw_platform_name)
        policy = platform_proxy_policy(platform_id, raw_platform_name)
        col_widths = col_widths or self._platform_col_widths([row])

        line = QWidget()
        line.setObjectName("SettingsPlatformRow")
        line.setFixedHeight(self._platform_row_height(row))
        line_layout = QHBoxLayout(line)
        line_layout.setContentsMargins(14, 4, 14, 4)
        line_layout.setSpacing(10)

        name_cell = QWidget()
        name_cell.setFixedWidth(col_widths["name"])
        name_layout = QHBoxLayout(name_cell)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(7)
        name_layout.addWidget(self._platform_icon_label(platform_id, platform_name))
        name_label = QLabel(self._elided_platform_name(platform_name, col_widths["name"] - 34))
        name_label.setObjectName("SettingsPlatformName")
        name_label.setToolTip(platform_name)
        name_layout.addWidget(name_label, 1)
        line_layout.addWidget(name_cell, 0)

        auth_badge = self._auth_badge(str(row.get("auth_status") or "未认证"), fixed_width=col_widths["auth"])
        line_layout.addWidget(auth_badge, 0)

        line_layout.addWidget(self._platform_count_combo(row, width=col_widths["count"]), 0)
        line_layout.addWidget(self._platform_timeout_combo(row, width=col_widths["timeout"]), 0)
        line_layout.addWidget(self._platform_proxy_widget(row, policy, row_container=line, width=col_widths["proxy"]), 0)
        line_layout.addStretch(1)

        return line

    def _build_playback_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})
        player_combo = self._build_combo(
            self._dict_value(options, "default_player", []),
            self._dict_value(value, "default_player", "builtin_player"),
            width=FORM_CONTROL_WIDTH,
        )
        player_combo.currentIndexChanged.connect(
            lambda *_args, combo=player_combo: self._emit_setting_changed(
                "playback",
                "default_player",
                current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("手动播放方式", player_combo))

        remember_switch = self._build_switch(self._dict_value(value, "remember_position", True))
        remember_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "remember_position", bool(checked))
        )
        layout.addWidget(self._build_setting_row("记住播放进度", remember_switch))

        autoplay_switch = self._build_switch(self._dict_value(value, "autoplay_next", True))
        autoplay_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "autoplay_next", bool(checked))
        )
        layout.addWidget(self._build_setting_row("视频播放完自动下一项", autoplay_switch))

        image_controls = QWidget()
        image_controls.setObjectName("ImageAutoAdvanceControls")
        image_controls.setProperty("settingsControlHeight", 38)
        image_layout = QHBoxLayout(image_controls)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(10)

        interval_combo = self._build_combo(
            self._dict_value(options, "image_auto_advance_interval_seconds", []),
            self._dict_value(value, "image_auto_advance_interval_seconds", 5),
            width=self._scaled_px(126, minimum=112),
        )
        interval_combo.setObjectName("ImageAutoAdvanceIntervalCombo")
        interval_combo.setToolTip(self._t("\u56fe\u7247\u81ea\u52a8\u8f6e\u64ad\u7684\u5207\u6362\u95f4\u9694"))
        interval_combo.currentIndexChanged.connect(
            lambda *_args, combo=interval_combo: self._emit_setting_changed(
                "playback",
                "image_auto_advance_interval_seconds",
                current_combo_int_value(combo, 5),
            )
        )

        image_switch = self._build_switch(self._dict_value(value, "manual_image_switch", True))
        image_switch.setObjectName("ImageManualSwitch")

        def sync_interval_visibility(checked: bool) -> None:
            show_interval = not bool(checked)
            interval_combo.setVisible(show_interval)
            interval_combo.setEnabled(show_interval)
            image_controls.setProperty("autoAdvanceEnabled", "true" if show_interval else "false")
            image_controls.style().unpolish(image_controls)
            image_controls.style().polish(image_controls)
            image_controls.updateGeometry()

        image_switch.toggled.connect(sync_interval_visibility)
        image_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("playback", "manual_image_switch", bool(checked))
        )
        image_layout.addStretch(1)
        image_layout.addWidget(interval_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        image_layout.addWidget(image_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        sync_interval_visibility(image_switch.isChecked())
        layout.addWidget(self._build_setting_row("\u56fe\u7247\u53ea\u624b\u52a8\u5207\u6362", image_controls))

    def _build_log_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        retention = self._build_combo(
            self._dict_value(options, "retention_days", RETENTION_OPTIONS),
            self._dict_value(value, "retention_days", 1),
            width=FORM_CONTROL_WIDTH,
        )
        retention.currentIndexChanged.connect(
            lambda *_args, combo=retention: self._emit_setting_changed(
                "logging",
                "retention_days",
                current_combo_int_value(combo, 1),
            )
        )
        layout.addWidget(self._build_setting_row("日志保留天数", retention))

        failed_record_retention = self._build_combo(
            self._dict_value(options, "failed_record_retention_days", []),
            self._dict_value(value, "failed_record_retention_days", 7),
            width=FORM_CONTROL_WIDTH,
        )
        failed_record_retention.currentIndexChanged.connect(
            lambda *_args, combo=failed_record_retention: self._emit_setting_changed(
                "logging",
                "failed_record_retention_days",
                current_combo_int_value(combo, 7),
            )
        )
        layout.addWidget(self._build_setting_row("失败记录保留天数", failed_record_retention))

        display_count = self._build_combo(
            self._dict_value(options, "ui_log_max_display_count", UI_LOG_MAX_DISPLAY_OPTIONS),
            self._dict_value(value, "ui_log_max_display_count", 300),
            width=FORM_CONTROL_WIDTH,
        )
        display_count.currentIndexChanged.connect(
            lambda *_args, combo=display_count: self._emit_setting_changed(
                "logging",
                "ui_log_max_display_count",
                current_combo_int_value(combo, 300),
            )
        )
        layout.addWidget(self._build_setting_row("UI日志最大显示数量", display_count))

        trace_switch = self._build_switch(self._dict_value(value, "auto_copy_trace_on_error", True))
        trace_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("logging", "auto_copy_trace_on_error", bool(checked))
        )
        layout.addWidget(self._build_setting_row("错误时自动复制 Trace", trace_switch))

    def _build_appearance_settings(self, layout: QVBoxLayout, value: Any) -> None:
        options = self._dict_value(value, "_options", {})

        language_combo = self._build_combo(
            self._dict_value(options, "language", []),
            self._dict_value(value, "language", "zh-CN"),
            width=FORM_CONTROL_WIDTH,
        )
        language_combo.currentIndexChanged.connect(
            lambda *_args, combo=language_combo: self._emit_setting_changed(
                "appearance",
                "language",
                current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("语言", language_combo))

        follow_switch = self._build_switch(self._dict_value(value, "follow_system", False))
        follow_switch.setProperty("settingsRole", "follow_system")
        follow_switch.toggled.connect(
            lambda checked: self._emit_setting_changed("appearance", "follow_system", bool(checked))
        )
        layout.addWidget(self._build_setting_row("跟随系统", follow_switch))

        theme_segment = SegmentedControl([("light", self._t("浅色")), ("dark", self._t("深色"))], parent=self)
        theme_segment.setProperty("settingsRole", "theme")
        theme_segment.set_theme_colors(self._colors())
        theme_value = str(self._dict_value(value, "theme", "light")).lower()
        theme_segment.set_value("dark" if theme_value == "dark" else "light")
        theme_segment.setFixedWidth(260)
        theme_segment.selection_changed.connect(self._emit_theme_setting_changed)
        self._segmented_controls.append(theme_segment)
        layout.addWidget(self._build_setting_row("浅色 / 深色", theme_segment, control_width=260))

        accent_combo = self._build_combo(
            self._dict_value(options, "accent", []),
            self._dict_value(value, "accent", "blue"),
            width=FORM_CONTROL_WIDTH,
        )
        accent_combo.currentIndexChanged.connect(
            lambda *_args, combo=accent_combo: self._emit_setting_changed(
                "appearance",
                "accent",
                current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("主题色", accent_combo))

        scale_combo = self._build_combo(
            self._dict_value(options, "scale", []),
            self._dict_value(value, "scale", "100%"),
            width=FORM_CONTROL_WIDTH,
        )
        scale_combo.currentIndexChanged.connect(
            lambda *_args, combo=scale_combo: self._emit_setting_changed(
                "appearance",
                "scale",
                current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("界面缩放", scale_combo))

        font_combo = self._build_combo(
            self._dict_value(options, "font_size", []),
            self._dict_value(value, "font_size", "medium"),
            width=FORM_CONTROL_WIDTH,
        )
        font_combo.currentIndexChanged.connect(
            lambda *_args, combo=font_combo: self._emit_setting_changed(
                "appearance",
                "font_size",
                current_combo_value(combo),
            )
        )
        layout.addWidget(self._build_setting_row("字体大小", font_combo))

    def show_action_feedback(self, message: str, *, ok: bool = True) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.action_feedback.setText(text)
        self.action_feedback.setProperty("status", "ok" if ok else "error")
        self.action_feedback.setVisible(True)
        self.action_feedback.style().unpolish(self.action_feedback)
        self.action_feedback.style().polish(self.action_feedback)
        QTimer.singleShot(
            6000,
            guarded_qt_callback(
                self.action_feedback,
                lambda label: label.setVisible(False),
            ),
        )

    def _apply_settings_page_style(self) -> None:
        if getattr(self, "_applying_style", False):
            return

        c = self._colors()
        page_title_px = self._scaled_px(22, minimum=20)
        detail_title_px = self._scaled_px(19, minimum=17)
        card_title_px = self._scaled_px(16, minimum=15)
        body_px = self._scaled_px(13, minimum=12)
        small_px = self._scaled_px(12, minimum=11)
        combo_px = self._scaled_px(13, minimum=12)

        qss = generate_settings_page_stylesheet(
            c,
            page_title_px=page_title_px,
            detail_title_px=detail_title_px,
            card_title_px=card_title_px,
            body_px=body_px,
            small_px=small_px,
            combo_px=combo_px,
            inline_button_px=self._scaled_px(14, minimum=12),
        )

        if qss == getattr(self, "_last_settings_stylesheet", ""):
            return

        self._applying_style = True
        try:
            self._last_settings_stylesheet = qss
            self.setStyleSheet(qss)
        finally:
            self._applying_style = False
