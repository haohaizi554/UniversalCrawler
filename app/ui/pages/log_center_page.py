from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect, QEvent
from PyQt6.QtGui import QIcon, QTextOption
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.combo_popup import (
    ThemedComboBox,
    fit_combo_width_to_contents,
    polish_combo_popup,
    refresh_themed_combo_boxes,
)
from app.ui.components.focus_state import bind_focus_property
from app.ui.components.log_center_controls import build_log_action_bar, build_log_table_footer
from app.ui.components.log_filter_input import LogFilterLineEdit, sync_log_filter_input_styles
from app.ui.components.log_inspector_sections import (
    LogInspectorRefs,
    build_log_detail_summary_section,
    build_log_inspector_header,
    build_log_json_section,
    build_log_kv_row,
    build_log_stack_section,
)
from shared.localization import normalize_language, tr
from shared.log_contract import LOG_CATEGORY_LABELS
from app.ui.pages.common import PageFrame, SnapshotActionDelegate, SnapshotActionTable
from app.ui.styles.themes import resolve_is_dark_theme, theme_colors
from shared.log_pipeline_rules import (
    is_crawl_pipeline_log,
    is_download_boundary_log,
    is_download_component_source,
    is_platform_root_crawl_log,
)
from shared.log_platforms import PlatformUiMeta
from app.ui.viewmodels.log_platforms import load_builtin_platform_metas, load_platform_options
from app.ui.viewmodels.log_query_worker import (
    LogQueryRequest,
    LogQueryResult,
    LogQueryWorker,
    stable_log_item_id,
)
from app.ui.viewmodels.log_detail_worker import (
    LogDetailExportRequest,
    LogDetailExportResult,
    LogDetailExportWorker,
    LogDetailRequest,
    LogDetailResult,
    LogDetailWorker,
)
from app.ui.viewmodels.pagination_state import parse_page_size
from app.utils.safe_slot import safe_slot


LOG_CATEGORIES = LOG_CATEGORY_LABELS
LOG_TAB_HEIGHT = 34
LOG_TAB_MIN_WIDTH = 92
LOG_TAB_TEXT_PADDING = 34
LOG_TAB_ROW_HEIGHT = 48
LOG_ACTION_BUTTON_TEXT_PADDING = 28
LOG_INSPECTOR_BUTTON_TEXT_PADDING = 24
LOG_DETAIL_KEY_TEXT_PADDING = 10
LOG_TIME_COLUMN_MIN_WIDTH = 144
LOG_TIME_COLUMN_SAMPLE = "0000-00-00 00:00:00"

