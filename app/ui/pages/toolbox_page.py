from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.icon_registry import ui_icon_path
from app.ui.components.settings_controls import SettingsComboBox, UiSwitch
from app.ui.pages.common import PageFrame
from app.utils.qt_runtime import load_qt_icon
from shared.localization import normalize_language, tr


_LOCAL_TEXT = {
    "en-US": {
        "选择工具": "Choose tool",
        "工具工作台": "Tool workspace",
        "参数": "Parameters",
        "结果": "Result",
        "历史": "History",
        "工具参数": "Tool parameters",
        "暂无可配置参数": "No configurable parameters",
        "验证参数": "Validate",
        "开始": "Start",
        "取消": "Cancel",
        "执行状态": "Execution status",
        "等待操作": "Waiting",
        "参数已更改，请重新验证": "Parameters changed; validate again",
        "暂无结果": "No result",
        "打开结果": "Open result",
        "清空历史": "Clear history",
        "验证中": "Validating",
        "准备就绪": "Ready",
        "正在启动": "Starting",
        "运行中": "Running",
        "正在取消": "Cancelling",
        "执行成功": "Succeeded",
        "执行失败": "Failed",
        "已取消": "Cancelled",
    },
    "zh-TW": {
        "选择工具": "選擇工具",
        "工具工作台": "工具工作臺",
        "参数": "參數",
        "结果": "結果",
        "历史": "歷史",
        "工具参数": "工具參數",
        "暂无可配置参数": "暫無可設定參數",
        "验证参数": "驗證參數",
        "开始": "開始",
        "取消": "取消",
        "执行状态": "執行狀態",
        "等待操作": "等待操作",
        "参数已更改，请重新验证": "參數已變更，請重新驗證",
        "暂无结果": "暫無結果",
        "打开结果": "開啟結果",
        "清空历史": "清空歷史",
        "验证中": "驗證中",
        "准备就绪": "準備就緒",
        "正在启动": "正在啟動",
        "运行中": "執行中",
        "正在取消": "正在取消",
        "执行成功": "執行成功",
        "执行失败": "執行失敗",
        "已取消": "已取消",
    },
}

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

_DISPLAY_PROJECTION_KEYS = (
    "toolbox_display_projection",
    "toolbox_projection",
    "toolbox_display",
)
_DISPLAY_BATCH_KEYS = ("toolbox_display_batch", "toolbox_projection_batch", "toolbox_batch")


