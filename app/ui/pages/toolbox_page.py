from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QPushButton, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget

from app.services.icon_registry import ui_icon_path
from app.ui.pages.common import PageFrame
from app.utils.qt_runtime import load_qt_icon

class ToolboxPage(PageFrame):
    tool_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("工具箱", "高效实用的辅助工具，提升工作效率", use_island=True)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        splitter.addWidget(self.grid_host)

        self.detail = QWidget()
        self.detail.setMinimumWidth(340)
        self.detail.setMaximumWidth(460)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(14, 0, 0, 0)
        detail_layout.addWidget(QLabel("最近使用"))
        self.recent = QTextEdit()
        self.recent.setReadOnly(True)
        self.recent.setMaximumHeight(160)
        detail_layout.addWidget(self.recent)
        detail_layout.addWidget(QLabel("工具详情"))
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text, 1)
        self.open_button = QPushButton("打开工具")
        self.open_button.clicked.connect(self._emit_current_tool)
        detail_layout.addWidget(self.open_button)
        splitter.addWidget(self.detail)
        splitter.setSizes([780, 360])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.root_layout.addWidget(splitter, 1)
        self.items: list[dict] = []
        self.recent_items: list[dict] = []
        self.current_tool_id = ""
        self._tool_buttons: dict[str, QToolButton] = {}

    def render(self, snapshot: dict) -> None:
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.items = list(snapshot.get("toolbox_items") or [])
        self.recent_items = list(snapshot.get("toolbox_recent_items") or [])
        self._tool_buttons = {}
        for index, item in enumerate(self.items):
            button = QToolButton()
            button.setObjectName("ToolCardButton")
            button.setText(f"{item.get('title')}\n{item.get('summary')}")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setMinimumHeight(102)
            button.setMinimumWidth(260)
            button.setToolTip(str(item.get("summary") or ""))
            icon = load_qt_icon([ui_icon_path(item.get("icon_file", ""))])
            if icon is not None:
                button.setIcon(icon)
                button.setIconSize(QSize(44, 44))
            button.clicked.connect(lambda _checked=False, tool_id=item.get("id", ""): self._select_tool(tool_id))
            self._tool_buttons[str(item.get("id", ""))] = button
            self.grid.addWidget(button, index // 2, index % 2)
        if self.items:
            self._select_tool(self.items[0].get("id", ""))
        self._render_recent()

    def _select_tool(self, tool_id: str) -> None:
        self.current_tool_id = tool_id
        for key, button in self._tool_buttons.items():
            button.setChecked(key == tool_id)
        item = next((tool for tool in self.items if tool.get("id") == tool_id), {})
        self.detail_text.setPlainText(
            "\n".join(
                [
                    f"工具: {item.get('title', '')}",
                    "",
                    f"说明: {item.get('summary', '')}",
                    "",
                    f"输入示例: {item.get('input_example', '')}",
                    "",
                    f"输出示例: {item.get('output_example', '')}",
                ]
            )
        )

    def _render_recent(self) -> None:
        if not self.recent_items:
            self.recent.setPlainText("暂无最近使用记录")
            return
        self.recent.setPlainText("\n".join(f"{item.get('title', '')}  {item.get('last_used', '')}" for item in self.recent_items))

    def _emit_current_tool(self) -> None:
        if self.current_tool_id:
            self.tool_requested.emit(self.current_tool_id)
