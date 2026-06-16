import builtins
import threading
import time
import unittest
from unittest.mock import patch


def _pyqt6_available():
    try:
        import PyQt6  # noqa: F401
        return True
    except ImportError:
        return False


class GUISelectionStrategyTests(unittest.TestCase):
    def test_gui_selection_falls_back_to_tty_when_pyqt6_is_missing(self):
        from app.ui.gui_selection_strategy import GUISelection

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "PyQt6.QtWidgets":
                raise ImportError("missing PyQt6")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import), patch(
            "app.ui.gui_selection_strategy.InteractiveTTYSelection"
        ) as mocked_fallback:
            strategy = GUISelection()

        self.assertFalse(strategy._qt_available)
        mocked_fallback.assert_called_once()

    @unittest.skipUnless(_pyqt6_available(), "PyQt6 not available")
    def test_gui_selection_dispatches_dialog_to_qt_main_thread(self):
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication

        from app.ui.gui_selection_strategy import GUISelection

        app = QApplication.instance() or QApplication([])
        strategy = GUISelection()
        observed: dict[str, object] = {}

        def fake_run_dialog(app_instance, items, prompt, *, fallback_count):
            observed["is_main_thread"] = QThread.currentThread() == app.thread()
            observed["items"] = items
            observed["prompt"] = prompt
            return [0]

        strategy._run_dialog = fake_run_dialog
        result_holder: dict[str, object] = {}

        worker = threading.Thread(
            target=lambda: result_holder.setdefault("result", strategy.select(["a", "b"], "挑一个")),
            daemon=True,
        )
        worker.start()

        deadline = time.time() + 2.0
        while worker.is_alive() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)

        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(observed.get("is_main_thread"))
        self.assertEqual(observed.get("items"), ["a", "b"])
        self.assertEqual(observed.get("prompt"), "挑一个")
        self.assertEqual(result_holder.get("result"), [0])


if __name__ == "__main__":
    unittest.main()
