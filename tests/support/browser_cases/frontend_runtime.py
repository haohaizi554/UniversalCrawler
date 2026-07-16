"""WebUI browser cases for frontend runtime lifecycle and compatibility."""

from __future__ import annotations


class FrontendRuntimeCases:
    def test_13l_runtime_compatibility_globals_delegate_to_the_public_service(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const nativeRuntime = window.UcpFrontendRuntime;
              const calls = [];
              window.UcpFrontendRuntime = Object.freeze({
                ...nativeRuntime,
                fetchState: (...args) => { calls.push(["fetchState", ...args]); return Promise.resolve("state"); },
                fetchDelta: (...args) => { calls.push(["fetchDelta", ...args]); return Promise.resolve("delta"); },
                scheduleSections: (...args) => { calls.push(["scheduleSections", ...args]); return "sections"; },
                send: (...args) => { calls.push(["send", ...args]); return true; },
              });
              try {
                const types = Object.fromEntries([
                  "fetchFrontendState",
                  "fetchFrontendDelta",
                  "scheduleRenderSections",
                  "sendWS",
                ].map(name => [name, typeof window[name]]));
                const values = [
                  await window.fetchFrontendState("state-arg"),
                  await window.fetchFrontendDelta("delta-arg"),
                  window.scheduleRenderSections(["queue_items"]),
                  window.sendWS("crawl_state", { running: true }),
                ];
                return { types, values, calls };
              } finally {
                window.UcpFrontendRuntime = nativeRuntime;
              }
            }
            """
        )

        self.assertEqual(set(result["types"].values()), {"function"})
        self.assertEqual(result["values"], ["state", "delta", "sections", True])
        self.assertEqual(
            result["calls"],
            [
                ["fetchState", "state-arg"],
                ["fetchDelta", "delta-arg"],
                ["scheduleSections", ["queue_items"]],
                ["send", "crawl_state", {"running": True}],
            ],
        )

    def test_13m_stale_callbacks_preserve_current_reconnect_and_render_handles(self):
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
              const nativeRequestAnimationFrame = window.requestAnimationFrame;
              const nativeCancelAnimationFrame = window.cancelAnimationFrame;
              const timers = [];
              const clearedTimers = [];
              const frames = [];
              const cancelledFrames = [];
              const sockets = [];
              const renderedSections = [];
              let state = { version: 0, queue_items: [], log_items: [] };

              class FakeWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                static CLOSED = 3;
                constructor() {
                  this.readyState = FakeWebSocket.CONNECTING;
                  sockets.push(this);
                }
                close() { this.readyState = FakeWebSocket.CLOSED; }
                send() {}
              }

              const response = payload => ({ ok: true, json: async () => payload });
              window.fetch = () => Promise.resolve(response({ version: 0, queue_items: [], log_items: [] }));
              window.WebSocket = FakeWebSocket;
              window.setTimeout = callback => {
                const timer = { id: timers.length + 1, callback };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = id => clearedTimers.push(id);
              window.requestAnimationFrame = callback => {
                const frame = { id: frames.length + 1, callback };
                frames.push(frame);
                return frame.id;
              };
              window.cancelAnimationFrame = id => cancelledFrames.push(id);

              try {
                runtime.configure({
                  getState: () => state,
                  replaceState: nextState => { state = nextState; },
                  buildMockState: () => ({ version: 0, queue_items: [], log_items: [] }),
                  patchSection: () => [],
                  renderSections: sections => renderedSections.push(Array.from(sections)),
                  renderAll: () => {},
                  onConnected: () => {},
                  onSettled: () => {},
                  appendUiLog: () => {},
                });

                await runtime.start();
                const oldSocket = sockets[0];
                runtime.scheduleSections(["run1"]);
                const oldFrame = frames[0];
                oldSocket.onclose();
                const oldReconnect = timers[0];
                runtime.dispose();

                await runtime.start();
                const currentSocket = sockets[1];
                runtime.scheduleSections(["run2"]);
                const currentFrame = frames[1];
                currentSocket.onclose();
                const currentReconnect = timers[1];

                oldFrame.callback();
                runtime.scheduleSections(["run2-extra"]);
                oldReconnect.callback();
                const replacementSocket = runtime.connect();
                replacementSocket.onclose();
                const replacementReconnect = timers[2];

                currentReconnect.callback();
                replacementReconnect.callback();
                currentFrame.callback();
                if (frames[2]) frames[2].callback();

                return {
                  oldFrameCancelled: cancelledFrames.includes(oldFrame.id),
                  currentFramePreserved: frames.length === 2,
                  currentReconnectCleared: clearedTimers.includes(currentReconnect.id),
                  renderedOnce: renderedSections.length === 1,
                };
              } finally {
                runtime.dispose();
                window.fetch = nativeFetch;
                window.WebSocket = NativeWebSocket;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
                window.requestAnimationFrame = nativeRequestAnimationFrame;
                window.cancelAnimationFrame = nativeCancelAnimationFrame;
              }
            }
            """
        )

        self.assertTrue(result["oldFrameCancelled"])
        self.assertTrue(result["currentFramePreserved"])
        self.assertTrue(result["currentReconnectCleared"])
        self.assertTrue(result["renderedOnce"])
