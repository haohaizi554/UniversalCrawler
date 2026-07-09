# WebUI `app.js` Responsibility Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `app/web/static/app.js` 按业务职责拆为可独立测试、可独立释放资源的静态模块，并把主入口收敛为状态所有权、启动编排、导航和兼容包装。

**Architecture:** 继续使用项目既有的 IIFE + `window.Ucp*` 服务对象，不引入构建工具。每个模块通过 `configure()` 注入共享状态访问器、翻译、DOM 工具和后端动作；`app.js` 保留唯一 `frontendState`，业务模块不得复制整个快照。

**Tech Stack:** 原生 JavaScript、HTML `defer` 脚本、Web Worker、FastAPI 静态资源、Python `unittest`/`pytest`、Playwright 浏览器测试、PyInstaller 静态目录打包。

## Global Constraints

- 不引入 Node.js、打包器、TypeScript 或新的运行时依赖。
- 不修改 GUI、后端接口、worker 消息协议或下载业务算法。
- `/api/frontend/state`、`/api/frontend/delta` 和 WebSocket 语义保持不变。
- `frontendState` 只由 `app.js` 持有；模块通过 `getState()` 读取，通过注入回调请求变更。
- HTML 内联事件所需的旧全局函数保留为薄包装，不重复实现业务逻辑。
- 所有新增脚本使用 `defer`、统一缓存版本 `v=20260710-app-split`，并加入打包与静态资源测试。
- 所有 worker、socket、timer 的释放函数必须幂等。
- 每个迁移任务严格执行 RED-GREEN-REFACTOR，先观察测试因缺少目标实现而失败。
- 不提交当前工作区中与本计划无关的已有改动。

---

## File Structure

### New production files

- `app/web/static/frontend_runtime.js`：快照、delta、WebSocket、渲染调度和页面退出清理。
- `app/web/static/list_pages.js`：四态列表、分页、选中状态协调和 `list_page_worker`。
- `app/web/static/log_i18n.js`：日志纯本地化、结构化字段映射和 worker 翻译提示。
- `app/web/static/log_center.js`：日志查询、分页、详情、复制、导出和两个日志 worker。
- `app/web/static/settings_controller.js`：设置页状态、热更新、代理输入和平台认证刷新。
- `app/web/static/dialog_controller.js`：目录、文件关联和任务选择弹窗。
- `app/web/static/playback_controller.js`：预览、播放、全屏、位置恢复和元数据回填。

### New test file

- `tests/test_web_static_module_boundaries.py`：模块文件、脚本顺序、导出接口、职责归属和 `app.js` 体积守卫。

### Modified files

- `app/web/static/app.js`：逐步删除迁移实现，增加模块配置和兼容包装。
- `app/web/static/index.html`：按依赖顺序加载新增模块。
- `tests/test_web_browser.py`：静态 bundle、缓存版本和运行态模块装载测试。
- `tests/test_unified_frontend_contract.py`：将跨端契约断言改为从拆分 bundle 检查。
- `tests/test_packaging.py`：安装/便携包静态资源标记覆盖新增模块。
- `packaging/README.md`：记录拆分后的静态资源验证清单。
- `app/web/INTERACTION_MAP.md`：更新 WebUI 状态、日志、列表、设置、弹窗和播放模块所有权。

---

### Task 1: Establish Module Shells and Load-Order Contract

**Files:**
- Create: `tests/test_web_static_module_boundaries.py`
- Create: `app/web/static/frontend_runtime.js`
- Create: `app/web/static/list_pages.js`
- Create: `app/web/static/log_i18n.js`
- Create: `app/web/static/log_center.js`
- Create: `app/web/static/settings_controller.js`
- Create: `app/web/static/dialog_controller.js`
- Create: `app/web/static/playback_controller.js`
- Modify: `app/web/static/index.html:8-16`
- Modify: `tests/test_web_browser.py:58-68`
- Modify: `tests/test_unified_frontend_contract.py:42-58`
- Modify: `tests/test_packaging.py:650-670`

**Interfaces:**
- Consumes: Existing classic scripts loaded with `defer`.
- Produces: `window.UcpFrontendRuntime`, `window.UcpListPages`, `window.UcpLogI18n`, `window.UcpLogCenter`, `window.UcpSettingsController`, `window.UcpDialogController`, and `window.UcpPlaybackController`, each with `configure(options = {})` and `dispose()`.

