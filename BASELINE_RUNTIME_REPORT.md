# BASELINE_RUNTIME_REPORT

## Scope

This report records the runtime baseline required before continuing larger GUI / WebUI / configuration-center work.

Environment note: GUI verification was executed through a real PyQt6 `QApplication` and `MainWindow` with `QT_QPA_PLATFORM=offscreen`, then captured with `QWidget.grab()`. This is a real Qt runtime smoke, but it is not a human-visible Windows desktop session.

## Entry Points

| Area | Command / File | Result |
|---|---|---|
| GUI | `python -m entry.gui_entry` / `entry.gui_entry:main` | Entry documented and importable; runtime smoke used `MainWindow` directly to avoid blocking the turn. |
| WebUI | `python -m entry.web_entry --no-qt --no-browser --host 127.0.0.1 --port 8765` | Started successfully. |
| Tests | `python -m pytest -q` | To be rerun after this baseline fix set. |
| Config file | `D:\desktop\project\UniversalCrawlerProplus\user_data\config.json` | Read/write verified through `ConfigManager`. |
| Installer | `python packaging/build_installer.py` | Build entry identified; static tests cover source integrity. |
| GUI backend link | `MainWindow` -> `AppShell` -> `FrontendStateService.handle_action()` -> `ConfigManager.set()` | Verified by GUI smoke. |
| WebUI backend link | Browser -> `/api/frontend/action` -> `WebController` -> `FrontendStateService.handle_action()` -> `ConfigManager.set()` | Verified by Playwright + REST. |

## GUI Runtime Baseline

Command used:

```powershell
python - <<'PY'
# creates QApplication + MainWindow, switches seven pages,
# switches all SettingsPage groups, captures screenshots,
# updates/restores download.max_retries and common.theme
PY
```

Artifact directory:

```text
runtime_artifacts/baseline-gui/
```

Screenshots:

- `runtime_artifacts/baseline-gui/gui-queue.png`
- `runtime_artifacts/baseline-gui/gui-active.png`
- `runtime_artifacts/baseline-gui/gui-completed.png`
- `runtime_artifacts/baseline-gui/gui-failed.png`
- `runtime_artifacts/baseline-gui/gui-logs.png`
- `runtime_artifacts/baseline-gui/gui-settings.png`
- `runtime_artifacts/baseline-gui/gui-toolbox.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-1.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-2.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-3.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-4.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-5.png`
- `runtime_artifacts/baseline-gui/gui-settings-group-6.png`

Result file:

```text
runtime_artifacts/baseline-gui/gui-smoke-result.json
```

Observed result:

- Seven GUI pages opened: `queue`, `active`, `completed`, `failed`, `logs`, `settings`, `toolbox`.
- Six configuration groups opened: basic, download, platform, playback, logging, appearance.
- `download.max_retries` changed from `3` to `0`, immediately appeared in the settings snapshot, persisted through `ConfigManager`, and was restored to `3`.
- `common.theme` changed to `dark`, persisted through `ConfigManager`, and was restored to `light`.
- No abnormal process exit was observed during the final GUI smoke.

## WebUI Runtime Baseline

Command used:

```powershell
python -m entry.web_entry --no-qt --no-browser --host 127.0.0.1 --port 8765
```

Service log:

```text
C:\tmp\ucrawl-webui-runtime.err.log
```

Endpoint checks:

- `GET /api/ping` -> `{"status":"ok","version":"1.0.0"}`
- `GET /api/frontend/state` returned `settings_snapshot`.
- `GET /api/frontend/delta?since_version=0` returned `sections` and version metadata.

Artifact directory:

```text
runtime_artifacts/baseline-webui/
```

Screenshots:

- `runtime_artifacts/baseline-webui/webui-settings-desktop.png`
- `runtime_artifacts/baseline-webui/webui-settings-mobile.png`
- `runtime_artifacts/baseline-webui/webui-settings-wide.png`

Result file:

```text
runtime_artifacts/baseline-webui/webui-smoke-result.json
```

Observed result:

- Settings page rendered 6 cards and 42 controls.
- Viewports verified: `1366x768`, `390x844`, `1920x1080`.
- No full-page horizontal overflow in those viewports.
- `download.max_retries` changed from `3` to `0` through `/api/frontend/action`, appeared in `/api/frontend/state`, and was restored to `3`.
- Console errors: `0`.
- HTTP 4xx/5xx responses during browser verification: `0`.

## Baseline Issues Found

### Fixed: Platform proxy combo enabled state crash

During GUI settings group switching, opening the platform settings group crashed rendering with:

```text
TypeError: setEnabled(self, a0: bool): argument 1 has unexpected type 'str'
```

Root cause:

```python
editable = bool(row.get("proxy_editable", policy.get("editable"))) and platform_id and config_key
```

The chained `and` expression returned `config_key` as a string. Fixed by converting the entire condition to `bool(...)`.

Regression coverage:

- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_gui_platform_settings_proxy_combo_uses_boolean_enabled_state`

Teaching note:

- `docx/配置中心平台代理启用状态类型修复.md`

### Fixed: GUI/WebUI file association default drift

The GUI settings page and WebUI settings action still emitted `include_image=true`, while the safer service/dialog default is video-only. This was aligned to `include_video=true, include_image=false`.

Regression coverage:

- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_gui_basic_settings_use_backend_options_and_emit_changes`
- `tests/test_unified_frontend_contract.py::UnifiedFrontendContractTests::test_web_basic_settings_use_backend_options_and_update_action`

## Baseline Risk List

- GUI smoke is automated offscreen, not a human-visible Windows desktop walkthrough.
- Full `pytest` must be rerun after the fixes recorded above.
- Final acceptance report still needs to be generated after full tests and final CR.

## Next Fix / Verification Plan

1. Run targeted and full test suites after the baseline fixes.
2. Verify packaging tests and installer source integrity.
3. Run final whitespace / syntax gates.
4. Generate `FINAL_ACCEPTANCE_REPORT.md`.
