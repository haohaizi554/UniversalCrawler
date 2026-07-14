from __future__ import annotations

import gc
import os
import unittest
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from app.ui.pages.active_downloads_page import ActiveDownloadsPage
from app.ui.pages.completed_page import CompletedPage
from app.ui.pages.download_queue_page import DownloadQueuePage
from app.ui.pages.failed_page import FailedPage
from app.utils.qt_lifecycle import connect_destroyed_cleanup, guarded_qt_callback


class _ShutdownProbe:
    def __init__(self) -> None:
        self.calls = 0

    def shutdown(self) -> None:
        self.calls += 1


class QtLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_guarded_callback_does_not_retain_or_touch_deleted_owner(self) -> None:
        owner = QObject()
        owner_ref = weakref.ref(owner)
        calls: list[QObject] = []
        callback = guarded_qt_callback(owner, calls.append)

        sip.delete(owner)
        del owner
        gc.collect()
        callback()

        self.assertIsNone(owner_ref())
        self.assertEqual(calls, [])

    def test_guarded_callback_does_not_hide_live_callback_errors(self) -> None:
        owner = QObject()
        self.addCleanup(sip.delete, owner)

        def fail(_owner: QObject) -> None:
            raise RuntimeError("live callback failure")

        callback = guarded_qt_callback(owner, fail)

        with self.assertRaisesRegex(RuntimeError, "live callback failure"):
            callback()

    def test_destroyed_cleanup_runs_once_without_retaining_owner(self) -> None:
        owner = QObject()
        owner_ref = weakref.ref(owner)
        calls: list[bool] = []
        connect_destroyed_cleanup(owner, lambda: calls.append(True))

        sip.delete(owner)
        del owner
        gc.collect()

        self.assertEqual(calls, [True])
        self.assertIsNone(owner_ref())

    def test_task_pages_shutdown_lazy_workers_when_parent_chain_destroys_them(self) -> None:
        pages_and_attributes = (
            (DownloadQueuePage(), "_page_worker"),
            (ActiveDownloadsPage(), "_items_worker"),
            (CompletedPage(self.app), "_page_worker"),
            (FailedPage(), "_page_worker"),
        )

        for page, attribute in pages_and_attributes:
            with self.subTest(page=type(page).__name__):
                probe = _ShutdownProbe()
                setattr(page, attribute, probe)

                sip.delete(page)
                self.app.processEvents()

                self.assertEqual(probe.calls, 1)


if __name__ == "__main__":
    unittest.main()
