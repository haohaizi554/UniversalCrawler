"""把运行时设置更新安全地切回 Qt GUI 线程。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal


class GuiRuntimeInvoker(QObject):
    call_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call_requested.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def invoke(self, callback: Callable[[], None]) -> None:
        self.call_requested.emit(callback)

    def invoke_and_wait(self, callback: Callable[[], None], *, timeout_seconds: float) -> None:
        """通过 QueuedConnection 切回 Qt 线程，并用超时限制同步等待。"""
        if QThread.currentThread() == self.thread():
            callback()
            return
        completed = threading.Event()
        cancelled = threading.Event()
        failures: list[Exception] = []

        def _run_with_ack() -> None:
            if cancelled.is_set():
                completed.set()
                return
            try:
                callback()
            except Exception as exc:
                failures.append(exc)
            finally:
                completed.set()

        self.call_requested.emit(_run_with_ack)
        if not completed.wait(max(0.0, float(timeout_seconds))):
            cancelled.set()
            raise TimeoutError("GUI runtime apply acknowledgement timed out")
        if failures:
            raise failures[0]

    def _run(self, callback: Callable[[], None]) -> None:
        callback()


class QtGuiRuntimeAdapter:
    """在 service 的最小 GUI 运行时端口后隔离 PyQt 类型。"""

    @staticmethod
    def is_gui_thread() -> bool:
        app = QCoreApplication.instance()
        if app is None:
            return threading.current_thread() is threading.main_thread()
        return QThread.currentThread() == app.thread()

    @staticmethod
    def create_invoker() -> GuiRuntimeInvoker | None:
        app = QCoreApplication.instance()
        if app is None:
            return None
        invoker = GuiRuntimeInvoker()
        if invoker.thread() != app.thread():
            invoker.moveToThread(app.thread())
        return invoker

    @staticmethod
    def owns_qobject(value: Any) -> bool:
        return isinstance(value, QObject)
