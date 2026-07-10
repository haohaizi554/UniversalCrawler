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


def test_list_pages_owns_paging_worker_and_four_state_renderers() -> None:
    module = (STATIC_DIR / "list_pages.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for marker in (
        'new Worker("/static/list_page_worker.js?v=20260708-list-page-worker")',
        "function applyListPageResult",
    ):
        assert marker in module
        assert marker not in app
    for name in ("Queue", "Active", "Completed", "Failed"):
        assert f"function render{name}" in module
        assert f"function render{name}() {{ return listPagesService().render{name}(); }}" in app


def test_list_pages_owns_copy_diagnostics_action() -> None:
    module = (STATIC_DIR / "list_pages.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "async function copyDiagnostics" in module
    assert "copyDiagnostics," in module.split("window.UcpListPages = Object.freeze({", 1)[1]
    assert "function copyDiagnostics(id) { return listPagesService().copyDiagnostics(id); }" in app
    wrapper = app.split("function copyDiagnostics(id)", 1)[1].split("function appendLog", 1)[0]
    assert "fetch(" not in wrapper
    assert "navigator.clipboard" not in wrapper


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
    for marker in (
        "function toggleTheme",
        "function restoreTheme",
        "function applyAppearance",
        "function applyTheme",
    ):
        assert marker in app
        assert marker not in module


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
    assert "let frontendState" not in runtime


def test_frontend_runtime_exports_the_complete_lifecycle_contract() -> None:
    runtime = (STATIC_DIR / "frontend_runtime.js").read_text(encoding="utf-8")
    for export in (
        "configure",
        "start",
        "connect",
        "fetchState",
        "fetchDelta",
        "scheduleDelta",
        "scheduleSections",
        "handleServerMessage",
        "send",
        "dispose",
    ):
        assert export in runtime.split("window.UcpFrontendRuntime = Object.freeze({", 1)[1]
    for guard in ("lifecycleGeneration", "stateFetchSequence", "deltaFetchSequence"):
        assert guard in runtime


def test_app_js_is_a_composition_root_not_a_feature_monolith() -> None:
    path = STATIC_DIR / "app.js"
    content = path.read_text(encoding="utf-8")
    assert path.stat().st_size <= 100_000
    assert "function configureFeatureModules()" in content
    assert "window.UcpFrontendRuntime.configure(runtimeDependencies())" in content
    for marker in (
        "RUNTIME_LOG_PHRASE_TRANSLATIONS",
        "function renderLogDetailResult",
        "function applyListPageResult",
        "function showSelectionModal",
        "function setupPlayerEvents",
    ):
        assert marker not in content


def test_frontend_runtime_owns_delayed_delta_scheduling() -> None:
    runtime = (STATIC_DIR / "frontend_runtime.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    operation = app.split("function performLogOperation(operation)", 1)[1].split(
        "function renderLogs()",
        1,
    )[0]
    assert "scheduleDelta: scheduleFrontendDeltaFetch" in runtime
    assert "frontendRuntimeService().scheduleDelta(200)" in operation
    assert "setTimeout" not in operation


def test_app_exposes_thin_runtime_compatibility_globals() -> None:
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for wrapper in (
        "window.fetchFrontendState = (...args) => frontendRuntimeService().fetchState(...args);",
        "window.fetchFrontendDelta = (...args) => frontendRuntimeService().fetchDelta(...args);",
        "window.scheduleRenderSections = (...args) => frontendRuntimeService().scheduleSections(...args);",
        "window.sendWS = (...args) => frontendRuntimeService().send(...args);",
    ):
        assert wrapper in app
