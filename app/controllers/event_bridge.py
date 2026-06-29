from PyQt6.QtCore import QObject, pyqtSignal

class DomainEventBridge(QObject):
    """Marshal pure-Python domain events back onto the Qt UI thread."""

    sig_event = pyqtSignal(object)
