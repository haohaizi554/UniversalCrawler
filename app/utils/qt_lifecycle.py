from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TypeVar

from PyQt6 import sip
from PyQt6.QtCore import QObject


QObjectT = TypeVar("QObjectT", bound=QObject)


def guarded_qt_callback(
    owner: QObjectT,
    callback: Callable[[QObjectT], None],
) -> Callable[[], None]:
    """用弱引用包装延迟回调，避免 QTimer 闭包延长 QObject 生命周期。

    调用前同时检查 Python 包装对象与底层 C++ 对象，防止访问已被 Qt 销毁的实例。
    """

    owner_ref = weakref.ref(owner)

    def invoke() -> None:
        target = owner_ref()
        if target is None or sip.isdeleted(target):
            return
        callback(target)

    return invoke


def connect_destroyed_cleanup(owner: QObject, cleanup: Callable[[], None]) -> None:
    """在 Qt 销毁 owner 时清理资源，并避免信号连接强持有绑定对象。"""

    bound_owner = getattr(cleanup, "__self__", None)
    if bound_owner is not None:
        cleanup_ref: Callable[[], Callable[[], None] | None] = weakref.WeakMethod(cleanup)
    else:
        def cleanup_ref() -> Callable[[], None]:
            return cleanup

    def invoke_cleanup(*_args: object) -> None:
        resolved = cleanup_ref()
        if resolved is not None:
            resolved()

    owner.destroyed.connect(invoke_cleanup)
