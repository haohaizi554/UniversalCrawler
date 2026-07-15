"""Unified frontend contracts owned by the static domain."""

from __future__ import annotations

from tests.unified_frontend_contract_support import (
    UnifiedFrontendContractTestCase as _UnifiedFrontendContractTestCase,
    Path,
    _css_bundle,
    _html_bundle,
)


class UnifiedFrontendStaticContractTests(_UnifiedFrontendContractTestCase):
    def test_web_update_dialog_exposes_latest_log_in_a_browser_tab(self):
        content = _html_bundle()

        self.assertIn('id="updateViewLogBtn"', content)
        self.assertIn('onclick="openUpdateLog()"', content)
        self.assertIn('function openUpdateLog()', content)
        self.assertIn('window.open("/api/debug/latest-log", "_blank", "noopener")', content)

    def test_hidden_attribute_cannot_be_overridden_by_component_display_rules(self):
        css = _css_bundle()

        self.assertIn("[hidden] {\n  display: none !important;\n}", css)

    def test_top_search_input_keeps_theme_tokens_for_disabled_and_autofill_states(self):
        content = _html_bundle()
        css = _css_bundle()

        self.assertIn('id="searchInput" class="search-input" autocomplete="off"', content)
        self.assertIn(".search-input:disabled", css)
        self.assertIn(".search-input:-webkit-autofill", css)
        self.assertIn("-webkit-box-shadow: 0 0 0 1000px var(--input) inset;", css)
        self.assertIn("-webkit-text-fill-color: var(--text);", css)

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
        self.assertIn("#page-failed th:nth-child(4), #page-failed td:nth-child(4) { width: 102px; }", css)
        self.assertIn("#page-failed th:nth-child(5), #page-failed td:nth-child(5) { width: 84px; }", css)
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
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")
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
        self.assertIn("function syncLogEmptyState", log_center)
        self.assertIn("syncLogEmptyState(items.length === 0);", log_center)
        self.assertIn("function syncLogTabLabels", log_center)
        self.assertIn("syncLogTabLabels();", log_center)
        self.assertIn("function selectValueOrFallback", log_center)
        self.assertIn('["logLevelFilter", "level", "all"]', log_center)
        self.assertIn('["logTimeFilter", "time", "30m"]', log_center)
        self.assertIn("window.UcpCustomSelect.syncForSelect(node)", log_center)
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
            "#page-logs th:nth-child(1), #page-logs td:nth-child(1) { width: max(144px, 17ch); }",
            "#page-logs th:nth-child(2), #page-logs td:nth-child(2) { width: 82px; }",
            "#page-logs th:nth-child(3), #page-logs td:nth-child(3) { width: 144px; }",
            "#page-logs th:nth-child(4), #page-logs td:nth-child(4) { width: 88px; }",
        ):
            self.assertIn(expected_width, css)
        self.assertIn("#page-logs .log-filter-label", css)
        self.assertIn("#page-logs .log-filter-field input", css)
        self.assertIn("flex: 0 0 40px", css)
        self.assertIn("#page-logs th, #page-logs td {\n  height: 32px;", css)
        self.assertIn("padding: 4px;", css)
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
        self.assertIn("setPage,", log_center)
        self.assertIn("setPageSize,", log_center)
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
        self.assertIn("copyTraceId,", log_center)
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
            "copyDetail,",
            "copyJson,",
            "exportDetail,",
            "dispose,",
        ):
            self.assertIn(detail_action, log_center)
        self.assertIn('new Worker("/static/log_detail_worker.js?v=20260714-log-detail-parity")', log_center)
        log_i18n = (static_dir / "log_i18n.js").read_text(encoding="utf-8")
        for translation_marker in (
            "function translateRuntimeLogText",
            "function localizeEnglishDynamicLogText",
            "function localizeLogEventCode",
        ):
            self.assertIn(translation_marker, log_i18n)
        self.assertIn("function logI18nService()", log_center)
        self.assertIn("logI18nService()?.localizeLogEventCode", log_center)
        self.assertIn('add("status_code", item.status_code || "", localizeLogEventCode(item.status_code || ""));', log_i18n)
        self.assertIn('add("event_code", item.event_code || "", localizeLogEventCode(item.event_code || ""));', log_i18n)
        self.assertIn('if (sections.has("settings_snapshot")) updatePlaceholder();', content)
        self.assertIn("trimFrontendLogItems();\n  updatePlaceholder();", content)
        self.assertIn("log-inspector-header", log_center)
        self.assertIn("log-json-card", log_center)
        self.assertIn("log-detail-readable", log_center)
        self.assertIn('data-json="${escAttr(result.detailJson || "{}")}"', log_center)
        self.assertIn("function emptyLogDetailSummaryHtml", log_center)
        self.assertIn("${emptyLogDetailSummaryHtml()}", log_center)
        self.assertIn('<pre class="log-snippet">{}</pre>', log_center)
        self.assertIn("copyCurrentLogJson()", log_center)
        self.assertIn("copyCurrentLogDetail()", log_center)
        self.assertIn("exportCurrentLogDetail()", log_center)
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
        self.assertIn('requireDependency("frontendAction")("register_file_associations", { include_video: includeVideo, include_image: includeImage })', content)
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
        self.assertIn("\\u81ea\\u52a8\\u6253\\u5f00\\uff0c\\u5f00\\u542f\\u65f6\\u4f7f\\u7528", content)
        self.assertIn("\\u70b9\\u51fb\\u64ad\\u653e\\u952e\\u65f6\\u4f7f\\u7528", content)
        self.assertIn('requireDependency("frontendAction")("open_file"', content)
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
        self.assertIn('patchSetting("外观设置", "follow_system", false)', content)
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
        self.assertNotIn("SETTINGS_GROUP_ICONS", content)
        self.assertIn("contract.group_icons", content)
        self.assertIn("function settingGroupIconFile", content)
        self.assertIn("settingGroupIconFile(group)", content)
        self.assertIn("settingGroupIconFile(state.currentGroup)", content)
        self.assertIn("settings-detail-icon", content)
        self.assertNotIn("SETTINGS_GROUP_HINTS_FALLBACK", content)
        self.assertNotIn("SETTINGS_GROUP_DESCRIPTIONS_FALLBACK", content)
        self.assertIn("contract.hints[state.currentGroup]", content)
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
        setting_action = css.rsplit("\n.setting-action {", 1)[1].split("}", 1)[0]
        self.assertIn("min-width: max-content", setting_action)
        self.assertIn("width: auto", setting_action)
        self.assertNotIn("width: 94px", setting_action)
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
        self.assertIn("renderCompletedDetail();\n    if (typeof dependencies.renderStatus", content)
        self.assertIn("renderStatus: () => {\n      renderStatus();\n      playbackControllerService().updateControls();", content)
        self.assertIn("function switchPreview", content)
        self.assertIn("function onSeekInput", content)
        self.assertIn("function onSeekCommit", content)
        self.assertIn("const canStartPreview = !!(state.currentPlayingId || getSelectedCompletedId());", content)
        self.assertIn("!hasVideo && !canStartPreview", content)
        self.assertIn("player.onloadedmetadata", content)
        self.assertIn("player.ondurationchange", content)
        self.assertIn("player.onplay", content)
        self.assertIn("updateFullscreenButtonState", content)
        self.assertNotIn("button.disabled = !hasPreviewContent()", content)
        self.assertNotIn("if (!hasPreviewContent()) return;", content)
        self.assertIn("adjacentCompletedId(state.currentPlayingId, 1, false)", content)
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
        self.assertIn("...(snapshot.download_options || {})", content)
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
        self.assertIn("hasFocusedDescendant(grid)", content)
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

    def test_completed_and_failed_cards_use_gui_semantic_radii(self):
        css = _css_bundle()

        self.assertIn("--completed-card-radius: 8px;", css)
        self.assertIn("--failed-card-radius: 10px;", css)
        completed = css.split("#page-completed .completed-table-card", 1)[1].split("}", 1)[0]
        completed_info = css.split("#page-completed .completed-info-card", 1)[1].split("}", 1)[0]
        failed_table = css.split("#page-failed .failed-table-card", 1)[1].split("}", 1)[0]
        failed_details = css.split(
            "#page-failed .failed-detail-card,\n#page-failed .failed-solutions-card",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("border-radius: var(--completed-card-radius);", completed)
        self.assertIn("border-radius: var(--completed-card-radius);", completed_info)
        self.assertIn("border-radius: var(--failed-card-radius);", failed_table)
        self.assertIn("border-radius: var(--failed-card-radius);", failed_details)

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
        css = _css_bundle()
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
        css = _css_bundle()

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
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")

        self.assertIn("/static/log_display.js", index)
        self.assertLess(index.index("/static/log_display.js"), index.index("/static/app.js"))
        self.assertIn("root.UcpLogDisplay", log_display)
        self.assertIn("logMatchesFilters(item, filters", log_display)
        self.assertIn("visibleLogItems(items, rowBudget", log_display)
        self.assertIn("window.UcpLogDisplay.queryLogItems", log_center)
        self.assertIn("function syncLogStaticLanguage()", log_center)
        self.assertIn("syncLogStaticLanguage();", log_center)
        self.assertNotIn("window.UcpLogDisplay", app_js)
        self.assertNotIn("function syncLogStaticLanguage()", app_js)
        self.assertNotIn("const category = logCategory(item);", app_js)

    def test_web_settings_render_logic_is_split_into_component(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        settings_render = (static_dir / "settings_render.js").read_text(encoding="utf-8")
        settings_controller = (static_dir / "settings_controller.js").read_text(encoding="utf-8")

        self.assertIn("/static/settings_render.js", index)
        self.assertLess(index.index("/static/settings_render.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpSettingsRender", settings_render)
        self.assertIn("settingsControls(group, value)", settings_render)
        self.assertIn("platformSettingRow(row)", settings_render)
        self.assertIn("service.configure({ esc, escAttr, t, optionLabel, countOptionLabel, platformIconUrl })", settings_controller)
        self.assertIn("window.UcpSettingsRender || null", settings_controller)
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
        playback_controller = (static_dir / "playback_controller.js").read_text(encoding="utf-8")

        self.assertIn("/static/playback_state.js", index)
        self.assertLess(index.index("/static/playback_state.js"), index.index("/static/app.js"))
        self.assertIn("window.UcpPlaybackState", playback_state)
        self.assertIn("playbackSettings(state)", playback_state)
        self.assertIn("cleanupPlaybackPositions(storage, state, items)", playback_state)
        self.assertIn("isImageItem(item)", playback_state)
        self.assertIn("fmtClockTime(seconds)", playback_state)
        self.assertNotIn("window.UcpPlaybackState || null", app_js)
        self.assertIn("playbackStateService()", playback_controller)
        self.assertIn("cleanupPlaybackPositions(localStorage, currentState(), items)", playback_controller)
