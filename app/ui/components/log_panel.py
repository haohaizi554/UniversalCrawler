"""展示并自动滚动应用运行日志。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit

class LogPanel(QPlainTextEdit):
    MAX_LOG_BLOCK_COUNT = 500

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setObjectName("LogText")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.document().setMaximumBlockCount(self.MAX_LOG_BLOCK_COUNT)

    def append_log(self, message: str) -> None:
        
        self.appendPlainText(str(message))
        self.moveCursor(QTextCursor.MoveOperation.End)
