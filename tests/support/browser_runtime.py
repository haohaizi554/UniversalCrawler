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

from tests.support.frontend_static_assets import stylesheet_paths_from_index

# 让 web_entry 等可被 import
_TESTS_DIR = Path(__file__).resolve().parents[1]
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
    static_dir = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
    parts = [(static_dir / "index.html").read_text(encoding="utf-8")]
    parts.extend(path.read_text(encoding="utf-8") for path in stylesheet_paths_from_index())
    for name in ("i18n.js", "custom_select.js", "media_display.js", "log_display.js", "log_query_worker.js", "log_detail_worker.js", "platform_limits.js", "settings_render.js", "task_render.js", "playback_state.js", "log_i18n.js", "frontend_runtime.js", "list_pages.js", "log_center.js", "settings_controller.js", "dialog_controller.js", "playback_controller.js", "app.js"):
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
    page.wait_for_function("window.__ucrawlFrontendStateLoaded === true", timeout=5000)

def _install_webui_test_helpers(page) -> None:
    page.evaluate(
        """
        () => {
          window.__isolateFrontendStateForTest = function (options = {}) {
            window.UcpFrontendRuntime.dispose();
            configureListPagesHelpers();
            configureSettingsControllerHelpers();
            configureDialogControllerHelpers();
            configurePlaybackControllerHelpers();
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
              const counts = (document.getElementById("logTotal")?.textContent || "").match(/\\d+/g) || [];
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
    # 用 tests.support.web_test_app 作为 uvicorn 启动入口。
    cmd = [
        sys.executable, "-m", "uvicorn",
        "tests.support.web_test_app:app",
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
            if proc.poll() is not None:
                break
            if _webui_server_responds(url, timeout=1.0):
                break
            time.sleep(0.05)
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
        if proc.poll() is not None:
            try:
                stderr_handle.flush()
                server_output.append(stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:])
            except OSError:
                pass
            stdout_handle.close()
            stderr_handle.close()
            raise RuntimeError(
                f"Server exited before becoming ready on {url}\n"
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


class WebUIBrowserTestBase(unittest.TestCase):
    """Single expensive server and Chromium lifecycle shared by all browser cases."""

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