- [ ] **Step 1: Write the failing module and script-order tests**

```python
from __future__ import annotations

import re
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
MODULES = (
    ("log_i18n.js", "UcpLogI18n"),
    ("frontend_runtime.js", "UcpFrontendRuntime"),
    ("list_pages.js", "UcpListPages"),
    ("log_center.js", "UcpLogCenter"),
    ("settings_controller.js", "UcpSettingsController"),
    ("dialog_controller.js", "UcpDialogController"),
    ("playback_controller.js", "UcpPlaybackController"),
)


def test_responsibility_modules_exist_and_export_namespaces() -> None:
    for filename, namespace in MODULES:
        content = (STATIC_DIR / filename).read_text(encoding="utf-8")
        assert f"window.{namespace} = Object.freeze" in content
        assert "function configure(options = {})" in content
        assert "function dispose()" in content


def test_responsibility_modules_load_before_app_in_dependency_order() -> None:
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'<script src="([^"]+)" defer></script>', index)
    expected = [f"/static/{name}?v=20260710-app-split" for name, _ in MODULES]
    assert [source for source in sources if source in expected] == expected
    assert sources.index(expected[-1]) < next(
        index for index, source in enumerate(sources) if source.startswith("/static/app.js?")
    )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py -q`

Expected: FAIL with `FileNotFoundError` for `log_i18n.js`.

- [ ] **Step 3: Add minimal, inert service shells**

Use this exact shell in each new file, replacing the namespace:

```javascript
(function () {
  let dependencies = Object.freeze({});

  function configure(options = {}) {
    dependencies = Object.freeze({ ...options });
    return window.UcpLogI18n;
  }

  function dispose() {
    dependencies = Object.freeze({});
  }

  window.UcpLogI18n = Object.freeze({ configure, dispose });
})();
```

Add the seven scripts to `index.html` in the order declared in `MODULES`, immediately before `app.js`, all using `?v=20260710-app-split`. Extend both Python bundle helpers and the packaging marker tuple with all seven filenames.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_web_browser.py::StaticAssetsTests::test_static_assets_are_cache_busted tests/test_packaging.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the module shell contract**

```powershell
git add -- app/web/static/index.html app/web/static/frontend_runtime.js app/web/static/list_pages.js app/web/static/log_i18n.js app/web/static/log_center.js app/web/static/settings_controller.js app/web/static/dialog_controller.js app/web/static/playback_controller.js tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py tests/test_packaging.py
git commit -m "refactor(web): establish frontend module boundaries"
```

---

### Task 2: Extract Pure Log Localization

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/log_i18n.js`
- Modify: `app/web/static/app.js:1523-2820`
- Modify: `tests/test_unified_frontend_contract.py:4160-4185`

**Interfaces:**
- Consumes: `configure({ currentLanguage, translateUiText, canonicalUiText })`.
- Produces: `translateRuntimeLogText(value)`, `translateStructuredLogText(value)`, `localizeLogEventCode(value)`, `logScopeDisplayText(item)`, `logStageDisplayText(item)`, `logResultNatureText(item)`, and `translationHints(item)` on `window.UcpLogI18n`.

- [ ] **Step 1: Add failing ownership and behavior tests**

```python
def test_log_i18n_owns_runtime_translation_tables() -> None:
    module = (STATIC_DIR / "log_i18n.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        "STRUCTURED_LOG_SEGMENT_ALIASES",
        "RUNTIME_LOG_PHRASE_TRANSLATIONS",
        "NON_EN_DYNAMIC_LOG_TEXT",
        "function translateRuntimeLogText",
        "function localizeLogEventCode",
    ):
        assert marker in module
        assert marker not in app
    assert "function logI18nService()" in app
```

Update the unified contract test so translation markers are read from `log_i18n.js`, while compatibility calls remain discoverable in the combined bundle.

- [ ] **Step 2: Run the ownership test and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_log_i18n_owns_runtime_translation_tables -q`

Expected: FAIL because the tables remain in `app.js`.

- [ ] **Step 3: Move the pure localization implementation**

