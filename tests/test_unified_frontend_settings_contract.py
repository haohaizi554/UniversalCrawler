"""Unified frontend contracts owned by the settings domain."""

from __future__ import annotations

from tests.unified_frontend_contract_support import (
    UnifiedFrontendContractTestCase as _UnifiedFrontendContractTestCase,
    FrontendStateService,
    QCheckBox,
    QComboBox,
    QDialog,
    QFont,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTest,
    QWidget,
    Qt,
    SettingsPathPicker,
    _css_bundle,
    _html_bundle,
    combo_edit_field_width,
    combo_widest_item_text_width,
    deepcopy,
    localize_active_event_message,
    patch,
    polish_combo_popup,
    prepare_active_item_for_display,
    theme_colors,
)


class UnifiedFrontendSettingsContractTests(_UnifiedFrontendContractTestCase):
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
        self.assertIn('scheduleModalFocus(byId("selectionConfirmBtn")', content)
        self.assertIn('requireDependency("sendWS")("select_tasks", { indices: null })', content)
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
