"""Qt-native task runtime for long and short background work."""

from __future__ import annotations

import logging
import threading
import weakref
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, pyqtSignal, pyqtSlot

class TaskCancelToken:
    """Thread-safe cancel token shared by long and short tasks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._done_event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait_cancelled(self, timeout: float | None = None) -> bool:
        """Wait until cancellation is requested, returning True when cancelled."""
        return self._event.wait(timeout)

    def mark_done(self) -> None:
        self._done_event.set()

    def is_done(self) -> bool:
        return self._done_event.is_set()

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
            self._token.mark_done()
            self.finished.emit()

class _ShortTaskRunnableSignals(QObject):
    progress = pyqtSignal(object)
    finished = pyqtSignal()

class LongTaskHandle:
    """Joinable long task handle backed by QThread."""

    def __init__(
        self,
        *,
        name: str,
        thread: QThread,
        token: TaskCancelToken,
        worker: _WorkerQObject | None,
        resource_hooks: list[Callable[[], Any]] | None = None,
    ) -> None:
        self.name = name
        self._thread = thread
        self._token = token
        self._worker: _WorkerQObject | None = worker
        self._resource_hooks: list[Callable[[], Any]] = list(resource_hooks or [])
        self._resource_hooks_lock = threading.RLock()
        self._resource_hooks_released = False

    def cancel(self) -> None:
        self._token.cancel()

    def wait(self, timeout_ms: int) -> bool:
        return self._thread.wait(timeout_ms)

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def terminate(self) -> None:
        self._token.cancel()
        self._thread.requestInterruption()
        self.release_resource_hooks()

    def is_done(self) -> bool:
        return self._token.is_done()

    def add_resource_hook(self, hook: Callable[[], Any]) -> None:
        with self._resource_hooks_lock:
            if self._resource_hooks_released:
                try:
                    hook()
                except Exception:  # pragma: no cover - defensive cleanup logging
                    logging.getLogger(__name__).exception("Long task resource hook failed after release: %s", self.name)
                return
            self._resource_hooks.append(hook)

    def release_resource_hooks(self) -> None:
        with self._resource_hooks_lock:
            if self._resource_hooks_released:
                return
            self._resource_hooks_released = True
            hooks = list(reversed(self._resource_hooks))
            self._resource_hooks.clear()
        logger = logging.getLogger(__name__)
        for hook in hooks:
            try:
                hook()
            except Exception:  # pragma: no cover - defensive cleanup logging
                logger.exception("Long task resource hook failed during terminate: %s", self.name)

class _LongTaskCompletionNotifier(QObject):
    """Own a safe QObject receiver for QThread.finished cleanup."""

    def __init__(self, runner: "LongTaskRunner", handle: LongTaskHandle) -> None:
        super().__init__(runner)
        self._runner_ref = weakref.ref(runner)
        self._handle = handle

    @pyqtSlot()
    def on_finished(self) -> None:
        runner = self._runner_ref()
        if runner is not None:
            runner._discard_handle(self._handle)
            runner._completion_notifiers.discard(self)
        self.deleteLater()

class LongTaskRunner(QObject):
    """Submit long-running jobs onto dedicated QThreads."""

    ORPHANED_HANDLE_WAIT_MS = 60_000
    _orphaned_handles: set[LongTaskHandle] = set()
    _orphaned_lock = threading.RLock()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handles: set[LongTaskHandle] = set()
        self._completion_notifiers: set[_LongTaskCompletionNotifier] = set()
        self._logger = logging.getLogger(__name__)

    def submit(
        self,
        *,
        name: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        resource_hooks: list[Callable[[], Any]] | None = None,
    ) -> LongTaskHandle:
        kwargs = kwargs or {}
        token = TaskCancelToken()
        thread = QThread()
        thread.setObjectName(name)
        worker = _WorkerQObject(fn, args, kwargs, token)
        worker.moveToThread(thread)
        handle = LongTaskHandle(name=name, thread=thread, token=token, worker=worker, resource_hooks=resource_hooks)
        self._handles.add(handle)
        notifier = _LongTaskCompletionNotifier(self, handle)
        self._completion_notifiers.add(notifier)
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(thread.deleteLater, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(notifier.on_finished, Qt.ConnectionType.QueuedConnection)
        thread.start()
        return handle

    def cancel_all(self, *, timeout_ms: int) -> None:
        for handle in list(self._handles):
            handle.cancel()
        for handle in list(self._handles):
            if handle.is_running() and not handle.wait(timeout_ms):
                handle.terminate()
                orphan_wait_ms = min(
                    self.ORPHANED_HANDLE_WAIT_MS,
                    max(1000, int(timeout_ms or 0)),
                )
                if handle.is_running() and not handle.wait(orphan_wait_ms):
                    release_hooks = getattr(handle, "release_resource_hooks", None)
                    if callable(release_hooks):
                        release_hooks()
                    self._logger.warning(
                        "Long task did not stop within %sms; leaving thread to exit cooperatively: %s",
                        timeout_ms + orphan_wait_ms,
                        handle.name,
                    )
                    with self._orphaned_lock:
                        self._orphaned_handles.add(handle)
            if not handle.is_running() or handle.is_done():
                self._discard_handle(handle)

    def _discard_handle(self, handle: LongTaskHandle) -> None:
        self._handles.discard(handle)
        handle._worker = None
        with self._orphaned_lock:
            self._orphaned_handles.discard(handle)

class _ShortTaskRunnable(QRunnable):
    def __init__(
        self,
        *,
        fn: Callable[[TaskCancelToken], Any],
        token: TaskCancelToken,
        name: str,
        panel: QObject | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self._token = token
        self._name = name
        self._logger = logging.getLogger(__name__)
        self._panel_ref = weakref.ref(panel) if panel is not None else lambda: None
        # No parent: _ShortTaskRunnable is QRunnable (not QObject); panel via weakref, hard parent unsafe.
        self._signals = _ShortTaskRunnableSignals()
        if panel is not None:
            on_progress = getattr(panel, "on_short_task_progress", None)
            if callable(on_progress):
                self._signals.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
            on_finished = getattr(panel, "on_short_task_finished", None)
            if callable(on_finished):
                self._signals.finished.connect(on_finished, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def run(self) -> None:
        try:
            if not self._token.is_cancelled():
                if self._panel_ref() is not None:
                    self._signals.progress.emit({"name": self._name, "state": "started"})
                self._fn(self._token)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.exception("Short task failed: %s", self._name)
        finally:
            if self._panel_ref() is not None:
                self._signals.progress.emit({"name": self._name, "state": "finished"})
                self._signals.finished.emit()
            self._token.mark_done()

class ShortTaskRunner(QObject):
    """Submit short-lived jobs onto QThreadPool."""

    def __init__(self, parent: QObject | None = None, *, max_thread_count: int | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool()
        if max_thread_count is not None:
            self._pool.setMaxThreadCount(max_thread_count)
        self._tokens: set[TaskCancelToken] = set()
        self._tokens_lock = threading.RLock()

    def submit(
        self,
        *,
        name: str,
        fn: Callable[[TaskCancelToken], Any],
        panel: QObject | None = None,
    ) -> TaskCancelToken:
        token = TaskCancelToken()
        with self._tokens_lock:
            self._prune_done_locked()
            self._tokens.add(token)
        runnable = _ShortTaskRunnable(
            fn=fn,
            token=token,
            name=name,
            panel=panel,
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
            self._prune_done_locked()

    def _discard_token(self, token: TaskCancelToken) -> None:
        with self._tokens_lock:
            self._tokens.discard(token)

    def _prune_done_locked(self) -> None:
        self._tokens = {token for token in self._tokens if not token.is_done()}
