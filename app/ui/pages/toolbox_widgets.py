from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import ui_icon_path
from app.ui.components.settings_controls import SettingsComboBox, UiSwitch
from app.ui.pages.toolbox_models import (
    action_enabled,
    freeze_display,
    history_line,
    parameter_fields_and_values,
    phase_for,
    result_lines,
)
from app.utils.qt_runtime import load_qt_icon


_PHASE_TEXT = {
    "idle": "等待操作",
    "validating": "验证中",
    "ready": "准备就绪",
    "valid": "准备就绪",
    "starting": "正在启动",
    "running": "运行中",
    "cancelling": "正在取消",
    "success": "执行成功",
    "completed": "执行成功",
    "error": "执行失败",
    "failed": "执行失败",
    "cancelled": "已取消",
    "canceled": "已取消",
}


def set_button_icon(button: QPushButton, icon_file: str, size: int = 16) -> None:
    icon = load_qt_icon([ui_icon_path(icon_file)])
    if icon is not None:
        button.setIcon(icon)
        button.setIconSize(QSize(size, size))


class ToolParameterEditor(QWidget):
    """Reusable parameter form and lifecycle action surface for one tool."""

    validate_requested = pyqtSignal()
    start_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, translate: Callable[[object], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translate = translate
        self.editors: dict[str, QWidget] = {}
        self._tool_id = ""
        self._schema_signature: Any = None
        self._values_signature: Any = None
        self._validation_signature: Any = None
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ToolboxParameterScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.host = QWidget()
        self.form = QFormLayout(self.host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("MutedLabel")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("ToolboxValidateButton")
        set_button_icon(self.validate_button, "action_repair.png")
        self.validate_button.clicked.connect(self.validate_requested)
        actions.addWidget(self.validate_button)
        actions.addStretch(1)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("StopTaskBtn")
        set_button_icon(self.cancel_button, "action_stop.png")
        self.cancel_button.clicked.connect(self.cancel_requested)
        actions.addWidget(self.cancel_button)
        self.start_button = QPushButton()
        self.start_button.setObjectName("PrimaryBtn")
        set_button_icon(self.start_button, "action_play.png")
        self.start_button.clicked.connect(self.start_requested)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        self.set_language()

    def set_language(self) -> None:
        self.title.setText(self._translate("工具参数"))
        self.validate_button.setText(self._translate("验证参数"))
        self.start_button.setText(self._translate("开始"))
        self.cancel_button.setText(self._translate("取消"))
        self._schema_signature = None

    def render(
        self,
        tool_id: str,
        item: Mapping[str, Any],
        projection: Mapping[str, Any],
    ) -> None:
        fields, values = parameter_fields_and_values(item, projection)
        self.set_form(tool_id, fields, values)
        self.render_lifecycle(projection, bool(tool_id))

    def set_form(self, tool_id: str, fields: Sequence[Mapping[str, Any]], values: Mapping[str, Any]) -> None:
        schema_signature = freeze_display(fields)
        values_signature = freeze_display(values)
        if self._tool_id == tool_id and self._schema_signature == schema_signature and self._values_signature == values_signature:
            return
        self._clear_form()
        self._tool_id = tool_id
        self._schema_signature = schema_signature
        self._values_signature = values_signature
        self._dirty = False
        if not fields:
            empty = QLabel(self._translate("暂无可配置参数"))
            empty.setObjectName("MutedLabel")
            self.form.addRow(empty)
            return
        for field in fields:
            field_id = str(field.get("id") or field.get("name") or "")
            if not field_id:
                continue
            editor = build_parameter_editor(field, values.get(field_id, field.get("value", field.get("default"))), self._translate, self._on_changed)
            self.editors[field_id] = editor
            label_text = self._translate(field.get("label") or field.get("title") or field_id)
            label = QLabel(f"{label_text} *" if bool(field.get("required")) else label_text)
            label.setToolTip(self._translate(field.get("help_text") or field.get("description") or ""))
            editor.setToolTip(label.toolTip())
            self.form.addRow(label, editor)

    def render_lifecycle(self, projection: Mapping[str, Any], has_tool: bool) -> None:
        validation = projection.get("validation") if isinstance(projection.get("validation"), Mapping) else {}
        validation_signature = freeze_display(
            {
                "validation": validation,
                "message": projection.get("validation_message"),
            }
        )
        if validation_signature != self._validation_signature:
            self._validation_signature = validation_signature
            self._dirty = False
        if not self._dirty:
            self.validation_label.setText(self._translate(validation.get("message") or projection.get("validation_message") or ""))
        phase = phase_for(projection)
        busy = phase in {"validating", "starting", "running", "cancelling"}
        validation_state = str(validation.get("state") or "").lower()
        defaults = {
            "tool_validate": has_tool and not busy,
            "tool_start": has_tool and not busy and validation_state not in {"invalid", "error"},
            "tool_cancel": has_tool and phase in {"starting", "running"},
        }
        self.validate_button.setEnabled(action_enabled(projection, "tool_validate", defaults["tool_validate"]))
        self.start_button.setEnabled(action_enabled(projection, "tool_start", defaults["tool_start"]))
        self.cancel_button.setEnabled(action_enabled(projection, "tool_cancel", defaults["tool_cancel"]))

    def values(self) -> dict[str, Any]:
        return parameter_values(self.editors)

    def _clear_form(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.editors.clear()

    def _on_changed(self, *_args: object) -> None:
        self._dirty = True
        self.validation_label.setText(self._translate("参数已更改，请重新验证"))


class ToolExecutionPanel(QWidget):
    """Reusable execution progress and result surface."""

    open_result_requested = pyqtSignal()

    def __init__(self, translate: Callable[[object], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translate = translate
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)
        self.state_label = QLabel()
        self.state_label.setObjectName("MutedLabel")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ToolboxProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("MutedLabel")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.result_view = QTextEdit()
        self.result_view.setObjectName("ToolboxResultView")
        self.result_view.setReadOnly(True)
        layout.addWidget(self.result_view, 1)
        self.open_result_button = QPushButton()
        self.open_result_button.setObjectName("ToolboxOpenResultButton")
        set_button_icon(self.open_result_button, "action_open_directory.png")
        self.open_result_button.clicked.connect(self.open_result_requested)
        layout.addWidget(self.open_result_button, 0, Qt.AlignmentFlag.AlignRight)
        self.set_language()

    def set_language(self) -> None:
        self.title.setText(self._translate("执行状态"))
        self.open_result_button.setText(self._translate("打开结果"))

    def render(self, projection: Mapping[str, Any], has_tool: bool) -> None:
        phase = phase_for(projection)
        self.state_label.setText(self._translate(projection.get("status_text") or _PHASE_TEXT.get(phase, "等待操作")))
        progress = projection.get("progress")
        visible = False
        text = ""
        if isinstance(progress, Mapping):
            text = str(progress.get("text") or progress.get("label") or "")
            if bool(progress.get("indeterminate")):
                self.progress_bar.setRange(0, 0)
                visible = True
            elif "value" in progress or "percent" in progress:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(_progress_value(progress.get("value", progress.get("percent"))))
                visible = True
        elif progress is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(_progress_value(progress))
            visible = True
        elif phase in {"starting", "running", "cancelling"}:
            self.progress_bar.setRange(0, 0)
            visible = True
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.progress_bar.setVisible(visible)
        self.progress_label.setText(self._translate(text))
        self.progress_label.setVisible(bool(text))
        lines = result_lines(projection.get("result"), self._translate)
        self.result_view.setPlainText("\n".join(lines) if lines else self._translate("暂无结果"))
        default = has_tool and bool(projection.get("result")) and phase in {"success", "completed"}
        self.open_result_button.setEnabled(action_enabled(projection, "tool_open_result", default))


class ToolHistoryPanel(QWidget):
    """Reusable display-only history surface and clear action."""

    clear_requested = pyqtSignal()

    def __init__(self, translate: Callable[[object], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translate = translate
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)
        self.view = QTextEdit()
        self.view.setObjectName("ToolboxHistoryView")
        self.view.setReadOnly(True)
        layout.addWidget(self.view, 1)
        self.clear_button = QPushButton()
        self.clear_button.setObjectName("ToolboxClearHistoryButton")
        set_button_icon(self.clear_button, "action_clear-all.png")
        self.clear_button.clicked.connect(self.clear_requested)
        layout.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignRight)
        self.set_language()

    def set_language(self) -> None:
        self.title.setText(self._translate("最近使用"))
        self.clear_button.setText(self._translate("清空历史"))

    def render(self, items: Sequence[Mapping[str, Any]], projection: Mapping[str, Any], has_tool: bool) -> None:
        if items:
            self.view.setPlainText("\n".join(line for line in (history_line(item, self._translate) for item in items) if line))
        else:
            self.view.setPlainText(self._translate("暂无最近使用记录"))
        self.clear_button.setEnabled(action_enabled(projection, "tool_clear_history", has_tool and bool(items)))


def build_parameter_editor(
    field: Mapping[str, Any], value: Any, translate: Callable[[object], str], on_change: Callable[..., None]
) -> QWidget:
    field_type = str(field.get("type") or field.get("control") or "text").strip().lower()
    if field_type in {"choice", "select", "enum"}:
        editor = SettingsComboBox()
        for option in field.get("options") or ():
            option_value = option.get("value", option.get("id", "")) if isinstance(option, Mapping) else option
            option_label = option.get("label", option.get("title", option_value)) if isinstance(option, Mapping) else option
            editor.addItem(translate(option_label), option_value)
        index = editor.findData(value)
        if index < 0 and value is not None:
            index = editor.findText(str(value))
        if index >= 0:
            editor.setCurrentIndex(index)
        editor.currentIndexChanged.connect(on_change)
    elif field_type in {"boolean", "bool", "switch", "toggle"}:
        editor = UiSwitch()
        editor.setChecked(bool(value))
        editor.toggled.connect(on_change)
    elif field_type in {"integer", "int", "spin"}:
        editor = QSpinBox()
        editor.setRange(_int_value(field.get("minimum"), -1_000_000), _int_value(field.get("maximum"), 1_000_000))
        editor.setValue(_int_value(value, _int_value(field.get("default"), 0)))
        editor.valueChanged.connect(on_change)
    elif field_type in {"number", "float", "double"}:
        editor = QDoubleSpinBox()
        editor.setRange(_float_value(field.get("minimum"), -1_000_000.0), _float_value(field.get("maximum"), 1_000_000.0))
        editor.setDecimals(max(0, min(8, _int_value(field.get("decimals"), 2))))
        editor.setValue(_float_value(value, _float_value(field.get("default"), 0.0)))
        editor.valueChanged.connect(on_change)
    elif field_type in {"multiline", "textarea", "text_area"}:
        editor = QTextEdit()
        editor.setPlainText(str(value or ""))
        editor.setMinimumHeight(72)
        editor.setMaximumHeight(104)
        editor.textChanged.connect(on_change)
    else:
        editor = QLineEdit(str(value or ""))
        editor.setPlaceholderText(translate(field.get("placeholder") or ""))
        if bool(field.get("secret")) or field_type in {"password", "secret"}:
            editor.setEchoMode(QLineEdit.EchoMode.Password)
        editor.textChanged.connect(on_change)
    editor.setObjectName("ToolboxParameterEditor")
    editor.setEnabled(bool(field.get("enabled", True)))
    return editor


def parameter_values(editors: Mapping[str, QWidget]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field_id, editor in editors.items():
        if isinstance(editor, QComboBox):
            value = editor.currentData()
            values[field_id] = editor.currentText() if value is None else value
        elif isinstance(editor, QCheckBox):
            values[field_id] = editor.isChecked()
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            values[field_id] = editor.value()
        elif isinstance(editor, QTextEdit):
            values[field_id] = editor.toPlainText()
        elif isinstance(editor, QLineEdit):
            values[field_id] = editor.text()
    return values


def _progress_value(value: Any) -> int:
    return max(0, min(100, _int_value(value, 0)))


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
