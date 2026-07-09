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
import tempfile
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
    for name in ("index.html", "app.css", "i18n.js", "custom_select.js", "media_display.js", "log_display.js", "log_query_worker.js", "log_detail_worker.js", "platform_limits.js", "settings_render.js", "task_render.js", "playback_state.js", "log_i18n.js", "frontend_runtime.js", "list_pages.js", "log_center.js", "settings_controller.js", "dialog_controller.js", "playback_controller.js", "app.js"):
        path = static_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)

def _stable_platform_settings_snapshot_js() -> str:
    """Deterministic platform rows for browser layout/contract tests.

    The running test server intentionally reuses the real settings renderer, while
    individual tests before it may mutate user-data-backed platform settings.
    Seed the UI with stable rows when the assertion is about rendering behavior,
    not the machine's current crawler configuration.
    """
    return r"""
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot['\u5e73\u53f0\u8bbe\u7f6e'] = [
                {
                  id: 'douyin',
                  name: '\u6296\u97f3',
                  auth_status: '\u5df2\u8ba4\u8bc1',
                  default_count: 50,
                  count_config_key: 'max_items',
                  count_unit: 'videos',
                  count_editable: true,
                  count_options: [{ value: '50', label: '50 \u4e2a\u89c6\u9891' }],
                  default_timeout: 60,
                  timeout_config_key: 'timeout',
                  timeout_editable: true,
                  timeout_options: [{ value: '60', label: '60 \u79d2\uff08\u63a8\u8350\uff09' }],
                  proxy: '\u7cfb\u7edf\u4ee3\u7406',
                  proxy_config_key: '',
                  proxy_editable: false,
                  proxy_options: ['\u7cfb\u7edf\u4ee3\u7406', '\u76f4\u8fde']
                },
                {
                  id: 'bilibili',
                  name: 'Bilibili',
                  auth_status: '\u5df2\u8ba4\u8bc1',
                  default_count: 1,
                  count_config_key: 'max_pages',
                  count_unit: 'pages',
                  count_editable: true,
                  count_options: [{ value: '1', label: '1 \u9875\uff08\u63a8\u8350\uff09' }],
                  default_timeout: 60,
                  timeout_config_key: 'timeout',
                  timeout_editable: true,
                  timeout_options: [{ value: '60', label: '60 \u79d2\uff08\u63a8\u8350\uff09' }],
                  proxy: '\u7cfb\u7edf\u4ee3\u7406',
                  proxy_config_key: '',
                  proxy_editable: false,
                  proxy_options: ['\u7cfb\u7edf\u4ee3\u7406']
                },
                {
                  id: 'kuaishou',
                  name: '\u5feb\u624b',
                  auth_status: '\u5df2\u8ba4\u8bc1',
                  default_count: 20,
                  count_config_key: 'max_items',
                  count_unit: 'videos',
                  count_editable: true,
                  count_options: [{ value: '20', label: '20 \u4e2a\u89c6\u9891\uff08\u63a8\u8350\uff09' }],
                  default_timeout: 60,
                  timeout_config_key: 'timeout',
                  timeout_editable: true,
                  timeout_options: [{ value: '60', label: '60 \u79d2\uff08\u63a8\u8350\uff09' }],
                  proxy: '\u7cfb\u7edf\u4ee3\u7406',
                  proxy_config_key: 'proxy_app',
                  proxy_editable: true,
                  proxy_custom_allowed: false,
                  proxy_options: ['\u7cfb\u7edf\u4ee3\u7406', '\u76f4\u8fde', 'Clash']
                },
                {
                  id: 'missav',
                  name: 'MissAV',
                  auth_status: '\u672a\u8ba4\u8bc1',
                  default_count: 20,
                  count_config_key: 'max_items',
                  count_unit: 'videos',
                  count_editable: true,
                  count_options: [{ value: '20', label: '20 \u4e2a\u89c6\u9891\uff08\u63a8\u8350\uff09' }],
                  default_timeout: 60,
                  timeout_config_key: 'timeout',
                  timeout_editable: true,
                  timeout_options: [{ value: '60', label: '60 \u79d2\uff08\u63a8\u8350\uff09' }],
                  proxy: '\u81ea\u5b9a\u4e49',
                  proxy_config_key: 'proxy_url',
                  proxy_editable: true,
                  proxy_custom_allowed: true,
                  proxy_custom_active: true,
                  proxy_custom_value: '7890',
                  proxy_options: ['\u7cfb\u7edf\u4ee3\u7406', '\u76f4\u8fde', 'Clash (7890)', '\u81ea\u5b9a\u4e49']
                }
              ];
"""

def _wait_for_webui_ready(page, server_url: str) -> None:
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_selector("#app-shell", state="visible", timeout=5000)
    page.wait_for_function(
        """
        () => (
          typeof renderAll === 'function' &&
          typeof switchPage === 'function' &&
          Boolean(document.querySelector('#topBar')) &&
          Boolean(document.querySelector('#rightPanel')) &&
          Boolean(document.querySelector('#sourceSelect'))
        )
        """,
        timeout=5000,
    )
    page.wait_for_function("window.__ucrawlFrontendStateSettled === true", timeout=5000)

def _install_webui_test_helpers(page) -> None:
    page.evaluate(
        """
        () => {
          window.__isolateFrontendStateForTest = function (options = {}) {
            window.UcpLogCenter.dispose();
            if (typeof pageIsUnloading !== "undefined") pageIsUnloading = true;
            localStorage.setItem("webui_log_page_size", "20");
            window.__logWorkerUrls = [];
            const NativeWorker = window.Worker;
            if (options.useLogWorker === false) {
              window.Worker = undefined;
            } else if (options.captureLogWorkers && typeof NativeWorker === "function") {
              window.Worker = function (url, workerOptions) {
                window.__logWorkerUrls.push(String(url));
                return new NativeWorker(url, workerOptions);
              };
              window.Worker.prototype = NativeWorker.prototype;
            }
            window.UcpLogCenter.configure({
              getState: () => frontendState,
              getLanguage: currentLanguage,
              t,
              esc,
              escAttr,
              byId,
              writeClipboard,
              runOperation: performLogOperation,
              onFiltersChange: () => {}
            });
            window.__restoreLogWorkerForTest = () => { window.Worker = NativeWorker; };
            if (!options.captureLogWorkers) window.Worker = NativeWorker;
          };

          window.__setLogFiltersForTest = function (filters = {}) {
            const aliases = {
              "全部": "all",
              "所有": "all",
              "近 30 分钟": "30m",
              "近 1 小时": "1h",
              "近 24 小时": "24h",
            };
            const value = (key, fallback) => aliases[filters[key]] || filters[key] || fallback;
            document.getElementById("logLevelFilter").value = value("level", "all");
            document.getElementById("logTimeFilter").value = value("time", "30m");
            document.getElementById("logPlatformFilter").value = value("platform", "all");
            document.getElementById("logTraceFilter").value = String(filters.trace || "");
            document.getElementById("logKeywordFilter").value = String(filters.keyword || "");
            document.getElementById("logLevelFilter").dispatchEvent(new Event("change", { bubbles: true }));
            document.getElementById("logTimeFilter").dispatchEvent(new Event("change", { bubbles: true }));
            document.getElementById("logPlatformFilter").dispatchEvent(new Event("change", { bubbles: true }));
            document.getElementById("logTraceFilter").dispatchEvent(new Event("input", { bubbles: true }));
            document.getElementById("logKeywordFilter").dispatchEvent(new Event("input", { bubbles: true }));
            window.UcpLogCenter.setTab(filters.category || "all");
          };

          window.__waitForLogRender = async function (options = {}) {
            const has = key => Object.prototype.hasOwnProperty.call(options, key);
            const timeoutMs = Number(options.timeoutMs || 5000);
            const deadline = Date.now() + timeoutMs;
            let last = {};

            while (Date.now() < deadline) {
              const rowNodes = Array.from(document.querySelectorAll("#logBody tr"));
              const rows = rowNodes.length;
              const counts = (document.getElementById("logTotal")?.textContent || "").match(/\d+/g) || [];
              const total = counts.length >= 3 ? Number(counts[0]) : null;
              const matched = counts.length >= 3 ? Number(counts[1]) : null;
              const visible = counts.length >= 3 ? Number(counts[2]) : null;
              const text = document.getElementById("page-logs")?.textContent || "";
              const selectedId = String(document.querySelector("#logBody tr.selected")?.dataset.key || "");
              const itemFound = !has("itemId") || rowNodes.some(row => String(row.dataset.key || "") === String(options.itemId));
              const textFound = !has("text") || text.includes(String(options.text));
              const detailReady = !has("selectedId") ||
                options.waitDetail === false ||
                (selectedId === String(options.selectedId) && Boolean(document.querySelector("#logDetail .log-detail-readable")));
              last = {
                pending: false,
                detailPending: !detailReady,
                detailReady,
                rows,
                total,
                matched,
                visible,
                selectedId,
                itemFound,
                textFound,
              };

              const ready = itemFound &&
                (!has("rows") || rows === Number(options.rows)) &&
                (!has("total") || total === Number(options.total)) &&
                (!has("matched") || matched === Number(options.matched)) &&
                (!has("visible") || visible === Number(options.visible)) &&
                (!has("selectedId") || selectedId === String(options.selectedId)) &&
                detailReady &&
                textFound;
              if (ready) return last;
              await new Promise(resolve => setTimeout(resolve, 25));
            }
            throw new Error(`Log render did not settle: ${JSON.stringify(last)}`);
          };
        }
        """
    )

def _new_webui_page(context):
    page = context.new_page()
    page.add_init_script("localStorage.clear(); sessionStorage.clear();")
    return page

