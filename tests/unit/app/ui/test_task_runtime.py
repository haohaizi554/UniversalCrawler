"""Task runtime cancellation tests."""

from __future__ import annotations

import threading
import time
import unittest

from PyQt6.QtWidgets import QApplication

from app.ui.task_runtime import LongTaskHandle, LongTaskRunner, ShortTaskRunner, TaskCancelToken

class TaskRuntimeCancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_long_task_submit_returns_cancellable_handle(self):
        runner = LongTaskRunner()
        handle = runner.submit(name="long", fn=lambda **_kwargs: None)
        self.assertEqual(handle.name, "long")
        handle.cancel()
        runner.cancel_all(timeout_ms=1000)

    def test_long_task_handle_is_discarded_after_thread_finished(self):
        runner = LongTaskRunner()
        handle = runner.submit(name="long", fn=lambda **_kwargs: None)

        deadline = time.time() + 2
        while not handle.is_done() and time.time() < deadline:
            self._app.processEvents()
            time.sleep(0.01)
        self.assertTrue(handle.wait(1000))
        self._app.processEvents()

        self.assertNotIn(handle, runner._handles)

    def test_long_task_cancel_all_does_not_force_terminate_stuck_qthread(self):
        class FakeHandle:
            name = "stuck"

            def __init__(self):
                self.cancel_called = False
                self.terminate_called = False

            def cancel(self):
                self.cancel_called = True

            def wait(self, _timeout_ms):
                return False

            def is_running(self):
                return True

            def terminate(self):
                self.terminate_called = True

            def is_done(self):
                return False

        runner = LongTaskRunner()
        handle = FakeHandle()
        runner._handles.add(handle)
        with runner._orphaned_lock:
            runner._orphaned_handles.discard(handle)

        runner.cancel_all(timeout_ms=1)

        self.assertTrue(handle.cancel_called)
        self.assertTrue(handle.terminate_called)
        self.assertIn(handle, runner._handles)
        with runner._orphaned_lock:
            self.assertIn(handle, runner._orphaned_handles)

    def test_long_task_handle_terminate_only_requests_interruption(self):
        class FakeThread:
            def __init__(self):
                self.interruption_requested = False
                self.force_terminated = False

            def requestInterruption(self):
                self.interruption_requested = True

            def terminate(self):
                self.force_terminated = True

        thread = FakeThread()
        token = TaskCancelToken()
        handle = LongTaskHandle(name="long", thread=thread, token=token, worker=None)

        handle.terminate()

        self.assertTrue(token.is_cancelled())
        self.assertTrue(thread.interruption_requested)
        self.assertFalse(thread.force_terminated)

    def test_cancel_token_wait_cancelled_reports_event_state(self):
        token = TaskCancelToken()

        self.assertFalse(token.wait_cancelled(0))
        token.cancel()

        self.assertTrue(token.wait_cancelled(0))

    def test_short_task_cancel_stops_before_run_body(self):
        runner = ShortTaskRunner(max_thread_count=1)
        started = threading.Event()

        def fn(token: TaskCancelToken):
            started.set()
            time.sleep(1)

        token = runner.submit(name="short", fn=fn)
        token.cancel()
        runner.cancel_all(timeout_ms=2000)
        time.sleep(0.2)
        self.assertFalse(started.is_set())

    def test_short_task_done_tokens_are_pruned_on_next_submit(self):
        runner = ShortTaskRunner(max_thread_count=1)
        completed = threading.Event()

        token = runner.submit(name="first", fn=lambda _token: completed.set())
        self.assertTrue(completed.wait(1))
        runner._pool.waitForDone(1000)
        self.assertTrue(token.is_done())

        second = runner.submit(name="second", fn=lambda _token: None)
        runner.cancel_all(timeout_ms=1000)

        with runner._tokens_lock:
            self.assertNotIn(token, runner._tokens)
            self.assertNotIn(second, runner._tokens)

if __name__ == "__main__":
    unittest.main()
