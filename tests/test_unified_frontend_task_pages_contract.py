"""Unified frontend contracts owned by the task pages domain."""

from __future__ import annotations

from tests.unified_frontend_contract_support import (
    UnifiedFrontendContractTestCase as _UnifiedFrontendContractTestCase,
    FailedLogMessageLabel,
    FrontendStateService,
    PaginationFooter,
    QFrame,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTest,
    Qt,
    SmartWrapLabel,
    combo_edit_field_width,
    combo_widest_item_text_width,
    deepcopy,
    prepare_failed_item_for_display,
)


class UnifiedFrontendTaskPagesContractTests(_UnifiedFrontendContractTestCase):
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

    def test_completed_delete_immediately_selects_the_adjacent_row(self):
        shell = self._make_shell()
        completed = shell.pages["completed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        snapshot["completed_items"] = [
            {
                "id": f"completed-{index}",
                "title": f"Completed {index}",
                "completed_at_table": "07-16 08:21",
                "duration": "00:08:06",
                "format": "MP4",
            }
            for index in range(1, 6)
        ]
        deleted_ids = []
        completed.delete_requested.connect(deleted_ids.append)
        completed.render(snapshot)
        self._wait_for_table_rows(completed.table, 5)

        self.assertTrue(completed.table.select_id("completed-3"))
        deleted_row = completed.table.row_for_id("completed-3")
        completed._on_table_action("delete", "completed-3")

        self.assertEqual(deleted_ids, ["completed-3"])
        self.assertEqual(completed.table.row_for_id("completed-3"), -1)
        self.assertEqual(completed.table.selected_id(), "completed-4")
        self.assertEqual(completed.table.row_for_id("completed-4"), deleted_row)

        completed._on_table_action("delete", "completed-4")
        self.assertEqual(completed.table.selected_id(), "completed-5")
        self.assertEqual(completed.table.row_for_id("completed-5"), deleted_row)

        completed._on_table_action("delete", "completed-5")
        self.assertEqual(completed.table.selected_id(), "completed-2")
        self.assertEqual(deleted_ids, ["completed-3", "completed-4", "completed-5"])

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
        clear_all_hits: list[bool] = []
        failed.clear_failed_records_requested.connect(lambda: clear_all_hits.append(True))
        failed.btn_clear_failed_records.click()
        self.app.processEvents()
        self.assertEqual(clear_all_hits, [True])

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

    def test_failed_page_optimistically_removes_rows_before_backend_refresh(self):
        shell = self._make_shell()
        failed = shell.pages["failed"]
        snapshot = deepcopy(FrontendStateService.mock_snapshot())
        template = snapshot["failed_items"][0]
        snapshot["failed_items"] = [
            {**template, "id": f"failed-{index}", "title": f"Failed {index}"}
            for index in range(3)
        ]
        shell.show_page("failed")
        failed.render(snapshot)
        self._wait_for_table_rows(failed.table, 3)

        deleted: list[str] = []
        failed.delete_requested.connect(deleted.append)
        failed._on_table_action("delete", "failed-1")
        self._wait_for_table_rows(failed.table, 2)
        self.assertEqual(deleted, ["failed-1"])
        self.assertNotIn("failed-1", failed._items_by_id)

        cleared: list[bool] = []
        failed.clear_failed_records_requested.connect(lambda: cleared.append(True))
        failed.btn_clear_failed_records.click()
        self._wait_for_table_rows(failed.table, 0)
        self.assertEqual(cleared, [True])
        self.assertEqual(failed.items, [])

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