Move the constants and functions anchored by `LOG_TAB_TRANSLATIONS`, `STRUCTURED_LOG_SEGMENT_ALIASES`, `RUNTIME_LOG_PHRASE_TRANSLATIONS`, `EN_LOG_FRAGMENT_CLEANUPS`, `NON_EN_DYNAMIC_LOG_TEXT`, and `BILIBILI_ROUTE_ALIASES` into `log_i18n.js`. Replace direct helper access with configured dependencies:

```javascript
function currentLanguage() {
  return typeof dependencies.currentLanguage === "function"
    ? dependencies.currentLanguage()
    : "zh-CN";
}

function translateUiText(value) {
  return typeof dependencies.translateUiText === "function"
    ? dependencies.translateUiText(value)
    : String(value || "");
}
```

Export the public functions with `Object.freeze`. In `app.js`, add only:

```javascript
function logI18nService() {
  return window.UcpLogI18n || null;
}
```

Update log rendering callers to use `logI18nService()?.method(...)` with the previous raw value as a safe fallback. Configure the module during startup.

- [ ] **Step 4: Run log localization contracts and verify GREEN**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_unified_frontend_contract.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the log localization module**

```powershell
git add -- app/web/static/log_i18n.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): extract log localization service"
```

---

### Task 3: Extract Log Center Controller and Worker Lifecycle

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/log_center.js`
- Modify: `app/web/static/app.js:22-83`
- Modify: `app/web/static/app.js:2817-3485`
- Modify: `tests/test_web_browser.py:880-950`
- Modify: `tests/test_unified_frontend_contract.py:4140-4190`

**Interfaces:**
- Consumes: `configure({ getState, getLanguage, t, esc, escAttr, byId, writeClipboard, runOperation, onFiltersChange })`.
- Produces: `render()`, `select(id)`, `setTab(category)`, `setPage(delta)`, `setPageSize(value)`, `copyTraceId()`, `copyDetail()`, `copyJson()`, `exportDetail()`, and `dispose()`.

- [ ] **Step 1: Add failing controller ownership tests**

```python
def test_log_center_owns_workers_and_render_pipeline() -> None:
    module = (STATIC_DIR / "log_center.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        'new Worker("/static/log_query_worker.js?v=20260707-log-worker")',
        'new Worker("/static/log_detail_worker.js?v=20260709-log-detail-worker")',
        "function renderLogQueryResult",
        "function renderLogDetailResult",
        "function syncLogFiltersFromDom",
    ):
        assert marker in module
        assert marker not in app
    assert "function renderLogs() { return logCenterService().render(); }" in app
```

- [ ] **Step 2: Run the new controller test and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_log_center_owns_workers_and_render_pipeline -q`

Expected: FAIL because worker construction and render functions remain in `app.js`.

- [ ] **Step 3: Move log state, workers, filters, renderers, and actions**

Move `logFilters`, paging state, query/detail worker state, worker close functions, query submission, table rendering, detail rendering, copy/export operations, tab/filter/page operations, and log-only HTML helpers into `log_center.js`. Store controller-local state in one object:

```javascript
const state = {
  filters: { category: "all", level: "all", time: "30m", platform: "all", trace: "", keyword: "" },
  page: 1,
  pageSize: 20,
  selectedId: "",
  querySequence: 0,
  detailSequence: 0,
  queryWorker: null,
  detailWorker: null,
  fallbackTimer: null,
};
```

Use `window.UcpLogI18n` for all language conversion. `dispose()` must terminate both workers, clear the fallback timer, reset pending flags, and be safe when called twice.

Keep only exact forwarding wrappers in `app.js`, for example:

```javascript
function renderLogs() { return logCenterService().render(); }
function selectLog(id) { return logCenterService().select(id); }
function setLogPage(delta) { return logCenterService().setPage(delta); }
function setLogPageSize(value) { return logCenterService().setPageSize(value); }
```

- [ ] **Step 4: Run worker, browser, and unified contracts**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py -q`

Expected: all selected tests PASS; no browser console exception from `UcpLogCenter`.

- [ ] **Step 5: Commit the log center controller**

```powershell
git add -- app/web/static/log_center.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): extract log center controller"
```

---

### Task 4: Extract Four-State List Controller

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/list_pages.js`
- Modify: `app/web/static/app.js:10-21`
- Modify: `app/web/static/app.js:1035-1514`
- Modify: `tests/test_web_browser.py:950-990`
- Modify: `tests/test_unified_frontend_contract.py`

