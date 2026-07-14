"""Thread-bound acknowledgement tests for the Qt runtime invoker."""

from __future__ import annotations

import threading
import unittest

from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from app.services.frontend_state_service import _GuiRuntimeInvoker


class _WorkerNotifier(QObject):
    finished = pyqtSignal()


class _QueuedDeliveryProbe(QObject):
    delivered = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.received = threading.Event()

    @pyqtSlot(object)
    def observe(self, _callback) -> None:
        self.received.set()
        self.delivered.emit()


class GuiRuntimeInvokerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.invoker = _GuiRuntimeInvoker()

    def _run_event_loop_until(self, signal, *, start=None, timeout_ms: int = 1000) -> None:
        loop = QEventLoop()
        deadline_expired = threading.Event()
        deadline = QTimer()
        deadline.setSingleShot(True)
        signal.connect(loop.quit, Qt.ConnectionType.QueuedConnection)
        deadline.timeout.connect(lambda: (deadline_expired.set(), loop.quit()))
        deadline.start(timeout_ms)
        if start is not None:
            start()
        loop.exec()
        deadline.stop()
        signal.disconnect(loop.quit)
        self.assertFalse(deadline_expired.is_set(), "Qt event delivery exceeded the bounded deadline")

    def _invoke_from_worker(self, callback, *, timeout_seconds: float = 1.0):
        notifier = _WorkerNotifier()
        outcome: dict[str, object] = {}

        def _target() -> None:
            try:
                self.invoker.invoke_and_wait(callback, timeout_seconds=timeout_seconds)
            except Exception as exc:  # exercised by the propagation tests
                outcome["error"] = exc
            else:
                outcome["returned"] = True
            finally:
                notifier.finished.emit()

        worker = threading.Thread(target=_target, name="gui-runtime-invoker-test")
        self._run_event_loop_until(notifier.finished, start=worker.start)
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive(), "GUI invoker worker leaked past its bounded join")
        return outcome

    def _invoke_from_worker_without_qt_events(self, callback, *, timeout_seconds: float = 0.0):
        outcome: dict[str, object] = {}
        finished = threading.Event()

        def _target() -> None:
            try:
                self.invoker.invoke_and_wait(callback, timeout_seconds=timeout_seconds)
            except Exception as exc:  # expected for the timeout path
                outcome["error"] = exc
            else:
                outcome["returned"] = True
            finally:
                finished.set()

        worker = threading.Thread(target=_target, name="gui-runtime-timeout-test")
        worker.start()
        self.assertTrue(finished.wait(1.0), "worker did not reach its timeout terminal state")
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive(), "timed-out GUI invoker worker leaked")
        return outcome

    def test_same_thread_invocation_runs_inline(self):
        callback_threads = []

        self.invoker.invoke_and_wait(
            lambda: callback_threads.append(QThread.currentThread()),
            timeout_seconds=0.0,
        )

        self.assertEqual(callback_threads, [self.invoker.thread()])

    def test_worker_invocation_waits_for_queued_gui_callback(self):
        callback_threads = []

        outcome = self._invoke_from_worker(
            lambda: callback_threads.append(QThread.currentThread()),
        )

        self.assertEqual(outcome, {"returned": True})
        self.assertEqual(callback_threads, [self.invoker.thread()])

    def test_worker_invocation_propagates_callback_exception(self):
        failure = RuntimeError("runtime apply exploded")

        def _raise_failure() -> None:
            raise failure

        outcome = self._invoke_from_worker(_raise_failure)

        self.assertIs(outcome.get("error"), failure)
        self.assertNotIn("returned", outcome)

    def test_worker_invocation_times_out_without_qt_delivery(self):
        callback_called = threading.Event()

        outcome = self._invoke_from_worker_without_qt_events(callback_called.set)

        self.assertIsInstance(outcome.get("error"), TimeoutError)
        self.assertEqual(str(outcome["error"]), "GUI runtime apply acknowledgement timed out")
        self.assertFalse(callback_called.is_set())
        self.app.processEvents()
        self.assertFalse(callback_called.is_set())

    def test_queued_callback_delivered_after_timeout_cannot_mutate_state(self):
        probe = _QueuedDeliveryProbe()
        self.invoker.call_requested.connect(probe.observe, Qt.ConnectionType.QueuedConnection)
        state: list[str] = []

        outcome = self._invoke_from_worker_without_qt_events(lambda: state.append("mutated"))

        self.assertIsInstance(outcome.get("error"), TimeoutError)
        self.assertFalse(probe.received.is_set())
        self.assertEqual(state, [])

        self._run_event_loop_until(probe.delivered)

        self.assertTrue(probe.received.is_set(), "the queued callback wrapper was not delivered")
        self.assertEqual(state, [], "a callback delivered after timeout mutated runtime state")


if __name__ == "__main__":
    unittest.main()
