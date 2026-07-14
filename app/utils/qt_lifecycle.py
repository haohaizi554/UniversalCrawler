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
    """Return a timer-safe callback that does not retain its QObject owner."""

    owner_ref = weakref.ref(owner)

    def invoke() -> None:
        target = owner_ref()
        if target is None or sip.isdeleted(target):
            return
        callback(target)

    return invoke


def connect_destroyed_cleanup(owner: QObject, cleanup: Callable[[], None]) -> None:
    """Run cleanup when Qt destroys owner, without retaining bound owners."""

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