**Interfaces:**
- Consumes: `configure({ getState, getSelection, setSelection, t, esc, escAttr, byId, frontendAction, playCompleted, renderStatus })`.
- Produces: `renderQueue()`, `renderActive()`, `renderCompleted()`, `renderFailed()`, `selectActive(id)`, `selectCompleted(id)`, `selectFailed(id)`, page setters, `navigationOrder()`, and `dispose()`.

- [ ] **Step 1: Add failing list ownership tests**

```python
def test_list_pages_owns_paging_worker_and_four_state_renderers() -> None:
    module = (STATIC_DIR / "list_pages.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        'new Worker("/static/list_page_worker.js?v=20260708-list-page-worker")',
        "function renderQueue",
        "function renderActive",
        "function renderCompleted",
        "function renderFailed",
        "function applyListPageResult",
    ):
        assert marker in module
        assert marker not in app
    assert "function renderQueue() { return listPagesService().renderQueue(); }" in app
```

- [ ] **Step 2: Run the ownership test and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_list_pages_owns_paging_worker_and_four_state_renderers -q`

Expected: FAIL because list paging remains in `app.js`.

- [ ] **Step 3: Move list-local state and rendering**

Move queue/completed/failed page numbers, page sizes, worker sequence state, worker lifecycle, row renderers, details, selection reconciliation, page operations, active options, and failure solution rendering into `list_pages.js`. Keep shared selection access explicit:

```javascript
function selected(domain) {
  return typeof dependencies.getSelection === "function"
    ? String(dependencies.getSelection(domain) || "")
    : "";
}

function setSelected(domain, id) {
  if (typeof dependencies.setSelection === "function") {
    dependencies.setSelection(domain, String(id || ""));
  }
}
```

`dispose()` terminates `list_page_worker` and invalidates all three request sequences. Preserve synchronous fallback behavior through a scheduled callback rather than direct work in the input event.

- [ ] **Step 4: Run list, browser, and cross-frontend tests**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py tests/test_list_page_worker.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the list controller**

```powershell
git add -- app/web/static/list_pages.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): extract four-state list controller"
```

---

### Task 5: Extract Settings and Dialog Controllers

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/settings_controller.js`
- Modify: `app/web/static/dialog_controller.js`
- Modify: `app/web/static/app.js:148-192`
- Modify: `app/web/static/app.js:3486-3727`
- Modify: `app/web/static/app.js:4044-4432`
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_unified_frontend_contract.py`

**Interfaces:**
- Settings consumes: `configure({ getState, t, optionLabel, byId, sendWS, syncAppearance, enhanceSelects })`.
- Settings produces: `render(force)`, `switchGroup(group)`, `updateBasic(key, value)`, `update(section, key, value)`, `handleProxySelect(...)`, and `commitProxyCustom(...)`.
- Dialog consumes: `configure({ getState, t, esc, escAttr, byId, frontendAction, sendWS, appendUiLog })`.
- Dialog produces directory, association, and selection modal show/confirm/cancel methods plus `handleShortcut(event)` and `dispose()`.

- [ ] **Step 1: Add failing settings/dialog ownership tests**

```python
def test_settings_and_dialog_controllers_own_their_handlers() -> None:
    settings = (STATIC_DIR / "settings_controller.js").read_text(encoding="utf-8")
    dialogs = (STATIC_DIR / "dialog_controller.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in ("function renderSettings", "function updateSetting", "function commitProxyCustom"):
        assert marker in settings
        assert marker not in app
    for marker in ("function showDirDialog", "function showFileAssociationModal", "function showSelectionModal"):
        assert marker in dialogs
        assert marker not in app
```

- [ ] **Step 2: Run the ownership test and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_settings_and_dialog_controllers_own_their_handlers -q`

Expected: FAIL because the functions remain in `app.js`.

- [ ] **Step 3: Move settings orchestration**

Move settings group constants, current group state, render/configuration functions, platform auth refresh, proxy handling, setting updates, and input/select helpers into `settings_controller.js`. Keep generated control markup delegated to `window.UcpSettingsRender`.

Expose global wrappers in `app.js` only for functions named by `onclick`, such as:

```javascript
function switchSettingsGroup(group) { return settingsControllerService().switchGroup(group); }
function updateSetting(section, key, value) { return settingsControllerService().update(section, key, value); }
function commitProxyCustom(platformId, key, input) { return settingsControllerService().commitProxyCustom(platformId, key, input); }
```

- [ ] **Step 4: Move all three dialog flows**

Move directory state, modal handlers, file association labels/actions, selection state/rows/actions, and shortcut routing into `dialog_controller.js`. Implement one shortcut entry:

```javascript
function handleShortcut(event) {
  if (handleSelectionShortcut(event)) return true;
  if (handleAssociationShortcut(event)) return true;
  if (event.key === "Escape" && isDirectoryOpen()) {
    cancelDirectory();
    return true;
  }
  return false;
}
```

`dispose()` clears selection items, directory paths, and modal visibility without sending backend actions.

- [ ] **Step 5: Run settings, dialog, and browser tests**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py -q`

Expected: all selected tests PASS, including Enter/Escape selection modal behavior and custom proxy input.

- [ ] **Step 6: Commit settings and dialogs**

```powershell
git add -- app/web/static/settings_controller.js app/web/static/dialog_controller.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): extract settings and dialog controllers"
```

---

### Task 6: Extract Playback Controller

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/playback_controller.js`
- Modify: `app/web/static/app.js:147`
- Modify: `app/web/static/app.js:3877-4030`
- Modify: `app/web/static/app.js:4433-4800`
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_unified_frontend_contract.py`

**Interfaces:**
- Consumes: `configure({ getState, getSelectedCompletedId, setSelectedCompletedId, t, byId, esc, frontendAction, appendLog, renderCompletedDetail })`.
- Produces: `playCompleted(id)`, `previewVideo(id)`, `togglePlay()`, `toggleFullscreen()`, `switchPreview(direction)`, seek handlers, deletion handlers, theme compatibility handlers, `closePreview()`, and `dispose()`.

- [ ] **Step 1: Add failing playback ownership tests**

```python
def test_playback_controller_owns_preview_and_media_events() -> None:
    module = (STATIC_DIR / "playback_controller.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        "function playCompleted",
        "function previewVideo",
        "function togglePlay",
        "function toggleFullscreen",
        "function setupPlayerEvents",
        "function rememberWebPlaybackPosition",
    ):
        assert marker in module
        assert marker not in app
