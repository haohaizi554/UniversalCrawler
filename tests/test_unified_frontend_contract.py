import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox, QTableView, QTableWidget, QWidget

from app.services.frontend_state_service import FrontendStateService
from app.ui.layout.app_shell import AppShell
from app.ui.pages.active_downloads_page import EventTimelineWidget, SmartWrapLabel, SpeedTrendWidget, TEXT
from app.ui.pages.common import ActionTable, connect_table_actions

def _html_bundle() -> str:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    return "\n".join((static_dir / name).read_text(encoding="utf-8") for name in ("index.html", "app.js"))

def _css_bundle() -> str:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    return (static_dir / "app.css").read_text(encoding="utf-8")

class UnifiedFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_shell(self) -> AppShell:
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        self.addCleanup(shell.deleteLater)
        self.addCleanup(self.app.processEvents)
        shell.resize(1280, 720)
        shell.render(FrontendStateService.mock_snapshot())
        self.app.processEvents()
        return shell

    def test_gui_exposes_exact_seven_pages(self):
        shell = self._make_shell()

        self.assertEqual(
            list(shell.pages),
            ["queue", "active", "completed", "failed", "logs", "settings", "toolbox"],
        )

    def test_gui_shell_renders_only_visible_page_until_navigation(self):
        shell = AppShell(is_dark_theme=False, style_provider=self.app)
        self.addCleanup(shell.deleteLater)
        self.addCleanup(self.app.processEvents)
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
        resets.clear()
        active.render(snapshot)
        self.assertEqual(resets, [])

        changed_snapshot = deepcopy(snapshot)
        changed_snapshot["active_downloads"][0]["progress"] = 66
        changed_snapshot["active_downloads"][0]["chunk_progress"]["percent"] = 66
        active.render(changed_snapshot)

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
        fields_host = active.findChild(QWidget, "ActiveDetailFieldsHost")
        fields_body = active.findChild(QWidget, "ActiveDetailFieldsBody")

        for card in (table_card, detail_card, events_card, queue_card):
            self.assertIsNotNone(card)
        self.assertIsNotNone(fields_scroll)
        self.assertIsNotNone(events_scroll)
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

    def test_active_downloads_trend_widget_has_stable_height_and_current_speed(self):
        shell = self._make_shell()
        shell.show_page("active")
        active = shell.pages["active"]
        snapshot = FrontendStateService.mock_snapshot()

        active.render(snapshot)
        self.app.processEvents()
        trend = active.findChild(SpeedTrendWidget)

        self.assertIsNotNone(trend)
        self.assertEqual(trend.minimumHeight(), SpeedTrendWidget.HEIGHT)
        self.assertEqual(trend.maximumHeight(), SpeedTrendWidget.HEIGHT)
        self.assertEqual(trend._speed_label, snapshot["active_downloads"][0]["speed"])

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
        self.app.processEvents()
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

        self.assertEqual([active.thread_combo.itemData(i) for i in range(active.thread_combo.count())], list(range(1, 9)))
        self.assertEqual([active.retry_combo.itemData(i) for i in range(active.retry_combo.count())], list(range(1, 11)))
        self.assertTrue(active.auto_retry.isChecked())

        active.auto_retry.resize(QSize(190, 36))
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(18, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertTrue(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        active.thread_combo.setCurrentIndex(4)
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
        self.assertEqual(active.thread_combo.currentData(), 6)
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
        self.assertEqual(active.thread_combo.currentData(), 6)

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

        self.assertEqual(queue.table.model().rowCount(), 20)
        self.assertEqual(queue.total_label.text(), "共 25 项")
        self.assertEqual(queue.page_label.text(), "1 / 2 页")

        queue.btn_next.click()
        self.assertEqual(queue.page_label.text(), "2 / 2 页")
        self.assertEqual(queue.table.model().rowCount(), 5)

        self.assertTrue(queue.select_id("q-03"))
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
        self.assertGreater(len(settings.findChildren(QSpinBox)), 0)
        self.assertGreater(len(settings.findChildren(QCheckBox)), 0)
        self.assertFalse(any(label.text() == "当前选项" for label in settings.findChildren(QLabel)))

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
        self.app.processEvents()

        table_card = completed.findChild(QFrame, "CompletedTableCard")
        preview_card = completed.findChild(QFrame, "CompletedPreviewCard")
        info_card = completed.findChild(QFrame, "CompletedInfoCard")

        self.assertIsNotNone(table_card)
        self.assertIsNotNone(preview_card)
        self.assertIsNotNone(info_card)
        self.assertIs(completed.table.parent(), table_card)
        self.assertGreater(table_card.layout().contentsMargins().left(), 0)
        self.assertFalse(hasattr(completed, "title_label"))
        self.assertTrue(completed.table.itemDelegate()._suppress_native_selection)

        table_time = completed.table.model().index(0, 1).data()
        full_time = snapshot["completed_items"][0]["completed_at"]
        detail_texts = [label.text() for label in completed.info_body.findChildren(QLabel)]

        self.assertNotIn("2026", table_time)
        self.assertEqual(table_time, snapshot["completed_items"][0]["completed_at_table"])
        self.assertGreaterEqual(completed.table.columnWidth(1), 160)
        self.assertGreaterEqual(completed.table.columnWidth(2), 120)
        metrics = completed.table.fontMetrics()
        self.assertLessEqual(metrics.horizontalAdvance("06-21 15:06") + 24, completed.table.columnWidth(1))
        self.assertLessEqual(metrics.horizontalAdvance("00:01:05") + 24, completed.table.columnWidth(2))
        self.assertIn(full_time, detail_texts)
        smart_info_values = completed.info_body.findChildren(SmartWrapLabel, "CompletedInfoSmartWrapLabel")
        self.assertGreaterEqual(len(smart_info_values), 2)
        self.assertTrue(any("/" in label.raw_text() or "\\" in label.raw_text() for label in smart_info_values))
        self.assertTrue(all(label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse for label in smart_info_values))
        for expected in ("文件名", "保存路径", "完成时间", "时长", "分辨率", "大小", "格式"):
            self.assertIn(expected, detail_texts)
        for removed in ("下载速率", "完成概览", "存储占用"):
            self.assertNotIn(removed, detail_texts)

    def test_completed_page_has_bottom_pagination_like_queue(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("completed")

        completed.render(snapshot)
        self.app.processEvents()

        self.assertEqual(completed.table.model().rowCount(), 20)
        self.assertEqual(completed.total_label.text(), f"共 {len(snapshot['completed_items'])} 项")
        first_page_id = completed.table.model().index(0, 0).data()

        completed.btn_next.click()
        self.app.processEvents()
        second_page_id = completed.table.model().index(0, 0).data()

        self.assertNotEqual(first_page_id, second_page_id)
        self.assertEqual(completed._page, 2)

    def test_failed_page_uses_split_cards_without_retry(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        snapshot = FrontendStateService.mock_snapshot()
        shell.show_page("failed")
        failed.render(snapshot)
        self.app.processEvents()

        self.assertIsNotNone(failed.findChild(QFrame, "FailedTableCard"))
        self.assertIsNotNone(failed.findChild(QFrame, "FailedDetailCard"))
        self.assertIsNotNone(failed.findChild(QFrame, "FailedSolutionsCard"))
        self.assertIsNotNone(failed.findChild(QScrollArea, "FailedLogExcerptScroll"))
        self.assertFalse(hasattr(failed, "title_label"))
        self.assertEqual(tuple(failed.table.itemDelegate()._action_ids), ("copy_diagnostics", "delete"))
        self.assertIn("reason_label", failed.table.table_model._columns)
        self.assertIn("failed_at_table", failed.table.table_model._columns)
        self.assertIn("status_label", failed.table.table_model._columns)
        self.assertIn("reason_label", failed.table.table_model._icon_columns)
        self.assertNotIn("status_label", failed.table.table_model._icon_columns)
        self.assertTrue(failed.table.itemDelegate()._suppress_native_selection)
        log_row = failed.findChild(QFrame, "FailedLogRow")
        self.assertIsNotNone(log_row)
        self.assertLessEqual(log_row.layout().contentsMargins().left(), 2)
        self.assertEqual(log_row.layout().itemAt(0).widget().objectName(), "FailedLogTime")
        self.assertEqual(log_row.layout().itemAt(0).widget().width(), 52)
        self.assertEqual(log_row.layout().itemAt(1).widget().objectName(), "InlineIcon")
        self.assertGreaterEqual(log_row.layout().itemAt(1).widget().width(), 28)
        self.assertFalse(failed.findChildren(QLabel, "FailedLogLevel"))

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
            "<th>标题</th><th>平台</th><th>状态</th><th>进度</th><th>操作</th>",
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

    def test_web_active_actions_keep_delete_only(self):
        content = _html_bundle()
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]

        self.assertNotIn("frontendAction('pause_download'", active_page)
        self.assertIn("frontendAction('delete_item'", content)

    def test_web_failed_page_uses_cards_and_removes_retry(self):
        content = _html_bundle()
        css = _css_bundle()
        failed_page = content.split('id="page-failed"', 1)[1].split('id="page-logs"', 1)[0]
        failed_fn = content.split("function renderFailed()", 1)[1].split("function selectFailed", 1)[0]

        self.assertNotIn('class="page-head"', failed_page)
        self.assertIn("failed-table-card", failed_page)
        self.assertIn("failed-detail-card", failed_page)
        self.assertIn("failed-solutions-card", failed_page)
        self.assertNotIn("retry_failed", failed_fn)
        self.assertIn("copyDiagnostics", failed_fn)
        self.assertIn("iconTextHtml", failed_fn)
        self.assertIn("failed_at_table || item.failed_at", failed_fn)
        self.assertIn("failedStatusHtml", failed_fn)
        self.assertIn("failedLogRowHtml", content)
        self.assertIn("solutionRowHtml", content)
        self.assertIn("#page-failed .failed-table-card", css)
        self.assertIn("#page-failed .failed-solutions-card", css)
        self.assertIn(".failed-log-row", css)
        self.assertIn(".failed-solution-row", css)
        self.assertIn(".failed-status-chip", css)
        failed_log_fn = content.split("function failedLogRowHtml", 1)[1].split("function solutionRowHtml", 1)[0]
        self.assertNotIn("log-level", failed_log_fn)
        self.assertLess(failed_log_fn.index("log-time"), failed_log_fn.index("<img"))
        self.assertIn("grid-template-columns: 52px 28px minmax(0, 1fr)", css)
        self.assertIn("padding: 6px 8px 6px 2px", css)
        self.assertIn("#page-failed tbody td:nth-child(3)", css)
        self.assertIn("width: 28px", css)

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
        self.assertIn('id="completedPageSize"', completed_page)
        self.assertIn("function setCompletedPage", content)
        self.assertIn("function setCompletedPageSize", content)
        self.assertNotIn("<th>分辨率</th>", completed_page)
        self.assertNotIn("<th>大小</th>", completed_page)
        self.assertIn("completed_at_table || item.completed_at", content)
        detail_fn = content.split("function renderCompletedDetail()", 1)[1].split("function basenameFromPath", 1)[0]
        for expected in ("文件名", "保存路径", "完成时间", "时长", "分辨率", "大小", "格式"):
            self.assertIn(expected, detail_fn)
        for removed in ("下载速率", "完成概览", "存储占用"):
            self.assertNotIn(removed, detail_fn)
        self.assertIn('byId("previewPanel")', content)
        self.assertIn("panel.requestFullscreen", content)
        self.assertNotIn('document.body.classList.toggle("is-fullscreen"', content)
        self.assertIn("#page-completed .completed-table-card", css)
        self.assertIn("#page-completed .completed-detail", css)
        self.assertIn(".preview-panel:fullscreen", css)
        self.assertIn("#page-completed th:nth-child(2), #page-completed td:nth-child(2) { width: 168px; }", css)
        self.assertIn("#page-completed th:nth-child(3), #page-completed td:nth-child(3) { width: 124px; }", css)

    def test_web_active_controls_and_detail_values_are_wrap_ready(self):
        content = _html_bundle()
        css = _css_bundle()
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]

        self.assertIn('class="active-toggle"', active_page)
        self.assertIn('id="activeAutoRetry"', active_page)
        self.assertIn('id="activeMaxConcurrent"', active_page)
        self.assertIn('<option value="8">8</option>', active_page)
        self.assertIn('<option value="10">', active_page)
        self.assertIn("function syncActiveDownloadOptions", content)
        self.assertIn("frontendState.download_options", content)
        self.assertIn("function smartWrapText", content)
        self.assertIn("kv-value smart-wrap", content)
        self.assertIn("active-detail-fields", content)
        self.assertIn("active-detail-metrics", content)
        active_detail_fn = content.split("function renderActiveDetail()", 1)[1].split("function activeEventTimelineHtml", 1)[0]
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
        self.assertIn("#activeDetail .active-detail-card", css)
        self.assertIn("#activeDetail .active-detail-fields .kv", css)
        self.assertIn("line-height: 1.18", css)
        self.assertIn("flex: 1 1 0", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn('activeTrendHtml(item.speed_trend || [], item.speed || "0 B/s")', content)
        self.assertIn('text-anchor="end"', content)
        self.assertIn("onloadedmetadata", content)
        self.assertIn('"update_completed_metadata"', content)
        self.assertIn("displayMetadataValue(item.duration, item.metadata_pending)", content)
        self.assertIn("speed-label", content)

    def test_web_rendering_uses_stable_dom_update_guards(self):
        content = _html_bundle()

        self.assertIn("function setHtmlIfChanged", content)
        self.assertIn("function patchTableRows", content)
        self.assertIn('patchTableRows("queueBody"', content)
        self.assertIn('setHtmlIfChanged("completedDetail"', content)
        self.assertIn("hasFocusedDescendant(\"settingsGrid\")", content)
        self.assertIn("webui_detail_width", content)
        self.assertIn("oldRow.classList.remove(\"selected\")", content)

if __name__ == "__main__":
    unittest.main()
