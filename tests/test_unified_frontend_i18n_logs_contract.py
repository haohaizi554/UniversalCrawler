"""Unified frontend contracts owned by the i18n logs domain."""

from __future__ import annotations

from tests.unified_frontend_contract_support import (
    UnifiedFrontendContractTestCase as _UnifiedFrontendContractTestCase,
    FrontendStateService,
    Path,
    QApplication,
    QLabel,
    QModelIndex,
    QTest,
    Qt,
    _html_bundle,
    combo_edit_field_width,
    combo_widest_item_text_width,
    deepcopy,
    patch,
    tempfile,
)


class UnifiedFrontendI18nLogsContractTests(_UnifiedFrontendContractTestCase):
    def test_production_log_literals_have_bidirectional_runtime_translation(self):
        import ast
        import re

        from shared.log_i18n import localize_log_text

        project_root = Path(__file__).resolve().parents[1]
        log_calls = {
            "append_log",
            "log",
            "log_api",
            "log_command",
            "log_web_event",
            "record_log",
        }

        def literal_text(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.JoinedStr):
                return "".join(
                    value.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                    else "{}"
                    for value in node.values
                )
            return None

        records: list[tuple[str, int, str]] = []
        for root_name in ("app", "shared", "entry"):
            root = project_root / root_name
            if not root.exists():
                continue
            for path in root.rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    function_name = (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else node.func.id
                        if isinstance(node.func, ast.Name)
                        else ""
                    )
                    if function_name not in log_calls:
                        continue
                    candidates = []
                    if function_name == "log_web_event" and len(node.args) >= 3:
                        candidates = [node.args[2]]
                    elif function_name in {"append_log", "record_log"} and node.args:
                        candidates = [node.args[0]]
                    else:
                        candidates = [
                            keyword.value
                            for keyword in node.keywords
                            if keyword.arg in {"description", "message"}
                        ]
                        if not candidates and node.args:
                            candidates = [node.args[-1]]
                    for candidate in candidates:
                        raw = literal_text(candidate)
                        if raw and raw.strip():
                            records.append((str(path.relative_to(project_root)), node.lineno, raw.strip()))

        cjk = re.compile(r"[\u3400-\u9fff]")
        english_phrase = re.compile(r"[A-Za-z]{3,}(?:[\s_-]+[A-Za-z]{2,})+")
        failures: list[str] = []
        for path, line, raw in dict.fromkeys(records):
            sample = re.sub(r"\{[^{}]*\}", "2", raw).replace("%s", "2").replace("%d", "2")
            if sample == "已切换到2主题":
                sample = "已切换到浅色主题"
            english = localize_log_text(sample, "en-US")
            chinese = localize_log_text(sample, "zh-CN")
            if cjk.search(sample) and cjk.search(english):
                failures.append(f"{path}:{line}: English residue: {english!r}")
            if not cjk.search(sample) and english_phrase.search(sample) and chinese == sample:
                failures.append(f"{path}:{line}: Chinese translation missing: {sample!r}")

        self.assertFalse(failures, "\n".join(failures))

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
        self.assertEqual(logs._tab_buttons["error"].text(), "\u9519\u8bef\u65e5\u5fd7 0")
        self.assertNotIn("All logs", tab_text)
        self.assertNotIn("Download logs", tab_text)
        self.assertNotIn("System logs", tab_text)

    def test_log_translation_pipeline_continues_after_structured_source_localization(self):
        from shared.log_i18n import localize_log_text

        self.assertEqual(
            localize_log_text("MainWindow · fetch video detail", "zh-CN"),
            "主窗口 · 获取视频详情",
        )
        self.assertEqual(
            localize_log_text("BiliAPI · fetch video detail", "zh-TW"),
            "Bilibili 介面 · 取得影片詳情",
        )
        self.assertEqual(
            localize_log_text("WebController · Web 端用户请求停止爬虫任务", "en-US"),
            "WebController · Web user requested to stop the crawl task",
        )
        self.assertEqual(
            localize_log_text("WebController · Web 端Crawl task finished", "zh-CN"),
            "Web 控制器 · Web 端爬虫任务结束",
        )

    def test_gui_log_center_localizes_dynamic_log_message_and_event_code(self):
        from shared.log_i18n import localize_log_payload, localize_log_text

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
        production_messages = {
            "Web 端用户请求停止爬虫任务": "Web user requested to stop the crawl task",
            "Web 端开始扫描本地媒体目录（异步）": "Web started scanning local media folder (async)",
            "Web 端下载任务完成": "Web download task completed",
            "Web 端下载任务失败": "Web download task failed",
            "Web 端保存目录已变更": "Web save directory changed",
            "Web 端爬虫任务结束": "Web crawl task finished",
            "✅ 任务已停止": "✅ Task stopped",
            "Bilibili 并发解析播放流并批量提交下载项": (
                "Bilibili is resolving streams concurrently and submitting download items in batches"
            ),
            "Bilibili 并发取流线程失败": "Bilibili concurrent stream worker failed",
            "HTTP 断点续传请求已建立": "HTTP resume request established",
            "目录切换后的初始扫描完成": "Initial scan after changing directory completed",
            "收到超长 WebSocket 消息，连接已关闭": (
                "Oversized WebSocket message received; connection closed"
            ),
            "打开快手搜索页": "Opening the Kuaishou search page",
            "已跳过更新版本: 3.6.17": "Skipped update version: 3.6.17",
            "更新安装包已下载并通过校验: update.exe": "Update package downloaded and verified: update.exe",
            "更新安装程序启动失败: denied": "Failed to start the update installer: denied",
            "已调度 select_tasks 测试事件": "select_tasks test event dispatched",
            "收到非法 JSON 消息": "Invalid JSON message received",
            "Bilibili 登录状态校验失败": "Bilibili login status check failed",
            "等待 Bilibili 扫码登录超时": "Timed out waiting for Bilibili QR-code login",
            "等待抖音扫码登录超时 (120秒)": "Timed out waiting for Douyin QR-code login (120 seconds)",
            "用户在登录过程中终止任务": "User stopped the task during login",
            "HTTP 下载失败，准备重试 (1/3)": "HTTP download failed; preparing to retry (1/3)",
            "HTTP 下载内容不完整，准备重试 (2/3)": "HTTP download incomplete; preparing to retry (2/3)",
            "HTTP 下载异常，准备重试 (3/3)": "HTTP download error; preparing to retry (3/3)",
            "分块下载失败，准备重试 (1/3)": "Chunked download failed; preparing to retry (1/3)",
            "B站 video 流断点续传：从 1024 字节继续下载": (
                "B-site video stream resume: continuing from 1024 bytes"
            ),
            "打开快手目标页": "Opening the Kuaishou target page",
            "页面访问": "Page navigation",
        }
        for source, expected in production_messages.items():
            with self.subTest(source=source):
                self.assertEqual(localize_log_text(source, "en-US"), expected)
        english_production_messages = {
            "Download worker did not stop before file deletion timeout": (
                "文件删除等待超时前下载线程未停止"
            ),
            "Started bounded download recovery maintenance": "已启动有界下载恢复维护",
            "Processed stale download temp artifacts at application startup": "应用启动时已处理过期下载临时文件",
            "Completed bounded download recovery maintenance": "已完成有界下载恢复维护",
            "Recovery directory could not be enumerated; the attempt was acknowledged": (
                "无法枚举恢复目录；本次尝试已确认"
            ),
            "A legacy directory scan was bounded or degraded": "旧版目录扫描已受限或降级",
            "Stopped legacy temp cleanup at the production scan budget": (
                "旧版临时文件清理已在生产扫描预算处停止"
            ),
            "File association registration is Windows-only": "文件关联注册仅支持 Windows",
            "Failed to set defaults for .mp4": "为以下项目设置默认值失败：.mp4",
            "Cannot resolve current user SID: access denied": "无法解析当前用户 SID：access denied",
            "Shell visibility probe: after_theme_apply": "界面可见性探测：after_theme_apply",
            "Shell chrome was hidden unexpectedly; restoring shell chrome": "界面外壳意外隐藏；正在恢复",
            "Exited stale media fullscreen while restoring shell chrome": (
                "恢复界面外壳时已退出残留的媒体全屏状态"
            ),
        }
        for source, expected in english_production_messages.items():
            with self.subTest(source=source):
                self.assertEqual(localize_log_text(source, "zh-CN"), expected)
        self.assertEqual(
            localize_log_text("select_tasks relay lag=12.5ms items=42", "zh-CN"),
            "select_tasks 转发延迟=12.5 毫秒，项目数=42",
        )
        self.assertEqual(
            localize_log_text("select_tasks 轉發延遲=12.5 毫秒，項目數=42", "en-US"),
            "select_tasks relay lag=12.5ms items=42",
        )
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

        from shared import log_i18n

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