```

- [ ] **Step 2: Run the playback test and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_playback_controller_owns_preview_and_media_events -q`

Expected: FAIL because playback functions remain in `app.js`.

- [ ] **Step 3: Move playback-local state, handlers, and lifecycle**

Move image auto-advance timer, current playing item, fullscreen state, preview selection, media validation, URL creation, controls, player event installation, position persistence, metadata reporting, preview navigation, and deletion confirmation into `playback_controller.js`. Reuse `window.UcpPlaybackState` and `window.UcpMediaDisplay` instead of duplicating pure helpers.

Implement lifecycle cleanup:

```javascript
function dispose() {
  clearImageAutoAdvanceTimer();
  const player = dependencies.byId?.("videoPlayer");
  if (player) {
    player.pause();
    player.removeAttribute("src");
    player.load();
  }
  currentPlayingId = "";
  isFullscreenMode = false;
}
```

Keep `onclick` wrappers in `app.js` as one-line forwards.

- [ ] **Step 4: Run playback browser tests and verify GREEN**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_web_browser.py -q -k "video or preview or playback or fullscreen or image"`

Expected: all selected tests PASS.

- [ ] **Step 5: Run the broader WebUI contract suite**

Run: `python -m pytest tests/test_web_browser.py tests/test_unified_frontend_contract.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit playback extraction**

```powershell
git add -- app/web/static/playback_controller.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_web_browser.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): extract playback controller"
```

---

### Task 7: Extract Frontend Runtime and Reduce `app.js` to Composition Root