class ToolboxPage(PageFrame):
    """Tool catalog and lifecycle view driven only by display projections."""

    tool_requested = pyqtSignal(str)
    action_requested = pyqtSignal(str, dict)

    def __init__(self) -> None:
        super().__init__("工具箱", "高效实用的辅助工具，提升工作效率", use_island=True)
        self.items: list[dict[str, Any]] = []
        self.recent_items: list[dict[str, Any]] = []
        self.current_tool_id = ""
        self._tool_buttons: dict[str, QToolButton] = {}
        self._display_projections: dict[str, dict[str, Any]] = {}
        self.parameter_editors: dict[str, QWidget] = {}
        self._form_tool_id = ""
        self._form_schema_signature: Any = None
        self._form_values_signature: Any = None
        self._form_dirty = False
        self._language = "zh-CN"

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        selector = QWidget()
        selector_layout = QVBoxLayout(selector)
        selector_layout.setContentsMargins(0, 0, 8, 0)
        selector_layout.setSpacing(8)
        self.selector_title = QLabel("选择工具")
        self.selector_title.setObjectName("SectionTitle")
        selector_layout.addWidget(self.selector_title)

        self.tool_scroll = QScrollArea()
        self.tool_scroll.setObjectName("ToolboxCatalogScroll")
        self.tool_scroll.setWidgetResizable(True)
        self.tool_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tool_scroll.setWidget(self.grid_host)
        selector_layout.addWidget(self.tool_scroll, 1)
        splitter.addWidget(selector)

        self.detail = QWidget()
        self.detail.setMinimumWidth(390)
        self.detail.setMaximumWidth(560)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(8)
        self.detail_title = QLabel("工具工作台")
        self.detail_title.setObjectName("SectionTitle")
        detail_layout.addWidget(self.detail_title)

        self.detail_text = QTextEdit()
        self.detail_text.setObjectName("ToolboxOverview")
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(126)
        detail_layout.addWidget(self.detail_text)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ToolboxWorkspaceTabs")
        self.tabs.addTab(self._build_parameter_tab(), "参数")
        self.tabs.addTab(self._build_result_tab(), "结果")
        self.tabs.addTab(self._build_history_tab(), "历史")
        detail_layout.addWidget(self.tabs, 1)

        # Kept as a non-visible compatibility target for integrations that still
        # address the former single "Open tool" button directly.
        self.open_button = QPushButton("打开工具", self.detail)
        self.open_button.setObjectName("ToolboxLegacyOpenButton")
        self.open_button.clicked.connect(self._emit_current_tool)
        self.open_button.hide()

        splitter.addWidget(self.detail)
        splitter.setSizes([690, 470])
        self.root_layout.addWidget(splitter, 1)
        self._render_workspace()

    @property
    def tool_action_requested(self):
        """Compatibility alias for callers that use a page-specific signal name."""

        return self.action_requested

    def _build_parameter_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        self.parameter_title = QLabel("工具参数")
        self.parameter_title.setObjectName("SectionTitle")
        layout.addWidget(self.parameter_title)

        self.form_scroll = QScrollArea()
        self.form_scroll.setObjectName("ToolboxParameterScroll")
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.form_host = QWidget()
        self.parameter_form = QFormLayout(self.form_host)
        self.parameter_form.setContentsMargins(0, 0, 0, 0)
        self.parameter_form.setHorizontalSpacing(12)
        self.parameter_form.setVerticalSpacing(8)
        self.parameter_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form_scroll.setWidget(self.form_host)
        layout.addWidget(self.form_scroll, 1)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("MutedLabel")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ToolboxProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("MutedLabel")
        self.progress_label.setWordWrap(True)
        self.progress_label.hide()
        layout.addWidget(self.progress_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.validate_button = QPushButton("验证参数")
        self.validate_button.setObjectName("ToolboxValidateButton")
        self._set_button_icon(self.validate_button, "action_repair.png")
        self.validate_button.clicked.connect(lambda: self._emit_action("tool_validate"))
        actions.addWidget(self.validate_button)
        actions.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("StopTaskBtn")
        self._set_button_icon(self.cancel_button, "action_stop.png")
        self.cancel_button.clicked.connect(lambda: self._emit_action("tool_cancel"))
        actions.addWidget(self.cancel_button)
        self.start_button = QPushButton("开始")
        self.start_button.setObjectName("PrimaryBtn")
        self._set_button_icon(self.start_button, "action_play.png")
        self.start_button.clicked.connect(self._emit_start)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        return tab

    def _build_result_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        self.result_title = QLabel("执行状态")
        self.result_title.setObjectName("SectionTitle")
        layout.addWidget(self.result_title)
        self.state_label = QLabel("等待操作")
        self.state_label.setObjectName("MutedLabel")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.result_view = QTextEdit()
        self.result_view.setObjectName("ToolboxResultView")
        self.result_view.setReadOnly(True)
        self.result_view.setPlainText("暂无结果")
        layout.addWidget(self.result_view, 1)
        self.open_result_button = QPushButton("打开结果")
        self.open_result_button.setObjectName("ToolboxOpenResultButton")
        self._set_button_icon(self.open_result_button, "action_open_directory.png")
        self.open_result_button.clicked.connect(lambda: self._emit_action("tool_open_result"))
        layout.addWidget(self.open_result_button, 0, Qt.AlignmentFlag.AlignRight)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)
        self.recent_title = QLabel("最近使用")
        self.recent_title.setObjectName("SectionTitle")
        layout.addWidget(self.recent_title)
        self.recent = QTextEdit()
        self.recent.setObjectName("ToolboxHistoryView")
        self.recent.setReadOnly(True)
        layout.addWidget(self.recent, 1)
        self.clear_history_button = QPushButton("清空历史")
        self.clear_history_button.setObjectName("ToolboxClearHistoryButton")
        self._set_button_icon(self.clear_history_button, "action_clear-all.png")
        self.clear_history_button.clicked.connect(lambda: self._emit_action("tool_clear_history"))
        layout.addWidget(self.clear_history_button, 0, Qt.AlignmentFlag.AlignRight)
        return tab

    @staticmethod
    def _set_button_icon(button: QPushButton, icon_file: str) -> None:
        icon = load_qt_icon([ui_icon_path(icon_file)])
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.title_label.setText(self._t("工具箱"))
        self.subtitle_label.setText(self._t("高效实用的辅助工具，提升工作效率"))
        self.selector_title.setText(self._t("选择工具"))
        self.detail_title.setText(self._t("工具工作台"))
        self.parameter_title.setText(self._t("工具参数"))
        self.result_title.setText(self._t("执行状态"))
        self.recent_title.setText(self._t("最近使用"))
        self.tabs.setTabText(0, self._t("参数"))
        self.tabs.setTabText(1, self._t("结果"))
        self.tabs.setTabText(2, self._t("历史"))
        self.validate_button.setText(self._t("验证参数"))
        self.start_button.setText(self._t("开始"))
        self.cancel_button.setText(self._t("取消"))
        self.open_result_button.setText(self._t("打开结果"))
        self.clear_history_button.setText(self._t("清空历史"))
        self.open_button.setText(self._t("打开工具"))
        self._form_schema_signature = None
        self._render_tool_cards()
        self._render_recent()

    def _t(self, text: object) -> str:
        source = str(text or "")
        translated = tr(source, self._language)
        if translated != source or self._language == "zh-CN":
            return translated
        return _LOCAL_TEXT.get(self._language, {}).get(source, source)

    def render(self, snapshot: dict) -> None:
        if "toolbox_items" in snapshot:
            self.items = self._mapping_list(snapshot.get("toolbox_items"))
        if "toolbox_recent_items" in snapshot:
            self.recent_items = self._mapping_list(snapshot.get("toolbox_recent_items"))

        selected_tool_id = str(snapshot.get("toolbox_selected_tool_id") or "")
        for key in _DISPLAY_BATCH_KEYS:
            if key in snapshot:
                selected_tool_id = self._ingest_display_batch(snapshot.get(key)) or selected_tool_id
        for key in _DISPLAY_PROJECTION_KEYS:
            if key in snapshot and isinstance(snapshot.get(key), Mapping):
                projection = dict(snapshot[key])
                selected_tool_id = str(projection.get("selected_tool_id") or selected_tool_id)
                self._store_projection(projection)

        self._render_tool_cards(preferred_tool_id=selected_tool_id)
        self._render_recent()

    def apply_display_projection(self, projection: Mapping[str, Any]) -> None:
        selected_tool_id = str(projection.get("selected_tool_id") or "")
        tool_id = self._store_projection(projection)
        if selected_tool_id and self._has_tool(selected_tool_id):
            self._select_tool(selected_tool_id)
        elif tool_id == self.current_tool_id:
            self._render_workspace()
        self._render_recent()

    def render_projection(self, projection: Mapping[str, Any]) -> None:
        self.apply_display_projection(projection)

    def apply_display_batch(self, batch: object) -> None:
        selected_tool_id = self._ingest_display_batch(batch)
        if selected_tool_id and self._has_tool(selected_tool_id):
            self._select_tool(selected_tool_id)
        else:
            self._render_workspace()
        self._render_recent()

    def render_batch(self, batch: object) -> None:
        self.apply_display_batch(batch)

    def _ingest_display_batch(self, batch: object) -> str:
        selected_tool_id = ""
        projections: list[Mapping[str, Any]] = []
        if isinstance(batch, Mapping):
            selected_tool_id = str(batch.get("selected_tool_id") or "")
            raw_projections = batch.get("projections") or batch.get("updates") or ()
            if isinstance(raw_projections, Sequence) and not isinstance(raw_projections, (str, bytes)):
                projections.extend(item for item in raw_projections if isinstance(item, Mapping))
            direct = batch.get("projection")
            if isinstance(direct, Mapping):
                projections.append(direct)
            if not projections and (batch.get("tool_id") or batch.get("id")):
                projections.append(batch)
            if "history" in batch:
                self.recent_items = self._mapping_list(batch.get("history"))
        elif isinstance(batch, Sequence) and not isinstance(batch, (str, bytes)):
            projections.extend(item for item in batch if isinstance(item, Mapping))

        for projection in projections:
            self._store_projection(projection)
        return selected_tool_id

    def _store_projection(self, projection: Mapping[str, Any]) -> str:
        tool_id = str(projection.get("tool_id") or projection.get("id") or self.current_tool_id)
        if not tool_id:
            return ""
        previous = self._display_projections.get(tool_id, {})
        merged = dict(previous)
        incoming = dict(projection)
        if isinstance(previous.get("form"), Mapping) and isinstance(incoming.get("form"), Mapping):
            form = dict(previous["form"])
            form.update(dict(incoming["form"]))
            incoming["form"] = form
        merged.update(incoming)
        merged["tool_id"] = tool_id
        self._display_projections[tool_id] = merged
        if tool_id == self.current_tool_id and (
            "validation" in projection or "validation_message" in projection
        ):
            self._form_dirty = False
        if "history" in projection:
            self.recent_items = self._mapping_list(projection.get("history"))
        return tool_id

    @staticmethod
    def _mapping_list(value: object) -> list[dict[str, Any]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [dict(item) for item in value if isinstance(item, Mapping)]

    def _render_tool_cards(self, *, preferred_tool_id: str = "") -> None:
        previous_tool_id = self.current_tool_id
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._tool_buttons = {}
        for index, item in enumerate(self.items):
            tool_id = str(item.get("id") or "")
            if not tool_id:
                continue
            button = QToolButton()
            button.setObjectName("ToolCardButton")
            button.setText(f"{self._t(item.get('title'))}\n{self._t(item.get('summary'))}")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(96)
            button.setMinimumWidth(246)
            button.setToolTip(self._t(item.get("summary")))
            icon = load_qt_icon([ui_icon_path(item.get("icon_file", ""))])
            if icon is not None:
                button.setIcon(icon)
                button.setIconSize(QSize(40, 40))
            button.clicked.connect(lambda _checked=False, current_id=tool_id: self._select_tool(current_id))
            self._tool_buttons[tool_id] = button
            self.grid.addWidget(button, index // 2, index % 2)

        available_ids = set(self._tool_buttons)
        selected_id = preferred_tool_id if preferred_tool_id in available_ids else ""
        if not selected_id and previous_tool_id in available_ids:
            selected_id = previous_tool_id
        if not selected_id and self.items:
            first_id = str(self.items[0].get("id") or "")
            selected_id = first_id if first_id in available_ids else ""
        self._select_tool(selected_id)

    def _has_tool(self, tool_id: str) -> bool:
        return any(str(item.get("id") or "") == tool_id for item in self.items)

    def _select_tool(self, tool_id: str) -> None:
        normalized = tool_id if self._has_tool(tool_id) else ""
        self.current_tool_id = normalized
        for key, button in self._tool_buttons.items():
            button.setChecked(key == normalized)
        self._render_workspace()

    def _current_item(self) -> dict[str, Any]:
        return next(
            (item for item in self.items if str(item.get("id") or "") == self.current_tool_id),
            {},
        )

    def _current_projection(self) -> dict[str, Any]:
        return self._display_projections.get(self.current_tool_id, {})

    def _render_workspace(self) -> None:
        item = self._current_item()
        projection = self._current_projection()
        if not item:
            self.detail_text.clear()
        else:
            self.detail_text.setPlainText(
                "\n".join(
                    [
                        f"{self._t('工具')}: {self._t(item.get('title'))}",
                        f"{self._t('说明')}: {self._t(item.get('summary'))}",
                        f"{self._t('输入示例')}: {self._t(item.get('input_example'))}",
                        f"{self._t('输出示例')}: {self._t(item.get('output_example'))}",
                    ]
                )
            )
        self._render_parameter_form(item, projection)
        self._render_lifecycle(projection)
        self._render_result(projection)

    def _parameter_fields_and_values(
        self,
        item: Mapping[str, Any],
        projection: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        form = projection.get("form") if isinstance(projection.get("form"), Mapping) else {}
        fields_value = form.get("fields") if form else None
        if fields_value is None:
            fields_value = projection.get("parameter_fields")
        if fields_value is None and isinstance(projection.get("parameters"), Sequence):
            fields_value = projection.get("parameters")
        if fields_value is None:
            fields_value = item.get("parameter_fields") or item.get("parameters") or ()
        fields = self._mapping_list(fields_value)

        values: dict[str, Any] = {}
        item_values = item.get("parameter_values")
        if isinstance(item_values, Mapping):
            values.update(item_values)
        projection_values = projection.get("parameter_values") or projection.get("values")
        if isinstance(projection_values, Mapping):
            values.update(projection_values)
        if form and isinstance(form.get("values"), Mapping):
            values.update(form["values"])
        if isinstance(projection.get("parameters"), Mapping):
            values.update(projection["parameters"])
        return fields, values

    def _render_parameter_form(self, item: Mapping[str, Any], projection: Mapping[str, Any]) -> None:
        fields, values = self._parameter_fields_and_values(item, projection)
        schema_signature = self._freeze_display(fields)
        values_signature = self._freeze_display(values)
        if (
            self._form_tool_id == self.current_tool_id
            and self._form_schema_signature == schema_signature
            and self._form_values_signature == values_signature
        ):
            return

        self._clear_form()
        self._form_tool_id = self.current_tool_id
        self._form_schema_signature = schema_signature
        self._form_values_signature = values_signature
        self._form_dirty = False
        if not fields:
            empty = QLabel(self._t("暂无可配置参数"))
            empty.setObjectName("MutedLabel")
            self.parameter_form.addRow(empty)
            return

        for field in fields:
            field_id = str(field.get("id") or field.get("name") or "")
            if not field_id:
                continue
            editor = self._build_parameter_editor(field, values.get(field_id, field.get("value", field.get("default"))))
            self.parameter_editors[field_id] = editor
            label_text = self._t(field.get("label") or field.get("title") or field_id)
            if bool(field.get("required")):
                label_text = f"{label_text} *"
            label = QLabel(label_text)
            label.setToolTip(self._t(field.get("help_text") or field.get("description") or ""))
            editor.setToolTip(label.toolTip())
            self.parameter_form.addRow(label, editor)

    def _clear_form(self) -> None:
        while self.parameter_form.count():
            item = self.parameter_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.parameter_editors = {}

    def _build_parameter_editor(self, field: Mapping[str, Any], value: Any) -> QWidget:
        field_type = str(field.get("type") or field.get("control") or "text").strip().lower()
        if field_type in {"choice", "select", "enum"}:
            editor = SettingsComboBox()
            for option in field.get("options") or ():
                if isinstance(option, Mapping):
                    option_value = option.get("value", option.get("id", ""))
                    option_label = option.get("label", option.get("title", option_value))
                else:
                    option_value = option
                    option_label = option
                editor.addItem(self._t(option_label), option_value)
            index = editor.findData(value)
            if index < 0 and value is not None:
                index = editor.findText(str(value))
            if index >= 0:
                editor.setCurrentIndex(index)
            editor.currentIndexChanged.connect(self._on_parameter_changed)
        elif field_type in {"boolean", "bool", "switch", "toggle"}:
            editor = UiSwitch()
            editor.setChecked(bool(value))
            editor.toggled.connect(self._on_parameter_changed)
        elif field_type in {"integer", "int", "spin"}:
            editor = QSpinBox()
            editor.setRange(self._int_value(field.get("minimum"), -1_000_000), self._int_value(field.get("maximum"), 1_000_000))
            editor.setValue(self._int_value(value, self._int_value(field.get("default"), 0)))
            editor.valueChanged.connect(self._on_parameter_changed)
        elif field_type in {"number", "float", "double"}:
            editor = QDoubleSpinBox()
            editor.setRange(self._float_value(field.get("minimum"), -1_000_000.0), self._float_value(field.get("maximum"), 1_000_000.0))
            editor.setDecimals(max(0, min(8, self._int_value(field.get("decimals"), 2))))
            editor.setValue(self._float_value(value, self._float_value(field.get("default"), 0.0)))
            editor.valueChanged.connect(self._on_parameter_changed)
        elif field_type in {"multiline", "textarea", "text_area"}:
            editor = QTextEdit()
            editor.setPlainText(str(value or ""))
            editor.setMinimumHeight(72)
            editor.setMaximumHeight(104)
            editor.textChanged.connect(self._on_parameter_changed)
        else:
            editor = QLineEdit(str(value or ""))
            editor.setPlaceholderText(self._t(field.get("placeholder") or ""))
            if bool(field.get("secret")) or field_type in {"password", "secret"}:
                editor.setEchoMode(QLineEdit.EchoMode.Password)
            editor.textChanged.connect(self._on_parameter_changed)
        editor.setObjectName("ToolboxParameterEditor")
        editor.setEnabled(bool(field.get("enabled", True)))
        return editor

    @staticmethod
    def _int_value(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float_value(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _freeze_display(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return tuple(sorted((str(key), cls._freeze_display(item)) for key, item in value.items()))
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(cls._freeze_display(item) for item in value)
        try:
            hash(value)
        except TypeError:
            return str(value)
        return value

    def _on_parameter_changed(self, *_args: object) -> None:
        self._form_dirty = True
        self.validation_label.setText(self._t("参数已更改，请重新验证"))

    def parameter_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field_id, editor in self.parameter_editors.items():
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

    def _render_lifecycle(self, projection: Mapping[str, Any]) -> None:
        phase = self._phase(projection)
        status_text = str(projection.get("status_text") or "")
        self.state_label.setText(self._t(status_text or _PHASE_TEXT.get(phase, "等待操作")))

        validation = projection.get("validation") if isinstance(projection.get("validation"), Mapping) else {}
        validation_text = str(validation.get("message") or projection.get("validation_message") or "")
        if not self._form_dirty:
            self.validation_label.setText(self._t(validation_text))

        progress = projection.get("progress")
        progress_visible = False
        progress_text = ""
        if isinstance(progress, Mapping):
            progress_text = str(progress.get("text") or progress.get("label") or "")
            if bool(progress.get("indeterminate")):
                self.progress_bar.setRange(0, 0)
                progress_visible = True
            elif "value" in progress or "percent" in progress:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(max(0, min(100, self._int_value(progress.get("value", progress.get("percent")), 0))))
                progress_visible = True
        elif progress is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, self._int_value(progress, 0))))
            progress_visible = True
        elif phase in {"starting", "running", "cancelling"}:
            self.progress_bar.setRange(0, 0)
            progress_visible = True
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.progress_bar.setVisible(progress_visible)
        self.progress_label.setText(self._t(progress_text))
        self.progress_label.setVisible(bool(progress_text))

        has_tool = bool(self.current_tool_id)
        busy = phase in {"validating", "starting", "running", "cancelling"}
        validation_state = str(validation.get("state") or "").lower()
        defaults = {
            "tool_validate": has_tool and not busy,
            "tool_start": has_tool and not busy and validation_state not in {"invalid", "error"},
            "tool_cancel": has_tool and phase in {"starting", "running"},
            "tool_open_result": has_tool and bool(projection.get("result")) and phase in {"success", "completed"},
            "tool_clear_history": has_tool and bool(self.recent_items),
        }
        self.validate_button.setEnabled(self._action_enabled(projection, "tool_validate", defaults["tool_validate"]))
        self.start_button.setEnabled(self._action_enabled(projection, "tool_start", defaults["tool_start"]))
        self.cancel_button.setEnabled(self._action_enabled(projection, "tool_cancel", defaults["tool_cancel"]))
        self.open_result_button.setEnabled(
            self._action_enabled(projection, "tool_open_result", defaults["tool_open_result"])
        )
        self.clear_history_button.setEnabled(
            self._action_enabled(projection, "tool_clear_history", defaults["tool_clear_history"])
        )

    @staticmethod
    def _phase(projection: Mapping[str, Any]) -> str:
        return str(projection.get("state") or projection.get("phase") or "idle").strip().lower()

    @staticmethod
    def _action_enabled(projection: Mapping[str, Any], action: str, default: bool) -> bool:
        actions = projection.get("actions")
        if isinstance(actions, Mapping) and action in actions:
            value = actions[action]
            if isinstance(value, Mapping):
                return bool(value.get("enabled", True))
            return bool(value)
        if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
            return action in actions
        short_name = action.removeprefix("tool_")
        for key in (f"can_{short_name}", f"{short_name}_enabled"):
            if key in projection:
                return bool(projection[key])
        return default

    def _render_result(self, projection: Mapping[str, Any]) -> None:
        result = projection.get("result")
        lines: list[str] = []
        if isinstance(result, Mapping):
            self._append_unique(lines, self._display_scalar(result.get("display_text")))
            self._append_unique(lines, self._display_scalar(result.get("summary")))
            for row in result.get("rows") or result.get("detail_rows") or ():
                if isinstance(row, Mapping):
                    label = self._display_scalar(row.get("label") or row.get("title"))
                    value = self._display_scalar(row.get("value") or row.get("display_value"))
                    if label and value:
                        self._append_unique(lines, f"{self._t(label)}: {self._t(value)}")
                    else:
                        self._append_unique(lines, self._display_scalar(row.get("display_text")))
                else:
                    self._append_unique(lines, self._display_scalar(row))
        else:
            self._append_unique(lines, self._display_scalar(result))
        self.result_view.setPlainText("\n".join(lines) if lines else self._t("暂无结果"))

    @staticmethod
    def _display_scalar(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        if isinstance(value, Mapping):
            nested = value.get("display_text") or value.get("text")
            return str(nested) if isinstance(nested, (str, int, float, bool)) else ""
        return ""

    @staticmethod
    def _append_unique(lines: list[str], value: str) -> None:
        if value and value not in lines:
            lines.append(value)

    def _render_recent(self) -> None:
        if not self.recent_items:
            self.recent.setPlainText(self._t("暂无最近使用记录"))
        else:
            lines = [self._history_line(item) for item in self.recent_items]
            self.recent.setPlainText("\n".join(line for line in lines if line))
        self._render_lifecycle(self._current_projection())

    def _history_line(self, item: Mapping[str, Any]) -> str:
        display_text = self._display_scalar(item.get("display_text"))
        if display_text:
            return self._t(display_text)
        parts = [
            self._display_scalar(item.get("finished_at") or item.get("last_used") or item.get("time_display")),
            self._display_scalar(item.get("title") or item.get("tool_title")),
            self._display_scalar(item.get("status_text")),
            self._display_scalar(item.get("summary")),
        ]
        return "  ".join(self._t(part) for part in parts if part)

    def _action_payload(self, action: str) -> dict[str, Any]:
        projection = self._current_projection()
        payload: dict[str, Any] = {}
        action_payloads = projection.get("action_payloads")
        if isinstance(action_payloads, Mapping) and isinstance(action_payloads.get(action), Mapping):
            payload.update(action_payloads[action])
        actions = projection.get("actions")
        if isinstance(actions, Mapping) and isinstance(actions.get(action), Mapping):
            explicit_payload = actions[action].get("payload")
            if isinstance(explicit_payload, Mapping):
                payload.update(explicit_payload)
        payload.setdefault("tool_id", self.current_tool_id)
        if action in {"tool_validate", "tool_start"}:
            payload["parameters"] = self.parameter_values()
        elif action == "tool_cancel":
            run_id = projection.get("run_id") or projection.get("execution_id")
            if run_id:
                payload.setdefault("run_id", str(run_id))
        elif action == "tool_open_result":
            result = projection.get("result")
            if isinstance(result, Mapping):
                result_id = result.get("id") or result.get("result_id")
                if result_id:
                    payload.setdefault("result_id", str(result_id))
        return payload

    def _emit_action(self, action: str) -> None:
        if not self.current_tool_id:
            return
        self.action_requested.emit(action, self._action_payload(action))

    def _emit_start(self) -> None:
        if not self.current_tool_id:
            return
        self._emit_action("tool_start")
        self.tool_requested.emit(self.current_tool_id)

    def _emit_current_tool(self) -> None:
        if self.current_tool_id:
            self.tool_requested.emit(self.current_tool_id)
