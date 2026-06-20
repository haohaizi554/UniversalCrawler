"""Qt-native task runtime for long and short background work."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, pyqtSignal, pyqtSlot

class TaskCancelToken:
    """Thread-safe cancel token shared by long and short tasks."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

class _WorkerQObject(QObject):
    finished = pyqtSignal()

    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        token: TaskCancelToken,
    ) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._token = token
        self._logger = logging.getLogger(__name__)

    @pyqtSlot()
    def run(self) -> None:
        if self._token.is_cancelled():
            self.finished.emit()
            return
        try:
            kwargs = dict(self._kwargs)
            kwargs["cancel_token"] = self._token
            self._fn(*self._args, **kwargs)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Long-running task failed")
        finally:
            self.finished.emit()

class LongTaskHandle:
    """Joinable long task handle backed by QThread."""

    def __init__(self, *, name: str, thread: QThread, token: TaskCancelToken) -> None:
        self.name = name
        self._thread = thread
        self._token = token

    def cancel(self) -> None:
        self._token.cancel()

    def wait(self, timeout_ms: int) -> bool:
        return self._thread.wait(timeout_ms)

    def is_running(self) -> bool:
        return self._thread.isRunning()

class LongTaskRunner(QObject):
    """Submit long-running jobs onto dedicated QThreads."""

    _orphaned_handles: set[LongTaskHandle] = set()
    _orphaned_lock = threading.RLock()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handles: set[LongTaskHandle] = set()

    def submit(
        self,
        *,
        name: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> LongTaskHandle:
        kwargs = kwargs or {}
        token = TaskCancelToken()
        thread = QThread()
        thread.setObjectName(name)
        worker = _WorkerQObject(fn, args, kwargs, token)
        worker.moveToThread(thread)
        handle = LongTaskHandle(name=name, thread=thread, token=token)
        self._handles.add(handle)
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(worker.deleteLater, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(thread.deleteLater, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(lambda: self._discard_handle(handle), Qt.ConnectionType.QueuedConnection)
        thread.start()
        return handle

    def cancel_all(self, *, timeout_ms: int) -> None:
        for handle in list(self._handles):
            handle.cancel()
        for handle in list(self._handles):
            if handle.is_running() and not handle.wait(timeout_ms):
                with self._orphaned_lock:
                    self._orphaned_handles.add(handle)

    def _discard_handle(self, handle: LongTaskHandle) -> None:
        self._handles.discard(handle)
        with self._orphaned_lock:
            self._orphaned_handles.discard(handle)

class _ShortTaskRunnable(QRunnable):
    def __init__(
        self,
        *,
        fn: Callable[[TaskCancelToken], Any],
        token: TaskCancelToken,
        name: str,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self._token = token
        self._name = name
        self._on_finished = on_finished
        self._logger = logging.getLogger(__name__)

    @pyqtSlot()
    def run(self) -> None:
        try:
            if not self._token.is_cancelled():
                self._fn(self._token)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Short task failed: %s", self._name)
        finally:
            if callable(self._on_finished):
                self._on_finished()

class ShortTaskRunner(QObject):
    """Submit short-lived jobs onto QThreadPool."""

    def __init__(self, parent: QObject | None = None, *, max_thread_count: int | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool()
        if max_thread_count is not None:
            self._pool.setMaxThreadCount(max_thread_count)
        self._tokens: set[TaskCancelToken] = set()
        self._tokens_lock = threading.RLock()

    def submit(self, *, name: str, fn: Callable[[TaskCancelToken], Any]) -> TaskCancelToken:
        token = TaskCancelToken()
        with self._tokens_lock:
            self._tokens.add(token)
        runnable = _ShortTaskRunnable(
            fn=fn,
            token=token,
            name=name,
            on_finished=lambda: self._discard_token(token),
        )
        self._pool.start(runnable)
        return token

    def cancel_all(self, *, timeout_ms: int = 5000) -> None:
        with self._tokens_lock:
            tokens = list(self._tokens)
        for token in tokens:
            token.cancel()
        self._pool.waitForDone(timeout_ms)
        with self._tokens_lock:
            self._tokens.difference_update(tokens)

    def _discard_token(self, token: TaskCancelToken) -> None:
        with self._tokens_lock:
            self._tokens.discard(token)
