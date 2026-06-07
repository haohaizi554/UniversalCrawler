"""GUI 弹窗式二次选择策略。

在交互式引导模式下，复用 GUI 的 SelectionDialog 弹窗进行二次选择，
与 GUI 体验完全一致。

工作原理：
1. spider 线程调用 select(items)
2. 通过 Qt 信号通知主线程弹出 SelectionDialog
3. 用户在 GUI 中选择后，通过事件返回结果
4. spider 线程拿到结果继续执行
"""

from __future__ import annotations

import sys
import threading
from typing import Protocol

from cli.selection_base import SelectionStrategy


class GUISelection:
    """GUI 弹窗式二次选择策略。

    复用 GUI SelectionDialog，与 GUI 体验完全一致。
    如果 PyQt6 不可用，自动降级为 RuleSelection (all)。
    """

    def __init__(self):
        self._fallback = None
        try:
            from PyQt6.QtWidgets import QApplication
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
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import Qt

            # 确保 QApplication 存在
            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            # 在主线程中弹出对话框
            # 由于 select() 在 spider 线程中调用，需要用 invokeMethod 或信号
            # 最简单的方式：用 QTimer 在主线程中执行
            result = [None]  # [selected_indices or None]
            event = threading.Event()

            def _show_dialog():
                try:
                    from app.ui.dialogs.selection import SelectionDialog

                    # 获取主窗口作为 parent（如果有）
                    parent = None
                    for w in app.topLevelWidgets():
                        if w.isVisible() and hasattr(w, 'windowTitle'):
                            parent = w
                            break

                    dialog = SelectionDialog(parent, items=items)
                    dialog.setWindowTitle(f"任务清单确认 - {prompt}" if prompt else "任务清单确认")

                    if dialog.exec() == dialog.DialogCode.Accepted:
                        result[0] = dialog.selected_indices
                    else:
                        result[0] = None  # 用户取消
                except Exception as e:
                    sys.stderr.write(f"[GUISelection] 对话框异常: {e}\n")
                    # 降级：全选
                    result[0] = list(range(n))
                finally:
                    event.set()

            # 在主线程中执行对话框
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, _show_dialog)

            # 等待用户完成选择（spider 线程阻塞在这里）
            while not event.is_set():
                app.processEvents()
                event.wait(0.1)

            return result[0]

        except Exception as e:
            sys.stderr.write(f"[GUISelection] 异常: {e}，降级为全选\n")
            return list(range(n))
