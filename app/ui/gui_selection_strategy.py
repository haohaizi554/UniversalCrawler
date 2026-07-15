"""UI 层内部基于 Qt 的任务选择策略。"""

from __future__ import annotations

import sys
import threading

from app.config import cfg
from shared.localization import normalize_language
from shared.interactive_selection import InteractiveTTYSelection

class _QtMainThreadInvoker:
    """通过 Qt 的 `queued signal` 将可调用对象投递到主线程。"""

    def __init__(self, app):
        from PyQt6.QtCore import QObject, Qt, pyqtSignal

        class Invoker(QObject):
            requested = pyqtSignal(object)

            def __init__(self):
                super().__init__()

            def _invoke(self, callback):
                callback()

        self._invoker = Invoker()
        self._invoker.moveToThread(app.thread())
        self._invoker.requested.connect(self._invoker._invoke, Qt.ConnectionType.QueuedConnection)

    def invoke(self, callback) -> None:
        self._invoker.requested.emit(callback)

class GUISelection:
    """优先使用 GUI 对话框；Qt 不可用时回退到 TTY 选择。"""

    def __init__(self):
        self._fallback = None
        self._invoker = None
        try:
            from PyQt6.QtWidgets import QApplication

            self._qt_available = True
            app = QApplication.instance()
            if app is not None:
                self._invoker = _QtMainThreadInvoker(app)
        except ImportError:
            self._qt_available = False
            self._fallback = InteractiveTTYSelection()

    @property
    def strategy_name(self) -> str:
        return "gui"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        if not self._qt_available:
            return self._fallback.select(items, prompt)

        count = len(items)
        if count == 0:
            return []

        try:
            from PyQt6.QtCore import QThread
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance() or QApplication(sys.argv)
            if QThread.currentThread() == app.thread():
                return self._run_dialog(app, items, prompt, fallback_count=count)

            result: list[list[int] | None] = [None]
            done = threading.Event()

            def run_on_main_thread() -> None:
                try:
                    result[0] = self._run_dialog(app, items, prompt, fallback_count=count)
                finally:
                    done.set()

            self._ensure_invoker(app).invoke(run_on_main_thread)
            done.wait()
            return result[0]
        except Exception as exc:
            sys.stderr.write(f"[GUISelection] error: {exc}; falling back to all items\n")
            return list(range(count))

    def _ensure_invoker(self, app):
        if self._invoker is None:
            self._invoker = _QtMainThreadInvoker(app)
        return self._invoker

    def _run_dialog(self, app_instance, items: list, prompt: str, *, fallback_count: int) -> list[int] | None:
        try:
            from app.ui.dialogs.selection import exec_selection_dialog

            parent = None
            for widget in app_instance.topLevelWidgets():
                if widget.isVisible() and hasattr(widget, "windowTitle"):
                    parent = widget
                    break

            title = f"任务清单确认 - {prompt}" if prompt else "任务清单确认"
            return exec_selection_dialog(parent, items, title=title, language=self._dialog_language(parent))
        except Exception as exc:
            sys.stderr.write(f"[GUISelection] dialog error: {exc}\n")
            return list(range(fallback_count))

    @staticmethod
    def _dialog_language(parent) -> str:
        getter = getattr(parent, "_current_ui_language", None)
        if callable(getter):
            try:
                return normalize_language(getter())
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
        try:
            return normalize_language(cfg.get("appearance", "language", "zh-CN"))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return "zh-CN"
