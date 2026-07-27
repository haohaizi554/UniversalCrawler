from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.pages.common import PageFrame
from app.ui.pages.toolbox_models import (
    ToolboxSnapshot,
    build_action_payload,
    normalize_toolbox_snapshot,
    phase_for,
)
from app.ui.pages.toolbox_widgets import (
    ToolExecutionPanel,
    ToolHistoryPanel,
    ToolParameterEditor,
    set_button_icon,
)
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
        self._snapshot = normalize_toolbox_snapshot({})
        self._language = "zh-CN"
        self._workspace_phase = ""

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
        self.parameter_editor = ToolParameterEditor(self._t, self.tabs)
        self.execution_panel = ToolExecutionPanel(self._t, self.tabs)
        self.history_panel = ToolHistoryPanel(self._t, self.tabs)
        self.parameter_editor.validate_requested.connect(lambda: self._emit_action("tool_validate"))
        self.parameter_editor.start_requested.connect(self._emit_start)
        self.parameter_editor.cancel_requested.connect(lambda: self._emit_action("tool_cancel"))
        self.execution_panel.open_result_requested.connect(lambda: self._emit_action("tool_open_result"))
        self.history_panel.clear_requested.connect(lambda: self._emit_action("tool_clear_history"))
        self.tabs.addTab(self.parameter_editor, "参数")
        self.tabs.addTab(self.execution_panel, "结果")
        self.tabs.addTab(self.history_panel, "历史")
        detail_layout.addWidget(self.tabs, 1)

        # Public controls remain direct references to their owning surfaces so
        # existing shell integrations do not need forwarding methods.
        self.parameter_editors = self.parameter_editor.editors
        self.parameter_title = self.parameter_editor.title
        self.form_scroll = self.parameter_editor.scroll
        self.form_host = self.parameter_editor.host
        self.parameter_form = self.parameter_editor.form
        self.validation_label = self.parameter_editor.validation_label
        self.validate_button = self.parameter_editor.validate_button
        self.cancel_button = self.parameter_editor.cancel_button
        self.start_button = self.parameter_editor.start_button
        self.result_title = self.execution_panel.title
        self.state_label = self.execution_panel.state_label
        self.progress_bar = self.execution_panel.progress_bar
        self.progress_label = self.execution_panel.progress_label
        self.result_view = self.execution_panel.result_view
        self.open_result_button = self.execution_panel.open_result_button
        self.recent_title = self.history_panel.title
        self.recent = self.history_panel.view
        self.clear_history_button = self.history_panel.clear_button

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

    def set_language(self, language: str | None) -> None:
        normalized = normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.title_label.setText(self._t("工具箱"))
        self.subtitle_label.setText(self._t("高效实用的辅助工具，提升工作效率"))
        self.selector_title.setText(self._t("选择工具"))
        self.detail_title.setText(self._t("工具工作台"))
        self.parameter_editor.set_language()
        self.execution_panel.set_language()
        self.history_panel.set_language()
        self.tabs.setTabText(0, self._t("参数"))
        self.tabs.setTabText(1, self._t("结果"))
        self.tabs.setTabText(2, self._t("历史"))
        self.open_button.setText(self._t("打开工具"))
        self._render_tool_cards()

    def _t(self, text: object) -> str:
        source = str(text or "")
        translated = tr(source, self._language)
        if translated != source or self._language == "zh-CN":
            return translated
        return _LOCAL_TEXT.get(self._language, {}).get(source, source)

    def render(self, snapshot: dict) -> None:
        self._apply_snapshot(normalize_toolbox_snapshot(snapshot, self._snapshot), render_cards=True)

    def apply_display_projection(self, projection: Mapping[str, Any]) -> None:
        self._apply_snapshot(normalize_toolbox_snapshot({"toolbox_display_projection": projection}, self._snapshot))

    def render_projection(self, projection: Mapping[str, Any]) -> None:
        self.apply_display_projection(projection)

    def apply_display_batch(self, batch: object) -> None:
        self._apply_snapshot(normalize_toolbox_snapshot({"toolbox_display_batch": batch}, self._snapshot))

    def render_batch(self, batch: object) -> None:
        self.apply_display_batch(batch)

    def _apply_snapshot(self, snapshot: ToolboxSnapshot, *, render_cards: bool = False) -> None:
        self._snapshot = snapshot
        self.items = [dict(item) for item in snapshot.items]
        self.recent_items = [dict(item) for item in snapshot.recent_items]
        self._display_projections = {key: dict(value) for key, value in snapshot.projections.items()}
        if render_cards:
            self._render_tool_cards(preferred_tool_id=snapshot.selected_tool_id)
        elif snapshot.selected_tool_id and self._has_tool(snapshot.selected_tool_id):
            self._select_tool(snapshot.selected_tool_id)
        else:
            self._render_workspace()

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
            set_button_icon(button, str(item.get("icon_file") or ""), 40)
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
        has_tool = bool(self.current_tool_id)
        self.parameter_editor.render(self.current_tool_id, item, projection)
        self.execution_panel.render(projection, has_tool)
        self.history_panel.render(self.recent_items, projection, has_tool)
        phase = phase_for(projection) if has_tool else "idle"
        if phase != self._workspace_phase:
            self._workspace_phase = phase
            self.tabs.setCurrentIndex(
                1
                if phase in {"starting", "running", "cancelling", "success", "completed", "error", "failed", "cancelled", "canceled"}
                else 0
            )

    def _emit_action(self, action: str) -> None:
        if not self.current_tool_id:
            return
        self.action_requested.emit(
            action,
            build_action_payload(
                action,
                self.current_tool_id,
                self._current_projection(),
                self.parameter_editor.values(),
            ),
        )

    def _emit_start(self) -> None:
        if not self.current_tool_id:
            return
        self._emit_action("tool_start")

    def _emit_current_tool(self) -> None:
        if self.current_tool_id:
            self.tool_requested.emit(self.current_tool_id)
