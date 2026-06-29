"""Custom video widget for fullscreen-friendly double click handling."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtMultimediaWidgets import QVideoWidget

#轻量级增强型视频渲染控件，视频双击切换
class ClickableVideoWidget(QVideoWidget):
    """Emits a signal on double click so the window can toggle fullscreen."""

    sig_double_click = pyqtSignal()

    def __init__(self, parent=None):
        """初始化当前实例并准备运行所需的状态，供 `ClickableVideoWidget` 使用。"""
        super().__init__(parent)
        # 交给全局主题样式控制明暗色，避免浅色主题下被强制覆盖成纯黑。
        self.setObjectName("VideoSurface")

    def mouseDoubleClickEvent(self, event):
        
        self.sig_double_click.emit()
        super().mouseDoubleClickEvent(event)
