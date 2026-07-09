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
from app.ui.viewmodels.failed_page_projection import prepare_failed_item_for_display

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
    static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    return (static_dir / "app.css").read_text(encoding="utf-8")

class UnifiedFrontendContractTests(unittest.TestCase):
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

    def test_gui_exposes_exact_seven_pages(self):
        shell = self._make_shell()

        self.assertEqual(
            list(shell.pages),
            ["queue", "active", "completed", "failed", "logs", "settings", "toolbox"],
        )

    def test_reselecting_current_sidebar_page_does_not_rerender_body(self):
        shell = self._make_shell()
        shell.show_page("failed")
        emitted: list[str] = []
        shell.page_changed.connect(emitted.append)
        failed = shell.pages["failed"]

        with patch.object(failed, "render", wraps=failed.render) as failed_render:
            shell.show_page("failed")

        self.assertEqual(emitted, [])
        failed_render.assert_not_called()
        self.assertEqual(shell.current_page_id, "failed")

    def test_switching_away_from_completed_releases_media_fullscreen_window(self):
        shell = self._make_shell()
        shell.show_page("completed")
        completed = shell.pages["completed"]
        media_panel = completed.media_panel
        original_parent = media_panel.parent()

        media_panel.enter_media_fullscreen()
        self.app.processEvents()
        fullscreen_window = media_panel._fullscreen_window
        self.assertIsNotNone(fullscreen_window)

        shell.show_page("failed")
        self.app.processEvents()

        self.assertEqual(shell.current_page_id, "failed")
        self.assertIsNone(media_panel._fullscreen_window)
        self.assertIs(media_panel.parent(), original_parent)
        try:
            self.assertFalse(fullscreen_window.isVisible())
        except RuntimeError:
            pass

    def test_sidebar_count_badge_uses_compact_mainstream_size(self):
        self.assertEqual(_badge_size("3"), QSize(24, 24))
        self.assertEqual(_badge_size("20").height(), 24)
        self.assertGreater(_badge_size("200").width(), _badge_size("20").width())
        self.assertLessEqual(_badge_size("200").height(), 24)

    def test_language_change_translates_current_page_and_defers_hidden_pages(self):
        shell = self._make_shell()
        calls: list[str] = []

        with patch.object(shell, "_translate_page", side_effect=lambda page_id: calls.append(page_id)):
            changed = shell.apply_language("en-US")
            shell.show_page("active", emit_change=False)

        self.assertTrue(changed)
        self.assertEqual(calls[0], "queue")
        self.assertIn("active", calls)
        self.assertNotIn("completed", calls)

    def test_gui_top_bar_uses_current_platform_placeholder_on_initial_language_render(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        bilibili_index = shell.sidebar.combo_source.findData("bilibili")
        self.assertGreaterEqual(bilibili_index, 0)

        shell.sidebar.combo_source.setCurrentIndex(bilibili_index)
        shell.render(snapshot)
        self.app.processEvents()

        placeholder = shell.top_bar.inp_search.placeholderText()
        self.assertIn("BV ID", placeholder)
        self.assertNotEqual("Enter a profile, shared, or collection link...", placeholder)

    def test_gui_log_query_submission_hands_snapshot_batch_to_worker_without_ui_clone(self):
        shell = self._make_shell()
        logs = shell.pages["logs"]
        row = {"id": "log-a", "time": "2026-07-06 10:00:00", "level": "INFO", "message": "hello"}
        row_batch = [row]
        logs._all_items = row_batch

        with patch.object(logs._log_query_worker, "submit") as submit:
            logs._submit_log_query(reset_page=True)

        request = submit.call_args.args[0]
        self.assertIs(request.items, row_batch)
        self.assertIs(request.items[0], row)

    def test_gui_log_empty_state_subtitle_uses_two_comma_free_lines(self):
        shell = self._make_shell()
        logs = shell.pages["logs"]

        subtitles = [label.text() for label in logs._empty_state_subtitles]

        self.assertEqual(subtitles, ["调整筛选条件", "或点击「刷新缓冲」重新加载日志"])
        self.assertNotIn("调整筛选条件，", subtitles)

    def test_global_stylesheet_applies_without_qss_parse_warnings(self):
        from PyQt6.QtCore import qInstallMessageHandler

        warnings: list[str] = []

        def capture_qt_message(_mode, _context, message: str) -> None:
            if "stylesheet" in message.lower() or "unknown property" in message.lower():
                warnings.append(message)

        previous_handler = qInstallMessageHandler(capture_qt_message)
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        try:
            window.setStyleSheet(generate_stylesheet(False))
            window.setStyleSheet(generate_stylesheet(True))
            self.app.processEvents()
        finally:
            qInstallMessageHandler(previous_handler)

        self.assertEqual([], warnings)

    def test_settings_path_input_marks_container_focused_for_accent_border(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]

        editor = settings.findChild(QLineEdit, "SettingsLineEdit")
        self.assertIsNotNone(editor)
        field = editor.parentWidget()
        self.assertIsNotNone(field)
        self.assertEqual(field.objectName(), "SettingsPathField")

        QApplication.sendEvent(editor, QEvent(QEvent.Type.FocusIn))
        self.assertEqual(field.property("focused"), "true")

        QApplication.sendEvent(editor, QEvent(QEvent.Type.FocusOut))
        self.assertEqual(field.property("focused"), "false")

    def test_settings_path_browse_button_uses_folder_icon_not_ellipsis(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]

        browse = settings.findChild(QToolButton, "SettingsPathBrowse")

        self.assertIsNotNone(browse)
        self.assertEqual(browse.text(), "")
        self.assertFalse(browse.icon().isNull())
        self.assertGreaterEqual(browse.iconSize().width(), 18)
        self.assertIn("QToolButton#SettingsPathBrowse", settings.styleSheet())
        self.assertIn("border-radius: 8px", settings.styleSheet())

    def test_settings_page_uses_shared_control_components(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]

        self.assertTrue(settings.findChildren(UiSwitch))
        self.assertTrue(settings.findChildren(SettingsComboBox))
        self.assertTrue(settings.findChildren(SettingsPathPicker))
        settings._set_current_group("外观设置")
        self.app.processEvents()
        self.assertTrue(settings.findChildren(SegmentedControl))


    def test_settings_catalog_keeps_real_group_icons_and_hints(self):
        from app.ui.viewmodels.settings_catalog import GROUP_HINTS, GROUP_ICONS

        groups = ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"]
        self.assertEqual(set(groups), set(GROUP_ICONS))
        self.assertEqual(set(groups), set(GROUP_HINTS))
        self.assertEqual(len(set(GROUP_ICONS.values())), len(groups))
        self.assertTrue(all("?" not in key and "?" not in value for key, value in GROUP_HINTS.items()))
        self.assertTrue(all(value.strip() for value in GROUP_HINTS.values()))

    def test_settings_page_renders_group_specific_icons_and_hint_text(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]

        seen_icon_keys: set[str] = set()
        for group in ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"]:
            settings._set_current_group(group)
            self.app.processEvents()
            hint = settings.findChild(QLabel, "SettingsHintText")
            detail_icon = settings.findChild(QLabel, "SettingsDetailIcon")
            self.assertIsNotNone(hint)
            self.assertIsNotNone(detail_icon)
            self.assertTrue(hint.text().strip(), group)
            self.assertNotIn("?", hint.text())
            pixmap = detail_icon.pixmap()
            self.assertIsNotNone(pixmap, group)
            self.assertFalse(pixmap.isNull(), group)
            seen_icon_keys.add(str(pixmap.cacheKey()))

        self.assertGreater(len(seen_icon_keys), 1)

    def test_gui_combo_popups_expand_short_lists_without_scrollbars(self):
        shell = self._make_shell()

        platform_combo = shell.sidebar.combo_source
        self.assertEqual(platform_combo.width(), 176)
        self.assertLessEqual(platform_combo.maximumWidth(), 176)
        self.assertIn(theme_colors(False)["accent"], platform_combo.styleSheet())
        platform_index = platform_combo.findData("xiaohongshu")
        self.assertGreaterEqual(platform_index, 0)
        platform_combo.setCurrentIndex(platform_index)
        polish_combo_popup(platform_combo, visible_rows=platform_combo.count())
        platform_combo.showPopup()
        self.app.processEvents()
        try:
            platform_view = platform_combo.view()
            self.assertIsInstance(platform_combo.itemDelegate(), NoFocusItemDelegate)
            self.assertIsInstance(platform_view.itemDelegate(), NoFocusItemDelegate)
            self.assertEqual(platform_view.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertEqual(platform_view.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertEqual(platform_view.property("comboPopupFullExpand"), "true")
            self.assertEqual(platform_view.verticalScrollBar().maximum(), 0)
            platform_row_height = int(platform_view.property("comboPopupRowHeight") or 0)
            self.assertGreaterEqual(platform_row_height, 32)
            self.assertLessEqual(platform_row_height, 40)
            self.assertGreaterEqual(platform_view.minimumHeight(), platform_combo.count() * platform_row_height)
            self.assertLessEqual(platform_view.maximumHeight(), platform_combo.count() * platform_row_height + 8)
            self.assertLessEqual(platform_view.maximumWidth(), 176)
            self.assertEqual(platform_view.property("comboPopupPaintedBorder"), "true")
            self.assertEqual(platform_view.property("comboPopupAccent"), theme_colors(False)["accent"])
            self.assertLessEqual(platform_view.viewport().geometry().left(), 1)
            self.assertLessEqual(platform_view.viewport().geometry().top(), 1)
            self.assertEqual(platform_view.currentIndex().row(), platform_combo.currentIndex())
            self.assertEqual(
                [index.row() for index in platform_view.selectionModel().selectedRows()],
                [platform_combo.currentIndex()],
            )
            self._assert_combo_popup_reclaims_native_gutter(platform_combo)
            self._assert_combo_selected_row_paints_to_right_edge(platform_combo)
        finally:
            platform_combo.hidePopup()
            platform_combo.view().window().hide()

        shell.show_page("settings")
        settings = shell.pages["settings"]
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()
        proxy_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.property("proxyCustomAllowed") == "true"
        )
        polish_combo_popup(proxy_combo, visible_rows=proxy_combo.count(), row_height=40)
        proxy_combo.showPopup()
        self.app.processEvents()
        try:
            proxy_view = proxy_combo.view()
            self.assertEqual(proxy_combo.count(), 9)
            self.assertEqual(proxy_view.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertEqual(proxy_view.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertEqual(proxy_view.property("comboPopupFullExpand"), "true")
            self.assertEqual(proxy_view.verticalScrollBar().maximum(), 0)
            self.assertGreaterEqual(proxy_view.minimumWidth(), proxy_combo.width())
            self.assertEqual(proxy_view.property("comboPopupPaintedBorder"), "true")
            self.assertEqual(proxy_view.currentIndex().row(), proxy_combo.currentIndex())
            self.assertEqual(
                [index.row() for index in proxy_view.selectionModel().selectedRows()],
                [proxy_combo.currentIndex()],
            )
            self._assert_combo_popup_reclaims_native_gutter(proxy_combo)
            self._assert_combo_selected_row_paints_to_right_edge(proxy_combo)
        finally:
            proxy_combo.hidePopup()
            proxy_combo.view().window().hide()

    def test_gui_platform_timeout_combo_has_no_native_arrow_gutter(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()

        platform_rows = settings._settings_snapshot[settings._group_order[2]]
        col_widths = settings._platform_col_widths(platform_rows)
        self.assertLessEqual(sum(col_widths.values()), settings._form_inner_width() - 28 - 40)
        self.assertGreaterEqual(col_widths["timeout"], 132)

        timeout_values = {"30", "60", "90", "120", "180", "300"}
        timeout_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo"
            and timeout_values.issubset({str(combo.itemData(index)) for index in range(combo.count())})
        )

        self.assertIn("推荐", timeout_combo.currentText())
        self.assertGreaterEqual(timeout_combo.width(), 132)
        self.assertGreaterEqual(combo_edit_field_width(timeout_combo), combo_widest_item_text_width(timeout_combo))
        self.assertGreaterEqual(combo_edit_field_width(timeout_combo), timeout_combo.width() - 24)
        self.assertNotIn("width: 28px", settings.styleSheet())
        polish_combo_popup(timeout_combo, visible_rows=timeout_combo.count(), row_height=38)
        timeout_combo.showPopup()
        self.app.processEvents()
        try:
            view = timeout_combo.view()
            popup = view.window()
            self.assertEqual(view.property("comboPopupTargetWidth"), timeout_combo.width())
            self.assertLessEqual(popup.width(), timeout_combo.width())
            self._assert_combo_popup_reclaims_native_gutter(timeout_combo)
            self._assert_combo_selected_row_paints_to_right_edge(timeout_combo)
        finally:
            timeout_combo.hidePopup()
            timeout_combo.view().window().hide()

    def test_combo_popup_late_geometry_lock_ignores_deleted_view(self):
        view = QTableView()
        self.addCleanup(view.deleteLater)

        with patch("app.ui.components.combo_popup._qt_object_alive", return_value=False):
            ComboPopupEventFilter._lock_popup_geometry(view)

    def test_gui_visible_combos_use_shared_theme_popup_contract(self):
        shell = self._make_shell()
        shell.show()

        for page_id in ("logs", "settings", "active", "completed"):
            shell.show_page(page_id)
            if page_id == "settings":
                shell.pages["settings"]._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
            self.app.processEvents()

            combos = [combo for combo in shell.findChildren(QComboBox) if combo.isVisible()]
            self.assertTrue(combos)
            for combo in combos:
                polish_combo_popup(combo, visible_rows=max(1, min(combo.count(), 12)), row_height=32)
                view = combo.view()
                self.assertEqual(combo.property("themedCombo"), "true")
                self.assertEqual(view.frameShape(), QFrame.Shape.NoFrame)
                self.assertEqual(view.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.assertEqual(view.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.assertEqual(view.viewport().styleSheet(), "background: transparent; border: none;")
                self.assertEqual(view.property("comboPopupPaintedBorder"), "true")
                self.assertEqual(view.property("comboPopupBorderRadius"), 8)
                self.assertIn("border-radius: 8px", view.styleSheet())
                self.assertNotIn("border-radius: 0px", view.styleSheet())

    def test_gui_themed_combos_refresh_control_styles_after_theme_switch(self):
        self.addCleanup(lambda: apply_application_theme(False))
        shell = self._make_shell()
        shell.show_page("logs")
        self.app.processEvents()

        log_combos = [
            shell.pages["logs"].level_filter,
            shell.pages["logs"].time_filter,
            shell.pages["logs"].platform_filter,
        ]
        light_input = theme_colors(False)["input"]
        dark_input = theme_colors(True)["input"]
        for combo in log_combos:
            self.assertIn(f"background: {light_input}", combo.styleSheet())

        apply_application_theme(True)
        shell.apply_theme(True)
        self.app.processEvents()

        for combo in log_combos:
            self.assertIn(f"background: {dark_input}", combo.styleSheet())
            self.assertIn(theme_colors(True)["panel"], combo.view().styleSheet())

    def test_log_filter_text_inputs_use_theme_focus_border(self):
        light_style = generate_stylesheet(False)
        dark_style = generate_stylesheet(True)
        css = _css_bundle()

        self.assertIn(".filters input:focus", css)
        self.assertIn(".filters input:focus-visible", css)
        self.assertIn("#page-logs .log-filters input:focus", css)
        self.assertIn("#page-logs .log-filters input:focus-visible", css)
        self.assertIn("#logTraceFilter:focus", css)
        self.assertIn("#logKeywordFilter:focus", css)
        self.assertIn("QLineEdit#LogFilterControl:focus", light_style)
        self.assertIn('QLineEdit#LogFilterControl[focused="true"]', light_style)
        self.assertIn("QLineEdit#LogFilterTextInput:focus", light_style)
        self.assertIn('QLineEdit#LogFilterTextInput[focused="true"]', light_style)
        self.assertIn(f"border: 2px solid {theme_colors(False)['accent']}", light_style)
        self.assertIn("QLineEdit#LogFilterControl:focus", dark_style)
        self.assertIn('QLineEdit#LogFilterControl[focused="true"]', dark_style)
        self.assertIn("QLineEdit#LogFilterTextInput:focus", dark_style)
        self.assertIn('QLineEdit#LogFilterTextInput[focused="true"]', dark_style)
        self.assertIn(f"border: 2px solid {theme_colors(True)['accent']}", dark_style)

        shell = self._make_shell()
        shell.show()
        shell.show_page("logs")
        self.app.processEvents()
        logs = shell.pages["logs"]
        accent = theme_colors(False)["accent"]
        for name in ("trace_filter", "keyword_filter"):
            editor = getattr(logs, name)
            self.assertEqual(editor.objectName(), "LogFilterTextInput")
            self.assertIn("QLineEdit:focus", editor.styleSheet())
            self.assertIn('QLineEdit[focused="true"]', editor.styleSheet())
            QApplication.sendEvent(editor, QEvent(QEvent.Type.FocusIn))
            self.app.processEvents()
            self.assertEqual(editor.property("focused"), "true")
            self.assertIn(f"border: 2px solid {accent}", editor.styleSheet())
            QApplication.sendEvent(editor, QEvent(QEvent.Type.FocusOut))
            self.app.processEvents()
            self.assertEqual(editor.property("focused"), "false")

            QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            if QApplication.focusWidget() is not editor:
                editor.setFocus(Qt.FocusReason.OtherFocusReason)
                QApplication.sendEvent(editor, QEvent(QEvent.Type.FocusIn))
                self.app.processEvents()
            self.assertEqual(editor.property("focused"), "true")
            self.assertIn(f"border: 2px solid {accent}", editor.styleSheet())
            editor.clearFocus()
            self.app.processEvents()

    def test_main_window_directory_picker_uses_native_folder_picker(self):
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(self.app.processEvents)
        window.set_current_save_dir = Mock()

        with patch(
            "app.ui.main_window.QFileDialog.getExistingDirectory",
            return_value="D:/Downloads",
        ) as picker:
            window.on_btn_dir_clicked()

        picker.assert_called_once()
        args, kwargs = picker.call_args
        self.assertIs(args[0], window)
        self.assertEqual(args[1], "选择保存目录")
        self.assertEqual(args[3], QFileDialog.Option.ShowDirsOnly)
        self.assertEqual(kwargs, {})
        window.set_current_save_dir.assert_called_once_with("D:/Downloads", persist=True)

    def test_settings_directory_picker_uses_native_folder_picker(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]
        editor = settings.findChild(QLineEdit, "SettingsLineEdit")
        self.assertIsNotNone(editor)
        changes = []
        settings.setting_changed.connect(lambda section, key, value: changes.append((section, key, value)))

        with patch(
            "app.ui.pages.settings_page.QFileDialog.getExistingDirectory",
            return_value="D:/Downloads",
        ) as picker:
            settings._browse_download_directory(editor, setting_key="download_directory")

        self.app.processEvents()

        picker.assert_called_once()
        args, kwargs = picker.call_args
        self.assertIs(args[0], settings)
        self.assertEqual(args[1], "选择下载目录")
        self.assertEqual(args[3], QFileDialog.Option.ShowDirsOnly)
        self.assertEqual(kwargs, {})
        self.assertEqual(editor.text(), "D:/Downloads")
        self.assertEqual(changes, [("common", "download_directory", "D:/Downloads")])
        self.assertEqual([], settings._directory_dialogs)

    def test_settings_page_cleanup_does_not_leave_hidden_toplevel_controls(self):
        shell = self._make_shell()
        shell.show_page("settings")
        settings = shell.pages["settings"]

        for group_name in list(settings._group_order) * 2:
            settings._set_current_group(group_name)
            self.app.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        hidden_settings_toplevels = [
            widget.objectName()
            for widget in self.app.topLevelWidgets()
            if not widget.isVisible() and widget.objectName().startswith("Settings")
        ]
        self.assertEqual([], hidden_settings_toplevels)

    def test_application_theme_ignores_orphan_controls_when_applying_root_styles(self):
        window = QMainWindow()
        orphan = QPushButton("orphan")
        orphan.setObjectName("SettingsNavButton")
        self.addCleanup(lambda: apply_application_theme(False))
        self.addCleanup(window.deleteLater)
        self.addCleanup(orphan.deleteLater)
        window.show()
        self.app.processEvents()

        apply_application_theme(True)
        self.app.processEvents()

        self.assertNotEqual("", window.styleSheet())
        self.assertEqual("", orphan.styleSheet())

    def test_application_theme_batches_root_repaint_during_stylesheet_swap(self):
        class RecordingWindow(QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.update_states: list[bool] = []

            def setUpdatesEnabled(self, enabled: bool) -> None:  # noqa: N802
                self.update_states.append(bool(enabled))
                super().setUpdatesEnabled(enabled)

        window = RecordingWindow()
        self.addCleanup(window.deleteLater)
        window.show()
        self.app.processEvents()

        apply_application_theme(False)
        self.app.processEvents()

        self.assertIn(False, window.update_states)
        self.assertEqual(window.update_states[-1], True)

    def test_gui_shell_renders_only_visible_page_until_navigation(self):
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        self.addCleanup(self._cleanup_shell, shell)
        snapshot = FrontendStateService.mock_snapshot()

        with (
            patch.object(shell.pages["queue"], "render") as queue_render,
            patch.object(shell.pages["active"], "render") as active_render,
            patch.object(shell.pages["settings"], "render") as settings_render,
        ):
            shell.render(snapshot)

            queue_render.assert_called_once_with(snapshot)
            active_render.assert_not_called()
            settings_render.assert_not_called()

            shell.show_page("settings")

            settings_render.assert_called_once_with(snapshot)
            active_render.assert_not_called()

    def test_gui_shell_fits_common_laptop_width(self):
        shell = self._make_shell()
        shell.resize(1180, 720)
        shell.show()
        self.app.processEvents()

        self.assertLessEqual(shell.width(), 1180)
        self.assertGreater(shell.stack.width(), 0)
        self.assertGreaterEqual(shell.top_bar.inp_search.width(), 220)

    def test_gui_pages_keep_bottom_status_visible_at_compact_height(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["completed_items"][0]["save_dir"] = (
            r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads"
        )
        shell.render(snapshot)
        shell.resize(1280, 720)
        shell.show()

        for page_id in shell.pages:
            shell.show_page(page_id)
            self.app.processEvents()
            status_bottom = shell.status_island.mapTo(shell, QPoint(0, shell.status_island.height())).y()
            stack_bottom = shell.stack.mapTo(shell, QPoint(0, shell.stack.height())).y()

            self.assertLessEqual(status_bottom, shell.height(), page_id)
            self.assertLessEqual(stack_bottom, shell.status_island.y(), page_id)

    def test_gui_page_table_columns_match_contract(self):
        shell = self._make_shell()

        expected = {
            "queue": ["视频标题", "平台", "状态", "操作"],
            "active": ["标题", "平台", "进度", "速度", "剩余时间", "操作"],
            "completed": ["标题", "完成时间", "时长", "格式", "操作"],
            "failed": ["标题", "失败时间", "失败原因", "状态", "操作"],
            "logs": ["时间", "级别", "来源", "Trace ID", "消息摘要"],
        }
        for page_id, headers in expected.items():
            table = shell.pages[page_id].table
            model = getattr(table, "model", lambda: None)()
            if model is not None:
                actual = [str(model.headerData(index, Qt.Orientation.Horizontal)) for index in range(model.columnCount())]
            else:
                actual = [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())]
            self.assertEqual(actual, headers, page_id)

        self.assertNotIn("任务ID", expected["logs"])
        self.assertNotIn("状态", expected["active"])

    def test_action_table_skips_identical_rows_and_keeps_single_action_handler(self):
        table = ActionTable(["标题", "进度", "操作"])
        calls: list[str] = []
        rows = [{"id": "row-1", "title": "Demo", "progress": 10}]

        if table.set_rows(rows, ["title", "progress"], actions={"delete": "删除"}):
            connect_table_actions(table, {"delete": calls.append})
        if table.set_rows(rows, ["title", "progress"], actions={"delete": "删除"}):
            connect_table_actions(table, {"delete": calls.append})

        buttons = table.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        buttons[0].click()

        self.assertEqual(calls, ["row-1"])
        table.deleteLater()

    def test_action_table_patches_stable_rows_without_full_clear(self):
        class RecordingActionTable(ActionTable):
            def __init__(self, headers):
                self.row_count_calls: list[int] = []
                super().__init__(headers)

            def setRowCount(self, count):  # noqa: N802
                self.row_count_calls.append(count)
                return super().setRowCount(count)

        table = RecordingActionTable(["Title", "Progress", "Actions"])
        calls: list[str] = []
        rows = [{"id": "row-1", "title": "Demo", "progress": 10}]
        if table.set_rows(rows, ["title", "progress"], actions={"delete": "Delete"}):
            connect_table_actions(table, {"delete": calls.append})

        table.row_count_calls.clear()
        updated_rows = [
            {"id": "row-1", "title": "Demo updated", "progress": 44},
            {"id": "row-2", "title": "Second", "progress": 1},
        ]
        if table.set_rows(updated_rows, ["title", "progress"], actions={"delete": "Delete"}):
            connect_table_actions(table, {"delete": calls.append})

        self.assertNotIn(0, table.row_count_calls)
        self.assertEqual(table.item(0, 0).text(), "Demo updated")
        self.assertEqual(table.cellWidget(0, 1).value(), 44)
        self.assertEqual(table.id_order(), ["row-1", "row-2"])

        row_one_button = next(button for button in table.findChildren(QPushButton) if button.item_id == "row-1")
        row_one_button.click()
        self.assertEqual(calls, ["row-1"])
        table.deleteLater()

    def test_action_table_reorders_same_ids_without_full_clear(self):
        class RecordingActionTable(ActionTable):
            def __init__(self, headers):
                self.row_count_calls: list[int] = []
                super().__init__(headers)

            def setRowCount(self, count):  # noqa: N802
                self.row_count_calls.append(count)
                return super().setRowCount(count)

        table = RecordingActionTable(["Title", "Progress", "Actions"])
        rows = [
            {"id": "row-1", "title": "First", "progress": 10},
            {"id": "row-2", "title": "Second", "progress": 20},
        ]
        table.set_rows(rows, ["title", "progress"], actions={"delete": "Delete"})

        table.row_count_calls.clear()
        table.set_rows(
            [
                {"id": "row-2", "title": "Second updated", "progress": 40},
                {"id": "row-1", "title": "First updated", "progress": 30},
            ],
            ["title", "progress"],
            actions={"delete": "Delete"},
        )

        self.assertNotIn(0, table.row_count_calls)
        self.assertEqual(table.id_order(), ["row-2", "row-1"])
        self.assertEqual(table.item(0, 0).text(), "Second updated")
        self.assertEqual(table.cellWidget(0, 1).value(), 40)
        table.deleteLater()

    def test_app_shell_item_index_initializes_on_first_partial_snapshot(self):
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        self.addCleanup(self._cleanup_shell, shell)
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["queue_items"] = [{"id": "queue-1", "title": "Queued"}]
        snapshot["active_downloads"] = [{"id": "active-1", "title": "Active"}]
        snapshot["completed_items"] = [
            {"id": "completed-1", "title": "Completed 1"},
            {"id": "completed-2", "title": "Completed 2"},
        ]
        snapshot["failed_items"] = [{"id": "failed-1", "title": "Failed"}]

        shell.render(snapshot, changed_sections={"completed_items"})
        self.app.processEvents()

        self.assertEqual(shell.row_for_video_id("queue-1"), 0)
        self.assertEqual(shell.row_for_video_id("active-1"), 0)
        self.assertEqual(shell.row_for_video_id("completed-2"), 1)
        self.assertEqual(shell.row_for_video_id("failed-1"), 0)
        self.assertEqual(shell.completed_id_order(), ["completed-1", "completed-2"])

    def test_active_downloads_page_uses_model_view_and_stable_updates(self):
        shell = self._make_shell()
        active = shell.pages["active"]

        self.assertIsInstance(active.table, QTableView)
        self.assertNotIsInstance(active.table, QTableWidget)

        model = active.table.model()
        resets: list[bool] = []
        changes: list[bool] = []
        model.modelReset.connect(lambda: resets.append(True))
        model.dataChanged.connect(lambda *_args: changes.append(True))

        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("active")
        active.render(snapshot)
        self._wait_for_table_rows(active.table, len(snapshot["active_downloads"]))
        resets.clear()
        active.render(snapshot)
        self._wait_for_table_rows(active.table, len(snapshot["active_downloads"]))
        self.assertEqual(resets, [])

        changed_snapshot = deepcopy(snapshot)
        changed_snapshot["active_downloads"][0]["progress"] = 66
        changed_snapshot["active_downloads"][0]["chunk_progress"]["percent"] = 66
        active.render(changed_snapshot)
        self._wait_until(lambda: bool(changes), message="active table did not patch changed cells")

        self.assertEqual(resets, [])
        self.assertTrue(changes)

    def test_active_downloads_page_uses_separate_cards_and_smart_wrap_labels(self):
        shell = self._make_shell()
        shell.show_page("active")
        self.app.processEvents()
        active = shell.pages["active"]

        table_card = active.findChild(QFrame, "ActiveTableCard")
        detail_card = active.findChild(QFrame, "ActiveDetailCard")
        events_card = active.findChild(QFrame, "ActiveEventsCard")
        queue_card = active.findChild(QFrame, "QueueControlPanel")
        fields_scroll = active.findChild(QScrollArea, "ActiveDetailFieldsScroll")
        events_scroll = active.findChild(QScrollArea, "ActiveEventsScroll")

        for card in (table_card, detail_card, events_card, queue_card):
            self.assertIsNotNone(card)
        self.assertIsNotNone(fields_scroll)
        self.assertIsNotNone(events_scroll)
        self._wait_until(
            lambda: fields_scroll.widget() is not None
            and len(active.detail_card.findChildren(SmartWrapLabel)) >= 3,
            message="active detail worker did not render the detail body",
        )
        fields_host = active.findChild(QWidget, "ActiveDetailFieldsHost")
        fields_body = active.findChild(QWidget, "ActiveDetailFieldsBody")
        self.assertIs(fields_scroll.widget(), fields_host)
        self.assertIs(fields_body.parentWidget(), fields_host)
        self.assertIs(active.table.parent(), table_card)
        self.assertGreater(table_card.layout().contentsMargins().left(), 0)
        self.assertEqual(active.detail_layout.contentsMargins().left(), 0)
        self.assertLessEqual(active.table.minimumHeight(), 280)

        wrap_labels = active.detail_card.findChildren(SmartWrapLabel)
        self.assertGreaterEqual(len(wrap_labels), 3)
        wrapped = [label for label in wrap_labels if "/" in label.raw_text() or "\\" in label.raw_text()]
        self.assertTrue(wrapped)
        self.assertTrue(wrapped[0].textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
        removed_detail_rows = {
            TEXT["thread_count"],
            TEXT["retry_count"],
            TEXT["write_status"],
            TEXT["merge_status"],
        }
        self.assertFalse(removed_detail_rows & set(active._detail_value_labels))

    def test_active_downloads_detail_consumes_service_ready_fields(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        item = snapshot["active_downloads"][0]
        item["title"] = "raw title should not win"
        item["detail_fields"] = [
            {"label": TEXT["title"], "value": "service ready title", "wrap": True},
            {"label": TEXT["platform"], "value": "service platform", "wrap": False},
            {"label": TEXT["save_dir"], "value": r"D:\service\ready", "wrap": True},
            {"label": TEXT["output_filename"], "value": "service-ready.mp4", "wrap": True},
            {"label": TEXT["source_url"], "value": "https://service.example/video", "wrap": True},
            {"label": TEXT["trace_id"], "value": "trace-ready", "wrap": False},
        ]
        item["chunk_progress_label"] = "42% (2/5)"
        item["speed_trend_label"] = "9.9 MB/s"

        active.render(snapshot)
        self._wait_for_active_detail_key(active, TEXT["title"])

        title_label = active._detail_value_labels[TEXT["title"]]
        title_text = title_label.raw_text() if hasattr(title_label, "raw_text") else title_label.text()
        self.assertEqual(title_text, "service ready title")
        self.assertEqual(active._detail_value_labels[TEXT["chunk_progress"]].text(), "42% (2/5)")
        trend = active.findChild(SpeedTrendWidget)
        self.assertIsNotNone(trend)
        self.assertEqual(trend._speed_label, "9.9 MB/s")

    def test_active_downloads_detail_runtime_fields_follow_live_item_values(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        item = snapshot["active_downloads"][0]
        item["source_url"] = "https://upos-sz-estghw.bilivideo.com/upgcxcode/12/25/33508362512/33508362512-1-30080.m4s?long=query"
        item["output_filename"] = "live-name.mp4"

        active.render(snapshot)
        self._wait_for_active_detail_key(active, TEXT["source_url"])

        self.assertEqual(active._detail_value_labels[TEXT["source_url"]].raw_text(), item["source_url"])
        self.assertEqual(active._detail_value_labels[TEXT["output_filename"]].raw_text(), "live-name.mp4")

    def test_active_downloads_detail_caps_long_text_fields_without_losing_raw_text(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        long_text = "接码平台开发者涉嫌侵犯公民个人信息罪，一审判4年9个月，" * 6
        item = snapshot["active_downloads"][0]
        item["title"] = long_text
        item["output_filename"] = f"{long_text}.mp4"
        for field in item.get("detail_fields") or []:
            if field.get("label") == TEXT["title"]:
                field["value"] = long_text
            elif field.get("label") == TEXT["output_filename"]:
                field["value"] = f"{long_text}.mp4"

        active.render(snapshot)
        def detail_text_ready() -> bool:
            title = active._detail_value_labels.get(TEXT["title"])
            output = active._detail_value_labels.get(TEXT["output_filename"])
            return (
                hasattr(title, "raw_text")
                and hasattr(output, "raw_text")
                and title.raw_text() == long_text
                and output.raw_text() == f"{long_text}.mp4"
            )

        self._wait_until(detail_text_ready, message="active detail did not receive updated long text")
        active.layout().activate()
        self.app.processEvents()

        title_label = active._detail_value_labels[TEXT["title"]]
        output_label = active._detail_value_labels[TEXT["output_filename"]]

        self.assertIsInstance(title_label, SmartWrapLabel)
        self.assertIsInstance(output_label, SmartWrapLabel)
        self.assertEqual(title_label.raw_text(), long_text)
        self.assertEqual(output_label.raw_text(), f"{long_text}.mp4")
        self.assertLessEqual(len(title_label.text().splitlines()), 4)
        self.assertLessEqual(len(output_label.text().splitlines()), 3)

    def test_smart_wrap_label_breaks_before_next_segment_when_it_will_not_fit(self):
        label = SmartWrapLabel("https://example.com/segment-that-fits/next-segment-that-does-not-fit")
        self.addCleanup(label.deleteLater)
        label.resize(230, 120)
        label.show()
        self.app.processEvents()

        lines = label.text().splitlines()

        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("/"))
        for line in lines:
            self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), label.contentsRect().width() + 2)

    def test_smart_wrap_label_uses_parent_visible_width_when_layout_overallocates(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(180, 160)
        label = SmartWrapLabel(r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads\demo", parent)
        label.move(86, 0)
        label.resize(420, 160)
        parent.show()
        self.app.processEvents()

        available = parent.contentsRect().width() - label.x()
        lines = [line for line in label.text().splitlines() if line]

        self.assertGreaterEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), available + 2)

    def test_smart_wrap_label_keeps_path_segments_together_when_width_allows(self):
        path = r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads"
        label = SmartWrapLabel(path)
        self.addCleanup(label.deleteLater)
        label.resize(520, 120)
        label.show()
        self.app.processEvents()

        lines = [line for line in label.text().splitlines() if line]

        self.assertLessEqual(len(lines), 2)
        self.assertTrue(any("project" in line and "UniversalCrawlerProplus" in line for line in lines))

    def test_smart_wrap_label_caps_very_long_url_even_in_wide_container(self):
        url = "https://upos-sz-estghw.bilivideo.com/upgcxcode/12/25/33508362512/33508362512-1-30080.m4s?long=query"
        label = SmartWrapLabel(url)
        self.addCleanup(label.deleteLater)
        label.resize(900, 160)
        label.show()
        self.app.processEvents()

        lines = [line for line in label.text().splitlines() if line]

        self.assertGreaterEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(
                label.fontMetrics().horizontalAdvance(line),
                SmartWrapLabel.LONG_SEGMENT_WRAP_WIDTH + 2,
            )

    def test_smart_wrap_label_caps_long_plain_text_to_requested_lines(self):
        long_text = "接码平台开发者涉嫌侵犯公民个人信息罪，一审判4年9个月，" * 8
        label = SmartWrapLabel(long_text, max_lines=3)
        self.addCleanup(label.deleteLater)
        label.resize(260, 160)
        label.show()
        self.app.processEvents()

        lines = [line for line in label.text().splitlines() if line]

        self.assertEqual(label.raw_text(), long_text)
        self.assertLessEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith(SmartWrapLabel.ELLIPSIS))
        for line in lines:
            self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), label.contentsRect().width() + 2)

    def test_active_downloads_trend_widget_has_stable_height_and_current_speed(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = FrontendStateService.mock_snapshot()

        active.render(snapshot)
        self._wait_for_active_detail_key(active, TEXT["title"])
        trend = active.findChild(SpeedTrendWidget)

        self.assertIsNotNone(trend)
        self.assertEqual(trend.minimumHeight(), SpeedTrendWidget.HEIGHT)
        self.assertEqual(trend.maximumHeight(), SpeedTrendWidget.HEIGHT)
        self.assertEqual(trend._speed_label, snapshot["active_downloads"][0]["speed"])

    def test_active_downloads_trend_widget_uses_smooth_curve_path(self):
        path = SpeedTrendWidget._smooth_curve_path([(0, 20), (20, 4), (40, 24), (60, 10)])

        self.assertGreater(path.elementCount(), 4)

    def test_active_downloads_height_budget_keeps_fixed_regions_visible(self):
        shell = self._make_shell()
        shell.resize(1280, 720)
        shell.show()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        item = snapshot["active_downloads"][0]
        item["title"] = "P10 疯批3D嘉米 座位抢占测试标题 " * 5
        item["save_dir"] = r"D:\desktop\project\UniversalCrawlerProplus\user_data\Downloads\4K直拍魂魄\very\long\path\that\must\scroll"
        item["output_filename"] = "P10_疯批3D嘉米_座位抢占测试_very_long_filename_1080p_60fps.mp4"
        item["source_url"] = "https://upos-sz-estghw.bilivideo.com/upgcxcode/12/25/33508362512/33508362512-1-30080.m4s?long=query"
        item["speed_trend"] = [2_400_000 for _ in range(60)]

        active.render(snapshot)
        self._wait_for_active_detail_key(active, TEXT["source_url"])
        shell.layout().activate()
        self.app.processEvents()

        trend = active.findChild(SpeedTrendWidget)
        detail_card = active.findChild(QFrame, "ActiveDetailCard")
        queue_card = active.findChild(QFrame, "QueueControlPanel")
        fields_scroll = active.findChild(QScrollArea, "ActiveDetailFieldsScroll")

        self.assertIsNotNone(trend)
        self.assertIsNotNone(detail_card)
        self.assertIsNotNone(queue_card)
        self.assertIsNotNone(fields_scroll)
        self.assertEqual(trend.height(), SpeedTrendWidget.HEIGHT)
        trend_bottom = trend.mapTo(detail_card, QPoint(0, trend.height())).y()
        self.assertLessEqual(trend_bottom, detail_card.height())
        queue_bottom = queue_card.mapTo(shell, QPoint(0, queue_card.height())).y()
        status_bottom = shell.status_island.mapTo(shell, QPoint(0, shell.status_island.height())).y()
        self.assertLessEqual(queue_bottom, shell.height())
        self.assertLessEqual(status_bottom, shell.height())
        self.assertLessEqual(active.table.minimumHeight(), 280)
        title_label = active._detail_value_labels[TEXT["title"]]
        source_label = active._detail_value_labels[TEXT["source_url"]]
        self.assertIsInstance(title_label, SmartWrapLabel)
        self.assertIsInstance(source_label, SmartWrapLabel)
        self.assertGreaterEqual(len(source_label.text().splitlines()), 2)
        for line in source_label.text().splitlines():
            self.assertLessEqual(
                source_label.fontMetrics().horizontalAdvance(line),
                source_label.contentsRect().width() + 2,
            )

    def test_active_downloads_event_timeline_has_room_for_six_rows(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]

        active.render(FrontendStateService.mock_snapshot())
        self.app.processEvents()
        timeline = active.findChild(EventTimelineWidget)

        self.assertIsNotNone(timeline)
        self.assertGreaterEqual(timeline.minimumHeight(), 214)
        self.assertGreaterEqual(timeline.maximumHeight(), timeline.minimumHeight())

    def test_active_downloads_action_column_emits_delete_only(self):
        shell = self._make_shell()
        active = shell.pages["active"]
        active.render(FrontendStateService.mock_snapshot())
        deleted: list[str] = []
        active.delete_requested.connect(deleted.append)

        active.table.action_requested.emit("pause", "a1")
        active.table.action_requested.emit("delete", "a1")

        self.assertEqual(deleted, ["a1"])

    def test_active_download_options_emit_real_payload(self):
        shell = self._make_shell()
        shell.show_page("active")
        self.app.processEvents()
        active = shell.pages["active"]
        emitted: list[dict] = []
        active.options_changed.connect(emitted.append)

        self.assertEqual(
            [active.thread_combo.itemData(i) for i in range(active.thread_combo.count())],
            [1, 3, 5],
        )
        self.assertEqual(active.thread_combo.currentData(), 3)
        self.assertIn("推荐", active.thread_combo.currentText())
        self.assertEqual([active.retry_combo.itemData(i) for i in range(active.retry_combo.count())], list(range(1, 11)))
        self.assertTrue(active.auto_retry.isChecked())

        active.auto_retry.resize(QSize(190, 36))
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(18, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertTrue(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        active.thread_combo.setCurrentIndex(2)
        active.retry_combo.setCurrentIndex(4)

        self.assertTrue(emitted)
        self.assertEqual(emitted[-1], {"auto_retry": False, "max_retries": 5, "max_concurrent": 5})

    def test_active_download_options_sync_from_snapshot_without_emit(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        active.render(FrontendStateService.mock_snapshot())
        self.app.processEvents()
        emitted: list[dict] = []
        active.options_changed.connect(emitted.append)
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["download_options"] = {"auto_retry": False, "max_retries": 7, "max_concurrent": 6}

        active.render(snapshot)
        self.app.processEvents()

        self.assertFalse(active.auto_retry.isChecked())
        self.assertEqual(active.retry_combo.currentData(), 7)
        self.assertEqual(active.thread_combo.currentData(), 5)
        self.assertEqual(emitted, [])

    def test_active_progress_refresh_does_not_reset_download_options(self):
        shell = self._make_shell()
        shell.show_page("active")
        self.app.processEvents()
        active = shell.pages["active"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["download_options"] = {"auto_retry": False, "max_retries": 7, "max_concurrent": 6}
        active.render(snapshot)
        partial = {
            "active_downloads": deepcopy(snapshot["active_downloads"]),
            "app_status": deepcopy(snapshot["app_status"]),
        }
        partial["active_downloads"][0]["progress"] = 72

        active.render(partial)
        self.app.processEvents()

        self.assertFalse(active.auto_retry.isChecked())
        self.assertEqual(active.retry_combo.currentData(), 7)
        self.assertEqual(active.thread_combo.currentData(), 5)

    def test_snapshot_list_pages_use_model_view_tables(self):
        shell = self._make_shell()

        for page_id in ("queue", "active", "completed", "failed", "logs"):
            table = shell.pages[page_id].table
            self.assertIsInstance(table, QTableView, page_id)
            self.assertNotIsInstance(table, QTableWidget, page_id)

    def test_snapshot_action_tables_forward_page_actions(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        queue = shell.pages["queue"]
        completed = shell.pages["completed"]
        failed = shell.pages["failed"]
        queue.render(snapshot)
        completed.render(snapshot)
        failed.render(snapshot)
        deleted: list[str] = []
        played: list[str] = []
        retried: list[str] = []
        queue.delete_requested.connect(deleted.append)
        completed.play_requested.connect(played.append)
        failed.retry_requested.connect(retried.append)

        queue.table.action_requested.emit("delete", "q1")
        completed.table.action_requested.emit("play", "c1")
        failed.table.action_requested.emit("retry", "f1")

        self.assertEqual(deleted, ["q1"])
        self.assertEqual(played, ["c1"])
        self.assertEqual(retried, ["f1"])

    def test_gui_queue_page_paginates_large_lists_and_selects_across_pages(self):
        shell = self._make_shell()
        queue = shell.pages["queue"]
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["queue_items"] = [
            {
                "id": f"q-{index:02d}",
                "title": f"Item {index:02d}",
                "platform": "抖音",
                "status": "待下载",
                "progress": 0,
                "actions": ["delete"],
            }
            for index in range(25)
        ]

        queue.render(snapshot)
        self._wait_for_table_rows(queue.table, 20)

        self.assertEqual(queue.table.model().rowCount(), 20)
        self.assertEqual(queue.total_label.text(), "共 25 项")
        self.assertEqual(queue.page_label.text(), "1 / 2 页")
        self.assertIsInstance(queue.pagination_footer, PaginationFooter)
        self.assertEqual(queue.btn_prev.objectName(), "PaginationButton")
        self.assertEqual(queue.btn_next.objectName(), "PaginationButton")
        for widget in (queue.btn_prev, queue.btn_next, queue.page_size_combo):
            self.assertGreaterEqual(widget.height(), 34)

        queue.btn_next.click()
        self._wait_for_table_rows(queue.table, 5)
        self.assertEqual(queue.page_label.text(), "2 / 2 页")
        self.assertEqual(queue.table.model().rowCount(), 5)

        self.assertTrue(queue.select_id("q-03"))
        self._wait_until(lambda: queue.selected_id() == "q-03", message="queue did not select q-03")
        self.assertEqual(queue.page_label.text(), "1 / 2 页")
        self.assertEqual(queue.selected_id(), "q-03")

    def test_gui_queue_refresh_button_requests_real_snapshot_refresh(self):
        shell = self._make_shell()
        queue = shell.pages["queue"]
        calls: list[bool] = []
        shell.refresh_requested.connect(lambda: calls.append(True))

        queue.btn_refresh.click()

        self.assertEqual(calls, [True])

    def test_gui_top_bar_keeps_only_unified_controls(self):
        shell = self._make_shell()
        top_bar = shell.top_bar

        self.assertEqual(top_bar.btn_start.text(), "启动任务")
        self.assertEqual(top_bar.btn_stop.text(), "停止")
        self.assertEqual(top_bar.btn_dir.text(), "更改目录")
        self.assertFalse(top_bar.container_dynamic.isVisible())

        visible_button_texts = {
            button.text()
            for button in top_bar.findChildren(QPushButton)
            if button.isVisible()
        }
        for removed in ("错误摘要", "复制Trace", "导出日志", "清空记录"):
            self.assertNotIn(removed, visible_button_texts)

    def test_gui_settings_uses_real_controls_without_current_option_panel(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        self.assertGreater(len(settings.findChildren(QLineEdit)), 0)
        self.assertGreater(len(settings.findChildren(QComboBox)), 0)
        self.assertGreater(len(settings.findChildren(QCheckBox)), 0)
        self.assertFalse(any(label.text() == "当前选项" for label in settings.findChildren(QLabel)))

        download_nav = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.property("groupName") == "下载设置"
        )
        download_nav.click()
        self.app.processEvents()
        self.assertGreater(len(settings.findChildren(QComboBox)), 3)
        self.assertTrue(any(label.text() == "图片受并发数限制" for label in settings.findChildren(QLabel)))
        self.assertFalse(any(editor.isVisible() for editor in settings.findChildren(QLineEdit)))

        log_nav = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.property("groupName") == "日志设置"
        )
        log_nav.click()
        self.app.processEvents()
        label_texts = {label.text() for label in settings.detail_panel.findChildren(QLabel)}
        self.assertIn("日志保留天数", label_texts)
        self.assertIn("失败记录保留天数", label_texts)
        self.assertIn("错误时自动复制 Trace", label_texts)
        self.assertNotIn("日志级别", label_texts)

        playback_nav = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.property("groupName") == "播放设置"
        )
        playback_nav.click()
        self.app.processEvents()
        interval_combo = settings.findChild(QComboBox, "ImageAutoAdvanceIntervalCombo")
        manual_switch = settings.findChild(QCheckBox, "ImageManualSwitch")
        self.assertIsNotNone(interval_combo)
        self.assertIsNotNone(manual_switch)
        self.assertEqual(interval_combo.currentData(), "5")
        self.assertEqual(
            [str(interval_combo.itemData(index)) for index in range(interval_combo.count())],
            ["1", "3", "5", "10"],
        )
        self.assertFalse(interval_combo.isHidden())
        manual_switch.setChecked(True)
        self.app.processEvents()
        self.assertTrue(interval_combo.isHidden())
        manual_switch.setChecked(False)
        self.app.processEvents()
        self.assertFalse(interval_combo.isHidden())

    def test_settings_render_does_not_rebuild_while_editor_has_focus(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        editor = settings.findChildren(QLineEdit)[0]
        editor.setFocus()
        editor.setText("typed value")
        self.app.processEvents()

        changed_snapshot = deepcopy(FrontendStateService.mock_snapshot())
        first_group = next(iter(changed_snapshot["settings_snapshot"]))
        changed_snapshot["settings_snapshot"][first_group]["filename_template"] = "changed-template"
        settings.render(changed_snapshot)

        self.assertIn(editor, settings.findChildren(QLineEdit))
        self.assertEqual(editor.text(), "typed value")

    def test_settings_render_repairs_empty_view_even_when_signature_matches(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        snapshot = FrontendStateService.mock_snapshot()
        settings.render(snapshot)
        self.assertGreaterEqual(settings.detail_layout.count(), 3)

        settings._clear_detail_panel()
        self.assertEqual(settings.detail_layout.count(), 0)
        settings.render(snapshot)
        self.app.processEvents()

        object_names = {
            settings.detail_layout.itemAt(index).widget().objectName()
            for index in range(settings.detail_layout.count())
            if settings.detail_layout.itemAt(index).widget() is not None
        }
        self.assertIn("SettingsDetailHeader", object_names)
        self.assertIn("SettingsFormCard", object_names)

    def test_gui_basic_settings_use_backend_options_and_emit_changes(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        combos = settings.findChildren(QComboBox)
        self.assertGreaterEqual(len(combos), 2)
        filename_combo, open_mode_combo = combos[0], combos[1]
        self.assertEqual(filename_combo.itemData(0), "current")
        self.assertEqual(filename_combo.itemText(0), "\u9ed8\u8ba4")
        self.assertEqual(open_mode_combo.currentData(), "builtin_player")
        self.assertEqual(open_mode_combo.currentText(), "\u5185\u7f6e\u64ad\u653e\u5668")
        self.assertTrue(any(not checkbox.isChecked() for checkbox in settings.findChildren(QCheckBox)))
        self.assertTrue(
            any(
                label.text() == "MissAV 有 5 秒盾，建议显式运行并手动过盾"
                for label in settings.findChildren(QLabel)
            )
        )

        changes = []
        associations = []
        settings.setting_changed.connect(lambda section, key, value: changes.append((section, key, value)))
        settings.file_association_requested.connect(lambda video, image: associations.append((video, image)))

        browser_title = None
        for _ in range(250):
            self.app.processEvents()
            browser_title = next(
                (label for label in settings.findChildren(QLabel) if label.text() == "显示浏览器内核"),
                None,
            )
            if browser_title is not None:
                break
            QTest.qWait(20)
        self.assertIsNotNone(browser_title)
        browser_row = browser_title
        while browser_row is not None and browser_row.objectName() != "SettingsSettingRow":
            browser_row = browser_row.parentWidget()
        self.assertIsNotNone(browser_row)
        browser_switch = browser_row.findChild(QCheckBox)
        self.assertIsNotNone(browser_switch)
        browser_target = not browser_switch.isChecked()
        browser_switch.setChecked(browser_target)
        self.app.processEvents()
        self.assertIn(("common", "show_browser_window", browser_target), changes)

        if filename_combo.count() > 1:
            filename_combo.setCurrentIndex(1)
            self.app.processEvents()
            self.assertIn(("common", "filename_template", filename_combo.itemData(1)), changes)

        button = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.objectName() == "SettingsActionButton"
        )
        button.click()
        self.app.processEvents()
        self.assertEqual(associations[-1], (True, True))

    def test_gui_settings_combo_popup_stays_inside_control_width(self):
        shell = self._make_shell()
        shell.show()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        filename_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.itemData(0) == "current"
        )
        self.assertEqual(filename_combo.itemText(0), "\u9ed8\u8ba4")
        self.assertEqual(filename_combo.property("comboPopupClampToControl"), "true")

        polish_combo_popup(filename_combo, visible_rows=filename_combo.count(), row_height=38)
        filename_combo.showPopup()
        self.app.processEvents()
        try:
            view = filename_combo.view()
            popup = view.window()
            QTest.qWait(60)
            self.app.processEvents()

            self.assertEqual(filename_combo.property("comboPopupMaxWidth"), filename_combo.width())
            self.assertEqual(view.property("comboPopupTargetWidth"), filename_combo.width())
            self.assertLessEqual(view.maximumWidth(), filename_combo.width())
            self.assertLessEqual(popup.maximumWidth(), filename_combo.width())
            self.assertLessEqual(popup.width(), filename_combo.width())

            combo_right = filename_combo.mapToGlobal(filename_combo.rect().topRight()).x()
            popup_right = popup.mapToGlobal(popup.rect().topRight()).x()
            self.assertLessEqual(popup_right, combo_right + 1)
        finally:
            filename_combo.hidePopup()
            filename_combo.view().window().hide()

        open_mode_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.currentData() == "builtin_player"
        )
        path_picker = next(iter(settings.findChildren(SettingsPathPicker)))
        naming_control = filename_combo.parentWidget()
        open_mode_row = open_mode_combo.parentWidget()
        self.assertEqual(path_picker.width(), naming_control.width())
        self.assertEqual(naming_control.width(), open_mode_row.width())
        self.assertGreaterEqual(path_picker.height(), 40)
        self.assertGreaterEqual(naming_control.height(), filename_combo.height())
        self.assertLessEqual(filename_combo.geometry().bottom(), naming_control.height())

        bind_button = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.objectName() == "SettingsActionButton"
        )
        self.assertIs(bind_button.parentWidget(), open_mode_row)
        self.assertEqual(open_mode_row.objectName(), "SettingsOpenBehaviorControl")
        self.assertGreaterEqual(open_mode_row.layout().contentsRect().height(), open_mode_combo.height())
        self.assertGreaterEqual(open_mode_combo.geometry().top(), 2)
        self.assertLessEqual(open_mode_combo.geometry().bottom(), open_mode_row.height() - 2)
        self.assertGreaterEqual(open_mode_row.height(), bind_button.height() + 4)
        self.assertGreaterEqual(bind_button.geometry().top(), 2)
        self.assertLessEqual(bind_button.geometry().bottom(), open_mode_row.height() - 3)
        self.assertGreaterEqual(open_mode_combo.geometry().left(), 4)
        self.assertLess(open_mode_combo.geometry().right(), bind_button.geometry().left())
        self.assertGreaterEqual(open_mode_row.width() - bind_button.geometry().right() - 1, 4)

        open_mode_combo.showPopup()
        self.app.processEvents()
        try:
            QTest.qWait(60)
            self.app.processEvents()
            open_view = open_mode_combo.view()
            open_popup = open_view.window()
            self.assertEqual(open_mode_combo.property("comboPopupMaxWidth"), open_mode_combo.width())
            self.assertEqual(open_view.property("comboPopupTargetWidth"), open_mode_combo.width())
            self.assertLessEqual(open_popup.width(), open_mode_combo.width())
        finally:
            open_mode_combo.hidePopup()
            open_mode_combo.view().window().hide()

    def test_gui_basic_settings_keep_control_column_aligned_in_english(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"

        shell.render(snapshot, changed_sections={"settings_snapshot"})
        shell.show_page("settings")
        shell.show()
        self.app.processEvents()

        settings = shell.pages["settings"]
        path_picker = next(iter(settings.findChildren(SettingsPathPicker)))
        filename_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.itemData(0) == "current"
        )
        open_mode_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.currentData() == "builtin_player"
        )

        controls = [path_picker, filename_combo.parentWidget(), open_mode_combo.parentWidget()]
        left_edges = [control.mapTo(settings, control.rect().topLeft()).x() for control in controls]
        widths = [control.width() for control in controls]

        self.assertEqual(left_edges, [left_edges[0]] * len(left_edges))
        self.assertEqual(widths, [widths[0]] * len(widths))

    def test_file_association_dialog_defaults_to_video_and_image(self):
        from app.ui.dialogs.file_association import FileAssociationDialog

        dialog = FileAssociationDialog()
        self.addCleanup(dialog.deleteLater)

        choice = dialog.choice()

        self.assertTrue(choice.include_video)
        self.assertTrue(choice.include_image)
        self.assertIn(theme_colors(dialog._is_dark)["accent"], dialog.styleSheet())
        self.assertIsNotNone(dialog.findChild(QPushButton, "DialogPrimaryButton"))
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogStatus"))

    def test_web_file_association_modal_matches_gui_confirmation_interaction(self):
        content = _html_bundle()
        css = _css_bundle()

        self.assertIn('id="fileAssociationModal" class="modal association-modal"', content)
        self.assertIn('id="associationTitle">绑定默认打开方式</h2>', content)
        self.assertIn('id="associationVideo" class="association-checkbox"', content)
        self.assertIn('id="associationImage" class="association-checkbox"', content)
        self.assertIn('id="associationCancelBtn"', content)
        self.assertIn('id="associationConfirmBtn"', content)
        self.assertIn('onclick="showFileAssociationModal()"', content)
        self.assertIn("function showFileAssociationModal()", content)
        self.assertIn("function confirmFileAssociationModal()", content)
        self.assertIn("function handleFileAssociationModalShortcut(event)", content)
        self.assertIn('if (event.key === "Enter") confirmFileAssociationModal();', content)
        self.assertIn("else cancelFileAssociationModal();", content)
        self.assertIn('window.applyFileAssociationLanguage === "function"', content)
        self.assertIn(".association-modal-box", css)
        self.assertIn("width: min(690px, 94vw);", css)
        self.assertIn(".association-option-list", css)
        self.assertIn(".association-status", css)
        self.assertIn("background: var(--panel-soft);", css)
        self.assertIn(".association-actions .btn", css)
        self.assertIn("height: 58px;", css)
        self.assertIn("width: 24px;", css)
        self.assertIn(".association-actions .btn:focus", css)
        self.assertIn(".association-checkbox:checked", css)
        self.assertIn(".association-checkbox:focus", css)

    def test_gui_selection_dialog_uses_scoped_theme_styles(self):
        from app.ui.dialogs.selection import SelectionDialog, SelectionTableDelegate

        dialog = SelectionDialog(None, items=[{"title": "测试视频"}])
        self.addCleanup(dialog.deleteLater)

        self.assertIn(theme_colors(dialog._is_dark)["accent"], dialog.styleSheet())
        self.assertIsNotNone(dialog.findChild(QTableWidget, "SelectionTable"))
        self.assertIsNotNone(dialog.findChild(QLabel, "SelectionDialogHeader"))
        self.assertTrue(dialog.btn_confirm.isDefault())
        self.assertEqual(dialog.table.selectionMode(), QTableWidget.SelectionMode.NoSelection)
        self.assertEqual(dialog.table.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(dialog.table.viewport().focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertIsInstance(dialog.table.itemDelegate(), SelectionTableDelegate)

        dialog.show()
        self.app.processEvents()
        dialog.table.setFocus()
        QTest.keyClick(dialog.table, Qt.Key.Key_Return)
        self.app.processEvents()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted.value)
        self.assertEqual(dialog.selected_indices, [0])

        esc_dialog = SelectionDialog(None, items=[{"title": "测试视频"}])
        self.addCleanup(esc_dialog.deleteLater)
        esc_dialog.show()
        self.app.processEvents()
        esc_dialog.table.setFocus()
        QTest.keyClick(esc_dialog.table, Qt.Key.Key_Escape)
        self.app.processEvents()

        self.assertFalse(esc_dialog.isVisible())
        self.assertEqual(esc_dialog.result(), QDialog.DialogCode.Rejected.value)

    def test_gui_selection_dialog_row_click_does_not_own_enter(self):
        from app.ui.dialogs.selection import SelectionDialog

        dialog = SelectionDialog(None, items=[{"title": "第一个"}, {"title": "第二个"}])
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        dialog.table.setCurrentCell(0, 0)
        dialog._on_cell_clicked(0, 0)
        self.assertFalse(dialog.table.currentIndex().isValid())

        QTest.keyClick(dialog.table.viewport(), Qt.Key.Key_Return)
        self.app.processEvents()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted.value)
        self.assertEqual(dialog.selected_indices, [1])

    def test_gui_selection_dialog_translates_dynamic_title_and_actions(self):
        from app.ui.dialogs.selection import SelectionDialog

        dialog = SelectionDialog(
            None,
            title="\u4efb\u52a1\u6e05\u5355\u786e\u8ba4 - Bilibili",
            items=[{"title": "video"}],
            language="en-US",
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.windowTitle(), "Task selection - Bilibili")
        self.assertIn("Scanned 1 resource", dialog.findChild(QLabel, "SelectionDialogHeader").text())
        self.assertEqual(dialog.btn_all.text(), "Select all")
        self.assertEqual(dialog.btn_invert.text(), "Invert")
        self.assertEqual(dialog.btn_cancel.text(), "Cancel task")
        self.assertEqual(dialog.btn_confirm.text(), "Start download")
        for button in (dialog.btn_all, dialog.btn_invert, dialog.btn_cancel, dialog.btn_confirm):
            self.assertGreaterEqual(button.minimumWidth(), button.sizeHint().width())
            self.assertGreater(button.minimumWidth(), button.fontMetrics().horizontalAdvance(button.text()) + 40)
        self.assertGreaterEqual(
            dialog.table.columnWidth(0),
            dialog.table.horizontalHeader().fontMetrics().horizontalAdvance("Select") + 30,
        )

    def test_gui_top_bar_platform_placeholder_uses_language_contract(self):
        from app.ui.layout.top_bar import TopBarWidget

        top_bar = TopBarWidget(is_dark_theme=False)
        self.addCleanup(top_bar.deleteLater)

        top_bar.set_language("zh-CN")
        top_bar.set_platform_placeholder("bilibili")
        self.assertIn("BV号", top_bar.inp_search.placeholderText())

        top_bar.set_language("en-US")
        self.assertIn("BV ID", top_bar.inp_search.placeholderText())

        top_bar.set_platform_placeholder("xiaohongshu")
        self.assertIn("Xiaohongshu ID", top_bar.inp_search.placeholderText())

    def test_gui_top_bar_directory_button_resizes_for_translations(self):
        from app.ui.layout.top_bar import TopBarWidget

        top_bar = TopBarWidget(is_dark_theme=False)
        self.addCleanup(top_bar.deleteLater)

        for language in ("zh-CN", "en-US", "zh-TW"):
            top_bar.set_language(language)
            self.app.processEvents()
            button = top_bar.btn_dir
            self.assertGreaterEqual(button.minimumWidth(), button.sizeHint().width())
            self.assertGreaterEqual(button.maximumWidth(), button.sizeHint().width())

    def test_gui_top_bar_theme_busy_keeps_button_clickable(self):
        from app.ui.layout.top_bar import TopBarWidget

        top_bar = TopBarWidget(is_dark_theme=False)
        self.addCleanup(top_bar.deleteLater)

        top_bar.set_theme_button_busy(True)
        self.assertTrue(top_bar.btn_theme.isEnabled())
        self.assertEqual(top_bar.btn_theme.property("themeBusy"), "true")

        top_bar.set_theme_button_busy(False)
        self.assertTrue(top_bar.btn_theme.isEnabled())
        self.assertEqual(top_bar.btn_theme.property("themeBusy"), "false")

    def test_web_selection_modal_matches_gui_confirmation_interaction(self):
        content = _html_bundle()
        css = _css_bundle()

        self.assertIn('id="selectionModal" class="modal selection-modal"', content)
        self.assertIn('role="dialog"', content)
        self.assertIn('id="selectionTitle" class="sr-only">任务清单确认</h2>', content)
        self.assertIn(".sr-only", css)
        self.assertIn('id="selectionHeader" class="selection-header"', content)
        self.assertIn("<th>选择</th><th>视频标题 / 描述</th>", content)
        self.assertIn('id="selectionAllBtn"', content)
        self.assertIn('id="selectionInvertBtn"', content)
        self.assertIn('id="selectionCancelBtn"', content)
        self.assertIn('id="selectionConfirmBtn"', content)
        self.assertIn("function selectAllSelectionItems", content)
        self.assertIn("function invertSelectionItems", content)
        self.assertIn("function toggleSelectionItem", content)
        self.assertIn('tabindex="-1"', content)
        self.assertIn('aria-checked="true"', content)
        self.assertIn('onmousedown="event.preventDefault()"', content)
        self.assertIn('byId("selectionConfirmBtn").focus', content)
        self.assertIn("sendWS(\"select_tasks\", { indices: null })", content)
        self.assertIn('document.addEventListener("keydown", event => {', content)
        self.assertIn("}, true);", content)
        self.assertIn(".selection-modal-box", css)
        self.assertIn("width: min(1200px, 94vw);", css)
        self.assertIn("height: min(900px, 88vh);", css)
        self.assertIn(".selection-table-shell", css)
        self.assertIn("height: 50px;", css)
        self.assertIn("width: 72px;", css)
        self.assertIn("width: 22px;", css)
        self.assertIn(".selection-bulk-actions .btn", css)
        self.assertIn("min-width: 120px;", css)
        self.assertIn("height: 50px;", css)
        self.assertIn(".selection-primary-actions .btn", css)
        self.assertIn("height: 54px;", css)
        self.assertIn("#selectionCancelBtn", css)
        self.assertIn("min-width: 150px;", css)
        self.assertIn("#selectionConfirmBtn", css)
        self.assertIn("min-width: 180px;", css)
        self.assertIn(".selection-row:focus", css)
        self.assertIn(".selection-row.unchecked td", css)
        self.assertIn("appearance: none", css)
        self.assertIn(".selection-checkbox:checked", css)
        self.assertIn("checkbox.setAttribute(\"aria-checked\"", content)

    def test_gui_platform_settings_proxy_combo_uses_boolean_enabled_state(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        platform_nav = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.property("groupName") == "\u5e73\u53f0\u8bbe\u7f6e"
        )
        platform_nav.click()
        self.app.processEvents()

        proxy_combos = [
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.property("proxyCustomAllowed") is not None
        ]
        self.assertGreaterEqual(len(proxy_combos), 1)
        self.assertTrue(all(isinstance(combo.isEnabled(), bool) for combo in proxy_combos))
        self.assertFalse(
            any(combo.isVisible() and combo.currentText() == "\u5f53\u524d\u547d\u540d\u65b9\u5f0f" for combo in settings.findChildren(QComboBox))
        )
        self.assertTrue(
            any(
                str(combo.currentData()) in {"10", "20", "30", "50", "9999"}
                for combo in settings.findChildren(QComboBox)
            )
        )

    def test_gui_platform_settings_show_page_counts_and_editable_custom_proxy_combo(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        self.app.processEvents()

        platform_nav = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.property("groupName") == "\u5e73\u53f0\u8bbe\u7f6e"
        )
        platform_nav.click()
        self.app.processEvents()

        combo_texts = [combo.currentText() for combo in settings.findChildren(QComboBox)]
        self.assertTrue(any("\u7bc7\u7b14\u8bb0" in text for text in combo_texts))
        self.assertTrue(any("页" in text for text in combo_texts))
        self.assertTrue(any("个视频" in text for text in combo_texts))
        self.assertTrue(any("秒" in text for text in combo_texts))
        proxy_inputs = [
            edit
            for edit in settings.findChildren(QLineEdit)
            if edit.objectName() == "SettingsProxyCustomEdit"
        ]
        self.assertTrue(proxy_inputs)
        self.assertTrue(any(edit.isEnabled() for edit in proxy_inputs))
        missav_proxy_combos = [
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.property("proxyCustomAllowed") == "true"
        ]
        self.assertTrue(missav_proxy_combos)
        self.assertTrue(all(not combo.isEditable() for combo in missav_proxy_combos))
        self.assertTrue(any(combo.property("customProxy") == "true" for combo in missav_proxy_combos))
        proxy_texts = [missav_proxy_combos[0].itemText(index) for index in range(missav_proxy_combos[0].count())]
        self.assertTrue(any("V2Ray / Qv2ray" in text for text in proxy_texts))
        self.assertFalse(any("(10808)" in text for text in proxy_texts))
        self.assertFalse(any("HTTP/SOCKS5" in text for text in proxy_texts))

    def test_gui_platform_settings_only_shows_custom_proxy_input_when_needed(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        snapshot = FrontendStateService.mock_snapshot()
        missav = next(row for row in snapshot["settings_snapshot"]["\u5e73\u53f0\u8bbe\u7f6e"] if row["id"] == "missav")
        missav["proxy"] = "\u7cfb\u7edf\u4ee3\u7406"
        missav["proxy_custom_active"] = False
        missav["proxy_custom_value"] = ""

        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        shell.show_page("settings")
        settings.render(snapshot)
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()

        proxy_input = next(
            edit
            for edit in settings.findChildren(QLineEdit)
            if edit.objectName() == "SettingsProxyCustomEdit"
        )
        proxy_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.objectName() == "SettingsCombo" and combo.property("proxyCustomAllowed") == "true"
        )
        container = proxy_input.parentWidget()
        self.assertTrue(proxy_input.isHidden())
        self.assertFalse(proxy_input.isEnabled())
        self.assertEqual(proxy_input.placeholderText(), "\u7aef\u53e3")
        self.assertGreaterEqual(proxy_combo.width(), container.width() - 2)

        custom_index = proxy_combo.findData("\u81ea\u5b9a\u4e49")
        self.assertGreaterEqual(custom_index, 0)
        proxy_combo.setCurrentIndex(custom_index)
        self.app.processEvents()

        self.assertFalse(proxy_input.isHidden())
        self.assertTrue(proxy_input.isEnabled())
        self.assertLess(proxy_combo.width(), container.width())

    def test_gui_platform_custom_proxy_field_stays_inside_scrolled_viewport(self):
        shell = self._make_shell()
        shell.resize(760, 520)
        settings = shell.pages["settings"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        base_rows = snapshot["settings_snapshot"]["\u5e73\u53f0\u8bbe\u7f6e"]
        rows = []
        for index in range(8):
            row = deepcopy(base_rows[index % len(base_rows)])
            row["id"] = f"{row['id']}_{index}"
            row["name"] = f"{row['name']} {index}"
            if index == 3:
                row.update(
                    {
                        "id": "missav",
                        "name": "MissAV",
                        "proxy": "\u81ea\u5b9a\u4e49",
                        "proxy_config_key": "proxy_app",
                        "proxy_editable": True,
                        "proxy_custom_allowed": True,
                        "proxy_custom_active": True,
                        "proxy_custom_value": "http://127.0.0.1:7890",
                    }
                )
            rows.append(row)
        snapshot["settings_snapshot"]["\u5e73\u53f0\u8bbe\u7f6e"] = rows

        shell.show_page("settings")
        shell.show()
        settings.render(snapshot)
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()

        scroll = settings.findChild(QScrollArea, "SettingsPlatformScroll")
        self.assertIsNotNone(scroll)
        proxy_input = next(
            edit
            for edit in settings.findChildren(QLineEdit)
            if edit.objectName() == "SettingsProxyCustomEdit" and edit.isEnabled()
        )
        container = proxy_input.parentWidget()
        input_right = proxy_input.mapTo(scroll.viewport(), proxy_input.rect().topRight()).x()
        container_right = container.mapTo(scroll.viewport(), container.rect().topRight()).x()
        col_widths = settings._platform_col_widths(rows, reserve_vertical_scrollbar=True)

        self.assertEqual(container.width(), col_widths["proxy"])
        self.assertEqual(container.property("customProxySurface"), "split")
        self.assertGreaterEqual(proxy_input.width(), 80)
        self.assertLessEqual(proxy_input.height(), container.height())
        self.assertFalse(proxy_input.isClearButtonEnabled())
        self.assertLessEqual(input_right, scroll.viewport().width())
        self.assertLessEqual(container_right, scroll.viewport().width())

    def test_gui_platform_custom_proxy_splits_into_two_bounded_fields_in_compact_layout(self):
        shell = self._make_shell()
        shell.resize(760, 520)
        settings = shell.pages["settings"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"
        missav = next(
            row for row in snapshot["settings_snapshot"]["\u5e73\u53f0\u8bbe\u7f6e"] if row["id"] == "missav"
        )
        missav["proxy"] = "\u81ea\u5b9a\u4e49"
        missav["proxy_config_key"] = "proxy_app"
        missav["proxy_editable"] = True
        missav["proxy_custom_allowed"] = True
        missav["proxy_custom_active"] = True
        missav["proxy_custom_value"] = "7890"

        shell.show_page("settings")
        shell.show()
        settings.render(snapshot)
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()

        proxy_input = next(
            edit
            for edit in settings.findChildren(QLineEdit)
            if edit.objectName() == "SettingsProxyCustomEdit" and edit.isEnabled()
        )
        container = proxy_input.parentWidget()
        proxy_combo = next(combo for combo in settings.findChildren(QComboBox) if combo.parentWidget() is container)
        container_right = container.mapTo(container, container.rect().topRight()).x()
        input_right = proxy_input.mapTo(container, proxy_input.rect().topRight()).x()
        input_top = proxy_input.mapTo(container, proxy_input.rect().topLeft()).y()
        input_bottom = proxy_input.mapTo(container, proxy_input.rect().bottomRight()).y()
        combo_bottom = proxy_combo.mapTo(container, proxy_combo.rect().bottomRight()).y()
        spacing = container.layout().spacing()

        self.assertEqual(container.property("customProxySurface"), "split")
        self.assertEqual(container.property("customProxyActive"), "true")
        self.assertEqual(proxy_combo.property("proxyEmbedded"), "false")
        self.assertEqual(proxy_input.property("proxyEmbedded"), "false")
        self.assertEqual(proxy_combo.width() + spacing + proxy_input.width(), container.width())
        self.assertGreaterEqual(proxy_input.width(), 80)
        self.assertGreaterEqual(input_top, 0)
        self.assertLessEqual(input_bottom, container.height() - 1)
        self.assertLessEqual(combo_bottom, container.height() - 1)
        self.assertLessEqual(input_right, container_right)

    def test_gui_top_quantity_hotloads_from_platform_settings_snapshot(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"
        platform_rows = snapshot["settings_snapshot"]["平台设置"]
        douyin = next(row for row in platform_rows if row["id"] == "douyin")
        douyin["default_count"] = 50

        index = shell.sidebar.combo_source.findData("douyin")
        self.assertGreaterEqual(index, 0)
        shell.sidebar.combo_source.setCurrentIndex(index)
        shell.render(snapshot)

        self.assertEqual(shell.top_bar.combo_video_count.currentData(), 50)
        self.assertEqual(shell.top_bar.combo_video_count.currentText(), "50 个视频")
        self.assertEqual(
            [shell.top_bar.combo_video_count.itemText(i) for i in range(shell.top_bar.combo_video_count.count())],
            [option["label"] for option in douyin["count_options"]],
        )

        douyin["default_count"] = 30
        shell.render(snapshot, changed_sections={"settings_snapshot"})

        self.assertEqual(shell.top_bar.combo_video_count.currentData(), 30)
        self.assertEqual(shell.top_bar.combo_video_count.currentText(), "30 个视频")

    def test_gui_top_quantity_uses_platform_units_pages_notes_and_max(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"

        bilibili_index = shell.sidebar.combo_source.findData("bilibili")
        self.assertGreaterEqual(bilibili_index, 0)
        shell.sidebar.combo_source.setCurrentIndex(bilibili_index)
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        combo = shell.top_bar.combo_video_count
        self.assertEqual(shell.top_bar.quantity_mode(), "pages")
        self.assertEqual(shell.top_bar.video_count_label.text(), "页数:")
        self.assertEqual(combo.currentData(), 1)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["1 页（推荐）", "2 页", "3 页", "5 页", "max"])

        xhs_index = shell.sidebar.combo_source.findData("xiaohongshu")
        self.assertGreaterEqual(xhs_index, 0)
        shell.sidebar.combo_source.setCurrentIndex(xhs_index)
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        self.assertEqual(shell.top_bar.quantity_mode(), "notes")
        self.assertEqual(shell.top_bar.video_count_label.text(), "笔记数:")
        self.assertEqual(combo.currentData(), 20)
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
            ["10 篇笔记", "20 篇笔记（推荐）", "30 篇笔记", "50 篇笔记", "max"],
        )

    def test_gui_top_quantity_control_and_popup_use_longest_option_width(self):
        shell = self._make_shell()
        combo = shell.top_bar.combo_video_count
        recommended_index = combo.findText("20 个视频（推荐）")
        fifty_index = combo.findData(50)
        ten_index = combo.findData(10)
        self.assertGreaterEqual(recommended_index, 0)
        self.assertGreaterEqual(fifty_index, 0)
        self.assertGreaterEqual(ten_index, 0)

        combo.setCurrentIndex(recommended_index)
        self.app.processEvents()
        recommended_width = combo.width()
        widest_text = combo_widest_item_text_width(combo)

        combo.setCurrentIndex(fifty_index)
        self.app.processEvents()
        fifty_width = combo.width()

        combo.setCurrentIndex(ten_index)
        self.app.processEvents()

        self.assertEqual(combo.width(), recommended_width)
        self.assertEqual(combo.width(), fifty_width)
        self.assertGreaterEqual(combo_edit_field_width(combo), widest_text)
        self.assertLessEqual(combo.width(), widest_text + 24)
        self.assertEqual(combo.property("comboPopupMaxWidth"), combo.width())

        combo.showPopup()
        self.app.processEvents()
        try:
            self.assertEqual(combo.view().width(), combo.width())
            self.assertGreaterEqual(combo_edit_field_width(combo), widest_text)
            self._assert_combo_selected_row_paints_to_right_edge(combo)
        finally:
            combo.hidePopup()
            combo.view().window().hide()

    def test_gui_top_quantity_english_label_fits_without_truncation(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"

        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        combo = shell.top_bar.combo_video_count
        self.assertNotIn("Recommended", combo.currentText())
        self.assertGreaterEqual(combo_edit_field_width(combo), combo_widest_item_text_width(combo))
        self.assertLessEqual(combo.width(), combo_widest_item_text_width(combo) + 24)

    def test_gui_top_quantity_chinese_recommended_label_refits_after_font_change(self):
        shell = self._make_shell()
        combo = shell.top_bar.combo_video_count
        recommended_index = combo.findText("20 个视频（推荐）")
        self.assertGreaterEqual(recommended_index, 0)
        combo.setCurrentIndex(recommended_index)
        larger_font = QFont(combo.font())
        larger_font.setPointSize(max(larger_font.pointSize() + 5, 16))
        combo.setFont(larger_font)

        shell.top_bar.set_theme_icon(shell.is_dark_theme)
        self.app.processEvents()

        required = combo_widest_item_text_width(combo)
        self.assertGreaterEqual(combo_edit_field_width(combo), required)
        self.assertLessEqual(combo.width(), required + 24)
        self.assertEqual(combo.property("comboPopupMaxWidth"), combo.width())

    def test_gui_settings_snapshot_same_language_does_not_rebuild_top_controls(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["font_size"] = "large"
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"

        with (
            patch.object(shell.top_bar, "set_language", wraps=shell.top_bar.set_language) as top_language,
            patch.object(shell.sidebar, "set_language", wraps=shell.sidebar.set_language) as sidebar_language,
            patch.object(
                shell.top_bar,
                "configure_for_platform",
                wraps=shell.top_bar.configure_for_platform,
            ) as configure_platform,
            patch.object(shell, "_translate_page", wraps=shell._translate_page) as translate_page,
        ):
            shell.render(snapshot, changed_sections={"settings_snapshot"})
            self.app.processEvents()

        top_language.assert_not_called()
        sidebar_language.assert_not_called()
        configure_platform.assert_not_called()
        translate_page.assert_not_called()

    def test_gui_active_progress_delta_keeps_static_translation_stable(self):
        shell = self._make_shell()
        shell.show_page("active")
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        active_page = shell.pages["active"]
        self.assertEqual(active_page.detail_title.text(), "Current download")
        changed_snapshot = deepcopy(snapshot)
        changed_snapshot["active_downloads"][0]["progress"] = 77
        changed_snapshot["active_downloads"][0]["chunk_progress"]["percent"] = 77
        changed_snapshot["active_downloads"][0]["speed"] = "2.4 MB/s"

        with patch.object(shell, "_translate_page", wraps=shell._translate_page) as translate_page:
            shell.render(changed_snapshot, changed_sections={"active_downloads", "app_status"})
            self.app.processEvents()

        translate_page.assert_not_called()
        self.assertEqual(active_page.detail_title.text(), "Current download")

    def test_gui_settings_language_snapshot_updates_visible_labels(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        snapshot["settings_snapshot"]["外观设置"]["accent"] = "red"
        snapshot["settings_snapshot"]["外观设置"]["font_size"] = "large"

        settings.render(snapshot)
        settings._set_current_group("外观设置")
        self.app.processEvents()

        nav_texts = {button.text() for button in settings.findChildren(QPushButton)}
        self.assertIn("Appearance", nav_texts)
        self.assertEqual(settings.page_title.text(), "Settings")
        combo_texts = {combo.currentText() for combo in settings.findChildren(QComboBox)}
        self.assertIn("English", combo_texts)
        self.assertIn("Red", combo_texts)
        self.assertIn("Large", combo_texts)
        label_texts = {label.text() for label in settings.findChildren(QLabel)}
        self.assertIn("Interface language", label_texts)
        self.assertIn("Appearance changes apply immediately and are saved locally.", label_texts)

        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()
        platform_names = {
            label.toolTip()
            for label in settings.findChildren(QLabel, "SettingsPlatformName")
        }
        self.assertIn("Douyin", platform_names)
        self.assertIn("Xiaohongshu", platform_names)
        self.assertIn("Kuaishou", platform_names)
        self.assertNotIn("\u6296\u97f3", platform_names)
        self.assertNotIn("\u5c0f\u7ea2\u4e66", platform_names)
        self.assertNotIn("\u5feb\u624b", platform_names)
        combo_texts = {combo.currentText() for combo in settings.findChildren(QComboBox)}
        self.assertIn("Custom", combo_texts)

    def test_gui_language_switch_translates_sidebar_platform_combo(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"

        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        combo = shell.sidebar.combo_source
        texts = {combo.itemText(index) for index in range(combo.count())}
        self.assertIn("Douyin", texts)
        self.assertIn("Xiaohongshu", texts)
        self.assertIn("Kuaishou", texts)
        self.assertNotIn("\u6296\u97f3", texts)
        self.assertNotIn("\u5c0f\u7ea2\u4e66", texts)
        self.assertNotIn("\u5feb\u624b", texts)

    def test_gui_active_timeline_translates_dynamic_event_messages(self):
        self.assertEqual(
            localize_active_event_message("\u4efb\u52a1\u8fdb\u5165 \u6296\u97f3 \u4e0b\u8f7d\u5668", "en-US"),
            "Task entered Douyin downloader",
        )
        self.assertEqual(
            localize_active_event_message("\u4efb\u52a1\u8fdb\u5165 Bilibili \u4e0b\u8f7d\u5668", "en-US"),
            "Task entered Bilibili downloader",
        )
        self.assertEqual(
            localize_active_event_message("\u97f3\u89c6\u9891\u6d41\u4e0b\u8f7d\u4e2d", "en-US"),
            "Audio/video stream downloading",
        )
        self.assertEqual(
            localize_active_event_message(
                "\u5f53\u524d\u901f\u5ea6\uff1a1.0 MB/s\uff0c\u5269\u4f59\uff1a00:47",
                "en-US",
            ),
            "Current speed: 1.0 MB/s, remaining: 00:47",
        )

    def test_gui_active_timeline_uses_worker_prepared_display_events(self):
        item = {
            "id": "active-1",
            "events": [
                {
                    "time": "20:20:48",
                    "message": "\u4efb\u52a1\u8fdb\u5165 Bilibili \u4e0b\u8f7d\u5668",
                },
                {
                    "time": "20:20:49",
                    "message": "\u5f53\u524d\u901f\u5ea6\uff1a1.0 MB/s\uff0c\u5269\u4f59\uff1a00:47",
                },
            ],
        }

        projected = prepare_active_item_for_display(item, language="en-US")

        self.assertEqual(
            [event["message_display"] for event in projected["events_display"]],
            [
                "Task entered Bilibili downloader",
                "Current speed: 1.0 MB/s, remaining: 00:47",
            ],
        )
        self.assertEqual(item["events"][0]["message"], "\u4efb\u52a1\u8fdb\u5165 Bilibili \u4e0b\u8f7d\u5668")

    def test_gui_settings_language_rebuild_closes_open_combo_popup(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        settings.render(snapshot)
        settings._set_current_group("外观设置")
        self.app.processEvents()

        language_combo = next(
            combo
            for combo in settings.findChildren(QComboBox)
            if combo.findData("en-US") >= 0 and combo.findData("zh-CN") >= 0
        )
        language_combo.showPopup()
        self.app.processEvents()

        changed_snapshot = deepcopy(snapshot)
        changed_snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        with patch.object(settings, "_close_combo_popups", wraps=settings._close_combo_popups) as close_popups:
            settings.render(changed_snapshot)
            self.app.processEvents()

        self.assertGreaterEqual(close_popups.call_count, 1)
        self.assertEqual(settings._language(), "en-US")

    def test_gui_page_switch_closes_combo_popups_and_leaked_popup_windows(self):
        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]

        logs.level_filter.showPopup()
        leaked_popup = QWidget()
        self.addCleanup(leaked_popup.deleteLater)
        leaked_popup.setObjectName("PolishedComboPopupWindow")
        leaked_popup.setWindowFlag(Qt.WindowType.Window, True)
        leaked_popup.show()
        self.app.processEvents()

        shell.show_page("queue", emit_change=False)
        self.app.processEvents()

        self.assertFalse(leaked_popup.isVisible())
        self.assertEqual(logs.level_filter.property("popupOpen"), "false")

    def test_gui_language_switch_restores_shell_and_page_texts(self):
        shell = self._make_shell()
        shell.show_page("logs")
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"

        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        self.assertEqual(shell.sidebar._items["queue"].title_label.text(), "Queue")
        self.assertEqual(shell.top_bar.btn_dir.text(), "Change folder")
        logs = shell.pages["logs"]
        log_title = logs.findChild(QLabel, "LogInspectorTitle")
        self.assertIsNotNone(log_title)
        self.assertEqual(log_title.text(), "Log details")
        self.assertEqual(logs.level_filter.currentText(), "All")
        self.assertEqual(logs.level_filter.currentData(), "全部")
        self.assertEqual(logs.page_size_combo.currentText(), "20 / page")
        self.assertEqual(logs.page_size_combo.currentData(), 20)
        self.assertEqual(logs._log_action_buttons["refresh"].text(), "Refresh")
        self.assertEqual(logs._log_action_buttons["clear"].text(), "Clear")
        self.assertEqual(logs._log_action_buttons["export"].text(), "Export")
        self.assertEqual(logs._log_action_buttons["copy_trace_id"].text(), "Copy TraceID")
        self.assertEqual(logs.detail_copy_button.text(), "Copy")
        self.assertEqual(logs.detail_export_button.text(), "Export")
        self.assertEqual(logs.json_copy_button.text(), "Copy")
        page_size = logs.page_size_combo
        widest_page_size = combo_widest_item_text_width(page_size)
        self.assertGreaterEqual(combo_edit_field_width(page_size), widest_page_size)
        self.assertLessEqual(page_size.width(), widest_page_size + 24)
        for button in (*logs._log_action_buttons.values(), logs.detail_copy_button, logs.detail_export_button, logs.json_copy_button):
            text_width = button.fontMetrics().horizontalAdvance(button.text())
            self.assertGreaterEqual(button.minimumWidth(), text_width + 20)
        detail_key_labels = {label.text(): label for label in logs.findChildren(QLabel, "LogDetailKey")}
        self.assertIn("Event code", detail_key_labels)
        for label in detail_key_labels.values():
            text_width = label.fontMetrics().horizontalAdvance(label.text())
            self.assertGreaterEqual(label.minimumWidth(), text_width + 8)

        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        self.assertEqual(shell.sidebar._items["queue"].title_label.text(), "下载队列")
        self.assertEqual(shell.top_bar.btn_dir.text(), "更改目录")
        self.assertEqual(log_title.text(), "日志详情")
        self.assertEqual(logs._log_action_buttons["refresh"].text(), "刷新")
        self.assertEqual(logs.detail_copy_button.text(), "复制")
        detail_key_labels = {label.text(): label for label in logs.findChildren(QLabel, "LogDetailKey")}
        self.assertIn("事件码", detail_key_labels)

    def test_gui_language_switch_updates_logs_without_filter_refresh_signal(self):
        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]
        calls: list[str] = []
        logs.level_filter.currentTextChanged.connect(lambda *_args: calls.append("level"))
        logs.time_filter.currentTextChanged.connect(lambda *_args: calls.append("time"))
        logs.platform_filter.currentIndexChanged.connect(lambda *_args: calls.append("platform"))

        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        self.assertEqual([], calls)
        self.assertEqual(logs.level_filter.currentText(), "All")
        self.assertEqual(logs.level_filter.currentData(), "\u5168\u90e8")

    def test_log_detail_copy_and_export_use_visible_inspector_item(self):
        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]
        logs.time_filter.setCurrentText("全部")
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["log_items"] = [
            {
                "id": "log-copy-export",
                "time": "2026-06-30 00:35:35",
                "level": "INFO",
                "raw_level": "INFO",
                "source": "ApplicationController",
                "platform": "\u7cfb\u7edf",
                "trace_id": "trace-log-copy-export",
                "message": "\u5e94\u7528\u5f00\u59cb\u521d\u59cb\u5316",
                "message_summary": "\u5e94\u7528\u5f00\u59cb\u521d\u59cb\u5316",
                "detail": {
                    "description": "\u5e94\u7528\u5f00\u59cb\u521d\u59cb\u5316",
                    "status_code": "APP_INIT",
                },
            }
        ]

        shell.render(snapshot, changed_sections={"log_items"})
        self._wait_for_log_rows(logs, 1)
        message_index = logs.table.model().index(0, 4)
        self.assertEqual(
            message_index.data(Qt.ItemDataRole.TextAlignmentRole),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter),
        )
        self._wait_for_log_detail_status_code(logs, "APP_INIT")
        self.assertTrue(logs.detail_copy_button.isEnabled())
        self.assertTrue(logs.detail_export_button.isEnabled())
        self.assertTrue(logs.json_copy_button.isEnabled())

        logs.table.clearSelection()
        logs.table.setCurrentIndex(QModelIndex())

        QApplication.clipboard().clear()
        logs.detail_copy_button.click()
        self.app.processEvents()
        self.assertIn("APP_INIT", QApplication.clipboard().text())
        self.assertIn("trace-log-copy-export", QApplication.clipboard().text())

        logs.json_copy_button.click()
        self.app.processEvents()
        self.assertIn("description", QApplication.clipboard().text())
        self.assertIn("APP_INIT", QApplication.clipboard().text())

        logs.copy_trace_button.click()
        self.app.processEvents()
        self.assertEqual("trace-log-copy-export", QApplication.clipboard().text())

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = Path(tmpdir) / "log_detail.json"
            with (
                patch(
                    "app.ui.pages.log_center_page.QFileDialog.getSaveFileName",
                    return_value=(str(export_path), "JSON 文件 (*.json)"),
                ),
                patch("app.ui.pages.log_center_page.QMessageBox.information"),
            ):
                logs.detail_export_button.click()
                for _ in range(100):
                    self.app.processEvents()
                    if export_path.exists():
                        break
                    QTest.qWait(20)
            self.assertTrue(export_path.exists())
            exported = export_path.read_text(encoding="utf-8")
            self.assertIn("APP_INIT", exported)
            self.assertIn("trace-log-copy-export", exported)

    def test_gui_language_switch_updates_model_view_table_headers(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()
        model = active.table.model()
        self.assertEqual(model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "Title")

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()
        self.assertEqual(model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "\u6807\u9898")

    def test_gui_language_switch_restores_ambiguous_table_headers_after_english_first_render(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        expected_en = {
            "queue": ["Title", "Platform", "Status", "Actions"],
            "active": ["Title", "Platform", "Progress", "Speed", "Remaining", "Actions"],
            "completed": ["Title", "Completed at", "Duration", "Format", "Actions"],
            "failed": ["Title", "Failed at", "Reason", "Status", "Actions"],
            "logs": ["Time", "Level", "Source", "Trace ID", "Summary"],
        }
        expected_zh = {
            "queue": ["\u89c6\u9891\u6807\u9898", "\u5e73\u53f0", "\u72b6\u6001", "\u64cd\u4f5c"],
            "active": ["\u6807\u9898", "\u5e73\u53f0", "\u8fdb\u5ea6", "\u901f\u5ea6", "\u5269\u4f59\u65f6\u95f4", "\u64cd\u4f5c"],
            "completed": ["\u6807\u9898", "\u5b8c\u6210\u65f6\u95f4", "\u65f6\u957f", "\u683c\u5f0f", "\u64cd\u4f5c"],
            "failed": ["\u6807\u9898", "\u5931\u8d25\u65f6\u95f4", "\u5931\u8d25\u539f\u56e0", "\u72b6\u6001", "\u64cd\u4f5c"],
            "logs": ["\u65f6\u95f4", "\u7ea7\u522b", "\u6765\u6e90", "Trace ID", "\u6d88\u606f\u6458\u8981"],
        }

        for page_id, headers in expected_en.items():
            shell.show_page(page_id)
            self.app.processEvents()
            model = shell.pages[page_id].table.model()
            actual = [
                str(model.headerData(index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
                for index in range(model.columnCount())
            ]
            self.assertEqual(actual, headers, page_id)
            self.assertEqual(getattr(model, "_headers", None), expected_zh[page_id], page_id)

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        for page_id, headers in expected_zh.items():
            shell.show_page(page_id)
            self.app.processEvents()
            model = shell.pages[page_id].table.model()
            actual = [
                str(model.headerData(index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
                for index in range(model.columnCount())
            ]
            self.assertEqual(actual, headers, page_id)

    def test_gui_language_switch_translates_dynamic_runtime_surfaces(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        snapshot["log_items"] = [
            {
                "id": "gui-i18n-log",
                "time": "2026-07-05 12:00:00",
                "level": "INFO",
                "raw_level": "INFO",
                "source": "GUI",
                "platform": "\u7cfb\u7edf",
                "platform_id": "system",
                "trace_id": "trace-gui-i18n",
                "message": "\u5e94\u7528\u5f00\u59cb\u521d\u59cb\u5316",
                "message_summary": "\u5e94\u7528\u5f00\u59cb\u521d\u59cb\u5316",
            }
        ]
        snapshot["queue_items"] = []
        snapshot["active_downloads"] = []
        snapshot["completed_items"] = [
            {
                "id": "done-gui-i18n",
                "title": "Demo",
                "filename": "demo.mp4",
                "local_path": "D:/Downloads/demo.mp4",
                "completed_at": "2026-07-05 12:00:00",
                "completed_at_table": "12:00:00",
                "duration": "00:01:00",
                "resolution": "1280 x 720",
                "size": "1 MB",
                "format": "MP4",
                "platform": "\u7cfb\u7edf",
                "platform_id": "system",
            }
        ]
        snapshot["failed_items"] = []

        shell.show_page("logs")
        logs = shell.pages["logs"]
        all_time_index = logs.time_filter.findData("\u5168\u90e8")
        self.assertGreaterEqual(all_time_index, 0)
        logs.time_filter.setCurrentIndex(all_time_index)
        shell.render(snapshot, changed_sections={"settings_snapshot", "log_items"})
        self._wait_for_log_rows(logs, 1)

        self.assertTrue(logs._tab_buttons["all"].text().startswith("All logs"))
        self.assertTrue(logs.footer_stats.text().startswith("Total 1 / matched 1 / showing 1"))
        self.assertEqual(logs.page_indicator.text(), "Page 1 / 1")
        self.assertTrue(logs.platform_filter.currentText().endswith("All"))
        self.assertEqual(logs.detail_platform_value.text(), "\u2699\ufe0f System")
        self.assertEqual(logs.detail_status_value.text(), "Process")
        self.assertEqual(logs.detail_scope_value.text(), "System")
        self.assertEqual(logs.detail_stage_value.text(), "Step")

        shell.show_page("queue")
        shell.render(snapshot, changed_sections={"settings_snapshot", "queue_items"})
        queue = shell.pages["queue"]
        self._wait_until(lambda: queue.event_body.text() == "No queued tasks", message="queue empty text was not translated")
        self.assertEqual(queue.path_prefix_label.text(), "Save to:")
        self.assertEqual(queue.event_title.text(), "Activity (latest 3)")
        self.assertEqual(queue.event_body.text(), "No queued tasks")
        self.assertEqual(queue.table.model().headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "Title")

        shell.show_page("active")
        shell.render(snapshot, changed_sections={"settings_snapshot", "active_downloads", "app_status"})
        active = shell.pages["active"]
        self._wait_until(lambda: active.running_count_label.text() == "Running: 0 tasks", message="active count was not translated")
        self.assertEqual(active.detail_events_title.text(), "Current task events")
        self.assertEqual(active.running_count_label.text(), "Running: 0 tasks")

        snapshot["completed_items"][0]["duration"] = "--"
        snapshot["completed_items"][0]["resolution"] = "--"
        snapshot["completed_items"][0]["metadata_pending"] = True
        shell.show_page("completed")
        shell.render(snapshot, changed_sections={"settings_snapshot", "completed_items"})
        completed = shell.pages["completed"]
        self._wait_for_table_rows(completed.table, 1)
        completed_model = completed.table.model()
        self.assertEqual(
            completed_model.data(completed_model.index(0, 2), Qt.ItemDataRole.DisplayRole),
            "Checking",
        )
        completed_labels = {label.text() for label in completed.info_body.findChildren(QLabel)}
        self.assertEqual(completed.info_title.text(), "File info")
        self.assertIn("Filename", completed_labels)
        self.assertIn("Save path", completed_labels)
        self.assertIn("Checking", completed_labels)
        self.assertNotIn("检测中", completed_labels)

        shell.show_page("failed")
        shell.render(snapshot, changed_sections={"settings_snapshot", "failed_items"})
        failed = shell.pages["failed"]
        self._wait_until(
            lambda: "No failed tasks" in {label.text() for label in failed.findChildren(QLabel)},
            message="failed empty text was not translated",
        )
        failed_labels = {label.text() for label in failed.findChildren(QLabel)}
        self.assertEqual(failed.detail_title.text(), "Error details")
        self.assertEqual(failed.solutions_title.text(), "Possible fixes")
        self.assertIn("No failed tasks", failed_labels)

    def test_failed_page_localizes_dynamic_error_details_and_solutions(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        title = "P05_末日废土生存指南"
        error = (
            "B站下载失败: B站流下载失败: "
            "('Connection aborted.', ConnectionResetError(10054, "
            "'远程主机强迫关闭了一个现有的连接。', None, 10054, None))"
        )
        snapshot["failed_items"] = [
            {
                "id": "failed-gui-i18n",
                "title": title,
                "failed_at": "2026-07-06 18:38:14",
                "failed_at_table": "07-06 18:38",
                "reason": error,
                "reason_detail": error,
                "reason_label": "链接失败",
                "reason_icon_file": "action_trace_link.png",
                "platform": "Bilibili",
                "platform_id": "bilibili",
                "trace_id": "bilibili_BV1Zj421D7xG_1445597741",
                "status_label": "失败",
                "log_excerpt_items": [
                    {
                        "time": "2026-07-06 18:34:48",
                        "level": "ERROR",
                        "message": f"下载失败 [{title}]: {error}",
                        "icon_file": "log_level_error.png",
                    },
                    {
                        "time": "2026-07-06 18:36:12",
                        "level": "ERROR",
                        "message": (
                            "('Connection aborted.', ConnectionResetError(10054, "
                            "'远程主机强迫关闭了一个现有的连接。', None, 10054, None))"
                        ),
                        "icon_file": "log_level_error.png",
                    },
                    {
                        "time": "2026-07-06 18:36:25",
                        "level": "INFO",
                        "message": "Bilibili 流请求建立成功",
                        "icon_file": "log_level_info.png",
                    },
                    {
                        "time": "2026-07-06 18:36:59",
                        "level": "ERROR",
                        "message": (
                            "B站流下载失败: ('Connection broken: "
                            "IncompleteRead(19528595 bytes read, 1597253 more expected)', "
                            "IncompleteRead(19528595 bytes read, 1597253 more expected))"
                        ),
                        "icon_file": "log_level_error.png",
                    }
                ],
                "solutions": [
                    {
                        "title": "重新获取链接",
                        "description": "请重新复制最新的分享链接并重试任务。",
                        "icon_file": "action_trace_link.png",
                    },
                    {
                        "title": "检查网络",
                        "description": "确认代理、DNS 和网络环境正常，必要时切换网络后重试。",
                        "icon_file": "status_network_warning.png",
                    },
                ],
            }
        ]

        shell.show_page("failed")
        shell.render(snapshot, changed_sections={"settings_snapshot", "failed_items"})

        failed = shell.pages["failed"]
        self._wait_for_table_rows(failed.table, 1)
        model = failed.table.model()
        self.assertEqual(model.index(0, 2).data(Qt.ItemDataRole.DisplayRole), "Link failed")

        visible_text = "\n".join(label.text() for label in failed.findChildren(QLabel))
        self.assertIn("B-site download failed", visible_text)
        self.assertIn("B-site stream download failed", visible_text)
        self.assertIn("The remote host forcibly closed an existing connection.", visible_text)
        self.assertIn("Bilibili stream request established", visible_text)
        self.assertIn("Connection broken: IncompleteRead", visible_text)
        self.assertIn("Download failed", visible_text)
        self.assertIn("Refresh link", visible_text)
        self.assertIn("Check network", visible_text)
        self.assertIn("Copy the latest share link again and retry the task.", visible_text)
        self.assertIn("Confirm proxy, DNS, and network settings are working", visible_text)
        self.assertNotIn("链接失败", visible_text)
        self.assertNotIn("B站下载失败", visible_text)
        self.assertNotIn("B站流下载失败", visible_text)
        self.assertNotIn("远程主机强迫关闭", visible_text)
        self.assertNotIn("Bilibili 流请求建立成功", visible_text)
        self.assertNotIn("重新获取链接", visible_text)
        self.assertNotIn("检查网络", visible_text)

    def test_failed_page_preserves_selected_item_id_after_list_refresh_reorders_rows(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"

        def failed_row(item_id: str, title: str) -> dict:
            return {
                "id": item_id,
                "title": title,
                "failed_at": "2026-07-06 18:49:04",
                "failed_at_table": "07-06 18:49",
                "reason": "B站下载失败",
                "reason_detail": "B站下载失败",
                "reason_label": "链接失败",
                "reason_icon_file": "action_trace_link.png",
                "platform": "Bilibili",
                "platform_id": "bilibili",
                "trace_id": item_id,
                "status_label": "失败",
                "log_excerpt_items": [],
                "solutions": [],
            }

        snapshot["failed_items"] = [
            failed_row("p16", "P16_生物为什么要进化出性别?"),
            failed_row("p18", "P18_如果月球突然消失了会发生什么?"),
            failed_row("p19", "P19_地球内部有没有高等文明存在?"),
        ]
        shell.show_page("failed")
        shell.render(snapshot, changed_sections={"settings_snapshot", "failed_items"})

        failed = shell.pages["failed"]
        self._wait_for_table_rows(failed.table, 3)
        self.assertTrue(failed.select_id("p16"))
        self._wait_until(lambda: failed.selected_id() == "p16", message="failed page did not select p16")
        self.assertEqual(failed.selected_id(), "p16")

        snapshot["failed_items"] = [
            snapshot["failed_items"][1],
            snapshot["failed_items"][0],
            snapshot["failed_items"][2],
        ]
        shell.render(snapshot, changed_sections={"failed_items"})
        self._wait_until(lambda: failed.selected_id() == "p16", message="failed page did not preserve p16")

        title_row = failed.summary_layout.itemAt(0).widget()
        title_value = title_row.layout().itemAt(1).widget().findChild(QLabel).text()
        self.assertEqual(failed.selected_id(), "p16")
        self.assertEqual(failed.table.selected_id(), "p16")
        self.assertEqual(title_value, "P16_生物为什么要进化出性别?")

        self.assertTrue(failed.select_id("p18"))
        self._wait_until(lambda: failed.selected_id() == "p18", message="failed page did not select p18")
        title_row = failed.summary_layout.itemAt(0).widget()
        title_value = title_row.layout().itemAt(1).widget().findChild(QLabel).text()
        self.assertEqual(failed.selected_id(), "p18")
        self.assertEqual(title_value, "P18_如果月球突然消失了会发生什么?")

    def test_gui_log_tabs_are_language_keyed_after_runtime_switch(self):
        shell = self._make_shell()
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["log_items"] = [
            {
                "id": "gui-log-tab-i18n",
                "time": "2026-07-06 03:30:00",
                "level": "WARN",
                "raw_level": "WARN",
                "source": "MainWindow",
                "platform": "\u7cfb\u7edf",
                "platform_id": "system",
                "status_code": "FRONTEND_RENDER_SLOW",
                "trace_id": "trace-gui-log-tab-i18n",
                "message": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                "message_summary": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
            }
        ]
        shell.show_page("logs")
        logs = shell.pages["logs"]
        all_time_index = logs.time_filter.findData("\u5168\u90e8")
        self.assertGreaterEqual(all_time_index, 0)
        logs.time_filter.setCurrentIndex(all_time_index)

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        shell.render(snapshot, changed_sections={"settings_snapshot", "log_items"})
        self._wait_for_log_rows(logs, 1)

        self.assertEqual(logs._tab_buttons["all"].text(), "All logs 1")
        self.assertEqual(logs._tab_buttons["crawl"].text(), "Crawl logs 0")
        self.assertEqual(logs._tab_buttons["download"].text(), "Download logs 0")
        self.assertEqual(logs._tab_buttons["system"].text(), "System logs 0")
        self.assertEqual(logs._tab_buttons["performance"].text(), "Performance logs 1")
        self.assertEqual(logs._tab_buttons["error"].text(), "Error logs 0")
        for button in logs._tab_buttons.values():
            text_width = button.fontMetrics().horizontalAdvance(button.text())
            self.assertGreaterEqual(button.minimumWidth(), text_width + 28)

        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()

        tab_text = " ".join(button.text() for button in logs._tab_buttons.values())
        self.assertEqual(logs._tab_buttons["all"].text(), "\u5168\u90e8\u65e5\u5fd7 1")
        self.assertEqual(logs._tab_buttons["crawl"].text(), "\u91c7\u96c6\u65e5\u5fd7 0")
        self.assertEqual(logs._tab_buttons["download"].text(), "\u4e0b\u8f7d\u65e5\u5fd7 0")
        self.assertEqual(logs._tab_buttons["system"].text(), "\u7cfb\u7edf\u65e5\u5fd7 0")
        self.assertEqual(logs._tab_buttons["performance"].text(), "\u6027\u80fd\u65e5\u5fd7 1")
        self.assertEqual(logs._tab_buttons["error"].text(), "\u5f02\u5e38\u65e5\u5fd7 0")
        self.assertNotIn("All logs", tab_text)
        self.assertNotIn("Download logs", tab_text)
        self.assertNotIn("System logs", tab_text)

    def test_gui_log_center_localizes_dynamic_log_message_and_event_code(self):
        from app.ui.viewmodels.log_i18n import localize_log_payload, localize_log_text

        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["\u5916\u89c2\u8bbe\u7f6e"]["language"] = "en-US"
        snapshot["log_items"] = [
            {
                "id": "gui-i18n-local-scan",
                "time": "2026-07-05 22:15:58",
                "level": "INFO",
                "raw_level": "INFO",
                "result_type": "info",
                "category": "system",
                "log_scope": "system",
                "event_stage": "step",
                "event_code": "GUI_\u5df2\u52a0\u8f7d_1_\u4e2a\u672c\u5730\u6587\u4ef6_\u89c6\u9891_1_\u56fe\u7247_0",
                "source": "GUI",
                "platform": "\u7cfb\u7edf",
                "platform_id": "system",
                "trace_id": "",
                "message": "\u2705 \u5df2\u52a0\u8f7d 1 \u4e2a\u672c\u5730\u6587\u4ef6 (\u89c6\u9891: 1, \u56fe\u7247: 0)",
                "message_summary": "\u2705 \u5df2\u52a0\u8f7d 1 \u4e2a\u672c\u5730\u6587\u4ef6 (\u89c6\u9891: 1, \u56fe\u7247: 0)",
                "detail": {
                    "description": "\u2705 \u5df2\u52a0\u8f7d 1 \u4e2a\u672c\u5730\u6587\u4ef6 (\u89c6\u9891: 1, \u56fe\u7247: 0)",
                    "status_code": "GUI_\u5df2\u52a0\u8f7d_1_\u4e2a\u672c\u5730\u6587\u4ef6_\u89c6\u9891_1_\u56fe\u7247_0",
                    "platform": "\u7cfb\u7edf",
                    "source": "GUI",
                },
            }
        ]

        shell.render(snapshot, changed_sections={"settings_snapshot", "log_items"})
        all_time_index = logs.time_filter.findData("\u5168\u90e8")
        self.assertGreaterEqual(all_time_index, 0)
        logs.time_filter.setCurrentIndex(all_time_index)
        self._wait_for_log_rows(logs, 1)

        message = logs.table.model().index(0, 4).data(Qt.ItemDataRole.DisplayRole)
        self.assertIn("Loaded 1 local file", message)
        self.assertIn("videos: 1, images: 0", message)
        for _ in range(250):
            self.app.processEvents()
            if "Loaded 1 local file" in logs.detail_message_value.toPlainText():
                break
            QTest.qWait(20)
        self.assertIn("Loaded 1 local file", logs.detail_message_value.toPlainText())
        self.assertEqual(
            logs.detail_status_code_value.text().replace("\n", ""),
            "GUI_LOADED_1_LOCAL_FILES_VIDEOS_1_IMAGES_0",
        )
        self.assertIn("Loaded 1 local file", logs._last_json_text)
        self.assertNotIn("\u5df2\u52a0\u8f7d", logs._last_json_text)
        self.assertEqual(localize_log_text("已切换到浅色主题", "en-US"), "Switched to light theme")
        self.assertEqual(localize_log_text("已切换到深色主题", "en-US"), "Switched to dark theme")
        self.assertEqual(localize_log_text("Switched to light theme", "zh-CN"), "已切换到浅色主题")
        self.assertEqual(localize_log_text("Switched to dark theme", "zh-TW"), "已切換到深色主題")
        self.assertEqual(
            localize_log_text("\u2139\ufe0f 该目录下没有找到视频或图片", "en-US"),
            "\u2139\ufe0f No videos or images found in this directory",
        )
        self.assertEqual(
            localize_log_text("\u2139\ufe0f No videos or images found in this directory", "zh-CN"),
            "\u2139\ufe0f 该目录下没有找到视频或图片",
        )
        self.assertEqual(localize_log_text("找到 3 个匹配用户", "en-US"), "Found 3 matching users")
        self.assertEqual(localize_log_text("Found 3 matching users", "zh-CN"), "找到 3 个匹配用户")
        localized_payload = localize_log_payload(
            {"description": "\u2139\ufe0f 该目录下没有找到视频或图片"},
            "zh-CN",
        )
        self.assertEqual(localized_payload["description"], "\u2139\ufe0f 该目录下没有找到视频或图片")
        self.assertNotIn("Found视频", localized_payload["description"])
        self.assertEqual(localize_log_text("用户确认了 45 个任务", "en-US"), "User confirmed 45 tasks")
        self.assertEqual(localize_log_text("启动 Bilibili 爬虫任务", "en-US"), "Started Bilibili crawl task")
        self.assertEqual(localize_log_text("Bilibili 爬虫任务结束", "en-US"), "Bilibili crawl task finished")
        self.assertEqual(localize_log_text("fetch video detail", "zh-CN"), "获取视频详情")
        self.assertEqual(localize_log_text("fetch video detail", "zh-TW"), "取得影片詳情")
        self.assertEqual(localize_log_text("Bilibili route: direct BV video", "zh-CN"), "Bilibili 路由：直接 BV 视频")
        self.assertEqual(localize_log_text("Download task has been queued", "zh-CN"), "下载任务已入队")
        self.assertEqual(localize_log_text("Released download concurrency slot", "zh-CN"), "已释放下载并发槽位")
        damaged_download_failure = "下载任务失败".encode("utf-8").decode("gbk", errors="replace")
        self.assertEqual(localize_log_text(damaged_download_failure, "zh-CN"), "下载任务失败")
        self.assertEqual(localize_log_text(damaged_download_failure, "en-US"), "Download task failed")
        damaged_payload = localize_log_payload({"description": damaged_download_failure}, "zh-CN")
        self.assertEqual(damaged_payload["description"], "下载任务失败")
        self.assertEqual(localize_log_text("System · MainWindow", "zh-CN"), "系统 · 主窗口")
        self.assertEqual(localize_log_text("系统 · MainWindow", "en-US"), "System · Main window")
        self.assertEqual(localize_log_text("系统 · ApplicationContext", "en-US"), "System · ApplicationContext")
        self.assertEqual(localize_log_text("Bilibili · BilibiliDownloader", "zh-CN"), "Bilibili · Bilibili 下载器")
        self.assertEqual(localize_log_text("System · BaseDownloader", "zh-CN"), "系统 · 基础下载器")
        self.assertEqual(localize_log_text("System · WebSocketRuntime", "zh-CN"), "系统 · WebSocket 运行时")
        self.assertEqual(localize_log_text("System · WebSocketBridge", "zh-CN"), "系统 · WebSocket 桥接器")
        self.assertEqual(localize_log_text("System · FrontendLogCache", "zh-CN"), "系统 · 前端日志缓存")
        self.assertEqual(localize_log_text("System · FailedRecordStore", "zh-CN"), "系统 · 失败记录存储")
        self.assertEqual(localize_log_text("System · BiliAPI", "zh-CN"), "系统 · Bilibili 接口")
        self.assertEqual(localize_log_text("Xiaohongshu · XiaohongshuDownloader", "zh-CN"), "小红书 · 小红书下载器")
        self.assertEqual(localize_log_text("Xiaohongshu · XiaohongshuSpider", "zh-CN"), "小红书 · 小红书爬虫")
        self.assertEqual(localize_log_text("Xiaohongshu · XiaoHongShuSpider", "zh-CN"), "小红书 · 小红书爬虫")
        self.assertEqual(localize_log_text("Xiaohongshu · XiaohongshuClient", "zh-CN"), "小红书 · 小红书客户端")
        self.assertEqual(localize_log_text("DownloadManager", "zh-CN"), "下载管理器")
        self.assertEqual(localize_log_text("系统 · GUI", "en-US"), "System · GUI")
        self.assertEqual(localize_log_text("ui callback failed", "zh-CN"), "UI 回调失败")
        self.assertEqual(localize_log_text("callback failed", "zh-CN"), "回调失败")
        self.assertEqual(localize_log_text("_on_spider_finished 被调用", "zh-CN"), "爬虫完成回调已调用")
        self.assertEqual(localize_log_text("Douyin参数初始化完成", "zh-CN"), "Douyin 参数初始化完成")
        self.assertEqual(localize_log_text("[INFO] Douyin参数初始化完成", "en-US"), "[INFO] Douyin parameters initialized")
        self.assertEqual(
            localize_log_text("[INFO] 正在更新抖音参数，请稍等...", "en-US"),
            "[INFO] Updating Douyin parameters, please wait...",
        )
        self.assertEqual(
            localize_log_text("[INFO] Updating Douyin parameters, please wait...", "zh-CN"),
            "[INFO] 正在更新抖音参数，请稍等...",
        )
        self.assertEqual(
            localize_log_text("配置文件 cookie 参数未登录，数据获取已提前结束", "en-US"),
            "Config cookie is not logged in; data fetching ended early",
        )
        self.assertEqual(
            localize_log_text("配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用", "en-US"),
            "Config cookie is not set; Douyin features may not work properly",
        )
        self.assertEqual(
            localize_log_text("⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用", "en-US"),
            "⚠️ Config cookie_tiktok is not set; TikTok features may not work properly",
        )
        self.assertEqual(
            localize_log_text("[INFO] Douyin参数更新完毕!", "en-US"),
            "[INFO] Douyin parameters updated!",
        )
        self.assertEqual(
            localize_log_text("[INFO] 抖音参数更新完毕！", "en-US"),
            "[INFO] Douyin parameters updated!",
        )
        self.assertEqual(
            localize_log_text("TikTok 参数更新完毕！", "en-US"),
            "TikTok parameters updated!",
        )
        self.assertEqual(
            localize_log_payload(
                {"description": "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用"},
                "en-US",
            )["description"],
            "⚠️ Config cookie_tiktok is not set; TikTok features may not work properly",
        )
        self.assertEqual(localize_log_text("Bilibili stream request established", "zh-CN"), "Bilibili 流请求建立成功")
        self.assertEqual(
            localize_log_text("Preparing to merge Bilibili audio/video stream", "zh-CN"),
            "准备合并 Bilibili 音视频流",
        )
        self.assertEqual(
            localize_log_text("Douyin download task submitted to the queue", "zh-CN"),
            "抖音下载任务已提交到下载队列",
        )
        self.assertEqual(
            localize_log_text("Kuaishou video stream captured and submitted to the queue", "zh-CN"),
            "快手视频流已捕获并提交到下载队列",
        )
        self.assertEqual(
            localize_log_text("MissAV detail page sniff timed out; playlist.m3u8 was not found", "zh-CN"),
            "MissAV 详情页嗅探超时，未发现 playlist.m3u8",
        )
        self.assertEqual(localize_log_text("Xiaohongshu crawl task finished", "zh-CN"), "小红书爬虫任务结束")
        self.assertEqual(
            localize_log_text("Preparing Kuaishou video stream download", "zh-TW"),
            "準備下載快手影片串流",
        )
        self.assertEqual(localize_log_text("Download completed: demo.mp4", "zh-CN"), "下载完成：demo.mp4")
        self.assertEqual(localize_log_text("Download task completed", "zh-CN"), "下载任务完成")
        self.assertEqual(localize_log_text("\U0001f50d Resolving link redirect", "zh-CN"), "\U0001f50d 正在解析链接重定向")
        self.assertEqual(localize_log_text("Started Douyin task | target: demo", "zh-CN"), "启动抖音任务 | 目标：demo")
        self.assertEqual(
            localize_log_text("准备下载 Bilibili 音视频流", "en-US"),
            "Preparing Bilibili audio/video stream download",
        )
        self.assertEqual(
            localize_log_text("B站下载失败: B站流下载失败: 远程主机强迫关闭了一个现有的连接。", "en-US"),
            "B-site download failed: B-site stream download failed: The remote host forcibly closed an existing connection.",
        )
        self.assertEqual(
            localize_log_text(
                "('Connection aborted.', ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接。', None, 10054, None))",
                "en-US",
            ),
            "('Connection aborted.', ConnectionResetError(10054, 'The remote host forcibly closed an existing connection.', None, 10054, None))",
        )
        self.assertEqual(localize_log_text("Bilibili 流请求建立成功", "en-US"), "Bilibili stream request established")
        self.assertEqual(
            localize_log_text(
                "下载失败 [demo]: B站下载失败: B站流下载失败: 远程主机强迫关闭了一个现有的连接。",
                "en-US",
            ),
            "Download failed [demo]: B-site download failed: B-site stream download failed: The remote host forcibly closed an existing connection.",
        )
        self.assertEqual(localize_log_text("启动抖音任务 | 目标: demo", "en-US"), "Started Douyin task | target: demo")
        self.assertEqual(
            localize_log_text("🎉 全部完成: 成功 45/45 | 失败 0", "en-US"),
            "🎉 All completed: success 45/45 | failed 0",
        )
        self.assertEqual(
            localize_log_text("Increased concurrency by rebuilding dispatch semaphore capacity.", "zh-CN"),
            "已通过重建分发信号量提高并发容量",
        )
        self.assertEqual(
            localize_log_text("Video-only mode skipped a non-video resource", "zh-CN"),
            "仅下载视频模式已跳过非视频资源",
        )
        self.assertEqual(
            localize_log_text("Video-only mode skipped non-video resource: demo", "zh-CN"),
            "仅下载视频模式已跳过非视频资源: demo",
        )
        self.assertEqual(localize_log_text("默认打开方式已生效", "en-US"), "Default open mode is active")
        self.assertEqual(localize_log_text("Default open mode is active", "zh-CN"), "默认打开方式已生效")
        self.assertEqual(localize_log_text("❌ save_dir 必须是字符串", "en-US"), "❌ save_dir must be a string")
        self.assertEqual(localize_log_text("Clear queue failed: busy", "zh-CN"), "清空队列失败: busy")
        self.assertEqual(
            localize_log_text("Download options updated: concurrency=3", "zh-CN"),
            "下载选项已更新: concurrency=3",
        )
        self.assertEqual(localize_log_text("download paused: demo", "zh-CN"), "下载已暂停: demo")
        self.assertEqual(localize_log_text("Web 端启动爬虫任务", "en-US"), "Web started crawl task")
        self.assertEqual(localize_log_text("CLI 下载任务失败", "en-US"), "CLI download task failed")
        self.assertEqual(
            localize_log_text("spider 已结束, 耗时 12s, 收集到 3 个项目, 二次选择 1 次", "en-US"),
            "spider finished, elapsed 12s, collected 3 items, secondary selections 1",
        )
        self.assertEqual(
            localize_log_text("B站 audio 流连接断开，5s 后重试 (1/3): timeout", "en-US"),
            "B-site audio stream disconnected; retrying in 5s (1/3): timeout",
        )
        self.assertEqual(
            localize_log_text("Guardrail stopped navigation: budget exhausted", "zh-CN"),
            "防护规则已停止页面跳转: budget exhausted",
        )
        self.assertEqual(
            localize_log_text("Guardrail stopped reload: budget exhausted", "zh-CN"),
            "防护规则已停止页面刷新: budget exhausted",
        )
        self.assertEqual(
            localize_log_text("Completed media metadata probe finished without usable duration or resolution", "zh-TW"),
            "媒體中繼資料探測已完成，但未取得可用時長或解析度",
        )
        self.assertEqual(
            localize_log_text(
                "Web event loop is unavailable; deferred frontend delta until a later async flush.",
                "zh-CN",
            ),
            "Web 事件循环不可用，已延后前端增量刷新",
        )
        self.assertEqual(
            localize_log_text(
                "Skipped frontend delta flush because no running event loop is available.",
                "zh-CN",
            ),
            "没有可用事件循环，已跳过前端增量刷新",
        )

    def test_gui_log_table_localizes_mixed_runtime_summary_rows_after_language_switch(self):
        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        samples = [
            ("gui-log-douyin-init", "[INFO] Douyin参数初始化完成", "GUI", "system", "系统"),
            ("gui-log-cookie", "配置文件 cookie 参数未登录，数据获取已提前结束", "DouyinSpider", "douyin", "Douyin"),
            (
                "gui-log-cookie-tiktok",
                "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                "DouyinSpider",
                "douyin",
                "Douyin",
            ),
            ("gui-log-completed-cn", "下载完成: demo.mp4", "BaseDownloader", "douyin", "Douyin"),
            ("gui-log-completed-emoji-cn", "✅️ 下载完成: emoji.mp4", "BaseDownloader", "douyin", "Douyin"),
            ("gui-log-douyin-updated", "[INFO] Douyin参数更新完毕!", "DouyinSpider", "douyin", "Douyin"),
            ("gui-log-updating-en", "[INFO] Updating Douyin parameters, please wait...", "DouyinSpider", "douyin", "Douyin"),
            ("gui-log-task-en", "Download task completed", "BaseDownloader", "douyin", "Douyin"),
            ("gui-log-redirect-en", "\U0001f50d Resolving link redirect", "DouyinSpider", "douyin", "Douyin"),
        ]
        snapshot["log_items"] = [
            {
                "id": item_id,
                "time": f"2026-07-08 13:28:{index:02d}",
                "level": "INFO",
                "raw_level": "INFO",
                "source": source,
                "platform": platform,
                "platform_id": platform_id,
                "trace_id": f"dy_i18n_{index}",
                "message": message,
                "message_summary": message,
            }
            for index, (item_id, message, source, platform_id, platform) in enumerate(samples, start=1)
        ]

        all_time_index = logs.time_filter.findData("全部")
        self.assertGreaterEqual(all_time_index, 0)
        logs.time_filter.setCurrentIndex(all_time_index)
        shell.render(snapshot, changed_sections={"settings_snapshot", "log_items"})
        self._wait_for_log_rows(logs, len(samples))

        def table_messages() -> str:
            model = logs.table.model()
            return "\n".join(
                str(model.index(row, 4).data(Qt.ItemDataRole.DisplayRole) or "")
                for row in range(model.rowCount())
            )

        self._wait_until(
            lambda: "[INFO] Douyin parameters initialized" in table_messages(),
            message="English log table did not translate Douyin parameter init",
        )
        en_messages = table_messages()
        self.assertIn("[INFO] Douyin parameters initialized", en_messages)
        self.assertIn("Config cookie is not logged in; data fetching ended early", en_messages)
        self.assertIn("⚠️ Config cookie_tiktok is not set; TikTok features may not work properly", en_messages)
        self.assertIn("Download completed: demo.mp4", en_messages)
        self.assertIn("✅️ Download completed: emoji.mp4", en_messages)
        self.assertIn("[INFO] Douyin parameters updated!", en_messages)
        self.assertNotIn("Douyin参数初始化完成", en_messages)
        self.assertNotIn("Douyin参数更新完毕", en_messages)
        self.assertNotIn("配置文件 cookie 参数未登录", en_messages)
        self.assertNotIn("配置文件 cookie_tiktok 参数未设置", en_messages)

        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self._wait_until(
            lambda: "\U0001f50d 正在解析链接重定向" in table_messages(),
            message="Chinese log table did not translate English redirect message",
        )
        zh_messages = table_messages()
        self.assertIn("[INFO] 正在更新抖音参数，请稍等...", zh_messages)
        self.assertIn("下载任务完成", zh_messages)
        self.assertIn("\U0001f50d 正在解析链接重定向", zh_messages)
        self.assertNotIn("Updating Douyin parameters", zh_messages)
        self.assertNotIn("Download task completed", zh_messages)

    def test_web_runtime_log_phrase_translations_match_gui_table(self):
        import ast
        import re

        from app.ui.viewmodels import log_i18n

        gui_source = Path(log_i18n.__file__).read_text(encoding="utf-8")
        gui_tree = ast.parse(gui_source)
        gui_entries = []
        for node in ast.walk(gui_tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_RUNTIME_LOG_PHRASE_TRANSLATIONS"
                for target in node.targets
            ):
                gui_entries = ast.literal_eval(node.value)
                break

        web_bundle = _html_bundle()
        web_block = web_bundle.split("const RUNTIME_LOG_PHRASE_TRANSLATIONS = [", 1)[1].split("];", 1)[0]
        web_entries = []
        web_aliases = {}
        for match in re.finditer(
            r'\{\s*zh:\s*"(.*?)",\s*en:\s*"(.*?)",\s*tw:\s*"(.*?)"(?:,\s*aliases:\s*\[(.*?)\])?\s*\}',
            web_block,
        ):
            entry = (match.group(1), match.group(2), match.group(3))
            web_entries.append(entry)
            if match.group(4):
                web_aliases[entry] = tuple(re.findall(r'"(.*?)"', match.group(4)))

        gui_entries_primary = {tuple(entry[:3]) for entry in gui_entries}
        gui_aliases = {tuple(entry[:3]): tuple(entry[3:]) for entry in gui_entries if len(entry) > 3}

        self.assertEqual(gui_entries_primary, set(web_entries))
        self.assertEqual(gui_aliases, web_aliases)
        self.assertIn(("默认打开方式已生效", "Default open mode is active", "預設開啟方式已生效"), gui_entries)
        self.assertIn(("已切换到浅色主题", "Switched to light theme", "已切換到淺色主題"), gui_entries)
        self.assertIn(
            ("该目录下没有找到视频或图片", "No videos or images found in this directory", "該目錄下沒有找到影片或圖片"),
            gui_entries,
        )
        self.assertNotIn(("已切换到", "Switched to", "已切換到"), gui_entries)
        self.assertNotIn(("主题", "theme", "主題"), gui_entries)
        self.assertNotIn(("找到", "Found", "找到"), gui_entries)

    def test_gui_log_center_localizes_source_components_after_language_switch(self):
        shell = self._make_shell()
        shell.show_page("logs")
        logs = shell.pages["logs"]
        snapshot = deepcopy(shell._last_snapshot or FrontendStateService.mock_snapshot())
        snapshot["settings_snapshot"]["外观设置"]["language"] = "en-US"
        snapshot["log_items"] = [
            {
                "id": "gui-i18n-source",
                "time": "2026-07-06 03:31:00",
                "level": "WARN",
                "raw_level": "WARN",
                "result_type": "warning",
                "category": "performance",
                "log_scope": "performance",
                "event_stage": "step",
                "event_code": "FRONTEND_RENDER_SLOW",
                "source": "MainWindow",
                "platform": "系统",
                "platform_id": "system",
                "trace_id": "",
                "message": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                "message_summary": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                "detail": {
                    "description": "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                    "platform": "系统",
                    "source": "MainWindow",
                },
            }
        ]

        shell.render(snapshot, changed_sections={"settings_snapshot", "log_items"})
        all_time_index = logs.time_filter.findData("全部")
        self.assertGreaterEqual(all_time_index, 0)
        logs.time_filter.setCurrentIndex(all_time_index)
        self._wait_for_log_rows(logs, 1)

        source = logs.table.model().index(0, 2).data(Qt.ItemDataRole.DisplayRole)
        self.assertTrue(str(source).endswith("System · Main window"))
        self._wait_for_log_detail_source(logs, "Main window")

        snapshot["settings_snapshot"]["外观设置"]["language"] = "zh-CN"
        shell.render(snapshot, changed_sections={"settings_snapshot"})
        self.app.processEvents()
        source = self._wait_for_log_table_cell_suffix(logs, 0, 2, "系统 · 主窗口")
        self.assertNotIn("MainWindow", str(source))
        self._wait_for_log_detail_source(logs, "主窗口")

    def test_gui_platform_custom_proxy_field_displays_port_and_commits_endpoint(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        missav = next(row for row in snapshot["settings_snapshot"]["\u5e73\u53f0\u8bbe\u7f6e"] if row["id"] == "missav")
        missav["proxy"] = "\u81ea\u5b9a\u4e49"
        missav["proxy_custom_allowed"] = True
        missav["proxy_custom_active"] = True
        missav["proxy_custom_value"] = "http://127.0.0.1:10809"

        settings.render(snapshot)
        settings._set_current_group("\u5e73\u53f0\u8bbe\u7f6e")
        self.app.processEvents()

        edit = next(
            editor
            for editor in settings.findChildren(QLineEdit)
            if editor.objectName() == "SettingsProxyCustomEdit" and editor.isEnabled()
        )
        self.assertEqual(edit.text(), "10809")
        changes = []
        settings.setting_changed.connect(lambda section, key, value: changes.append((section, key, value)))

        edit.setText("7890")
        edit.editingFinished.emit()
        self.app.processEvents()

        self.assertIn(("missav", "proxy_url", "http://127.0.0.1:7890"), changes)

    def test_gui_translation_catalog_is_loaded_from_language_files(self):
        import json

        catalog_dir = Path(__file__).resolve().parents[1] / "app" / "ui" / "i18n"
        en_catalog = json.loads((catalog_dir / "en-US.json").read_text(encoding="utf-8"))
        tw_catalog = json.loads((catalog_dir / "zh-TW.json").read_text(encoding="utf-8"))

        self.assertEqual(en_catalog["\u914d\u7f6e\u4e2d\u5fc3"], "Settings")
        self.assertEqual(tw_catalog["\u914d\u7f6e\u4e2d\u5fc3"], "\u8a2d\u5b9a\u4e2d\u5fc3")
        self.assertEqual(en_catalog["请输入主页链接、分享链接或合集链接"], "Enter a profile, shared, or collection link")
        self.assertEqual(tw_catalog["请输入主页链接、分享链接或合集链接"], "請輸入主頁連結、分享連結或合集連結")
        self.assertEqual(en_catalog["播放前校验失败"], "Pre-playback check failed")
        self.assertEqual(tw_catalog["播放前校验失败"], "播放前校驗失敗")
        self.assertEqual(en_catalog["检测中"], "Checking")
        self.assertEqual(tw_catalog["检测中"], "檢測中")
        self.assertEqual(en_catalog["链接失败"], "Link failed")
        self.assertEqual(tw_catalog["链接失败"], "連結失敗")
        self.assertEqual(en_catalog["重新获取链接"], "Refresh link")
        self.assertEqual(tw_catalog["重新获取链接"], "重新取得連結")
        self.assertEqual(en_catalog["检查网络"], "Check network")
        self.assertEqual(tw_catalog["检查网络"], "檢查網路")

    def test_webui_loads_language_catalogs_from_shared_api(self):
        content = _html_bundle()

        self.assertIn("const FALLBACK_UI_TEXT", content)
        self.assertIn("/api/i18n/", content)
        self.assertIn("loadUiTextCatalogs()", content)
        self.assertIn("UI_TEXT[language] = { ...(FALLBACK_UI_TEXT[language] || {}), ...catalog }", content)

    def test_web_i18n_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        i18n_js = (static_dir / "i18n.js").read_text(encoding="utf-8")

        self.assertIn("/static/i18n.js", index)
        self.assertLess(index.index("/static/i18n.js"), index.index("/static/custom_select.js"))
        self.assertIn("window.UcpI18n", i18n_js)
        self.assertIn("const FALLBACK_UI_TEXT", i18n_js)
        self.assertNotIn("const FALLBACK_UI_TEXT", app_js)
        self.assertIn("window.UcpI18n || null", app_js)
        self.assertIn("service.loadUiTextCatalogs()", app_js)

    def test_gui_settings_theme_segment_disables_follow_system_immediately(self):
        shell = self._make_shell()
        settings = shell.pages["settings"]
        shell.show_page("settings")
        snapshot = FrontendStateService.mock_snapshot()
        snapshot["settings_snapshot"]["外观设置"]["follow_system"] = True
        snapshot["settings_snapshot"]["外观设置"]["theme"] = "light"

        settings.render(snapshot)
        settings._set_current_group("外观设置")
        self.app.processEvents()

        follow_switch = next(
            switch
            for switch in settings.findChildren(QCheckBox)
            if switch.property("settingsRole") == "follow_system"
        )
        self.assertTrue(follow_switch.isChecked())
        changes = []
        settings.setting_changed.connect(lambda section, key, value: changes.append((section, key, value)))

        dark_button = next(
            button
            for button in settings.findChildren(QPushButton)
            if button.objectName() == "SettingsSegmentButton" and button.property("segment_value") == "dark"
        )
        dark_button.click()
        self.app.processEvents()

        self.assertFalse(follow_switch.isChecked())
        self.assertIn(("common", "theme", "dark"), changes)

    def test_gui_settings_cards_do_not_exceed_detail_panel_width(self):
        shell = self._make_shell()
        shell.resize(780, 620)
        shell.show_page("settings")
        settings = shell.pages["settings"]
        self.app.processEvents()

        for group_name in list(settings._group_order):
            settings._set_current_group(group_name)
            self.app.processEvents()
            margins = settings.detail_layout.contentsMargins()
            available = max(320, settings.detail_panel.width() - margins.left() - margins.right() - 4)
            current_widgets = [
                settings.detail_layout.itemAt(index).widget()
                for index in range(settings.detail_layout.count())
                if settings.detail_layout.itemAt(index).widget() is not None
            ]
            form_card = next((widget for widget in current_widgets if widget.objectName() == "SettingsFormCard"), None)
            hint_card = next((widget for widget in current_widgets if widget.objectName() == "SettingsHintCard"), None)
            self.assertIsNotNone(form_card)
            self.assertLessEqual(form_card.width(), available)
            self.assertIsNotNone(hint_card)
            self.assertLessEqual(hint_card.width(), available)
            for panel_name in ("SettingsPlatformTablePanel", "SettingsPlatformSummaryBar"):
                panel = form_card.findChild(QFrame, panel_name)
                if panel is not None:
                    self.assertLessEqual(panel.width(), max(300, form_card.width() - 20))

    def test_completed_file_info_skips_identical_rebuilds(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("completed")
        completed.render(snapshot)
        info_body = completed.info_body

        completed.render(snapshot)

        self.assertIs(completed.info_body, info_body)

    def test_completed_page_uses_separate_cards_and_short_table_time(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("completed")
        completed.render(snapshot)
        self._wait_for_table_rows(completed.table, 20)

        table_card = completed.findChild(QFrame, "CompletedTableCard")
        preview_card = completed.findChild(QFrame, "CompletedPreviewCard")
        info_card = completed.findChild(QFrame, "CompletedInfoCard")
        info_scroll = completed.findChild(QScrollArea, "CompletedInfoScroll")

        self.assertIsNotNone(table_card)
        self.assertIsNotNone(preview_card)
        self.assertIsNotNone(info_card)
        self.assertIsNotNone(info_scroll)
        self.assertIs(info_scroll.widget(), completed.info_body)
        self.assertEqual(info_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertIs(completed.table.parent(), table_card)
        self.assertGreater(table_card.layout().contentsMargins().left(), 0)
        self.assertFalse(hasattr(completed, "title_label"))
        self.assertTrue(completed.table.itemDelegate()._suppress_native_selection)

        table_time = completed.table.model().index(0, 1).data()
        full_time = snapshot["completed_items"][0]["completed_at"]
        detail_texts = [label.text() for label in completed.info_body.findChildren(QLabel)]

        self.assertNotIn("2026", table_time)
        self.assertEqual(table_time, snapshot["completed_items"][0]["completed_at_table"])
        metrics = completed.table.fontMetrics()
        self.assertGreaterEqual(completed.table.columnWidth(1), metrics.horizontalAdvance("06-21 15:06") + 8)
        self.assertLessEqual(completed.table.columnWidth(1), 156)
        self.assertGreaterEqual(completed.table.columnWidth(2), metrics.horizontalAdvance("00:01:05") + 8)
        self.assertLessEqual(completed.table.columnWidth(2), 136)
        self.assertGreaterEqual(completed.table.columnWidth(3), metrics.horizontalAdvance("WEBP") + 16)
        self.assertLessEqual(completed.table.columnWidth(3), 112)
        header = completed.table.horizontalHeader()
        self.assertEqual(header.sectionResizeMode(0), QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            self.assertEqual(header.sectionResizeMode(column), QHeaderView.ResizeMode.Fixed)
        self.assertIn(full_time, detail_texts)
        smart_info_values = completed.info_body.findChildren(SmartWrapLabel, "CompletedInfoSmartWrapLabel")
        self.assertGreaterEqual(len(smart_info_values), 2)
        self.assertGreaterEqual(completed.detail.minimumWidth(), 430)
        self.assertTrue(any("/" in label.raw_text() or "\\" in label.raw_text() for label in smart_info_values))
        self.assertFalse(any("\n" in label.raw_text() for label in smart_info_values))
        self.assertTrue(all(label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse for label in smart_info_values))
        info_layout = completed.info_body.layout()
        span_positions = []
        for value_label in smart_info_values[:2]:
            for index in range(info_layout.count()):
                if info_layout.itemAt(index).widget() is value_label:
                    span_positions.append(info_layout.getItemPosition(index))
        self.assertTrue(span_positions)
        self.assertTrue(all(column == 1 and column_span == 1 for _row, column, _row_span, column_span in span_positions))
        filename_key_row = next(
            info_layout.getItemPosition(index)[0]
            for index in range(info_layout.count())
            if getattr(info_layout.itemAt(index).widget(), "text", lambda: "")() == "文件名"
        )
        save_dir_key_row = next(
            info_layout.getItemPosition(index)[0]
            for index in range(info_layout.count())
            if getattr(info_layout.itemAt(index).widget(), "text", lambda: "")() == "保存路径"
        )
        self.assertEqual(span_positions[0][0], filename_key_row)
        self.assertEqual(span_positions[1][0], save_dir_key_row)
        for expected in ("文件名", "保存路径", "完成时间", "时长", "分辨率", "大小", "格式"):
            self.assertIn(expected, detail_texts)
        for removed in ("下载速率", "完成概览", "存储占用"):
            self.assertNotIn(removed, detail_texts)

    def test_completed_file_info_caps_long_filename_without_losing_raw_text(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        long_text = "接码平台开发者涉嫌侵犯公民个人信息罪，一审判4年9个月，" * 6
        snapshot["completed_items"][0]["filename"] = f"{long_text}.mp4"

        completed.render(snapshot)
        self._wait_until(
            lambda: completed.table.model().rowCount() > 0,
            message="completed table did not render the first page",
        )
        self._wait_until(
            lambda: any(
                label.raw_text() == f"{long_text}.mp4"
                for label in completed.info_body.findChildren(SmartWrapLabel, "CompletedInfoSmartWrapLabel")
            ),
            message="completed file info did not render the long filename",
        )
        completed.layout().activate()
        self.app.processEvents()

        filename_label = next(
            label
            for label in completed.info_body.findChildren(SmartWrapLabel, "CompletedInfoSmartWrapLabel")
            if label.raw_text() == f"{long_text}.mp4"
        )

        self.assertLessEqual(len(filename_label.text().splitlines()), 5)
        self.assertTrue(filename_label.text().endswith(SmartWrapLabel.ELLIPSIS))
        self.assertEqual(filename_label.toolTip(), f"{long_text}.mp4")

    def test_completed_page_compacts_short_visible_columns_without_truncating_webp(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        compact_items = []
        base_items = snapshot["completed_items"] or [{"id": "completed", "title": "demo"}]
        for index in range(1, 26):
            row = dict(base_items[(index - 1) % len(base_items)])
            row["id"] = f"compact-{index}"
            row["title"] = f"04女大_💣_{index}"
            row["completed_at_table"] = "06-29 19:24"
            row["duration"] = "--" if index != 5 else "00:00:08"
            row["format"] = "WEBP" if index != 5 else "MP4"
            compact_items.append(row)
        snapshot["completed_items"] = compact_items

        shell.show_page("completed")
        completed.render(snapshot)
        self._wait_for_table_rows(completed.table, 20)
        self._wait_until(
            lambda: completed.table.columnWidth(0) >= 190,
            message="completed title column was not fitted",
        )

        metrics = completed.table.fontMetrics()
        self.assertGreaterEqual(completed.table.columnWidth(0), 190)
        self.assertGreaterEqual(completed.table.columnWidth(1), metrics.horizontalAdvance("06-29 19:24") + 8)
        self.assertLessEqual(completed.table.columnWidth(1), 156)
        self.assertGreaterEqual(completed.table.columnWidth(2), metrics.horizontalAdvance("00:00:08") + 8)
        self.assertLessEqual(completed.table.columnWidth(2), 136)
        self.assertGreaterEqual(completed.table.columnWidth(3), metrics.horizontalAdvance("WEBP") + 16)
        self.assertLessEqual(completed.table.columnWidth(3), 112)
        self.assertLessEqual(completed.table.columnWidth(4), 100)
        self.assertGreaterEqual(
            completed.table.visualRect(completed.table.model().index(4, 2)).width(),
            metrics.horizontalAdvance("00:00:08") + 8,
        )
        self.assertGreaterEqual(
            completed.table.visualRect(completed.table.model().index(0, 3)).width(),
            metrics.horizontalAdvance("WEBP") + 16,
        )
        action_right = completed.table.columnViewportPosition(4) + completed.table.columnWidth(4)
        self.assertGreaterEqual(action_right, completed.table.viewport().width() - 2)

    def test_completed_page_has_bottom_pagination_like_queue(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("completed")

        completed.render(snapshot)
        self._wait_for_table_rows(completed.table, 20)

        self.assertEqual(completed.btn_prev.objectName(), "PaginationButton")
        self.assertEqual(completed.btn_next.objectName(), "PaginationButton")
        self.assertIsInstance(completed.pagination_footer, PaginationFooter)
        for widget in (completed.btn_prev, completed.btn_next, completed.page_size_combo):
            self.assertGreaterEqual(widget.height(), 34)
            self.assertLessEqual(widget.geometry().bottom(), widget.parentWidget().contentsRect().bottom())

        page_size_combo = completed.page_size_combo
        widest_page_size = combo_widest_item_text_width(page_size_combo)
        self.assertGreaterEqual(combo_edit_field_width(page_size_combo), widest_page_size)
        self.assertLessEqual(page_size_combo.width(), widest_page_size + 24)
        self.assertEqual(page_size_combo.property("comboPopupMaxWidth"), page_size_combo.width())
        self.assertEqual(page_size_combo.property("comboPopupClampToControl"), "true")
        page_size_combo.showPopup()
        self.app.processEvents()
        try:
            QTest.qWait(60)
            self.app.processEvents()
            self.assertEqual(page_size_combo.view().width(), page_size_combo.width())
            self.assertEqual(page_size_combo.view().window().width(), page_size_combo.width())
            self._assert_combo_selected_row_paints_to_right_edge(page_size_combo)
        finally:
            page_size_combo.hidePopup()
            page_size_combo.view().window().hide()

        self.assertEqual(completed.table.model().rowCount(), 20)
        self.assertEqual(completed.total_label.text(), f"共 {len(snapshot['completed_items'])} 项")
        first_page_id = completed.table.model().index(0, 0).data()

        completed.btn_next.click()
        self._wait_until(
            lambda: completed.table.model().index(0, 0).data() != first_page_id,
            message="completed page did not render the next page",
        )
        second_page_id = completed.table.model().index(0, 0).data()

        self.assertNotEqual(first_page_id, second_page_id)
        self.assertEqual(completed._page, 2)

    def test_failed_page_uses_split_cards_without_retry(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("failed")
        failed.render(snapshot)
        self._wait_for_table_rows(failed.table, len(snapshot["failed_items"]))

        self.assertIsNotNone(failed.findChild(QFrame, "FailedTableCard"))
        self.assertIsNotNone(failed.findChild(QFrame, "FailedDetailCard"))
        self.assertIsNotNone(failed.findChild(QFrame, "FailedSolutionsCard"))
        self.assertIsNotNone(failed.findChild(QScrollArea, "FailedLogExcerptScroll"))
        self.assertGreaterEqual(failed.detail.minimumWidth(), 420)
        self.assertEqual(failed.detail_card_layout.contentsMargins().left(), 14)
        self.assertFalse(hasattr(failed, "title_label"))
        self.assertEqual(tuple(failed.table.itemDelegate()._action_ids), ("copy_diagnostics", "delete"))
        self.assertEqual(failed.btn_clear_failed_records.text(), "删除所有")
        clear_all_hits: list[bool] = []
        failed.clear_failed_records_requested.connect(lambda: clear_all_hits.append(True))
        failed.btn_clear_failed_records.click()
        self.app.processEvents()
        self.assertEqual(clear_all_hits, [True])
        self.assertNotIn("retry", snapshot["failed_items"][0].get("actions", []))
        self.assertIn("reason_label", failed.table.table_model._columns)
        self.assertIn("failed_at_table", failed.table.table_model._columns)
        self.assertIn("status_label", failed.table.table_model._columns)
        self.assertIn("reason_label", failed.table.table_model._icon_columns)
        self.assertNotIn("status_label", failed.table.table_model._icon_columns)
        self.assertTrue(failed.table.itemDelegate()._suppress_native_selection)
        reason_col = failed.table.table_model._columns.index("reason_label")
        self.assertTrue(failed.table.itemDelegate()._is_failed_reason_cell(failed.table.table_model.index(0, reason_col)))
        log_row = failed.findChild(QFrame, "FailedLogRow")
        self.assertIsNotNone(log_row)
        self.assertEqual(log_row.layout().contentsMargins().left(), 0)
        self.assertEqual(log_row.layout().spacing(), 5)
        self.assertEqual(log_row.layout().itemAt(0).widget().objectName(), "FailedLogTime")
        time_widget = log_row.layout().itemAt(0).widget()
        self.assertGreaterEqual(time_widget.width(), time_widget.fontMetrics().horizontalAdvance("88:88:88") + 2)
        level_badge = log_row.layout().itemAt(1).widget()
        self.assertIn(level_badge.objectName(), {"LogLevelBadgeInfo", "LogLevelBadgeSuccess", "LogLevelBadgeWarn", "LogLevelBadgeError", "LogLevelBadgeCommand"})
        self.assertEqual(level_badge.height(), 22)
        self.assertEqual(level_badge.width(), 68)
        message_widget = log_row.layout().itemAt(2).widget()
        self.assertIsInstance(message_widget, FailedLogMessageLabel)
        self.assertEqual(message_widget.minimumWidth(), 0)
        self.assertEqual(log_row.layout().stretch(2), 1)
        first_summary_row = failed.summary_layout.itemAt(0).widget()
        self.assertIsNotNone(first_summary_row)
        value_widget = first_summary_row.layout().itemAt(1).widget()
        self.assertEqual(value_widget.minimumWidth(), 0)
        failed.render(snapshot)
        self.app.processEvents()
        self.assertIs(failed.summary_layout.itemAt(0).widget(), first_summary_row)
        failed._clear_layout(failed.summary_layout)
        self.assertIs(first_summary_row.parent(), failed.summary_body)
        self.assertTrue(first_summary_row.isHidden())

    def test_failed_page_uses_worker_pagination_batches(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())

        def failed_row(index: int) -> dict:
            return {
                "id": f"failed-{index:02d}",
                "title": f"Failed task {index:02d}",
                "failed_at": "2026-07-06 18:49:04",
                "failed_at_table": "07-06 18:49",
                "reason": "B站下载失败",
                "reason_detail": "B站下载失败",
                "reason_label": "链接失败",
                "reason_icon_file": "action_trace_link.png",
                "platform": "Bilibili",
                "platform_id": "bilibili",
                "trace_id": f"trace-{index:02d}",
                "status_label": "失败",
                "log_excerpt_items": [],
                "solutions": [],
            }

        snapshot["failed_items"] = [failed_row(index) for index in range(45)]
        shell.show_page("failed")
        failed.render(snapshot)

        self._wait_for_table_rows(failed.table, 20)
        self.assertIsInstance(failed.pagination_footer, PaginationFooter)
        self.assertEqual(failed.table.model().rowCount(), 20)
        self.assertIn("45", failed.total_label.text())
        self.assertEqual(failed.selected_id(), "failed-00")

        first_page_title = failed.table.model().index(0, 0).data(Qt.ItemDataRole.DisplayRole)
        failed.btn_next.click()
        self._wait_until(
            lambda: failed._page == 2
            and failed.table.model().index(0, 0).data(Qt.ItemDataRole.DisplayRole) != first_page_title,
            message="failed page did not render the second worker page",
        )
        self.assertEqual(failed.table.model().rowCount(), 20)
        self.assertEqual(failed.selected_id(), "failed-20")

        failed.btn_next.click()
        self._wait_for_table_rows(failed.table, 5)
        self.assertEqual(failed._page, 3)
        self.assertEqual(failed.selected_id(), "failed-40")
        self.assertFalse(failed.btn_next.isEnabled())

    def test_failed_log_rows_keep_full_time_and_aligned_messages(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        damaged_download_failure = "下载任务失败".encode("utf-8").decode("gbk", errors="replace")
        rows = [
            {"time": "2026-06-30 03:32:05", "level": "WARN", "message": "下载策略执行失败，回退到后续策略"},
            {"time": "2026-06-30 03:32:06", "level": "ERROR", "message": "小红书视频下载失败"},
            {"time": "03:32:07", "level": "INFO", "message": "Released download concurrency slot"},
            {"time": "03:32:08", "level": "ERROR", "message": damaged_download_failure},
        ]

        display_rows = prepare_failed_item_for_display(
            {"id": "failed-log-contract", "log_excerpt_items": rows},
            language="zh-CN",
        )["log_excerpt_display_items"]
        widgets = [failed._log_row(row) for row in display_rows]

        message_x = []
        for widget in widgets:
            layout = widget.layout()
            time_widget = layout.itemAt(0).widget()
            badge = layout.itemAt(1).widget()
            self.assertRegex(time_widget.text(), r"^\d{2}:\d{2}:\d{2}$")
            self.assertGreaterEqual(time_widget.width(), time_widget.fontMetrics().horizontalAdvance(time_widget.text()) + 8)
            self.assertEqual(badge.width(), 68)
            message_x.append(layout.itemAt(2).geometry().x() if widget.isVisible() else time_widget.width() + layout.spacing() + badge.width() + layout.spacing())

        self.assertEqual(len(set(message_x)), 1)
        message_labels = [widget.layout().itemAt(2).widget() for widget in widgets]
        self.assertEqual(message_labels[-1].text(), "下载任务失败")

    def test_failed_log_scroll_resets_to_top_when_detail_log_changes(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        failed.log_scroll.setFixedHeight(86)
        rows = [
            {"time": f"2026-07-09 07:22:{index:02d}", "level": "INFO", "message": f"日志片段 {index}"}
            for index in range(12)
        ]
        snapshot["failed_items"] = [
            {
                "id": "failed-scroll",
                "title": "Scroll detail",
                "failed_at": "2026-07-09 07:23:34",
                "failed_at_table": "07-09 07:23",
                "reason": "B站下载失败",
                "reason_detail": "B站下载失败",
                "reason_label": "链接失败",
                "reason_icon_file": "action_trace_link.png",
                "platform": "Bilibili",
                "platform_id": "bilibili",
                "trace_id": "trace-scroll",
                "status_label": "失败",
                "log_excerpt_items": rows,
                "solutions": [],
            }
        ]
        shell.show_page("failed")
        shell.render(snapshot, changed_sections={"failed_items"})
        self._wait_for_table_rows(failed.table, 1)
        bar = failed.log_scroll.verticalScrollBar()
        bar.setRange(0, 100)
        bar.setValue(100)
        self.assertGreater(bar.value(), 0)

        snapshot["failed_items"][0]["log_excerpt_items"] = rows + [
            {"time": "2026-07-09 07:23:34", "level": "ERROR", "message": "最终失败"}
        ]
        shell.render(snapshot, changed_sections={"failed_items"})
        self._wait_until(
            lambda: failed.log_scroll.verticalScrollBar().value() == 0,
            message="failed log scroll did not reset after detail log changed",
        )

    def test_failed_log_rows_wrap_long_error_segments_without_clipping(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        long_message = (
            "B-site stream download failed: ('Connection broken: "
            "IncompleteRead(524288bytesread,375299811moreexpected)',"
            "IncompleteRead(524288bytesread,375299811moreexpected))"
        )

        widget = failed._log_row({"time_display": "06:32:21", "level": "ERROR", "message_display": long_message})
        message_label = widget.layout().itemAt(2).widget()

        self.assertIsInstance(message_label, FailedLogMessageLabel)
        self.assertEqual(message_label.raw_text(), long_message)
        rendered_text = QLabel.text(message_label)
        self.assertIn(FailedLogMessageLabel.SOFT_BREAK, rendered_text)
        self.assertNotIn(FailedLogMessageLabel.SOFT_BREAK, message_label.text())
        self.assertIn("Connection broken: IncompleteRead", message_label.text())

    def test_queue_recent_events_skip_identical_rebuilds(self):
        shell = self._make_shell()
        queue = shell.pages["queue"]
        snapshot = FrontendStateService.mock_snapshot()
        queue.render(snapshot)
        first_widget = queue.event_layout.itemAt(0).widget()

        queue.render(snapshot)

        self.assertIs(queue.event_layout.itemAt(0).widget(), first_widget)

    def test_web_page_headers_and_removed_controls_match_contract(self):
        content = _html_bundle()

        for header in (
            "<th>视频标题</th><th>平台</th><th>状态</th><th>操作</th>",
            "<th>标题</th><th>平台</th><th>进度</th><th>速度</th><th>剩余时间</th><th>操作</th>",
            "<th>标题</th><th>完成时间</th><th>时长</th><th>格式</th><th>操作</th>",
            "<th>标题</th><th>失败时间</th><th>失败原因</th><th>状态</th><th>操作</th>",
            "<th>时间</th><th>级别</th><th>来源</th><th>Trace ID</th><th>消息摘要</th>",
        ):
            self.assertIn(header, content)

        top_bar = content.split('<header class="top-bar" id="topBar">', 1)[1].split("</header>", 1)[0]
        for removed in ("错误摘要", "复制Trace", "导出日志", "清空记录"):
            self.assertNotIn(removed, top_bar)

        logs_page = content.split('id="page-logs"', 1)[1].split('id="page-settings"', 1)[0]
        self.assertNotIn("任务ID", logs_page)

    def test_web_queue_page_matches_gui_toolbar_and_status_icons(self):
        content = _html_bundle()
        css = _css_bundle()

        queue_page = content.split('id="page-queue"', 1)[1].split('id="page-active"', 1)[0]
        queue_status_fn = content.split("function queueStatusHtml", 1)[1].split("function queueRow", 1)[0]
        self.assertIn("queue-path-row", queue_page)
        self.assertIn("frontendAction('clear_queue'", queue_page)
        self.assertNotIn("queueComfortableBtn", queue_page)
        self.assertNotIn("queueCompactBtn", queue_page)
        self.assertIn("current.queue_status", queue_status_fn)
        self.assertIn("queue-status-cell", queue_status_fn)
        self.assertNotIn("status-pill", content)
        self.assertIn("#page-queue th, #page-queue td { height: 52px; }", css)
        self.assertIn("#page-queue th:nth-child(2), #page-queue td:nth-child(2) { width: 96px; }", css)
        self.assertIn("#page-queue th:nth-child(4), #page-queue td:nth-child(4) { width: 44px; }", css)
        self.assertIn(".queue-path-row .path-text", css)
        self.assertIn("color: var(--text);", css.split(".queue-path-row .path-text", 1)[1].split("}", 1)[0])

    def test_web_shell_matches_gui_island_structure(self):
        content = _html_bundle()
        css = _css_bundle()

        sidebar = content.split('id="leftPanel"', 1)[1].split('<section class="right-column">', 1)[0]
        top_bar = content.split('<header class="top-bar" id="topBar">', 1)[1].split("</header>", 1)[0]

        self.assertIn('class="platform-island"', sidebar)
        self.assertIn('id="sourceSelect"', sidebar)
        self.assertIn('class="nav-island"', sidebar)
        self.assertIn('class="nav-separator"', sidebar)
        self.assertNotIn('id="sourceSelect"', top_bar)
        self.assertIn('class="right-column"', content)
        self.assertIn('id="statusIndicator" class="status-dot"', content)
        self.assertIn('class="status-metric status-metric-main"><span class="status-caption" data-status-caption="下载速度">下载速度:</span><span id="statusDownload" class="status-value">0 B/s</span>', content)
        self.assertIn('id="statusHelpBtn"', content)
        self.assertNotIn('id="statusUpload"', content)
        self.assertNotIn('byId("statusUpload")', content)
        self.assertNotIn("upload_speed", content)
        self.assertNotIn("#statusUpload", css)
        self.assertIn(".platform-island", css)
        self.assertIn(".custom-select-source {\n  min-width: 176px;", css)
        self.assertIn(".source-select { min-width: 176px; }", css)
        self.assertIn(".search-input { flex: 1; min-width: 220px; }", css)
        self.assertIn("justify-content: center;", css)
        self.assertIn("width: 176px;\n  min-width: 176px;\n  max-width: 176px;", css)
        self.assertIn(".nav-island", css)
        self.assertIn(".nav-item {\n  height: 40px;", css)
        self.assertIn(".status-dot.running", css)
        self.assertIn(".status-help-btn", css)
        self.assertIn(".btn-theme { width: 48px; height: 36px;", css)
        self.assertIn(".btn-primary.is-running:disabled", css)
        self.assertIn("start-button-sweep", css)
        self.assertIn('startBtn.classList.toggle("is-running", crawlRunning);', content)
        self.assertIn("height: 34px;\n  flex: 0 0 34px;", css)
        self.assertIn(".status-value", css)
        self.assertIn(".status-metric-main", css)
        self.assertIn("min-width: 88px;", css)
        self.assertIn(".page-stack", css)
        self.assertIn("background: transparent", css)
        self.assertIn('data-icon="${escAttr(iconFileUrl(iconFile))}"', content)
        self.assertIn("class=\"custom-select-icon\"", content)
        self.assertIn(".custom-select-icon", css)
        self.assertIn(".custom-select-label", css)
        self.assertIn('themeButton.innerHTML = `<img src="/ui-icon/${iconFile}" alt="" />`', content)
        self.assertIn('caption.textContent = `${t(caption.dataset.statusCaption || "")}:`;', content)
        self.assertIn('byId("statusDownload").textContent = status.download_speed || "0 B/s";', content)
        self.assertIn('statusIndicator.className = `status-dot ${indicator === "idle" ? "" : indicator}`.trim()', content)

    def test_web_active_actions_keep_delete_only(self):
        content = _html_bundle()
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]

        self.assertNotIn("frontendAction('pause_download'", active_page)
        self.assertIn("frontendAction('delete_item'", content)

    def test_web_failed_page_uses_cards_and_removes_retry(self):
        content = _html_bundle()
        css = _css_bundle()
        failed_page = content.split('id="page-failed"', 1)[1].split('id="page-logs"', 1)[0]
        failed_fn = content.split("function failedRow", 1)[1].split("function failedDetailHtml", 1)[0]

        self.assertNotIn('class="page-head"', failed_page)
        self.assertIn("failed-table-card", failed_page)
        self.assertIn("failed-detail-card", failed_page)
        self.assertIn("failed-solutions-card", failed_page)
        self.assertIn("frontendAction('clear_failed_records',{})", failed_page)
        self.assertNotIn("retry_failed", failed_fn)
        self.assertIn("frontendAction('delete_failed_record'", failed_fn)
        self.assertNotIn("frontendAction('delete_item'", failed_fn)
        mock_fn = content.split("function buildMockState()", 1)[1].split("function configureCustomSelectHelpers", 1)[0]
        self.assertNotIn('actions: ["retry", "copy_diagnostics", "delete"]', mock_fn)
        self.assertIn("copyDiagnostics", failed_fn)
        self.assertIn("iconTextHtml", failed_fn)
        self.assertIn("failed_at_table || item.failed_at", failed_fn)
        self.assertIn("failedStatusHtml", failed_fn)
        self.assertIn("failedLogRowHtml", content)
        self.assertIn("solutionRowHtml", content)
        self.assertIn("#page-failed .failed-table-card", css)
        self.assertIn("#page-failed .failed-solutions-card", css)
        self.assertIn(".failed-clear-all", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(420px, clamp(420px, var(--detail-width, 440px), 540px));", css)
        self.assertIn("grid-template-columns: 82px minmax(0, 1fr);", css)
        self.assertIn(".failed-log-row", css)
        self.assertIn(".failed-solution-row", css)
        self.assertIn(".failed-status-chip", css)
        self.assertIn("#page-failed th:nth-child(4), #page-failed td:nth-child(4) { width: 82px; }", css)
        self.assertIn("#page-failed th:nth-child(5), #page-failed td:nth-child(5) { width: 72px; }", css)
        failed_log_fn = content.split("function failedLogRowHtml", 1)[1].split("function solutionRowHtml", 1)[0]
        self.assertIn("log-level", failed_log_fn)
        self.assertNotIn("<img", failed_log_fn)
        self.assertLess(failed_log_fn.index("log-time"), failed_log_fn.index("log-level"))
        self.assertIn("grid-template-columns: 9.5ch 74px minmax(0, 1fr)", css)
        self.assertIn("padding: 2px 0", css)
        self.assertIn("function failedLogTime", content)
        self.assertIn("failedLogTime(entry.time)", failed_log_fn)
        self.assertIn("#page-failed tbody td:nth-child(3)", css)
        self.assertIn(".failed-log-row .log-level", css)

    def test_web_log_center_matches_gui_tabs_actions_and_filters(self):
        content = _html_bundle()
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        log_display = (static_dir / "log_display.js").read_text(encoding="utf-8")
        i18n_js = (static_dir / "i18n.js").read_text(encoding="utf-8")
        logs_page = content.split('id="page-logs"', 1)[1].split('id="page-settings"', 1)[0]

        for tab in ("all", "crawl", "download", "system", "performance", "error"):
            self.assertIn(f'data-log-tab="{tab}"', logs_page)
        self.assertEqual(logs_page.count('class="log-filter-field"'), 5)
        self.assertEqual(logs_page.count('class="log-filter-label"'), 5)
        self.assertNotIn("<label><span>日志级别</span><select", logs_page)
        self.assertIn('id="logLevelFilter" aria-label="日志级别"', logs_page)
        self.assertIn('id="logTraceFilter" aria-label="Trace ID"', logs_page)
        self.assertIn('<option value="CMD">CMD</option>', logs_page)
        self.assertIn('<option value="30m" selected>近 30 分钟</option>', logs_page)
        self.assertIn('id="logEmptyState" class="log-empty-state" hidden', logs_page)
        self.assertIn("暂无匹配日志", logs_page)
        self.assertIn("调整筛选条件 或点击「刷新缓冲」重新加载日志", logs_page)
        self.assertIn("<span data-log-empty-primary>调整筛选条件</span>", logs_page)
        self.assertIn("<span data-log-empty-secondary>或点击「刷新缓冲」重新加载日志</span>", logs_page)
        self.assertNotIn("调整筛选条件，", logs_page)
        self.assertIn("function syncLogEmptyState", content)
        self.assertIn("syncLogEmptyState(items.length === 0);", content)
        self.assertIn("function syncLogTabLabels", content)
        self.assertIn("syncLogTabLabels();", content)
        self.assertIn("function selectValueOrFallback", content)
        self.assertIn('["logLevelFilter", "level", "all"]', content)
        self.assertIn('["logTimeFilter", "time", "30m"]', content)
        self.assertIn("syncCustomSelectForSelect(node);", content)
        css = _css_bundle()
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))", css)
        self.assertIn("#page-logs .log-tabs .tab", css)
        self.assertIn("min-width: 92px;", css)
        self.assertIn("height: 34px;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn("#page-logs .log-tabs .tab.active", css)
        self.assertIn("#page-logs .log-empty-state", css)
        self.assertIn("inset: 56px 0 0;", css)
        self.assertIn("flex-direction: column;", css.split("#page-logs .log-empty-state .log-empty-subtitle", 1)[1].split("}", 1)[0])
        log_filters_css = css.split("#page-logs .log-filters {", 1)[1].split("}", 1)[0]
        for expected_column in (
            "minmax(84px, .9fr)",
            "minmax(128px, 1.2fr)",
            "minmax(108px, 1fr)",
            "minmax(112px, 1fr)",
        ):
            self.assertIn(expected_column, log_filters_css)
        self.assertIn("border: 1px solid var(--border)", log_filters_css)
        self.assertIn("border-radius: 8px", log_filters_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(340px, clamp(340px, 26vw, 460px));", css)
        for expected_width in (
            "#page-logs th:nth-child(1), #page-logs td:nth-child(1) { width: 136px; }",
            "#page-logs th:nth-child(2), #page-logs td:nth-child(2) { width: 78px; }",
            "#page-logs th:nth-child(3), #page-logs td:nth-child(3) { width: 144px; }",
            "#page-logs th:nth-child(4), #page-logs td:nth-child(4) { width: 88px; }",
        ):
            self.assertIn(expected_width, css)
        self.assertIn("#page-logs .log-filter-label", css)
        self.assertIn("#page-logs .log-filter-field input", css)
        self.assertIn("flex: 0 0 40px", css)
        self.assertIn("#page-logs th, #page-logs td {\n  height: 32px;", css)
        self.assertIn("padding: 5px 8px;", css)
        self.assertIn("#page-logs .log-filter-label", i18n_js)
        for elem_id in ("logTotal", "logPrevPage", "logPageIndicator", "logPageSize", "logNextPage"):
            self.assertIn(f'id="{elem_id}"', logs_page)
        self.assertIn("共 0 条 / 匹配 0 条 / 当前显示 0 条", logs_page)
        self.assertIn("<option value=\"0\">全部</option>", logs_page)
        self.assertIn("#page-logs .log-footer {\n  min-height: 48px;", css)
        self.assertIn("flex-wrap: wrap;", css)
        self.assertIn("#logTotal {\n  flex: 1 1 128px;", css)
        self.assertIn("#logPageIndicator", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn("#page-logs .log-footer .btn {\n  height: 30px;", css)
        self.assertIn("#logPrevPage {\n  min-width: 112px;", css)
        self.assertIn("#logNextPage {\n  min-width: 100px;", css)
        self.assertIn("#page-logs .custom-select-page-size,\n#page-logs .custom-select-page-size .custom-select-button {\n  height: 30px;", css)
        self.assertIn("function setLogPage(delta)", content)
        self.assertIn("function setLogPageSize(value)", content)
        self.assertIn("boundedItems.slice(start, start + pageSize)", content)
        for action in (
            "runLogOperation('refresh')",
            "runLogOperation('clear')",
            "runLogOperation('export')",
            "runLogOperation('open_latest')",
            "runLogOperation('open_error_summary')",
            "copySelectedLogTraceId()",
        ):
            self.assertIn(action, logs_page)
        self.assertIn("function currentLogTraceId", content)
        self.assertIn("function copySelectedLogTraceId", content)
        log_detail_worker = (static_dir / "log_detail_worker.js").read_text(encoding="utf-8")
        for detail_worker_action in (
            "function normalizeLogDetailPayload",
            "function formatLogDetailDisplayText",
            "function readableLogDetailValue",
            "function buildLogDetailResult",
        ):
            self.assertIn(detail_worker_action, log_detail_worker)
            self.assertNotIn(detail_worker_action, content)
        for detail_action in (
            "function ensureLogDetailWorker",
            "function receiveLogDetailResult",
            "function submitLogDetail",
            "function currentLogDetailResult",
            "function renderLogDetailResult",
            "function copyCurrentLogDetail",
            "function copyCurrentLogJson",
            "function exportCurrentLogDetail",
        ):
            self.assertIn(detail_action, content)
        self.assertIn('new Worker("/static/log_detail_worker.js?v=20260709-log-detail-worker")', content)
        log_i18n = (static_dir / "log_i18n.js").read_text(encoding="utf-8")
        for translation_marker in (
            "function translateRuntimeLogText",
            "function localizeEnglishDynamicLogText",
            "function localizeLogEventCode",
        ):
            self.assertIn(translation_marker, log_i18n)
        self.assertIn("function logI18nService()", content)
        self.assertIn("logI18nService()?.localizeLogEventCode", content)
        self.assertIn('add("status_code", item.status_code || "", localizeLogEventCode(item.status_code || ""));', log_i18n)
        self.assertIn('add("event_code", item.event_code || "", localizeLogEventCode(item.event_code || ""));', log_i18n)
        self.assertIn('if (sections.has("settings_snapshot")) updatePlaceholder();', content)
        self.assertIn("trimFrontendLogItems();\n  updatePlaceholder();", content)
        self.assertIn("log-inspector-header", content)
        self.assertIn("log-json-card", content)
        self.assertIn("log-detail-readable", content)
        self.assertIn('data-json="${escAttr(result.detailJson || "{}")}"', content)
        self.assertIn("function emptyLogDetailSummaryHtml", content)
        self.assertIn("${emptyLogDetailSummaryHtml()}", content)
        self.assertIn('<pre class="log-snippet">{}</pre>', content)
        self.assertIn("copyCurrentLogJson()", content)
        self.assertIn("copyCurrentLogDetail()", content)
        self.assertIn("exportCurrentLogDetail()", content)
        self.assertIn("#page-logs .log-inspector-header", css)
        self.assertIn("#page-logs .logs-right-column", css)
        self.assertIn("#page-logs .log-json-card .log-snippet", css)
        self.assertIn("#page-logs .log-detail-readable", css)
        self.assertIn('return "performance"', log_display)
        self.assertIn('return "crawl"', log_display)

    def test_web_basic_settings_use_backend_options_and_update_action(self):
        content = _html_bundle()
        css = _css_bundle()
        settings_fn = content.split("function settingsControls", 1)[1].split('if (group === "\u4e0b\u8f7d\u8bbe\u7f6e"', 1)[0]

        self.assertIn("value._options", settings_fn)
        self.assertIn("options.filename_template", settings_fn)
        self.assertIn("options.default_open_mode", settings_fn)
        self.assertIn("SETTING_SHORT_DESCRIPTIONS", content)
        self.assertIn("settingLabelHtml", content)
        self.assertIn("settingControlCluster", content)
        self.assertIn("update_basic_setting", content)
        self.assertIn("showFileAssociationModal()", settings_fn)
        self.assertIn("const associationButton", settings_fn)
        self.assertIn('settingCheckbox("\\u663e\\u793a\\u6d4f\\u89c8\\u5668\\u5185\\u6838", "show_browser_window"', settings_fn)
        self.assertIn("MissAV \\u6709 5 \\u79d2\\u76fe", content)
        self.assertIn('settingSelect("\\u4e0b\\u8f7d\\u5b8c\\u6210\\u6253\\u5f00\\u65b9\\u5f0f", "default_open_mode"', settings_fn)
        self.assertIn('frontendAction("register_file_associations", { include_video: includeVideo, include_image: includeImage })', content)
        self.assertNotIn("settingNumber", content)
        self.assertNotIn('type="number"', content)
        self.assertIn("options.speed_limit_kb", content)
        self.assertIn('"image_respects_concurrency"', content)
        self.assertIn('settingCheckbox("\\u56fe\\u7247\\u53d7\\u5e76\\u53d1\\u6570\\u9650\\u5236"', content)
        self.assertIn('label: "\\u65e0\\u9650\\u5236"', content)
        self.assertNotIn("\\u65e0\\u9650\\u5236\\uff080 KB/s\\uff09", content)
        download_settings_fn = content.split('if (group === "\\u4e0b\\u8f7d\\u8bbe\\u7f6e")', 1)[1].split('if (group === "\\u5e73\\u53f0\\u8bbe\\u7f6e")', 1)[0]
        ordered_download_controls = [
            '"max_retries"',
            '"resume_enabled"',
            '"speed_limit_kb"',
            '"video_only"',
        ]
        self.assertEqual(
            [download_settings_fn.index(control) for control in ordered_download_controls],
            sorted(download_settings_fn.index(control) for control in ordered_download_controls),
        )
        self.assertIn("applyAppearance", content)
        self.assertIn('open_after_download: false', content)
        self.assertIn('show_browser_window: true', content)
        self.assertIn('filename_template: "current"', content)
        self.assertIn('default_open_mode: "builtin_player"', content)
        self.assertIn('default_player: "builtin_player"', content)
        self.assertIn('settingSelect("\\u624b\\u52a8\\u64ad\\u653e\\u65b9\\u5f0f", "default_player"', content)
        self.assertIn("\\u81ea\\u52a8\\u6253\\u5f00\\u5f00\\u542f\\u65f6\\u4f7f\\u7528", content)
        self.assertIn("\\u70b9\\u51fb\\u64ad\\u653e\\u952e\\u65f6\\u4f7f\\u7528", content)
        self.assertIn('frontendAction("open_file"', content)
        self.assertIn("shouldUseBuiltinPlayer", content)
        self.assertIn("shouldAutoplayNext", content)
        self.assertIn("imageManualSwitchSetting", content)
        settings_render_source = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "settings_render.js").read_text(encoding="utf-8")
        self.assertIn("\\u65e5\\u5fd7\\u4fdd\\u7559\\u5929\\u6570", settings_render_source)
        self.assertIn("UI\\u65e5\\u5fd7\\u6700\\u5927\\u663e\\u793a\\u6570\\u91cf", settings_render_source)
        self.assertNotIn('settingSelect("\\u4fdd\\u7559\\u5929\\u6570"', settings_render_source)
        self.assertNotIn('settingSelect("UI\\u6700\\u5927\\u663e\\u793a\\u6570"', settings_render_source)
        self.assertIn("\\u91cd\\u8bd5\\u6b21\\u6570", settings_render_source)
        self.assertIn("\\u4e0b\\u8f7d\\u901f\\u5ea6\\u9650\\u5236\\uff08KB/s\\uff09", settings_render_source)
        self.assertNotIn("\\u6700\\u5927\\u91cd\\u8bd5", settings_render_source)
        self.assertNotIn("\\u901f\\u5ea6\\u9650\\u5236 KB/s", settings_render_source)
        self.assertIn("\\u8bb0\\u4f4f\\u64ad\\u653e\\u8fdb\\u5ea6", settings_render_source)
        self.assertIn("\\u89c6\\u9891\\u64ad\\u653e\\u5b8c\\u81ea\\u52a8\\u4e0b\\u4e00\\u9879", settings_render_source)
        self.assertIn("\\u56fe\\u7247\\u53ea\\u624b\\u52a8\\u5207\\u6362", settings_render_source)
        self.assertNotIn("\\u8bb0\\u4f4f\\u64ad\\u653e\\u4f4d\\u7f6e", settings_render_source)
        self.assertNotIn("\\u81ea\\u52a8\\u64ad\\u653e\\u4e0b\\u4e00\\u9879", settings_render_source)
        self.assertNotIn("\\u624b\\u52a8\\u5207\\u6362\\u56fe\\u7247", settings_render_source)
        self.assertIn("image_auto_advance_interval_seconds", content)
        self.assertIn("imageAutoAdvanceIntervalMs", content)
        self.assertIn(".image-auto-interval[hidden]", css)
        self.assertNotIn('"hardware_acceleration"', content)
        self.assertNotIn('"builtin_player_enabled"', content)
        self.assertNotIn('settingCheckbox("\\u5185\\u7f6e\\u64ad\\u653e\\u5668"', content)
        self.assertNotIn('settingCheckbox("\\u786c\\u4ef6\\u52a0\\u901f"', content)
        self.assertIn("retention_days: 1", content)
        self.assertIn("uiLogDisplayLimit", content)
        self.assertIn("trimFrontendLogItems", content)
        self.assertIn('value: "100", label: "100 条"', content)
        self.assertIn('value: "300", label: "300 条（推荐）"', content)
        self.assertIn('value: "500", label: "500 条"', content)
        self.assertNotIn('value: "1000", label: "1000 条"', content)
        self.assertNotIn('value: "2000", label: "2000 条"', content)
        self.assertNotIn('value: "5000", label: "5000 条"', content)
        self.assertIn('"1", label: "1 天（推荐）"', content)
        self.assertNotIn('level: "info"', content)
        self.assertNotIn('"cleanup_old_logs_on_start"', content)
        self.assertNotIn('settingSelect("\\u65e5\\u5fd7\\u7ea7\\u522b", "level"', content)
        self.assertNotIn('settingCheckbox("\\u542f\\u52a8\\u65f6\\u6e05\\u7406\\u65e7\\u65e5\\u5fd7"', content)
        self.assertIn('accent: "blue"', content)
        self.assertIn('font_size: "medium"', content)
        self.assertIn('language: "zh-CN"', content)
        self.assertIn('settingSelect("语言", "language"', content)
        self.assertIn("themeSegmentSetting", content)
        self.assertIn("selectAppearanceTheme", content)
        self.assertIn("appearance.follow_system = false", content)
        self.assertIn('data-setting="theme"', content)
        self.assertNotIn('settingSelect("\\u4e3b\\u9898", "theme"', content)
        self.assertIn("handleProxySelect", content)
        self.assertIn("commitProxyCustom", content)
        self.assertIn("proxyCustomDisplayValue", content)
        self.assertIn("proxyOptionDisplayLabel", content)
        self.assertIn("platform-proxy-entry", content)
        self.assertIn(r'placeholder="${escapeAttr(translate("\u7aef\u53e3"))}"', content)
        self.assertIn("hidden disabled", content)
        self.assertIn('row.classList.toggle("has-proxy-custom", custom)', content)
        self.assertIn('proxyEntry.classList.toggle("has-custom", custom)', content)
        self.assertIn("optionLabel", content)
        self.assertIn("switchSettingsGroup", content)
        self.assertIn("settings-shell", content)
        self.assertIn("settings-nav-btn", content)
        self.assertIn("SETTINGS_GROUP_ICONS", content)
        self.assertIn("function settingGroupIconFile", content)
        self.assertIn("settingGroupIconFile(group)", content)
        self.assertIn("settingGroupIconFile(currentSettingsGroup)", content)
        self.assertIn("settings-detail-icon", content)
        self.assertIn('action_open_directory.png', content)
        self.assertIn('action_theme_palette.png', content)
        self.assertIn("SETTINGS_GROUP_HINTS_FALLBACK", content)
        self.assertIn("settings-hint-card", content)
        self.assertIn("has-trailing-action", content)
        self.assertIn("settingRowClassForKey", content)
        self.assertIn("setting-wide-control", content)
        self.assertIn("associationText", content)
        self.assertIn('>${associationText}</button>', content)
        self.assertIn("associationAttr", content)
        self.assertIn('aria-label="${associationAttr}"', content)
        self.assertIn("setting-path-browse", content)
        self.assertIn("选择保存目录", content)
        self.assertIn('onclick="showDirDialog()"', content)
        self.assertIn("contract.group_hints", content)
        self.assertIn("集中管理下载行为、平台状态、播放体验、日志策略与界面外观", content)
        self.assertIn('document.querySelector("#page-settings .page-head p")', content)
        self.assertIn("高效实用的辅助工具，提升工作效率", content)
        self.assertIn('document.querySelector("#page-toolbox .page-head p")', content)
        self.assertIn('class="detail-panel toolbox-detail" id="toolDetail"', content)
        self.assertIn(".toolbox-detail {\n  display: flex;", css)
        self.assertIn(".toolbox-detail > .btn {\n  width: 100%;\n  margin-top: auto;", css)
        self.assertIn(".toolbox-detail .recent-list", css)
        self.assertIn("align-content: start", css.split(".toolbox-detail .kv {", 1)[1].split("}", 1)[0])
        self.assertIn('icon_file: "tool_link_parser.png"', content)
        self.assertIn('icon_file: "tool_batch_rename.png"', content)
        self.assertIn('icon_file: "tool_file_verify.png"', content)
        self.assertNotIn('item.icon_file || "nav_toolbox.png"', content.split("function buildMockState", 1)[1].split("toolbox_recent_items", 1)[0])
        self.assertIn("platformSettingsSummary", content)
        self.assertIn("setting-platform-header", content)
        self.assertIn("platformIconUrl", content)
        self.assertIn("platform-name-cell", content)
        self.assertIn("platform-auth-badge", content)
        self.assertIn("platform-count", content)
        self.assertIn("platform-timeout", content)
        self.assertIn("platform-proxy", content)
        self.assertIn("const timeoutKey = platformRow.timeout_config_key", content)
        self.assertIn("config[timeoutKey] = timeoutValue", content)
        self.assertIn(".setting-row select:focus", css)
        self.assertIn(".setting-label", css)
        self.assertIn(".setting-control-cluster", css)
        self.assertIn(".setting-row input[type=\"checkbox\"].setting-switch", css)
        self.assertIn(".settings-hint-card", css)
        self.assertIn(".settings-hint-icon", css)
        self.assertIn("width: min(1080px, max(520px, 82%));", css)
        self.assertIn("gap: 7px", css)
        self.assertIn("padding: 10px;", css)
        self.assertIn(".setting-wide-control", css)
        self.assertIn("min-height: 60px", css)
        self.assertIn("height: 40px;", css.split(".settings-hint-card", 1)[1].split("}", 1)[0])
        self.assertIn("width: 100%;", css.split(".settings-platform-body", 1)[1].split("}", 1)[0])
        self.assertNotIn("max-width: 594px", css)
        self.assertIn("select option", css)
        self.assertIn(".proxy-custom.active", css)
        self.assertIn(".proxy-custom[hidden]", css)
        self.assertIn(".settings-shell", css)
        self.assertIn(".settings-side-nav", css)
        self.assertIn(".settings-nav-btn img", css)
        self.assertIn(".settings-nav-btn span", css)
        self.assertIn(".settings-detail-icon", css)
        self.assertIn(".settings-detail-icon img", css)
        self.assertIn("grid-template-columns: 32px minmax(0, 1fr)", css)
        self.assertIn("width: 32px;\n  height: 32px", css)
        self.assertIn("width: 20px;\n  height: 20px", css)
        self.assertIn("#page-settings .page-head {\n  flex-direction: column;", css)
        self.assertIn("align-items: flex-start;", css)
        self.assertIn(".setting-control-cluster.has-trailing-action", css)
        self.assertIn("flex: 0 0 94px", css)
        self.assertIn(".platform-summary", css)
        self.assertIn(".platform-name-cell", css)
        self.assertIn(".platform-name-cell img", css)
        self.assertIn(".platform-auth-badge", css)
        self.assertIn(".platform-auth-badge.is-authed", css)
        self.assertIn(".platform-auth-badge.is-unauthed", css)
        self.assertIn("has-proxy-custom", content)
        self.assertIn(".platform-proxy-entry.has-custom", css)
        self.assertIn("grid-template-columns: minmax(72px, 48fr) minmax(86px, 52fr)", css)
        self.assertIn(".platform-proxy-entry .custom-select.platform-proxy", css)
        self.assertIn("grid-template-columns: minmax(64px, 86px) minmax(92px, 104px)", css)
        self.assertIn(".setting-download-directory", css)
        self.assertIn(".setting-path-browse", css)
        self.assertIn(".setting-path-browse img", css)
        self.assertIn(".setting-theme-segment", css)
        self.assertIn(".setting-theme-segment-btn.active", css)
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn(".setting-platform .platform-count", css)
        self.assertIn(".setting-platform .platform-timeout", css)
        self.assertIn(".setting-platform .platform-proxy-entry", css)
        self.assertNotIn("setting-card-wide", content)
        self.assertNotIn('default_player: "内置播放器"', content)
        self.assertNotIn('accent: "#0d6efd"', content)

    def test_web_completed_page_uses_three_cards_short_time_and_media_fullscreen(self):
        content = _html_bundle()
        css = _css_bundle()
        completed_page = content.split('id="page-completed"', 1)[1].split('id="page-failed"', 1)[0]

        self.assertNotIn('class="page-head"', completed_page)
        self.assertNotIn('id="completedSummary"', completed_page)
        self.assertIn("completed-table-card", completed_page)
        self.assertIn("completed-preview-card", completed_page)
        self.assertIn("completed-info-card", completed_page)
        self.assertIn("completed-footer", completed_page)
        self.assertIn('id="mediaViewport"', completed_page)
        self.assertIn('id="mediaControls"', completed_page)
        self.assertIn('id="playBtn"', completed_page)
        self.assertIn('id="prevBtn"', completed_page)
        self.assertIn('id="nextBtn"', completed_page)
        self.assertIn('id="seekSlider"', completed_page)
        self.assertIn('id="timeLabel"', completed_page)
        self.assertIn('id="fullscreenBtn"', completed_page)
        self.assertNotIn('<video id="videoPlayer" controls', completed_page)
        compat_hidden = content.split('<div class="compat-hidden"', 1)[1]
        for control_id in ("playBtn", "prevBtn", "nextBtn", "seekSlider", "timeLabel", "fullscreenBtn"):
            self.assertNotIn(f'id="{control_id}"', compat_hidden)
        self.assertIn('id="completedPageSize"', completed_page)
        self.assertIn("function setCompletedPage", content)
        self.assertIn("function setCompletedPageSize", content)
        self.assertNotIn("<th>分辨率</th>", completed_page)
        self.assertNotIn("<th>大小</th>", completed_page)
        self.assertIn("completed_at_table || item.completed_at", content)
        detail_fn = content.split("function completedDetailHtml", 1)[1].split("function iconTextHtml", 1)[0]
        for expected in ("\\u6587\\u4ef6\\u540d", "\\u4fdd\\u5b58\\u8def\\u5f84", "\\u5b8c\\u6210\\u65f6\\u95f4", "\\u65f6\\u957f", "\\u5206\\u8fa8\\u7387", "\\u5927\\u5c0f", "\\u683c\\u5f0f"):
            self.assertIn(expected, detail_fn)
        self.assertIn("LONG_TEXT_KEYS", content)
        self.assertIn('["\\u6807\\u9898", "\\u6587\\u4ef6\\u540d", "\\u8f93\\u51fa\\u6587\\u4ef6\\u540d"]', content)
        self.assertIn('title="${escapeAttr(valueText)}"', content)
        for removed in ("\\u4e0b\\u8f7d\\u901f\\u5ea6", "\\u5b8c\\u6210\\u6982\\u89c8", "\\u5b58\\u50a8\\u5360\\u7528"):
            self.assertNotIn(removed, detail_fn)
        self.assertIn('byId("previewPanel")', content)
        self.assertIn("panel.requestFullscreen", content)
        self.assertNotIn('document.body.classList.toggle("is-fullscreen"', content)
        self.assertIn("#page-completed .completed-table-card", css)
        self.assertIn("#page-completed .completed-detail", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(400px, clamp(400px, 28vw, 620px));", css)
        self.assertIn("flex: 2 1 260px", css)
        self.assertIn("min-height: 260px", css)
        media_controls_block = css.split(".media-controls", 1)[1].split(".media-control-btn,", 1)[0]
        self.assertIn("height: 50px", media_controls_block)
        self.assertIn("padding: 0 15px", media_controls_block)
        self.assertIn("gap: 10px", media_controls_block)
        media_button_block = css.split(".media-control-btn {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 32px", media_button_block)
        self.assertIn("height: 32px", media_button_block)
        self.assertIn("min-width: 40px", css.split(".media-seek {", 1)[1].split("}", 1)[0])
        self.assertIn("min-width: 64px", css.split(".media-time {", 1)[1].split("}", 1)[0])
        self.assertIn("function installMediaControlHandlers", content)
        self.assertIn("function updateMediaControls", content)
        self.assertIn("renderCompletedDetail();\n  updateNavBtnsState();\n  updateMediaControls();", content)
        self.assertIn("function switchPreview", content)
        self.assertIn("function onSeekInput", content)
        self.assertIn("function onSeekCommit", content)
        self.assertIn("const canStartPreview = !!(currentPlayingId || selected.completed || selectedVideoId);", content)
        self.assertIn("!hasVideo && !canStartPreview", content)
        self.assertIn("player.onloadedmetadata", content)
        self.assertIn("player.ondurationchange", content)
        self.assertIn("player.onplay", content)
        self.assertIn("updateFullscreenButtonState", content)
        self.assertNotIn("button.disabled = !hasPreviewContent()", content)
        self.assertNotIn("if (!hasPreviewContent()) return;", content)
        self.assertIn("adjacentCompletedId(currentPlayingId, 1, false)", content)
        self.assertIn(".preview-panel:fullscreen", css)
        self.assertIn("#page-completed th:nth-child(2), #page-completed td:nth-child(2) { width: 142px; }", css)
        self.assertIn("#page-completed th:nth-child(3), #page-completed td:nth-child(3) { width: 108px; }", css)
        self.assertIn("#page-completed th:nth-child(4), #page-completed td:nth-child(4) { width: 76px; }", css)
        self.assertIn("#page-completed th:nth-child(5), #page-completed td:nth-child(5) { width: 100px; }", css)
        self.assertIn("#page-completed .completed-info-card .kv-value.long-text", css)
        self.assertIn("-webkit-line-clamp: 5", css)

    def test_web_active_controls_and_detail_values_are_wrap_ready(self):
        content = _html_bundle()
        css = _css_bundle()
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]

        self.assertIn('class="active-control-title">队列控制</strong>', active_page)
        self.assertIn('class="active-toggle"', active_page)
        self.assertIn('id="activeAutoRetry"', active_page)
        self.assertIn('id="activeMaxConcurrent"', active_page)
        self.assertIn('<option value="3" selected>3（推荐）</option>', active_page)
        self.assertIn('<option value="1">1</option>', active_page)
        self.assertIn('<option value="5">5</option>', active_page)
        self.assertNotIn('<option value="8">8</option>', active_page)
        self.assertNotIn('<option value="12" selected>', active_page)
        self.assertIn('<option value="10">', active_page)
        self.assertIn("function syncActiveDownloadOptions", content)
        self.assertIn("frontendState.download_options", content)
        self.assertIn("function smartWrapText", content)
        self.assertIn('kv-value smart-wrap${LONG_TEXT_KEYS.has(keyText) ? " long-text" : ""}', content)
        self.assertIn('kv-value${LONG_TEXT_KEYS.has(keyText) ? " long-text" : ""}', content)
        self.assertIn("long-text", content)
        self.assertIn("active-detail-fields", content)
        self.assertIn("active-detail-metrics", content)
        active_detail_fn = content.split("function activeDetailHtml", 1)[1].split("function completedDetailHtml", 1)[0]
        self.assertIn("item.detail_fields", active_detail_fn)
        self.assertIn("item.chunk_progress_label", active_detail_fn)
        self.assertIn("item.speed_trend_label", active_detail_fn)
        for removed in (
            "\\u7ebf\\u7a0b\\u6570",
            "\\u91cd\\u8bd5\\u6b21\\u6570",
            "\\u5199\\u5165\\u72b6\\u6001",
            "\\u5408\\u5e76\\u72b6\\u6001",
        ):
            self.assertNotIn(removed, active_detail_fn)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn(".kv-value.smart-wrap { overflow-wrap: normal", css)
        self.assertIn("#page-active .page-grid", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(360px, clamp(360px, var(--detail-width, 400px), 500px));", css)
        self.assertIn(".active-control-title", css)
        self.assertIn("#page-active .controls-panel.active-controls", css)
        self.assertIn("height: 96px;", css)
        self.assertIn("flex-direction: column;", css)
        self.assertIn("#activeSummary", css)
        self.assertIn("#page-active td {\n  height: 74px;", css)
        self.assertIn("#page-active th {\n  height: 40px;", css)
        self.assertIn("#page-active th:nth-child(2), #page-active td:nth-child(2) { width: 82px; }", css)
        self.assertIn("#page-active th:nth-child(3), #page-active td:nth-child(3) { width: 118px; }", css)
        self.assertIn("#page-active th:nth-child(6), #page-active td:nth-child(6) { width: 72px; }", css)
        self.assertIn("#activeDetail .active-detail-card", css)
        self.assertIn("#activeDetail .active-detail-fields .kv", css)
        self.assertIn("#activeDetail .active-detail-fields .kv-value.long-text", css)
        self.assertIn("-webkit-line-clamp: 4", css)
        self.assertIn("line-height: 1.18", css)
        self.assertIn("flex: 1 1 0", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn('activeTrendRenderer(item.speed_trend || [], item.speed_trend_label || item.speed || "0 B/s")', content)
        self.assertIn('text-anchor="end"', content)
        self.assertIn("onloadedmetadata", content)
        self.assertIn('"update_completed_metadata"', content)
        self.assertIn("metadataValueRenderer(item.duration, item.metadata_pending)", content)
        self.assertIn("speed-label", content)
        self.assertIn("stroke-linecap: round", css)
        self.assertIn('"队列控制": "Queue controls"', content)
        self.assertIn("stroke-linejoin: round", css)

    def test_web_rendering_uses_stable_dom_update_guards(self):
        content = _html_bundle()
        css = _css_bundle()

        self.assertIn("function setHtmlIfChanged", content)
        self.assertIn("function patchTableRows", content)
        self.assertIn('patchTableRows("queueBody"', content)
        self.assertIn('setHtmlIfChanged("activeDetail"', content)
        self.assertIn('setHtmlIfChanged("completedDetail"', content)
        self.assertNotIn('byId("activeDetail").innerHTML', content)
        self.assertIn("hasFocusedDescendant(\"settingsGrid\")", content)
        self.assertIn("webui_detail_width", content)
        self.assertIn("oldRow.classList.remove(\"selected\")", content)
        self.assertIn("--row-hover", css)
        self.assertIn("tbody tr:hover:not(.selected) td", css)
        self.assertIn("tr.selected:hover td", css)
        self.assertIn("background: var(--row-selected)", css)
        self.assertIn(".op.icon {\n  width: 24px;\n  height: 28px;", css)
        self.assertIn("border-color: transparent", css)
        self.assertIn("#page-active td:nth-child(6)", css)
        self.assertIn("scrollbar-color: var(--border-strong) transparent", css)
        self.assertIn("*::-webkit-scrollbar-button", css)
        self.assertIn("background-clip: content-box", css)
        self.assertIn("margin: 0 4px;", css)

    def test_web_custom_select_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        custom_select = (static_dir / "custom_select.js").read_text(encoding="utf-8")

        self.assertIn("/static/custom_select.js", index)
        self.assertIn("window.UcpCustomSelect", custom_select)
        self.assertIn("window.UcpCustomSelect.enhance", app_js)
        self.assertIn("window.UcpCustomSelect.syncForSelect", app_js)
        self.assertIn("fitWidthToContent", custom_select)
        self.assertIn("custom-select-page-size", custom_select)
        self.assertIn("optionTextWidth", custom_select)
        self.assertIn("originalValue", custom_select)
        self.assertIn("option.value = option.dataset.originalValue", custom_select)
        self.assertIn("updateMenuPlacement", custom_select)
        self.assertIn('wrapper.classList.toggle("open-up", shouldOpenUp)', custom_select)
        self.assertIn('menu.style.top = `${top}px`', custom_select)
        self.assertNotIn("let openCustomSelect", app_js)

    def test_web_custom_select_theme_states_keep_labels_readable(self):
        css = _css_bundle()
        dark_theme = css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
        selected_block = css.split(
            '.custom-select-option.selected,\n.custom-select-option[aria-selected="true"]',
            1,
        )[1].split("}", 1)[0]
        label_inherit_block = css.split(
            ".setting-row .custom-select .custom-select-button .custom-select-label",
            1,
        )[1].split("}", 1)[0]

        self.assertIn("--select-menu-bg: var(--panel);", css)
        self.assertIn("--select-menu-bg: var(--input);", dark_theme)
        self.assertIn("--select-option-selected-text: var(--on-accent);", css)
        self.assertIn("--select-option-selected-text: #111827;", dark_theme)
        self.assertIn("color: var(--select-option-selected-text);", selected_block)
        self.assertIn(".custom-select-option[aria-selected=\"true\"]", css)
        self.assertIn(".setting-row .custom-select .custom-select-menu .custom-select-label", css)
        self.assertIn(".setting-platform .custom-select .custom-select-menu .custom-select-label", css)
        self.assertIn("color: inherit;", label_inherit_block)
        self.assertIn("font-weight: inherit;", label_inherit_block)

    def test_web_custom_select_autofits_count_and_page_size_without_menu_gap(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        css = (static_dir / "app.css").read_text(encoding="utf-8")
        custom_select = (static_dir / "custom_select.js").read_text(encoding="utf-8")

        self.assertIn('wrapper.classList.contains("custom-select-count")', custom_select)
        self.assertIn('wrapper.classList.contains("custom-select-page-size")', custom_select)
        self.assertIn("Math.ceil(widest + 48)", custom_select)
        self.assertIn(".custom-select-count {\n  width: auto;", css)
        self.assertIn(".custom-select-page-size", css)
        self.assertIn(".custom-select-page-size .custom-select-button {\n  height: 34px;", css)
        self.assertIn(".custom-select-menu", css)
        self.assertIn(".custom-select.open-up .custom-select-menu", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("calc(var(--option-count, 6) * 36px + 4px)", css)
        self.assertIn("padding: 0;", css)
        self.assertIn("border-radius: 0;", css)

    def test_web_top_bar_wraps_on_narrow_desktop_without_squashing_buttons(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        css = (static_dir / "app.css").read_text(encoding="utf-8")

        self.assertIn("flex: 0 0 auto;", css)
        self.assertIn("@media (max-width: 1120px) and (min-width: 981px)", css)
        self.assertIn(".top-bar .search-input", css)
        self.assertIn("flex: 1 1 100%;", css)
        self.assertIn("min-width: 0;", css)

    def test_web_media_display_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        media_display = (static_dir / "media_display.js").read_text(encoding="utf-8")
        task_render = (static_dir / "task_render.js").read_text(encoding="utf-8")

        self.assertIn("/static/media_display.js", index)
        self.assertLess(index.index("/static/media_display.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpMediaDisplay", media_display)
        self.assertIn("activeTrendHtml(values, speedLabel", media_display)
        self.assertIn("function smoothTrendPath(points)", media_display)
        self.assertIn('<path d="${linePath}" class="line" />', media_display)
        self.assertNotIn("<polyline", media_display)
        self.assertIn("displayMetadataValue(value, pending", media_display)
        self.assertIn("return translate(text);", media_display)
        self.assertIn("function pendingMetadataLabel()", media_display)
        self.assertIn('return pending ? pendingMetadataLabel() : "--";', media_display)
        self.assertIn("window.UcpMediaDisplay.activeTrendHtml", app_js)
        self.assertIn("window.UcpMediaDisplay.displayMetadataValue", app_js)
        self.assertIn("let metadataValueRenderer = (value, pending = false) => {", task_render)
        self.assertIn("function pendingMetadataLabel()", task_render)
        self.assertIn('return pending ? pendingMetadataLabel() : "--";', task_render)

    def test_web_log_display_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        log_display = (static_dir / "log_display.js").read_text(encoding="utf-8")

        self.assertIn("/static/log_display.js", index)
        self.assertLess(index.index("/static/log_display.js"), index.index("/static/app.js"))
        self.assertIn("root.UcpLogDisplay", log_display)
        self.assertIn("logMatchesFilters(item, filters", log_display)
        self.assertIn("visibleLogItems(items, rowBudget", log_display)
        self.assertIn("window.UcpLogDisplay.filteredLogItems", app_js)
        self.assertIn("window.UcpLogDisplay.visibleLogItems", app_js)
        self.assertIn("function syncLogStaticLanguage()", app_js)
        self.assertIn("syncLogStaticLanguage();", app_js)
        self.assertNotIn("const category = logCategory(item);", app_js)


    def test_web_settings_render_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        settings_render = (static_dir / "settings_render.js").read_text(encoding="utf-8")

        self.assertIn("/static/settings_render.js", index)
        self.assertLess(index.index("/static/settings_render.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpSettingsRender", settings_render)
        self.assertIn("settingsControls(group, value)", settings_render)
        self.assertIn("platformSettingRow(row)", settings_render)
        self.assertIn("window.UcpSettingsRender.configure", app_js)
        self.assertIn("window.UcpSettingsRender || null", app_js)
        self.assertNotIn("const options = value && value._options ? value._options : {};", app_js)

    def test_gui_settings_platform_controls_are_split_into_component(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "app" / "ui" / "pages" / "settings_page.py").read_text(encoding="utf-8")
        controls = (root / "app" / "ui" / "components" / "settings_platform_controls.py").read_text(encoding="utf-8")

        self.assertIn("from app.ui.components.settings_platform_controls import", page)
        self.assertIn("build_platform_count_combo(", page)
        self.assertIn("build_platform_timeout_combo(", page)
        self.assertIn("build_platform_proxy_widget(", page)
        self.assertIn("def build_platform_proxy_widget", controls)
        self.assertIn("SettingsProxyControl", controls)
        self.assertNotIn("compact_proxy_options(list(row.get(\"proxy_options\")", page)

    def test_gui_log_inspector_sections_are_split_into_component(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "app" / "ui" / "pages" / "log_center_page.py").read_text(encoding="utf-8")
        sections = (root / "app" / "ui" / "components" / "log_inspector_sections.py").read_text(encoding="utf-8")

        self.assertIn("from app.ui.components.log_inspector_sections import", page)
        self.assertIn("build_log_detail_summary_section(", page)
        self.assertIn("build_log_json_section(", page)
        self.assertIn("class LogInspectorRefs", sections)
        self.assertIn("def build_log_stack_section", sections)
        self.assertNotIn("self.detail_copy_button = QPushButton", page)
        self.assertNotIn("self.json_copy_button = QPushButton", page)

    def test_gui_log_detail_wraps_long_fields_without_horizontal_overflow(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "app" / "ui" / "pages" / "log_center_page.py").read_text(encoding="utf-8")
        sections = (root / "app" / "ui" / "components" / "log_inspector_sections.py").read_text(encoding="utf-8")

        self.assertIn("SmartWrapLabel", sections)
        self.assertIn("def _detail_value_label", sections)
        self.assertIn("layout.addWidget(value_widget, 1)", sections)
        self.assertIn("row.setMinimumHeight(24)", sections)
        self.assertNotIn("row.setFixedHeight(26)", sections)
        self.assertIn("setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)", sections)
        self.assertIn("setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)", sections)
        self.assertIn("layout_hint = self.detail_summary_section.layout().sizeHint().height()", page)
        self.assertIn("overflow-wrap: anywhere", page)

    def test_gui_log_inspector_avoids_nested_vertical_scrollbars(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "app" / "ui" / "pages" / "log_center_page.py").read_text(encoding="utf-8")

        self.assertIn("self.inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)", page)
        self.assertIn("remaining_for_json", page)
        self.assertIn("json_chrome = 76", page)
        self.assertIn("self.json_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)", page)

    def test_gui_log_center_controls_are_split_into_component(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "app" / "ui" / "pages" / "log_center_page.py").read_text(encoding="utf-8")
        controls = (root / "app" / "ui" / "components" / "log_center_controls.py").read_text(encoding="utf-8")

        self.assertIn("from app.ui.components.log_center_controls import", page)
        self.assertIn("build_log_action_bar(", page)
        self.assertIn("build_log_table_footer(", page)
        self.assertIn("class LogTableFooterRefs", controls)
        self.assertIn("def build_log_action_bar", controls)
        self.assertIn("def build_log_table_footer", controls)
        self.assertNotIn("self.copy_trace_button = button", page)
        self.assertNotIn("self.footer_stats = QLabel", page)
        self.assertNotIn("self.page_size_combo = ThemedComboBox", page)

    def test_web_task_render_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        task_render = (static_dir / "task_render.js").read_text(encoding="utf-8")

        self.assertIn("/static/task_render.js", index)
        self.assertLess(index.index("/static/task_render.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpTaskRender", task_render)
        self.assertIn("queueRow(item)", task_render)
        self.assertIn("activeDetailHtml(item)", task_render)
        self.assertIn("completedDetailHtml(item)", task_render)
        self.assertIn("failedDetailHtml(item)", task_render)
        self.assertIn("window.UcpTaskRender.configure", app_js)
        self.assertIn("window.UcpTaskRender || null", app_js)

    def test_web_playback_state_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        playback_state = (static_dir / "playback_state.js").read_text(encoding="utf-8")

        self.assertIn("/static/playback_state.js", index)
        self.assertLess(index.index("/static/playback_state.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpPlaybackState", playback_state)
        self.assertIn("playbackSettings(state)", playback_state)
        self.assertIn("cleanupPlaybackPositions(storage, state, items)", playback_state)
        self.assertIn("isImageItem(item)", playback_state)
        self.assertIn("fmtClockTime(seconds)", playback_state)
        self.assertIn("window.UcpPlaybackState || null", app_js)
        self.assertIn("cleanupPlaybackPositions(localStorage, frontendState, items)", app_js)
if __name__ == "__main__":
    unittest.main()
