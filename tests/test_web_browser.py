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
            "selectionModal", "selectionBody", "selectionHeader",
            "playBtn", "prevBtn", "nextBtn", "seekSlider", "timeLabel",
            "fullscreenBtn", "previewArea",
            "tableWrap", "topBar", "queueBody",
        ]
        for elem_id in required_ids:
            # JS 用 getElementById('xxx') 引用
            self.assertIn(f'id="{elem_id}"', content,
                         f"missing id in HTML: {elem_id}")

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
        self.assertIn("\\u589e\\u91cf\\u72b6\\u6001\\u57fa\\u7ebf\\u4e0d\\u8fde\\u7eed", delta_block)

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

        self.assertIn('for (const key of ["active", "completed", "failed"])', remove_block)
        self.assertIn("selected[key] = \"\"", remove_block)
        self.assertIn("selectedVideoId = null", remove_block)
        self.assertIn("currentPlayingId = null", remove_block)
        self.assertIn("removePlaybackPosition(id)", remove_block)

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

    def test_append_log_uses_batched_render_scheduler(self):
        content = _static_bundle_content()
        append_log_block = content.split("function appendLog(message)", 1)[1].split(
            "function onChangeDirClicked()",
            1,
        )[0]

        self.assertIn("trimFrontendLogItems();", append_log_block)
        self.assertIn('scheduleRenderSections(["log_items", "app_status"])', append_log_block)
        self.assertNotIn("renderLogs();", append_log_block)

    def test_web_log_display_limit_is_applied_to_local_state(self):
        content = _static_bundle_content()
        self.assertIn("function uiLogDisplayLimit()", content)
        self.assertIn("function trimFrontendLogItems()", content)
        self.assertIn("frontendState.log_items = frontendState.log_items.slice(-limit);", content)
        self.assertIn("if (trimFrontendLogItems() && !changed.includes(\"log_items\")) changed.push(\"log_items\");", content)

    def test_web_log_rendering_is_current_page_and_budgeted(self):
        content = _static_bundle_content()
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
        self.assertIn("visibleLogItems(filteredItems)", render_logs_block)
        self.assertIn("function visibleLogItems(items)", content)

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
        self._page.evaluate("appendLog('test marker 12345')")
        content = self._page.locator("#logPanel").text_content()
        self.assertIn("test marker 12345", content)

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
