# Refactor Extraction Notes - 2026-06-30

## Extraction Done

- Moved platform settings table column sizing from `SettingsPage` to `app/ui/viewmodels/settings_platform_layout.py`.
- Kept `SettingsPage._platform_col_widths()` as a thin compatibility wrapper so existing callers and tests stay stable.
- Moved settings snapshot assembly to `app/services/frontend_settings_adapter.py` so `FrontendStateService` can focus on state, events, and actions.
- Moved pure video row formatting and classification to `app/services/frontend_video_adapter.py`, including queue status, queue rows, completed-table time, file size labels, path format labels, failure category, and failure solutions.

## Why This Is Worth Keeping

- Column sizing is pure layout policy. It does not need a live QWidget and can be tested with small unit tests.
- Settings snapshots are a stable config-to-frontend contract. Testing them outside the GUI is cheaper and safer.
- Video row adaptation is a stable `VideoItem -> frontend row` boundary. Keeping this outside the state service prevents the service from absorbing formatting and UI fallback rules.
- `FrontendStateService` still owns side effects: metadata probing, event publishing, config writes, runtime application, and download-manager interaction.

## Engineering Rules

- For files over 1000 lines, extract pure policies, formatters, classifiers, pagination, and data adapters before extracting one-off UI fragments.
- Page classes should orchestrate: receive snapshots, handle user events, and compose widgets.
- Service classes should own side effects: read/write config, publish events, call managers, and schedule background work.
- Keep thin wrappers during each extraction so existing callers remain stable while tests move toward the new module.
- When automation writes files, keep the script source ASCII or explicitly verify UTF-8 output. Broken terminal encoding must not create mojibake in tracked docs or source.
