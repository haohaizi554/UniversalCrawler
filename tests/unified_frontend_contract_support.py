"""Shared QApplication lifecycle and UI test helpers for frontend contracts."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QModelIndex, QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QTableView, QTableWidget, QToolButton, QWidget, QHeaderView

from app.services.frontend_state_service import FrontendStateService
from app.ui.components.combo_popup import (
    ComboPopupEventFilter,
    NoFocusItemDelegate,
    combo_edit_field_width,
    combo_widest_item_text_width,
    polish_combo_popup,
)
from app.ui.components.pagination_footer import PaginationFooter
from app.ui.components.settings_controls import SettingsComboBox, SegmentedControl, UiSwitch
from app.ui.components.settings_path_picker import SettingsPathPicker
from app.ui.components.smart_wrap_label import SmartWrapLabel
from app.ui.layout.app_shell import AppShell
from app.ui.layout.sidebar import _badge_size
from app.ui.main_window import MainWindow
from app.ui.pages.active_downloads_page import EventTimelineWidget, SpeedTrendWidget, TEXT
from app.ui.pages.common import ActionTable, connect_table_actions
from app.ui.pages.failed_page import FailedLogMessageLabel
from app.ui.styles.themes import apply_application_theme, generate_stylesheet, theme_colors
from app.ui.viewmodels.active_download_projection import (
    localize_active_event_message,
    prepare_active_item_for_display,
)
from shared.failed_page_projection import prepare_failed_item_for_display
from tests.frontend_static_assets import css_bundle_from_index

def _html_bundle() -> str:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    return "\n".join(
        (static_dir / name).read_text(encoding="utf-8")
        for name in (
            "index.html",
            "i18n.js",
            "custom_select.js",
            "media_display.js",
            "log_display.js",
            "platform_limits.js",
            "settings_render.js",
            "task_render.js",
            "playback_state.js",
            "log_i18n.js",
            "frontend_runtime.js",
            "list_pages.js",
            "log_center.js",
            "settings_controller.js",
            "dialog_controller.js",
            "playback_controller.js",
            "app.js",
        )
    )

def _css_bundle() -> str:
    return css_bundle_from_index()

__all__ = (
    'ActionTable',
    'AppShell',
    'ComboPopupEventFilter',
    'EventTimelineWidget',
    'FailedLogMessageLabel',
    'FrontendStateService',
    'MainWindow',
    'Mock',
    'NoFocusItemDelegate',
    'PaginationFooter',
    'Path',
    'QApplication',
    'QCheckBox',
    'QColor',
    'QComboBox',
    'QDialog',
    'QEvent',
    'QFileDialog',
    'QFont',
    'QFrame',
    'QHeaderView',
    'QLabel',
    'QLineEdit',
    'QMainWindow',
    'QModelIndex',
    'QPoint',
    'QPushButton',
    'QScrollArea',
    'QSize',
    'QTableView',
    'QTableWidget',
    'QTest',
    'QToolButton',
    'QWidget',
    'Qt',
    'SegmentedControl',
    'SettingsComboBox',
    'SettingsPathPicker',
    'SmartWrapLabel',
    'SpeedTrendWidget',
    'TEXT',
    'UiSwitch',
    'UnifiedFrontendContractTestCase',
    '_badge_size',
    '_css_bundle',
    '_html_bundle',
    'apply_application_theme',
    'combo_edit_field_width',
    'combo_widest_item_text_width',
    'connect_table_actions',
    'deepcopy',
    'generate_stylesheet',
    'localize_active_event_message',
    'os',
    'patch',
    'polish_combo_popup',
    'prepare_active_item_for_display',
    'prepare_failed_item_for_display',
    'tempfile',
    'theme_colors',
    'unittest',
)


class UnifiedFrontendContractTestCase(unittest.TestCase):
    """Infrastructure-only base; domain assertions live in explicit test modules."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _cleanup_shell(self, shell: AppShell) -> None:
        logs = getattr(shell, "pages", {}).get("logs")
        for worker_name in (
            "_log_query_worker",
            "_log_detail_worker",
            "_log_detail_export_worker",
        ):
            worker = getattr(logs, worker_name, None)
            shutdown = getattr(worker, "shutdown", None)
            if callable(shutdown):
                shutdown()
        shell.deleteLater()
        self.app.processEvents()

    def _make_shell(self) -> AppShell:
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        self.addCleanup(self._cleanup_shell, shell)
        shell.resize(1280, 720)
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        shell.render(snapshot)
        self.app.processEvents()
        return shell

    def _wait_for_log_rows(self, logs, expected_rows: int = 1) -> None:
        for _ in range(100):
            self.app.processEvents()
            if logs.table.model().rowCount() >= expected_rows:
                return
            QTest.qWait(20)
        self.app.processEvents()
        self.assertGreaterEqual(logs.table.model().rowCount(), expected_rows)

    def _wait_for_log_detail_source(self, logs, expected_text: str) -> None:
        for _ in range(250):
            self.app.processEvents()
            if logs.detail_source_value.text() == expected_text:
                return
            QTest.qWait(20)
        self.app.processEvents()
        self.assertEqual(logs.detail_source_value.text(), expected_text)

    def _wait_for_log_table_cell_suffix(self, logs, row: int, column: int, expected_suffix: str) -> str:
        last_value = ""
        for _ in range(250):
            self.app.processEvents()
            last_value = str(logs.table.model().index(row, column).data(Qt.ItemDataRole.DisplayRole) or "")
            if last_value.endswith(expected_suffix):
                return last_value
            QTest.qWait(20)
        self.app.processEvents()
        self.assertTrue(last_value.endswith(expected_suffix), last_value)
        return last_value

    def _wait_for_log_table_cell_without(self, logs, row: int, column: int, forbidden_text: str) -> str:
        last_value = ""
        for _ in range(250):
            self.app.processEvents()
            last_value = str(logs.table.model().index(row, column).data(Qt.ItemDataRole.DisplayRole) or "")
            if forbidden_text not in last_value:
                return last_value
            QTest.qWait(20)
        self.app.processEvents()
        self.assertNotIn(forbidden_text, last_value)
        return last_value

    def _wait_for_log_detail_status_code(self, logs, expected_text: str) -> None:
        for _ in range(250):
            self.app.processEvents()
            if expected_text in logs.detail_status_code_value.text():
                return
            QTest.qWait(20)
        self.app.processEvents()
        self.assertIn(expected_text, logs.detail_status_code_value.text())

    def _wait_until(self, predicate, *, message: str = "condition was not met") -> None:
        for _ in range(250):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(20)
        self.app.processEvents()
        self.assertTrue(predicate(), message)

    def _wait_for_table_rows(self, table: QTableView, expected_rows: int) -> None:
        self._wait_until(
            lambda: table.model().rowCount() == expected_rows,
            message=f"expected {expected_rows} table rows, got {table.model().rowCount()}",
        )

    def _wait_for_active_detail_key(self, active, key: str) -> None:
        self._wait_until(
            lambda: key in active._detail_value_labels,
            message=f"active detail key was not rendered: {key}",
        )

    def _assert_combo_selected_row_paints_to_right_edge(self, combo: QComboBox) -> None:
        view = combo.view()
        popup = view.window()
        view.repaint()
        view.viewport().repaint()
        popup.repaint()
        self.app.processEvents()
        image = popup.grab().toImage()
        self.assertFalse(image.isNull())
        row_rect = view.visualRect(view.currentIndex())
        self.assertTrue(row_rect.isValid())
        self.assertGreaterEqual(row_rect.width(), view.viewport().width() - 1)
        row_center_in_popup = view.viewport().mapTo(popup, row_rect.center())
        sample_x = max(0, image.width() - 10)
        sample_y = min(max(0, row_center_in_popup.y()), image.height() - 1)
        pixel = image.pixelColor(sample_x, sample_y)
        accent = QColor(str(view.property("comboPopupAccent") or theme_colors(False)["accent"]))
        distance = abs(pixel.red() - accent.red()) + abs(pixel.green() - accent.green()) + abs(pixel.blue() - accent.blue())
        self.assertLessEqual(distance, 12, f"{combo.objectName()} selected row leaves an unpainted right edge")

    def _assert_combo_popup_reclaims_native_gutter(self, combo: QComboBox) -> None:
        view = combo.view()
        popup = view.window()
        target_width = view.width()
        self.assertGreater(target_width, 0)
        popup.setMinimumWidth(0)
        popup.setMaximumWidth(16777215)
        popup.resize(target_width + 12, popup.height())
        polish_combo_popup(
            combo,
            visible_rows=max(1, min(combo.count(), 12)),
            row_height=int(view.property("comboPopupRowHeight") or 32),
        )
        self.app.processEvents()
        QTest.qWait(30)
        self.app.processEvents()
        self.assertEqual(popup.width(), target_width)
        self.assertEqual(popup.maximumWidth(), target_width)
