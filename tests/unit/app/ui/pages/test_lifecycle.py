from __future__ import annotations

import gc
import os
import unittest
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from app.ui.layout.app_shell import AppShell
from app.ui.pages.active_downloads_page import ActiveDownloadsPage
from app.ui.pages.completed_page import CompletedPage
from app.ui.pages.download_queue_page import DownloadQueuePage
from app.ui.pages.failed_page import FailedPage
from app.utils import qt_lifecycle
from app.utils.qt_lifecycle import connect_destroyed_cleanup, guarded_qt_callback


class _ShutdownProbe:
    def __init__(self) -> None:
        self.calls = 0

    def shutdown(self) -> None:
        self.calls += 1


class _QObjectCleanupProbe(QObject):
    def cleanup(self) -> None:
        pass


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

    def test_destroyed_cleanup_waits_for_python_wrapper_collection(self) -> None:
        owner = QObject()
        owner_ref = weakref.ref(owner)
        calls: list[bool] = []
        connect_destroyed_cleanup(owner, lambda: calls.append(True))

        sip.delete(owner)
        self.assertEqual(calls, [])

        del owner
        gc.collect()

        self.assertEqual(calls, [True])
        self.assertIsNone(owner_ref())

    def test_destroyed_cleanup_rejects_qobject_bound_methods(self) -> None:
        owner = _QObjectCleanupProbe()
        self.addCleanup(sip.delete, owner)

        with self.assertRaisesRegex(TypeError, "pure-Python"):
            connect_destroyed_cleanup(owner, owner.cleanup)

    def test_shutdown_resource_slot_releases_resource_once(self) -> None:
        slot_type = getattr(qt_lifecycle, "ShutdownResourceSlot", None)
        self.assertIsNotNone(slot_type)
        slot = slot_type()
        probe = _ShutdownProbe()
        slot.value = probe

        slot.shutdown()
        slot.shutdown()

        self.assertEqual(probe.calls, 1)
        self.assertIsNone(slot.value)

    def test_task_pages_shutdown_lazy_workers_before_deferred_delete(self) -> None:
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

                page.deleteLater()
                self.assertEqual(probe.calls, 1)
                self.app.processEvents()

                self.assertEqual(probe.calls, 1)

    def test_completed_page_destroyed_cleanup_does_not_reenter_media_children(self) -> None:
        page = CompletedPage(self.app)
        cleanup_calls: list[bool] = []
        page.cleanup = lambda: cleanup_calls.append(True)

        sip.delete(page)
        self.app.processEvents()

        self.assertEqual(cleanup_calls, [])

    def test_app_shell_delete_later_cleans_media_before_deferred_delete(self) -> None:
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        completed_page = shell.pages["completed"]
        cleanup_calls: list[bool] = []
        original_cleanup = completed_page.cleanup

        def cleanup_probe() -> None:
            cleanup_calls.append(True)
            original_cleanup()

        completed_page.cleanup = cleanup_probe
        try:
            shell.deleteLater()
            self.assertEqual(cleanup_calls, [True])
        finally:
            self.app.processEvents()

    def test_app_shell_delete_later_shuts_workers_before_deferred_delete(self) -> None:
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        probe = _ShutdownProbe()
        shell.pages["completed"]._page_worker = probe
        try:
            shell.deleteLater()
            self.assertEqual(probe.calls, 1)
        finally:
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