class LogCenterTableDelegate(SnapshotActionDelegate):
    """日志中心表格 delegate：source_display 支持按行居中对齐。"""

    def _content_rect(self, rect: QRect) -> QRect:
        left, right = self._cell_padding
        return rect.adjusted(left, 0, -right, 0)

    def _paint_icon_text(self, painter, option, index) -> None:
        if self._column_key(index) != "source_display":
            super()._paint_icon_text(painter, option, index)
            return
        model = index.model()
        row = model.row_at(index.row()) if hasattr(model, "row_at") else None
        center_content = str((row or {}).get("source_display_align") or "").lower() == "center"

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.save()
        rect = self._content_rect(option.rect)
        icon_size = 16
        gap = 6
        has_icon = isinstance(icon, QIcon) and not icon.isNull()
        available_text_width = max(0, rect.width() - (icon_size + gap if has_icon else 0))
        display_text = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, available_text_width)
        text_width = min(available_text_width, option.fontMetrics.horizontalAdvance(display_text))
        content_width = (icon_size + gap if has_icon else 0) + text_width
        x = rect.x() + max(0, (rect.width() - content_width) // 2) if center_content else rect.x()
        if isinstance(icon, QIcon) and not icon.isNull():
            icon_rect = QRect(x, rect.y() + max(0, (rect.height() - icon_size) // 2), icon_size, icon_size)
            icon.paint(painter, icon_rect)
            text_rect = QRect(
                icon_rect.right() + gap,
                rect.y(),
                max(text_width + 2, available_text_width if not center_content else text_width + 2),
                rect.height(),
            )
        else:
            text_rect = QRect(
                x,
                rect.y(),
                max(text_width + 2, rect.width() if not center_content else text_width + 2),
                rect.height(),
            )
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), display_text)
        painter.restore()


class LogCenterPage(PageFrame):
    log_action_requested = pyqtSignal(str)
    _log_query_finished = pyqtSignal(object)
    _log_detail_finished = pyqtSignal(object)
    _log_detail_export_finished = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        self.setObjectName("LogCenterPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._all_items: Sequence[Any] = ()
        self.items: list[dict[str, Any]] = []
        self._category = "all"
        self._tab_buttons: dict[str, QPushButton] = {}
        self._log_action_buttons: dict[str, QPushButton] = {}
        self._platform_options: list[PlatformUiMeta] = []
        self._platform_meta_by_id: dict[str, PlatformUiMeta] = load_builtin_platform_metas()
        self._platform_option_ids: tuple[str, ...] = ()
        self._page_size = 20
        self._current_page = 1
        self._log_items_signature: tuple[Any, ...] | None = None
        self._filter_signature: tuple[Any, ...] | None = None
        self._category_count_signature: tuple[Any, ...] | None = None
        self._category_counts: dict[str, int] = {key: 0 for key in LOG_CATEGORIES}
        self._query_sequence = 0
        self._query_total_count = 0
        self._query_matched_count = 0
        self._query_total_pages = 1
        self._query_first_trace_id = ""
        self._query_page_items: list[dict[str, Any]] = []
        self._last_json_text = "{}"
        self._inspector_item_id = ""
        self._detail_sequence = 0
        self._detail_export_sequence = 0
        self._current_detail_result: LogDetailResult | None = None
        self._language = "zh-CN"
        self._filter_query_timer = QTimer(self)
        self._filter_query_timer.setSingleShot(True)
        self._filter_query_timer.setInterval(120)
        self._filter_query_timer.timeout.connect(lambda: self._submit_log_query(reset_page=True))
        self._log_query_finished.connect(self._on_log_query_result)
        self._log_query_worker = LogQueryWorker(lambda result: self._log_query_finished.emit(result))
        self._log_detail_finished.connect(self._on_log_detail_result)
        self._log_detail_worker = LogDetailWorker(lambda result: self._log_detail_finished.emit(result))
        self._log_detail_export_finished.connect(self._on_log_detail_export_result)
        self._log_detail_export_worker = LogDetailExportWorker(
            lambda result: self._log_detail_export_finished.emit(result)
        )
        self.destroyed.connect(lambda *_args: self._log_query_worker.shutdown())
        self.destroyed.connect(lambda *_args: self._log_detail_worker.shutdown())
        self.destroyed.connect(lambda *_args: self._log_detail_export_worker.shutdown())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("LogCenterSplitter")
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([860, 420])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)

        self._sync_inspector_action_buttons(False)
        self._sync_inspector_static_labels()
        self._refresh_platform_filter()
        self._sync_table_presentation()

    def set_cache_service(self, cache_service: object | None) -> None:
        set_cache_service = getattr(self._log_detail_worker, "set_cache_service", None)
        if callable(set_cache_service):
            set_cache_service(cache_service)

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self._sync_filter_labels()
        self._sync_filter_combo_labels()
        self._sync_platform_combo_labels()
        self._sync_log_page_size_combo_labels()
        self._sync_action_bar_labels()
        self._sync_inspector_static_labels()
        self._sync_empty_state_text()
        if hasattr(self, "table") and hasattr(self.table, "table_model"):
            self.table.table_model.set_language(normalized)
        self._sync_tab_buttons()
        self._sync_table_presentation()
        if self._all_items or self._query_page_items:
            self._submit_log_query(reset_page=False, selected_id=self.selected_id() or "")
        else:
            self._render_detail()

    def _t(self, text: object) -> str:
        return tr(str(text or ""), self._language)

    def _resolve_theme_is_dark(self) -> bool:
        window = self.window()
        if window is not None and hasattr(window, "is_dark_theme"):
            return bool(window.is_dark_theme)
        return resolve_is_dark_theme(self)

    def _tab_button_style(self, active: bool) -> str:
        c = theme_colors(self._resolve_theme_is_dark())

        if active:
            return """
            QPushButton#LogTabButton {{
                min-height: 34px;
                max-height: 34px;
                min-width: 92px;
                border: 1px solid {accent};
                border-bottom: 3px solid {accent};
                border-radius: 8px;
                background-color: {accent_soft};
                color: {accent};
                font-size: 14px;
                font-weight: 800;
                padding: 0px 12px;
                margin: 0px 3px 4px 0px;
            }}
            QPushButton#LogTabButton:hover {{
                background-color: {accent_soft};
                color: {accent};
                border: 1px solid {accent};
                border-bottom: 3px solid {accent};
            }}
            """.format(**c)

        return """
        QPushButton#LogTabButton {{
            min-height: 34px;
            max-height: 34px;
            min-width: 92px;
            border: 1px solid {border};
            border-bottom: 3px solid transparent;
            border-radius: 8px;
            background-color: {panel};
            color: {muted};
            font-size: 14px;
            font-weight: 500;
            padding: 0px 12px;
            margin: 0px 3px 4px 0px;
        }}
        QPushButton#LogTabButton:hover {{
            background-color: {panel_soft};
            color: {text};
            border: 1px solid {border_strong};
            border-bottom: 3px solid {border_strong};
        }}
        """.format(**c)

    def _sync_filter_text_input_style(self) -> None:
        if not hasattr(self, "trace_filter") or not hasattr(self, "keyword_filter"):
            return
        sync_log_filter_input_styles(
            (self.trace_filter, self.keyword_filter),
            is_dark=self._resolve_theme_is_dark(),
        )

    def _apply_tab_button_style(self, button: QPushButton, active: bool) -> None:
        button.setStyleSheet(self._tab_button_style(active))
        button.setChecked(active)
        button.setProperty("active", "true" if active else "false")
        button.setProperty("selected", "true" if active else "false")
        button.setAccessibleName("selected" if active else "")

        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)

        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            QTimer.singleShot(0, self._refresh_log_center_visual_state)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched in (
            getattr(self, "trace_filter", None),
            getattr(self, "keyword_filter", None),
        ) and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            if isinstance(watched, LogFilterLineEdit):
                watched.setProperty("focused", "true" if event.type() == QEvent.Type.FocusIn else "false")
            self._sync_filter_text_input_style()
            QTimer.singleShot(0, self._sync_filter_text_input_style)
        return super().eventFilter(watched, event)

    def _refresh_theme_widgets(self) -> None:
        self._refresh_log_center_visual_state()

    def _apply_message_box_style(self) -> None:
        c = theme_colors(self._resolve_theme_is_dark())
        is_dark = self._resolve_theme_is_dark()

        message_bg = "#29313C" if is_dark else "#F3F6FA"
        message_border = "#4B5563" if is_dark else "#D8E0EA"

        if hasattr(self, "detail_message_frame"):
            self.detail_message_frame.setStyleSheet(
                f"""
                QFrame#LogMessageBoxFrame {{
                    background-color: {message_bg};
                    border: 1px solid {message_border};
                    border-radius: 9px;
                }}
                """
            )

        if hasattr(self, "detail_message_value"):
            self.detail_message_value.setStyleSheet(
                f"""
                QPlainTextEdit#LogMessageText {{
                    color: {c["text"]};
                    background: transparent;
                    border: none;
                    padding: 0px;
                    font-size: 13px;
                    font-weight: 400;
                    selection-background-color: {c["row_selected"]};
                    selection-color: {c["text"]};
                }}

                QPlainTextEdit#LogMessageText QScrollBar:vertical {{
                    width: 8px;
                    background: transparent;
                    margin: 2px;
                }}

                QPlainTextEdit#LogMessageText QScrollBar::handle:vertical {{
                    background: {c["scrollbar_handle"]};
                    border-radius: 4px;
                    min-height: 24px;
                }}

                QPlainTextEdit#LogMessageText QScrollBar::add-line:vertical,
                QPlainTextEdit#LogMessageText QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                """
            )

            self.detail_message_value.viewport().setAutoFillBackground(False)
            self.detail_message_value.viewport().update()

    def _configure_message_editor_wrap(self) -> None:
        """Force message editor to wrap long words, URLs, paths and trace ids."""
        if not hasattr(self, "detail_message_value"):
            return

        editor = self.detail_message_value

        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        option = editor.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        editor.document().setDefaultTextOption(option)

        editor.setMinimumWidth(0)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if editor.viewport() is not None:
            editor.viewport().setMinimumWidth(0)
            editor.viewport().update()

    def _sync_message_document_width(self) -> None:
        if not hasattr(self, "detail_message_value"):
            return

        editor = self.detail_message_value
        viewport = editor.viewport()
        if viewport is None:
            return

        width = max(40, viewport.width() - 4)
        editor.document().setTextWidth(width)
        viewport.update()

    @safe_slot
    def _refresh_log_center_visual_state(self) -> None:
        refresh_themed_combo_boxes(self)
        self._sync_tab_buttons()
        self._sync_filter_text_input_style()

        if hasattr(self, "detail_message_value"):
            self._apply_message_box_style()
            self._configure_message_editor_wrap()
            self._sync_message_document_width()
            QTimer.singleShot(0, self._resize_detail_message_box)

        if hasattr(self, "table"):
            self.table.viewport().update()
            self.table.horizontalHeader().viewport().update()

        if hasattr(self, "json_text"):
            current_result = self._current_detail_result_for_selection()
            if current_result is not None:
                self.json_text.setHtml(self._format_json_text_html(current_result.detail_json_escaped, escaped=True))
            else:
                self.json_text.setHtml(self._format_json_text_html(self._last_json_text or "{}"))
            self.json_text.viewport().update()

        if self._current_log_item():
            self._render_detail()

    @staticmethod
    def _style_panel(frame: QFrame) -> QFrame:
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return frame

    def _build_left_panel(self) -> QFrame:
        panel = self._style_panel(QFrame())
        panel.setObjectName("LogListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._build_log_tabs())
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_action_bar())
        layout.addWidget(self._build_log_table_area(), 1)
        return panel

    def _build_log_tabs(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("LogTabs")
        scroll.setFixedHeight(LOG_TAB_ROW_HEIGHT)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)

        row = QWidget()
        row.setObjectName("LogTabsContent")
        row.setFixedHeight(44)
        row.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for category, label in LOG_CATEGORIES.items():
            button = QPushButton(label)
            button.setObjectName("LogTabButton")
            button.setProperty("i18nSkipText", "true")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFlat(True)
            button.setFixedHeight(LOG_TAB_HEIGHT)
            button.setMinimumWidth(LOG_TAB_MIN_WIDTH)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=category: self._set_category(key))
            layout.addWidget(button)
            self._tab_buttons[category] = button

        layout.addStretch(1)
        scroll.setWidget(row)
        self._tab_content = row
        self._sync_tab_buttons()
        return scroll

    def _build_filter_bar(self) -> QFrame:
        bar = self._style_panel(QFrame())
        bar.setObjectName("LogFilterBar")
        layout = QGridLayout(bar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        self.level_filter = ThemedComboBox(row_height=34)
        self.level_filter.setObjectName("LogFilterControl")
        for label in ["全部", "INFO", "SUCCESS", "WARN", "ERROR", "CMD"]:
            self.level_filter.addItem(label, label)
        self.time_filter = ThemedComboBox(row_height=34)
        self.time_filter.setObjectName("LogFilterControl")
        for label in ["近 30 分钟", "近 1 小时", "近 24 小时", "全部"]:
            self.time_filter.addItem(label, label)
        self.platform_filter = ThemedComboBox(row_height=34)
        self.platform_filter.setObjectName("LogFilterControl")
        self.trace_filter = LogFilterLineEdit(self._sync_filter_text_input_style)
        self.trace_filter.setPlaceholderText("请输入 Trace ID")
        self.keyword_filter = LogFilterLineEdit(self._sync_filter_text_input_style)
        self.keyword_filter.setPlaceholderText("请输入关键词")
        bind_focus_property(self.trace_filter)
        bind_focus_property(self.keyword_filter)
        self.trace_filter.installEventFilter(self)
        self.keyword_filter.installEventFilter(self)
        self._sync_filter_text_input_style()

        self._filter_label_widgets: dict[str, QLabel] = {}
        filters = [
            ("日志级别", self.level_filter),
            ("时间范围", self.time_filter),
            ("平台", self.platform_filter),
            ("Trace ID", self.trace_filter),
            ("关键词搜索", self.keyword_filter),
        ]
        for index, (label, widget) in enumerate(filters):
            label_widget = QLabel(label)
            label_widget.setObjectName("LogFilterLabel")
            self._filter_label_widgets[label] = label_widget
            widget.setFixedHeight(32)
            layout.addWidget(label_widget, 0, index)
            layout.addWidget(widget, 1, index)
            layout.setColumnStretch(index, 1)

        self.level_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.time_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.platform_filter.currentIndexChanged.connect(lambda *_args: self._apply_filters())
        self.trace_filter.textChanged.connect(lambda *_args: self._on_filter_text_changed())
        self.keyword_filter.textChanged.connect(lambda *_args: self._on_filter_text_changed())
        for combo in (self.level_filter, self.time_filter, self.platform_filter):
            polish_combo_popup(combo, visible_rows=max(1, combo.count()), row_height=34)
        return bar

    def _sync_filter_labels(self) -> None:
        for source_text, label in getattr(self, "_filter_label_widgets", {}).items():
            label.setText(self._t(source_text))
        if hasattr(self, "trace_filter"):
            self.trace_filter.setPlaceholderText(self._t("请输入 Trace ID"))
        if hasattr(self, "keyword_filter"):
            self.keyword_filter.setPlaceholderText(self._t("请输入关键词"))

    def _sync_filter_combo_labels(self) -> None:
        for combo in (getattr(self, "level_filter", None), getattr(self, "time_filter", None)):
            if combo is None:
                continue
            blocked = combo.blockSignals(True)
            try:
                for index in range(combo.count()):
                    source_text = str(combo.itemData(index) or combo.itemText(index))
                    combo.setItemText(index, self._t(source_text))
            finally:
                combo.blockSignals(blocked)
            polish_combo_popup(combo, visible_rows=max(1, combo.count()), row_height=34)

    def _log_page_size_label(self, value: int) -> str:
        if self._language == "en-US":
            return f"{value} / page"
        if self._language == "zh-TW":
            return f"{value} 條/頁"
        return f"{value} 条/页"

    def _sync_log_page_size_combo_labels(self) -> None:
        combo = getattr(self, "page_size_combo", None)
        if combo is None:
            return
        blocked = combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                value = int(combo.itemData(index) or 0)
                if value > 0:
                    combo.setItemText(index, self._log_page_size_label(value))
                else:
                    combo.setItemText(index, self._t("全部"))
        finally:
            combo.blockSignals(blocked)
        self._fit_page_size_combo_width()
        if hasattr(self, "prev_page_button"):
            self.prev_page_button.setText(self._t("上一页"))
        if hasattr(self, "next_page_button"):
            self.next_page_button.setText(self._t("下一页"))

    def _on_filter_text_changed(self) -> None:
        self._sync_filter_text_input_style()
        self._filter_query_timer.start()

    def _build_action_bar(self) -> QWidget:
        row, refs = build_log_action_bar(
            emit_action=self.log_action_requested.emit,
            copy_trace_id=self._copy_current_trace_id,
        )
        self.copy_trace_button = refs.copy_trace_button
        self._log_action_buttons = dict(refs.action_buttons)
        self._sync_action_bar_labels()
        return row

    @staticmethod
    def _source_text(widget: QWidget, fallback: str = "") -> str:
        source = widget.property("_i18n_source_text")
        if source is None:
            source = fallback or getattr(widget, "text", lambda: "")()
            widget.setProperty("_i18n_source_text", source)
        return str(source or "")

    def _fit_fixed_button_width(self, button: QPushButton, *, min_width: int, padding: int) -> None:
        width = max(min_width, button.fontMetrics().horizontalAdvance(button.text()) + padding)
        button.setFixedWidth(width)
        button.setMinimumWidth(width)
        button.setMaximumWidth(width)
        button.updateGeometry()

    def _sync_source_button_label(self, button: QPushButton | None, *, min_width: int, padding: int) -> None:
        if button is None:
            return
        source_text = self._source_text(button)
        button.setText(self._t(source_text))
        tooltip_source = button.property("_i18n_source_tooltip")
        if tooltip_source:
            button.setToolTip(self._t(tooltip_source))
        self._fit_fixed_button_width(button, min_width=min_width, padding=padding)

    def _sync_action_bar_labels(self) -> None:
        for button in getattr(self, "_log_action_buttons", {}).values():
            minimum = int(button.property("logActionMinWidth") or button.minimumWidth() or 0)
            self._sync_source_button_label(
                button,
                min_width=minimum,
                padding=LOG_ACTION_BUTTON_TEXT_PADDING,
            )

    def _sync_inspector_static_labels(self) -> None:
        detail_key_labels: list[QLabel] = []
        for label in self.findChildren(QLabel):
            source = label.property("_i18n_source_text")
            if source is None:
                continue
            label.setText(self._t(source))
            if label.objectName() == "LogDetailKey":
                detail_key_labels.append(label)

        if detail_key_labels:
            key_width = max(
                56,
                max(label.fontMetrics().horizontalAdvance(label.text()) for label in detail_key_labels)
                + LOG_DETAIL_KEY_TEXT_PADDING,
            )
            for label in detail_key_labels:
                label.setFixedWidth(key_width)
                label.updateGeometry()

        for button_name in ("detail_copy_button", "detail_export_button", "json_copy_button"):
            self._sync_source_button_label(
                getattr(self, button_name, None),
                min_width=52,
                padding=LOG_INSPECTOR_BUTTON_TEXT_PADDING,
            )

    def _build_log_table_area(self) -> QFrame:
        container = self._style_panel(QFrame())
        container.setObjectName("LogTableContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table_stack = QStackedWidget()
        self.table_stack.setObjectName("LogTableStack")

        self.table = SnapshotActionTable(
            headers=["时间", "级别", "来源", "Trace ID", "消息摘要"],
            columns=["time", "level_display", "source_display", "trace_id", "message_summary"],
            icon_columns={"source_display"},
            row_height=32,
            cell_padding=(4, 4),
            suppress_native_selection=True,
        )
        self.table.setObjectName("LogItemsTable")
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self._configure_table_columns()
        self._install_log_table_delegate()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.selectionModel().currentChanged.connect(lambda *_args: self._render_detail())

        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self._build_empty_state())
        layout.addWidget(self.table_stack, 1)
        layout.addWidget(self._build_table_footer())
        return container

    def _build_table_footer(self) -> QWidget:
        row, refs = build_log_table_footer(
            page_size_changed=self._on_page_size_changed,
            go_prev_page=self._go_prev_page,
            go_next_page=self._go_next_page,
        )
        self.footer_stats = refs.footer_stats
        self.page_indicator = refs.page_indicator
        self.page_size_combo = refs.page_size_combo
        self.prev_page_button = refs.prev_page_button
        self.next_page_button = refs.next_page_button
        return row

    def _fit_page_size_combo_width(self) -> None:
        fit_combo_width_to_contents(
            self.page_size_combo,
            min_width=88,
            max_width=168,
            horizontal_padding=16,
        )

    def _build_right_panel(self) -> QFrame:
        panel = self._style_panel(QFrame())
        panel.setObjectName("LogInspectorPanel")
        panel.setMinimumWidth(400)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_inspector_header())

        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setObjectName("LogInspectorScroll")
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("LogInspectorBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)
        body_layout.addWidget(self._build_detail_summary_section(), 0)
        body_layout.addWidget(self._build_json_section(), 0)
        body_layout.addWidget(self._build_stack_section(), 0)
        body_layout.addStretch(1)

        self.inspector_scroll.setWidget(body)
        layout.addWidget(self.inspector_scroll, 1)
        return panel

    def _assign_inspector_refs(self, refs: LogInspectorRefs) -> None:
        for name, value in refs.__dict__.items():
            if value is not None:
                setattr(self, name, value)

    def _build_inspector_header(self) -> QWidget:
        header, refs = build_log_inspector_header(
            copy_detail=self._copy_current_log_detail,
            export_detail=self._export_current_log_detail,
        )
        self._assign_inspector_refs(refs)
        return header

    def _build_kv_row(self, key: str, value_widget: QWidget) -> QWidget:
        return build_log_kv_row(key, value_widget)

    def _build_detail_summary_section(self) -> QFrame:
        section, refs = build_log_detail_summary_section(self._style_panel)
        self._assign_inspector_refs(refs)
        self._configure_message_editor_wrap()
        self._apply_message_box_style()
        return section

    def _build_json_section(self) -> QFrame:
        section, refs = build_log_json_section(
            style_panel=self._style_panel,
            copy_json=self._copy_current_log_json,
        )
        self._assign_inspector_refs(refs)
        return section

    def _build_stack_section(self) -> QFrame:
        section, refs = build_log_stack_section(self._style_panel)
        self._assign_inspector_refs(refs)
        return section

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("LogEmptyState")
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(24, 48, 24, 48)
        layout.setSpacing(8)
        title = QLabel("暂无匹配日志")
        title.setObjectName("LogEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self._empty_state_title = title
        self._empty_state_subtitles: list[QLabel] = []
        for line in ("调整筛选条件", "或点击「刷新缓冲」重新加载日志"):
            subtitle = QLabel(line)
            subtitle.setObjectName("LogEmptySubtitle")
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle.setWordWrap(False)
            layout.addWidget(subtitle)
            self._empty_state_subtitles.append(subtitle)
        self._sync_empty_state_text()
        return panel

    def _sync_empty_state_text(self) -> None:
        if hasattr(self, "_empty_state_title"):
            self._empty_state_title.setText(self._t("暂无匹配日志"))
        subtitles = getattr(self, "_empty_state_subtitles", [])
        source_lines = ("调整筛选条件", "或点击「刷新缓冲」重新加载日志")
        for label, source_text in zip(subtitles, source_lines, strict=False):
            label.setText(self._t(source_text))

    def _configure_table_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setFixedHeight(32)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        time_width = max(
            LOG_TIME_COLUMN_MIN_WIDTH,
            self.table.fontMetrics().horizontalAdvance(LOG_TIME_COLUMN_SAMPLE) + 16,
        )
        self.table.setColumnWidth(0, time_width)
        self.table.setColumnWidth(1, 82)
        self.table.setColumnWidth(2, 188)
        self.table.setColumnWidth(3, 140)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _install_log_table_delegate(self) -> None:
        current = self.table.itemDelegate()
        if not isinstance(current, SnapshotActionDelegate):
            return
        self.table.setItemDelegate(
            LogCenterTableDelegate(
                progress_columns=current._progress_columns,
                icon_columns=current._icon_columns,
                title_columns=current._title_columns,
                action_column=current._action_column,
                action_ids=current._action_ids,
                cell_padding=current._cell_padding,
                suppress_native_selection=current._suppress_native_selection,
                parent=self.table,
            )
        )

    def _load_platform_options(self, snapshot: dict | None = None) -> list[PlatformUiMeta]:
        return load_platform_options(snapshot)

    def _platform_combo_label(self, meta: PlatformUiMeta) -> str:
        label = self._t(meta.label)
        if meta.emoji and not meta.icon_path:
            return f"{meta.emoji} {label}"
        return label

    def _add_platform_combo_item(self, meta: PlatformUiMeta) -> None:
        icon = QIcon()
        if meta.icon_path:
            icon = QIcon(meta.icon_path)
        self.platform_filter.addItem(icon, self._platform_combo_label(meta), meta.id)

    def _sync_platform_combo_labels(self) -> None:
        combo = getattr(self, "platform_filter", None)
        if combo is None:
            return
        blocked = combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                platform_id = str(combo.itemData(index) or "")
                meta = self._platform_meta_by_id.get(platform_id)
                if meta is not None:
                    combo.setItemText(index, self._platform_combo_label(meta))
        finally:
            combo.blockSignals(blocked)
        polish_combo_popup(combo, visible_rows=max(1, combo.count()), row_height=34)

    def _refresh_platform_filter(self, snapshot: dict | None = None) -> None:
        if not hasattr(self, "platform_filter"):
            return
        new_options = self._load_platform_options(snapshot)
        new_ids = tuple(meta.id for meta in new_options)
        if new_ids == self._platform_option_ids:
            return

        current_id = self._selected_platform_id() or "all"
        self.platform_filter.blockSignals(True)
        self.platform_filter.clear()
        self._platform_options = new_options
        self._platform_meta_by_id = {meta.id: meta for meta in new_options}
        for meta in new_options:
            self._add_platform_combo_item(meta)

        index = self.platform_filter.findData(current_id)
        if index < 0:
            index = self.platform_filter.findData("all")
        if index < 0:
            index = 0
        self.platform_filter.setCurrentIndex(index)
        self.platform_filter.blockSignals(False)
        self._platform_option_ids = new_ids
        polish_combo_popup(self.platform_filter, visible_rows=max(1, self.platform_filter.count()), row_height=34)

    def _selected_platform_id(self) -> str | None:
        if not hasattr(self, "platform_filter"):
            return None
        platform_id = self.platform_filter.currentData()
        if platform_id is None:
            return None
        normalized = str(platform_id).strip().lower()
        if normalized in {"", "all"}:
            return None
        return normalized

    def _selected_level_filter(self) -> str:
        if not hasattr(self, "level_filter"):
            return "\u5168\u90e8"
        return str(self.level_filter.currentData() or self.level_filter.currentText())

    def _selected_time_filter(self) -> str:
        if not hasattr(self, "time_filter"):
            return "\u5168\u90e8"
        return str(self.time_filter.currentData() or self.time_filter.currentText())

    def _trace_filter_query(self) -> str:
        return self.trace_filter.text().strip().lower() if hasattr(self, "trace_filter") else ""

    def _keyword_filter_query(self) -> str:
        return self.keyword_filter.text().strip().lower() if hasattr(self, "keyword_filter") else ""

    def render(self, snapshot: dict) -> None:
        self._refresh_platform_filter(snapshot)
        incoming_items = self._snapshot_log_items(snapshot)
        incoming_signature = self._make_log_items_signature(incoming_items)
        filter_signature = self._make_filter_signature()
        if incoming_signature == self._log_items_signature and filter_signature == self._filter_signature:
            self._sync_tab_buttons()
            return
        self._all_items = incoming_items
        self._log_items_signature = incoming_signature
        self._category_count_signature = None
        self._submit_log_query(reset_page=False)

    @staticmethod
    def _snapshot_log_items(snapshot: Mapping[str, Any]) -> Sequence[Any]:
        rows = snapshot.get("log_items") or ()
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            return ()
        return rows

    def _make_log_items_signature(self, items: Sequence[Any]) -> tuple[Any, ...]:
        if not items:
            return (0, "", "")
        return (
            len(items),
            self._stable_log_item_signature(items[0], 0),
            self._stable_log_item_signature(items[-1], len(items) - 1),
        )

    @staticmethod
    def _stable_log_item_signature(item: Any, index: int) -> tuple[Any, ...]:
        if not isinstance(item, Mapping):
            return ("", "", "", "", index)
        return (
            item.get("id"),
            item.get("time"),
            item.get("trace_id"),
            item.get("message_summary") or item.get("message"),
            index,
        )

    def _make_filter_signature(self) -> tuple[Any, ...]:
        return (
            self._category,
            self._selected_level_filter(),
            self._selected_time_filter(),
            self._selected_platform_id() or "",
            self._trace_filter_query(),
            self._keyword_filter_query(),
            self._platform_option_ids,
            self._language,
        )

    def _make_category_count_signature(self) -> tuple[Any, ...]:
        signature = self._make_filter_signature()
        return (
            self._log_items_signature,
            signature[1:],
        )

    def _set_category(self, category: str) -> None:
        self._category = category if category in LOG_CATEGORIES else "all"
        self._sync_tab_buttons()
        self._apply_filters()

    def _category_count(self, category: str) -> int:
        return int(self._category_counts.get(category, 0))

    def _update_category_tab_counts(self) -> None:
        for category, button in self._tab_buttons.items():
            label = self._t(LOG_CATEGORIES[category])
            count = self._category_count(category)
            button.setText(f"{label} {count}")

    def _sync_tab_buttons(self) -> None:
        self._update_category_tab_counts()

        for category, button in self._tab_buttons.items():
            active = category == self._category
            self._apply_tab_button_style(button, active)
            self._fit_tab_button_width(button)
        self._sync_tab_content_width()

    def _fit_tab_button_width(self, button: QPushButton) -> None:
        width = max(
            LOG_TAB_MIN_WIDTH,
            button.fontMetrics().horizontalAdvance(button.text()) + LOG_TAB_TEXT_PADDING,
        )
        button.setFixedWidth(width)
        button.setMinimumWidth(width)
        button.setMaximumWidth(width)
        button.setToolTip(button.text())
        button.updateGeometry()

    def _sync_tab_content_width(self) -> None:
        content = getattr(self, "_tab_content", None)
        if content is None:
            return
        layout = content.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        buttons = list(self._tab_buttons.values())
        width = margins.left() + margins.right() + sum(max(button.width(), button.minimumWidth()) for button in buttons)
        if buttons:
            width += max(0, len(buttons) - 1) * layout.spacing()
        content.setMinimumWidth(width)
        content.updateGeometry()

    def _sync_table_presentation(self) -> None:
        self.table_stack.setCurrentIndex(0 if self.items else 1)
        self._update_footer_stats()

    def _total_pages(self) -> int:
        return max(1, int(self._query_total_pages or 1))

    @safe_slot
    def _on_page_size_changed(self) -> None:
        data = self.page_size_combo.currentData() if hasattr(self, "page_size_combo") else None
        text = self.page_size_combo.currentText() if hasattr(self, "page_size_combo") else "20 条/页"
        self._page_size = parse_page_size(data, text, default=20, all_labels={"全部", "All"})
        self._current_page = 1
        self._submit_log_query(reset_page=True)

    @safe_slot
    def _go_prev_page(self) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self._submit_log_query(reset_page=False, selected_id="")

    @safe_slot
    def _go_next_page(self) -> None:
        if self._current_page < self._total_pages():
            self._current_page += 1
            self._submit_log_query(reset_page=False, selected_id="")

    def _refresh_paged_table(self, *, selected_id: str = "") -> None:
        self.items = list(self._query_page_items)

        self.table.set_rows(self.items)
        self._configure_table_columns()
        self._apply_platform_icons_to_table()
        self._sync_table_presentation()

        if selected_id and self.select_id(selected_id):
            self._render_detail()
            return
        if self.items:
            self.table.selectRow(0)
        self._render_detail()

    def _update_footer_stats(self) -> None:
        if not hasattr(self, "footer_stats"):
            return
        total_pages = self._total_pages()
        total = self._query_total_count
        matched = self._query_matched_count
        visible = len(self.items)
        if self._language == "en-US":
            stats_text = f"Total {total} / matched {matched} / showing {visible}"
            page_text = f"Page {self._current_page} / {total_pages}"
        elif self._language == "zh-TW":
            stats_text = f"共 {total} 條 / 符合 {matched} 條 / 目前顯示 {visible} 條"
            page_text = f"第 {self._current_page} / {total_pages} 頁"
        else:
            stats_text = f"共 {total} 条 / 匹配 {matched} 条 / 当前显示 {visible} 条"
            page_text = f"第 {self._current_page} / {total_pages} 页"
        self.footer_stats.setText(stats_text)
        if hasattr(self, "page_indicator"):
            self.page_indicator.setText(page_text)
        if hasattr(self, "prev_page_button"):
            self.prev_page_button.setEnabled(self._current_page > 1 and self._query_matched_count > 0)
        if hasattr(self, "next_page_button"):
            self.next_page_button.setEnabled(
                self._current_page < total_pages and self._query_matched_count > 0 and self._page_size > 0
            )

    def _apply_filters(self) -> None:
        previous_id = self.selected_id()
        self._filter_signature = self._make_filter_signature()
        self._current_page = 1
        self._submit_log_query(reset_page=True, selected_id=previous_id or "")

    def _submit_log_query(self, *, reset_page: bool, selected_id: str | None = None) -> None:
        if reset_page:
            self._current_page = 1
        self._filter_signature = self._make_filter_signature()
        self._query_sequence += 1
        request = LogQueryRequest(
            sequence=self._query_sequence,
            items=self._all_items,
            categories=tuple(LOG_CATEGORIES),
            category=self._category,
            level=self._selected_level_filter(),
            time_range=self._selected_time_filter(),
            platform_id=self._selected_platform_id(),
            trace_query=self._trace_filter_query(),
            keyword=self._keyword_filter_query(),
            platform_options=tuple(self._platform_options),
            platform_meta_by_id=dict(self._platform_meta_by_id),
            page=self._current_page,
            page_size=self._page_size,
            language=self._language,
            selected_id=self.selected_id() if selected_id is None else str(selected_id or ""),
        )
        self._log_query_worker.submit(request)

    @safe_slot
    def _on_log_query_result(self, result: object) -> None:
        if not isinstance(result, LogQueryResult):
            return
        if result.sequence != self._query_sequence:
            return
        self._query_page_items = list(result.page_items)
        self._category_counts = dict(result.category_counts)
        self._category_count_signature = self._make_category_count_signature()
        self._query_total_count = int(result.total_count)
        self._query_matched_count = int(result.matched_count)
        self._query_total_pages = int(result.total_pages)
        self._query_first_trace_id = str(result.first_trace_id or "")
        self._current_page = int(result.current_page)
        self._sync_tab_buttons()
        self._refresh_paged_table(selected_id=result.selected_id)

    def _apply_platform_icons_to_table(self) -> None:
        model = self.table.table_model
        if "source_display" not in model._columns or not self.items:
            return
        column = model._columns.index("source_display")
        top_left = model.index(0, column)
        bottom_right = model.index(len(self.items) - 1, column)
        model.dataChanged.emit(
            top_left,
            bottom_right,
            [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
        )

    def _is_download_component_source(self, source: str) -> bool:
        return is_download_component_source(source)

    def _is_download_boundary_log(self, item: dict[str, Any]) -> bool:
        return is_download_boundary_log(item)

    def _is_platform_root_crawl_log(self, item: dict[str, Any]) -> bool:
        return is_platform_root_crawl_log(item)

    def _is_crawl_pipeline_log(self, item: dict[str, Any]) -> bool:
        return is_crawl_pipeline_log(item)

    @staticmethod
    def _direct_trace_id_from_item(item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        for key in ("trace_id", "traceId", "trace"):
            text = str(item.get(key) or "").strip()
            if text and text != "-":
                return text
        return ""

    def _current_or_first_trace_id(self) -> str:
        current_result = self._current_detail_result_for_selection()
        if current_result is not None and current_result.trace_id:
            return current_result.trace_id
        trace_id = self._direct_trace_id_from_item(self._current_log_item())
        if trace_id:
            return trace_id
        for item in self.items:
            trace_id = self._direct_trace_id_from_item(item)
            if trace_id:
                return trace_id
        return self._query_first_trace_id

    @safe_slot
    def _copy_current_trace_id(self) -> None:
        trace_id = self._current_or_first_trace_id()
        if not trace_id:
            QMessageBox.information(
                self,
                self._t("复制 Trace ID"),
                self._t("当前筛选结果中没有可复制的 Trace ID。"),
            )
            return
        QApplication.clipboard().setText(trace_id)
        if hasattr(self, "copy_trace_button"):
            self._flash_button_text(self.copy_trace_button, self._t("已复制"))

    def _current_detail_result_for_selection(self) -> LogDetailResult | None:
        current_result = self._current_detail_result
        selected_id = self.selected_id()
        if current_result is not None and selected_id and current_result.item_id == selected_id:
            return current_result
        return None

    def _current_log_row_item(self) -> tuple[int, dict[str, Any]] | None:
        if not hasattr(self, "table"):
            return None

        checked_rows: set[int] = set()

        def row_item(row: int) -> tuple[int, dict[str, Any]] | None:
            if row in checked_rows or row < 0:
                return None
            checked_rows.add(row)
            item = self.table.row_at(row)
            if item:
                return row, item
            return None

        index = self.table.currentIndex()
        if index.isValid():
            current = row_item(index.row())
            if current:
                return current

        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selected_current = selection_model.currentIndex()
            if selected_current.isValid():
                current = row_item(selected_current.row())
                if current:
                    return current
            for selected in selection_model.selectedRows():
                current = row_item(selected.row())
                if current:
                    return current

        if self._inspector_item_id:
            for row, item in enumerate(self.items):
                if self._item_id(item, row) == self._inspector_item_id:
                    return row, item

        if self.items:
            return 0, self.items[0]
        return None

    def _current_log_item(self) -> dict[str, Any] | None:
        current = self._current_log_row_item()
        return current[1] if current else None

    def _sync_inspector_action_buttons(self, enabled: bool) -> None:
        for name in ("detail_copy_button", "detail_export_button", "json_copy_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)

    def _flash_button_text(self, button: QPushButton, text: str | None = None, delay_ms: int = 900) -> None:
        source_text = self._source_text(button)
        old_text = self._t(source_text)
        flash_text = text if text is not None else self._t("已复制")
        min_width = int(button.property("logActionMinWidth") or button.minimumWidth() or 52)
        padding = (
            LOG_ACTION_BUTTON_TEXT_PADDING
            if button in getattr(self, "_log_action_buttons", {}).values()
            else LOG_INSPECTOR_BUTTON_TEXT_PADDING
        )

        button.setText(flash_text)
        self._fit_fixed_button_width(button, min_width=min_width, padding=padding)

        def restore() -> None:
            try:
                button.setText(self._t(source_text) if source_text else old_text)
                self._fit_fixed_button_width(button, min_width=min_width, padding=padding)
            except RuntimeError:
                return

        QTimer.singleShot(delay_ms, restore)

    @safe_slot
    def _copy_current_log_json(self) -> None:
        if not self._current_log_item():
            return
        current_result = self._current_detail_result_for_selection()
        if current_result is None:
            return
        QApplication.clipboard().setText(current_result.detail_json_text)
        self._flash_button_text(self.json_copy_button, self._t("已复制"))

    @safe_slot
    def _copy_current_log_detail(self) -> None:
        item = self._current_log_item()
        if not item:
            return
        current_result = self._current_detail_result_for_selection()
        if current_result is None:
            return
        QApplication.clipboard().setText(current_result.full_payload_text)
        self._flash_button_text(self.detail_copy_button, self._t("已复制"))

    @safe_slot
    def _export_current_log_detail(self) -> None:
        item = self._current_log_item()
        if not item:
            QMessageBox.warning(self, self._t("导出失败"), self._t("当前没有可导出的日志。"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("导出日志详情"),
            "log_detail.json",
            self._t("JSON 文件 (*.json);;文本文件 (*.txt)"),
        )
        if not path:
            return
        current_result = self._current_detail_result_for_selection()
        if current_result is None:
            QMessageBox.warning(self, self._t("导出失败"), self._t("当前没有可导出的日志。"))
            return
        try:
            self._detail_export_sequence += 1
            sequence = self._detail_export_sequence
            self.detail_export_button.setEnabled(False)
            self._log_detail_export_worker.submit(
                LogDetailExportRequest(
                    sequence=sequence,
                    item_id=current_result.item_id,
                    path=str(path),
                    text=current_result.full_payload_text,
                )
            )
        except RuntimeError as exc:
            self.detail_export_button.setEnabled(True)
            QMessageBox.warning(self, self._t("导出失败"), f"{self._t('无法写入文件：')}{exc}")

    @safe_slot
    def _on_log_detail_export_result(self, result: object) -> None:
        if not isinstance(result, LogDetailExportResult):
            return
        if result.sequence != self._detail_export_sequence:
            return
        current_result = self._current_detail_result
        self.detail_export_button.setEnabled(current_result is not None)
        if not result.ok:
            QMessageBox.warning(self, self._t("导出失败"), f"{self._t('无法写入文件：')}{result.error}")
            return
        # Async completion must not open a native modal dialog: the page may be
        # closing while this queued result is delivered. Inline feedback keeps
        # export completion non-blocking and teardown-safe.
        self._flash_button_text(self.detail_export_button, self._t("导出成功"))

    def _apply_level_badge_style(self, level: str) -> None:
        mapping = {
            "INFO": "LogLevelBadgeInfo",
            "SUCCESS": "LogLevelBadgeSuccess",
            "OK": "LogLevelBadgeSuccess",
            "WARN": "LogLevelBadgeWarn",
            "WARNING": "LogLevelBadgeWarn",
            "ERROR": "LogLevelBadgeError",
            "CMD": "LogLevelBadgeCommand",
            "COMMAND": "LogLevelBadgeCommand",
        }
        object_name = mapping.get(level.upper(), "LogLevelBadgeInfo")
        self.detail_level_badge.setObjectName(object_name)
        self.detail_level_badge.style().unpolish(self.detail_level_badge)
        self.detail_level_badge.style().polish(self.detail_level_badge)

    def _clear_detail_panel(self) -> None:
        self._detail_sequence += 1
        self._current_detail_result = None
        self._inspector_item_id = ""
        self._sync_inspector_action_buttons(False)
        self.detail_time_value.setText("-")
        self.detail_level_badge.setText("-")
        self._apply_level_badge_style("INFO")
        self.detail_status_value.setText("-")
        self.detail_scope_value.setText("-")
        self.detail_stage_value.setText("-")
        self.detail_status_code_value.setText("-")
        self.detail_source_value.setText("-")
        self.detail_platform_value.setText("-")
        self.detail_trace_value.setText("-")
        self.detail_message_value.setPlainText("-")
        self._configure_message_editor_wrap()
        self.detail_message_value.setToolTip("")
        QTimer.singleShot(0, self._resize_detail_message_box)
        self._last_json_text = "{}"
        self.json_text.setHtml(self._format_json_text_html("{}"))
        QTimer.singleShot(0, self._resize_json_viewer_to_content)
        self.stack_text.clear()
        self.stack_section.setVisible(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "detail_message_value"):
            return
        QTimer.singleShot(0, self._resize_detail_message_box)
        QTimer.singleShot(0, self._resize_json_viewer_to_content)

    @safe_slot
    def _resize_detail_message_box(self) -> None:
        self._configure_message_editor_wrap()
        self._sync_message_document_width()

        editor = self.detail_message_value
        frame = self.detail_message_frame

        viewport_width = editor.viewport().width() if editor.viewport() is not None else 0
        if viewport_width <= 0:
            viewport_width = max(260, self.detail_summary_section.width() - 52)

        document = editor.document()
        document.setTextWidth(max(40, viewport_width - 4))
        document.adjustSize()

        editor_desired_height = int(document.size().height()) + 8

        inspector_height = 0
        if hasattr(self, "inspector_scroll") and self.inspector_scroll.viewport() is not None:
            inspector_height = self.inspector_scroll.viewport().height()

        if inspector_height >= 760:
            max_frame_height = 190
        elif inspector_height >= 620:
            max_frame_height = 160
        else:
            max_frame_height = 130

        frame_padding_v = 20
        desired_frame_height = editor_desired_height + frame_padding_v
        frame_height = max(58, min(max_frame_height, desired_frame_height))

        frame.setFixedHeight(frame_height)

        if desired_frame_height > max_frame_height:
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout_hint = 0
        if self.detail_summary_section.layout() is not None:
            layout_hint = self.detail_summary_section.layout().sizeHint().height()

        kv_height = 9 * 26
        kv_spacing = 8 * 6
        margins = 12 + 12
        message_title = 22
        section_height = max(
            layout_hint,
            kv_height + kv_spacing + message_title + frame_height + margins,
        )

        summary_cap = 420 if inspector_height >= 760 else 380
        self.detail_summary_section.setMaximumHeight(min(summary_cap, max(360, section_height)))

        if hasattr(self, "json_text"):
            QTimer.singleShot(0, self._resize_json_viewer_to_content)

    @safe_slot
    def _resize_json_viewer_to_content(self) -> None:
        text = self._last_json_text or "{}"

        viewport_width = 0
        if hasattr(self, "json_text") and self.json_text.viewport() is not None:
            viewport_width = self.json_text.viewport().width()
        if viewport_width <= 0 and hasattr(self, "json_text"):
            viewport_width = self.json_text.width()

        chars_per_line = max(28, int(max(viewport_width, 260) / 7.2))

        visual_lines = 0
        for raw_line in text.splitlines() or ["{}"]:
            line = raw_line.rstrip()
            if not line:
                visual_lines += 1
                continue
            visual_lines += max(1, math.ceil(len(line) / chars_per_line))

        visual_lines = max(4, visual_lines)
        estimated_height = visual_lines * 22 + 56

        inspector_height = 0
        if hasattr(self, "inspector_scroll") and self.inspector_scroll.viewport() is not None:
            inspector_height = self.inspector_scroll.viewport().height()

        if inspector_height > 0:
            summary_height = 0
            if hasattr(self, "detail_summary_section"):
                summary_height = (
                    self.detail_summary_section.height()
                    or self.detail_summary_section.maximumHeight()
                    or self.detail_summary_section.sizeHint().height()
                )
                summary_height = min(summary_height, self.detail_summary_section.maximumHeight())

            stack_height = 0
            if hasattr(self, "stack_section") and self.stack_section.isVisible():
                stack_height = min(220, max(160, self.stack_section.sizeHint().height())) + 8

            body_margins = 10 + 12
            body_spacing = 8
            json_chrome = 76
            remaining_for_json = (
                inspector_height
                - summary_height
                - stack_height
                - body_margins
                - body_spacing
                - json_chrome
            )
            max_height = max(140, min(360, remaining_for_json, int(inspector_height * 0.42)))
        else:
            max_height = 300

        if estimated_height <= max_height:
            height = max(140, estimated_height)
            self.json_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            height = max_height
            self.json_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.json_text.setFixedHeight(height)

        if hasattr(self, "json_section"):
            self.json_section.setMaximumHeight(height + 76)

    def _format_json_text_html(self, text: str, *, escaped: bool = False) -> str:
        colors = theme_colors(self._resolve_theme_is_dark())
        escaped_text = str(text or "{}") if escaped else html.escape(str(text or "{}"))
        return f"""
        <html>
        <head>
        <style>
        html, body {{
            margin: 0;
            padding: 0;
            background: {colors["panel_soft"]};
            color: {colors["text"]};
            font-family: "Cascadia Mono", "Consolas", monospace;
            font-size: 12px;
        }}
        pre {{
            margin: 0;
            padding: 0;
            white-space: pre-wrap;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}
        </style>
        </head>
        <body><pre>{escaped_text}</pre></body>
        </html>
        """

    def _render_detail(self) -> None:
        current = self._current_log_row_item()
        if not current:
            self._clear_detail_panel()
            return
        row, item = current
        item_id = self._item_id(item, row)
        self._inspector_item_id = item_id
        current_result = self._current_detail_result
        if (
            current_result is not None
            and current_result.item_id == item_id
            and current_result.language == self._language
        ):
            self._sync_inspector_action_buttons(True)
            return
        self._current_detail_result = None
        self._last_json_text = "{}"
        self._sync_inspector_action_buttons(False)
        self.json_text.setHtml(self._format_json_text_html("{}"))
        self.stack_text.clear()
        self.stack_section.setVisible(False)
        self._detail_sequence += 1
        self._log_detail_worker.submit(
            LogDetailRequest(
                sequence=self._detail_sequence,
                item_id=item_id,
                item=dict(item),
                language=self._language,
                platform_options=tuple(self._platform_options),
                platform_meta_by_id=dict(self._platform_meta_by_id),
            )
        )

    @safe_slot
    def _on_log_detail_result(self, result: object) -> None:
        if not isinstance(result, LogDetailResult):
            return
        if result.sequence != self._detail_sequence or result.item_id != self._inspector_item_id:
            return
        self._current_detail_result = result
        self._sync_inspector_action_buttons(True)

        self.detail_time_value.setText(result.time_text)
        self.detail_source_value.setText(result.source_text)
        self.detail_platform_value.setText(result.platform_text)
        self.detail_trace_value.setText(result.trace_id if result.trace_id else "-")
        self.detail_message_value.setPlainText(result.message_text)
        self._configure_message_editor_wrap()
        self.detail_message_value.setToolTip(result.raw_message if result.raw_message else "")
        QTimer.singleShot(0, self._resize_detail_message_box)

        self.detail_level_badge.setText(result.raw_level)
        self._apply_level_badge_style(result.level_style_key)

        self.detail_status_value.setText(result.status_text)
        self.detail_scope_value.setText(result.scope_text)
        self.detail_stage_value.setText(result.stage_text)
        self.detail_status_code_value.setText(result.event_code_text)
        self.detail_status_code_value.setToolTip(result.event_code_tooltip)

        self._last_json_text = result.detail_json_text
        self.json_text.setHtml(self._format_json_text_html(result.detail_json_escaped, escaped=True))
        QTimer.singleShot(0, self._resize_json_viewer_to_content)

        self.stack_section.setVisible(result.has_stack)
        if result.has_stack:
            self.stack_text.setPlainText(result.stack_text)
        else:
            self.stack_text.clear()

    def selected_id(self) -> str | None:
        current = self._current_log_row_item()
        if not current:
            return None
        row, item = current
        return self._item_id(item, row)

    def row_for_id(self, item_id: str) -> int:
        for row, item in enumerate(self.items):
            if self._item_id(item, row) == item_id:
                return row
        return -1

    def select_id(self, item_id: str) -> bool:
        row = self.row_for_id(item_id)
        if row < 0:
            return False
        self.table.selectRow(row)
        return True

    @staticmethod
    def _item_id(item: dict[str, Any], row: int) -> str:
        return stable_log_item_id(item, row)
