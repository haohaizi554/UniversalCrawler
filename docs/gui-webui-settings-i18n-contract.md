# GUI / WebUI Settings And I18n Contract

## Scope

The GUI configuration center and WebUI settings page must consume the same `FrontendStateService.settings_snapshot()` contract. Setting controls must hot-load from snapshot options, and visible language text must be resolved through the shared language catalogs.

## Combo Boxes

- GUI combo boxes must route through `app.ui.components.combo_popup.polish_combo_popup()` or `ThemedComboBox`.
- Short popup lists must fully expand without vertical or horizontal scrollbars, and their internal vertical scrollbar range must stay locked at zero.
- Popup views must use the themed no-frame view and `NoFocusItemDelegate`; native focus rectangles and white popup shells are regressions.
- Callers that pass popup row height or visible row count must have those values persisted on the combo so `showPopup()` cannot silently fall back to default popup geometry.
- Settings page combo controls keep their page-specific chrome, while popup behavior remains centralized.
- Log center, active downloads, completed downloads, download queue, plugin settings, platform sidebar, and top quantity controls are covered by `tests/test_unified_frontend_contract.py`.

## Appearance Updates

- Language changes may retranslate shell and visible pages.
- Same-language settings refreshes must not retranslate every page or rebuild top quantity controls.
- Theme/font/scale updates must batch top-level repaint while stylesheet and palette are swapped.
- Managed `ThemedComboBox` controls must refresh their inline control stylesheet after theme changes; otherwise dark-theme pages can retain light combo boxes even though the global palette has changed.
- GUI and WebUI theme/accent values must remain synchronized with appearance settings.

## Language Catalogs

- Source language is `zh-CN`; generated catalogs live in `app/ui/i18n/en-US.json` and `app/ui/i18n/zh-TW.json`.
- GUI translation uses `app.ui.localization.tr()`.
- WebUI keeps a local fallback dictionary for first paint, then loads the same shared catalogs through `/api/i18n/{language}` and merges them over the fallback.
- Both `app.web.server.create_app()` and `app.web.rest_router.build_rest_router()` must expose `/api/i18n/{language}`.

## Regression Commands

```bash
python -m pytest tests/test_unified_frontend_contract.py -q
python -m pytest tests/test_fastapi_endpoints.py::StateEndpointTests::test_i18n_catalog_endpoint_serves_shared_language_files tests/test_fastapi_endpoints.py::StateEndpointTests::test_i18n_catalog_endpoint_returns_empty_for_source_language -q
node --check app/web/static/app.js
```
