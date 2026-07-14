"""Unified frontend contracts owned by the shell domain."""

from __future__ import annotations

from tests.unified_frontend_contract_support import (
    UnifiedFrontendContractTestCase as _UnifiedFrontendContractTestCase,
    ActionTable,
    AppShell,
    ComboPopupEventFilter,
    EventTimelineWidget,
    FrontendStateService,
    MainWindow,
    Mock,
    NoFocusItemDelegate,
    PaginationFooter,
    QApplication,
    QComboBox,
    QEvent,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPoint,
    QPushButton,
    QScrollArea,
    QSize,
    QTableView,
    QTableWidget,
    QTest,
    QToolButton,
    QWidget,
    Qt,
    SegmentedControl,
    SettingsComboBox,
    SettingsPathPicker,
    SmartWrapLabel,
    SpeedTrendWidget,
    TEXT,
    UiSwitch,
    _badge_size,
    _css_bundle,
    apply_application_theme,
    combo_edit_field_width,
    combo_widest_item_text_width,
    connect_table_actions,
    deepcopy,
    generate_stylesheet,
    patch,
    polish_combo_popup,
    theme_colors,
)


class UnifiedFrontendShellContractTests(_UnifiedFrontendContractTestCase):
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

    def test_rapid_failed_page_navigation_does_not_spawn_transient_windows(self):
        shell = self._make_shell()
        shell.show()
        self.app.processEvents()
        baseline_top_levels = {id(widget) for widget in self.app.topLevelWidgets()}
        navigation = ("failed", "queue", "failed", "logs", "failed", "completed", "failed")

        for _ in range(20):
            for page_id in navigation:
                QTest.mouseClick(shell.sidebar._items[page_id], Qt.MouseButton.LeftButton)
            self.app.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        unexpected_visible_windows = [
            widget.objectName() or type(widget).__name__
            for widget in self.app.topLevelWidgets()
            if id(widget) not in baseline_top_levels and widget.isVisible()
        ]
        self.assertEqual(unexpected_visible_windows, [])
        self.assertEqual(shell.current_page_id, "failed")
        self.assertIs(shell.stack.currentWidget(), shell.pages["failed"])
        self.assertTrue(shell.status_island.isVisible())

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

    def test_gui_toolbox_renders_tool_and_recent_delta_sections_while_visible(self):
        shell = self._make_shell()
        snapshot = FrontendStateService.mock_snapshot()
        shell.render(snapshot)
        shell.show_page("toolbox")
        toolbox = shell.pages["toolbox"]

        snapshot["toolbox_items"] = [
            {
                "id": "delta-tool",
                "title": "增量工具",
                "summary": "增量工具说明",
                "input_example": "输入",
                "output_example": "输出",
                "icon_file": "nav_toolbox.png",
            }
        ]
        shell.render(snapshot, changed_sections={"toolbox_items"})
        self.app.processEvents()

        self.assertEqual(list(toolbox._tool_buttons), ["delta-tool"])
        self.assertIn("增量工具", toolbox.detail_text.toPlainText())

        snapshot["toolbox_recent_items"] = [
            {"id": "delta-tool", "title": "增量工具", "last_used": "刚刚"}
        ]
        shell.render(snapshot, changed_sections={"toolbox_recent_items"})
        self.app.processEvents()

        self.assertIn("增量工具", toolbox.recent.toPlainText())
        self.assertIn("刚刚", toolbox.recent.toPlainText())

    def test_gui_toolbox_hot_language_change_rebuilds_dynamic_content(self):
        shell = self._make_shell()
        shell.show_page("toolbox")
        toolbox = shell.pages["toolbox"]

        shell.apply_language("en-US")
        self.app.processEvents()

        self.assertEqual(toolbox.open_button.text(), "Open tool")
        self.assertIn("Tool: Link parser", toolbox.detail_text.toPlainText())
        self.assertIn("Description:", toolbox.detail_text.toPlainText())
        self.assertIn("Today", toolbox.recent.toPlainText())
        self.assertNotIn("工具:", toolbox.detail_text.toPlainText())

        shell.apply_language("zh-TW")
        self.app.processEvents()

        self.assertEqual(toolbox.open_button.text(), "開啟工具")
        self.assertIn("工具: 連結解析", toolbox.detail_text.toPlainText())
        self.assertIn("說明:", toolbox.detail_text.toPlainText())
        self.assertNotIn("Link parser", toolbox.detail_text.toPlainText())

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
        from shared.settings_metadata import GROUP_HINTS, GROUP_ICONS

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
        # addCleanup 按后进先出执行：先走正式 closeEvent 停止 worker，再延迟销毁并处理事件。
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
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
