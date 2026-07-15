from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QWidget


class FocusPropertyBinder(QObject):
    """把子控件焦点镜像为动态属性，供 QSS 统一绘制组合控件焦点态。"""

    def __init__(self, source: QWidget, target: QWidget | None = None, property_name: str = "focused") -> None:
        super().__init__(source)
        self._target = target or source
        self._property_name = property_name
        source.installEventFilter(self)
        self._set_focused(source.hasFocus())

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            self._set_focused(event.type() == QEvent.Type.FocusIn)
        return False

    def _set_focused(self, focused: bool) -> None:
        value = "true" if focused else "false"
        if self._target.property(self._property_name) == value:
            return
        self._target.setProperty(self._property_name, value)
        style = self._target.style()
        style.unpolish(self._target)
        style.polish(self._target)
        self._target.update()


def bind_focus_property(source: QWidget, target: QWidget | None = None, property_name: str = "focused") -> None:
    binder = FocusPropertyBinder(source, target=target, property_name=property_name)
    binders = list(source.property("_focusPropertyBinders") or [])
    binders.append(binder)
    source.setProperty("_focusPropertyBinders", binders)
