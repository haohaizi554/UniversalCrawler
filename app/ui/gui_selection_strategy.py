"""Qt-backed selection strategy kept inside the UI layer."""

from __future__ import annotations

import sys
import threading


class GUISelection:
    """GUI 弹窗式二次选择策略。

    复用 GUI `SelectionDialog`，如果 PyQt6 不可用则自动降级为全选。
    """

    def __init__(self):
        self._fallback = None
        try:
            from PyQt6.QtWidgets import QApplication  # noqa: F401
            self._qt_available = True
        except ImportError:
            self._qt_available = False
            from cli.selection_base import RuleSelection

            self._fallback = RuleSelection(all_items=True)

    @property
    def strategy_name(self) -> str:
        return "gui"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """弹出 GUI SelectionDialog 让用户选择。"""
        if not self._qt_available:
            return self._fallback.select(items, prompt)

        n = len(items)
        if n == 0:
            return []

        try:
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            result = [None]
            event = threading.Event()

            def _show_dialog():
                try:
                    from app.ui.dialogs.selection import SelectionDialog

                    parent = None
                    for widget in app.topLevelWidgets():
                        if widget.isVisible() and hasattr(widget, "windowTitle"):
                            parent = widget
                            break

                    dialog = SelectionDialog(parent, items=items)
                    dialog.setWindowTitle(f"任务清单确认 - {prompt}" if prompt else "任务清单确认")

                    if dialog.exec() == dialog.DialogCode.Accepted:
                        result[0] = dialog.selected_indices
                    else:
                        result[0] = None
                except Exception as exc:
                    sys.stderr.write(f"[GUISelection] 对话框异常: {exc}\n")
                    result[0] = list(range(n))
                finally:
                    event.set()

            QTimer.singleShot(0, _show_dialog)

            while not event.is_set():
                app.processEvents()
                event.wait(0.1)

            return result[0]
        except Exception as exc:
            sys.stderr.write(f"[GUISelection] 异常: {exc}，降级为全选\n")
            return list(range(n))
