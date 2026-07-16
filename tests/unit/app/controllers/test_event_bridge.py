from __future__ import annotations

import threading
import time
import unittest

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import QApplication

from app.controllers.event_bridge import DomainEventBridge


class DomainEventBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_thread_emit_is_delivered_on_qt_main_thread(self):
        bridge = DomainEventBridge()
        delivered = threading.Event()
        observed: list[tuple[object, bool]] = []
        errors: list[BaseException] = []

        def on_event(payload):
            observed.append((payload, QThread.currentThread() == self.app.thread()))
            delivered.set()

        bridge.sig_event.connect(on_event, Qt.ConnectionType.QueuedConnection)

        def emit_from_worker() -> None:
            try:
                bridge.sig_event.emit({"topic": "download.progress"})
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=emit_from_worker, name="event-bridge-worker")
        worker.start()
        worker.join(timeout=1)

        deadline = time.time() + 2
        while not delivered.is_set() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertEqual(errors, [])
        self.assertTrue(delivered.is_set())
        self.assertEqual(observed, [({"topic": "download.progress"}, True)])


if __name__ == "__main__":
    unittest.main()
