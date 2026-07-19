from __future__ import annotations

import weakref
from collections.abc import Callable
from threading import Lock
from typing import Generic, Protocol, TypeVar

from PyQt6 import sip
from PyQt6.QtCore import QObject


QObjectT = TypeVar("QObjectT", bound=QObject)
ShutdownResourceT = TypeVar("ShutdownResourceT", bound="ShutdownResource")


class ShutdownResource(Protocol):
    def shutdown(self) -> None: ...


class ShutdownResourceSlot(Generic[ShutdownResourceT]):
    """Own a non-Qt resource that remains safe during QObject teardown."""

    def __init__(self, value: ShutdownResourceT | None = None) -> None:
        self._lock = Lock()
        self._value = value
        self._closed = False

    @property
    def value(self) -> ShutdownResourceT | None:
        with self._lock:
            return self._value

    @value.setter
    def value(self, resource: ShutdownResourceT | None) -> None:
        shutdown_immediately = False
        with self._lock:
            if self._closed and resource is not None:
                shutdown_immediately = True
            else:
                self._value = resource
        if shutdown_immediately:
            resource.shutdown()

    def shutdown(self) -> None:
        with self._lock:
            resource = self._value
            self._value = None
            self._closed = True
        if resource is not None:
            resource.shutdown()


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
    """Run a best-effort fallback after the Python wrapper is collected.

    Qt emits ``destroyed`` from inside the C++ destructor. Joining worker
    threads from that signal can race with destruction of the widget tree, so
    real shutdown must happen through an explicit ``shutdown``/``deleteLater``
    path before native teardown starts.
    """

    bound_owner = getattr(cleanup, "__self__", None)
    if isinstance(bound_owner, QObject):
        raise TypeError("destroyed cleanup must belong to a pure-Python lifecycle owner")
    if bound_owner is not None:
        cleanup_ref: Callable[[], Callable[[], None] | None] = weakref.WeakMethod(cleanup)
    else:
        def cleanup_ref() -> Callable[[], None]:
            return cleanup

    def invoke_cleanup(*_args: object) -> None:
        resolved = cleanup_ref()
        if resolved is not None:
            resolved()

    finalizer = weakref.finalize(owner, invoke_cleanup)
    finalizer.atexit = False
