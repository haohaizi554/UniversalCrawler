"""WebUI browser cases owned by frontend runtime state sequencing."""

from __future__ import annotations


class FrontendRuntimeStateCases:
    def test_13i_frontend_runtime_rejects_stale_async_work_and_disposes_idempotently(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const runtime = window.UcpFrontendRuntime;
              runtime.dispose();

              const nativeFetch = window.fetch;
              const NativeWebSocket = window.WebSocket;
              const nativeRequestAnimationFrame = window.requestAnimationFrame;
              const nativeCancelAnimationFrame = window.cancelAnimationFrame;
              const moduleNames = [
                "UcpLogCenter",
                "UcpListPages",
                "UcpSettingsController",
                "UcpDialogController",
                "UcpPlaybackController",
              ];
              const nativeModules = Object.fromEntries(moduleNames.map(name => [name, window[name]]));
              const disposeCounts = Object.fromEntries(moduleNames.map(name => [name, 0]));
              const requests = [];
              const sockets = [];
              const frames = [];
              const renders = [];
              const logs = [];
              const settled = [];
              let state = { version: 0, queue_items: [], log_items: [] };

              class FakeWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                static CLOSED = 3;

                constructor(url) {
                  this.url = url;
                  this.readyState = FakeWebSocket.CONNECTING;
                  this.closeCalls = 0;
                  this.sent = [];
                  sockets.push(this);
                }

                close() {
                  this.closeCalls += 1;
                  this.readyState = FakeWebSocket.CLOSED;
                }

                send(payload) {
                  this.sent.push(payload);
                }
              }

              const deferredResponse = url => {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                requests.push({ url: String(url), resolve });
                return promise;
              };
              const response = payload => ({ ok: true, json: async () => payload });

              try {
                for (const name of moduleNames) {
                  window[name] = { dispose: () => { disposeCounts[name] += 1; } };
                }
                window.WebSocket = FakeWebSocket;
                window.fetch = deferredResponse;
                window.requestAnimationFrame = callback => {
                  frames.push(callback);
                  return frames.length;
                };
                window.cancelAnimationFrame = () => {};

                const dependencies = {
                  getState: () => state,
                  replaceState: nextState => { state = nextState; },
                  buildMockState: () => ({ version: 0, queue_items: [], log_items: [] }),
                  patchSection: () => [],
                  renderSections: sections => renders.push(Array.from(sections)),
                  renderAll: () => renders.push(["all"]),
                  onConnected: () => {},
                  onSettled: value => settled.push(value),
                  appendUiLog: (...parts) => logs.push(parts.join(" ")),
                };

                runtime.configure(dependencies);
                const firstStart = runtime.start();
                const duplicateStart = runtime.start();
                const firstSocket = sockets[0];
                const staleMessage = firstSocket.onmessage;
                runtime.scheduleSections(["queue_items"]);
                const staleFrame = frames[0];

                runtime.dispose();
                runtime.dispose();
                runtime.configure(dependencies);
                const secondStart = runtime.start();
                const secondSocket = sockets[1];

                requests[1].resolve(response({ version: 2, queue_items: [{ id: "current" }], log_items: [] }));
                await secondStart;
                requests[0].resolve(response({ version: 1, queue_items: [{ id: "stale" }], log_items: [] }));
                await firstStart;
                staleMessage({ data: JSON.stringify({
                  type: "frontend_state",
                  data: { version: 1, queue_items: [{ id: "stale-socket" }], log_items: [] },
                }) });
                staleFrame();

                const staleDelta = runtime.fetchDelta();
                const currentDelta = runtime.fetchDelta();
                requests[3].resolve(response({
                  version: 4,
                  base_version: 2,
                  sections: { queue_items: [{ id: "delta-current" }] },
                  changed_sections: ["queue_items"],
                }));
                await currentDelta;
                requests[2].resolve(response({
                  version: 3,
                  base_version: 2,
                  sections: { queue_items: [{ id: "delta-stale" }] },
                  changed_sections: ["queue_items"],
                }));
                await staleDelta;

                runtime.scheduleSections(["queue_items"]);
                frames.at(-1)();
                runtime.dispose();
                runtime.dispose();

                return {
                  duplicateStartShared: duplicateStart === firstStart,
                  fetchCount: requests.length,
                  socketCount: sockets.length,
                  firstSocketClosedOnce: firstSocket.closeCalls === 1,
                  secondSocketClosedOnce: secondSocket.closeCalls === 1,
                  staleStateIgnored: state.queue_items[0]?.id === "delta-current",
                  staleFrameIgnored: renders.length === 2 && renders[0][0] === "all" && renders[1][0] === "queue_items",
                  disposersCalledOncePerRun: Object.values(disposeCounts).every(count => count === 2),
                  settledCount: settled.length,
                  logs,
                };
              } finally {
                runtime.dispose();
                window.fetch = nativeFetch;
                window.WebSocket = NativeWebSocket;
                window.requestAnimationFrame = nativeRequestAnimationFrame;
                window.cancelAnimationFrame = nativeCancelAnimationFrame;
                for (const name of moduleNames) window[name] = nativeModules[name];
              }
            }
            """
        )

        self.assertTrue(result["duplicateStartShared"])
        self.assertEqual(result["fetchCount"], 4)
        self.assertEqual(result["socketCount"], 2)
        self.assertTrue(result["firstSocketClosedOnce"])
        self.assertTrue(result["secondSocketClosedOnce"])
        self.assertTrue(result["staleStateIgnored"])
        self.assertTrue(result["staleFrameIgnored"])
        self.assertTrue(result["disposersCalledOncePerRun"])
        self.assertEqual(result["settledCount"], 1)
        self.assertEqual(result["logs"], [])

    def test_13j_frontend_runtime_rejects_full_state_older_than_newer_transport_state(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const runtime = window.UcpFrontendRuntime;
              runtime.dispose();
              const nativeFetch = window.fetch;
              const NativeWebSocket = window.WebSocket;
              const requests = [];
              let state = { version: 0, queue_items: [], log_items: [] };

              class FakeWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                static CLOSED = 3;
                constructor() { this.readyState = FakeWebSocket.CONNECTING; }
                close() { this.readyState = FakeWebSocket.CLOSED; }
                send() {}
              }

              window.fetch = url => new Promise(resolve => requests.push({ url: String(url), resolve }));
              window.WebSocket = FakeWebSocket;
              const response = payload => ({ ok: true, json: async () => payload });

              try {
                runtime.configure({
                  getState: () => state,
                  replaceState: nextState => { state = nextState; },
                  buildMockState: () => ({ version: 0, queue_items: [], log_items: [] }),
                  patchSection: () => [],
                  renderSections: () => {},
                  renderAll: () => {},
                  onConnected: () => {},
                  onSettled: () => {},
                  appendUiLog: () => {},
                });

                const versionedFetch = runtime.start();
                runtime.handleServerMessage({
                  type: "frontend_state",
                  data: { version: 2, queue_items: [{ id: "socket-v2" }], log_items: [] },
                });
                requests[0].resolve(response({
                  version: 1,
                  queue_items: [{ id: "fetch-v1" }],
                  log_items: [],
                }));
                await versionedFetch;
                const versionedStaleIgnored = state.version === 2 && state.queue_items[0]?.id === "socket-v2";

                const unversionedFetch = runtime.fetchState();
                runtime.handleServerMessage({
                  type: "frontend_state",
                  data: { version: 3, queue_items: [{ id: "socket-v3" }], log_items: [] },
                });
                requests[1].resolve(response({
                  queue_items: [{ id: "fetch-without-version" }],
                  log_items: [],
                }));
                await unversionedFetch;

                return {
                  versionedStaleIgnored,
                  unversionedStaleIgnored: state.version === 3 && state.queue_items[0]?.id === "socket-v3",
                };
              } finally {
                runtime.dispose();
                window.fetch = nativeFetch;
                window.WebSocket = NativeWebSocket;
              }
            }
            """
        )

        self.assertTrue(result["versionedStaleIgnored"])
        self.assertTrue(result["unversionedStaleIgnored"])

    def test_13k_frontend_runtime_cancels_delayed_delta_from_an_old_run(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const runtime = window.UcpFrontendRuntime;
              runtime.dispose();
              const nativeFetch = window.fetch;
              const NativeWebSocket = window.WebSocket;
              const nativeSetTimeout = window.setTimeout;
              const nativeClearTimeout = window.clearTimeout;
              const timers = [];
              const cleared = [];
              let deltaRequests = 0;
              let state = { version: 0, queue_items: [], log_items: [] };

              class FakeWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                static CLOSED = 3;
                constructor() { this.readyState = FakeWebSocket.CONNECTING; }
                close() { this.readyState = FakeWebSocket.CLOSED; }
                send() {}
              }

              const response = payload => ({ ok: true, json: async () => payload });
              window.fetch = url => {
                if (String(url).includes("/api/frontend/delta")) deltaRequests += 1;
                return Promise.resolve(response({ version: 0, queue_items: [], log_items: [] }));
              };
              window.WebSocket = FakeWebSocket;
              window.setTimeout = callback => {
                const timer = { id: timers.length + 1, callback };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => cleared.push(id);

              try {
                runtime.configure({
                  getState: () => state,
                  replaceState: nextState => { state = nextState; },
                  buildMockState: () => ({ version: 0, queue_items: [], log_items: [] }),
                  patchSection: () => [],
                  renderSections: () => {},
                  renderAll: () => {},
                  onConnected: () => {},
                  onSettled: () => {},
                  appendUiLog: () => {},
                });

                await runtime.start();
                runtime.scheduleDelta(200);
                const oldTimer = timers[0];
                runtime.dispose();
                await runtime.start();
                runtime.scheduleDelta(200);
                const currentTimer = timers[1];
                oldTimer.callback();
                runtime.scheduleDelta(200);
                const replacementTimer = timers[2];
                currentTimer.callback();
                replacementTimer.callback();
                await Promise.resolve();

                return {
                  oldTimerCleared: cleared.includes(oldTimer.id),
                  currentTimerCleared: cleared.includes(currentTimer.id),
                  exactlyOneDeltaRequest: deltaRequests === 1,
                };
              } finally {
                runtime.dispose();
                window.fetch = nativeFetch;
                window.WebSocket = NativeWebSocket;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
              }
            }
            """
        )

        self.assertTrue(result["oldTimerCleared"])
        self.assertTrue(result["currentTimerCleared"])
        self.assertTrue(result["exactlyOneDeltaRequest"])

    def test_13ka_rest_action_error_refetches_full_state_for_optimistic_rollback(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const runtime = window.UcpFrontendRuntime;
              runtime.dispose();
              const nativeFetch = window.fetch;
              const NativeWebSocket = window.WebSocket;
              let state = { version: 0, queue_items: [], log_items: [], settings_snapshot: {} };
              const urls = [];

              class FakeWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                static CLOSED = 3;
                constructor() { this.readyState = FakeWebSocket.CONNECTING; }
                close() { this.readyState = FakeWebSocket.CLOSED; }
                send() {}
              }

              const response = payload => ({ ok: true, json: async () => payload });
              window.fetch = url => {
                const text = String(url);
                urls.push(text);
                if (text.includes('/api/frontend/action')) {
                  return Promise.resolve(response({ status: 'error', message: 'save failed' }));
                }
                if (text.includes('/api/frontend/delta')) {
                  return Promise.resolve(response({ version: 1, changed_sections: [], sections: {} }));
                }
                return Promise.resolve(response({ version: 1, queue_items: [], log_items: [], settings_snapshot: {} }));
              };
              window.WebSocket = FakeWebSocket;

              try {
                runtime.configure({
                  getState: () => state,
                  replaceState: nextState => { state = nextState; },
                  buildMockState: () => ({ version: 0, queue_items: [], log_items: [] }),
                  patchSection: () => [],
                  renderSections: () => {},
                  renderAll: () => {},
                  onConnected: () => {},
                  onSettled: () => {},
                  appendUiLog: () => {},
                });
                await runtime.start();
                urls.length = 0;
                runtime.send('frontend_action', {
                  action: 'update_setting',
                  payload: { section: 'download', key: 'max_retries', value: 5 },
                });
                for (let index = 0; index < 20 && urls.length < 2; index += 1) await Promise.resolve();

                return {
                  requestedAction: urls.some(url => url.includes('/api/frontend/action')),
                  requestedState: urls.some(url => url.endsWith('/api/frontend/state')),
                  requestedDelta: urls.some(url => url.includes('/api/frontend/delta')),
                };
              } finally {
                runtime.dispose();
                window.fetch = nativeFetch;
                window.WebSocket = NativeWebSocket;
              }
            }
            """
        )

        self.assertTrue(result["requestedAction"])
        self.assertTrue(result["requestedState"])
        self.assertFalse(result["requestedDelta"])
