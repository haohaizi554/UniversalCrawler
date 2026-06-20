"""Task runtime cancellation tests."""

from __future__ import annotations

import threading
import time
import unittest

from PyQt6.QtWidgets import QApplication

from app.ui.task_runtime import LongTaskRunner, ShortTaskRunner, TaskCancelToken

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

if __name__ == "__main__":
    unittest.main()
