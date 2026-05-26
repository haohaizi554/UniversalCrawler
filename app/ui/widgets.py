# app/ui/widgets.py

from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import pyqtSignal

class ClickableVideoWidget(QVideoWidget):
    sig_double_click = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        # 设置黑色背景和圆角，防止视频未加载时显示灰色
        self.setStyleSheet("background-color: #000; border-top-left-radius: 4px; border-top-right-radius: 4px;")
    def mouseDoubleClickEvent(self, event):
        self.sig_double_click.emit()