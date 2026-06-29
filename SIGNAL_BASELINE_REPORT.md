# SIGNAL_BASELINE_REPORT

## Scope

This report covers runtime signal/event refresh paths that can affect GUI and WebUI responsiveness:

- PyQt signals and GUI slots
- EventBus and AppState change events
- download progress and queue events
- log refresh events
- WebSocket pushes and HTTP frontend state deltas
- FrontendState snapshot generation
- table/list/page rendering

It intentionally excludes UI redesign, downloader protocol changes, plugin rewrites, and broad architecture replacement.

## Current GUI Signal And Refresh Path

1. User actions originate in `app/ui/main_window.py` and `app/ui/layout/app_shell.py`.
2. GUI controls emit PyQt signals such as `sig_start_crawl`, `sig_stop_crawl`, `delete_requested`, `setting_changed`, `clear_all_requested`, and page switch signals.
3. Application state changes are stored through `app/services/app_state.py`.
4. `AppState._publish_change()` publishes `app_state.changed` through `app/core/event_bus.py`.
5. `MainWindow._on_app_state_changed()` maps topics to refresh topics and schedules work through `app/ui/ui_update_scheduler.py`.
6. `UiUpdateScheduler` coalesces dirty topics on a QTimer and flushes on the GUI thread through a queued Qt signal.
7. `MainWindow._render_frontend_state()` calls `FrontendStateService.get_delta()` or `get_snapshot()` and sends changed sections to `AppShell.render()`.
8. `AppShell.render()` renders only the current visible page when the changed sections matter to that page, then updates status/count widgets.
9. Table-heavy pages use `QAbstractTableModel` implementations such as `SnapshotTableModel` and `ActiveDownloadsModel`, which emit `dataChanged` when row identity is stable and reset only when the row shape changes.

## Current WebUI Signal And Refresh Path

1. Backend events enter `app/web/controller.py` through `WebSocketBridge.emit()`.
2. The bridge records frontend events in `FrontendStateService.record_event()` and schedules versioned deltas with a short debounce.
3. `FrontendStateService` delegates dirty-section tracking to `FrontendEventAggregator`.
4. WebSocket delivery goes through `app/web/ws_transport.py`, where each connection has a bounded outbound queue and noisy messages can be coalesced or dropped.
5. `app/web/ws_dispatcher.py` handles `frontend_action` messages with a client `frontend_version`, returns `frontend_action_result`, and sends `frontend_delta` only when the client version is stale.
6. HTTP routes in `app/web/rest_router.py` and `app/web/server.py` expose `/api/frontend/state`, `/api/frontend/delta`, and `/api/frontend/action`.
7. `app/web/static/app.js` applies `frontend_delta` by changed section and schedules rendering with `requestAnimationFrame`.
8. Frontend rendering is section-driven through `scheduleRenderSections()` and only re-renders the affected current page or status/count areas.

## High-Frequency Event Sources

- Download progress: `DownloadManager.task_progress`, `WebController._publish_video_state()`, `WebWorkflowService._schedule_progress_broadcast()`, and `AppState.update_video_state()`.
- Logs: `WebSocketBridge.emit("log")`, `FrontendStateService.record_log()`, `AppState.record_log()`, and GUI/WebUI log pages.
- Queue changes: `videos.upsert`, `videos.remove`, `videos.remove_many`, `videos.clear`, `item_found`, `clear_videos`, and `scan_result`.
- Task lifecycle: `task_started`, `task_finished`, `task_error`, `video_state_changed`, and direct download success/failure broadcasts.
- Page switching: `AppShell.show_page()` and `AppState.set_visible_page()`.
- Configuration changes: `settings.update`, `config`, `update_basic_setting`, `update_setting`, and appearance/theme actions.

## Existing Protections Observed

- GUI refreshes are coalesced by `UiUpdateScheduler` with queued Qt delivery.
- GUI frontend rendering supports versioned delta merging and changed-section rendering.
- GUI table models avoid full resets when row identity/order is stable.
- `AppState` keeps a bounded log buffer.
- Download progress is throttled in `AppState` and `WebController`.
- WebSocket connections use bounded queues in `ConnectionManager`.
- WebSocket noisy events can be coalesced and stale noisy events can be dropped under pressure.
- Frontend deltas are versioned and section-aware.
- WebUI DOM rendering is batched with `requestAnimationFrame`.
- HTTP and WebSocket frontend actions now pass client `frontend_version` and can return/apply `frontend_delta`.
- `AppState.record_log()` now batches `logs.append` notifications in a short publish window while retaining immediate in-memory log writes.

## Operations That Can Still Stall GUI

- Large local scans or queue replacements can still force table model resets when row identity changes broadly.
- Fast bursts of terminal task state changes can move rows across queue/active/completed/failed buckets and trigger several section updates.
- Log filtering and sorting in `LogCenterPage._apply_filters()` can become expensive when many log rows are visible or filters change repeatedly.
- Synchronous file dialogs and OS integration actions must remain outside long-running UI paths.
- Full theme/application stylesheet refresh can be expensive if triggered repeatedly.

## Operations That Can Still Stall WebUI

