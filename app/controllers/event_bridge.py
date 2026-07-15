from PyQt6.QtCore import QObject, pyqtSignal

class DomainEventBridge(QObject):
    """把纯 Python 领域事件转发到 Qt UI 线程。"""

    sig_event = pyqtSignal(object)
