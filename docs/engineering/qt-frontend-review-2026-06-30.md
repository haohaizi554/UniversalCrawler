# Qt Frontend Engineering Review - 2026-06-30

## References Studied

- Qt Model/View Programming: keep data ownership in models, let views render only visible state, and prefer model signals over widget rebuilds.
- Qt Threads and QObjects: GUI objects must stay on the GUI thread; background work should communicate through queued signals or a main-thread invoker.
- Microsoft window messages: frameless Windows windows need a coherent `WM_NCCALCSIZE`, `WM_NCHITTEST`, and `WM_GETMINMAXINFO` strategy.
- Mature frameless Qt projects commonly keep native resize capability while hiding native frame painting, instead of mixing partial native and partial custom behavior.

## Current Lessons

1. Frameless window behavior must be treated as a platform adapter.
   On Windows, custom painting alone is not enough. The window still needs native hit-test semantics for resize edges, title drag, taskbar-aware maximize, and snap-like behavior.

2. Qt `showMaximized()` is not always safe for custom frameless windows.
   In this project it can be reported as full screen under some restored geometry and native-style combinations. The current fix separates work-area maximize from true full screen.

3. High-volume UI pages should render only what the user can see.
   Hidden pages should not translate, filter, reset, or repaint under high-frequency download/log events. Shared chrome and counters can update independently.

4. Logs need an append/ring-buffer path, not repeated full filtering on every render.
   Page-size increases should expand future capacity only. They should not immediately read old logs to fill the view. Page-size decreases should trim the in-memory UI buffer.

5. Any background-to-Qt call needs an explicit GUI-thread bridge.
   `QTimer.singleShot(0, callable)` from a Python worker thread is not a complete engineering contract. Use a QObject signal with `QueuedConnection` or the existing desktop/UI invoker.

6. Frameless resize should have two paths: native hit-test plus Qt system resize.
   `WM_NCHITTEST` is required for Windows snap/resize semantics, but child widgets can still receive mouse presses at the client edge. A `QWindow.startSystemResize()` fallback from a window-scoped event filter makes border dragging reliable without manual geometry math.

7. Translation and log filters are part of the render budget.
   Language changes should translate the visible page immediately and mark hidden pages dirty. Log views should skip table rebuilds when the item window and filter signature did not change, and category counts should be computed in one pass.

## Review Findings To Track

- Done 2026-06-30: `app/ui/main_window.py` now uses native hit-test plus `startSystemResize()` fallback and a window-scoped event filter for border dragging.
- Done 2026-06-30: `app/ui/layout/app_shell.py` now translates only the current page immediately and defers hidden pages with dirty flags.
- Done 2026-06-30: `app/ui/pages/log_center_page.py` now skips unchanged log renders and computes category counts in a single filtered pass.
- Done 2026-06-30: `app/services/frontend_state_service.py` now dispatches runtime GUI settings through a queued QObject invoker when a Qt app exists.
- Done 2026-06-30: `app/core/event_bus.py` now records slow synchronous handlers so fan-out stalls are visible.
- Remaining: `app/core/event_bus.py` publish is still synchronous fan-out. Long work should be moved behind an async/queued adapter when a handler is proven slow.
- `app/ui/viewmodels/snapshot_table_model.py`: model updates are better than widget resets, but the full-row signature scan should be avoided for very large sections by accepting section deltas keyed by id.

## Rule For Future UI Changes

When landing a UI or Qt runtime change, update this folder with the lesson if the change teaches one of these:

- a platform-specific Qt behavior,
- a high-frequency rendering or event-coalescing rule,
- a threading/main-thread boundary,
- a model/view or table performance rule,
- a user-experience pitfall that tests should guard.
