# Final Acceptance Report

Generated: 2026-06-28 Asia/Shanghai

## 1. Modified File List

Current working tree includes changes across these project areas:

- Runtime/UI: `app/services/frontend_state_service.py`, `app/debug_logger.py`, `app/ui/pages/settings_page.py`, `app/ui/dialogs/file_association.py`, `app/ui/components/media_preview_panel.py`, `app/ui/layout/app_shell.py`, `app/ui/main_window.py`, `app/ui/ui_update_scheduler.py`, `app/ui/styles/themes.py`, `app/ui/pages/failed_page.py`, `app/ui/pages/log_center_page.py`, `app/ui/viewmodels/snapshot_table_model.py`
- WebUI: `app/web/static/app.js`, `app/web/static/app.css`, `app/web/static/index.html`, `app/web/server.py`, `app/web/ws_dispatcher.py`, `app/web/controller_config_service.py`, `app/web/INTERACTION_MAP.md`
- Core/config: `app/config/__init__.py`, `app/config/constants.py`, `app/config/settings.py`, `app/controllers/application_controller.py`, `app/core/download_manager.py`, `app/core/download_manager_core.py`, `app/services/app_state.py`
- Packaging/install: `packaging/build_installer.py`, `packaging/README.md`, `docs/packaging.md`, generated installer `dist/installer/UniversalCrawlerPro_Setup_1.0.0.exe`
- Tests: `tests/test_frontend_state_service.py`, `tests/test_unified_frontend_contract.py`, `tests/test_ui_dialogs.py`, `tests/test_packaging.py`, `tests/test_application_controller.py`, `tests/test_config_settings.py`, `tests/test_desktop_host.py`, `tests/test_downloaders.py`, `tests/test_fastapi_endpoints.py`, `tests/test_main_window.py`, `tests/test_registry.py`, `tests/test_web_browser.py`, `tests/test_snapshot_table_model.py`, `tests/test_ui_update_scheduler.py`, `tests/README.md`
- Docs/reports: `README.md`, `README_EN.md`, `docs/config.md`, `docs/testing.md`, `docs/cli/API_REFERENCE.md`, `docs/cli/CLI_GUIDE.md`, `cli/skill/SKILL.md`, `mermaid/README.md`, `BASELINE_RUNTIME_REPORT.md`, `FINAL_ACCEPTANCE_REPORT.md`, `docx/配置中心平台代理启用状态类型修复.md`, `docx/运行时热加载与调试日志代理修复.md`
- Runtime evidence: `runtime_artifacts/baseline-gui/`, `runtime_artifacts/baseline-webui/`, `runtime_artifacts/final-gui/`, `runtime_artifacts/final-webui/`

Note: the working tree also contains pre-existing/development artifact deletions under `.codex_tmp/` plus deleted legacy markdown files shown by `git status`. They were not reverted.

## 2. GUI Runtime Result

Final GUI smoke used real PyQt widgets in `QT_QPA_PLATFORM=offscreen` through `AppShell + FrontendStateService`.

- Artifact: `runtime_artifacts/final-gui/gui-smoke-result.json`
- Screenshots: `runtime_artifacts/final-gui/gui-queue.png`, `gui-active.png`, `gui-completed.png`, `gui-failed.png`, `gui-logs.png`, `gui-settings.png`, `gui-toolbox.png`
- Pages switched successfully: queue, active, completed, failed, logs, settings, toolbox
- Settings groups rendered successfully: basic, download, platform, playback, logging, appearance
- Hot load verified:
  - `download.max_retries`: `3 -> 0 -> 3`
  - `common.theme`: `light -> dark -> light`
- File association signal verified: `[true, false]` (video only by default)
- Abnormal exit: false

## 3. WebUI Runtime Result

Final WebUI smoke started `python -m entry.web_entry --no-qt --no-browser --host 127.0.0.1 --port 8766` and drove it with Python Playwright.

- Artifact: `runtime_artifacts/final-webui/webui-smoke-result.json`
- Screenshots: `runtime_artifacts/final-webui/webui-settings-desktop.png`, `webui-settings-mobile.png`, `webui-settings-wide.png`
- Viewports:
  - desktop 1366x768: no horizontal overflow
  - mobile 390x844: no horizontal overflow
  - wide 1920x1080: no horizontal overflow
- Settings cards: 6
- Settings controls: 42
- Console errors: none
- Bad HTTP responses: none
- REST hot load verified: `download.max_retries` `3 -> 0 -> 3`
- Delta endpoint verified with keys including `sections`, `version`, and `base_version`
- Abnormal exit: false

## 4. Config Center Acceptance

All six settings pages/groups now render through one shared settings snapshot and update through hot-load actions.

