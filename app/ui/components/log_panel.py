"""界面模块，封装 `app/ui/components/log_panel.py` 对应的窗口、对话框或界面组件逻辑。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit

#日志展示面板，负责应用运行日志的追加、展示与自动滚动
class LogPanel(QPlainTextEdit):
    """定义 `LogPanel` 界面组件，负责对应区域的展示与交互。"""

    MAX_LOG_BLOCK_COUNT = 5000

    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `LogPanel` 使用。"""
        super().__init__()
        self.setReadOnly(True)
        self.setObjectName("LogText")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.document().setMaximumBlockCount(self.MAX_LOG_BLOCK_COUNT)

    def append_log(self, message: str) -> None:
        
        self.appendPlainText(str(message))
        self.moveCursor(QTextCursor.MoveOperation.End)