**Files:**
- Modify: `tests/test_web_static_module_boundaries.py`
- Modify: `app/web/static/frontend_runtime.js`
- Modify: `app/web/static/app.js:1-145`
- Modify: `app/web/static/app.js:357-1029`
- Modify: `app/web/static/app.js:3765-3876`
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_fastapi_endpoints.py`

**Interfaces:**
- Consumes: `configure({ getState, replaceState, buildMockState, patchSection, renderSections, renderAll, onConnected, onSettled, appendUiLog })`.
- Produces: `start()`, `connect()`, `fetchState()`, `fetchDelta()`, `scheduleSections(sections)`, `handleServerMessage(message)`, `send(type, data)`, and `dispose()`.

- [ ] **Step 1: Add failing runtime ownership and size tests**

```python
def test_frontend_runtime_owns_transport_and_render_scheduler() -> None:
    runtime = (STATIC_DIR / "frontend_runtime.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        "function connectWS",
        "function fetchFrontendState",
        "function fetchFrontendDelta",
        "function scheduleRenderSections",
        "function cleanupPageResources",
    ):
        assert marker in runtime
        assert marker not in app


def test_app_js_is_a_composition_root_not_a_feature_monolith() -> None:
    path = STATIC_DIR / "app.js"
    content = path.read_text(encoding="utf-8")
    assert path.stat().st_size <= 100_000
    for marker in (
        "RUNTIME_LOG_PHRASE_TRANSLATIONS",
        "function renderLogDetailResult",
        "function applyListPageResult",
        "function showSelectionModal",
        "function setupPlayerEvents",
    ):
        assert marker not in content
```

- [ ] **Step 2: Run runtime and size tests and verify RED**

Run: `python -m pytest tests/test_web_static_module_boundaries.py::test_frontend_runtime_owns_transport_and_render_scheduler tests/test_web_static_module_boundaries.py::test_app_js_is_a_composition_root_not_a_feature_monolith -q`

Expected: FAIL because transport remains in `app.js` and `app.js` exceeds 100,000 bytes.

- [ ] **Step 3: Move transport, delta, render coalescing, and cleanup**

Move socket/timer state, `scheduleFrame`, section batching, delta application coordination, legacy event patching, state/delta fetch, connection setup, server message routing, and teardown into `frontend_runtime.js`.

Use state replacement callbacks rather than storing a second snapshot:

```javascript
function currentState() {
  return dependencies.getState();
}

function replaceState(nextState) {
  dependencies.replaceState(nextState);
}
```

`dispose()` closes WebSocket, nulls `onclose`, clears reconnect and delta timers, calls the registered module disposers exactly once, and tolerates repeated calls.

- [ ] **Step 4: Configure all modules from `app.js`**

Create a single composition function:

```javascript
function configureFeatureModules() {
  window.UcpLogI18n.configure({ currentLanguage, translateUiText, canonicalUiText });
  window.UcpLogCenter.configure(logCenterDependencies());
  window.UcpListPages.configure(listPageDependencies());
  window.UcpSettingsController.configure(settingsDependencies());
  window.UcpDialogController.configure(dialogDependencies());
  window.UcpPlaybackController.configure(playbackDependencies());
  window.UcpFrontendRuntime.configure(runtimeDependencies());
}
```

Call it once during `DOMContentLoaded`, then call `UcpFrontendRuntime.start()`. Keep `app.js` responsible for `frontendState`, navigation, top-level render routing, status bar, crawl commands, toolbox, and compatibility wrappers.

- [ ] **Step 5: Run runtime, endpoint, and browser tests**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_fastapi_endpoints.py tests/test_web_browser.py tests/test_unified_frontend_contract.py -q`

Expected: all selected tests PASS; `app.js` is at most 100,000 bytes.

- [ ] **Step 6: Commit the composition root**

```powershell
git add -- app/web/static/frontend_runtime.js app/web/static/app.js tests/test_web_static_module_boundaries.py tests/test_fastapi_endpoints.py tests/test_web_browser.py tests/test_unified_frontend_contract.py
git commit -m "refactor(web): reduce app entry to composition root"
```

---

### Task 8: Browser Lifecycle, Packaging, Documentation, and Full Regression

