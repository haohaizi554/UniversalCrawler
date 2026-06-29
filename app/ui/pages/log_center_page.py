from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from app.debug_logger import debug_logger
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect, QEvent
from PyQt6.QtGui import QFont, QFontMetrics, QIcon, QTextOption
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import platform_icon_file, ui_icon_path
from app.ui.components.combo_popup import (
    ThemedComboBox,
    fit_combo_width_to_contents,
    polish_combo_popup,
    refresh_themed_combo_boxes,
)
from app.ui.pages.common import PageFrame, SnapshotActionDelegate, SnapshotActionTable
from app.ui.styles.themes import resolve_is_dark_theme, theme_colors
from app.utils.safe_slot import safe_slot


LOG_CATEGORIES = {
    "all": "全部日志",
    "crawl": "采集日志",
    "download": "下载日志",
    "system": "系统日志",
    "performance": "性能日志",
    "error": "异常日志",
}


@dataclass(frozen=True)
class PlatformUiMeta:
    id: str
    label: str
    icon_path: str | None = None
    emoji: str | None = None
    aliases: tuple[str, ...] = ()


def _resolve_platform_icon_path(platform_id: str) -> str | None:
    path = Path(ui_icon_path(platform_icon_file(platform_id)))
    return str(path) if path.is_file() else None


_LOG_EMOJI_PREFIX_RE = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]+")


def _platform_icon_file_for_id(platform_id: str, meta: PlatformUiMeta | None) -> str:
    if platform_id == "system":
        return ""
    if not platform_id:
        return ""
    icon_file = platform_icon_file(platform_id)
    if platform_id not in _builtin_platform_metas() and icon_file == "platform_web.png":
        return ""
    return icon_file if Path(ui_icon_path(icon_file)).is_file() else ""


def _builtin_platform_metas() -> dict[str, PlatformUiMeta]:
    return {
        "all": PlatformUiMeta("all", "全部", emoji="🌐"),
        "system": PlatformUiMeta(
            "system",
            "系统",
            icon_path=None,
            emoji="⚙️",
            aliases=("系统", "system", "gui", "applicationcontroller"),
        ),
        "douyin": PlatformUiMeta(
            "douyin",
            "抖音",
            icon_path=_resolve_platform_icon_path("douyin"),
            emoji="🎵",
            aliases=("抖音", "douyin", "dy_", "aweme", "douyinspider", "douyindownloader"),
        ),
        "bilibili": PlatformUiMeta(
            "bilibili",
            "Bilibili",
            icon_path=_resolve_platform_icon_path("bilibili"),
            emoji="📺",
            aliases=(
                "Bilibili",
                "bilibili",
                "bili",
                "biliapi",
                "bilibilispider",
                "bilibilidownloader",
                "bv",
                "bvid",
            ),
        ),
        "kuaishou": PlatformUiMeta(
            "kuaishou",
            "快手",
            icon_path=_resolve_platform_icon_path("kuaishou"),
            emoji="⚡",
            aliases=("快手", "kuaishou", "ks_", "kuaishouspider", "kuaishoudownloader"),
        ),
        "missav": PlatformUiMeta(
            "missav",
            "MissAV",
            icon_path=_resolve_platform_icon_path("missav"),
            emoji="🎬",
            aliases=("MissAV", "missav", "missavspider", "missavdownloader", "surrit"),
        ),
        "xiaohongshu": PlatformUiMeta(
            "xiaohongshu",
            "小红书",
            icon_path=_resolve_platform_icon_path("xiaohongshu"),
            emoji="📕",
            aliases=("小红书", "xiaohongshu", "xhs", "redbook", "xiaohongshuspider", "xiaohongshudownloader"),
        ),
    }


_BUILTIN_PLATFORM_ORDER = ("douyin", "bilibili", "kuaishou", "missav", "xiaohongshu")


class LogCenterTableDelegate(SnapshotActionDelegate):
    """日志中心表格 delegate：source_display 支持按行居中对齐。"""

    def _paint_icon_text(self, painter, option, index) -> None:
        if self._column_key(index) != "source_display":
            super()._paint_icon_text(painter, option, index)
            return
        model = index.model()
        row = model.row_at(index.row()) if hasattr(model, "row_at") else None
        if str((row or {}).get("source_display_align") or "").lower() != "center":
            super()._paint_icon_text(painter, option, index)
            return

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.save()
        rect = option.rect.adjusted(8, 0, -8, 0)
        icon_size = 16
        gap = 6
        has_icon = isinstance(icon, QIcon) and not icon.isNull()
        available_text_width = max(0, rect.width() - (icon_size + gap if has_icon else 0))
        display_text = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, available_text_width)
        text_width = min(available_text_width, option.fontMetrics.horizontalAdvance(display_text))
        content_width = (icon_size + gap if has_icon else 0) + text_width
        x = rect.x() + max(0, (rect.width() - content_width) // 2)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon_rect = QRect(x, rect.y() + max(0, (rect.height() - icon_size) // 2), icon_size, icon_size)
            icon.paint(painter, icon_rect)
            text_rect = QRect(icon_rect.right() + gap, rect.y(), text_width + 2, rect.height())
        else:
            text_rect = QRect(x, rect.y(), text_width + 2, rect.height())
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), display_text)
        painter.restore()


