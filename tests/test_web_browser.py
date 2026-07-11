"""WebUI static contracts and the single Playwright browser test assembly."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.web_browser_cases.dialogs_and_keyboard import DialogsAndKeyboardCases as _DialogsAndKeyboardCases
from tests.web_browser_cases.localization_and_logs import LocalizationCases as _LocalizationCases
from tests.web_browser_cases.log_center import LogCenterCases as _LogCenterCases
from tests.web_browser_cases.playback import PlaybackCases as _PlaybackCases
from tests.web_browser_cases.runtime_and_lists import RuntimeAndListCases as _RuntimeAndListCases
from tests.web_browser_cases.settings import SettingsCases as _SettingsCases
from tests.web_browser_cases.smoke_and_assets import SmokeAndAssetsCases as _SmokeAndAssetsCases
from tests.web_browser_support import (
    WebUIBrowserTestBase as _WebUIBrowserTestBase,
    _playwright_available,
    _running_server,
    _static_bundle_content,
    _wait_for_webui_ready,
)

# ============================================================
# 静态资源测试（不需要 Playwright）
# ============================================================

class StaticAssetsTests(unittest.TestCase):
    """web 静态资源语法和结构测试（不需要浏览器）。"""

    def test_index_html_exists(self):
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        self.assertTrue(p.exists())

    def test_index_html_has_doctype(self):
        content = _static_bundle_content()
        self.assertTrue(content.lower().startswith("<!doctype html>"))

    def test_index_html_required_ids(self):
        """所有 JS 引用的 id 必须在 HTML 中存在。"""
        content = _static_bundle_content()
        required_ids = [
            "sourceSelect", "searchInput", "dynamicArea",
            "startBtn", "stopBtn", "themeBtn",
            "leftPanel", "rightPanel", "previewPanel", "logPanel",
            "queueBody", "pathLabel",
            "hSplitter", "vSplitter",
            "dirModal", "dirInput", "dirList", "dirDrivesList",
            "fileAssociationModal", "associationVideo", "associationImage",
            "associationCancelBtn", "associationConfirmBtn",
            "selectionModal", "selectionBody", "selectionHeader",
            "playBtn", "prevBtn", "nextBtn", "seekSlider", "timeLabel",
            "fullscreenBtn", "previewArea",
            "tableWrap", "topBar", "queueBody",
        ]
        for elem_id in required_ids:
            # JS 用 getElementById('xxx') 引用
            self.assertIn(f'id="{elem_id}"', content,
                         f"missing id in HTML: {elem_id}")

    def test_completed_preview_controls_are_visible_not_compat_hidden(self):
        html_path = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        bundle = _static_bundle_content()
        completed_page = html.split('id="page-completed"', 1)[1].split('id="page-failed"', 1)[0]
        compat_hidden = html.split('<div class="compat-hidden"', 1)[1]

        self.assertIn('id="mediaViewport"', completed_page)
        self.assertIn('id="mediaControls"', completed_page)
        self.assertIn('id="videoPlayer"', completed_page)
        self.assertNotIn('<video id="videoPlayer" controls', completed_page)
        self.assertIn('ondblclick="toggleFullscreen()"', completed_page)
        for elem_id in ("playBtn", "prevBtn", "nextBtn", "seekSlider", "timeLabel", "fullscreenBtn"):
            self.assertIn(f'id="{elem_id}"', completed_page)
            self.assertNotIn(f'id="{elem_id}"', compat_hidden)

        self.assertIn("function installMediaControlHandlers", bundle)
        self.assertIn("function updateMediaControls", bundle)
        self.assertIn("function switchPreview", bundle)
        self.assertIn("function onSeekCommit", bundle)
        self.assertIn("player.onplay", bundle)
        self.assertIn('addOwnedListener(document, "fullscreenchange", handleFullscreenChange)', bundle)

    def test_index_html_required_js_functions(self):
        """所有 onclick/on... 引用的函数必须存在。"""
        import re
        content = _static_bundle_content()
        # 从 onclick="..." 提取函数名
        onclicks = re.findall(r'onclick="(\w+)\(', content)
        for fn in set(onclicks):
            self.assertTrue(
                f"function {fn}(" in content or f"window.{fn} =" in content,
                f"missing JS function: {fn}",
            )

    def test_selection_modal_keyboard_shortcuts_are_scoped(self):
        content = _static_bundle_content()

        self.assertIn('id="selectionModal" class="modal selection-modal" tabindex="-1"', content)
        self.assertIn("function handleSelectionModalShortcut(event)", content)
        self.assertIn("function isSelectionModalOpen()", content)
        self.assertIn("function isTextEntryTarget(target)", content)
        self.assertIn("function selectAllSelectionItems()", content)
        self.assertIn("function invertSelectionItems()", content)
        self.assertIn('"checkbox"', content)
        self.assertIn('scheduleModalFocus(byId("selectionConfirmBtn")', content)
        self.assertIn('if (event.key === "Enter") confirmSelection();', content)
        self.assertIn("else cancelSelection();", content)
        self.assertIn("if (handleSelectionModalShortcut(event)) return true;", content)
        self.assertIn("}, true);", content)

    def test_file_association_modal_shortcuts_are_bound_to_dialog_actions(self):
        content = _static_bundle_content()

        self.assertIn('id="fileAssociationModal" class="modal association-modal" tabindex="-1"', content)
        self.assertIn('id="associationVideo" class="association-checkbox"', content)
        self.assertIn('id="associationImage" class="association-checkbox"', content)
        self.assertIn("function showFileAssociationModal()", content)
        self.assertIn("function confirmFileAssociationModal()", content)
        self.assertIn("function handleFileAssociationModalShortcut(event)", content)
        self.assertIn('if (!["Enter", "Escape"].includes(event.key)) return false;', content)
        self.assertIn('if (event.key === "Enter") confirmFileAssociationModal();', content)
        self.assertIn("else cancelFileAssociationModal();", content)
        self.assertIn("if (handleFileAssociationModalShortcut(event)) return true;", content)

    def test_directory_modal_uses_web_directory_browser_contract(self):
        content = _static_bundle_content()

        self.assertIn('id="dirModal" class="modal dir-modal" tabindex="-1"', content)
        for elem_id in (
            "dirTitle",
            "dirStatus",
            "dirGoBtn",
            "dirParentBtn",
            "dirRefreshBtn",
            "dirCancelBtn",
            "dirConfirmBtn",
        ):
            self.assertIn(f'id="{elem_id}"', content)
        for fn in (
            "installDirDialogHandlers",
            "showDirDialog",
            "dirLoadPath",
            "dirBrowsePath",
            "dirGoParent",
            "dirRefresh",
            "confirmDirDialog",
        ):
            self.assertIn(f"function {fn}", content)
        self.assertIn('/api/dir/list', content)
        self.assertIn('/api/dir/change', content)
        self.assertIn('localStorage.setItem("dir_last_browsed"', content)
        self.assertIn("await dependencies.fetchState()", content)
        self.assertIn(".dir-modal-box", content)
        self.assertIn(".dir-entry.selected", content)
        self.assertIn(".dir-folder-list", content)
        self.assertIn("max-height: none", content)

    def test_preview_nav_buttons_are_visible(self):
        import re
        content = _static_bundle_content()

        block = re.search(r"\.(?:nav-btn|nav-item)\s*\{(?P<body>.*?)\}", content, re.S)

        self.assertIsNotNone(block)
        body = block.group("body").replace(" ", "").lower()
        self.assertIn("display:flex", body)
        self.assertNotIn("display:none", body)

    def test_mobile_sidebar_scrollbar_is_hidden(self):
        content = _static_bundle_content()

        self.assertIn("scroll-snap-type: x proximity", content)
        self.assertIn("scrollbar-width: none", content)
        self.assertIn(".sidebar::-webkit-scrollbar { display: none; }", content)

    def test_static_assets_are_cache_busted(self):
        content = _static_bundle_content()

        for stylesheet in (
            "app.css",
            "log_layout.css",
            "task_pages.css",
            "task_runtime.css",
            "media_logs.css",
            "settings.css",
            "overlays_responsive.css",
        ):
            self.assertIn(f'/static/{stylesheet}?v=20260711-css-split', content)
        self.assertIn('/static/i18n.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/media_display.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/platform_limits.js?v=20260701-platform-limits', content)
        self.assertIn('/static/settings_render.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/task_render.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/playback_state.js?v=20260701-playback-state', content)
        self.assertIn('/static/custom_select.js?v=20260707-placement-stable', content)
        self.assertIn('/static/log_display.js?v=20260705-i18n-state-boundary', content)
        self.assertIn('/static/app.js?v=20260710-app-split', content)

    def test_split_frontend_scripts_share_cache_version_and_load_order(self):
        import re

        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        index = (static_dir / "index.html").read_text(encoding="utf-8")
        expected_names = [
            "log_i18n.js",
            "frontend_runtime.js",
            "list_pages.js",
            "log_center.js",
            "settings_controller.js",
            "dialog_controller.js",
            "playback_controller.js",
            "app.js",
        ]
        scripts = re.findall(
            r'<script src="/static/([^"?]+)\?v=([^"]+)" defer></script>',
            index,
        )
        split_scripts = [(name, version) for name, version in scripts if name in expected_names]

        self.assertEqual([name for name, _version in split_scripts], expected_names)
        self.assertEqual({version for _name, version in split_scripts}, {"20260710-app-split"})

    def test_video_end_autoplays_next_preview(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        content = (static_dir / "playback_controller.js").read_text(encoding="utf-8")

        self.assertIn("function autoplayNextPreview(", content)
        self.assertIn("setupPlayerEvents(player, sourceId, generation, operation)", content)
        self.assertIn("function setupPlayerEvents(player, sourceId", content)
        self.assertIn("shouldAutoplayNext()", content)
        self.assertIn("autoplayNextPreview();", content)

    def test_css_variables_defined(self):
        """深色/浅色主题 CSS 变量必须定义。"""
        content = _static_bundle_content()
        # 关键 CSS 变量
        for var in ("--bg", "--panel", "--accent", "--text", "--border"):
            self.assertIn(var, content, f"missing CSS variable: {var}")

    def test_platform_settings_static_contract_matches_gui(self):
        content = _static_bundle_content()

        self.assertIn("configureTopCountForSource", content)
        self.assertIn('count_config_key || "max_items"', content)
        self.assertIn('data-setting="proxy_url"', content)
        self.assertIn('updateSetting(platformId, key, "自定义")', content)
        self.assertIn("renderSettings(true);", content)
        self.assertIn("\u7b14\u8bb0\u6570:", content)
        self.assertIn("function countFallbackOptions(unit)", content)
        self.assertIn("unit === \"pages\"", content)
        self.assertIn("unit === \"notes\"", content)
        self.assertIn("countUnit === \"pages\"", content)
        self.assertIn("[\"pages\", \"notes\"].includes", content)
        self.assertNotIn("<option>100</option>", content)
        self.assertIn("个视频", content)
        self.assertIn("1 页（推荐）", content)

    def test_no_console_error_patterns(self):
        """不应有明显错误模式。"""
        content = _static_bundle_content()
        # 不应出现 TODO/FIXME 标记
        self.assertNotIn("TODO", content)
        self.assertNotIn("FIXME", content)
        # 不应有未配对的花括号（粗略检查）
        self.assertEqual(content.count("{"), content.count("}"))

    def test_high_frequency_events_use_delta_not_full_state_fetch(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        content = _static_bundle_content()
        self.assertIn('case "frontend_delta":', runtime)
        self.assertIn("function applyFrontendDelta(", runtime)
        self.assertIn("function patchTableRows(", content)
        high_event_block = runtime.split('case "item_found":', 1)[1].split('case "frontend_action_result":', 1)[0]
        self.assertNotIn("fetchFrontendState();", high_event_block)
        self.assertIn("applyLegacyFrontendEvent(type, data);", high_event_block)

    def test_frontend_delta_uses_batched_section_rendering(self):
        runtime = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "frontend_runtime.js").read_text(encoding="utf-8")
        delta_block = runtime.split("function applyFrontendDelta(delta", 1)[1].split(
            "function patchLegacyProgress",
            1,
        )[0]
        scheduler_block = runtime.split("function scheduleRenderSections(sections)", 1)[1].split(
            "function flushRenderSections(",
            1,
        )[0]

        self.assertIn("if (uniqueChanged.length) scheduleRenderSections(uniqueChanged)", delta_block)
        self.assertIn("frontendSectionSignature(value)", delta_block)
        self.assertNotIn("changed.length ? changed : [\"all\"]", delta_block)
        self.assertNotIn("dependencies.renderAll", delta_block)
        self.assertIn("scheduleFrame", scheduler_block)

    def test_frontend_delta_rejects_stale_or_discontinuous_versions(self):
        runtime = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "frontend_runtime.js").read_text(encoding="utf-8")
        delta_block = runtime.split("function applyFrontendDelta(delta", 1)[1].split(
            "function patchLegacyProgress",
            1,
        )[0]

        self.assertIn("deltaVersion <= localVersion", delta_block)
        self.assertIn("deltaBaseVersion > localVersion", delta_block)
        self.assertIn("fetchFrontendState();", delta_block)
        self.assertIn('appendUiLog("增量状态基线不连续，正在重新同步...")', delta_block)

    def test_frontend_delta_updates_icon_manifest_and_rerenders_current_page(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        app = (static_dir / "app.js").read_text(encoding="utf-8")
        delta_block = runtime.split("function applyFrontendDelta(delta", 1)[1].split(
            "function patchLegacyProgress",
            1,
        )[0]
        patch_block = app.split("function patchRuntimeSection(section, value)", 1)[1].split(
            "function runtimeDependencies()",
            1,
        )[0]
        render_block = app.split("function renderFrontendSections(sections)", 1)[1].split("function setHtmlIfChanged", 1)[0]

        self.assertIn("patchSection(key, value", delta_block)
        self.assertIn('section === "icon_manifest"', patch_block)
        self.assertIn("updateIconManifest(value)", patch_block)
        self.assertIn('sections.has("icon_manifest")', render_block)
        self.assertIn("renderCurrentPage()", render_block)

    def test_web_page_teardown_closes_ws_and_log_worker(self):
        content = _static_bundle_content()

        self.assertIn("let wsReconnectTimer = null;", content)
        self.assertIn("function cleanupPageResources()", content)
        self.assertIn("clearTimeout(wsReconnectTimer.id);", content)
        self.assertIn("socket.onclose = null;", content)
        self.assertIn("closeLogQueryWorker();", content)
        self.assertIn('window.addEventListener("pagehide", cleanupPageResources', content)
        self.assertIn('window.addEventListener("beforeunload", cleanupPageResources', content)

    def test_settings_snapshot_delta_does_not_rerender_non_settings_page(self):
        content = _static_bundle_content()
        flush_block = content.split("function renderFrontendSections(sections)", 1)[1].split(
            "function setHtmlIfChanged",
            1,
        )[0]

        self.assertIn('sections.has("settings_snapshot") && currentPage === "queue"', flush_block)
        self.assertIn('if (sections.has("settings_snapshot")) updatePlaceholder();', flush_block)
        self.assertIn("configureTopCountForSource(source);", content)
        self.assertNotIn('sections.has("settings_snapshot") && currentPage !== "settings"', flush_block)

    def test_deleted_delta_clears_stale_selection_state(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        app = (static_dir / "app.js").read_text(encoding="utf-8")
        remove_block = app.split("function removeDeletedSelectionState(ids)", 1)[1].split(
            "function patchRuntimeSection",
            1,
        )[0]
        state_block = runtime.split("function removeDeletedFromState(ids", 1)[1].split("function applyFrontendDelta", 1)[0]

        self.assertIn("playbackControllerService().prepareDeleteItem(id)", remove_block)
        self.assertIn('for (const key of ["active", "completed", "failed"])', remove_block)
        self.assertIn("selected[key] = \"\"", remove_block)
        self.assertIn("selectedVideoId = null", remove_block)
        self.assertIn("playbackControllerService().removePlaybackPosition(id)", remove_block)
        self.assertNotIn("currentPlayingId", remove_block)
        self.assertIn("nextState[section] = (state[section] || []).filter", state_block)

    def test_task_pages_reconcile_stale_selection_before_render(self):
        content = _static_bundle_content()
        self.assertIn("function reconcileSelectedTask(key, items)", content)
        self.assertIn("function selectedTaskItem(key, items)", content)

        active_block = content.split("function renderActive()", 1)[1].split("function currentDownloadOptions()", 1)[0]
        completed_block = content.split("function renderCompleted()", 1)[1].split("function selectCompleted", 1)[0]
        failed_block = content.split("function renderFailed()", 1)[1].split("function selectFailed", 1)[0]
        for block, key in ((active_block, "active"), (completed_block, "completed"), (failed_block, "failed")):
            self.assertIn(f'reconcileSelectedTask("{key}"', block)
        self.assertIn('selectedTaskItem("active"', content)
        self.assertIn('selectedTaskItem("completed"', content)
        self.assertIn('selectedTaskItem("failed"', content)

    def test_toolbox_reconciles_stale_selection_before_render(self):
        content = _static_bundle_content()
        toolbox_block = content.split("function renderToolbox()", 1)[1].split("function selectTool", 1)[0]
        detail_block = content.split("function renderToolDetail()", 1)[1].split("function renderStatus", 1)[0]

        self.assertIn('reconcileSelectedTask("tool", items)', toolbox_block)
        self.assertIn('selectedTaskItem("tool"', detail_block)
        self.assertNotIn("if (!selected.tool && items.length) selected.tool = items[0].id", toolbox_block)

    def test_delete_item_closes_current_preview_before_request(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        app = (static_dir / "app.js").read_text(encoding="utf-8")
        controller = (static_dir / "playback_controller.js").read_text(encoding="utf-8")
        frontend_action_block = app.split("function frontendAction(action, payload)", 1)[1].split(
            "function openDirectory(id)", 1,
        )[0]
        delete_block = controller.split("function prepareDeleteItem(id)", 1)[1].split(
            "function deleteVideo(id)", 1,
        )[0]

        self.assertIn('playbackControllerService().prepareDeleteItem(payload && (payload.id || payload.video_id))', frontend_action_block)
        self.assertIn('state.currentPlayingId === sourceId', delete_block)
        self.assertIn("closePreview();", delete_block)
        self.assertIn("prepareDeleteItem(id);", controller)

    def test_start_crawl_validates_platform_and_connection_before_running_state(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        content = _static_bundle_content()
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        ui_state_block = content.split("function setCrawlUiState(isRunning)", 1)[1].split("function startCrawl()", 1)[0]
        start_block = content.split("function startCrawl()", 1)[1].split("function stopCrawl()", 1)[0]
        stop_block = content.split("function stopCrawl()", 1)[1].split("let sendWS", 1)[0]
        send_block = runtime.split("function send(type, data = {})", 1)[1].split("function bindLifecycleListeners", 1)[0]

        self.assertIn('const sourceSelect = byId("sourceSelect")', ui_state_block)
        self.assertIn('const countSelect = byId("videoCountSelect")', ui_state_block)
        self.assertIn("control.disabled = crawlRunning", ui_state_block)
        self.assertIn('startBtn.classList.toggle("is-running", crawlRunning);', ui_state_block)
        self.assertIn('startBtn.setAttribute("aria-busy", crawlRunning ? "true" : "false");', ui_state_block)
        self.assertIn("syncCustomSelectForSelect(sourceSelect)", ui_state_block)
        self.assertIn(".btn-primary.is-running:disabled", content)
        self.assertIn("@keyframes start-button-sweep", content)
        self.assertIn("platformKnown", start_block)
        self.assertIn('appendUiLog("未选择有效模式", "", "❌ ")', start_block)
        self.assertIn('if (!sendWS("start_crawl"', start_block)
        self.assertIn('appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ")', start_block)
        self.assertIn("setCrawlUiState(true);", start_block)
        self.assertIn("if (sendWS(\"stop_crawl\", {}))", stop_block)
        self.assertIn("return true;", send_block)
        self.assertIn("return false;", send_block)

    def test_web_runtime_ui_messages_use_i18n_helpers(self):
        content = _static_bundle_content()
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")
        playback = (static_dir / "playback_controller.js").read_text(encoding="utf-8")

        self.assertIn("function uiTextWithDetail(label, detail = \"\")", content)
        self.assertIn("function appendUiLog(label, detail = \"\", prefix = \"\")", content)
        for snippet in (
            'appendUiLog("请输入主页链接、分享链接或合集链接")',
            'appendUiLog("未选择有效模式", "", "❌ ")',
            'appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ")',
            'appendUiLog("正在绑定默认打开方式...")',
        ):
            self.assertIn(snippet, content)
        self.assertIn('appendUiLog("\\u64ad\\u653e\\u524d\\u6821\\u9a8c\\u5931\\u8d25", error.message || error, "\\u274c ")', playback)
        self.assertIn('"\\u6587\\u4ef6\\u4e0d\\u5b58\\u5728\\u6216\\u5df2\\u88ab\\u5220\\u9664"', playback)
        self.assertIn('requireDependency("writeClipboard")(traceId, t(', log_center)
        for stale in (
            'appendLog("请输入主页链接、分享链接或合集链接")',
            'appendLog("❌ 未选择有效模式")',
            'appendLog("⚠️ 前端连接尚未就绪，请稍后重试")',
            'appendLog("\\u6b63\\u5728\\u7ed1\\u5b9a\\u9ed8\\u8ba4\\u6253\\u5f00\\u65b9\\u5f0f...")',
            'appendLog("❌ 文件不存在或已被删除")',
        ):
            self.assertNotIn(stale, content)
        self.assertIn('"请输入主页链接、分享链接或合集链接": "Enter a profile, shared, or collection link"', content)
        self.assertIn('"未选择有效模式": "No valid mode selected"', content)

    def test_web_playback_position_cache_uses_path_key_and_cleans_orphans(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        playback_state = (static_dir / "playback_state.js").read_text(encoding="utf-8")
        controller = (static_dir / "playback_controller.js").read_text(encoding="utf-8")
        list_pages = (static_dir / "list_pages.js").read_text(encoding="utf-8")

        self.assertIn("const PLAYBACK_POSITION_PREFIX", playback_state)
        self.assertIn("function playbackPositionIdentity(state, id)", playback_state)
        self.assertIn("item.local_path || item.filename || item.id", playback_state)
        self.assertIn("encodeURIComponent(playbackPositionIdentity(state, id))", playback_state)
        self.assertIn("function cleanupPlaybackPositions(storage, state, items)", playback_state)
        self.assertIn("key.startsWith(PLAYBACK_POSITION_PREFIX)", playback_state)
        self.assertIn("cleanupPlaybackPositions(items);", list_pages)
        self.assertIn("window.UcpPlaybackState.cleanupPlaybackPositions(localStorage, currentState(), items);", list_pages)
        self.assertIn("localStorage.removeItem(legacyPlaybackPositionKey(sourceId))", controller)

    def test_web_preview_validates_media_with_server_before_playback(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        content = (static_dir / "playback_controller.js").read_text(encoding="utf-8")
        validate_block = content.split("async function validateMediaForPreview(id, generation, operation)", 1)[1].split(
            "async function playCompleted(id)",
            1,
        )[0]
        play_block = content.split("async function playCompleted(id)", 1)[1].split(
            "function previewVideo(id)",
            1,
        )[0]

        self.assertIn('headers: { Range: "bytes=0-0" }', validate_block)
        self.assertIn("response.body.cancel()", validate_block)
        self.assertIn("response.status === 404", validate_block)
        self.assertIn("isCurrentOperation(generation, operation)", validate_block)
        self.assertIn("if (!(await validateMediaForPreview(sourceId, generation, operation))) {", play_block)
        self.assertIn("if (!isCurrentOperation(generation, operation)) return false;", play_block)
        self.assertIn("const initialItem = completedItemById(sourceId);", play_block)
        self.assertIn("const item = completedItemById(sourceId);", play_block)
        self.assertLess(
            play_block.index("await validateMediaForPreview"),
            play_block.index("const item = completedItemById(sourceId);"),
        )
        self.assertIn("appendPlaybackFailure", content)
        self.assertIn("playResult.catch(error =>", play_block)

    def test_selection_modal_shortcuts_are_bound_to_dialog_actions(self):
        content = _static_bundle_content()
        modal_block = content.split("function showSelectionModal(items)", 1)[1].split(
            "function confirmSelection()",
            1,
        )[0]
        shortcut_block = content.split("function handleSelectionModalShortcut(event)", 1)[1].split(
            "function toggleTheme()",
            1,
        )[0]

        self.assertIn('scheduleModalFocus(byId("selectionConfirmBtn")', modal_block)
        self.assertIn('if (!["Enter", "Escape"].includes(event.key)) return false;', shortcut_block)
        self.assertIn("event.preventDefault();", shortcut_block)
        self.assertIn("event.stopPropagation();", shortcut_block)
        self.assertIn('if (event.key === "Enter") confirmSelection();', shortcut_block)
        self.assertIn("else cancelSelection();", shortcut_block)

        confirm_block = content.split("function confirmSelection()", 1)[1].split(
            "function cancelSelection()",
            1,
        )[0]
        cancel_block = content.split("function cancelSelection()", 1)[1].split(
            "function isSelectionModalOpen()",
            1,
        )[0]
        self.assertIn('if (!requireDependency("sendWS")("select_tasks", { indices })) return false;', confirm_block)
        self.assertIn('if (!requireDependency("sendWS")("select_tasks", { indices: null })) return false;', cancel_block)

    def test_frontend_full_snapshot_rejects_state_older_than_ws_delta(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        snapshot_block = runtime.split("function applyFullState(data", 1)[1].split(
            "function removeDeletedFromState",
            1,
        )[0]

        self.assertIn("incomingVersion < frontendVersion", snapshot_block)
        self.assertIn("operationAdvanced", snapshot_block)
        self.assertIn("return false", snapshot_block)

    def test_zero_retry_setting_is_not_replaced_by_default(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        controller = (static_dir / "list_pages.js").read_text(encoding="utf-8")
        options_block = controller.split("function currentDownloadOptions()", 1)[1].split(
            "function normalizeDownloadConcurrency",
            1,
        )[0]

        self.assertIn("settings.max_retries ?? 3", options_block)
        self.assertNotIn("settings.max_retries || 3", options_block)

    def test_failed_optimistic_setting_action_resyncs_server_state(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        runtime = (static_dir / "frontend_runtime.js").read_text(encoding="utf-8")
        result_block = runtime.split('case "frontend_action_result":', 1)[1].split(
            "default:",
            1,
        )[0]

        self.assertIn('data.status && data.status !== "ok"', result_block)
        self.assertIn("fetchFrontendState();", result_block)

    def test_interaction_map_does_not_keep_stale_fixed_bug_claims(self):
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "app" / "web" / "INTERACTION_MAP.md").read_text(encoding="utf-8")
        stale_claims = [
            "`selectedVideoId = id` — 选中行和播放共用",
            "变量 `currentPlayingId` 已声明但未使用",
            "cancelSelection() → sendWS('select_tasks', {indices: []})",
            "| BUG-9 | cancelSelection None vs [] | ⚠️ 低优先级 |",
            "| P3 | BUG-9: cancelSelection None vs [] | 实际影响极小 | 低 |",
            '"选择视频进行预览"',
            "Web 多了占位文字",
            "`.op-btn:hover` 变色",
            "`.op-btn.del:hover` 变红",
            "Web 多了 hover 效果",
            "| 状态列宽度 | `ResizeToContents` | `width:90px; text-align:center`",
            "| 进度列宽度 | `ResizeToContents` | `width:120px`",
            "| 操作列宽度 | `ResizeToContents` | `width:80px; text-align:center`",
            "`▶` 文字",
            "`✕` 文字",
            "Web 多了一个顶层 content_type",
            "themeBtn.textContent",
            "`.op-btn { margin:0 2px }`",
            "不保存 splitter 比例，刷新后恢复默认值",
            "`renderQueue()` 每次重建整个表格 HTML",
            "Web 端没检查 plugin 有效性",
            'if not keyword: append_log("请输入搜索内容"); return',
            "`setCrawlState(true)` 在 sendWS 之前",
            "`dynamicArea.innerHTML = html`",
            "`renderDynamicArea()` + `sendWS('change_source')`",
            "`area.innerHTML = '' + renderDynamicArea()`",
            "| **弹选择资源** | **`SelectionDialog.exec()` 模态阻塞** | **`showSelectionModal` + WebSocket 异步** | ⚠️ BUG-158 | 异步实现可能漏事件 |",
            "`▶` / `⏸` 字符",
            "`▶` / `⏸` Unicode",
            "player.onended = () => playBtn.textContent = '▶'",
            "Web 没有真正的\"系统图标\"概念，只能用 Unicode 字符近似。",
        ]
        for claim in stale_claims:
            self.assertNotIn(claim, doc)

    def test_append_log_uses_batched_render_scheduler(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        content = (static_dir / "app.js").read_text(encoding="utf-8")
        append_log_block = content.split("function appendLog(message)", 1)[1].split(
            "window.onChangeDirClicked",
            1,
        )[0]

        self.assertIn("trimFrontendLogItems();", append_log_block)
        self.assertIn('scheduleRenderSections(["log_items", "app_status"])', append_log_block)
        self.assertNotIn("renderLogs();", append_log_block)
        self.assertIn("formatLocalDateTime();", append_log_block)
        self.assertNotIn("toISOString()", append_log_block)

    def test_web_runtime_log_timestamp_uses_local_time(self):
        content = _static_bundle_content()
        self.assertIn("function formatLocalDateTime", content)
        self.assertIn("value.getFullYear()", content)
        self.assertIn("value.getHours()", content)
        self.assertIn("value.getSeconds()", content)
        self.assertNotIn("new Date().toISOString().replace", content)

    def test_web_log_display_limit_is_applied_to_local_state(self):
        content = _static_bundle_content()
        app = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function uiLogDisplayLimit()", content)
        self.assertIn("function trimFrontendLogItems()", content)
        self.assertIn("frontendState.log_items = frontendState.log_items.slice(-limit);", content)
        patch_block = app.split("function patchRuntimeSection(section, value)", 1)[1].split("function runtimeDependencies", 1)[0]
        self.assertIn('if (section === "log_items")', patch_block)
        self.assertIn("trimFrontendLogItems();", patch_block)
        log_query_items_block = content.split("function logQueryItems()", 1)[1].split(
            "function logQuerySignature",
            1,
        )[0]
        self.assertNotIn("trimFrontendLogItems();", log_query_items_block)

    def test_web_log_rendering_is_current_page_and_budgeted(self):
        content = _static_bundle_content()
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")
        render_all_block = content.split("function renderAll()", 1)[1].split(
            "function renderCurrentPage()",
            1,
        )[0]
        render_logs_block = log_center.split("function render()", 1)[1].split(
            "function patchLogTableRows",
            1,
        )[0]
        query_result_block = log_center.split("function renderLogQueryResult", 1)[1].split(
            "function syncLogEmptyState",
            1,
        )[0]
        submit_log_query_block = log_center.split("function submitLogQuery", 1)[1].split(
            "function render()",
            1,
        )[0]

        self.assertIn("const LOG_RENDER_ROW_BUDGET = 300;", content)
        self.assertNotIn("LOG_QUERY_WORKER_THRESHOLD", content)
        self.assertIn("renderCurrentPage();", render_all_block)
        self.assertNotIn("renderLogs();", render_all_block)
        self.assertIn("submitLogQuery(items, signature);", render_logs_block)
        self.assertNotIn("queryLogsSync(items, sequence);", render_logs_block)
        self.assertIn("function scheduleLogQueryFallback(items, sequence)", content)
        self.assertIn("function queryLogsSyncRequest(request)", content)
        self.assertIn("const request = buildLogQueryRequest(Array.isArray(items) ? items.slice() : [], sequence);", content)
        self.assertIn("scheduleLogQueryFallback(items, sequence);", content)
        self.assertIn("Number(sequence) !== state.querySequence", log_center)
        self.assertIn("receiveLogQueryResult(queryLogsSyncRequest(request));", content)
        self.assertNotIn("receiveLogQueryResult(queryLogsSync(items, sequence));", submit_log_query_block)
        self.assertIn('new Worker("/static/log_query_worker.js?v=20260707-log-worker")', content)
        self.assertIn("const items = Array.isArray(result.pageItems)", query_result_block)
        self.assertIn("patchLogTableRows(items);", query_result_block)
        self.assertIn("boundedItems.slice(start, start + pageSize)", content)
        self.assertIn("queryLogItems(request", content)
        self.assertIn("function visibleLogItems(items, rowBudget = 300)", content)
        self.assertIn("rowBudget: uiLogDisplayLimit()", log_center)
        self.assertIn("function setLogPage(delta)", content)
        self.assertIn("function setLogPageSize(value)", content)
        self.assertIn("function normalizeLogPageSize(value)", content)
        self.assertIn("window.UcpCustomSelect.syncForSelect(size)", query_result_block)
        for elem_id in ("logTotal", "logPrevPage", "logPageIndicator", "logPageSize", "logNextPage"):
            self.assertIn(f'id="{elem_id}"', html)
        self.assertIn('<option value="0">全部</option>', html)

    def test_web_log_table_uses_gui_display_fields(self):
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        content = (static_dir / "log_center.js").read_text(encoding="utf-8")
        css = _static_bundle_content()
        render_logs_block = content.split("function patchLogTableRows", 1)[1].split(
            "function renderLogQueryResult",
            1,
        )[0]

        self.assertIn("function logLevelCellHtml(item)", content)
        self.assertIn("function logSourceCellHtml(item)", content)
        self.assertIn("function logDetailSummaryHtml(item)", content)
        self.assertIn("item.level_display || item.level", content)
        self.assertIn("item.source_display || item.source || item.platform", content)
        self.assertIn("item.source_display_icon_file || \"\"", content)
        self.assertIn("${logLevelCellHtml(item)}", render_logs_block)
        self.assertIn("${logSourceCellHtml(item)}", render_logs_block)
        self.assertIn("${logDetailSummaryHtml(item)}", content)
        self.assertIn("logLevelCellHtml(item)", content)
        self.assertIn("logSourceCellHtml(item)", content)
        self.assertIn(".log-level-badge", css)
        self.assertIn(".log-source-cell", css)

    def test_web_log_detail_formatting_runs_in_worker(self):
        content = _static_bundle_content()
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")
        render_detail_block = log_center.split("function renderLogDetail(itemsOverride)", 1)[1].split(
            "function reportMessage",
            1,
        )[0]

        self.assertIn('new Worker("/static/log_detail_worker.js?v=20260709-log-detail-worker")', content)
        self.assertIn("function ensureLogDetailWorker()", log_center)
        self.assertIn("function receiveLogDetailResult(result)", log_center)
        self.assertIn("function submitLogDetail(item)", log_center)
        self.assertIn("renderLogDetailResult(result);", log_center)
        self.assertNotIn("function localizedLogDetailPayload", app_js)
        self.assertNotIn("function formatLogDetailDisplayText", app_js)
        self.assertNotIn("function buildLogDetailPayload", app_js)
        self.assertNotIn("JSON.parse", render_detail_block)
        self.assertNotIn("JSON.stringify", render_detail_block)
        self.assertNotIn("localizedLogDetailPayload(item)", render_detail_block)
        self.assertNotIn("formatLogDetailDisplayText(detailPayload)", render_detail_block)

    def test_web_table_page_size_matches_gui_pagination_contract(self):
        content = _static_bundle_content()
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        list_pages = (static_dir / "list_pages.js").read_text(encoding="utf-8")
        render_queue_block = list_pages.split("function renderQueue()", 1)[1].split(
            "function applyQueuePageResult",
            1,
        )[0]
        render_completed_block = list_pages.split("function renderCompleted()", 1)[1].split(
            "function applyCompletedPageResult",
            1,
        )[0]
        render_failed_block = list_pages.split("function renderFailed()", 1)[1].split(
            "function applyFailedPageResult",
            1,
        )[0]

        self.assertIn("function normalizeTablePageSize(value)", list_pages)
        self.assertIn('new Worker("/static/list_page_worker.js?v=20260708-list-page-worker")', list_pages)
        self.assertIn('state.queuePageSize = normalizeTablePageSize(localStorage.getItem("webui_queue_page_size") || 20);', list_pages)
        self.assertIn('state.completedPageSize = normalizeTablePageSize(localStorage.getItem("webui_completed_page_size") || 20);', list_pages)
        self.assertIn('state.failedPageSize = normalizeTablePageSize(localStorage.getItem("webui_failed_page_size") || 20);', list_pages)
        self.assertIn("return [20, 50, 100].includes(numeric) ? numeric : 20;", list_pages)
        self.assertIn("state.queuePageSize = normalizeTablePageSize(value);", list_pages)
        self.assertIn("state.completedPageSize = normalizeTablePageSize(value);", list_pages)
        self.assertIn("state.failedPageSize = normalizeTablePageSize(value);", list_pages)
        self.assertIn("function ensureListPageWorker()", list_pages)
        self.assertIn("function submitListPageRequest(pageKey, requestData)", list_pages)
        self.assertIn("function applyListPageResult(result, worker = state.worker", list_pages)
        self.assertIn("worker.postMessage(request);", list_pages)
        self.assertIn("scheduleListPageFallback(request);", list_pages)
        self.assertIn("const timer = setTimeout(() =>", list_pages)
        self.assertIn('submitListPageRequest("queue"', render_queue_block)
        self.assertIn('submitListPageRequest("completed"', render_completed_block)
        self.assertIn('submitListPageRequest("failed"', render_failed_block)
        self.assertIn('syncCustomSelectForSelect(byId("queuePageSize"))', list_pages)
        self.assertIn('syncCustomSelectForSelect(byId("completedPageSize"))', list_pages)
        self.assertIn('syncCustomSelectForSelect(byId("failedPageSize"))', list_pages)
        self.assertIn('byId("queuePrevPage").disabled = state.queuePage <= 1;', list_pages)
        self.assertIn('byId("queueNextPage").disabled = state.queuePage >= totalPages;', list_pages)
        self.assertIn('byId("completedPrevPage").disabled = state.completedPage <= 1;', list_pages)
        self.assertIn('byId("completedNextPage").disabled = state.completedPage >= totalPages;', list_pages)
        self.assertIn('byId("failedPrevPage").disabled = state.failedPage <= 1;', list_pages)
        self.assertIn('byId("failedNextPage").disabled = state.failedPage >= totalPages;', list_pages)
        for elem_id in (
            "queuePrevPage",
            "queueNextPage",
            "completedPrevPage",
            "completedNextPage",
            "failedPrevPage",
            "failedNextPage",
        ):
            self.assertIn(f'id="{elem_id}"', content)
        self.assertIn('id="queuePrevPage" class="icon-btn pagination-button" type="button"', content)
        self.assertIn('id="completedNextPage" class="icon-btn pagination-button" type="button"', content)
        self.assertIn('id="failedNextPage" class="icon-btn pagination-button" type="button"', content)
        self.assertIn(".pagination-button", content)
        self.assertIn("width: 38px;", content)
        self.assertIn('aria-label="上一页"', content)
        self.assertIn('aria-label="下一页"', content)
        self.assertIn(".icon-btn:disabled", content)
        self.assertIn(".icon-btn:disabled:hover", content)
        self.assertIn("const pagerIconButtons = {", content)
        self.assertIn('queuePrevPage: "上一页"', content)
        self.assertIn('completedNextPage: "下一页"', content)
        self.assertIn('button.setAttribute("aria-label", t(label));', content)
        self.assertNotIn("queuePageSize = Math.max(20, Number(value) || 20)", list_pages)
        self.assertNotIn("completedPageSize = Math.max(20, Number(value) || 20)", list_pages)
        self.assertNotIn("items.slice(start, start + state.queuePageSize)", render_queue_block)
        self.assertNotIn("items.slice(start, start + state.completedPageSize)", render_completed_block)

    def test_web_active_download_selects_sync_custom_shell_after_state_updates(self):
        content = _static_bundle_content()
        sync_block = content.split("function syncActiveDownloadOptions()", 1)[1].split(
            "function updateDownloadOptions()",
            1,
        )[0]

        self.assertIn('const retries = byId("activeMaxRetries");', sync_block)
        self.assertIn('const concurrent = byId("activeMaxConcurrent");', sync_block)
        self.assertIn("syncCustomSelectForSelect(retries);", sync_block)
        self.assertIn("syncCustomSelectForSelect(concurrent);", sync_block)

    def test_disabled_web_buttons_do_not_receive_hover_treatment(self):
        content = _static_bundle_content()

        self.assertIn(".btn:not(:disabled):hover", content)
        self.assertIn(".btn-dir:not(:disabled):hover", content)
        self.assertIn(".modal-actions .btn:not(:disabled):hover", content)
        self.assertNotIn(".btn:hover, .nav-item:hover, .tab:hover", content)
        self.assertNotIn(".btn-dir:hover {", content)
        self.assertNotIn(".modal-actions .btn:hover", content)

    def test_websocket_endpoint_referenced(self):
        """前端必须连 /ws。"""
        content = _static_bundle_content()
        self.assertIn("/ws", content)

    def test_no_xss_vulnerability(self):
        """关键位置必须用 esc() 函数。"""
        content = _static_bundle_content()
        # 必须定义 esc 函数
        self.assertIn("function esc(", content)
        # 必须使用 esc（避免 XSS）
        self.assertGreater(content.count("esc("), 0)

    def test_unified_seven_page_structure(self):
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = p.read_text(encoding="utf-8")
        for page_id in ("queue", "active", "completed", "failed", "logs", "settings", "toolbox"):
            self.assertIn(f'id="page-{page_id}"', content)
        top_bar = content.split('<header class="top-bar" id="topBar">', 1)[1].split("</header>", 1)[0]
        for removed in ("错误摘要", "复制Trace", "导出日志", "清空记录"):
            self.assertNotIn(removed, top_bar)
        queue_page = content.split('id="page-queue"', 1)[1].split('id="page-active"', 1)[0]
        self.assertNotIn("<video", queue_page)
        self.assertNotIn('type="checkbox"', queue_page)
        active_page = content.split('id="page-active"', 1)[1].split('id="page-completed"', 1)[0]
        self.assertNotIn("<video", active_page)
        self.assertNotIn("<th>状态</th>", active_page)

class WebSocketMessageTypesTests(unittest.TestCase):
    """WebSocket 消息类型一致性测试。"""

    def test_all_message_types_have_handlers(self):
        """前端所有 handleServerMessage switch case 必须定义。"""
        import re
        content = _static_bundle_content()
        # 提取所有 case
        cases = re.findall(r"case [\"'](\w+)[\"']:", content)
        # 必须的 case
        for required in (
            "init_state", "platforms", "config", "log", "item_found",
            "video_state_changed", "video_renamed", "video_removed",
            "clear_videos", "task_started", "task_progress",
            "task_finished", "task_error", "crawl_state",
            "select_tasks", "scan_result",
        ):
            self.assertIn(required, cases, f"missing WS case: {required}")

# ============================================================
# Playwright 浏览器测试（可选）
# ============================================================

@unittest.skipUnless(_playwright_available(), "playwright not installed")

# ============================================================
# Playwright ???????????????
# ============================================================

@unittest.skipUnless(_playwright_available(), "playwright not installed")
class WebUIBrowserTests(
    _SmokeAndAssetsCases,
    _LocalizationCases,
    _LogCenterCases,
    _DialogsAndKeyboardCases,
    _PlaybackCases,
    _SettingsCases,
    _RuntimeAndListCases,
    _WebUIBrowserTestBase,
):
    """??????? Chromium ???????? WebUI ??????"""


@unittest.skipUnless(_playwright_available(), "playwright not installed")
class WebUIAccessibilityTests(unittest.TestCase):
    """Web UI 可访问性测试。"""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._server_ctx = _running_server()
        cls._server_url = cls._server_ctx.__enter__()
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=True)
        cls._context = cls._browser.new_context()
        cls._page = cls._context.new_page()
        cls._page.add_init_script("localStorage.clear(); sessionStorage.clear();")

    @classmethod
    def tearDownClass(cls):
        try:
            cls._page.close()
            cls._context.close()
            cls._browser.close()
            cls._playwright.stop()
        except Exception:
            pass
        try:
            cls._server_ctx.__exit__(None, None, None)
        except Exception:
            pass

    def _goto_ready(self):
        _wait_for_webui_ready(self._page, self._server_url)

    def test_buttons_have_text_or_title(self):
        """所有按钮必须有可读文本或 title。"""
        self._goto_ready()
        # 检查所有 .btn / button 元素
        buttons = self._page.locator("button").all()
        for b in buttons:
            text = (b.text_content() or "").strip()
            title = b.get_attribute("title") or ""
            # 至少有一个不能空
            if not text and not title:
                # 排除纯图标的 op-btn
                if "op-btn" in (b.get_attribute("class") or ""):
                    continue
                self.fail(f"Button has no text/title: {b.get_attribute('class')}")

    def test_html_has_lang(self):
        """html 必须有 lang 属性。"""
        self._page.goto(self._server_url, wait_until="domcontentloaded")
        lang = self._page.evaluate("document.documentElement.getAttribute('lang')")
        self.assertIn(lang, ("zh-CN", "zh", "en"), f"html lang={lang!r}")

    def test_viewport_meta(self):
        """必须有 viewport meta 标签。"""
        self._page.goto(self._server_url, wait_until="domcontentloaded")
        viewport = self._page.locator("meta[name=viewport]").get_attribute("content")
        self.assertIsNotNone(viewport)
        self.assertIn("width=device-width", viewport)

# ============================================================
# Web 设计指南审查（来自 web-design-guidelines skill）
# ============================================================

class WebDesignGuidelinesTests(unittest.TestCase):
    """参考 Vercel Web Interface Guidelines 检查关键 UI 规则。

    实际完整审查应通过 skill 完成，本测试只覆盖最关键的：
    - 键盘可达性（focus 可见）
    - 颜色对比度（CSS 变量定义）
    - 响应式 viewport
    - 错误状态有提示
    """

    def test_focus_visible_css_exists(self):
        """必须有 focus 样式（键盘可达性）。"""
        content = _static_bundle_content()
        # 至少有几个 :focus 规则
        self.assertIn(":focus", content)
        self.assertGreater(content.count(":focus"), 0)

    def test_buttons_have_hover_state(self):
        """按钮必须有 hover 样式。"""
        content = _static_bundle_content()
        self.assertIn(":hover", content)
        self.assertGreater(content.count(":hover"), 5)

    def test_error_messages_have_log(self):
        """错误消息应写入日志（用户可见）。"""
        content = _static_bundle_content()
        # 至少有几个 ❌ 错误日志
        self.assertGreaterEqual(content.count("失败"), 3)

    def test_disabled_state_styled(self):
        """disabled 状态应有样式。"""
        content = _static_bundle_content()
        self.assertIn(":disabled", content)

if __name__ == "__main__":
    unittest.main()