**Files:**
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_packaging.py`
- Modify: `packaging/README.md:180-205`
- Modify: `app/web/INTERACTION_MAP.md`
- Modify: `docs/engineering/frontend-refresh-and-concurrency.md`

**Interfaces:**
- Consumes: All seven `window.Ucp*` modules and their `dispose()` contracts.
- Produces: Runtime evidence that all modules load, page switching remains stable, and release packaging contains every static resource.

- [ ] **Step 1: Add a failing browser lifecycle test**

Add a Playwright test that loads the real WebUI, checks all namespaces, switches through the four list pages, logs, settings, and toolbox, and reports browser errors:

```python
def test_split_frontend_modules_load_and_survive_navigation(self):
    errors: list[str] = []
    self._page.on("pageerror", lambda error: errors.append(str(error)))
    self._page.goto(self._server_url, wait_until="domcontentloaded")
    self._page.wait_for_selector("#app-shell", state="visible", timeout=5000)
    namespaces = self._page.evaluate(
        """() => [
          'UcpFrontendRuntime', 'UcpListPages', 'UcpLogI18n', 'UcpLogCenter',
          'UcpSettingsController', 'UcpDialogController', 'UcpPlaybackController'
        ].map(name => [name, typeof window[name]])"""
    )
    assert all(kind == "object" for _, kind in namespaces)
    for page_id in ("queue", "active", "completed", "failed", "logs", "settings", "toolbox"):
        self._page.evaluate("pageId => switchPage(pageId)", page_id)
        self._page.wait_for_selector(f'#page-{page_id}.active', state="visible", timeout=5000)
    assert errors == []
```

- [ ] **Step 2: Run the lifecycle test and verify RED if any integration is incomplete**

Run: `python -m pytest tests/test_web_browser.py -q -k "split_frontend_modules_load_and_survive_navigation"`

Expected before final wiring: FAIL with a missing namespace or browser exception. If it already passes because all wiring was completed in earlier tasks, temporarily remove one `configure()` call, observe the expected failure, restore it, and rerun.

- [ ] **Step 3: Complete integration and packaging assertions**

Ensure all namespaces are configured before the first render and all scripts appear in `packaging/build_installer.py` source markers through the recursive static tree contract. Extend the packaging test tuple with the seven module filenames and verify `portable.spec` still includes the whole `app/web/static` tree.

- [ ] **Step 4: Update engineering documentation**

In `app/web/INTERACTION_MAP.md`, replace single-file ownership claims with the seven-module map and document the state access rule. In `docs/engineering/frontend-refresh-and-concurrency.md`, document:

- `app.js` owns state and composition only.
- feature controllers receive dependencies through `configure()`.
- worker/socket/timer ownership and `dispose()` are local to their modules.
- browser tests use selectors/events instead of fixed sleeps.
- latest focused and full-suite test baselines from Steps 5 and 6.

Update `packaging/README.md` so release verification lists the seven new JavaScript files alongside `app.js`.

- [ ] **Step 5: Run focused static, browser, and packaging suites**

Run: `python -m pytest tests/test_web_static_module_boundaries.py tests/test_fastapi_endpoints.py tests/test_web_browser.py tests/test_unified_frontend_contract.py tests/test_packaging.py -q`

Expected: all selected tests PASS with no new warning.

- [ ] **Step 6: Run the complete suite and record the baseline**

Run: `python -X faulthandler -m pytest -q`

Expected: all tests PASS; only pre-existing documented skips/warnings remain. Record exact pass/skip/warning counts and elapsed time in `docs/engineering/frontend-refresh-and-concurrency.md`.

- [ ] **Step 7: Verify source quality and working-tree scope**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace error; only files named by this plan plus unrelated pre-existing user changes are modified.

- [ ] **Step 8: Commit final integration and docs**

```powershell
git add -- tests/test_web_browser.py tests/test_packaging.py packaging/README.md app/web/INTERACTION_MAP.md docs/engineering/frontend-refresh-and-concurrency.md
git commit -m "docs(web): record split frontend architecture"
```

---

## Final Acceptance Checklist

- [ ] Seven responsibility modules load before `app.js` with a shared cache version.
- [ ] `app.js` is no larger than 100,000 bytes.
- [ ] `app.js` contains no log translation tables, worker controllers, dialog implementations, list paging implementation, or media event implementation.
- [ ] Each module exposes a frozen namespace, explicit `configure()` contract, and idempotent `dispose()`.
- [ ] Four-state lists, log center, settings, dialogs, playback, state/delta, and WebSocket behavior remain unchanged.
- [ ] New files are covered by static, browser, endpoint, packaging, and unified frontend tests.
- [ ] Full pytest suite passes and its exact baseline is documented.