class LogCenterPage(PageFrame):
    log_action_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("", use_island=False)
        self.setObjectName("LogCenterPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._all_items: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self._category = "all"
        self._tab_buttons: dict[str, QPushButton] = {}
        self._platform_options: list[PlatformUiMeta] = []
        self._platform_meta_by_id: dict[str, PlatformUiMeta] = _builtin_platform_metas()
        self._platform_option_ids: tuple[str, ...] = ()
        self._page_size = 20
        self._current_page = 1
        self._filtered_items: list[dict[str, Any]] = []
        self._last_json_text = "{}"
        self._inspector_item_id = ""

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("LogCenterSplitter")
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([860, 420])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)

        self._sync_inspector_action_buttons(False)
        self._refresh_platform_filter()
        self._sync_table_presentation()

    def _resolve_theme_is_dark(self) -> bool:
        window = self.window()
        if window is not None and hasattr(window, "is_dark_theme"):
            return bool(window.is_dark_theme)
        return resolve_is_dark_theme(self)

    def _tab_button_style(self, active: bool) -> str:
        c = theme_colors(self._resolve_theme_is_dark())

        if active:
            return f"""
            QPushButton#LogTabButton {{
                min-height: 34px;
                max-height: 34px;
                min-width: 92px;
                border: 1px solid {c["accent"]};
                border-bottom: 3px solid {c["accent"]};
                border-radius: 8px;
                background-color: {c["accent_soft"]};
                color: {c["accent"]};
                font-size: 14px;
                font-weight: 800;
                padding: 0px 12px;
                margin: 0px 3px 4px 0px;
            }}
            QPushButton#LogTabButton:hover {{
                background-color: {c["accent_soft"]};
                color: {c["accent"]};
                border: 1px solid {c["accent"]};
                border-bottom: 3px solid {c["accent"]};
            }}
            """

        return f"""
        QPushButton#LogTabButton {{
            min-height: 34px;
            max-height: 34px;
            min-width: 92px;
            border: 1px solid {c["border"]};
            border-bottom: 3px solid transparent;
            border-radius: 8px;
            background-color: {c["panel"]};
            color: {c["muted"]};
            font-size: 14px;
            font-weight: 500;
            padding: 0px 12px;
            margin: 0px 3px 4px 0px;
        }}
        QPushButton#LogTabButton:hover {{
            background-color: {c["panel_soft"]};
            color: {c["text"]};
            border: 1px solid {c["border_strong"]};
            border-bottom: 3px solid {c["border_strong"]};
        }}
        """

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

        if hasattr(self, "detail_message_value"):
            self._apply_message_box_style()
            self._configure_message_editor_wrap()
            self._sync_message_document_width()
            QTimer.singleShot(0, self._resize_detail_message_box)

        if hasattr(self, "table"):
            self.table.viewport().update()
            self.table.horizontalHeader().viewport().update()

        if hasattr(self, "json_text"):
            self.json_text.setHtml(self._format_json_html(self._current_detail_payload()))
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
        row = QWidget()
        row.setObjectName("LogTabs")
        row.setFixedHeight(44)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for category, label in LOG_CATEGORIES.items():
            button = QPushButton(label)
            button.setObjectName("LogTabButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFlat(True)
            button.setFixedHeight(34)
            button.setMinimumWidth(92)
            button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=category: self._set_category(key))
            layout.addWidget(button)
            self._tab_buttons[category] = button

        layout.addStretch(1)
        self._sync_tab_buttons()
        return row

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
        self.trace_filter = QLineEdit()
        self.trace_filter.setObjectName("LogFilterControl")
        self.trace_filter.setPlaceholderText("请输入 Trace ID")
        self.keyword_filter = QLineEdit()
        self.keyword_filter.setObjectName("LogFilterControl")
        self.keyword_filter.setPlaceholderText("请输入关键词")

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
            widget.setFixedHeight(32)
            layout.addWidget(label_widget, 0, index)
            layout.addWidget(widget, 1, index)
            layout.setColumnStretch(index, 1)

        self.level_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.time_filter.currentTextChanged.connect(lambda *_args: self._apply_filters())
        self.platform_filter.currentIndexChanged.connect(lambda *_args: self._apply_filters())
        self.trace_filter.textChanged.connect(lambda *_args: self._apply_filters())
        self.keyword_filter.textChanged.connect(lambda *_args: self._apply_filters())
        for combo in (self.level_filter, self.time_filter, self.platform_filter):
            polish_combo_popup(combo, visible_rows=max(1, combo.count()), row_height=34)
        return bar

    def _build_action_bar(self) -> QWidget:
        row = QWidget()
        row.setObjectName("LogActionBar")
        row.setFixedHeight(36)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        actions = [
            ("refresh", "刷新", "刷新日志缓冲", "LogPrimaryActionButton", 68),
            ("clear", "清空", "清空当前日志缓存", "LogDangerActionButton", 68),
            ("export", "导出", "导出日志", "LogActionButton", 68),
            ("open_latest", "debug.log", "打开 latest_debug.log", "LogActionButton", 92),
            ("open_error_summary", "error.md", "打开 latest_error_summary.md", "LogActionButton", 92),
            (
                "copy_trace_id",
                "复制TraceID",
                "复制当前选中日志的 Trace ID；如果当前日志没有 Trace ID，则尝试复制当前筛选结果中的第一个有效 Trace ID。",
                "LogActionButton",
                104,
            ),
        ]
        for operation, label, tooltip, style_name, width in actions:
            button = QPushButton(label)
            button.setObjectName(style_name)
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(30)
            button.setFixedWidth(width)
            if operation == "copy_trace_id":
                self.copy_trace_button = button
                button.clicked.connect(lambda _checked=False: self._copy_current_trace_id())
            else:
                button.clicked.connect(lambda _checked=False, key=operation: self.log_action_requested.emit(key))
            layout.addWidget(button)
        layout.addStretch(1)
        return row

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
            cell_padding=(8, 5),
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
        row = QWidget()
        row.setObjectName("LogTableFooter")
        row.setFixedHeight(48)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.footer_stats = QLabel("共 0 条 / 匹配 0 条 / 当前显示 0 条")
        self.footer_stats.setObjectName("LogFooterStats")
        self.footer_stats.setMinimumWidth(0)
        self.footer_stats.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.footer_stats, 1)

        self.page_indicator = QLabel("第 1 / 1 页")
        self.page_indicator.setObjectName("LogPageIndicator")
        self.page_indicator.setFixedWidth(92)
        self.page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_indicator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.page_indicator, 0)
        self.page_size_combo = ThemedComboBox(row_height=32)
        self.page_size_combo.setObjectName("LogFooterPageSize")
        for label, value in [("20 条/页", 20), ("50 条/页", 50), ("100 条/页", 100), ("全部", 0)]:
            self.page_size_combo.addItem(label, value)
        self.page_size_combo.setFixedHeight(30)
        self.page_size_combo.setProperty("contentWidthPadding", 16)
        self.page_size_combo.setProperty("contentMinWidth", 88)
        self.page_size_combo.setProperty("contentMaxWidth", 168)
        self._fit_page_size_combo_width()
        polish_combo_popup(self.page_size_combo, visible_rows=self.page_size_combo.count(), row_height=32)
        layout.addWidget(self.page_size_combo)
        self.prev_page_button = QPushButton("上一页")
        self.prev_page_button.setObjectName("LogFooterPageButton")
        self.prev_page_button.setFixedHeight(30)
        self.prev_page_button.setMinimumWidth(112)
        self.next_page_button = QPushButton("下一页")
        self.next_page_button.setObjectName("LogFooterPageButton")
        self.next_page_button.setFixedHeight(30)
        self.next_page_button.setMinimumWidth(100)
        layout.addWidget(self.prev_page_button)
        layout.addWidget(self.next_page_button)
        self.page_size_combo.currentIndexChanged.connect(lambda *_args: self._on_page_size_changed())
        self.prev_page_button.clicked.connect(lambda _checked=False: self._go_prev_page())
        self.next_page_button.clicked.connect(lambda _checked=False: self._go_next_page())
        return row

    def _fit_page_size_combo_width(self) -> None:
        fit_combo_width_to_contents(
            self.page_size_combo,
            min_width=88,
            max_width=168,
            horizontal_padding=16,
        )
        return
        metrics = self.page_size_combo.fontMetrics()
        widest = max(
            (metrics.horizontalAdvance(self.page_size_combo.itemText(index)) for index in range(self.page_size_combo.count())),
            default=metrics.horizontalAdvance(self.page_size_combo.currentText() or "20 条/页"),
        )
        target_width = max(104, min(168, widest + 50))
        self.page_size_combo.setFixedWidth(target_width)
        self.page_size_combo.setProperty("comboPopupMaxWidth", target_width)

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
        self.inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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

    def _build_inspector_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("LogInspectorHeader")
        header.setFixedHeight(48)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 10, 12, 10)
        title = QLabel("日志详情")
        title.setObjectName("LogInspectorTitle")
        layout.addWidget(title)
        layout.addStretch(1)
        self.detail_copy_button = QPushButton("复制")
        self.detail_copy_button.setObjectName("LogInspectorActionButton")
        self.detail_export_button = QPushButton("导出")
        self.detail_export_button.setObjectName("LogInspectorActionButton")
        self.detail_copy_button.setFixedHeight(26)
        self.detail_copy_button.setMinimumWidth(52)
        self.detail_export_button.setFixedHeight(26)
        self.detail_export_button.setMinimumWidth(52)
        self.detail_copy_button.clicked.connect(lambda _checked=False: self._copy_current_log_detail())
        self.detail_export_button.clicked.connect(lambda _checked=False: self._export_current_log_detail())
        layout.addWidget(self.detail_copy_button)
        layout.addWidget(self.detail_export_button)
        return header

    def _build_kv_row(self, key: str, value_widget: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("LogKvRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        key_label = QLabel(key)
        key_label.setObjectName("LogDetailKey")
        key_label.setFixedWidth(56)
        key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(key_label)
        layout.addWidget(value_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        row.setFixedHeight(26)
        return row

    def _build_detail_summary_section(self) -> QFrame:
        self.detail_summary_section = self._style_panel(QFrame())
        self.detail_summary_section.setObjectName("LogDetailSummarySection")
        self.detail_summary_section.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.detail_summary_section.setMaximumHeight(360)
        layout = QVBoxLayout(self.detail_summary_section)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.detail_time_value = QLabel("-")
        self.detail_level_badge = QLabel("-")
        self.detail_level_badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.detail_status_value = QLabel("-")
        self.detail_scope_value = QLabel("-")
        self.detail_stage_value = QLabel("-")
        self.detail_status_code_value = QLabel("-")
        self.detail_source_value = QLabel("-")
        self.detail_platform_value = QLabel("-")
        self.detail_trace_value = QLabel("-")
        self.detail_message_frame = QFrame()
        self.detail_message_frame.setObjectName("LogMessageBoxFrame")
        self.detail_message_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.detail_message_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.detail_message_frame.setMinimumHeight(56)
        self.detail_message_frame.setMaximumHeight(190)

        message_frame_layout = QVBoxLayout(self.detail_message_frame)
        message_frame_layout.setContentsMargins(12, 10, 12, 10)
        message_frame_layout.setSpacing(0)

        self.detail_message_value = QPlainTextEdit()
        self.detail_message_value.setObjectName("LogMessageText")
        self.detail_message_value.setReadOnly(True)
        self.detail_message_value.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_message_value.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_message_value.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_message_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail_message_value.setMinimumWidth(0)
        self.detail_message_value.setMinimumHeight(36)
        self.detail_message_value.setPlainText("-")
        self.detail_message_value.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._configure_message_editor_wrap()

        message_frame_layout.addWidget(self.detail_message_value)
        self._apply_message_box_style()

        value_labels = (
            self.detail_time_value,
            self.detail_status_value,
            self.detail_scope_value,
            self.detail_stage_value,
            self.detail_status_code_value,
            self.detail_source_value,
            self.detail_platform_value,
            self.detail_trace_value,
        )
        for label in value_labels:
            label.setObjectName("LogDetailValue")
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        self.detail_level_badge.setObjectName("LogLevelBadgeInfo")
        self.detail_level_badge.setFixedHeight(22)
        self.detail_level_badge.setMinimumWidth(46)
        self.detail_level_badge.setMaximumWidth(76)
        self.detail_level_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._build_kv_row("时间", self.detail_time_value))
        layout.addWidget(self._build_kv_row("级别", self.detail_level_badge))
        layout.addWidget(self._build_kv_row("性质", self.detail_status_value))
        layout.addWidget(self._build_kv_row("范围", self.detail_scope_value))
        layout.addWidget(self._build_kv_row("阶段", self.detail_stage_value))
        layout.addWidget(self._build_kv_row("事件码", self.detail_status_code_value))
        layout.addWidget(self._build_kv_row("来源", self.detail_source_value))
        layout.addWidget(self._build_kv_row("平台", self.detail_platform_value))
        layout.addWidget(self._build_kv_row("Trace ID", self.detail_trace_value))

        message_title = QLabel("消息")
        message_title.setObjectName("LogMessageTitle")
        layout.addWidget(message_title)
        layout.addWidget(self.detail_message_frame)
        return self.detail_summary_section

    def _build_json_section(self) -> QFrame:
        section = self._style_panel(QFrame())
        self.json_section = section
        section.setObjectName("LogJsonSection")
        section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        section.setMaximumHeight(520)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header_widget = QWidget()
        header_widget.setObjectName("LogJsonSectionHeader")
        header_widget.setFixedHeight(32)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("详细信息")
        title.setObjectName("LogSectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.json_copy_button = QPushButton("复制")
        self.json_copy_button.setObjectName("LogInspectorActionButton")
        self.json_copy_button.setFixedHeight(26)
        self.json_copy_button.setMinimumWidth(52)
        self.json_copy_button.clicked.connect(lambda _checked=False: self._copy_current_log_json())
        header.addWidget(self.json_copy_button)
        layout.addWidget(header_widget)

        self.json_text = QTextBrowser()
        self.json_text.setObjectName("LogJsonViewer")
        self.json_text.setOpenExternalLinks(False)
        self.json_text.setFrameShape(QFrame.Shape.NoFrame)
        self.json_text.setReadOnly(True)
        self.json_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.json_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.json_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.json_text.setContentsMargins(0, 0, 0, 0)
        self.json_text.document().setDocumentMargin(0)
        layout.addWidget(self.json_text, 0)
        return section

    def _build_stack_section(self) -> QFrame:
        self.stack_section = self._style_panel(QFrame())
        self.stack_section.setObjectName("LogStackSection")
        self.stack_section.setMinimumHeight(160)
        self.stack_section.setMaximumHeight(220)
        layout = QVBoxLayout(self.stack_section)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        title = QLabel("堆栈跟踪")
        title.setObjectName("LogSectionTitle")
        layout.addWidget(title)
        self.stack_text = QPlainTextEdit()
        self.stack_text.setObjectName("LogStackText")
        self.stack_text.setReadOnly(True)
        self.stack_text.setFrameShape(QFrame.Shape.NoFrame)
        self.stack_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.stack_text.setFont(mono)
        layout.addWidget(self.stack_text, 1)
        self.stack_section.setVisible(False)
        return self.stack_section

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
        subtitle = QLabel("调整筛选条件，或点击「刷新缓冲」重新加载日志")
        subtitle.setObjectName("LogEmptySubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return panel

    def _configure_table_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setFixedHeight(32)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 178)
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
        builtins = _builtin_platform_metas()
        options: list[PlatformUiMeta] = [builtins["all"]]
        seen: set[str] = {"all"}
        entries: list[dict[str, Any]] = []

        snapshot = snapshot or {}
        for key in ("platforms", "plugins", "available_platforms"):
            value = snapshot.get(key)
            if isinstance(value, list) and value:
                for item in value:
                    if isinstance(item, dict):
                        entries.append(item)
                    elif isinstance(item, str) and item.strip():
                        entries.append({"id": item.strip()})
                break

        if not entries:
            settings = snapshot.get("settings_snapshot")
            if isinstance(settings, dict):
                platform_settings = settings.get("平台设置")
                if isinstance(platform_settings, list):
                    entries.extend(item for item in platform_settings if isinstance(item, dict))

        if not entries:
            try:
                from app.core.plugin_registry import registry

                for plugin in registry.get_all_plugins():
                    entries.append({"id": plugin.id, "name": plugin.name})
            except (ImportError, RuntimeError, AttributeError) as exc:
                debug_logger.log_exception("LogCenterPage", "load_plugin_entries", exc)

        for entry in entries:
            platform_id = str(entry.get("id") or entry.get("platform_id") or "").strip().lower()
            if not platform_id or platform_id in seen or platform_id == "all":
                continue
            default = builtins.get(platform_id)
            label = str(entry.get("name") or entry.get("label") or (default.label if default else platform_id))
            icon_path = str(entry.get("icon_path") or entry.get("icon") or "").strip() or None
            if icon_path and not Path(icon_path).is_file():
                icon_path = _resolve_platform_icon_path(platform_id)
            elif not icon_path and default:
                icon_path = default.icon_path
            emoji = default.emoji if default else None
            aliases = default.aliases if default else (platform_id,)
            options.append(
                PlatformUiMeta(
                    id=platform_id,
                    label=label,
                    icon_path=icon_path,
                    emoji=emoji,
                    aliases=aliases,
                )
            )
            seen.add(platform_id)

        for platform_id in _BUILTIN_PLATFORM_ORDER:
            if platform_id in seen:
                continue
            options.append(builtins[platform_id])
            seen.add(platform_id)

        if "system" not in seen:
            options.append(builtins["system"])
        return options

    def _add_platform_combo_item(self, meta: PlatformUiMeta) -> None:
        label = meta.label
        if meta.emoji and not (meta.icon_path and Path(meta.icon_path).is_file()):
            label = f"{meta.emoji} {label}"
        icon = QIcon()
        if meta.icon_path and Path(meta.icon_path).is_file():
            icon = QIcon(meta.icon_path)
        self.platform_filter.addItem(icon, label, meta.id)

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

    def render(self, snapshot: dict) -> None:
        self._refresh_platform_filter(snapshot)
        self._all_items = list(snapshot.get("log_items") or [])

        self._sync_tab_buttons()

        self._apply_filters()

    def _debug_classification_counts(self) -> dict[str, int]:
        counts = {key: 0 for key in LOG_CATEGORIES}
        for item in self._all_items:
            counts["all"] += 1
            scope = self._derive_log_scope(item)
            if scope in counts:
                counts[scope] += 1
        return counts

    def _debug_classification_matrix(self) -> dict[str, Any]:
        """Debug helper only. Do not render in UI."""
        matrix: dict[str, dict[str, int]] = {}
        suspicious_system_downloads: list[dict[str, str]] = []

        for item in self._all_items:
            scope = self._derive_log_scope(item)
            platform_id = self._resolve_item_platform_id(item) or "unresolved"

            matrix.setdefault(scope, {})
            matrix[scope][platform_id] = matrix[scope].get(platform_id, 0) + 1

            facts = self._classification_facts(item)

            if scope == "system" and (
                facts["status_upper"].startswith(
                    ("DL_", "APP_DL_", "BILI_DL_", "XHS_DL_", "DY_DL_", "KS_DL_", "MISSAV_DL_")
                )
                or facts["event_code_upper"].startswith(
                    ("DL_", "APP_DL_", "BILI_DL_", "XHS_DL_", "DY_DL_", "KS_DL_", "MISSAV_DL_")
                )
                or "downloadmanager" in facts["source_lower"]
                or "downloadworker" in facts["source_lower"]
                or "downloader" in facts["source_lower"]
                or "下载任务" in facts["message_lower"]
                or "下载完成" in facts["message_lower"]
            ):
                suspicious_system_downloads.append(
                    {
                        "source": facts["source"],
                        "action": facts["action"],
                        "status": facts["status"],
                        "event_code": facts["event_code"],
                        "message": facts["message"][:100],
                        "reason": self._derive_scope_reason(item),
                    }
                )

        return {
            "matrix": matrix,
            "suspicious_system_downloads": suspicious_system_downloads[:50],
        }

    def _set_category(self, category: str) -> None:
        self._category = category if category in LOG_CATEGORIES else "all"
        self._sync_tab_buttons()
        self._apply_filters()

    def _category_count(self, category: str) -> int:
        count = 0
        for item in self._all_items:
            if not self._matches_non_category_filters(item):
                continue
            if category == "all" or self._matches_category_for_count(item, category):
                count += 1
        return count

    def _matches_category_for_count(self, item: dict[str, Any], category: str) -> bool:
        if category == "all":
            return True
        scope = self._derive_log_scope(item)
        return scope == category

    def _update_category_tab_counts(self) -> None:
        for category, button in self._tab_buttons.items():
            label = LOG_CATEGORIES[category]
            count = self._category_count(category)
            button.setText(f"{label} {count}")

    def _sync_tab_buttons(self) -> None:
        self._update_category_tab_counts()

        for category, button in self._tab_buttons.items():
            active = category == self._category
            self._apply_tab_button_style(button, active)

    def _sync_table_presentation(self) -> None:
        self.table_stack.setCurrentIndex(0 if self.items else 1)
        self._update_footer_stats()

    def _total_pages(self) -> int:
        if self._page_size <= 0:
            return 1
        return max(1, math.ceil(len(self._filtered_items) / self._page_size))

    @safe_slot
    def _on_page_size_changed(self) -> None:
        data = self.page_size_combo.currentData() if hasattr(self, "page_size_combo") else None
        if data is not None:
            self._page_size = int(data)
        else:
            text = self.page_size_combo.currentText() if hasattr(self, "page_size_combo") else "20 条/页"
            self._page_size = 0 if text in {"全部", "All", "全部"} else int(text.split()[0])
        self._current_page = 1
        self._refresh_paged_table()

    @safe_slot
    def _go_prev_page(self) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self._refresh_paged_table()

    @safe_slot
    def _go_next_page(self) -> None:
        if self._current_page < self._total_pages():
            self._current_page += 1
            self._refresh_paged_table()

    def _refresh_paged_table(self) -> None:
        if self._page_size <= 0:
            page_items = list(self._filtered_items)
        else:
            start = (self._current_page - 1) * self._page_size
            end = start + self._page_size
            page_items = self._filtered_items[start:end]
        self.items = [self._decorate_log_item(item) for item in page_items]

        self.table.set_rows(self.items)
        self._configure_table_columns()
        self._apply_platform_icons_to_table()
        self._sync_table_presentation()

        if self.items:
            self.table.selectRow(0)
        self._render_detail()

    def _update_footer_stats(self) -> None:
        if not hasattr(self, "footer_stats"):
            return
        total_pages = self._total_pages()
        self.footer_stats.setText(
            f"共 {len(self._all_items)} 条 / 匹配 {len(self._filtered_items)} 条 / 当前显示 {len(self.items)} 条"
        )
        if hasattr(self, "page_indicator"):
            self.page_indicator.setText(f"第 {self._current_page} / {total_pages} 页")
        if hasattr(self, "prev_page_button"):
            self.prev_page_button.setEnabled(self._current_page > 1 and bool(self._filtered_items))
        if hasattr(self, "next_page_button"):
            self.next_page_button.setEnabled(
                self._current_page < total_pages and bool(self._filtered_items) and self._page_size > 0
            )

    def _apply_filters(self) -> None:
        previous_id = self.selected_id()
        raw_items = [item for item in self._all_items if self._matches_filters(item)]
        self._filtered_items = self._sort_log_items(raw_items)
        self._current_page = 1
        if previous_id:
            for index, item in enumerate(self._filtered_items):
                if self._item_id(item, index) == previous_id:
                    if self._page_size > 0:
                        self._current_page = index // self._page_size + 1
                    break
        self._current_page = min(self._current_page, self._total_pages())
        self._refresh_paged_table()
        if previous_id and self.select_id(previous_id):
            self._render_detail()
            return
        if self.items:
            self.table.selectRow(0)
        self._render_detail()

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

    def _normalized_source(self, item: dict[str, Any]) -> str:
        value = str(
            item.get("source")
            or item.get("logger")
            or item.get("module")
            or item.get("component")
            or ""
        ).strip()

        if "/" in value:
            left, _right = value.split("/", 1)
            return left.strip()

        return value

    def _normalized_action(self, item: dict[str, Any]) -> str:
        value = str(
            item.get("action")
            or item.get("event")
            or item.get("event_type")
            or item.get("operation")
            or ""
        ).strip()

        if value:
            return value

        source = str(item.get("source") or "").strip()
        if "/" in source:
            _left, right = source.split("/", 1)
            return right.strip()

        return ""

    def _classification_facts(self, item: dict[str, Any]) -> dict[str, str]:
        """Build one normalized text/facts object for all semantic classification.

        Do not trust item['category'] as the source of truth.
        Existing category is kept only as legacy_category fallback.
        """
        raw_source = str(
            item.get("source")
            or item.get("logger")
            or item.get("module")
            or item.get("component")
            or ""
        ).strip()

        raw_action = str(
            item.get("action")
            or item.get("event")
            or item.get("event_type")
            or item.get("operation")
            or ""
        ).strip()

        source = raw_source
        action = raw_action
        if "/" in raw_source:
            left, right = raw_source.split("/", 1)
            if left.strip():
                source = left.strip()
            if not action and right.strip():
                action = right.strip()

        detail = item.get("detail")
        detail_text = ""
        if isinstance(detail, dict):
            try:
                detail_text = json.dumps(detail, ensure_ascii=False, default=str)
            except TypeError:
                detail_text = str(detail)
        else:
            detail_text = str(detail or "")

        status = self._normalized_status_code(item)
        event_code = status or self._normalized_event_code(item)

        message = str(
            item.get("message")
            or item.get("message_summary")
            or item.get("description")
            or ""
        ).strip()

        platform = str(item.get("platform") or item.get("platform_label") or "").strip()
        trace_id = str(item.get("trace_id") or item.get("traceId") or "").strip()
        raw_level = self._normalized_raw_level(item)
        legacy_category = str(item.get("category") or "").strip().lower()

        combined = " ".join(
            [
                raw_level,
                source,
                action,
                status,
                event_code,
                message,
                platform,
                trace_id,
                detail_text,
                legacy_category,
            ]
        )

        return {
            "raw_level": raw_level,
            "source": source,
            "source_lower": source.lower(),
            "action": action,
            "action_lower": action.lower(),
            "status": status,
            "status_upper": status.upper(),
            "event_code": event_code,
            "event_code_upper": event_code.upper(),
            "message": message,
            "message_lower": message.lower(),
            "platform": platform,
            "platform_lower": platform.lower(),
            "trace_id": trace_id,
            "detail_text": detail_text,
            "detail_lower": detail_text.lower(),
            "legacy_category": legacy_category,
            "combined": combined,
            "combined_upper": combined.upper(),
            "combined_lower": combined.lower(),
        }

    def _normalized_status_code(self, item: dict[str, Any]) -> str:
        def pick_from_dict(data: dict[str, Any]) -> str:
            keys = (
                "status_code",
                "状态码",
                "code",
                "event",
                "event_type",
                "status",
                "状态",
                "http_status",
                "api_code",
            )
            for key in keys:
                value = data.get(key)
                text = str(value or "").strip()
                if text:
                    return text

            nested_keys = (
                "detail",
                "details",
                "extra",
                "request",
                "response",
                "response_summary",
                "响应摘要",
                "context",
                "上下文",
                "payload",
            )
            for key in nested_keys:
                value = data.get(key)
                if isinstance(value, dict):
                    nested = pick_from_dict(value)
                    if nested:
                        return nested
            return ""

        candidates: list[str] = []

        direct = pick_from_dict(item)
        if direct:
            candidates.append(direct)

        detail = item.get("detail")
        if isinstance(detail, dict):
            value = pick_from_dict(detail)
            if value:
                candidates.append(value)
        elif isinstance(detail, str) and detail.strip():
            text = detail.strip()
            structured = self._parse_structured_detail_text(text)
            if structured:
                value = pick_from_dict(structured)
                if value:
                    candidates.append(value)

            for pattern in (
                r"状态码\s*[:：]\s*([A-Za-z0-9_./:-]+)",
                r"status_code\s*[:：]\s*([A-Za-z0-9_./:-]+)",
                r"状态\s*[:：]\s*([A-Za-z0-9_./:-]+)",
            ):
                match = re.search(pattern, text)
                if match:
                    candidates.append(match.group(1).strip())

        for value in candidates:
            text = str(value or "").strip()
            if text:
                return text

        return ""

    def _normalized_event_code(self, item: dict[str, Any]) -> str:
        status = self._normalized_status_code(item)
        if status:
            return status

        action = self._normalized_action(item)
        if action:
            text = action.strip()
            text = text.replace("API::", "API_")
            text = re.sub(r"[^A-Za-z0-9]+", "_", text)
            text = re.sub(r"_+", "_", text).strip("_")
            if text:
                return text.upper()

        source = self._normalized_source(item)
        message = str(item.get("message") or item.get("message_summary") or "").strip()
        if source or message:
            seed = f"{source}_{message[:32]}"
            seed = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", seed)
            seed = re.sub(r"_+", "_", seed).strip("_")
            return seed.upper() if seed else "-"

        return "-"

    def _normalized_raw_level(self, item: dict[str, Any]) -> str:
        return str(item.get("level") or "").strip().upper()

    def _is_performance_log(self, item: dict[str, Any]) -> bool:
        facts = self._classification_facts(item)
        combined = facts["combined_upper"]

        tokens = (
            "FRONTEND_RENDER_SLOW",
            "FRONTEND RENDER SLOW",
            "UI_RENDER_SLOW",
            "UI_REFRESH_SLOW",
            "SCHEDULER_SLOW",
            "RENDER_SLOW",
            "FLUSH_SLOW",
            "INTERACTIVE BUDGET",
            "RENDER EXCEEDED",
            "REFRESH CADENCE WAS RELAXED",
            "COALESCED_COUNT",
            "SCHEDULED_COUNT",
            "LAST_FLUSH_DURATION_MS",
            "DURATION_MS",
        )
        return any(token in combined for token in tokens)

    def _is_system_config_log(self, item: dict[str, Any]) -> bool:
        """Only classify real UI/system configuration changes as system config.

        Do not scan detail_text here. Download task detail often contains
        save_dir / max_concurrent / options-like fields.
        """
        facts = self._classification_facts(item)

        source = facts["source_lower"]
        action = facts["action_lower"]
        status = facts["status_upper"]
        event_code = facts["event_code_upper"]
        message = facts["message_lower"]

        config_text = " ".join(
            [
                source,
                action,
                status,
                event_code,
                message,
            ]
        ).upper()

        config_sources = (
            "gui",
            "mainwindow",
            "applicationcontroller",
            "system",
        )

        explicit_config_actions = {
            "update_download_options",
            "download_options_updated",
            "change_download_options",
            "set_download_options",
            "update_settings",
            "save_settings",
            "change_save_dir",
            "scan_local_dir",
            "scan_local_dir_finished",
        }

        explicit_config_statuses = (
            "APP_DIR_CHANGED",
            "APP_SCAN_START",
            "APP_SCAN_OK",
            "APP_SETTINGS_UPDATED",
            "APP_CONFIG_UPDATED",
            "DOWNLOAD_OPTIONS_UPDATED",
        )

        if action in explicit_config_actions:
            return True

        if status.startswith(explicit_config_statuses):
            return True

        if event_code.startswith(explicit_config_statuses):
            return True

        if any(src in source for src in config_sources):
            message_tokens = (
                "DOWNLOAD OPTIONS UPDATED",
                "CONCURRENCY=",
                "RETRIES=",
                "AUTO_RETRY",
                "AUTO RETRY",
                "修改线程",
                "线程并发",
                "并发数",
                "重试次数",
                "自动重试",
                "更改目录",
                "保存目录",
                "配置已更新",
                "设置已更新",
            )
            if any(token in config_text for token in message_tokens):
                return True

        return False

    def _derive_result_type(self, item: dict[str, Any]) -> str:
        facts = self._classification_facts(item)

        raw_level = facts["raw_level"]
        source = facts["source_lower"]
        action = facts["action_lower"]
        status = facts["status_upper"]
        combined = facts["combined_upper"]

        if raw_level in {"ERROR", "FATAL", "CRITICAL"}:
            return "error"

        if raw_level in {"WARN", "WARNING"}:
            return "warn"

        if raw_level in {"COMMAND", "CMD"}:
            return "command"

        if "FFMPEG" in combined or "COMMAND" in combined or action == "ffmpeg":
            return "command"

        if self._is_performance_log(item):
            return "warn"

        error_tokens = (
            "ERROR",
            "FAIL",
            "FAILED",
            "EXCEPTION",
            "FATAL",
            "TIMEOUT",
            "ABORT",
            "CONNECTION_RESET",
            "PROXY_ERROR",
            "LOCAL_HLS_PROXY_ERROR",
            "HTTP_4",
            "HTTP_5",
        )
        if any(token in combined for token in error_tokens):
            return "error"

        config_tokens = (
            "DOWNLOAD OPTIONS UPDATED",
            "CONCURRENCY",
            "AUTO_RETRY",
            "AUTO RETRY",
            "RETRIES",
            "THREAD",
            "MAX_CONCURRENT",
        )
        if any(token in combined for token in config_tokens):
            return "info"

        warn_tokens = (
            "WARN",
            "WARNING",
            "SLOW",
            "RETRY",
            "DEGRADED",
            "RATE_LIMIT",
            "SKIP",
            "EMPTY",
            "NOT_FOUND",
        )
        if any(token in combined for token in warn_tokens):
            return "warn"

        success_tokens = (
            "_OK",
            "_SUCCESS",
            "_FINISH",
            "_FINISHED",
            "_COMPLETE",
            "_COMPLETED",
            "_DONE",
            "APP_READY",
            "APP_SCAN_OK",
            "DL_FINISH",
            "APP_DL_FINISH",
            "BILI_MERGE_OK",
            "MERGE_FINISHED",
            "DOWNLOAD_FINISHED",
        )
        if any(token in combined for token in success_tokens):
            return "success"

        message = facts["message_lower"]
        detail = facts["detail_lower"]

        success_message_tokens = (
            "下载完成",
            "下载任务完成",
            "合并完成",
            "音视频合并完成",
            "流请求建立成功",
        )

        if any(token in message for token in success_message_tokens):
            return "success"

        if any(token in detail for token in success_message_tokens):
            return "success"

        if status == "200":
            if (
                "api::" in action
                or action.startswith("api_")
                or "stream_" in action
                or "request" in action
                or "check_login" in action
                or "get_video_info" in action
                or "get_play_url" in action
                or "api" in source
                or "downloader" in source
            ):
                return "success"

        return "info"

    @staticmethod
    def _result_display_text(result_type: str, raw_level: str = "") -> str:
        return {
            "info": "INFO",
            "success": "SUCCESS",
            "warn": "WARN",
            "error": "ERROR",
            "command": "CMD",
        }.get(result_type, raw_level or "INFO")

    @staticmethod
    def _result_nature_text(result_type: str) -> str:
        return {
            "info": "过程",
            "success": "成功",
            "warn": "预警",
            "error": "错误",
            "command": "命令",
        }.get(result_type, "过程")

    def _is_download_component_source(self, source: str) -> bool:
        source = str(source or "").strip().lower()
        if not source:
            return False

        tokens = (
            "downloadmanager",
            "download_manager",
            "downloadworker",
            "download_worker",
            "downloadrunner",
            "download_runner",
            "downloadservice",
            "download_service",
            "downloader",
            "bilibilidownloader",
            "douyindownloader",
            "kuaishoudownloader",
            "xiaohongshudownloader",
            "missavdownloader",
            "n_m3u8dl",
            "n_m3u8dl_re",
            "ffmpeg",
        )
        return any(token in source for token in tokens)

    def _is_download_boundary_log(self, item: dict[str, Any]) -> bool:
        """Return True only after the pipeline has crossed into download execution.

        Must recognize both structured event codes and Chinese generated messages.
        """
        facts = self._classification_facts(item)
        source = facts["source_lower"]
        action = facts["action_lower"]
        status = facts["status_upper"]
        event_code = facts["event_code_upper"]
        message = facts["message_lower"]
        detail = facts["detail_lower"]
        combined = facts["combined_upper"]

        crawl_handoff_statuses = (
            "BILI_TASK_EMIT",
            "BILI_QUEUE_READY",
            "APP_ITEM_FOUND",
            "APP_CRAWL_START",
            "APP_CRAWL_FINISH",
            "XHS_TASK_EMIT",
            "DY_TASK_EMIT",
            "KS_TASK_EMIT",
            "MISSAV_TASK_EMIT",
        )
        if status in crawl_handoff_statuses or event_code in crawl_handoff_statuses:
            return False

        crawl_handoff_actions = {
            "emit_download_task",
            "download_queue_ready",
            "item_found",
            "start_crawl",
            "crawl_finished",
            "run_start",
            "run_finish",
        }
        if action in crawl_handoff_actions:
            return False

        download_status_prefixes = (
            "DL_",
            "APP_DL_",
            "BILI_DL_",
            "BILI_MERGE",
            "XHS_DL_",
            "DY_DL_",
            "KS_DL_",
            "MISSAV_DL_",
        )
        if any(status.startswith(prefix) for prefix in download_status_prefixes):
            return True
        if any(event_code.startswith(prefix) for prefix in download_status_prefixes):
            return True

        download_actions = {
            "queue_task",
            "dispatch_task",
            "start_download",
            "prepare_download",
            "download_finished",
            "normalize_extension",
            "release_slot",
            "merge_finished",
            "ffmpeg",
            "api::stream_audio",
            "api::stream_video",
            "stream_audio",
            "stream_video",
            "download_stream",
            "download_file",
            "download_hls",
            "download_m3u8",
        }
        if action in download_actions:
            return True

        chinese_download_tokens = (
            "下载完成",
            "下载任务完成",
            "下载任务已进入队列",
            "进入队列",
            "已进入队列",
            "任务已从队列分发",
            "从队列分发",
            "分发到下载线程",
            "下载任务开始执行",
            "开始执行",
            "开始下载",
            "准备下载",
            "下载并发槽位已释放",
            "槽位已释放",
            "音视频合并完成",
            "合并完成",
            "流请求建立成功",
        )

        generated_download_prefixes = (
            "DOWNLOADER_",
            "DOWNLOADMANAGER_",
            "DOWNLOADWORKER_",
            "DOWNLOADRUNNER_",
            "DOWNLOADSERVICE_",
            "BILIBILIDOWNLOADER_",
            "DOUYINDOWNLOADER_",
            "KUAISHOUDOWNLOADER_",
            "XIAOHONGSHUDOWNLOADER_",
            "MISSAVDOWNLOADER_",
        )

        generated_text = " ".join([event_code, status, message, detail]).lower()

        if any(event_code.startswith(prefix) for prefix in generated_download_prefixes):
            if any(token in generated_text for token in chinese_download_tokens):
                return True

        if self._is_download_component_source(source):
            if any(token in message for token in chinese_download_tokens):
                return True
            if any(token in detail for token in chinese_download_tokens):
                return True

        strong_download_sources = (
            "downloadmanager",
            "download_manager",
            "downloadworker",
            "download_worker",
            "downloadrunner",
            "download_runner",
            "downloadservice",
            "download_service",
            "n_m3u8dl",
            "n_m3u8dl_re",
            "ffmpeg",
        )
        if any(token in source for token in strong_download_sources):
            return True

        if "FFMPEG" in combined:
            return True

        if "MERGE" in combined:
            return True

        if "合并" in message:
            return True

        if "downloader" in source:
            downloader_boundary_tokens = (
                "PREPARE",
                "STREAM_AUDIO",
                "STREAM_VIDEO",
                "START_DOWNLOAD",
                "DL_START",
                "DL_QUEUE",
                "DL_DISPATCH",
                "DL_FINISH",
                "BILI_DL_PREPARE",
                "BILI_MERGE_OK",
                "SAVE_PATH",
                "TARGET_PATH",
                "LOCAL_PATH",
                "CONTENT_LENGTH",
                "_VIDEO.M4S",
                "_AUDIO.M4S",
                "M3U8",
            )
            boundary_text = " ".join(
                [
                    action.upper(),
                    status,
                    event_code,
                    message.upper(),
                    detail.upper(),
                ]
            )
            if any(token in boundary_text for token in downloader_boundary_tokens):
                return True

        return False

    def _is_platform_root_crawl_log(self, item: dict[str, Any]) -> bool:
        """Platform root source logs are crawl logs unless they cross download boundary."""
        if self._is_download_boundary_log(item):
            return False

        facts = self._classification_facts(item)
        source = facts["source_lower"]
        message = facts["message_lower"]
        status = facts["status_upper"]
        event_code = facts["event_code_upper"]
        combined = facts["combined_upper"]

        platform_root_sources = {
            "bilibili",
            "bili",
            "douyin",
            "dy",
            "kuaishou",
            "ks",
            "xiaohongshu",
            "xhs",
            "redbook",
            "missav",
        }

        if source in platform_root_sources:
            return True

        platform_prefixes = (
            "BILIBILI_",
            "BILI_",
            "DOUYIN_",
            "DY_",
            "KUAISHOU_",
            "KS_",
            "XIAOHONGSHU_",
            "XHS_",
            "MISSAV_",
        )

        if any(status.startswith(prefix) for prefix in platform_prefixes):
            return True

        if any(event_code.startswith(prefix) for prefix in platform_prefixes):
            return True

        crawl_message_tokens = (
            "已聚合",
            "聚合",
            "扫描结束",
            "扫描完成",
            "正在展开",
            "展开",
            "最终确认",
            "有效资源",
            "候选资源",
            "发现",
            "第 ",
            "页",
            "route",
            "搜索",
            "解析",
            "获取播放",
            "播放地址",
            "装配完成",
            "提交到下载队列",
        )

        if any(token in message for token in crawl_message_tokens):
            return True

        crawl_combined_tokens = (
            "AGGREGATE",
            "AGGREGATED",
            "COLLECT",
            "COLLECTED",
            "EXPAND",
            "EXPANDED",
            "SCAN",
            "FOUND",
            "DISCOVER",
            "DISCOVERED",
            "CONFIRM",
            "CONFIRMED",
            "ROUTE",
            "PARSE",
            "EXTRACT",
            "FETCH",
            "PLAY_URL",
            "GET_VIDEO_INFO",
            "GET_PLAY_URL",
            "TASK_EMIT",
            "QUEUE_READY",
        )

        if any(token in combined for token in crawl_combined_tokens):
            return True

        return False

    def _is_crawl_pipeline_log(self, item: dict[str, Any]) -> bool:
        """Return True for search/parse/extract/discovery logs before download boundary."""
        if self._is_download_boundary_log(item):
            return False

        if self._is_platform_root_crawl_log(item):
            return True

        facts = self._classification_facts(item)
        source = facts["source_lower"]
        action = facts["action_lower"]
        status = facts["status_upper"]
        event_code = facts["event_code_upper"]
        message = facts["message_lower"]
        combined = facts["combined_upper"]

        crawl_status_prefixes = (
            "APP_CRAWL",
            "APP_ITEM_FOUND",
            "BILI_SPIDER",
            "BILI_ROUTE",
            "BILI_PARSE",
            "BILI_API",
            "BILI_QUEUE_READY",
            "BILI_TASK_EMIT",
            "XHS_",
            "DY_",
            "KS_",
            "MISSAV_",
        )

        crawl_actions = {
            "run_start",
            "run_finish",
            "start_crawl",
            "item_found",
            "download_queue_ready",
            "emit_download_task",
            "api::check_login",
            "api::get_video_info",
            "api::get_play_url",
            "check_login",
            "get_video_info",
            "get_play_url",
            "search",
            "parse",
            "fetch",
            "extract",
            "extract_detail",
            "extract_items",
            "resolve_url",
            "resolve_play_url",
            "parse_detail",
            "parse_page",
            "parse_video",
            "parse_note",
            "parse_aweme",
            "parse_feed",
            "parse_profile",
        }

        crawl_source_tokens = (
            "spider",
            "api",
            "parser",
            "extractor",
            "crawler",
            "scraper",
            "resolver",
            "route",
            "browser",
            "playwright",
        )

        crawl_message_tokens = (
            "解析",
            "获取播放流地址",
            "获取播放地址",
            "检查登录",
            "搜索",
            "发现可下载资源",
            "提交到下载队列",
            "下载任务已装配完成",
            "已聚合",
            "聚合",
            "扫描结束",
            "扫描完成",
            "正在展开",
            "最终确认",
            "有效资源",
            "候选资源",
            "第 ",
            "页",
            "fetch video detail",
            "get video info",
            "get play url",
        )

        if any(status.startswith(prefix) for prefix in crawl_status_prefixes):
            return True

        if any(event_code.startswith(prefix) for prefix in crawl_status_prefixes):
            return True

        if action in crawl_actions:
            return True

        if action.startswith("api::") and not any(
            token in action
            for token in ("stream_audio", "stream_video", "download", "merge")
        ):
            return True

        if any(token in source for token in crawl_source_tokens):
            return True

        if any(token in message for token in crawl_message_tokens):
            return True

        if any(token in combined for token in ("GET_VIDEO_INFO", "GET_PLAY_URL", "CHECK_LOGIN", "ITEM_FOUND", "TASK_EMIT")):
            return True

        return False

    def _derive_scope_reason(self, item: dict[str, Any]) -> str:
        if self._is_performance_log(item):
            return "performance_token"

        if self._is_download_boundary_log(item):
            return "download_boundary"

        if self._is_system_config_log(item):
            return "system_config"

        if self._is_platform_root_crawl_log(item):
            return "platform_root_crawl"

        if self._is_crawl_pipeline_log(item):
            return "crawl_pipeline"

        facts = self._classification_facts(item)
        if facts["legacy_category"]:
            return f"legacy_{facts['legacy_category']}"

        return "fallback_system"

    def _derive_log_scope(self, item: dict[str, Any]) -> str:
        facts = self._classification_facts(item)

        raw_level = facts["raw_level"]
        source = facts["source_lower"]
        action = facts["action_lower"]
        status = facts["status_upper"]
        event_code = facts["event_code_upper"]
        combined = facts["combined_upper"]
        legacy_category = facts["legacy_category"]

        if raw_level in {"ERROR", "FATAL", "CRITICAL"}:
            return "error"

        hard_error_tokens = (
            "LOCAL_HLS_PROXY_ERROR",
            "PROXY_ERROR",
            "CONNECTION_RESET",
            "FATAL",
            "EXCEPTION",
            "TRACEBACK",
        )
        if any(token in combined for token in hard_error_tokens):
            return "error"

        if self._is_performance_log(item):
            return "performance"

        if source == "applicationcontroller":
            if status.startswith(("APP_CRAWL", "APP_ITEM_FOUND")) or event_code.startswith(
                ("APP_CRAWL", "APP_ITEM_FOUND")
            ):
                return "crawl"

            if status.startswith("APP_DL_") or event_code.startswith("APP_DL_"):
                return "download"

            if action in {"start_crawl", "item_found", "crawl_finished"}:
                return "crawl"

            if action in {"download_finished"}:
                return "download"

            if self._is_system_config_log(item):
                return "system"

            if status.startswith(("APP_INIT", "APP_READY", "APP_SCAN", "APP_DIR")) or event_code.startswith(
                ("APP_INIT", "APP_READY", "APP_SCAN", "APP_DIR")
            ):
                return "system"

            return "system"

        if self._is_download_boundary_log(item):
            return "download"

        if self._is_system_config_log(item):
            return "system"

        if self._is_platform_root_crawl_log(item):
            return "crawl"

        if self._is_crawl_pipeline_log(item):
            return "crawl"

        system_sources = (
            "gui",
            "mainwindow",
            "frontendstateservice",
            "uiupdatescheduler",
            "system",
        )
        system_status_prefixes = (
            "APP_INIT",
            "APP_READY",
            "APP_SCAN",
            "APP_DIR",
            "UI_",
            "FRONTEND_",
        )

        if any(token in source for token in system_sources):
            return "system"

        if status.startswith(system_status_prefixes) or event_code.startswith(system_status_prefixes):
            return "system"

        if legacy_category == "download":
            if self._is_download_boundary_log(item):
                return "download"
            if self._is_platform_root_crawl_log(item) or self._is_crawl_pipeline_log(item):
                return "crawl"
            return "system"

        if legacy_category == "crawl":
            if not self._is_download_boundary_log(item):
                return "crawl"
            return "download"

        if legacy_category == "performance":
            return "performance" if self._is_performance_log(item) else "system"

        if legacy_category == "error":
            return "error" if raw_level in {"ERROR", "FATAL", "CRITICAL"} else "system"

        if legacy_category == "system":
            return "system"

        return "system"

    def _derive_event_stage(self, item: dict[str, Any]) -> str:
        facts = self._classification_facts(item)
        result_type = self._derive_result_type(item)

        raw_level = facts["raw_level"]
        action = facts["action_lower"]
        combined = facts["combined_upper"]
        message = facts["message_lower"]

        if result_type == "error" or raw_level in {"ERROR", "FATAL", "CRITICAL"}:
            return "error"

        if self._is_performance_log(item):
            return "performance"

        if self._is_system_config_log(item):
            return "config"

        if "APP_INIT" in combined or action == "app_init":
            return "init"

        if "SCAN" in combined or "scan" in action or "扫描结束" in message or "扫描完成" in message:
            return "scan"

        if "CHECK_LOGIN" in combined or "check_login" in action or "登录状态" in message:
            return "login"

        if "最终确认" in message:
            return "confirm"

        if any(token in message for token in ("已聚合", "聚合", "有效资源", "候选资源")):
            return "aggregate"

        if any(token in message for token in ("正在展开", "展开")):
            return "expand"

        if "确认" in message:
            return "confirm"

        if "GET_VIDEO_INFO" in combined or "get_video_info" in action or "video detail" in message or "解析" in message:
            return "parse"

        if "GET_PLAY_URL" in combined or "get_play_url" in action or "播放流" in message or "获取" in message:
            return "fetch"

        if "STREAM_AUDIO" in combined or "STREAM_VIDEO" in combined or "流请求" in message:
            return "request"

        if "ITEM_FOUND" in combined or "item_found" in action or "发现可下载资源" in message:
            return "found"

        if "发现" in message and "页" in message:
            return "found"

        if "TASK_EMIT" in combined or "emit_download_task" in action or "提交到下载队列" in message:
            return "emit"

        if "QUEUE" in combined or "queue_task" in action or "进入队列" in message:
            return "queue"

        if "DISPATCH" in combined or "dispatch_task" in action or "分发" in message:
            return "dispatch"

        if "PREPARE" in combined or "prepare_download" in action or "准备下载" in message:
            return "prepare"

        if "START_DOWNLOAD" in combined or "DL_START" in combined or "下载任务开始" in message:
            return "download"

        if "MERGE" in combined or "FFMPEG" in combined or "合并" in message:
            return "merge"

        if "NORMALIZED" in combined or "normalize" in action or "修正扩展名" in message:
            return "normalize"

        if "RELEASE" in combined or "release_slot" in action or "槽位已释放" in message:
            return "release"

        if any(token in message for token in ("下载任务已进入队列", "进入队列", "已进入队列")):
            return "queue"

        if any(token in message for token in ("任务已从队列分发", "从队列分发", "分发到下载线程")):
            return "dispatch"

        if any(token in message for token in ("下载任务开始执行", "开始执行", "开始下载")):
            return "download"

        if any(token in message for token in ("准备下载", "准备下载 bilibili")):
            return "prepare"

        if any(token in message for token in ("下载完成", "下载任务完成")):
            return "finish"

        if any(token in message for token in ("下载并发槽位已释放", "槽位已释放")):
            return "release"

        if result_type == "success" or "FINISH" in combined or "完成" in message:
            return "finish"

        if "START" in combined or action.endswith("_start") or "启动" in message:
            return "start"

        return "step"

    @staticmethod
    def _stage_display_text(stage: str) -> str:
        return {
            "init": "初始化",
            "config": "配置",
            "scan": "扫描",
            "start": "启动",
            "login": "登录",
            "aggregate": "聚合",
            "expand": "展开",
            "confirm": "确认",
            "parse": "解析",
            "fetch": "获取",
            "request": "请求",
            "found": "发现",
            "emit": "提交",
            "queue": "入队",
            "dispatch": "分发",
            "prepare": "准备",
            "download": "下载",
            "merge": "合并",
            "normalize": "修正",
            "release": "释放",
            "finish": "完成",
            "performance": "性能",
            "error": "异常",
            "step": "步骤",
        }.get(stage, stage or "-")

    @staticmethod
    def _scope_display_text(scope: str) -> str:
        return {
            "system": "系统",
            "crawl": "采集",
            "download": "下载",
            "performance": "性能",
            "error": "异常",
        }.get(scope, scope or "-")

    def _decorate_log_item(self, item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        platform_id = self._resolve_item_platform_id(item)
        meta = self._platform_meta_by_id.get(platform_id) or _builtin_platform_metas().get(platform_id)
        if meta is None:
            if platform_id:
                meta = PlatformUiMeta(platform_id, platform_id)
            else:
                fallback_label = str(item.get("platform") or "未知")
                meta = PlatformUiMeta("", fallback_label)

        source = str(item.get("source") or "").strip()
        label = meta.label
        row["platform_id"] = platform_id or meta.id
        row["platform_label"] = label
        row["platform_icon_path"] = meta.icon_path
        row["platform_emoji"] = meta.emoji

        icon_file = _platform_icon_file_for_id(platform_id, meta)
        has_icon = bool(icon_file)

        if has_icon:
            row["source_display_icon_file"] = icon_file
            display_text = f"{label} · {source}" if source else label
        else:
            row.pop("source_display_icon_file", None)
            emoji = meta.emoji or ""
            prefix = f"{emoji} {label}".strip() if emoji else label
            display_text = f"{prefix} · {source}" if source else prefix

        row["source_display_text"] = display_text
        row["source_display"] = display_text
        row["source_display_full"] = display_text
        row["source_display_align"] = "center"

        result_type = self._derive_result_type(item)
        raw_level = self._normalized_raw_level(item)
        scope = self._derive_log_scope(item)
        stage = self._derive_event_stage(item)
        event_code = self._normalized_event_code(item)

        row["raw_level"] = raw_level
        row["result_type"] = result_type
        row["level_display"] = self._result_display_text(result_type, raw_level)
        row["level_display_align"] = "center"
        row["log_scope"] = scope
        row["event_stage"] = stage
        row["event_stage_display"] = self._stage_display_text(stage)
        row["status_code"] = self._normalized_status_code(item)
        row["event_code"] = event_code

        facts = self._classification_facts(item)
        row["_classification_source"] = facts["source"]
        row["_classification_action"] = facts["action"]
        row["_classification_status"] = facts["status"]
        row["_classification_legacy_category"] = facts["legacy_category"]
        row["_scope_reason"] = self._derive_scope_reason(item)
        return row

    def _resolve_item_platform_id(self, item: dict[str, Any]) -> str:
        explicit = str(item.get("platform_id") or "").strip().lower()
        if explicit and explicit not in {"", "all"}:
            if explicit in self._platform_meta_by_id or explicit in _builtin_platform_metas():
                return explicit

        source_id = str(item.get("source_id") or "").strip().lower()
        if source_id and (source_id in self._platform_meta_by_id or source_id in _builtin_platform_metas()):
            return source_id

        platform_text = str(item.get("platform") or "").strip()
        lowered = platform_text.lower()
        for meta in self._platform_options:
            if lowered == meta.id or lowered == meta.label.lower():
                return meta.id
            if any(lowered == alias.lower() for alias in meta.aliases):
                return meta.id

        source_text = " ".join(
            str(item.get(key) or "")
            for key in (
                "source",
                "action",
                "event",
                "event_type",
                "trace_id",
                "traceId",
                "message",
                "message_summary",
                "detail",
                "source_id",
                "platform_id",
                "plugin_name",
            )
        ).lower()
        facts = self._classification_facts(item)
        source_text = " ".join(
            [
                source_text,
                facts["source_lower"],
                facts["action_lower"],
                facts["detail_lower"],
            ]
        )
        for meta in self._platform_options:
            if meta.id in {"", "all"}:
                continue
            tokens = (meta.id, *meta.aliases)
            if any(token.lower() in source_text for token in tokens if token):
                return meta.id

        if platform_text in {"系统", "system"}:
            return "system"
        return ""

    def _format_platform_label(self, item: dict[str, Any]) -> str:
        platform_id = self._resolve_item_platform_id(item)
        meta = self._platform_meta_by_id.get(platform_id) or _builtin_platform_metas().get(platform_id)
        if meta is None:
            return str(item.get("platform") or "-")
        icon_file = _platform_icon_file_for_id(platform_id, meta)
        has_icon = bool(icon_file)
        if has_icon:
            return meta.label
        prefix = meta.emoji or ""
        if prefix:
            return f"{prefix} {meta.label}".strip()
        return meta.label

    def _matches_non_category_filters(self, item: dict[str, Any]) -> bool:
        level = (
            str(self.level_filter.currentData() or self.level_filter.currentText())
            if hasattr(self, "level_filter")
            else "全部"
        )
        if level != "全部":
            result_type = self._derive_result_type(item)
            display = self._result_display_text(result_type, self._normalized_raw_level(item))
            if display != level:
                return False

        if not self._matches_time_range(item):
            return False

        platform_id = self._selected_platform_id()
        if platform_id and not self._matches_platform(item, platform_id):
            return False

        trace_query = self.trace_filter.text().strip().lower() if hasattr(self, "trace_filter") else ""
        if trace_query and trace_query not in str(item.get("trace_id") or "").lower():
            return False

        keyword = self.keyword_filter.text().strip().lower() if hasattr(self, "keyword_filter") else ""
        if keyword and keyword not in self._searchable_text(item, include_detail=True).lower():
            return False

        return True

    def _matches_filters(self, item: dict[str, Any]) -> bool:
        if not self._matches_category(item):
            return False
        return self._matches_non_category_filters(item)

    def _sort_log_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed = list(enumerate(items))

        def sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[datetime, int]:
            index, item = pair
            dt = self._item_datetime(item)
            if dt is None:
                dt = datetime.min
            return dt, index

        return [item for _, item in sorted(indexed, key=sort_key, reverse=True)]

    def _extract_trace_id_from_item(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        candidates = [
            item.get("trace_id"),
            item.get("traceId"),
            item.get("trace"),
        ]

        detail = item.get("detail")
        if isinstance(detail, dict):
            candidates.extend(
                [
                    detail.get("trace_id"),
                    detail.get("traceId"),
                    detail.get("trace"),
                ]
            )

        payload = self._normalize_detail_payload(item)
        if isinstance(payload, dict):
            candidates.extend(
                [
                    payload.get("trace_id"),
                    payload.get("traceId"),
                    payload.get("trace"),
                ]
            )

        for value in candidates:
            text = str(value or "").strip()
            if text and text != "-":
                return text
        return ""

    def _current_or_first_trace_id(self) -> str:
        trace_id = self._extract_trace_id_from_item(self._current_log_item())
        if trace_id:
            return trace_id
        for item in self.items:
            trace_id = self._extract_trace_id_from_item(item)
            if trace_id:
                return trace_id
        for item in self._filtered_items:
            trace_id = self._extract_trace_id_from_item(item)
            if trace_id:
                return trace_id
        return ""

    @safe_slot
    def _copy_current_trace_id(self) -> None:
        trace_id = self._current_or_first_trace_id()
        if not trace_id:
            QMessageBox.information(self, "没有 Trace ID", "当前日志和筛选结果中没有可复制的 Trace ID。")
            return
        QApplication.clipboard().setText(trace_id)
        if hasattr(self, "copy_trace_button"):
            self._flash_button_text(self.copy_trace_button, "已复制")

    def _build_current_log_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "time": item.get("time"),
            "level": item.get("level"),
            "platform": self._format_platform_label(item),
            "source": item.get("source"),
            "trace_id": self._extract_trace_id_from_item(item) or item.get("trace_id") or "",
            "message": item.get("message") or item.get("message_summary") or "",
            "detail": self._normalize_detail_payload(item),
            "stack": item.get("stack") or "",
        }

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

    def _current_detail_payload(self) -> Any:
        item = self._current_log_item()
        return self._normalize_detail_payload(item) if item else {}

    def _sync_inspector_action_buttons(self, enabled: bool) -> None:
        for name in ("detail_copy_button", "detail_export_button", "json_copy_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)

    @staticmethod
    def _flash_button_text(button: QPushButton, text: str = "已复制", delay_ms: int = 900) -> None:
        old = button.text()
        button.setText(text)
        QTimer.singleShot(delay_ms, lambda: button.setText(old))

    @safe_slot
    def _copy_current_log_json(self) -> None:
        if not self._current_log_item():
            return
        QApplication.clipboard().setText(self._format_json_text(self._current_detail_payload()))
        self._flash_button_text(self.json_copy_button)

    @safe_slot
    def _copy_current_log_detail(self) -> None:
        item = self._current_log_item()
        if not item:
            return
        payload = self._build_current_log_payload(item)
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._flash_button_text(self.detail_copy_button)

    @safe_slot
    def _export_current_log_detail(self) -> None:
        item = self._current_log_item()
        if not item:
            QMessageBox.warning(self, "导出失败", "当前没有可导出的日志。")
            return
        payload = self._build_current_log_payload(item)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志详情",
            "log_detail.json",
            "JSON 文件 (*.json);;文本文件 (*.txt)",
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：{exc}")
            return
        QMessageBox.information(self, "导出成功", f"日志详情已导出到：{path}")

    def _matches_platform(self, item: dict[str, Any], platform_id: str) -> bool:
        if not platform_id or platform_id == "all":
            return True

        scope = self._derive_log_scope(item)

        if scope in {"system", "performance"}:
            return True

        resolved = self._resolve_item_platform_id(item)
        if resolved and resolved == platform_id:
            return True

        meta = self._platform_meta_by_id.get(platform_id) or _builtin_platform_metas().get(platform_id)
        tokens: set[str] = {platform_id.lower()}
        if meta is not None:
            tokens.add(meta.id.lower())
            tokens.add(meta.label.lower())
            tokens.update(alias.lower() for alias in meta.aliases)

        facts = self._classification_facts(item)
        text = " ".join(
            [
                facts["platform_lower"],
                facts["source_lower"],
                facts["action_lower"],
                facts["message_lower"],
                facts["detail_lower"],
                str(item.get("source_id") or "").lower(),
                str(item.get("platform_id") or "").lower(),
                str(item.get("plugin_name") or "").lower(),
                str(item.get("trace_id") or "").lower(),
                str(item.get("traceId") or "").lower(),
            ]
        )

        if any(token and token in text for token in tokens if len(token) > 1):
            return True

        return False

    def _matches_category(self, item: dict[str, Any]) -> bool:
        if self._category == "all":
            return True
        scope = self._derive_log_scope(item)
        return scope == self._category

    def _matches_time_range(self, item: dict[str, Any]) -> bool:
        label = (
            str(self.time_filter.currentData() or self.time_filter.currentText())
            if hasattr(self, "time_filter")
            else "全部"
        )
        minutes = {"近 30 分钟": 30, "近 1 小时": 60, "近 24 小时": 24 * 60}.get(label)
        if minutes is None:
            return True
        timestamp = self._item_datetime(item)
        if timestamp is None:
            return False
        return timestamp >= datetime.now() - timedelta(minutes=minutes)

    @staticmethod
    def _item_datetime(item: dict[str, Any]) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(str(item.get("time") or ""), fmt)
            except ValueError:
                continue
        return None

    def _searchable_text(self, item: dict[str, Any], *, include_detail: bool = False) -> str:
        facts = self._classification_facts(item)
        keys = [
            "platform",
            "source",
            "trace_id",
            "traceId",
            "level",
            "message_summary",
            "message",
            "status_code",
            "action",
            "event",
            "event_type",
            "category",
        ]
        values = [str(item.get(key) or "") for key in keys]
        values.extend(
            [
                facts["raw_level"],
                facts["source"],
                facts["action"],
                facts["status"],
                facts["event_code"],
                facts["platform"],
                facts["legacy_category"],
                self._derive_log_scope(item),
                self._derive_event_stage(item),
                self._derive_result_type(item),
            ]
        )
        if include_detail:
            values.extend([facts["detail_text"], str(item.get("stack") or "")])
        return " ".join(values)

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
        self.json_text.setHtml(self._format_json_html({}))
        QTimer.singleShot(0, self._resize_json_viewer_to_content)
        self.stack_text.clear()
        self.stack_section.setVisible(False)

    @staticmethod
    def _soft_wrap_text(text: str) -> str:
        value = str(text or "")
        for sep in ("\\", "/", "_", "-"):
            value = value.replace(sep, f"{sep}\u200b")
        return value

    @staticmethod
    def _strip_leading_emoji(text: str) -> str:
        return _LOG_EMOJI_PREFIX_RE.sub("", str(text or "").strip()).strip()

    @classmethod
    def _looks_like_path(cls, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if ":\\" in text or text.startswith("/") or text.startswith("\\\\"):
            return True
        return "\\" in text and len(text) >= 8

    @classmethod
    def _extract_message_payload(cls, message: str) -> dict[str, Any] | None:
        clean = cls._strip_leading_emoji(message)
        if ":" not in clean:
            return None
        before, after = clean.split(":", 1)
        before = before.strip()
        after = after.strip()
        if cls._looks_like_path(after):
            return {"description": before, "path": after}
        return None

    @classmethod
    def _refine_description_path(cls, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        description = str(result.get("description") or "").strip()
        if description:
            extracted = cls._extract_message_payload(description)
            if extracted:
                result["description"] = extracted["description"]
                result.setdefault("path", extracted["path"])
            else:
                result["description"] = cls._strip_leading_emoji(description)
        detail_text = str(result.get("detail") or "").strip()
        if detail_text and "description" not in result:
            extracted = cls._extract_message_payload(detail_text)
            if extracted:
                result.update(extracted)
            else:
                result["description"] = cls._strip_leading_emoji(detail_text)
        return result

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

        kv_height = 9 * 26
        kv_spacing = 8 * 6
        margins = 12 + 12
        message_title = 22
        section_height = kv_height + kv_spacing + message_title + frame_height + margins

        self.detail_summary_section.setMaximumHeight(min(480, max(340, section_height)))

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
            max_height = max(180, min(360, int(inspector_height * 0.42)))
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

    def _format_json_html(self, payload: Any) -> str:
        colors = theme_colors(self._resolve_theme_is_dark())
        text = self._format_json_text(payload)
        escaped = html.escape(text)
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
        }}
        </style>
        </head>
        <body><pre>{escaped}</pre></body>
        </html>
        """

    @staticmethod
    def _parse_structured_detail_text(detail: str) -> dict[str, Any] | None:
        text = str(detail or "").strip()
        if not text:
            return None

        result: dict[str, Any] = {}
        in_details = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("说明:"):
                result["description"] = LogCenterPage._strip_leading_emoji(line.split(":", 1)[1].strip())
                in_details = False
                continue
            if line.startswith("状态码:"):
                result["status_code"] = line.split(":", 1)[1].strip()
                in_details = False
                continue
            if line.rstrip(":") in {"详情", "详细信息"}:
                in_details = True
                continue

            bullet_match = re.match(r"^-\s*(.+)$", line)
            if bullet_match:
                payload = bullet_match.group(1).strip()
                if ":" in payload:
                    key, value = payload.split(":", 1)
                    result[key.strip()] = value.strip()
                continue

            if in_details and ":" in line:
                key, value = line.split(":", 1)
                result[key.strip().lstrip("- ")] = value.strip()
                continue

            if ":" in line:
                key, value = line.split(":", 1)
                normalized_key = key.strip()
                normalized_value = value.strip()
                if normalized_key == "说明":
                    result["description"] = LogCenterPage._strip_leading_emoji(normalized_value)
                elif normalized_key == "状态码":
                    result["status_code"] = normalized_value
                elif normalized_key:
                    result[normalized_key] = normalized_value

        return result or None

    def _normalize_detail_payload(self, item: dict[str, Any]) -> Any:
        detail = item.get("detail")
        payload: dict[str, Any] | list[Any] | None = None

        if detail is not None and detail != "":
            if isinstance(detail, dict):
                payload = dict(detail)
            elif isinstance(detail, list):
                payload = list(detail)
            else:
                text = str(detail).strip()
                if text:
                    try:
                        parsed = json.loads(text)
                        payload = parsed
                    except json.JSONDecodeError:
                        structured = self._parse_structured_detail_text(text)
                        payload = structured if structured else {"detail": text}

        if payload is None:
            payload = {}

        if isinstance(payload, dict):
            payload = self._refine_description_path(payload)
            message = str(item.get("message") or item.get("message_summary") or "").strip()
            extracted = self._extract_message_payload(message) if message else None
            if extracted:
                if not payload.get("description"):
                    payload["description"] = extracted["description"]
                payload.setdefault("path", extracted.get("path"))
            elif message and not payload.get("description"):
                payload["description"] = self._strip_leading_emoji(message)
            event = item.get("event") or item.get("event_type") or item.get("status_code")
            if event and "status_code" not in payload and "event" not in payload:
                payload["event"] = event
            status_code = self._normalized_status_code(item)
            if status_code and "status_code" not in payload:
                payload["status_code"] = status_code
            for key in ("platform", "source", "trace_id"):
                value = item.get(key)
                if value and key not in payload:
                    payload[key] = value
            payload = {key: value for key, value in payload.items() if value not in (None, "", [])}

        return payload or {}

    @staticmethod
    def _format_json_text(payload: Any) -> str:
        if payload in (None, ""):
            return "{}"
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _render_detail(self) -> None:
        current = self._current_log_row_item()
        if not current:
            self._clear_detail_panel()
            return
        row, item = current
        self._inspector_item_id = self._item_id(item, row)
        self._sync_inspector_action_buttons(True)

        self.detail_time_value.setText(str(item.get("time") or "-"))
        self.detail_source_value.setText(str(item.get("source") or "-"))
        self.detail_platform_value.setText(self._format_platform_label(item))
        trace_id = self._extract_trace_id_from_item(item)
        self.detail_trace_value.setText(trace_id if trace_id else "-")
        message = str(item.get("message") or item.get("message_summary") or "-")
        raw_message = str(item.get("message") or item.get("message_summary") or "")
        self.detail_message_value.setPlainText(message)
        self._configure_message_editor_wrap()
        self.detail_message_value.setToolTip(raw_message if raw_message else "")
        QTimer.singleShot(0, self._resize_detail_message_box)

        raw_level = item.get("raw_level") or self._normalized_raw_level(item)
        result_type = item.get("result_type") or self._derive_result_type(item)
        scope = item.get("log_scope") or self._derive_log_scope(item)
        stage = item.get("event_stage") or self._derive_event_stage(item)
        event_code = item.get("event_code") or self._normalized_event_code(item)

        self.detail_level_badge.setText(raw_level or "-")
        self._apply_level_badge_style(self._result_display_text(result_type, raw_level))

        self.detail_status_value.setText(self._result_nature_text(result_type))
        self.detail_scope_value.setText(self._scope_display_text(scope))
        self.detail_stage_value.setText(self._stage_display_text(stage))
        self.detail_status_code_value.setText(event_code or "-")
        self.detail_status_code_value.setToolTip(event_code or "")

        payload = self._normalize_detail_payload(item)
        self._last_json_text = self._format_json_text(payload)
        self.json_text.setHtml(self._format_json_html(payload))
        QTimer.singleShot(0, self._resize_json_viewer_to_content)

        stack = str(item.get("stack") or "").strip()
        has_stack = bool(stack and stack != "无")
        self.stack_section.setVisible(has_stack)
        if has_stack:
            self.stack_text.setPlainText(stack)

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
        return str(item.get("id") or f"{item.get('time', '')}|{item.get('trace_id', '')}|{row}")
