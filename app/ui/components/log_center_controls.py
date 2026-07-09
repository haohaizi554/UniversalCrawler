from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app.ui.components.combo_popup import (
    ThemedComboBox,
    fit_combo_width_to_contents,
    polish_combo_popup,
)


@dataclass
class LogActionBarRefs:
    copy_trace_button: QPushButton | None = None
    action_buttons: dict[str, QPushButton] = field(default_factory=dict)


@dataclass
class LogTableFooterRefs:
    footer_stats: QLabel
    page_indicator: QLabel
    page_size_combo: ThemedComboBox
    prev_page_button: QPushButton
    next_page_button: QPushButton


def build_log_action_bar(
    *,
    emit_action: Callable[[str], None],
    copy_trace_id: Callable[[], None],
) -> tuple[QWidget, LogActionBarRefs]:
    row = QWidget()
    row.setObjectName("LogActionBar")
    row.setFixedHeight(36)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    copy_trace_button: QPushButton | None = None
    action_buttons: dict[str, QPushButton] = {}
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
        button.setProperty("_i18n_source_text", label)
        button.setProperty("_i18n_source_tooltip", tooltip)
        button.setProperty("i18nSkipText", "true")
        button.setProperty("logActionMinWidth", width)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(30)
        button.setFixedWidth(width)
        if operation == "copy_trace_id":
            copy_trace_button = button
            button.clicked.connect(lambda _checked=False: copy_trace_id())
        else:
            button.clicked.connect(lambda _checked=False, key=operation: emit_action(key))
        action_buttons[operation] = button
        layout.addWidget(button)

    layout.addStretch(1)
    return row, LogActionBarRefs(copy_trace_button=copy_trace_button, action_buttons=action_buttons)


def build_log_table_footer(
    *,
    page_size_changed: Callable[[], None],
    go_prev_page: Callable[[], None],
    go_next_page: Callable[[], None],
) -> tuple[QWidget, LogTableFooterRefs]:
    row = QWidget()
    row.setObjectName("LogTableFooter")
    row.setFixedHeight(48)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(14, 6, 14, 6)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    footer_stats = QLabel("共 0 条 / 匹配 0 条 / 当前显示 0 条")
    footer_stats.setObjectName("LogFooterStats")
    footer_stats.setMinimumWidth(0)
    footer_stats.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout.addWidget(footer_stats, 1)

    page_indicator = QLabel("第 1 / 1 页")
    page_indicator.setObjectName("LogPageIndicator")
    page_indicator.setFixedWidth(92)
    page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
    page_indicator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    layout.addWidget(page_indicator, 0)

    page_size_combo = ThemedComboBox(row_height=32)
    page_size_combo.setObjectName("LogFooterPageSize")
    for label, value in [("20 条/页", 20), ("50 条/页", 50), ("100 条/页", 100), ("全部", 0)]:
        page_size_combo.addItem(label, value)
    page_size_combo.setFixedHeight(30)
    page_size_combo.setProperty("contentWidthPadding", 16)
    page_size_combo.setProperty("contentMinWidth", 88)
    page_size_combo.setProperty("contentMaxWidth", 168)
    fit_combo_width_to_contents(
        page_size_combo,
        min_width=88,
        max_width=168,
        horizontal_padding=16,
    )
    polish_combo_popup(page_size_combo, visible_rows=page_size_combo.count(), row_height=32)
    layout.addWidget(page_size_combo)

    prev_page_button = QPushButton("上一页")
    prev_page_button.setObjectName("LogFooterPageButton")
    prev_page_button.setFixedHeight(30)
    prev_page_button.setMinimumWidth(112)
    next_page_button = QPushButton("下一页")
    next_page_button.setObjectName("LogFooterPageButton")
    next_page_button.setFixedHeight(30)
    next_page_button.setMinimumWidth(100)
    layout.addWidget(prev_page_button)
    layout.addWidget(next_page_button)

    page_size_combo.currentIndexChanged.connect(lambda *_args: page_size_changed())
    prev_page_button.clicked.connect(lambda _checked=False: go_prev_page())
    next_page_button.clicked.connect(lambda _checked=False: go_next_page())

    return row, LogTableFooterRefs(
        footer_stats=footer_stats,
        page_indicator=page_indicator,
        page_size_combo=page_size_combo,
        prev_page_button=prev_page_button,
        next_page_button=next_page_button,
    )
