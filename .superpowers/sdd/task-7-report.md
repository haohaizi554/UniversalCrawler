# Task 7 Report: Frontend Runtime Extraction

## Status

Complete. `frontend_runtime.js` owns frontend transport and lifecycle work, while
`app.js` is the composition root and sole owner of `frontendState`.

## RED

- Added runtime ownership and composition-root contracts.
- Added a Playwright lifecycle test covering duplicate start, idempotent dispose,
  stale state/delta fetches, stale socket callbacks, stale render frames, and
  per-run module disposal.
- Initial static run: 3 failed as expected because runtime was still an inert
  shell and `app.js` had no `configureFeatureModules()` composition function.
- Initial lifecycle run failed as expected with
  `TypeError: runtime.start is not a function`.
- Review RED reproduced a pending `/state` v1 response overwriting socket v2.
- Review RED reproduced the missing public delayed-delta scheduler with
  `TypeError: runtime.scheduleDelta is not a function`.
- Review RED reproduced all four missing `window` compatibility functions and
  verified that the browser could not call `window.fetchFrontendState`.
- Second-review RED reproduced stale timer A clearing run-two timer B before
  generation validation, so scheduling C did not cancel B and B+C both fetched.
- The same identity-order audit reproduced stale reconnect and render callbacks
  releasing the current run's shared handles.

## GREEN

- New ownership/composition contracts: 3 passed.
- New runtime lifecycle browser contract: 1 passed.
- Static module boundary suite: 10 passed.
- Endpoint and unified frontend suites: 225 passed.
- Brief focused suite, excluding the explicitly deferred Task 8 timestamp test:
  354 passed, 1 deselected in 87.71s.
- Brief focused suite without exclusion: 354 passed, 1 known failure in 89.85s.
- Review-focused runtime lifecycle and module tests: 16 passed.
- Review brief focused suite, excluding the explicitly deferred Task 8 test:
  359 passed, 1 deselected in 71.44s.
- Review brief focused suite without exclusion: 359 passed, 1 known failure in
  86.44s.
- Second-review runtime lifecycle and module tests: 17 passed.
- Second-review brief focused suite, excluding the deferred Task 8 test:
  360 passed, 1 deselected in 62.94s.
- Second-review brief focused suite without exclusion: 360 passed, 1 known
  failure in 69.73s.
- `node --check app/web/static/frontend_runtime.js`: passed.
- `node --check app/web/static/app.js`: passed.
- `git diff --check`: passed.

## Changes

- Implemented `configure`, `start`, `connect`, `fetchState`, `fetchDelta`,
  `scheduleSections`, `handleServerMessage`, `send`, and idempotent `dispose`.
- Moved WebSocket reconnect, state/delta transport, version continuity, legacy
  event patching, render coalescing, action fallback transport, and page cleanup
  into `frontend_runtime.js`.
- Added generation and sequence guards for socket handlers, state/delta/action
  fetches, reconnect/delta timers, and render-frame callbacks.
- Added cross-transport state freshness: versioned full states are monotonic,
  and unversioned fetch responses may commit only when their captured operation
  epoch is still current.
- Exported generation-aware `scheduleDelta()` and removed the remaining
  `setTimeout(fetchFrontendDelta, ...)` from `app.js`.
- Added explicit one-line `window.fetchFrontendState`,
  `window.fetchFrontendDelta`, `window.scheduleRenderSections`, and
  `window.sendWS` compatibility delegates.
- Replaced raw delayed-delta and reconnect timer handles with per-schedule token
  objects; callbacks now verify shared-token identity before clearing handles or
  evaluating generation/sequence.
- Added render-frame identity checks so a cancelled old frame cannot release a
  newer run's frame and break section coalescing.
- Kept state replacement behind injected `getState`/`replaceState`; runtime does
  not declare or retain a second `frontendState` snapshot.
- Added one guarded `configureFeatureModules()` call in `DOMContentLoaded`, then
  starts `UcpFrontendRuntime` exactly once.
- Kept navigation, top-level section routing, status, crawl commands, toolbox,
  module dependencies, and compatibility wrappers in `app.js`.
- Updated browser/static contracts to read transport behavior from the split
  runtime and added condition-driven lifecycle coverage without fixed sleeps.

## Size

- `app/web/static/app.js`: 57,118 bytes (limit: 100,000 bytes).
- `app/web/static/frontend_runtime.js`: 20,571 bytes.

## Risks

- The only focused-suite failure is the pre-existing
  `test_13e_log_center_dispose_is_idempotent_and_cancels_pending_fallback` test.
  Its fixed `2026-07-10 10:00:00` log timestamp is now outside the 30-minute
  filter, so no detail worker is created. Per the Task 7 brief, this remains for
  Task 8 and was not changed here.
- Platform catalog loading remains in `app.js` because Task 7 assigns only
  frontend state/delta and WebSocket transport to the runtime.

## Commit

- `2c595345` - `refactor(web): reduce app entry to composition root`
- `b323ebf4` - `fix(web): guard frontend runtime freshness`
- `bbd0df42` - `fix(web): preserve runtime timer identity`