def _webui_server_responds(server_url: str, timeout: float = 3.0) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{server_url}/api/ping", timeout=timeout) as response:
            return response.status == 200
    except (OSError, TimeoutError, urllib.error.URLError):
        return False

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
    with tempfile.TemporaryDirectory(prefix="ucrawl-web-test-") as user_data_root:
        env["UCRAWL_USER_DATA_ROOT"] = user_data_root
        stdout_path = Path(user_data_root) / "uvicorn.stdout.log"
        stderr_path = Path(user_data_root) / "uvicorn.stderr.log"
        stdout_handle = stdout_path.open("wb")
        stderr_handle = stderr_path.open("wb")
        proc = subprocess.Popen(
            cmd,
            cwd=str(_PROJECT_ROOT),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
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
                stderr_handle.flush()
                server_output.append(stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:])
            except Exception:
                pass
            proc.terminate()
            stdout_handle.close()
            stderr_handle.close()
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
            stdout_handle.close()
            stderr_handle.close()

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
        self.assertIn("document.addEventListener(\"fullscreenchange\"", bundle)

    def test_index_html_required_js_functions(self):
        """所有 onclick/on... 引用的函数必须存在。"""
        import re
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

        self.assertIn('/static/app.css?v=20260705-settings-control-surface', content)
        self.assertIn('/static/i18n.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/media_display.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/platform_limits.js?v=20260701-platform-limits', content)
        self.assertIn('/static/settings_render.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/task_render.js?v=20260705-i18n-surface', content)
        self.assertIn('/static/playback_state.js?v=20260701-playback-state', content)
        self.assertIn('/static/custom_select.js?v=20260707-placement-stable', content)
        self.assertIn('/static/log_display.js?v=20260705-i18n-state-boundary', content)
        self.assertIn('/static/app.js?v=20260709-log-detail-worker', content)

    def test_video_end_autoplays_next_preview(self):
        content = _static_bundle_content()

        self.assertIn("function autoplayNextPreview(", content)
        self.assertIn("setupPlayerEvents(player, id)", content)
        self.assertIn("function setupPlayerEvents(player, sourceId)", content)
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

    def test_web_page_teardown_closes_ws_and_log_worker(self):
        content = _static_bundle_content()

        self.assertIn("let wsReconnectTimer = null;", content)
        self.assertIn("function cleanupPageResources()", content)
        self.assertIn("clearTimeout(wsReconnectTimer);", content)
        self.assertIn("socket.onclose = null;", content)
        self.assertIn("closeLogQueryWorker();", content)
        self.assertIn('window.addEventListener("pagehide", cleanupPageResources', content)
        self.assertIn('window.addEventListener("beforeunload", cleanupPageResources', content)

    def test_settings_snapshot_delta_does_not_rerender_non_settings_page(self):
        content = _static_bundle_content()
        flush_block = content.split("function flushRenderSections()", 1)[1].split(
            "function applyFrontendDelta(delta)",
            1,
        )[0]

        self.assertIn('sections.has("settings_snapshot") && currentPage === "queue"', flush_block)
        self.assertIn('if (sections.has("settings_snapshot")) updatePlaceholder();', flush_block)
        self.assertIn("configureTopCountForSource(source);", content)
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
        static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
        log_center = (static_dir / "log_center.js").read_text(encoding="utf-8")

        self.assertIn("function uiTextWithDetail(label, detail = \"\")", content)
        self.assertIn("function appendUiLog(label, detail = \"\", prefix = \"\")", content)
        for snippet in (
            'appendUiLog("请输入主页链接、分享链接或合集链接")',
            'appendUiLog("未选择有效模式", "", "❌ ")',
            'appendUiLog("前端连接尚未就绪，请稍后重试", "", "⚠️ ")',
            'appendUiLog("正在绑定默认打开方式...")',
            'appendUiLog("文件不存在或已被删除", "", "❌ ")',
            'appendUiLog("播放前校验失败", error.message || error, "❌ ")',
        ):
            self.assertIn(snippet, content)
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
        css = (static_dir / "app.css").read_text(encoding="utf-8")
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
        render_queue_block = content.split("function renderQueue()", 1)[1].split(
            "function queueTitleHtml",
            1,
        )[0]
        render_completed_block = content.split("function renderCompleted()", 1)[1].split(
            "function selectCompleted",
            1,
        )[0]
        render_failed_block = content.split("function renderFailed()", 1)[1].split(
            "function selectFailed",
            1,
        )[0]

        self.assertIn("function normalizeTablePageSize(value)", content)
        self.assertIn('new Worker("/static/list_page_worker.js?v=20260708-list-page-worker")', content)
        self.assertIn('let queuePageSize = normalizeTablePageSize(localStorage.getItem("webui_queue_page_size") || 20);', content)
        self.assertIn('let completedPageSize = normalizeTablePageSize(localStorage.getItem("webui_completed_page_size") || 20);', content)
        self.assertIn('let failedPageSize = normalizeTablePageSize(localStorage.getItem("webui_failed_page_size") || 20);', content)
        self.assertIn("return [20, 50, 100].includes(numeric) ? numeric : 20;", content)
        self.assertIn("queuePageSize = normalizeTablePageSize(value);", content)
        self.assertIn("completedPageSize = normalizeTablePageSize(value);", content)
        self.assertIn("failedPageSize = normalizeTablePageSize(value);", content)
        self.assertIn("function ensureListPageWorker()", content)
        self.assertIn("function submitListPageRequest(pageKey, requestData)", content)
        self.assertIn("function applyListPageResult(result)", content)
        self.assertIn("worker.postMessage(request);", content)
        self.assertIn("applyListPageResult(buildListPageResultSync(request));", content)
        self.assertIn('submitListPageRequest("queue"', render_queue_block)
        self.assertIn('submitListPageRequest("completed"', render_completed_block)
        self.assertIn('submitListPageRequest("failed"', render_failed_block)
        self.assertIn("applyQueuePageResult(result)", render_queue_block)
        self.assertIn("applyCompletedPageResult(result)", render_completed_block)
        self.assertIn("applyFailedPageResult(result)", render_failed_block)
        self.assertIn('syncCustomSelectForSelect(byId("queuePageSize"))', render_queue_block)
        self.assertIn('syncCustomSelectForSelect(byId("completedPageSize"))', render_completed_block)
        self.assertIn('syncCustomSelectForSelect(byId("failedPageSize"))', render_failed_block)
        self.assertIn('byId("queuePrevPage").disabled = queuePage <= 1;', render_queue_block)
        self.assertIn('byId("queueNextPage").disabled = queuePage >= totalPages;', render_queue_block)
        self.assertIn('byId("completedPrevPage").disabled = completedPage <= 1;', render_completed_block)
        self.assertIn('byId("completedNextPage").disabled = completedPage >= totalPages;', render_completed_block)
        self.assertIn('byId("failedPrevPage").disabled = failedPage <= 1;', render_failed_block)
        self.assertIn('byId("failedNextPage").disabled = failedPage >= totalPages;', render_failed_block)
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
        self.assertNotIn("queuePageSize = Math.max(20, Number(value) || 20)", content)
        self.assertNotIn("completedPageSize = Math.max(20, Number(value) || 20)", content)
        self.assertNotIn("allItems.slice(start, start + queuePageSize)", render_queue_block)
        self.assertNotIn("allItems.slice(start, start + completedPageSize)", render_completed_block)

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
        cls._page = _new_webui_page(cls._context)

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
        # local/session storage is cleared by the page init script before each navigation.
        pass

    @classmethod
    def _reset_page(cls):
        try:
            cls._page.close()
        except Exception:
            pass
        cls._page = _new_webui_page(cls._context)

    @classmethod
    def _restart_server(cls):
        try:
            cls._server_ctx.__exit__(None, None, None)
        except Exception:
            pass
        cls._server_ctx = _running_server()
        cls._server_url = cls._server_ctx.__enter__()

    def _goto_ready(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        last_error = None
        for _attempt in range(3):
            try:
                _wait_for_webui_ready(self._page, self._server_url)
                _install_webui_test_helpers(self._page)
                return
            except PlaywrightTimeoutError as exc:
                last_error = exc
                if not _webui_server_responds(self._server_url):
                    self.__class__._restart_server()
                self.__class__._reset_page()
        if last_error is not None:
            raise last_error

    def _wait_for_platform_options(self):
        self._page.wait_for_function(
            "(document.querySelector('#sourceSelect')?.options.length || 0) > 0",
            timeout=5000,
        )

    def test_01_index_loads(self):
        """主页加载成功。"""
        self._goto_ready()
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
        self._goto_ready()
        # 等待 select 可见
        sel = self._page.locator("#sourceSelect")
        self.assertTrue(sel.is_visible(), "sourceSelect should be visible after init")

    def test_06b_source_select_uses_platform_icons_like_gui(self):
        self._goto_ready()
        self._wait_for_platform_options()

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
        self._goto_ready()
        before = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self._page.locator("#themeBtn").click()
        self._page.wait_for_function(
            "expected => document.documentElement.getAttribute('data-theme') === expected",
            arg="light" if before == "dark" else "dark",
            timeout=5000,
        )
        after = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self.assertIn(before, {"light", "dark"})
        self.assertEqual(after, "light" if before == "dark" else "dark")

    def test_07b_appearance_theme_segment_disables_follow_system(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              const appearance = (frontendState.settings_snapshot['\\u5916\\u89c2\\u8bbe\\u7f6e'] ||= {});
              appearance.follow_system = true;
              appearance.theme = 'light';
              currentSettingsGroup = '\\u5916\\u89c2\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const beforeSwitch = document.querySelector('#page-settings [data-setting="follow_system"]');
              const darkButton = document.querySelector('#page-settings .setting-theme-segment-btn[data-value="dark"]');
              darkButton?.click();
              const afterSwitch = document.querySelector('#page-settings [data-setting="follow_system"]');
              const activeButton = document.querySelector('#page-settings .setting-theme-segment-btn.active');
              return {
                hasSegment: Boolean(darkButton),
                beforeFollowSystem: beforeSwitch ? beforeSwitch.checked : null,
                afterFollowSystem: afterSwitch ? afterSwitch.checked : null,
                activeValue: activeButton?.dataset.value || '',
                theme: frontendState.settings_snapshot['\\u5916\\u89c2\\u8bbe\\u7f6e']?.theme || '',
                dataTheme: document.documentElement.dataset.theme || ''
              };
            }
            """
        )

        self.assertTrue(result["hasSegment"])
        self.assertTrue(result["beforeFollowSystem"])
        self.assertFalse(result["afterFollowSystem"])
        self.assertEqual(result["activeValue"], "dark")
        self.assertEqual(result["theme"], "dark")
        self.assertEqual(result["dataTheme"], "dark")

    def test_08_dir_modal_opens(self):
        """点击更改目录按钮应弹出目录弹窗。"""
        self._goto_ready()
        # 找到更改目录按钮
        # HTML 里 onclick="onChangeDirClicked()"
        self._page.evaluate("onChangeDirClicked()")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('dirModal')?.style.display)",
            timeout=5000,
        )
        # 检查 modal.style.display 变成了 flex
        display = self._page.evaluate("document.getElementById('dirModal').style.display")
        self.assertIn(display, ("flex", "block"))

    def test_09_selection_modal_can_be_called(self):
        """showSelectionModal 函数可以调用。"""
        self._goto_ready()
        # 直接调用 showSelectionModal
        self._page.evaluate("showSelectionModal([{title: 'test'},{title: 'demo'}])")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display) && document.getElementById('selectionHeader')?.textContent.includes('2')",
            timeout=5000,
        )
        header = self._page.locator("#selectionHeader").text_content()
        self.assertIn("2", header)

    def test_09b_language_switch_translates_runtime_ui_messages(self):
        self._goto_ready()

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

    def test_09c_language_switch_keeps_log_filter_values_and_labels(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = "en-US";
              window.__setLogFiltersForTest({ level: "全部", time: "近 24 小时", platform: "全部" });
              applyStaticLanguage();
              switchPage("logs");
              renderLogs();
              const ids = ["logLevelFilter", "logTimeFilter", "logPlatformFilter"];
              return Object.fromEntries(ids.map(id => {
                const select = document.getElementById(id);
                const wrapper = select.closest(".custom-select");
                return [id, {
                  value: select.value,
                  label: wrapper.querySelector(".custom-select-label").textContent.trim()
                }];
              }));
            }
            """
        )

        self.assertEqual(result["logLevelFilter"], {"value": "all", "label": "All"})
        self.assertEqual(result["logTimeFilter"], {"value": "24h", "label": "Last 24 hours"})
        self.assertEqual(result["logPlatformFilter"], {"value": "all", "label": "All"})

    def test_09d_log_tabs_keep_gui_counts_after_language_refresh(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.log_items = [
                {
                  id: 'log-crawl',
                  time: new Date().toISOString(),
                  level: 'INFO',
                  source: 'Crawler',
                  trace_id: 'trace-crawl',
                  message_summary: '采集主页解析完成',
                  message: '采集主页解析完成'
                },
                {
                  id: 'log-download',
                  time: new Date().toISOString(),
                  level: 'INFO',
                  source: 'BilibiliDownloader',
                  platform: 'Bilibili',
                  trace_id: 'trace-download',
                  message_summary: '下载分片完成',
                  message: '下载分片完成'
                },
                {
                  id: 'log-error',
                  time: new Date().toISOString(),
                  level: 'ERROR',
                  source: 'GUI',
                  trace_id: 'trace-error',
                  message_summary: '任务异常退出',
                  message: '任务异常退出'
                }
              ];
              window.__setLogFiltersForTest({
                category: 'all',
                level: '全部',
                time: '近 30 分钟',
                platform: '全部',
                trace: '',
                keyword: ''
              });
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-CN"
              };
              document.documentElement.dataset.language = 'zh-CN';
              switchPage('logs');
              renderLogs();
              await window.__waitForLogRender({ rows: 3, total: 3, matched: 3, visible: 3, text: '全部日志 3' });
              const zh = Array.from(document.querySelectorAll('#logTabs [data-log-tab]')).map(button => button.textContent.trim());
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = 'en-US';
              applyStaticLanguage();
              const en = Array.from(document.querySelectorAll('#logTabs [data-log-tab]')).map(button => button.textContent.trim());
              return {
                timeValue: document.getElementById('logTimeFilter').value,
                zh,
                en
              };
            }
            """
        )

        self.assertEqual(result["timeValue"], "30m")
        self.assertIn("全部日志 3", result["zh"])
        self.assertIn("错误日志 1", result["zh"])
        self.assertIn("All logs 3", result["en"])
        self.assertIn("Crawl logs 1", result["en"])
        self.assertIn("Download logs 1", result["en"])
        self.assertIn("System logs 0", result["en"])
        self.assertIn("Performance logs 0", result["en"])
        self.assertIn("Error logs 1", result["en"])

    def test_09da_log_query_uses_worker_even_for_small_batches(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest({ captureLogWorkers: true });
              if (ws) {
                try { ws.close(); } catch (_error) {}
                ws = null;
              }
              frontendState.log_items = Array.from({ length: 12 }, (_, index) => ({
                id: `worker-log-${index}`,
                time: '2026-07-06 03:30:' + String(index % 60).padStart(2, '0'),
                level: index % 10 === 0 ? 'ERROR' : 'INFO',
                source: index % 2 === 0 ? 'BilibiliDownloader' : 'GUI',
                platform: index % 2 === 0 ? 'Bilibili' : '系统',
                trace_id: `trace-${index}`,
                message_summary: index % 2 === 0 ? '下载任务完成' : '系统状态刷新',
                message: index % 2 === 0 ? '下载任务完成' : '系统状态刷新'
              }));
              window.__setLogFiltersForTest({
                category: 'all',
                level: 'all',
                time: 'all',
                platform: 'all',
                trace: '',
                keyword: ''
              });
              switchPage('logs');
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 12, total: 12, matched: 12, visible: 12, timeoutMs: 6000 });
              window.__restoreLogWorkerForTest();
              const counts = (document.getElementById('logTotal').textContent.match(/\d+/g) || []).map(Number);
              return {
                workerCreated: window.__logWorkerUrls.includes('/static/log_query_worker.js?v=20260707-log-worker'),
                pending: false,
                rows: document.querySelectorAll('#logBody tr').length,
                total: counts[0] || 0,
                matched: counts[1] || 0,
                visible: counts[2] || 0,
                allTab: document.querySelector('#logTabs [data-log-tab="all"]')?.textContent.trim() || ''
              };
            }
            """
        )

        self.assertTrue(result["workerCreated"])
        self.assertFalse(result["pending"])
        self.assertEqual(result["rows"], 12)
        self.assertEqual(result["total"], 12)
        self.assertEqual(result["matched"], 12)
        self.assertEqual(result["visible"], 12)
        self.assertIn("12", result["allTab"])

    def test_09e_language_switch_translates_log_values_and_completed_detail_labels(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "en-US"
              };
              document.documentElement.dataset.language = "en-US";
              frontendState.log_items = [{
                id: "log-i18n-a",
                time: "2026-07-05 09:04:22",
                level: "INFO",
                raw_level: "INFO",
                result_type: "info",
                category: "system",
                log_scope: "system",
                event_stage: "step",
                event_stage_display: "步骤",
                event_code: "GUI_日志缓存已刷新",
                source: "GUI",
                source_display: "系统 · GUI",
                source_display_icon_file: "nav_settings.png",
                platform: "系统",
                trace_id: "",
                message_summary: "日志缓存已刷新",
                message: "日志缓存已刷新",
                detail: { description: "日志缓存已刷新", platform: "系统", source: "GUI" },
                stack: ""
              }];
              frontendState.completed_items = [{
                id: "completed-i18n-a",
                title: "demo",
                filename: "demo.mp4",
                save_dir: "D:\\\\Downloads",
                completed_at: "2026-07-05 09:14:13",
                duration: "00:01:00",
                resolution: "1280 x 720",
                size: "1.3 GB",
                format: "MP4"
              }];
              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              switchPage("logs");
              applyStaticLanguage();
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: 'System \\u00b7 GUI' });
              const logText = document.getElementById("page-logs").textContent;
              currentPage = "completed";
              selected.completed = "completed-i18n-a";
              renderCompleted();
              const waitForCompletedText = expectedText => new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const text = document.getElementById("completedDetail").textContent;
                  if (text.includes(expectedText)) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error(`completed detail did not render: ${expectedText}`));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              await waitForCompletedText("Filename");
              const completedText = document.getElementById("completedDetail").textContent;
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-TW"
              };
              document.documentElement.dataset.language = "zh-TW";
              switchPage("logs");
              applyStaticLanguage();
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: '系統 \\u00b7 圖形介面' });
              const twLogText = document.getElementById("page-logs").textContent;
              currentPage = "completed";
              renderCompleted();
              await waitForCompletedText("檔案名稱");
              const twCompletedText = document.getElementById("completedDetail").textContent;
              return { logText, completedText, twLogText, twCompletedText };
            }
            """
        )

        self.assertIn("System · GUI", result["logText"])
        self.assertIn("Log cache refreshed", result["logText"])
        self.assertIn("GUI_LOG_CACHE_REFRESHED", result["logText"])
        self.assertIn("Process", result["logText"])
        self.assertIn("Step", result["logText"])
        self.assertNotIn("日志缓存已刷新", result["logText"])
        for label in ("Filename", "Save path", "Completed at", "Duration", "Resolution", "Size", "Format"):
            self.assertIn(label, result["completedText"])
        self.assertNotIn("文件名", result["completedText"])
        self.assertIn("系統 · 圖形介面", result["twLogText"])
        self.assertIn("日誌快取已刷新", result["twLogText"])
        self.assertIn("圖形介面_日誌快取已刷新", result["twLogText"])
        self.assertNotIn("日志缓存已刷新", result["twLogText"])
        for label in ("檔案名稱", "儲存路徑", "完成時間", "時長", "解析度", "大小", "格式"):
            self.assertIn(label, result["twCompletedText"])

    def test_09f_language_switch_translates_settings_logs_active_and_platforms(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.settings_snapshot = {
                "基础设置": {
                  download_directory: "D:\\\\Downloads",
                  filename_template: "默认",
                  open_after_download: false,
                  default_open_mode: "内置播放器",
                  _options: {
                    filename_template: [{ value: "默认", label: "默认" }],
                    default_open_mode: [{ value: "内置播放器", label: "内置播放器" }, { value: "打开所在目录", label: "打开所在目录" }]
                  }
                },
                "下载设置": {
                  max_concurrent: 3,
                  image_respects_concurrency: true,
                  request_timeout: 60,
                  max_retries: 3,
                  resume_enabled: true,
                  speed_limit_kb: 0,
                  video_only: false,
                  _options: {
                    max_concurrent: [{ value: "3", label: "3（推荐）" }],
                    request_timeout: [{ value: "60", label: "60 秒（推荐）" }],
                    max_retries: [{ value: "3", label: "3（推荐）" }],
                    speed_limit_kb: [{ value: "0", label: "无限制" }]
                  }
                },
                "平台设置": [
                  { id: "douyin", name: "抖音", auth_status: "已认证", default_count: 50, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "50", label: "50 个视频" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理", "直连"], proxy_editable: false },
                  { id: "missav", name: "MissAV", auth_status: "未认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "自定义", proxy_config_key: "proxy", proxy_editable: true, proxy_custom_allowed: true, proxy_custom_active: true, proxy_custom_value: "http://127.0.0.1:7890", proxy_options: ["系统代理", "直连", "自定义"] },
                  { id: "xiaohongshu", name: "小红书", auth_status: "已认证", default_count: 20, count_unit: "notes", count_config_key: "max_notes", count_editable: true, count_options: [{ value: "20", label: "20 篇笔记（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false }
                ],
                "播放设置": {
                  default_player: "内置播放器",
                  remember_position: true,
                  autoplay_next: true,
                  manual_image_switch: true,
                  _options: { default_player: [{ value: "内置播放器", label: "内置播放器" }] }
                },
                "日志设置": {
                  retention_days: 1,
                  ui_log_max_display_count: 300,
                  auto_copy_trace_on_error: true,
                  _options: {
                    retention_days: [{ value: "1", label: "1 天（推荐）" }, { value: "3", label: "3 天" }, { value: "5", label: "5 天" }, { value: "7", label: "7 天" }],
                    ui_log_max_display_count: [{ value: "300", label: "300 条（推荐）" }]
                  }
                },
                "外观设置": { language: "en-US", theme: "light", accent: "red", scale: "100%", font_size: "medium" }
              };
              frontendState.settings_contract = {
                group_order: ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"],
                group_descriptions: {
                  "基础设置": "下载目录、文件命名和打开行为",
                  "下载设置": "并发、超时、重试和下载策略",
                  "平台设置": "认证状态、爬取数量和代理入口",
                  "播放设置": "播放器、断点续播和预览行为",
                  "日志设置": "保留策略、显示上限和错误追踪",
                  "外观设置": "语言、主题、界面缩放和字体"
                },
                group_hints: {
                  "基础设置": "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。",
                  "下载设置": "并发越高不一定越快，建议根据网络和磁盘性能调整。",
                  "日志设置": "UI 显示数量只影响日志中心显示，不影响日志文件本身。"
                }
              };
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              frontendState.active_downloads = [];
              frontendState.log_items = [{
                id: "log-i18n-surface",
                time: "2026-07-05 09:55:36",
                level: "WARN",
                raw_level: "WARN",
                result_type: "warn",
                category: "performance",
                log_scope: "performance",
                event_stage: "performance",
                event_code: "FRONTEND_RENDER_SLOW",
                source: "MainWindow",
                source_display: "系统 · MainWindow",
                source_display_icon_file: "nav_settings.png",
                platform: "系统",
                trace_id: "",
                message_summary: "📂 正在扫描目录: D:\\\\Downloads",
                message: "📂 正在扫描目录: D:\\\\Downloads",
                detail: { description: "说明：应用开始初始化", type: "预警", scope: "性能", stage: "性能", platform: "系统", source: "MainWindow" },
                stack: ""
              }];
              platforms = [
                { id: "missav", name: "MissAV" },
                { id: "douyin", name: "抖音" },
                { id: "xiaohongshu", name: "小红书" },
                { id: "kuaishou", name: "快手" },
                { id: "bilibili", name: "Bilibili" }
              ];
              document.documentElement.dataset.language = "en-US";
              renderSignatures = {};
              applyStaticLanguage();
              renderPlatforms();
              const sourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());

              currentPage = "settings";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "settings"));
              const settingsTexts = {};
              for (const group of ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置"]) {
                currentSettingsGroup = group;
                renderSettings(true);
                settingsTexts[group] = document.getElementById("page-settings").textContent;
              }

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              renderLogs();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: "All logs 1" });
              const logsText = document.getElementById("page-logs").textContent;
              const logPlatformLabel = document.querySelector("#logPlatformFilter").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();

              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const activeText = document.getElementById("page-active").textContent;
              const retryLabel = document.querySelector("#activeMaxRetries").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();

              frontendState.settings_snapshot["外观设置"].language = "zh-CN";
              frontendState.settings_contract.group_descriptions["平台设置"] = "Auth status, crawl quantity, and proxy entry";
              frontendState.settings_snapshot["平台设置"][0].count_options = [{ value: "50", label: "50 videos" }];
              frontendState.settings_snapshot["平台设置"][0].timeout_options = [{ value: "60", label: "60 sec (Recommended)" }];
              frontendState.settings_snapshot["平台设置"][0].proxy_options = [{ value: "系统代理", label: "System proxy" }];
              frontendState.settings_snapshot["日志设置"]._options.retention_days = [{ value: "1", label: "1 day (Recommended)" }];
              frontendState.log_items[0].source_display = "System · MainWindow";
              frontendState.log_items[0].platform = "System";
              frontendState.log_items[0].message_summary = "📂 Scanning folder: D:\\\\Downloads";
              frontendState.log_items[0].message = "Frontend render exceeded the interactive budget; refresh cadence was relaxed";
              frontendState.log_items[0].detail = { description: "Frontend render exceeded the interactive budget; refresh cadence was relaxed", type: "Warning", scope: "Performance", stage: "Performance", platform: "System", source: "MainWindow" };
              document.documentElement.dataset.language = "zh-CN";
              applyStaticLanguage();
              renderPlatforms();
              const zhSourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());

              currentPage = "settings";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "settings"));
              currentSettingsGroup = "平台设置";
              renderSettings(true);
              const zhSettingsText = document.getElementById("page-settings").textContent;

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              window.UcpLogCenter.render();
              await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: "前端渲染超过交互预算" });
              const zhLogsText = document.getElementById("page-logs").textContent;

              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const zhActiveText = document.getElementById("page-active").textContent;
              const zhRetryLabel = document.querySelector("#activeMaxRetries").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();
              return { sourceOptions, settingsTexts, logsText, logPlatformLabel, activeText, retryLabel, zhSourceOptions, zhSettingsText, zhLogsText, zhActiveText, zhRetryLabel };
            }
            """
        )

        joined_settings = "\n".join(result["settingsTexts"].values())
        for expected in (
            "Download folder, filename rules, and open behavior",
            "Concurrency, timeout, retry, and download policy",
            "Player, resume playback, and preview behavior",
            "Retention policy, display limits, and error tracing",
            "Maximum simultaneous downloads",
            "Control the image fast lane",
            "1 day (Recommended)",
            "Custom",
            "Timeout",
            "Douyin",
            "Xiaohongshu",
        ):
            self.assertIn(expected, joined_settings)
        for unexpected in ("下载目录、文件命名", "播放器、断点续播", "保留策略、显示上限", "最大同时下载数", "自定义", "超时"):
            self.assertNotIn(unexpected, joined_settings)

        self.assertIn("Douyin", result["sourceOptions"])
        self.assertIn("Xiaohongshu", result["sourceOptions"])
        self.assertIn("Kuaishou", result["sourceOptions"])
        self.assertEqual(result["logPlatformLabel"], "All")
        self.assertIn("All logs 1", result["logsText"])
        self.assertIn("System · Main window", result["logsText"])
        self.assertIn("Scanning folder: D:\\Downloads", result["logsText"])
        self.assertIn("Warning", result["logsText"])
        self.assertIn("Performance", result["logsText"])
        self.assertIn("Total 1 / matched 1 / showing 1", result["logsText"])
        for unexpected in ("全部日志", "系统 · MainWindow", "正在扫描目录", "预警", "性能", "共 1 条"):
            self.assertNotIn(unexpected, result["logsText"])
        self.assertIn("Queue controls", result["activeText"])
        self.assertIn("Auto retry failures", result["activeText"])
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("No events", result["activeText"])
        self.assertIn("Running: 0 tasks", result["activeText"])
        self.assertEqual(result["retryLabel"], "3 times")
        self.assertIn("抖音", result["zhSourceOptions"])
        self.assertIn("小红书", result["zhSourceOptions"])
        self.assertIn("认证状态、爬取数量和代理入口", result["zhSettingsText"])
        self.assertIn("50 个视频", result["zhSettingsText"])
        self.assertIn("60 秒（推荐）", result["zhSettingsText"])
        self.assertIn("系统代理", result["zhSettingsText"])
        self.assertIn("全部日志 1", result["zhLogsText"])
        self.assertIn("系统 · 主窗口", result["zhLogsText"])
        self.assertIn("正在扫描目录：D:\\Downloads", result["zhLogsText"])
        self.assertIn("前端渲染超过交互预算", result["zhLogsText"])
        self.assertIn("预警", result["zhLogsText"])
        self.assertIn("性能", result["zhLogsText"])
        self.assertIn("共 1 条 / 匹配 1 条 / 当前显示 1 条", result["zhLogsText"])
        self.assertIn("队列控制", result["zhActiveText"])
        self.assertIn("暂无事件", result["zhActiveText"])
        self.assertIn("当前运行：0 个任务", result["zhActiveText"])
        self.assertEqual(result["zhRetryLabel"], "3次")
        for unexpected in ("Douyin", "Xiaohongshu", "Auth status", "50 videos", "System proxy"):
            self.assertNotIn(unexpected, result["zhSettingsText"] + "\n".join(result["zhSourceOptions"]))
        for unexpected in ("All logs", "System · MainWindow", "Scanning folder", "Warning", "Performance", "Total 1 / matched 1 / showing 1"):
            self.assertNotIn(unexpected, result["zhLogsText"])
        for unexpected in ("Queue controls", "No events", "Running: 0 tasks"):
            self.assertNotIn(unexpected, result["zhActiveText"])

    def test_09g_current_page_language_controls_runtime_dialogs_and_dynamic_text(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              frontendState.settings_snapshot["外观设置"] = {
                ...(frontendState.settings_snapshot["外观设置"] || {}),
                language: "zh-CN",
                theme: "light",
                accent: "purple",
                scale: "100%",
                font_size: "medium"
              };
              document.documentElement.dataset.language = "en-US";
              frontendState.active_downloads = [];
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              showFileAssociationModal();
              const modalText = document.getElementById("fileAssociationModal").textContent;
              const activeText = document.getElementById("page-active").textContent;
              const languageBeforeApply = currentLanguage();
              const recLabel = optionLabel("20 videos (Rec.)");
              const runningLabel = translateUiText("当前运行：0 个任务");
              applyAppearance(frontendState.settings_snapshot["外观设置"]);
              const languageAfterApply = currentLanguage();
              cancelFileAssociationModal();
              return { languageBeforeApply, languageAfterApply, modalText, activeText, recLabel, runningLabel };
            }
            """
        )

        self.assertEqual(result["languageBeforeApply"], "en-US")
        self.assertEqual(result["languageAfterApply"], "zh-CN")
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("No events", result["activeText"])
        self.assertIn("Running: 0 tasks", result["activeText"])
        self.assertIn("Bind default app", result["modalText"])
        self.assertIn("Video resources", result["modalText"])
        self.assertIn("Cancel", result["modalText"])
        self.assertIn("Bind", result["modalText"])
        self.assertEqual(result["recLabel"], "20 videos (Recommended)")
        self.assertEqual(result["runningLabel"], "Running: 0 tasks")
        for unexpected in ("当前任务事件", "暂无事件", "当前运行", "绑定默认打开方式", "取消"):
            self.assertNotIn(unexpected, result["activeText"] + result["modalText"])

    def test_09h_runtime_language_update_translates_dropdowns_logs_active_and_dialogs(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              window.__languageActions = [];
              window.frontendAction = (action, payload) => window.__languageActions.push({ action, payload });
              frontendAction = window.frontendAction;
              platforms = [
                { id: "douyin", name: "抖音" },
                { id: "xiaohongshu", name: "小红书" },
                { id: "kuaishou", name: "快手" },
                { id: "missav", name: "MissAV" },
                { id: "bilibili", name: "Bilibili" }
              ];
              frontendState.settings_snapshot = {
                "外观设置": {
                  language: "zh-CN",
                  theme: "light",
                  accent: "purple",
                  scale: "100%",
                  font_size: "medium",
                  _options: {
                    language: [
                      { value: "zh-CN", label: "简体中文（推荐）" },
                      { value: "en-US", label: "English" }
                    ],
                    accent: [{ value: "purple", label: "紫色" }],
                    scale: [{ value: "100%", label: "100%（推荐）" }],
                    font_size: [{ value: "medium", label: "中（推荐）" }],
                    theme: [{ value: "light", label: "浅色" }, { value: "dark", label: "深色" }]
                  }
                },
                "平台设置": [
                  { id: "douyin", name: "抖音", auth_status: "已认证", default_count: 50, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "50", label: "50 个视频" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "xiaohongshu", name: "小红书", auth_status: "已认证", default_count: 20, count_unit: "notes", count_config_key: "max_notes", count_editable: true, count_options: [{ value: "20", label: "20 篇笔记（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "kuaishou", name: "快手", auth_status: "已认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false },
                  { id: "missav", name: "MissAV", auth_status: "未认证", default_count: 20, count_unit: "videos", count_config_key: "max_items", count_editable: true, count_options: [{ value: "20", label: "20 个视频（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "自定义", proxy_config_key: "proxy", proxy_editable: true, proxy_custom_allowed: true, proxy_custom_active: true, proxy_custom_value: "7890", proxy_options: ["系统代理", "直连", "自定义"] },
                  { id: "bilibili", name: "Bilibili", auth_status: "已认证", default_count: 1, count_unit: "pages", count_config_key: "max_pages", count_editable: true, count_options: [{ value: "1", label: "1 页（推荐）" }], default_timeout: 60, timeout_config_key: "timeout", timeout_editable: true, timeout_options: [{ value: "60", label: "60 秒（推荐）" }], proxy: "系统代理", proxy_options: ["系统代理"], proxy_editable: false }
                ]
              };
              frontendState.log_items = [
                {
                  id: "log-runtime-language",
                  time: "2026-07-05 11:33:04",
                  level: "WARN",
                  type: "预警",
                  scope: "性能",
                  stage: "性能",
                  source: "系统 · MainWindow",
                  platform: "系统",
                  trace_id: "-",
                  message_summary: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                  message: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                  detail: {
                    description: "Frontend render exceeded the interactive budget; refresh cadence was relaxed",
                    type: "预警",
                    scope: "性能",
                    stage: "性能",
                    source: "MainWindow",
                    platform: "系统"
                  }
                },
                {
                  id: "log-bilibili-start",
                  time: "2026-07-05 11:33:03",
                  level: "INFO",
                  type: "过程",
                  scope: "采集",
                  stage: "启动",
                  source: "Bilibili · BilibiliSpider",
                  platform: "Bilibili",
                  trace_id: "bilibili_crawl_1",
                  message_summary: "启动 Bilibili 爬虫任务",
                  message: "启动 Bilibili 爬虫任务",
                  detail: { description: "启动 Bilibili 爬虫任务", source: "BilibiliSpider", platform: "Bilibili" }
                },
                {
                  id: "log-bilibili-confirm",
                  time: "2026-07-05 11:33:02",
                  level: "INFO",
                  type: "过程",
                  scope: "系统",
                  stage: "确认",
                  source: "系统 · GUI",
                  platform: "系统",
                  trace_id: "-",
                  message_summary: "用户确认了 45 个任务",
                  message: "用户确认了 45 个任务",
                  detail: { description: "用户确认了 45 个任务", source: "GUI", platform: "系统" }
                },
                {
                  id: "log-bilibili-finish",
                  time: "2026-07-05 11:33:01",
                  level: "INFO",
                  type: "成功",
                  scope: "下载",
                  stage: "完成",
                  source: "Bilibili · Downloader",
                  platform: "Bilibili",
                  trace_id: "bilibili_BV1",
                  message_summary: "下载任务完成",
                  message: "下载任务完成",
                  detail: { description: "下载任务完成", source: "Downloader", platform: "Bilibili" }
                }
              ];
              document.documentElement.dataset.language = "zh-CN";
              renderPlatforms();
              currentPage = "settings";
              currentSettingsGroup = "外观设置";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "settings"));
              renderSettings(true);
              updateSetting("appearance", "language", "en-US");

              const sourceOptions = Array.from(document.querySelectorAll("#sourceSelect option")).map(option => option.textContent.trim());
              currentSettingsGroup = "平台设置";
              renderSettings(true);
              const settingsText = document.getElementById("page-settings").textContent;
              const customProxyPlaceholder = document.querySelector(".proxy-custom")?.getAttribute("placeholder") || "";

              window.__setLogFiltersForTest({ category: "all", level: "全部", time: "全部", platform: "全部", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));
              renderLogs();
              await window.__waitForLogRender({
                rows: 4,
                total: 4,
                matched: 4,
                visible: 4,
                itemId: "log-bilibili-start",
                text: "Started Bilibili crawl task",
              });
              const logsText = document.getElementById("page-logs").textContent;
              const logPlatformButton = document.querySelector("#logPlatformFilter").closest(".custom-select").querySelector(".custom-select-label").textContent.trim();
              const logPlatformOriginal = document.querySelector("#logPlatformFilter option[value='all']").dataset.originalLabel;

              frontendState.completed_items = [{
                id: "completed-pending",
                title: "pending metadata",
                filename: "pending.mp4",
                local_path: "D:/Downloads/pending.mp4",
                completed_at: "2026-07-05 11:32:00",
                completed_at_table: "11:32:00",
                duration: "检测中",
                resolution: "检测中",
                metadata_pending: true,
                size: "1 MB",
                format: "MP4"
              }];
              selected.completed = "completed-pending";
              currentPage = "completed";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "completed"));
              renderCompleted();
              await new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const text = document.getElementById("page-completed").textContent;
                  if (text.includes("Checking")) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error("completed page did not render localized pending metadata"));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              const completedText = document.getElementById("page-completed").textContent;

              frontendState.active_downloads = [{
                id: "active-language",
                title: "demo",
                platform: "Bilibili",
                platform_id: "bilibili",
                progress: 25,
                speed: "1.0 MB/s",
                remaining_time: "00:47",
                chunk_progress: { percent: 25, completed: 25, total: 100 },
                events: [
                  { time: "20:20:48", message: "任务进入 Bilibili 下载器" },
                  { time: "20:20:49", message: "音视频流下载中" },
                  { time: "20:20:50", message: "当前速度：1.0 MB/s，剩余：00:47" }
                ]
              }];
              frontendState.download_options = { auto_retry: true, max_retries: 3, max_concurrent: 3 };
              selected.active = "active-language";
              currentPage = "active";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "active"));
              renderActive();
              const activeText = document.getElementById("page-active").textContent;

              showFileAssociationModal();
              const modalText = document.getElementById("fileAssociationModal").textContent;
              cancelFileAssociationModal();

              return { sourceOptions, settingsText, customProxyPlaceholder, logsText, logPlatformButton, logPlatformOriginal, completedText, activeText, modalText };
            }
            """
        )

        for expected in ("Douyin", "Xiaohongshu", "Kuaishou"):
            self.assertIn(expected, result["sourceOptions"])
            self.assertIn(expected, result["settingsText"])
        self.assertIn("Custom", result["settingsText"])
        self.assertEqual(result["customProxyPlaceholder"], "Port")
        self.assertEqual(result["logPlatformButton"], "All")
        self.assertEqual(result["logPlatformOriginal"], "全部")
        self.assertIn("All logs", result["logsText"])
        self.assertIn("Warning", result["logsText"])
        self.assertIn("Performance", result["logsText"])
        self.assertIn("System", result["logsText"])
        self.assertIn("Started Bilibili crawl task", result["logsText"])
        self.assertIn("User confirmed 45 tasks", result["logsText"])
        self.assertIn("Download task completed", result["logsText"])
        self.assertIn("Checking", result["completedText"])
        self.assertIn("Current task events", result["activeText"])
        self.assertIn("Task entered Bilibili downloader", result["activeText"])
        self.assertIn("Audio/video stream downloading", result["activeText"])
        self.assertIn("Current speed: 1.0 MB/s, remaining: 00:47", result["activeText"])
        self.assertIn("Running: 1 tasks", result["activeText"])
        self.assertIn("Bind default app", result["modalText"])
        self.assertIn("Video resources", result["modalText"])
        for unexpected in (
            "抖音",
            "小红书",
            "快手",
            "自定义",
            "全部日志",
            "全部",
            "预警",
            "性能",
            "系统",
            "启动 Bilibili 爬虫任务",
            "用户确认了 45 个任务",
            "下载任务完成",
            "检测中",
            "暂无事件",
            "当前运行",
            "音视频流下载中",
            "绑定默认打开方式",
        ):
            self.assertNotIn(unexpected, "\n".join(result["sourceOptions"]) + result["settingsText"] + result["logsText"] + result["completedText"] + result["activeText"] + result["modalText"])

    def test_09i_runtime_log_translation_handles_raw_english_sources(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              document.documentElement.dataset.language = "zh-CN";
              const cn = [
                window.UcpLogI18n.translateRuntimeLogText("fetch video detail"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili route: direct BV video"),
                window.UcpLogI18n.translateRuntimeLogText("Download task has been queued"),
                window.UcpLogI18n.translateRuntimeLogText("Released download concurrency slot"),
                window.UcpLogI18n.translateRuntimeLogText("Frontend render exceeded the interactive budget; refresh cadence was relaxed"),
                window.UcpLogI18n.translateRuntimeLogText("Download completed: 小伙拉货挣到钱了"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili stream request established"),
                window.UcpLogI18n.translateRuntimeLogText("Preparing to merge Bilibili audio/video stream"),
                window.UcpLogI18n.translateRuntimeLogText("Douyin download task submitted to the queue"),
                window.UcpLogI18n.translateRuntimeLogText("Kuaishou video stream captured and submitted to the queue"),
                window.UcpLogI18n.translateRuntimeLogText("MissAV detail page sniff timed out; playlist.m3u8 was not found"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu crawl task finished"),
                window.UcpLogI18n.translateRuntimeLogText("Switched to light theme"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ No videos or images found in this directory"),
                window.UcpLogI18n.translateRuntimeLogText("Found 3 matching users"),
                window.UcpLogI18n.translateRuntimeLogText("System · BaseDownloader"),
                window.UcpLogI18n.translateRuntimeLogText("System · WebSocketRuntime"),
                window.UcpLogI18n.translateRuntimeLogText("System · WebSocketBridge"),
                window.UcpLogI18n.translateRuntimeLogText("System · FrontendLogCache"),
                window.UcpLogI18n.translateRuntimeLogText("System · FailedRecordStore"),
                window.UcpLogI18n.translateRuntimeLogText("System · BiliAPI"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuDownloader"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuSpider"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaoHongShuSpider"),
                window.UcpLogI18n.translateRuntimeLogText("Xiaohongshu · XiaohongshuClient"),
                window.UcpLogI18n.translateRuntimeLogText("ui callback failed"),
                window.UcpLogI18n.translateRuntimeLogText("callback failed"),
                window.UcpLogI18n.translateRuntimeLogText("_on_spider_finished 被调用"),
                window.UcpLogI18n.translateRuntimeLogText("Web event loop is unavailable; deferred frontend delta until a later async flush."),
                window.UcpLogI18n.translateRuntimeLogText("Skipped frontend delta flush because no running event loop is available."),
                window.UcpLogI18n.translateRuntimeLogText("Douyin参数初始化完成"),
                window.UcpLogI18n.translateRuntimeLogText("Douyin parameters updated!"),
                window.UcpLogI18n.translateRuntimeLogText("Config cookie_tiktok is not set; TikTok features may not work properly"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Updating Douyin parameters, please wait..."),
                window.UcpLogI18n.translateRuntimeLogText("Download task completed"),
                window.UcpLogI18n.translateRuntimeLogText("\U0001f50d Resolving link redirect")
              ];
              document.documentElement.dataset.language = "zh-TW";
              const tw = [
                window.UcpLogI18n.translateRuntimeLogText("fetch video detail"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili route: browser scan search"),
                window.UcpLogI18n.translateRuntimeLogText("Dispatched queued task to a download worker"),
                window.UcpLogI18n.translateRuntimeLogText("Download completed: demo.mp4"),
                window.UcpLogI18n.translateRuntimeLogText("Started Douyin task | target: demo"),
                window.UcpLogI18n.translateRuntimeLogText("Preparing Kuaishou video stream download"),
                window.UcpLogI18n.translateRuntimeLogText("Switched to dark theme"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ No videos or images found in this directory"),
                window.UcpLogI18n.translateRuntimeLogText("Found 2 matching users")
              ];
              document.documentElement.dataset.language = "en-US";
              const en = [
                window.UcpLogI18n.translateRuntimeLogText("用户确认了 45 个任务"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili 流请求建立成功"),
                window.UcpLogI18n.translateRuntimeLogText("准备下载 Bilibili 音视频流"),
                window.UcpLogI18n.translateRuntimeLogText("准备合并 Bilibili 音视频流"),
                window.UcpLogI18n.translateRuntimeLogText("Bilibili 下载任务已提交到下载队列"),
                window.UcpLogI18n.translateRuntimeLogText("🎉 全部完成: 成功 45/45 | 失败 0"),
                window.UcpLogI18n.translateRuntimeLogText("启动抖音任务 | 目标: demo"),
                window.UcpLogI18n.translateRuntimeLogText("快手分享链接已解析并提交到下载队列"),
                window.UcpLogI18n.translateRuntimeLogText("MissAV m3u8 嗅探成功并提交下载"),
                window.UcpLogI18n.translateRuntimeLogText("小红书爬虫任务结束"),
                window.UcpLogI18n.translateRuntimeLogText("已切换到浅色主题"),
                window.UcpLogI18n.translateRuntimeLogText("已切换到深色主题"),
                window.UcpLogI18n.translateRuntimeLogText("ℹ️ 该目录下没有找到视频或图片"),
                window.UcpLogI18n.translateRuntimeLogText("找到 3 个匹配用户"),
                window.UcpLogI18n.translateRuntimeLogText("爬虫完成回调已调用"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] 正在更新抖音参数，请稍等..."),
                window.UcpLogI18n.translateRuntimeLogText("配置文件 cookie 参数未登录，数据获取已提前结束"),
                window.UcpLogI18n.translateRuntimeLogText("配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用"),
                window.UcpLogI18n.translateRuntimeLogText("⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Douyin参数初始化完成"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] Douyin参数更新完毕!"),
                window.UcpLogI18n.translateRuntimeLogText("[INFO] 抖音参数更新完毕！"),
                window.UcpLogI18n.translateRuntimeLogText("TikTok 参数更新完毕！"),
                window.UcpLogI18n.translateRuntimeLogText("✅️ 下载完成: emoji.mp4"),
                window.UcpLogI18n.translateRuntimeLogText("下载完成: demo.mp4")
              ];
              return { cn, tw, en };
            }
            """
        )

        self.assertEqual(
            result["cn"],
            [
                "获取视频详情",
                "Bilibili 路由：直接 BV 视频",
                "下载任务已入队",
                "已释放下载并发槽位",
                "前端渲染超过交互预算，已降低刷新频率",
                "下载完成：小伙拉货挣到钱了",
                "Bilibili 流请求建立成功",
                "准备合并 Bilibili 音视频流",
                "抖音下载任务已提交到下载队列",
                "快手视频流已捕获并提交到下载队列",
                "MissAV 详情页嗅探超时，未发现 playlist.m3u8",
                "小红书爬虫任务结束",
                "已切换到浅色主题",
                "ℹ️ 该目录下没有找到视频或图片",
                "找到 3 个匹配用户",
                "系统 · 基础下载器",
                "系统 · WebSocket 运行时",
                "系统 · WebSocket 桥接器",
                "系统 · 前端日志缓存",
                "系统 · 失败记录存储",
                "系统 · Bilibili 接口",
                "小红书 · 小红书下载器",
                "小红书 · 小红书爬虫",
                "小红书 · 小红书爬虫",
                "小红书 · 小红书客户端",
                "UI 回调失败",
                "回调失败",
                "爬虫完成回调已调用",
                "Web 事件循环不可用，已延后前端增量刷新",
                "没有可用事件循环，已跳过前端增量刷新",
                "Douyin 参数初始化完成",
                "抖音参数更新完毕！",
                "配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                "[INFO] 正在更新抖音参数，请稍等...",
                "下载任务完成",
                "\U0001f50d 正在解析链接重定向",
            ],
        )
        self.assertEqual(
            result["tw"],
            [
                "取得影片詳情",
                "Bilibili 路由：瀏覽器掃描 search",
                "已將排隊任務分發給下載執行緒",
                "下載完成：demo.mp4",
                "啟動抖音任務 | 目標：demo",
                "準備下載快手影片串流",
                "已切換到深色主題",
                "ℹ️ 該目錄下沒有找到影片或圖片",
                "找到 2 個匹配使用者",
            ],
        )
        self.assertEqual(
            result["en"],
            [
                "User confirmed 45 tasks",
                "Bilibili stream request established",
                "Preparing Bilibili audio/video stream download",
                "Preparing to merge Bilibili audio/video stream",
                "Bilibili download task submitted to the queue",
                "🎉 All completed: success 45/45 | failed 0",
                "Started Douyin task | target: demo",
                "Kuaishou share link parsed and submitted to the queue",
                "MissAV m3u8 sniffed successfully and submitted for download",
                "Xiaohongshu crawl task finished",
                "Switched to light theme",
                "Switched to dark theme",
                "ℹ️ No videos or images found in this directory",
                "Found 3 matching users",
                "_on_spider_finished was called",
                "[INFO] Updating Douyin parameters, please wait...",
                "Config cookie is not logged in; data fetching ended early",
                "Config cookie is not set; Douyin features may not work properly",
                "⚠️ Config cookie_tiktok is not set; TikTok features may not work properly",
                "[INFO] Douyin parameters initialized",
                "[INFO] Douyin parameters updated!",
                "[INFO] Douyin parameters updated!",
                "TikTok parameters updated!",
                "✅️ Download completed: emoji.mp4",
                "Download completed: demo.mp4",
            ],
        )

    def test_09ia_log_table_localizes_mixed_runtime_summaries_after_language_switch(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.log_items = [
                {
                  id: "web-log-douyin-init",
                  time: "2026-07-08 13:28:01",
                  level: "INFO",
                  source: "GUI",
                  platform: "系统",
                  trace_id: "dy_i18n_1",
                  message_summary: "[INFO] Douyin参数初始化完成",
                  message: "[INFO] Douyin参数初始化完成"
                },
                {
                  id: "web-log-cookie",
                  time: "2026-07-08 13:28:02",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_2",
                  message_summary: "配置文件 cookie 参数未登录，数据获取已提前结束",
                  message: "配置文件 cookie 参数未登录，数据获取已提前结束"
                },
                {
                  id: "web-log-cookie-tiktok",
                  time: "2026-07-08 13:28:03",
                  level: "WARN",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_3",
                  message_summary: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                  message: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用",
                  detail: { description: "⚠️ 配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用" }
                },
                {
                  id: "web-log-completed-cn",
                  time: "2026-07-08 13:28:04",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_4",
                  message_summary: "下载完成: demo.mp4",
                  message: "下载完成: demo.mp4"
                },
                {
                  id: "web-log-completed-emoji-cn",
                  time: "2026-07-08 13:28:05",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_5",
                  message_summary: "✅️ 下载完成: emoji.mp4",
                  message: "✅️ 下载完成: emoji.mp4",
                  detail: { description: "✅️ 下载完成: emoji.mp4" }
                },
                {
                  id: "web-log-douyin-updated",
                  time: "2026-07-08 13:28:06",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_6",
                  message_summary: "[INFO] Douyin参数更新完毕!",
                  message: "[INFO] Douyin参数更新完毕!"
                },
                {
                  id: "web-log-updating-en",
                  time: "2026-07-08 13:28:07",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_7",
                  message_summary: "[INFO] Updating Douyin parameters, please wait...",
                  message: "[INFO] Updating Douyin parameters, please wait..."
                },
                {
                  id: "web-log-task-en",
                  time: "2026-07-08 13:28:08",
                  level: "INFO",
                  source: "BaseDownloader",
                  platform: "Douyin",
                  trace_id: "dy_i18n_8",
                  message_summary: "Download task completed",
                  message: "Download task completed"
                },
                {
                  id: "web-log-redirect-en",
                  time: "2026-07-08 13:28:09",
                  level: "INFO",
                  source: "DouyinSpider",
                  platform: "Douyin",
                  trace_id: "dy_i18n_9",
                  message_summary: "\U0001f50d Resolving link redirect",
                  message: "\U0001f50d Resolving link redirect"
                }
              ];
              window.__setLogFiltersForTest({ category: "all", level: "all", time: "all", platform: "all", trace: "", keyword: "" });
              currentPage = "logs";
              document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.dataset.page === "logs"));

              document.documentElement.dataset.language = "en-US";
              renderLogs();
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, text: "[INFO] Douyin parameters initialized" });
              const enText = document.getElementById("page-logs").textContent;
              selectLog("web-log-cookie-tiktok");
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, selectedId: "web-log-cookie-tiktok", text: "Config cookie_tiktok is not set; TikTok features may not work properly" });
              const enDetailText = document.getElementById("logDetail").textContent;
              const enDetailJson = document.querySelector("#logDetail .log-detail-readable")?.dataset?.json || "";

              document.documentElement.dataset.language = "zh-CN";
              renderLogs();
              await window.__waitForLogRender({ rows: 9, total: 9, matched: 9, visible: 9, text: "\U0001f50d 正在解析链接重定向" });
              const zhText = document.getElementById("page-logs").textContent;
              return { enText, enDetailText, enDetailJson, zhText };
            }
            """
        )

        self.assertIn("[INFO] Douyin parameters initialized", result["enText"])
        self.assertIn("Config cookie is not logged in; data fetching ended early", result["enText"])
        self.assertIn("⚠️ Config cookie_tiktok is not set; TikTok features may not work properly", result["enText"])
        self.assertIn("Download completed: demo.mp4", result["enText"])
        self.assertIn("✅️ Download completed: emoji.mp4", result["enText"])
        self.assertIn("[INFO] Douyin parameters updated!", result["enText"])
        self.assertNotIn("Douyin参数初始化完成", result["enText"])
        self.assertNotIn("Douyin参数更新完毕", result["enText"])
        self.assertNotIn("配置文件 cookie 参数未登录", result["enText"])
        self.assertNotIn("配置文件 cookie_tiktok 参数未设置", result["enText"])
        self.assertIn("⚠️ Config cookie_tiktok is not set; TikTok features may not work properly", result["enDetailText"])
        self.assertIn("Config cookie_tiktok is not set; TikTok features may not work properly", result["enDetailJson"])
        self.assertNotIn("配置文件 cookie_tiktok 参数未设置", result["enDetailJson"])
        self.assertIn("[INFO] 正在更新抖音参数，请稍等...", result["zhText"])
        self.assertIn("下载任务完成", result["zhText"])
        self.assertIn("\U0001f50d 正在解析链接重定向", result["zhText"])
        self.assertNotIn("Updating Douyin parameters", result["zhText"])
        self.assertNotIn("Download task completed", result["zhText"])

    def test_09j_completed_pending_metadata_fallback_respects_language(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const pendingText = String.fromCharCode(0x68c0, 0x6d4b, 0x4e2d);
              const originalMediaDisplay = window.UcpMediaDisplay;
              const taskRenderScript = await fetch("/static/task_render.js").then(response => response.text());
              document.documentElement.dataset.language = "en-US";
              const frame = document.createElement("iframe");
              document.body.appendChild(frame);
              try {
                window.UcpMediaDisplay = null;
                frame.contentWindow.eval(taskRenderScript);
                frame.contentWindow.UcpTaskRender.configure({ t: translateUiText });
                return {
                  direct: displayMetadataValue(pendingText, true),
                  emptyPending: displayMetadataValue("", true),
                  rowHtml: frame.contentWindow.UcpTaskRender.completedRow({
                    id: "pending-row",
                    title: "demo",
                    completed_at_table: "07-05 22:44",
                    duration: pendingText,
                    metadata_pending: true,
                    format: "MP4"
                  }, "")
                };
              } finally {
                window.UcpMediaDisplay = originalMediaDisplay;
                frame.remove();
              }
            }
            """
        )

        self.assertEqual(result["direct"], "Checking")
        self.assertEqual(result["emptyPending"], "Checking")
        self.assertIn("Checking", result["rowHtml"])
        self.assertNotIn("检测中", result["rowHtml"])

    def test_10_fullscreen_toggle(self):
        """toggleFullscreen 应在 body 上加 is-fullscreen 类。"""
        self._goto_ready()
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
        self.assertTrue(result["called"])
        self.assertFalse(result["bodyFullscreen"])

    def test_11_esc_closes_modals(self):
        """Esc 键应关闭弹窗。"""
        self._goto_ready()
        # 打开 selection modal
        self._page.evaluate("showSelectionModal([{title: 'x'}])")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        # 按 Esc
        self._page.keyboard.press("Escape")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        # modal 应隐藏
        display = self._page.evaluate("document.getElementById('selectionModal').style.display")
        self.assertIn(display, ("none", ""), f"selectionModal should be hidden, got display={display!r}")

    def test_11b_enter_confirms_selection_modal(self):
        self._goto_ready()
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
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display)",
            timeout=5000,
        )
        self._page.evaluate("document.querySelector('#selectionBody input').focus()")

        self._page.keyboard.press("Enter")
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('selectionModal')?.style.display) && window.__selectionShortcutMessages?.length === 1",
            timeout=5000,
        )

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
        self._goto_ready()

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
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('fileAssociationModal')?.style.display)",
            timeout=5000,
        )
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
        self._page.wait_for_function(
            "() => ['', 'none'].includes(document.getElementById('fileAssociationModal')?.style.display) && window.__associationActions?.length === 1",
            timeout=5000,
        )

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
        self._goto_ready()

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
        self._goto_ready()

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
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              frontendState.active_downloads = [
                { id: 'active-a', title: 'Active A', platform: 'Bilibili', platform_id: 'bilibili', progress: 12, speed: '1 MB/s' }
              ];
              selected.active = 'missing-active';
              renderActive();

              frontendState.completed_items = Array.from({ length: 21 }, (_, index) => {
                const number = index + 1;
                return {
                  id: `completed-${number}`,
                  title: `Completed ${number}`,
                  filename: `completed-${number}.mp4`,
                  completed_at: `2026-07-04 06:${String(number).padStart(2, '0')}:00`,
                  completed_at_table: `07-04 06:${String(number).padStart(2, '0')}`,
                  format: 'MP4'
                };
              });
              completedPageSize = 20;
              completedPage = 2;
              selected.completed = 'missing-completed';
              renderCompleted();
              const waitForSelectedRow = (selector, expectedId, selectedGetter, label) => new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const selectedRow = document.querySelector(`${selector} tr.selected`);
                  if (selectedGetter() === expectedId && selectedRow && selectedRow.dataset.id === expectedId) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error(`${label} page worker did not render the selected row`));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              await waitForSelectedRow('#completedBody', 'completed-21', () => selected.completed, 'completed');

              frontendState.failed_items = [
                { id: 'failed-a', title: 'Failed A', failed_at: '2026-07-04 06:03:00', failed_at_table: '07-04 06:03', reason: '403', reason_label: '链接失败', platform: 'Bilibili', platform_id: 'bilibili', status_label: '失败' }
              ];
              selected.failed = 'missing-failed';
              renderFailed();
              await waitForSelectedRow('#failedBody', 'failed-a', () => selected.failed, 'failed');

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
        self.assertEqual(result["completedSelected"], "completed-21")
        self.assertEqual(result["completedRows"], ["completed-21"])
        self.assertIn("completed-21.mp4", result["completedDetail"])
        self.assertEqual(result["failedSelected"], "failed-a")
        self.assertEqual(result["failedRows"], ["failed-a"])
        self.assertIn("Failed A", result["failedDetail"])
        self.assertEqual(result["toolSelected"], "tool-a")
        self.assertEqual(len(result["toolCards"]), 1)
        self.assertIn("Tool A", result["toolCards"][0])
        self.assertIn("Tool A", result["toolDetail"])

    def test_11g_settings_nav_icons_load_from_backend_route(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              currentSettingsGroup = '基础设置';
              switchPage('settings');
              renderSettings(true);
              const images = Array.from(document.querySelectorAll('#page-settings .settings-nav-btn img, #page-settings .settings-detail-icon img'));
              await Promise.all(images.map(img => {
                if (img.complete && img.naturalWidth > 0) return Promise.resolve();
                return new Promise((resolve, reject) => {
                  img.addEventListener('load', resolve, { once: true });
                  img.addEventListener('error', () => reject(new Error(img.src)), { once: true });
                });
              }));
              return {
                nav: Array.from(document.querySelectorAll('#page-settings .settings-nav-btn')).map(button => ({
                  label: button.querySelector('span')?.textContent.trim(),
                  src: button.querySelector('img')?.getAttribute('src'),
                  loaded: (button.querySelector('img')?.naturalWidth || 0) > 0
                })),
                detail: {
                  src: document.querySelector('#page-settings .settings-detail-icon img')?.getAttribute('src'),
                  loaded: (document.querySelector('#page-settings .settings-detail-icon img')?.naturalWidth || 0) > 0
                }
              };
            }
            """
        )

        self.assertEqual([row["label"] for row in result["nav"]], ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"])
        self.assertTrue(all(row["src"].startswith("/ui-icon/") for row in result["nav"]))
        self.assertTrue(all(row["loaded"] for row in result["nav"]))
        self.assertTrue(result["detail"]["src"].startswith("/ui-icon/"))
        self.assertTrue(result["detail"]["loaded"])

    def test_11h_platform_custom_proxy_stays_inside_settings_panel(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              __STABLE_PLATFORM_SETTINGS__
              currentSettingsGroup = '\\u5e73\\u53f0\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const proxySelect = Array.from(document.querySelectorAll('#page-settings select.platform-proxy'))
                .find(select => !select.disabled && Array.from(select.options).some(option => option.value === '\\u81ea\\u5b9a\\u4e49'));
              if (proxySelect) {
                const customOption = Array.from(proxySelect.options).find(option => option.value === '\\u81ea\\u5b9a\\u4e49');
                proxySelect.value = customOption.value;
                proxySelect.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const panel = document.querySelector('#page-settings .settings-detail-panel');
              const row = document.querySelector('#page-settings .setting-platform.has-proxy-custom');
              const input = row?.querySelector('.proxy-custom.active');
              const proxyControl = row?.querySelector('.custom-select.platform-proxy') || row?.querySelector('select.platform-proxy');
              const panelRect = panel?.getBoundingClientRect();
              const rowRect = row?.getBoundingClientRect();
              const inputRect = input?.getBoundingClientRect();
              const proxyRect = proxyControl?.getBoundingClientRect();
              const gap = inputRect && proxyRect ? Math.round(inputRect.left - proxyRect.right) : null;
              const inputWidthRatio = inputRect && proxyRect
                ? inputRect.width / Math.max(1, inputRect.width + proxyRect.width)
                : 0;
              const inputTopInset = inputRect && rowRect ? inputRect.top - rowRect.top : null;
              const inputBottomInset = inputRect && rowRect ? rowRect.bottom - inputRect.bottom : null;
              return {
                hasInput: Boolean(input),
                documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                rowOverflow: rowRect && panelRect ? rowRect.right - panelRect.right : null,
                inputOverflow: inputRect && panelRect ? inputRect.right - panelRect.right : null,
                inputWidth: inputRect ? inputRect.width : 0,
                proxyWidth: proxyRect ? proxyRect.width : 0,
                gap,
                inputWidthRatio,
                inputTopInset,
                inputBottomInset,
                inputHeightDelta: inputRect && proxyRect ? Math.abs(inputRect.height - proxyRect.height) : null,
                inputSameRow: inputRect && proxyRect
                  ? Math.abs((inputRect.top + inputRect.height / 2) - (proxyRect.top + proxyRect.height / 2)) <= 4
                  : false
              };
            }
            """.replace("__STABLE_PLATFORM_SETTINGS__", _stable_platform_settings_snapshot_js())
        )

        self.assertTrue(result["hasInput"])
        self.assertLessEqual(result["documentOverflow"], 1)
        self.assertLessEqual(result["rowOverflow"], 1)
        self.assertLessEqual(result["inputOverflow"], 1)
        self.assertGreaterEqual(result["proxyWidth"], 72)
        self.assertGreaterEqual(result["inputWidth"], 86)
        self.assertGreaterEqual(result["inputWidthRatio"], 0.45)
        self.assertLessEqual(result["inputWidthRatio"], 0.62)
        self.assertGreaterEqual(result["gap"], 7)
        self.assertGreaterEqual(result["inputTopInset"], 1)
        self.assertGreaterEqual(result["inputBottomInset"], 1)
        self.assertLessEqual(result["inputHeightDelta"], 1)
        self.assertTrue(result["inputSameRow"])

    def test_11ha_settings_card_slicing_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u57fa\\u7840\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const body = document.querySelector('#page-settings .settings-detail-body');
              const hint = document.querySelector('#page-settings .settings-hint-card');
              const row = document.querySelector('#page-settings .setting-row');
              const platformBefore = body?.getBoundingClientRect().width || 0;
              const styles = body ? getComputedStyle(body) : null;
              const rowStyles = row ? getComputedStyle(row) : null;
              const hintStyles = hint ? getComputedStyle(hint) : null;
              const basicMetrics = {
                bodyGap: styles?.gap || '',
                bodyPaddingLeft: styles?.paddingLeft || '',
                bodyRadius: styles?.borderRadius || '',
                rowMinHeight: rowStyles?.minHeight || '',
                rowPaddingTop: rowStyles?.paddingTop || '',
                rowRadius: rowStyles?.borderRadius || '',
                hintHeight: hint?.getBoundingClientRect().height || 0,
                hintRadius: hintStyles?.borderRadius || '',
                bodyHintSameWidth: body && hint
                  ? Math.abs(body.getBoundingClientRect().width - hint.getBoundingClientRect().width)
                  : 999,
                wideSettings: Array.from(document.querySelectorAll('#page-settings .setting-wide-control [data-setting]'))
                  .map(node => node.dataset.setting),
                platformBefore
              };
              currentSettingsGroup = '\\u5e73\\u53f0\\u8bbe\\u7f6e';
              renderSettings(true);
              const platformBody = document.querySelector('#page-settings .settings-platform-body');
              const panel = document.querySelector('#page-settings .settings-detail-panel');
              return {
                ...basicMetrics,
                platformBodyWidth: platformBody?.getBoundingClientRect().width || 0,
                panelInnerWidth: panel
                  ? panel.getBoundingClientRect().width
                    - parseFloat(getComputedStyle(panel).paddingLeft)
                    - parseFloat(getComputedStyle(panel).paddingRight)
                  : 0
              };
            }
            """
        )

        self.assertEqual(result["bodyGap"], "7px")
        self.assertEqual(result["bodyPaddingLeft"], "10px")
        self.assertEqual(result["bodyRadius"], "12px")
        self.assertEqual(result["rowMinHeight"], "60px")
        self.assertEqual(result["rowPaddingTop"], "8px")
        self.assertEqual(result["rowRadius"], "9px")
        self.assertAlmostEqual(result["hintHeight"], 40, delta=1)
        self.assertEqual(result["hintRadius"], "9px")
        self.assertLessEqual(result["bodyHintSameWidth"], 1)
        self.assertIn("download_directory", result["wideSettings"])
        self.assertIn("filename_template", result["wideSettings"])
        self.assertIn("default_open_mode", result["wideSettings"])
        self.assertGreater(result["platformBodyWidth"], result["platformBefore"])
        self.assertLessEqual(abs(result["platformBodyWidth"] - result["panelInnerWidth"]), 2)

    def test_11hb_settings_controls_expose_backend_setting_keys(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              __STABLE_PLATFORM_SETTINGS__
              const groups = {
                basic: '\\u57fa\\u7840\\u8bbe\\u7f6e',
                download: '\\u4e0b\\u8f7d\\u8bbe\\u7f6e',
                platform: '\\u5e73\\u53f0\\u8bbe\\u7f6e',
                playback: '\\u64ad\\u653e\\u8bbe\\u7f6e',
                logging: '\\u65e5\\u5fd7\\u8bbe\\u7f6e',
                appearance: '\\u5916\\u89c2\\u8bbe\\u7f6e'
              };
              const collected = {};
              switchPage('settings');
              for (const [name, group] of Object.entries(groups)) {
                currentSettingsGroup = group;
                renderSettings(true);
                collected[name] = Array.from(new Set(
                  Array.from(document.querySelectorAll('#page-settings [data-setting]'))
                    .map(node => node.dataset.setting)
                    .filter(Boolean)
                )).sort();
              }
              return collected;
            }
            """.replace("__STABLE_PLATFORM_SETTINGS__", _stable_platform_settings_snapshot_js())
        )

        expected = {
            "basic": {
                "download_directory",
                "filename_template",
                "open_after_download",
                "show_browser_window",
                "default_open_mode",
            },
            "download": {
                "max_concurrent",
                "image_respects_concurrency",
                "request_timeout",
                "max_retries",
                "resume_enabled",
                "speed_limit_kb",
                "video_only",
            },
            "platform": {"max_items", "max_pages", "timeout", "proxy_app", "proxy_url"},
            "playback": {
                "default_player",
                "remember_position",
                "autoplay_next",
                "image_auto_advance_interval_seconds",
                "manual_image_switch",
            },
            "logging": {
                "retention_days",
                "failed_record_retention_days",
                "ui_log_max_display_count",
                "auto_copy_trace_on_error",
            },
            "appearance": {"language", "follow_system", "theme", "accent", "scale", "font_size"},
        }
        for group, keys in expected.items():
            self.assertTrue(keys.issubset(set(result[group])), (group, result[group]))

    def test_11i_default_open_mode_row_keeps_select_readable(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u57fa\\u7840\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const defaultOpen = document.querySelector('#page-settings [data-setting="default_open_mode"]');
              const cluster = defaultOpen?.closest('.setting-control-cluster');
              const selectBox = defaultOpen?.closest('.custom-select') || defaultOpen;
              const action = cluster?.querySelector('.setting-action');
              const selectRect = selectBox?.getBoundingClientRect();
              const actionRect = action?.getBoundingClientRect();
                return {
                hasCluster: Boolean(cluster),
                selectWidth: selectRect ? selectRect.width : 0,
                actionWidth: actionRect ? actionRect.width : 0,
                actionText: action?.textContent?.trim() || '',
                actionTitle: action?.getAttribute('title') || '',
                actionAria: action?.getAttribute('aria-label') || ''
              };
            }
            """
        )

        self.assertTrue(result["hasCluster"])
        self.assertGreaterEqual(result["selectWidth"], 140)
        self.assertLessEqual(result["actionWidth"], 104)
        self.assertIn("绑定默认打开方式", result["actionText"])
        self.assertIn("默认打开方式", result["actionTitle"])
        self.assertEqual(result["actionTitle"], result["actionAria"])

    def test_11ia_settings_custom_select_selected_option_keeps_theme_contrast(self):
        self._goto_ready()

        samples = self._page.evaluate(
            """
            async () => {
              const accents = ["blue", "green", "purple", "orange", "red"];
              const themes = ["light", "dark"];
              const waitFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve()));
              const rgb = value => {
                const raw = String(value || "");
                const nums = raw.match(/[\\d.]+/g);
                if (!nums || nums.length < 3) return null;
                if (raw.startsWith("color(")) {
                  return nums.slice(0, 3).map(Number).map(component => component <= 1 ? component * 255 : component);
                }
                return nums.slice(0, 3).map(Number);
              };
              const luminance = color => {
                if (!color) return 0;
                const channels = color.map(component => {
                  const normalized = component / 255;
                  return normalized <= 0.03928
                    ? normalized / 12.92
                    : Math.pow((normalized + 0.055) / 1.055, 2.4);
                });
                return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
              };
              const contrast = (front, back) => {
                const a = luminance(front);
                const b = luminance(back);
                const light = Math.max(a, b);
                const dark = Math.min(a, b);
                return (light + 0.05) / (dark + 0.05);
              };
              const sample = async (theme, accent) => {
                applyAppearance({ theme, accent, scale: "100%", font_size: "medium", language: "zh-CN" });
                currentSettingsGroup = "\\u57fa\\u7840\\u8bbe\\u7f6e";
                switchPage("settings");
                renderSettings(true);
                await waitFrame();
                const select = document.querySelector('#page-settings select[data-setting="filename_template"]');
                const wrapper = select?.closest(".custom-select");
                const button = wrapper?.querySelector(".custom-select-button");
                button?.click();
                const deadline = Date.now() + 1200;
                let sampleResult = null;
                while (Date.now() < deadline) {
                  await waitFrame();
                  const menu = wrapper?.querySelector(".custom-select-menu");
                  const option = wrapper?.querySelector(".custom-select-option.selected");
                  const label = option?.querySelector(".custom-select-label");
                  const optionStyle = option ? getComputedStyle(option) : null;
                  const labelStyle = label ? getComputedStyle(label) : null;
                  const optionColor = optionStyle?.color || "";
                  const labelColor = labelStyle?.color || "";
                  const backgroundColor = optionStyle?.backgroundColor || "";
                  sampleResult = {
                    theme,
                    accent,
                    hasOption: Boolean(option && label && menu && !menu.hidden),
                    optionColor,
                    labelColor,
                    backgroundColor,
                    contrast: contrast(rgb(labelColor), rgb(backgroundColor)),
                  };
                  if (sampleResult.hasOption && optionColor && labelColor && backgroundColor) break;
                }
                closeCustomSelect(wrapper);
                return {
                  theme,
                  accent,
                  ...(sampleResult || {
                    hasOption: false,
                    optionColor: "",
                    labelColor: "",
                    backgroundColor: "",
                    contrast: 1,
                  }),
                };
              };
              const results = [];
              for (const theme of themes) {
                for (const accent of accents) {
                  results.push(await sample(theme, accent));
                }
              }
              return results;
            }
            """
        )

        for sample in samples:
            self.assertTrue(sample["hasOption"], sample)
            self.assertEqual(sample["labelColor"], sample["optionColor"], sample)
            self.assertGreaterEqual(sample["contrast"], 4.5, sample)

    def test_11j_settings_select_opens_up_near_panel_bottom(self):
        original_viewport = self._page.viewport_size
        self._page.set_viewport_size({"width": 1280, "height": 520})
        try:
            self._goto_ready()
            result = self._page.evaluate(
                """
                async () => {
                  const waitFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
                  const waitUntil = async (predicate, timeoutMs = 1200) => {
                    const deadline = Date.now() + timeoutMs;
                    let value = null;
                    while (Date.now() < deadline) {
                      value = predicate();
                      if (value && value.ready) return value;
                      await waitFrame();
                    }
                    return value || { ready: false };
                  };
                  const geometry = (wrapper, menu) => {
                    const wrapperRect = wrapper?.getBoundingClientRect();
                    const menuRect = menu?.getBoundingClientRect();
                    const opened = Boolean(menu && !menu.hidden);
                    const opensUp = Boolean(wrapper?.classList.contains('open-up'));
                    const menuAboveControl = Boolean(menuRect && wrapperRect && menuRect.bottom <= wrapperRect.top + 1);
                    const menuInsideViewport = Boolean(menuRect && menuRect.top >= 3 && menuRect.bottom <= window.innerHeight - 3);
                    return {
                      ready: opened && opensUp && menuAboveControl && menuInsideViewport,
                      opened,
                      opensUp,
                      menuAboveControl,
                      menuInsideViewport,
                      wrapperTop: wrapperRect ? Math.round(wrapperRect.top) : null,
                      wrapperBottom: wrapperRect ? Math.round(wrapperRect.bottom) : null,
                      menuTop: menuRect ? Math.round(menuRect.top) : null,
                      menuBottom: menuRect ? Math.round(menuRect.bottom) : null,
                      viewportHeight: window.innerHeight,
                    };
                  };
                  currentSettingsGroup = '\\u4e0b\\u8f7d\\u8bbe\\u7f6e';
                  switchPage('settings');
                  renderSettings(true);
                  await waitFrame();
                  const select = document.querySelector('#page-settings select[data-setting="speed_limit_kb"]');
                  const wrapper = select?.closest('.custom-select');
                  const button = wrapper?.querySelector('.custom-select-button');
                  wrapper?.scrollIntoView({ block: 'end', inline: 'nearest' });
                  await waitUntil(() => {
                    const rect = wrapper?.getBoundingClientRect();
                    return { ready: Boolean(rect && window.innerHeight - rect.bottom <= 96) };
                  });
                  button?.click();
                  const menu = wrapper?.querySelector('.custom-select-menu');
                  return await waitUntil(() => geometry(wrapper, menu));
                }
                """
            )
        finally:
            if original_viewport:
                self._page.set_viewport_size(original_viewport)

        self.assertTrue(result["opened"], result)
        self.assertTrue(result["opensUp"], result)
        self.assertTrue(result["menuAboveControl"], result)
        self.assertTrue(result["menuInsideViewport"], result)

    def test_11k_download_settings_order_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u4e0b\\u8f7d\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              return Array.from(document.querySelectorAll('#page-settings .setting-row'))
                .map(row => row.querySelector('[data-setting]')?.dataset.setting || '')
                .filter(Boolean);
            }
            """
        )

        self.assertEqual(
            result,
            [
                "max_concurrent",
                "image_respects_concurrency",
                "request_timeout",
                "max_retries",
                "resume_enabled",
                "speed_limit_kb",
                "video_only",
            ],
        )

    def test_11ka_download_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u4e0b\\u8f7d\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const keys = ['max_retries', 'speed_limit_kb'];
              return Object.fromEntries(keys.map(key => {
                const control = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = control?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["max_retries"]["label"], "重试次数")
        self.assertIn("失败后重试次数", result["max_retries"]["description"])
        self.assertEqual(result["speed_limit_kb"]["label"], "下载速度限制（KB/s）")
        self.assertIn("限制最大下载速度", result["speed_limit_kb"]["description"])

    def test_11kb_log_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u65e5\\u5fd7\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const keys = ['retention_days', 'failed_record_retention_days', 'ui_log_max_display_count'];
              return Object.fromEntries(keys.map(key => {
                const control = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = control?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["retention_days"]["label"], "日志保留天数")
        self.assertIn("初始化时自动清理", result["retention_days"]["description"])
        self.assertEqual(result["failed_record_retention_days"]["label"], "失败记录保留天数")
        self.assertIn("自动清理过期失败记录", result["failed_record_retention_days"]["description"])
        self.assertEqual(result["ui_log_max_display_count"]["label"], "UI日志最大显示数量")
        self.assertIn("限制日志中心展示条数", result["ui_log_max_display_count"]["description"])

    def test_11l_download_directory_browse_button_opens_dir_dialog(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              currentSettingsGroup = '\\u57fa\\u7840\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const row = document.querySelector('#page-settings .setting-download-directory');
              const button = row?.querySelector('.setting-path-browse');
              const icon = button?.querySelector('img');
              button?.click();
              await new Promise(resolve => setTimeout(resolve, 120));
              const modal = document.getElementById('dirModal');
              const result = {
                hasButton: Boolean(button),
                title: button?.getAttribute('title') || '',
                aria: button?.getAttribute('aria-label') || '',
                iconSrc: icon?.getAttribute('src') || '',
                display: modal?.style.display || ''
              };
              if (modal) modal.style.display = 'none';
              return result;
            }
            """
        )

        self.assertTrue(result["hasButton"])
        self.assertIn("选择保存目录", result["title"])
        self.assertEqual(result["title"], result["aria"])
        self.assertIn("action_open_directory.png", result["iconSrc"])
        self.assertEqual(result["display"], "flex")

    def test_11m_playback_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              currentSettingsGroup = '\\u64ad\\u653e\\u8bbe\\u7f6e';
              switchPage('settings');
              renderSettings(true);
              const keys = ['remember_position', 'autoplay_next', 'manual_image_switch'];
              return Object.fromEntries(keys.map(key => {
                const input = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = input?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["remember_position"]["label"], "记住播放进度")
        self.assertIn("下次恢复播放位置", result["remember_position"]["description"])
        self.assertEqual(result["autoplay_next"]["label"], "视频播放完自动下一项")
        self.assertIn("结束后播放下一项", result["autoplay_next"]["description"])
        self.assertEqual(result["manual_image_switch"]["label"], "图片只手动切换")
        self.assertIn("关闭图片自动轮播", result["manual_image_switch"]["description"])

    def test_12_console_no_errors(self):
        """主页加载应无 JS 错误。"""
        errors = []
        self._page.on("pageerror", lambda e: errors.append(str(e)))
        self._page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                      if msg.type == "error" else None)
        self._goto_ready()
        # 过滤已知的非关键错误
        critical_errors = [e for e in errors
                           if "favicon" not in e.lower()
                           and "WebSocket" not in e
                           and "ws" not in e.lower()
                           and "404" not in e]
        self.assertEqual(critical_errors, [], f"JS errors: {critical_errors}")

    def test_13_log_panel_writes(self):
        """appendLog 应在 logPanel 写入内容。"""
        self._goto_ready()
        timestamp = self._page.evaluate("formatLocalDateTime(new Date(2026, 6, 4, 6, 24, 9))")
        self.assertEqual(timestamp, "2026-07-04 06:24:09")
        self._page.evaluate("appendLog('test marker 12345')")
        content = self._page.locator("#logPanel").text_content()
        self.assertIn("test marker 12345", content)

    def test_13b_log_center_footer_paginates_like_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              switchPage('logs');
              currentPage = 'logs';
              window.__setLogFiltersForTest({ time: '全部' });
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
              await window.__waitForLogRender({ rows: 20, total: 25, matched: 25, visible: 20 });
              const firstPageRows = document.querySelectorAll('#logBody tr').length;
              const firstStats = document.getElementById('logTotal').textContent;
              const firstIndicator = document.getElementById('logPageIndicator').textContent;
              const firstPrevDisabled = document.getElementById('logPrevPage').disabled;
              const firstNextDisabled = document.getElementById('logNextPage').disabled;
              setLogPage(1);
              await window.__waitForLogRender({ rows: 5, total: 25, matched: 25, visible: 5 });
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

    def test_13c_log_center_empty_state_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              switchPage('logs');
              currentPage = 'logs';
              window.__setLogFiltersForTest({ category: 'all', level: '全部', time: '全部', platform: '全部', trace: '', keyword: '不会命中的关键字' });
              frontendState.log_items = [{
                id: 'log-empty-a',
                time: '2026-07-04 06:30:00',
                level: 'INFO',
                source: 'GUI',
                trace_id: 'trace-log-empty-a',
                message_summary: '可见日志',
                message: '可见日志',
                detail: '',
                stack: ''
              }];
              renderLogs();
              await window.__waitForLogRender({ rows: 0, total: 1, matched: 0, visible: 0 });
              const empty = document.getElementById('logEmptyState');
              const subtitle = empty.querySelector('.log-empty-subtitle');
              const primaryNode = empty.querySelector('[data-log-empty-primary]');
              const secondaryNode = empty.querySelector('[data-log-empty-secondary]');
              return {
                rowCount: document.querySelectorAll('#logBody tr').length,
                hidden: empty.hidden,
                text: empty.textContent.replace(/\\s+/g, ' ').trim(),
                ariaLabel: subtitle?.getAttribute('aria-label') || '',
                primary: primaryNode?.textContent || '',
                secondary: secondaryNode?.textContent || '',
                primaryTop: primaryNode?.getBoundingClientRect().top || 0,
                secondaryTop: secondaryNode?.getBoundingClientRect().top || 0,
                subtitleDisplay: getComputedStyle(subtitle).display,
                subtitleDirection: getComputedStyle(subtitle).flexDirection,
                stats: document.getElementById('logTotal').textContent
              };
            }
            """
        )

        self.assertEqual(result["rowCount"], 0)
        self.assertFalse(result["hidden"])
        self.assertIn("暂无匹配日志", result["text"])
        self.assertEqual(result["ariaLabel"], "调整筛选条件 或点击「刷新缓冲」重新加载日志")
        self.assertNotIn("调整筛选条件，", result["text"])
        self.assertEqual(result["primary"], "调整筛选条件")
        self.assertEqual(result["secondary"], "或点击「刷新缓冲」重新加载日志")
        self.assertGreater(result["secondaryTop"], result["primaryTop"])
        self.assertEqual(result["subtitleDisplay"], "flex")
        self.assertEqual(result["subtitleDirection"], "column")
        self.assertEqual(result["stats"], "共 1 条 / 匹配 0 条 / 当前显示 0 条")

    def test_13c_log_table_summary_column_stays_visible_at_gui_width(self):
        self._page.set_viewport_size({"width": 1270, "height": 1024})
        try:
            self._goto_ready()

            result = self._page.evaluate(
                """
                async () => {
                  window.__isolateFrontendStateForTest();
                  currentPage = 'logs';
                  window.__setLogFiltersForTest({ category: 'all', level: '全部', time: '全部', platform: '全部', trace: '', keyword: '' });
                  frontendState.log_items = [{
                    id: 'log-layout-a',
                    time: '2026-07-04 22:45:00',
                    level: 'INFO',
                    source: 'GUI',
                    source_display: '系统 · WebUI',
                    source_display_icon_file: 'nav_settings.png',
                    trace_id: 'web_scan_start_trace_20260704',
                    message_summary: 'Web 端开始扫描本地媒体目录（异步）',
                    message: 'Web 端开始扫描本地媒体目录（异步）',
                    detail: '',
                    stack: ''
                  }];
                  switchPage('logs');
                  renderLogs();
                  await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, text: 'Web 端开始扫描本地媒体目录' });
                  const shell = document.querySelector('#page-logs .logs-table-card .table-shell');
                  const shellRect = shell.getBoundingClientRect();
                  const headers = Array.from(document.querySelectorAll('#page-logs thead th')).map(node => node.getBoundingClientRect());
                  const rowCells = Array.from(document.querySelectorAll('#logBody tr:first-child td')).map(node => node.getBoundingClientRect());
                  const grid = document.querySelector('#page-logs .logs-grid');
                  const detail = document.querySelector('#page-logs .logs-right-column');
                  return {
                    shellRight: shellRect.right,
                    headerRight: headers[4].right,
                    cellRight: rowCells[4].right,
                    summaryHeaderWidth: headers[4].width,
                    summaryCellWidth: rowCells[4].width,
                    scrollOverflow: shell.scrollWidth - shell.clientWidth,
                    gridColumns: getComputedStyle(grid).gridTemplateColumns,
                    detailWidth: detail.getBoundingClientRect().width
                  };
                }
                """
            )
        finally:
            self._page.set_viewport_size({"width": 1280, "height": 720})

        self.assertLessEqual(result["headerRight"], result["shellRight"] + 1)
        self.assertLessEqual(result["cellRight"], result["shellRight"] + 1)
        self.assertLessEqual(result["scrollOverflow"], 1)
        self.assertGreaterEqual(result["summaryHeaderWidth"], 82)
        self.assertGreaterEqual(result["summaryCellWidth"], 82)
        self.assertLessEqual(result["detailWidth"], 360)

    def test_13c_log_detail_copy_export_actions_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
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
                switchPage('logs');
                window.__setLogFiltersForTest({ time: '全部' });
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
                window.UcpLogCenter.render();
                await window.__waitForLogRender({ rows: 1, total: 1, matched: 1, visible: 1, selectedId: 'log-detail-a' });
                window.UcpLogCenter.copyDetail();
                window.UcpLogCenter.copyJson();
                window.UcpLogCenter.exportDetail();
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                  selectedLog: document.querySelector('#logBody tr.selected')?.dataset.key || '',
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
        self._goto_ready()
        # 注入测试数据
        self._page.evaluate("""
            switchPage('queue');
            videoOrder = ['a', 'b', 'c'];
            videos = {
                'a': {title: 'Item A', progress: 0, status: 'done'},
                'b': {title: 'Item B', progress: 0, status: 'done'},
                'c': {title: 'Item C', progress: 0, status: 'done'},
            };
            selectedVideoId = null;
            renderQueue();
            document.body.focus();
        """)
        self._page.wait_for_function(
            "() => document.querySelectorAll('#queueBody tr[data-id]').length === 3",
            timeout=5000,
        )
        # 第一次按 ArrowDown → 选中 a
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_function("() => selectedVideoId === 'a'", timeout=5000)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "a")
        # 再按 ArrowDown → 选中 b
        self._page.keyboard.press("ArrowDown")
        self._page.wait_for_function("() => selectedVideoId === 'b'", timeout=5000)
        sel = self._page.evaluate("selectedVideoId")
        self.assertEqual(sel, "b")

    def test_15_delete_key_removes(self):
        """Delete 键应触发删除。"""
        self._goto_ready()
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
        self._page.wait_for_function("() => window._deletedIds?.length === 1", timeout=5000)
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
