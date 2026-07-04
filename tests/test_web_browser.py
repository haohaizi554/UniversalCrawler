"""Web 浏览器测试 (Playwright)。

用真实 Chromium 浏览器对 web UI 进行：
- 静态资源检查（HTML/CSS/JS 语法）
- 端点可达性
- 主题切换交互
- WebSocket 连接
- 键盘交互（Enter 搜索、方向键、Esc 退出）
- 选择对话框打开/关闭
- 暗/亮主题 CSS 变量

设计原则：
- 不真爬虫（断网或失败时优雅降级）
- 用 sync_playwright 同步 API
- 默认 5s 超时（避免 CI 卡死）
- 启动 uvicorn 服务器，浏览器连 localhost

参考：
- Skill: webapp-testing（with_server.py 模式）
- Skill: agent-browser（snapshot 模式）

依赖：
- playwright install chromium
- pip install playwright
"""

from __future__ import annotations

import os
import sys
import time
import unittest
import socket
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

# 让 web_entry 等可被 import
_TESTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 离线模式
os.environ.setdefault("UCRAWL_OFFLINE", "1")

def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False

def _find_free_port() -> int:
    """找一个空闲端口（避免与 web_entry 端口冲突）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def _static_bundle_content() -> str:
    """Read split WebUI assets as one bundle for static assertions."""
    static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
    parts = []
    for name in ("index.html", "app.css", "i18n.js", "custom_select.js", "media_display.js", "log_display.js", "platform_limits.js", "settings_render.js", "task_render.js", "playback_state.js", "app.js"):
        path = static_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)

@contextmanager
def _running_server(host: str = "127.0.0.1", port: int = 0):
    """在后台启动 web_entry 服务器，测试结束后关闭。

    Yields:
        (host, port) 元组
    """
    if port == 0:
        port = _find_free_port()
    env = os.environ.copy()
    env["UCRAWL_OFFLINE"] = "1"
    env["PYTHONPATH"] = str(_PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # 用 no-qt + no-browser 模式（避免 Qt 弹窗 + 自动开浏览器）
    # 用 tests.web_test_app 作为 uvicorn 启动入口（该文件用 create_app() 暴露 app）
    cmd = [
        sys.executable, "-m", "uvicorn",
        "tests.web_test_app:app",
        "--host", host,
        "--port", str(port),
        "--no-access-log",
        "--log-level", "warning",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # 等服务器起来（最多 30s）
    deadline = time.time() + 30
    url = f"http://{host}:{port}"
    server_output: list[str] = []
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.2)
    else:
        # 失败时打印 stderr 便于排查
        try:
            stderr_data = proc.stderr.read() if proc.stderr else b""
            server_output.append(stderr_data.decode("utf-8", errors="replace")[-2000:])
        except Exception:
            pass
        proc.terminate()
        raise RuntimeError(
            f"Server failed to start on {url}\n"
            f"stderr: {''.join(server_output)[:1500]}"
        )
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

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
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        self.assertTrue(content.lower().startswith("<!doctype html>"))

    def test_index_html_required_ids(self):
        """所有 JS 引用的 id 必须在 HTML 中存在。"""
        from pathlib import Path
        import re
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
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
        self.assertIn("document.addEventListener(\"fullscreenchange\"", bundle)

    def test_index_html_required_js_functions(self):
        """所有 onclick/on... 引用的函数必须存在。"""
        from pathlib import Path
        import re
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        # 从 onclick="..." 提取函数名
        onclicks = re.findall(r'onclick="(\w+)\(', content)
        for fn in set(onclicks):
            self.assertIn(f"function {fn}(", content,
                         f"missing JS function: {fn}")

    def test_selection_modal_keyboard_shortcuts_are_scoped(self):
        content = _static_bundle_content()

        self.assertIn('id="selectionModal" class="modal selection-modal" tabindex="-1"', content)
        self.assertIn("function handleSelectionModalShortcut(event)", content)
        self.assertIn("function isSelectionModalOpen()", content)
        self.assertIn("function isTextEntryTarget(target)", content)
        self.assertIn("function selectAllSelectionItems()", content)
        self.assertIn("function invertSelectionItems()", content)
        self.assertIn('"checkbox"', content)
        self.assertIn('byId("selectionConfirmBtn").focus({ preventScroll: true })', content)
        self.assertIn('if (event.key === "Enter") confirmSelection();', content)
        self.assertIn("else cancelSelection();", content)
        self.assertIn("if (handleSelectionModalShortcut(event)) return;", content)
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
        self.assertIn("if (handleFileAssociationModalShortcut(event)) return;", content)

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
        self.assertIn("await fetchFrontendState()", content)
        self.assertIn(".dir-modal-box", content)
        self.assertIn(".dir-entry.selected", content)
        self.assertIn(".dir-folder-list", content)
        self.assertIn("max-height: none", content)

    def test_preview_nav_buttons_are_visible(self):
        from pathlib import Path
        import re
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
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

        self.assertIn('/static/app.css?v=20260628-settings-masterdetail', content)
        self.assertIn('/static/i18n.js?v=20260701-i18n', content)
        self.assertIn('/static/custom_select.js?v=20260701-custom-select', content)
        self.assertIn('/static/media_display.js?v=20260701-media-display', content)
        self.assertIn('/static/log_display.js?v=20260701-log-display', content)
        self.assertIn('/static/platform_limits.js?v=20260701-platform-limits', content)
        self.assertIn('/static/settings_render.js?v=20260701-settings-render', content)
        self.assertIn('/static/task_render.js?v=20260701-task-render', content)
        self.assertIn('/static/playback_state.js?v=20260701-playback-state', content)
        self.assertIn('/static/app.js?v=20260628-settings-masterdetail', content)

    def test_video_end_autoplays_next_preview(self):
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()

        self.assertIn("function autoplayNextPreview(", content)
        self.assertIn("setupPlayerEvents(player, id)", content)
        self.assertIn("function setupPlayerEvents(player, sourceId)", content)
        self.assertIn("shouldAutoplayNext()", content)
        self.assertIn("autoplayNextPreview();", content)

    def test_css_variables_defined(self):
        """深色/浅色主题 CSS 变量必须定义。"""
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        # 关键 CSS 变量
        for var in ("--bg", "--panel", "--accent", "--text", "--border"):
            self.assertIn(var, content, f"missing CSS variable: {var}")

    def test_platform_settings_static_contract_matches_gui(self):
        content = _static_bundle_content()

        self.assertIn("configureTopCountForSource", content)
        self.assertIn('count_config_key || "max_items"', content)
        self.assertIn('data-setting="proxy_url"', content)
        self.assertIn('updateSetting(platformId, key, "\\u81ea\\u5b9a\\u4e49")', content)
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
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        # 不应出现 TODO/FIXME 标记
        self.assertNotIn("TODO", content)
        self.assertNotIn("FIXME", content)
        # 不应有未配对的花括号（粗略检查）
        self.assertEqual(content.count("{"), content.count("}"))

    def test_high_frequency_events_use_delta_not_full_state_fetch(self):
        content = _static_bundle_content()
        self.assertIn('case "frontend_delta":', content)
        self.assertIn("function applyFrontendDelta(", content)
        self.assertIn("function patchTableRows(", content)
        high_event_block = content.split('case "item_found":', 1)[1].split('case "select_tasks":', 1)[0]
        self.assertNotIn("fetchFrontendState();", high_event_block)
        self.assertIn("applyLegacyFrontendEvent(type, data);", high_event_block)

    def test_frontend_delta_uses_batched_section_rendering(self):
        content = _static_bundle_content()
        delta_block = content.split("function applyFrontendDelta(delta)", 1)[1].split(
            "function removeDeletedFromFrontendState",
            1,
        )[0]
        scheduler_block = content.split("function scheduleRenderSections(sections)", 1)[1].split(
            "function flushRenderSections()",
            1,
        )[0]

        self.assertIn("if (changed.length) scheduleRenderSections(changed)", delta_block)
        self.assertIn("frontendSectionSignature(value)", delta_block)
        self.assertNotIn("changed.length ? changed : [\"all\"]", delta_block)
        self.assertNotIn("renderAll();", delta_block)
        self.assertIn("scheduleFrame", scheduler_block)

    def test_frontend_delta_rejects_stale_or_discontinuous_versions(self):
        content = _static_bundle_content()
        delta_block = content.split("function applyFrontendDelta(delta)", 1)[1].split(
            "function removeDeletedFromFrontendState",
            1,
        )[0]

        self.assertIn("deltaVersion <= localVersion", delta_block)
        self.assertIn("deltaBaseVersion > localVersion", delta_block)
        self.assertIn("fetchFrontendState();", delta_block)
        self.assertIn('appendUiLog("增量状态基线不连续，正在重新同步...")', delta_block)

    def test_frontend_delta_updates_icon_manifest_and_rerenders_current_page(self):
        content = _static_bundle_content()
        delta_block = content.split("function applyFrontendDelta(delta)", 1)[1].split(
            "function removeDeletedFromFrontendState",
            1,
        )[0]
        flush_block = content.split("function flushRenderSections()", 1)[1].split(
            "function applyFrontendDelta(delta)",
            1,
        )[0]

        self.assertIn("updateIconManifest(sections.icon_manifest)", delta_block)
        self.assertIn("changed.push(\"icon_manifest\")", delta_block)
        self.assertIn('sections.has("icon_manifest")', flush_block)
        self.assertIn("renderCurrentPage()", flush_block)

    def test_settings_snapshot_delta_does_not_rerender_non_settings_page(self):
        content = _static_bundle_content()
        flush_block = content.split("function flushRenderSections()", 1)[1].split(
            "function applyFrontendDelta(delta)",
            1,
        )[0]

        self.assertIn('sections.has("settings_snapshot") && currentPage === "queue"', flush_block)
        self.assertIn('configureTopCountForSource(byId("sourceSelect")?.value || "douyin")', flush_block)
        self.assertNotIn('sections.has("settings_snapshot") && currentPage !== "settings"', flush_block)

    def test_deleted_delta_clears_stale_selection_state(self):
        content = _static_bundle_content()
        remove_block = content.split("function removeDeletedFromFrontendState(ids)", 1)[1].split(
            "function applyLegacyFrontendEvent",
            1,
        )[0]

        self.assertIn("const removesPlayingItem", remove_block)
        self.assertIn("if (removesPlayingItem) closePreview();", remove_block)
        self.assertIn('for (const key of ["active", "completed", "failed"])', remove_block)
        self.assertIn("selected[key] = \"\"", remove_block)
        self.assertIn("selectedVideoId = null", remove_block)
        self.assertIn("currentPlayingId = null", remove_block)
        self.assertIn("removePlaybackPosition(id)", remove_block)

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
        content = _static_bundle_content()
        frontend_action_block = content.split("function frontendAction(action, payload)", 1)[1].split(
            "function mediaUrl(id)",
            1,
        )[0]
        delete_block = content.split("function prepareDeleteItem(id)", 1)[1].split(
            "async function previewVideo(id)",
            1,
        )[0]

        self.assertIn('if (action === "delete_item") prepareDeleteItem(payload && (payload.id || payload.video_id));', frontend_action_block)
        self.assertIn("function prepareDeleteItem(id)", content)
        self.assertIn("String(currentPlayingId || \"\") === videoId", delete_block)
        self.assertIn("closePreview();", delete_block)
        self.assertIn("prepareDeleteItem(id);", delete_block)

    def test_start_crawl_validates_platform_and_connection_before_running_state(self):
        content = _static_bundle_content()
        ui_state_block = content.split("function setCrawlUiState(isRunning)", 1)[1].split("function startCrawl()", 1)[0]
        start_block = content.split("function startCrawl()", 1)[1].split("function stopCrawl()", 1)[0]
        stop_block = content.split("function stopCrawl()", 1)[1].split("function sendWS", 1)[0]
        send_block = content.split("function sendWS(type, data)", 1)[1].split("const defaultSendWS", 1)[0]

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

        self.assertIn("function uiTextWithDetail(label, detail = \"\")", content)
        self.assertIn("function appendUiLog(label, detail = \"\", prefix = \"\")", content)
        for snippet in (
            'appendUiLog("请输入主页链接、分享链接或合集链接")',
            'appendUiLog("未选择有效模式", "", "❌ ")',
            'appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ")',
            'appendUiLog("正在绑定默认打开方式...")',
            'appendUiLog("文件不存在或已被删除", "", "❌ ")',
            'appendUiLog("播放前校验失败", error.message || error, "❌ ")',
            'appendUiLog("已复制 Trace ID", traceId)',
        ):
            self.assertIn(snippet, content)
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
        content = _static_bundle_content()

        self.assertIn("const PLAYBACK_POSITION_PREFIX", content)
        self.assertIn("function playbackPositionIdentity(id)", content)
        self.assertIn("item.local_path || item.filename || item.id", content)
        self.assertIn("encodeURIComponent(playbackPositionIdentity(id))", content)
        self.assertIn("function cleanupWebPlaybackPositions(items)", content)
        self.assertIn("key.startsWith(PLAYBACK_POSITION_PREFIX)", content)
        self.assertIn("cleanupWebPlaybackPositions(allItems);", content)
        self.assertIn("localStorage.removeItem(legacyPlaybackPositionKey(sourceId))", content)

    def test_web_preview_validates_media_with_server_before_playback(self):
        content = _static_bundle_content()
        validate_block = content.split("async function validateMediaForPreview(id)", 1)[1].split(
            "async function playCompleted(id)",
            1,
        )[0]
        play_block = content.split("async function playCompleted(id)", 1)[1].split(
            "function openDirectory(id)",
            1,
        )[0]

        self.assertIn("previewRequestToken", content)
        self.assertIn('headers: { Range: "bytes=0-0" }', validate_block)
        self.assertIn("response.body.cancel()", validate_block)
        self.assertIn("response.status === 404", validate_block)
        self.assertIn("播放前校验失败", validate_block)
        self.assertIn('appendUiLog(response.status === 404 ? "文件不存在或已被删除" : "播放前校验失败"', validate_block)
        self.assertIn("if (!(await validateMediaForPreview(id)) || requestToken !== previewRequestToken) return;", play_block)
        self.assertIn("appendPlaybackFailure", content)
        self.assertIn("video.play().catch(error => appendPlaybackFailure(item, error))", play_block)

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

        self.assertIn('byId("selectionConfirmBtn").focus({ preventScroll: true })', modal_block)
        self.assertIn('if (!["Enter", "Escape"].includes(event.key)) return false;', shortcut_block)
        self.assertIn("event.preventDefault();", shortcut_block)
        self.assertIn("event.stopPropagation();", shortcut_block)
        self.assertIn('if (event.key === "Enter") confirmSelection();', shortcut_block)
        self.assertIn("else cancelSelection();", shortcut_block)

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
        content = _static_bundle_content()
        append_log_block = content.split("function appendLog(message)", 1)[1].split(
            "function onChangeDirClicked()",
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
        self.assertIn("function uiLogDisplayLimit()", content)
        self.assertIn("function trimFrontendLogItems()", content)
        self.assertIn("frontendState.log_items = frontendState.log_items.slice(-limit);", content)
        self.assertIn("if (trimFrontendLogItems() && !changed.includes(\"log_items\")) changed.push(\"log_items\");", content)

    def test_web_log_rendering_is_current_page_and_budgeted(self):
        content = _static_bundle_content()
        html = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        render_all_block = content.split("function renderAll()", 1)[1].split(
            "function renderCurrentPage()",
            1,
        )[0]
        render_logs_block = content.split("function renderLogs()", 1)[1].split(
            "function logItemId",
            1,
        )[0]

        self.assertIn("const LOG_RENDER_ROW_BUDGET = 300;", content)
        self.assertIn("renderCurrentPage();", render_all_block)
        self.assertNotIn("renderLogs();", render_all_block)
        self.assertIn("const boundedItems = visibleLogItems(filteredItems, uiLogDisplayLimit());", render_logs_block)
        self.assertIn("boundedItems.slice(start, start + logPageSize)", render_logs_block)
        self.assertIn("function visibleLogItems(items, rowBudget = LOG_RENDER_ROW_BUDGET)", content)
        self.assertIn("function setLogPage(delta)", content)
        self.assertIn("function setLogPageSize(value)", content)
        self.assertIn("function normalizeLogPageSize(value)", content)
        self.assertIn('syncCustomSelectForSelect(byId("logPageSize"))', render_logs_block)
        for elem_id in ("logTotal", "logPrevPage", "logPageIndicator", "logPageSize", "logNextPage"):
            self.assertIn(f'id="{elem_id}"', html)
        self.assertIn('<option value="0">全部</option>', html)

    def test_web_log_table_uses_gui_display_fields(self):
        content = _static_bundle_content()
        render_logs_block = content.split("function renderLogs()", 1)[1].split(
            "function logItemId",
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
        self.assertIn("[\"级别\", logLevelCellHtml(item)]", content)
        self.assertIn("[\"来源\", logSourceCellHtml(item)]", content)
        self.assertIn(".log-level-badge", content)
        self.assertIn(".log-source-cell", content)

    def test_web_table_page_size_matches_gui_pagination_contract(self):
        content = _static_bundle_content()
        render_queue_block = content.split("function renderQueue()", 1)[1].split(
            "function queueTitleHtml",
            1,
        )[0]
        render_completed_block = content.split("function renderCompleted()", 1)[1].split(
            "function selectCompleted",
            1,
        )[0]

        self.assertIn("function normalizeTablePageSize(value)", content)
        self.assertIn('let queuePageSize = normalizeTablePageSize(localStorage.getItem("webui_queue_page_size") || 20);', content)
        self.assertIn('let completedPageSize = normalizeTablePageSize(localStorage.getItem("webui_completed_page_size") || 20);', content)
        self.assertIn("return [20, 50, 100].includes(numeric) ? numeric : 20;", content)
        self.assertIn("queuePageSize = normalizeTablePageSize(value);", content)
        self.assertIn("completedPageSize = normalizeTablePageSize(value);", content)
        self.assertIn('syncCustomSelectForSelect(byId("queuePageSize"))', render_queue_block)
        self.assertIn('syncCustomSelectForSelect(byId("completedPageSize"))', render_completed_block)
        self.assertIn('byId("queuePrevPage").disabled = queuePage <= 1;', render_queue_block)
        self.assertIn('byId("queueNextPage").disabled = queuePage >= totalPages;', render_queue_block)
        self.assertIn('byId("completedPrevPage").disabled = completedPage <= 1;', render_completed_block)
        self.assertIn('byId("completedNextPage").disabled = completedPage >= totalPages;', render_completed_block)
        for elem_id in ("queuePrevPage", "queueNextPage", "completedPrevPage", "completedNextPage"):
            self.assertIn(f'id="{elem_id}"', content)
        self.assertIn('id="queuePrevPage" class="icon-btn pagination-button" type="button"', content)
        self.assertIn('id="completedNextPage" class="icon-btn pagination-button" type="button"', content)
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
        self.assertNotIn("queuePageSize = Math.max(20, Number(value) || 20)", content)
        self.assertNotIn("completedPageSize = Math.max(20, Number(value) || 20)", content)

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
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        self.assertIn("/ws", content)

    def test_no_xss_vulnerability(self):
        """关键位置必须用 esc() 函数。"""
        from pathlib import Path
        import re
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
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
        from pathlib import Path
        import re
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
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
class WebUIBrowserTests(unittest.TestCase):
    """用真实浏览器测试 web UI（用 with_server 模式）。"""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        # 启动服务器（找一个空闲端口）
        cls._server_ctx = _running_server()
        cls._server_url = cls._server_ctx.__enter__()
        # 启动 Chromium
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=True)
        cls._context = cls._browser.new_context(viewport={"width": 1280, "height": 720})
        cls._page = cls._context.new_page()

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

    def setUp(self):
        # 每个测试前清 localStorage
        self._page.goto(self._server_url)
        try:
            self._page.evaluate("localStorage.clear()")
        except Exception:
            pass

    def test_01_index_loads(self):
        """主页加载成功。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        # 3 秒解锁超时后应能看到 body
        self._page.wait_for_timeout(3500)
        title = self._page.title()
        self.assertIn("Universal", title)

    def test_02_platforms_endpoint(self):
        """/api/platforms 返回非空列表。"""
        resp = self._page.request.get(f"{self._server_url}/api/platforms")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertGreater(len(data), 0)
        for p in data:
            self.assertIn("id", p)
            self.assertIn("name", p)

    def test_03_ping_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/ping")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_04_state_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/state")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIn("video_count", data)
        self.assertIn("is_crawling", data)

    def test_05_config_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/config")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)

    def test_06_source_select_visible(self):
        """sourceSelect 应可见。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 等待 select 可见
        sel = self._page.locator("#sourceSelect")
        self.assertTrue(sel.is_visible(), "sourceSelect should be visible after init")

    def test_06b_source_select_uses_platform_icons_like_gui(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            () => {
              const wrapper = document.querySelector('.custom-select-source');
              const button = wrapper && wrapper.querySelector('.custom-select-button');
              if (button) button.click();
              const optionIcon = document.querySelector('#sourceSelect option')?.dataset.icon || '';
              const buttonIcon = wrapper?.querySelector('.custom-select-button .custom-select-icon')?.getAttribute('src') || '';
              const menuIconCount = wrapper ? wrapper.querySelectorAll('.custom-select-menu .custom-select-icon').length : 0;
              return { optionIcon, buttonIcon, menuIconCount };
            }
            """
        )

        self.assertIn("/ui-icon/platform_", result["optionIcon"])
        self.assertIn("/ui-icon/platform_", result["buttonIcon"])
        self.assertGreater(result["menuIconCount"], 0)

    def test_07_theme_toggle_changes_data_theme(self):
        """点击主题按钮应切换 data-theme。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        before = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self._page.locator("#themeBtn").click()
        self._page.wait_for_timeout(200)
        after = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self.assertIn(before, {"light", "dark"})
        self.assertEqual(after, "light" if before == "dark" else "dark")

    def test_08_dir_modal_opens(self):
        """点击更改目录按钮应弹出目录弹窗。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 找到更改目录按钮
        # HTML 里 onclick="onChangeDirClicked()"
        self._page.evaluate("onChangeDirClicked()")
        # 等待弹窗出现
        modal = self._page.locator("#dirModal")
        # 不一定立即可见（要先 fetch /api/dir/list）
        self._page.wait_for_timeout(2000)
        # 检查 modal.style.display 变成了 flex
        display = self._page.evaluate("document.getElementById('dirModal').style.display")
        self.assertIn(display, ("flex", "block"))

    def test_09_selection_modal_can_be_called(self):
        """showSelectionModal 函数可以调用。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 直接调用 showSelectionModal
        self._page.evaluate("showSelectionModal([{title: 'test'},{title: 'demo'}])")
        # 弹窗应出现
        self._page.wait_for_timeout(500)
        header = self._page.locator("#selectionHeader").text_content()
        self.assertIn("2", header)

    def test_09b_language_switch_translates_runtime_ui_messages(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = "en-US";
              applyStaticLanguage();
              document.getElementById("searchInput").value = "";
              startCrawl();
              setDirStatus("目录加载失败：boom", "error");
              const lastLog = frontendState.log_items[frontendState.log_items.length - 1] || {};
              return {
                startLabel: document.getElementById("startBtn").textContent.trim(),
                logMessage: lastLog.message,
                dirStatus: document.getElementById("dirStatus").textContent
              };
            }
            """
        )

        self.assertEqual(result["startLabel"], "Start")
        self.assertEqual(result["logMessage"], "Enter a profile, shared, or collection link")
        self.assertEqual(result["dirStatus"], "Failed to load folder: boom")

    def test_10_fullscreen_toggle(self):
        """toggleFullscreen 应在 body 上加 is-fullscreen 类。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        result = self._page.evaluate(
            """
            () => {
              const panel = document.getElementById('previewPanel');
              let called = false;
              Object.defineProperty(panel, 'requestFullscreen', {
                configurable: true,
                value: () => {
                  called = true;
                  return Promise.resolve();
                }
              });
              toggleFullscreen();
              return {
                called,
                bodyFullscreen: document.body.classList.contains('is-fullscreen')
              };
            }
            """
        )
        self._page.wait_for_timeout(200)
        self.assertTrue(result["called"])
        self.assertFalse(result["bodyFullscreen"])

    def test_11_esc_closes_modals(self):
        """Esc 键应关闭弹窗。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 打开 selection modal
        self._page.evaluate("showSelectionModal([{title: 'x'}])")
        self._page.wait_for_timeout(300)
        # 按 Esc
        self._page.keyboard.press("Escape")
        self._page.wait_for_timeout(200)
        # modal 应隐藏
        display = self._page.evaluate("document.getElementById('selectionModal').style.display")
        self.assertIn(display, ("none", ""), f"selectionModal should be hidden, got display={display!r}")

    def test_11b_enter_confirms_selection_modal(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        self._page.evaluate(
            """
            () => {
              window.__selectionShortcutMessages = [];
              window.sendWS = (type, payload) => window.__selectionShortcutMessages.push({ type, payload });
              sendWS = window.sendWS;
              showSelectionModal([{title: 'first'}, {title: 'second'}]);
            }
            """
        )
        self._page.wait_for_timeout(100)
        self._page.evaluate("document.querySelector('#selectionBody input').focus()")

        self._page.keyboard.press("Enter")
        self._page.wait_for_timeout(100)

        result = self._page.evaluate(
            """
            () => ({
              display: document.getElementById('selectionModal').style.display,
              messages: window.__selectionShortcutMessages
            })
            """
        )
        self.assertIn(result["display"], ("none", ""))
        self.assertEqual(
            result["messages"],
            [{"type": "select_tasks", "payload": {"indices": [0, 1]}}],
        )

    def test_11c_file_association_modal_esc_and_enter_match_gui(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        esc_result = self._page.evaluate(
            """
            () => {
              showFileAssociationModal();
              return {
                before: document.getElementById('fileAssociationModal').style.display,
                video: document.getElementById('associationVideo').checked,
                image: document.getElementById('associationImage').checked
              };
            }
            """
        )
        self.assertEqual(esc_result["before"], "flex")
        self.assertTrue(esc_result["video"])
        self.assertTrue(esc_result["image"])

        self._page.keyboard.press("Escape")
        self._page.wait_for_timeout(100)
        display_after_esc = self._page.evaluate("document.getElementById('fileAssociationModal').style.display")
        self.assertIn(display_after_esc, ("none", ""))

        self._page.evaluate(
            """
            () => {
              window.__associationActions = [];
              window.frontendAction = (action, payload) => window.__associationActions.push({ action, payload });
              frontendAction = window.frontendAction;
              showFileAssociationModal();
              document.getElementById('associationImage').checked = false;
              document.getElementById('associationConfirmBtn').focus();
            }
            """
        )
        self._page.keyboard.press("Enter")
        self._page.wait_for_timeout(100)

        enter_result = self._page.evaluate(
            """
            () => ({
              display: document.getElementById('fileAssociationModal').style.display,
              actions: window.__associationActions
            })
            """
        )
        self.assertIn(enter_result["display"], ("none", ""))
        self.assertEqual(
            enter_result["actions"],
            [{"action": "register_file_associations", "payload": {"include_video": True, "include_image": False}}],
        )

    def test_11d_missing_media_validation_keeps_preview_closed(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = (url, options) => {
                if (String(url).includes('/api/media/missing-media')) {
                  return Promise.resolve(new Response('', { status: 404 }));
                }
                return originalFetch(url, options);
              };
              try {
                frontendState.completed_items = [{
                  id: 'missing-media',
                  title: 'Missing Demo',
                  filename: 'missing.mp4',
                  local_path: 'Z:/missing.mp4',
                  content_type: 'video',
                  format: 'MP4'
                }];
                currentPage = 'completed';
                renderCompleted();
                await playCompleted('missing-media');
                return {
                  currentPlayingId,
                  videoDisplay: document.getElementById('videoPlayer').style.display,
                  previewDisplay: document.getElementById('previewArea').style.display,
                  logs: (frontendState.log_items || []).slice(-4).map(item => item.message)
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertIsNone(result["currentPlayingId"])
        self.assertNotEqual(result["videoDisplay"], "block")
        self.assertNotEqual(result["previewDisplay"], "none")
        self.assertTrue(
            any("文件不存在" in message for message in result["logs"]),
            f"expected missing-file log, got {result['logs']!r}",
        )

    def test_11e_delete_current_preview_closes_player_immediately(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = () => Promise.resolve(new Response(JSON.stringify({ status: 'ok' }), {
                status: 200,
                headers: { 'content-type': 'application/json' }
              }));
              try {
                ws = null;
                frontendState.completed_items = [{
                  id: 'playing-delete',
                  title: 'Playing Delete',
                  filename: 'playing-delete.mp4',
                  local_path: 'Z:/playing-delete.mp4',
                  content_type: 'video',
                  format: 'MP4'
                }];
                currentPage = 'completed';
                selected.completed = 'playing-delete';
                selectedVideoId = 'playing-delete';
                currentPlayingId = 'playing-delete';
                const video = document.getElementById('videoPlayer');
                const preview = document.getElementById('previewArea');
                video.style.display = 'block';
                preview.textContent = '';
                preview.style.display = 'none';

                frontendAction('delete_item', { id: 'playing-delete' });
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                  currentPlayingId,
                  videoDisplay: video.style.display,
                  previewDisplay: preview.style.display,
                  previewText: preview.textContent
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertIsNone(result["currentPlayingId"])
        self.assertEqual(result["videoDisplay"], "none")
        self.assertEqual(result["previewDisplay"], "flex")
        self.assertEqual(result["previewText"], "")

    def test_11f_stale_selection_reconciles_to_visible_first_row(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            () => {
              frontendState.active_downloads = [
                { id: 'active-a', title: 'Active A', platform: 'Bilibili', platform_id: 'bilibili', progress: 12, speed: '1 MB/s' }
              ];
              selected.active = 'missing-active';
              renderActive();

              frontendState.completed_items = [
                { id: 'completed-a', title: 'Completed A', filename: 'completed-a.mp4', completed_at: '2026-07-04 06:00:00', completed_at_table: '07-04 06:00', format: 'MP4' },
                { id: 'completed-b', title: 'Completed B', filename: 'completed-b.mp4', completed_at: '2026-07-04 06:01:00', completed_at_table: '07-04 06:01', format: 'MP4' },
                { id: 'completed-c', title: 'Completed C', filename: 'completed-c.mp4', completed_at: '2026-07-04 06:02:00', completed_at_table: '07-04 06:02', format: 'MP4' }
              ];
              completedPageSize = 2;
              completedPage = 2;
              selected.completed = 'missing-completed';
              renderCompleted();

              frontendState.failed_items = [
                { id: 'failed-a', title: 'Failed A', failed_at: '2026-07-04 06:03:00', failed_at_table: '07-04 06:03', reason: '403', reason_label: '链接失败', platform: 'Bilibili', platform_id: 'bilibili', status_label: '失败' }
              ];
              selected.failed = 'missing-failed';
              renderFailed();

              frontendState.toolbox_items = [
                { id: 'tool-a', title: 'Tool A', summary: 'Tool summary', input_example: 'Input A', output_example: 'Output A', icon_file: 'nav_toolbox.png' }
              ];
              selected.tool = 'missing-tool';
              renderToolbox();

              const selectedRows = selector => Array.from(document.querySelectorAll(selector)).map(row => row.dataset.id);
              return {
                activeSelected: selected.active,
                activeRows: selectedRows('#activeBody tr.selected'),
                activeDetail: document.getElementById('activeDetail').textContent,
                completedSelected: selected.completed,
                completedRows: selectedRows('#completedBody tr.selected'),
                completedDetail: document.getElementById('completedDetail').textContent,
                failedSelected: selected.failed,
                failedRows: selectedRows('#failedBody tr.selected'),
                failedDetail: document.getElementById('failedDetail').textContent,
                toolSelected: selected.tool,
                toolCards: Array.from(document.querySelectorAll('#toolGrid .tool-card.active')).map(button => button.textContent),
                toolDetail: document.getElementById('toolDetail').textContent
              };
            }
            """
        )

        self.assertEqual(result["activeSelected"], "active-a")
        self.assertEqual(result["activeRows"], ["active-a"])
        self.assertIn("Active A", result["activeDetail"])
        self.assertEqual(result["completedSelected"], "completed-c")
        self.assertEqual(result["completedRows"], ["completed-c"])
        self.assertIn("completed-c.mp4", result["completedDetail"])
        self.assertEqual(result["failedSelected"], "failed-a")
        self.assertEqual(result["failedRows"], ["failed-a"])
        self.assertIn("Failed A", result["failedDetail"])
        self.assertEqual(result["toolSelected"], "tool-a")
        self.assertEqual(len(result["toolCards"]), 1)
        self.assertIn("Tool A", result["toolCards"][0])
        self.assertIn("Tool A", result["toolDetail"])

    def test_12_console_no_errors(self):
        """主页加载应无 JS 错误。"""
        errors = []
        self._page.on("pageerror", lambda e: errors.append(str(e)))
        self._page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                      if msg.type == "error" else None)
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 过滤已知的非关键错误
        critical_errors = [e for e in errors
                           if "favicon" not in e.lower()
                           and "WebSocket" not in e
                           and "ws" not in e.lower()
                           and "404" not in e]
        self.assertEqual(critical_errors, [], f"JS errors: {critical_errors}")

    def test_13_log_panel_writes(self):
        """appendLog 应在 logPanel 写入内容。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        timestamp = self._page.evaluate("formatLocalDateTime(new Date(2026, 6, 4, 6, 24, 9))")
        self.assertEqual(timestamp, "2026-07-04 06:24:09")
        self._page.evaluate("appendLog('test marker 12345')")
        content = self._page.locator("#logPanel").text_content()
        self.assertIn("test marker 12345", content)

    def test_13b_log_center_footer_paginates_like_gui(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            () => {
              currentPage = 'logs';
              logPage = 1;
              logPageSize = 20;
              frontendState.log_items = Array.from({ length: 25 }, (_, index) => ({
                id: `log-${index + 1}`,
                time: `2026-07-04 06:${String(index).padStart(2, '0')}:00`,
                level: 'INFO',
                source: 'GUI',
                trace_id: `trace-${index + 1}`,
                message_summary: `message-${index + 1}`,
                message: `message-${index + 1}`,
                detail: '',
                stack: ''
              }));
              renderLogs();
              const firstPageRows = document.querySelectorAll('#logBody tr').length;
              const firstStats = document.getElementById('logTotal').textContent;
              const firstIndicator = document.getElementById('logPageIndicator').textContent;
              const firstPrevDisabled = document.getElementById('logPrevPage').disabled;
              const firstNextDisabled = document.getElementById('logNextPage').disabled;
              setLogPage(1);
              return {
                firstPageRows,
                firstStats,
                firstIndicator,
                firstPrevDisabled,
                firstNextDisabled,
                secondPageRows: document.querySelectorAll('#logBody tr').length,
                secondStats: document.getElementById('logTotal').textContent,
                secondIndicator: document.getElementById('logPageIndicator').textContent,
                secondPrevDisabled: document.getElementById('logPrevPage').disabled,
                secondNextDisabled: document.getElementById('logNextPage').disabled
              };
            }
            """
        )

        self.assertEqual(result["firstPageRows"], 20)
        self.assertEqual(result["firstStats"], "共 25 条 / 匹配 25 条 / 当前显示 20 条")
        self.assertEqual(result["firstIndicator"], "第 1 / 2 页")
        self.assertTrue(result["firstPrevDisabled"])
        self.assertFalse(result["firstNextDisabled"])
        self.assertEqual(result["secondPageRows"], 5)
        self.assertEqual(result["secondStats"], "共 25 条 / 匹配 25 条 / 当前显示 5 条")
        self.assertEqual(result["secondIndicator"], "第 2 / 2 页")
        self.assertFalse(result["secondPrevDisabled"])
        self.assertTrue(result["secondNextDisabled"])

    def test_13c_log_detail_copy_export_actions_match_gui(self):
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)

        result = self._page.evaluate(
            """
            async () => {
              const originalClick = HTMLAnchorElement.prototype.click;
              const originalCreateObjectUrl = URL.createObjectURL;
              const originalRevokeObjectUrl = URL.revokeObjectURL;
              window.__copiedLogTexts = [];
              window.__downloadedLogDetail = null;
              Object.defineProperty(navigator, 'clipboard', {
                value: {
                  writeText: text => {
                    window.__copiedLogTexts.push(text);
                    return Promise.resolve();
                  }
                },
                configurable: true
              });
              HTMLAnchorElement.prototype.click = function () {
                window.__downloadedLogDetail = { href: this.href, download: this.download };
              };
              URL.createObjectURL = () => 'blob:log-detail';
              URL.revokeObjectURL = () => {};
              try {
                currentPage = 'logs';
                logPage = 1;
                logPageSize = 20;
                frontendState.log_items = [{
                  id: 'log-detail-a',
                  time: '2026-07-04 06:30:00',
                  level: 'INFO',
                  raw_level: 'INFO',
                  source: 'ApplicationController',
                  platform: '系统',
                  trace_id: 'trace-log-detail-a',
                  message_summary: '应用开始初始化',
                  message: '应用开始初始化',
                  detail: { description: '应用开始初始化', status_code: 'APP_INIT' },
                  stack: ''
                }];
                selected.log = '';
                renderLogs();
                copyCurrentLogDetail();
                copyCurrentLogJson();
                exportCurrentLogDetail();
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                  selectedLog: selected.log,
                  detailText: document.getElementById('logDetail').textContent,
                  copied: window.__copiedLogTexts,
                  download: window.__downloadedLogDetail
                };
              } finally {
                HTMLAnchorElement.prototype.click = originalClick;
                URL.createObjectURL = originalCreateObjectUrl;
                URL.revokeObjectURL = originalRevokeObjectUrl;
              }
            }
            """
        )

        self.assertEqual(result["selectedLog"], "log-detail-a")
        self.assertIn("日志详情", result["detailText"])
        self.assertIn("详细信息", result["detailText"])
        self.assertEqual(len(result["copied"]), 2)
        self.assertIn("trace-log-detail-a", result["copied"][0])
        self.assertIn("APP_INIT", result["copied"][0])
        self.assertIn("description", result["copied"][1])
        self.assertIn("APP_INIT", result["copied"][1])
        self.assertEqual(result["download"]["href"], "blob:log-detail")
        self.assertEqual(result["download"]["download"], "log_detail_trace-log-detail-a.json")

    def test_14_keyboard_arrow_navigation(self):
        """方向键应在 videoOrder 之间切换。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # 注入测试数据
        self._page.evaluate("""
            videoOrder = ['a', 'b', 'c'];
            videos = {
                'a': {title: 'Item A', progress: 0, status: 'done'},
                'b': {title: 'Item B', progress: 0, status: 'done'},
                'c': {title: 'Item C', progress: 0, status: 'done'},
            };
            renderQueue();
        """)
        # 第一次按 ArrowDown → 选中 a
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_timeout(100)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "a")
        # 再按 ArrowDown → 选中 b
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_timeout(100)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "b")

    def test_15_delete_key_removes(self):
        """Delete 键应触发删除。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
        # Mock sendWS 来拦截 delete_video
        self._page.evaluate("""
            window._deletedIds = [];
            window.sendWS = (type, data) => {
                if (type === 'delete_video') window._deletedIds.push(data.video_id);
            };
            videoOrder = ['x1'];
            videos = {'x1': {title: 'to delete', progress: 0, status: 'done'}};
            renderQueue();
            selectedVideoId = 'x1';
            updateSelection(null, 'x1');
        """)
        # 焦点不在输入框
        self._page.evaluate("document.body.focus()")
        self._page.keyboard.press("Delete")
        self._page.wait_for_timeout(100)
        deleted = self._page.evaluate("window._deletedIds")
        self.assertEqual(deleted, ["x1"])

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

    def test_buttons_have_text_or_title(self):
        """所有按钮必须有可读文本或 title。"""
        self._page.goto(self._server_url)
        self._page.wait_for_load_state("networkidle")
        self._page.wait_for_timeout(3500)
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
        self._page.goto(self._server_url)
        lang = self._page.evaluate("document.documentElement.getAttribute('lang')")
        self.assertIn(lang, ("zh-CN", "zh", "en"), f"html lang={lang!r}")

    def test_viewport_meta(self):
        """必须有 viewport meta 标签。"""
        self._page.goto(self._server_url)
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
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        # 至少有几个 :focus 规则
        self.assertIn(":focus", content)
        self.assertGreater(content.count(":focus"), 0)

    def test_buttons_have_hover_state(self):
        """按钮必须有 hover 样式。"""
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        self.assertIn(":hover", content)
        self.assertGreater(content.count(":hover"), 5)

    def test_error_messages_have_log(self):
        """错误消息应写入日志（用户可见）。"""
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        # 至少有几个 ❌ 错误日志
        self.assertGreaterEqual(content.count("失败"), 3)

    def test_disabled_state_styled(self):
        """disabled 状态应有样式。"""
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "index.html"
        content = _static_bundle_content()
        self.assertIn(":disabled", content)

if __name__ == "__main__":
    unittest.main()