| Group | GUI | WebUI | Hot-load path |
| --- | --- | --- | --- |
| Basic | rendered, file association signal `[true,false]` | rendered, action sends `{include_video:true, include_image:false}` | `update_basic_setting`, `register_file_associations` |
| Download | rendered, spinboxes stable | rendered, numeric controls stable | `update_setting(download, key, value)` |
| Platform | rendered after proxy-enabled type fix | rendered with disabled/enabled proxy controls | platform key routed through `update_setting` |
| Playback | rendered | rendered | `update_setting(playback, key, value)` |
| Logging | rendered | rendered | `update_setting(logging, key, value)` |
| Appearance | rendered, theme hot-loaded | rendered, theme path shared | `update_setting(common/appearance, key, value)` |

## 5. GUI/WebUI Function Mapping

| Capability | GUI | WebUI | Shared backend |
| --- | --- | --- | --- |
| Page model | `AppShell.pages` | `PAGE_DEFINITIONS` / DOM pages | `FrontendStateService.get_snapshot()` |
| Settings snapshot | `SettingsPage.render()` | `settingsControls()` | `FrontendStateService.settings_snapshot()` |
| Settings update | Qt signal `setting_changed` | REST/WebSocket `frontend_action` | `handle_action("update_setting")` |
| File association | `FileAssociationDialog`, settings button | settings action button | `register_file_associations` action/service |
| Download options | active/settings controls | settings controls | `download_options_snapshot()` and runtime manager hooks |
| Logs | `LogCenterPage` | Web log page | shared log records/events |
| Toolbox | `ToolboxPage` | Web toolbox page | `toolbox_items()` |

## 6. Installer Adaptation Result

Installer adaptation is aligned with the current project:

- Portable source prerequisites exist:
  - `dist/UniversalCrawlerPro/UniversalCrawlerPro.exe`
  - `dist/UniversalCrawlerPro/CrawlerWebPortal.exe`
  - wizard images exist
- Inno compiler resolved: `D:\APP\Inno Setup 6\ISCC.exe`
- `tests/test_packaging.py`: `84 passed`
- Installer artifact exists: `dist/installer/UniversalCrawlerPro_Setup_1.0.0.exe`
- Installer artifact size: `874009774` bytes
- EXE header check: `MZ == true`

Operational note: `python packaging/build_installer.py` exceeded the tool timeout while `ISCC.exe` continued in the background. The background process completed, no `ISCC` / `build_installer` process remained, and the installer artifact timestamp updated to `2026/6/28 2:34:10`.

## 7. Test Commands And Results

- `python -m pytest -q`
  - Result: `1365 passed, 1 skipped, 5 warnings`
  - Duration: `151.61s`
- `python -m pytest tests\test_packaging.py -q`
  - Result: `84 passed`
- `node --check app\web\static\app.js`
  - Result: passed
- `python -m py_compile app\services\frontend_state_service.py app\debug_logger.py app\ui\dialogs\file_association.py app\ui\pages\settings_page.py app\ui\components\media_preview_panel.py app\web\server.py packaging\build_installer.py`
  - Result: passed
- `git diff --check`
  - Result: passed; only line-ending warnings were printed
- Runtime GUI smoke
  - Result: passed, artifact `runtime_artifacts/final-gui/gui-smoke-result.json`
- Runtime WebUI smoke
  - Result: passed, artifact `runtime_artifacts/final-webui/webui-smoke-result.json`

## 8. Fixed Bug List

- Fixed GUI platform settings crash: `QWidget.setEnabled()` received a string because chained `and` returned `config_key`; the value is now explicitly boolean.
- Fixed GUI/WebUI/default-app drift: default file association action is video-only and does not take over images unless explicitly selected.
- Fixed runtime download hot-load double-application: `set_max_concurrent()` is no longer overwritten by a later fallback using stale config defaults.
- Fixed `DebugLoggerProxy` mock lifecycle: added attribute deletion support so `unittest.mock.patch` exits cleanly.
- Kept media preview repair switching compatible with repaired/cache playback paths covered by tests.

## 9. Remaining Risks

- GUI runtime smoke used Qt offscreen mode, not a physical monitor/GPU. It verifies widget construction, page switching, rendering, screenshots, and hot-load behavior, but not GPU-specific compositor glitches.
- The installer artifact was generated and validated by existence/header/size/timestamp, but the packaging command crossed the tool timeout before the parent shell returned a normal success code. Background `ISCC.exe` finished and left no residual process.
- `git status` still contains unrelated/development artifact deletions and broad existing changes. They were preserved rather than reverted.
- Full crawl/download against real external sites was not executed; tests cover internal contracts and runtime UI behavior.

## 10. Follow-up Recommendations

- Add a first-class `--check` or `--dry-run` mode to `packaging/build_installer.py` so installer prerequisites can be validated without starting Inno compilation.
- Persist the GUI/WebUI smoke scripts as reusable test utilities instead of one-off inline probes.
- Add a CI job for `node --check`, `py_compile`, `pytest`, and packaging prerequisite checks.
- Run one manual Windows desktop pass on a real monitor before release, focusing on file association UX, installer wizard choices, and GPU-backed media preview.
