from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextOption
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.smart_wrap_label import SmartWrapLabel


@dataclass
class LogInspectorRefs:
    header: QWidget | None = None
    detail_copy_button: QPushButton | None = None
    detail_export_button: QPushButton | None = None
    detail_summary_section: QFrame | None = None
    detail_time_value: QLabel | None = None
    detail_level_badge: QLabel | None = None
    detail_status_value: QLabel | None = None
    detail_scope_value: QLabel | None = None
    detail_stage_value: QLabel | None = None
    detail_status_code_value: QLabel | None = None
    detail_source_value: QLabel | None = None
    detail_platform_value: QLabel | None = None
    detail_trace_value: QLabel | None = None
    detail_message_frame: QFrame | None = None
    detail_message_value: QPlainTextEdit | None = None
    json_section: QFrame | None = None
    json_copy_button: QPushButton | None = None
    json_text: QTextBrowser | None = None
    stack_section: QFrame | None = None
    stack_text: QPlainTextEdit | None = None


def _action_button(label: str) -> QPushButton:
    button = QPushButton(label)
    button.setObjectName("LogInspectorActionButton")
    button.setFixedHeight(26)
    button.setMinimumWidth(52)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def build_log_kv_row(key: str, value_widget: QWidget) -> QWidget:
    row = QWidget()
    row.setObjectName("LogKvRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    key_label = QLabel(key)
    key_label.setObjectName("LogDetailKey")
    key_label.setFixedWidth(56)
    key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    value_widget.setMinimumWidth(0)
    value_cell = QWidget(row)
    value_cell.setObjectName("LogKvValueCell")
    value_cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    value_layout = QHBoxLayout(value_cell)
    value_layout.setContentsMargins(0, 0, 0, 0)
    value_layout.setSpacing(0)
    if str(value_widget.objectName()).startswith("LogLevelBadge"):
        value_layout.addWidget(value_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value_layout.addStretch(1)
    else:
        value_layout.addWidget(value_widget, 1)
    layout.addWidget(key_label)
    layout.addWidget(value_cell, 1)
    row.setMinimumHeight(24)
    return row


def _detail_value_label() -> SmartWrapLabel:
    label = SmartWrapLabel("-", compact=True)
    label.setObjectName("LogDetailValue")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return label


def _plain_detail_value_label() -> QLabel:
    label = QLabel("-")
    label.setObjectName("LogDetailValue")
    label.setWordWrap(False)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    label.setMinimumWidth(0)
    label.setProperty("i18nSkipText", "true")
    return label


def build_log_inspector_header(
    *,
    copy_detail: Callable[[], None],
    export_detail: Callable[[], None],
) -> tuple[QWidget, LogInspectorRefs]:
    header = QWidget()
    header.setObjectName("LogInspectorHeader")
    header.setFixedHeight(48)
    layout = QHBoxLayout(header)
    layout.setContentsMargins(12, 10, 12, 10)

    title = QLabel("日志详情")
    title.setObjectName("LogInspectorTitle")
    layout.addWidget(title)
    layout.addStretch(1)

    detail_copy_button = _action_button("复制")
    detail_export_button = _action_button("导出")
    detail_copy_button.clicked.connect(lambda _checked=False: copy_detail())
    detail_export_button.clicked.connect(lambda _checked=False: export_detail())
    layout.addWidget(detail_copy_button)
    layout.addWidget(detail_export_button)

    return header, LogInspectorRefs(
        header=header,
        detail_copy_button=detail_copy_button,
        detail_export_button=detail_export_button,
    )


def build_log_detail_summary_section(
    style_panel: Callable[[QFrame], QFrame],
) -> tuple[QFrame, LogInspectorRefs]:
    section = style_panel(QFrame())
    section.setObjectName("LogDetailSummarySection")
    section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    section.setMaximumHeight(420)
    section.setMinimumWidth(0)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)

    detail_time_value = _plain_detail_value_label()
    detail_level_badge = QLabel("-")
    detail_level_badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    detail_status_value = _plain_detail_value_label()
    detail_scope_value = _plain_detail_value_label()
    detail_stage_value = _plain_detail_value_label()
    detail_status_code_value = _detail_value_label()
    detail_source_value = _plain_detail_value_label()
    detail_platform_value = _plain_detail_value_label()
    detail_trace_value = _detail_value_label()

    detail_message_frame = QFrame()
    detail_message_frame.setObjectName("LogMessageBoxFrame")
    detail_message_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    detail_message_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    detail_message_frame.setMinimumHeight(56)
    detail_message_frame.setMaximumHeight(190)
    message_frame_layout = QVBoxLayout(detail_message_frame)
    message_frame_layout.setContentsMargins(12, 10, 12, 10)
    message_frame_layout.setSpacing(0)

    detail_message_value = QPlainTextEdit()
    detail_message_value.setObjectName("LogMessageText")
    detail_message_value.setReadOnly(True)
    detail_message_value.setFrameShape(QFrame.Shape.NoFrame)
    detail_message_value.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    detail_message_value.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    detail_message_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    detail_message_value.setMinimumWidth(0)
    detail_message_value.setMinimumHeight(36)
    detail_message_value.setPlainText("-")
    detail_message_value.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    message_frame_layout.addWidget(detail_message_value)


    detail_level_badge.setObjectName("LogLevelBadgeInfo")
    detail_level_badge.setFixedHeight(22)
    detail_level_badge.setMinimumWidth(46)
    detail_level_badge.setMaximumWidth(76)
    detail_level_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(build_log_kv_row("时间", detail_time_value))
    layout.addWidget(build_log_kv_row("级别", detail_level_badge))
    layout.addWidget(build_log_kv_row("性质", detail_status_value))
    layout.addWidget(build_log_kv_row("范围", detail_scope_value))
    layout.addWidget(build_log_kv_row("阶段", detail_stage_value))
    layout.addWidget(build_log_kv_row("事件码", detail_status_code_value))
    layout.addWidget(build_log_kv_row("来源", detail_source_value))
    layout.addWidget(build_log_kv_row("平台", detail_platform_value))
    layout.addWidget(build_log_kv_row("Trace ID", detail_trace_value))

    message_title = QLabel("消息")
    message_title.setObjectName("LogMessageTitle")
    layout.addWidget(message_title)
    layout.addWidget(detail_message_frame)

    return section, LogInspectorRefs(
        detail_summary_section=section,
        detail_time_value=detail_time_value,
        detail_level_badge=detail_level_badge,
        detail_status_value=detail_status_value,
        detail_scope_value=detail_scope_value,
        detail_stage_value=detail_stage_value,
        detail_status_code_value=detail_status_code_value,
        detail_source_value=detail_source_value,
        detail_platform_value=detail_platform_value,
        detail_trace_value=detail_trace_value,
        detail_message_frame=detail_message_frame,
        detail_message_value=detail_message_value,
    )


def build_log_json_section(
    *,
    style_panel: Callable[[QFrame], QFrame],
    copy_json: Callable[[], None],
) -> tuple[QFrame, LogInspectorRefs]:
    section = style_panel(QFrame())
    section.setObjectName("LogJsonSection")
    section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    section.setMaximumHeight(520)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)

    header_widget = QWidget()
    header_widget.setObjectName("LogJsonSectionHeader")
    header_widget.setFixedHeight(32)
    header_widget.setMinimumWidth(0)
    header = QHBoxLayout(header_widget)
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)
    title = QLabel("详细信息")
    title.setObjectName("LogSectionTitle")
    title.setMinimumWidth(0)
    title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    header.addWidget(title, 1)
    json_copy_button = _action_button("复制")
    json_copy_button.clicked.connect(lambda _checked=False: copy_json())
    header.addWidget(json_copy_button, 0, Qt.AlignmentFlag.AlignRight)
    layout.addWidget(header_widget)

    json_text = QTextBrowser()
    json_text.setObjectName("LogJsonViewer")
    json_text.setOpenExternalLinks(False)
    json_text.setFrameShape(QFrame.Shape.NoFrame)
    json_text.setReadOnly(True)
    json_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    json_text.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
    json_text.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    json_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    json_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    json_text.setContentsMargins(0, 0, 0, 0)
    json_text.document().setDocumentMargin(0)
    layout.addWidget(json_text, 0)

    return section, LogInspectorRefs(
        json_section=section,
        json_copy_button=json_copy_button,
        json_text=json_text,
    )


def build_log_stack_section(
    style_panel: Callable[[QFrame], QFrame],
) -> tuple[QFrame, LogInspectorRefs]:
    section = style_panel(QFrame())
    section.setObjectName("LogStackSection")
    section.setMinimumHeight(160)
    section.setMaximumHeight(220)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)

    title = QLabel("堆栈追踪")
    title.setObjectName("LogSectionTitle")
    layout.addWidget(title)

    stack_text = QPlainTextEdit()
    stack_text.setObjectName("LogStackText")
    stack_text.setReadOnly(True)
    stack_text.setFrameShape(QFrame.Shape.NoFrame)
    stack_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    mono = QFont("Cascadia Mono")
    mono.setStyleHint(QFont.StyleHint.Monospace)
    mono.setPointSize(10)
    stack_text.setFont(mono)
    layout.addWidget(stack_text, 1)

    section.setVisible(False)
    return section, LogInspectorRefs(stack_section=section, stack_text=stack_text)