- Full `frontend_state` snapshots rebuild all sections, including large video lists and logs.
- Local directory scans that emit many `item_found` events can still cause heavy section rebuild pressure.
- Legacy WebSocket events still exist for compatibility and can trigger fallback delta fetches when no delta is available.
- Very slow WebSocket clients can fill per-connection queues, though bounded queues and noisy-event replacement now reduce impact.
- Large completed/failed lists can still be costly when the current page requires those sections.

## Most Dangerous Files

1. `app/web/controller.py` - bridges download/spider events to WebSocket and frontend state deltas.
2. `app/services/frontend_state_service.py` - builds snapshots/deltas and can touch large video/log collections.
3. `app/services/app_state.py` - central GUI state store and EventBus publisher for high-frequency changes.
4. `app/web/ws_transport.py` - backpressure boundary for slow WebSocket clients.
5. `app/ui/main_window.py` - GUI event-to-render coordinator and section refresh mapper.

## Most Dangerous Functions

1. `WebSocketBridge.emit()` in `app/web/controller.py` - central high-frequency event ingress for WebUI.
2. `FrontendStateService.get_delta()` in `app/services/frontend_state_service.py` - versioned state builder for incremental refresh.
3. `AppState.record_log()` in `app/services/app_state.py` - high-frequency log ingestion and UI notification source.
4. `MainWindow._render_frontend_state()` in `app/ui/main_window.py` - GUI snapshot/delta render coordinator.
5. `ConnectionManager._enqueue()` in `app/web/ws_transport.py` - WebSocket backpressure, coalescing, and overflow behavior.

## Current Validation Status

No full acceptance validation has been completed yet.

## Latest Small-Step Fix

The current round optimized the log refresh chain in `app/services/app_state.py`:

- `record_log()` still appends to the in-memory ring buffer immediately.
- `logs.append` UI/EventBus notifications are batched with a 100 ms publish window.
- `clear_logs()` and log buffer resize operations cancel pending batched notifications and publish their explicit state immediately.

This reduces high-frequency log write amplification before events reach GUI render scheduling or WebUI delta aggregation.

The previous WebUI action/delta fix is also present:

- HTTP `POST /api/frontend/action` accepts `frontend_version` in both route implementations.
- HTTP action responses include `frontend_delta` when available.
- WebUI JS applies returned `frontend_delta` directly and only falls back to `/api/frontend/delta` when needed.
- WebSocket noisy message replacement now coalesces matching noisy messages by event type and coalesce key.

The WebUI direct-send path in `app/web/controller.py` was also tightened:

- `async_scan_local_dir()`, `async_change_dir()`, `async_delete_video()`, and `async_rename_video()` keep direct awaited sends for ordering.
- Those sends now pass through `_send_recorded_frontend_event()` so `FrontendStateService` records dirty sections before the legacy WebSocket event is sent.
- `clear_videos`, `item_found`, `scan_result`, `video_removed`, `video_renamed`, and directly-sent logs now stay aligned with versioned frontend deltas.

## Latest Minimal Validation

- `python -m py_compile app/services/app_state.py app/web/rest_router.py app/web/server.py app/web/ws_transport.py` passed.
- `node --check app/web/static/app.js` passed.
- 1000 rapid `AppState.record_log()` calls produced 1 batched `logs.append` EventBus notification and retained the latest 300 log entries by existing buffer policy.
- GUI offscreen instantiation succeeded with title `Universal Crawler Pro` and pages `active`, `completed`, `failed`, `logs`, `queue`, `settings`, `toolbox`.
- WebUI app initialization through FastAPI TestClient succeeded; `/api/ping` returned HTTP 200 with status `ok`.
- HTTP `POST /api/frontend/action` returned HTTP 200 and included a `frontend_delta` object.
- Direct WebUI event simulation through `_send_recorded_frontend_event("item_found", ...)` advanced frontend version from 0 to 1 and marked video-related changed sections.
- Slow WebSocket simulation with `ConnectionManager(max_queue_size=8)` coalesced 200 same-video progress events into 1 queued message with 199 coalesces.
- Slow WebSocket simulation with 200 distinct noisy progress events held queue size at 8 and dropped stale noisy events instead of allowing unbounded growth.
- Desktop download progress simulation through `DownloadControllerMixin._emit_task_progress_event()` reduced 1000 rapid progress callbacks to 1 emitted domain event, then allowed the next event after the throttle window.
- Local uvicorn WebUI startup succeeded on `127.0.0.1:8765`; `/api/ping` returned HTTP 200.
- GUI offscreen runtime simulation loaded 120 tasks, switched across all 7 pages 30 times, batch-removed 80 tasks, and cleared the queue without exceptions. The final recorded render duration was about 10 ms.

The following evidence is still required before declaring the goal complete:

- GUI startup observed in a normal visible desktop session, not only offscreen.
- WebUI page behavior observed in an actual browser session, not only HTTP/server startup.
- high-frequency progress behavior observed during a real or end-to-end download workflow.
- 1000-log behavior observed with the visible GUI/WebUI log pages open.
- page switching observed visually without stalls.
- queue clear and batch delete observed visually without stalls.
- key tests or focused verification commands passing.
- `SIGNAL_OPTIMIZATION_ACCEPTANCE_REPORT.md` written with the actual validation results.
