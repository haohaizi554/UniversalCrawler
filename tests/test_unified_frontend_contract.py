import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QSpinBox, QTableView, QTableWidget

from app.services.frontend_state_service import FrontendStateService
from app.ui.layout.app_shell import AppShell
from app.ui.pages.active_downloads_page import SmartWrapLabel, SpeedTrendWidget
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
            "completed": ["标题", "完成时间", "时长", "分辨率", "大小", "格式", "操作"],
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

        for card in (table_card, detail_card, events_card, queue_card):
            self.assertIsNotNone(card)
        self.assertIs(active.table.parent(), table_card)
        self.assertGreater(table_card.layout().contentsMargins().left(), 0)
        self.assertEqual(active.detail_layout.contentsMargins().left(), 0)

        wrap_labels = active.detail_card.findChildren(SmartWrapLabel)
        self.assertGreaterEqual(len(wrap_labels), 3)
        wrapped = [label for label in wrap_labels if "/" in label.raw_text() or "\\" in label.raw_text()]
        self.assertTrue(wrapped)
        self.assertTrue(any(SmartWrapLabel.BREAK in label.text() for label in wrapped))
        self.assertTrue(wrapped[0].textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)

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

        self.assertEqual([active.thread_combo.itemData(i) for i in range(active.thread_combo.count())], [2, 3, 5])
        self.assertTrue(active.auto_retry.isChecked())

        active.auto_retry.resize(QSize(190, 36))
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(18, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertTrue(active.auto_retry.isChecked())
        QTest.mouseClick(active.auto_retry, Qt.MouseButton.LeftButton, pos=QPoint(active.auto_retry.width() - 12, active.auto_retry.height() // 2))
        self.assertFalse(active.auto_retry.isChecked())
        active.thread_combo.setCurrentIndex(2)
        active.retry_combo.setCurrentIndex(3)

        self.assertTrue(emitted)
        self.assertEqual(emitted[-1], {"auto_retry": False, "max_retries": 5, "max_concurrent": 5})

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
            "<th>标题</th><th>完成时间</th><th>时长</th><th>分辨率</th><th>大小</th><th>格式</th><th>操作</th>",
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

    def test_web_active_controls_and_detail_values_are_wrap_ready(self):
        content = _html_bundle()
        css = _css_bundle()
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]

        self.assertIn('class="active-toggle"', active_page)
        self.assertIn('id="activeAutoRetry"', active_page)
        self.assertIn("function smartWrapText", content)
        self.assertIn("kv-value smart-wrap", content)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn('activeTrendHtml(item.speed_trend || [], item.speed || "0 B/s")', content)
        self.assertIn('text-anchor="end"', content)
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
