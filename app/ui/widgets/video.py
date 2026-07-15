"""提供便于切换全屏的双击视频控件。"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtMultimediaWidgets import QVideoWidget

class ClickableVideoWidget(QVideoWidget):
    """双击时发出信号，由窗口统一切换全屏。"""

    sig_double_click = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 交给全局主题样式控制明暗色，避免浅色主题下被强制覆盖成纯黑。
        self.setObjectName("VideoSurface")

    def mouseDoubleClickEvent(self, event):
        
        self.sig_double_click.emit()
        super().mouseDoubleClickEvent(event)
