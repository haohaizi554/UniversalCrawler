"""WebUI browser cases owned by log center worker lifecycle behavior."""

from __future__ import annotations


class LogCenterWorkerCases:
    def test_13d_log_center_ignores_stale_worker_errors_and_retries_current_detail(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const nativeWorker = window.Worker;
              const workers = [];
              const state = {
                log_items: [{
                  id: "worker-log",
                  time: "2026-07-10 09:00:00",
                  level: "INFO",
                  source: "GUI",
                  trace_id: "worker-trace",
                  message_summary: "initial message",
                  message: "initial message",
                  detail: { description: "same", nested: { alpha: 1, beta: 1 } },
                  stack: ""
                }],
                settings_snapshot: {}
              };

              class ControlledWorker {
                constructor(url) {
                  this.url = String(url);
                  this.requests = [];
                  this.terminateCalls = 0;
                  workers.push(this);
                }
                postMessage(request) { this.requests.push(request); }
                terminate() { this.terminateCalls += 1; }
                emit(payload) { this.onmessage?.({ data: payload }); }
                fail() { this.onerror?.(new Event("error")); }
              }

              const workerFor = name => workers.find(worker => worker.url.includes(name));
              const detailWorkers = () => workers.filter(worker => worker.url.includes("log_detail_worker"));
              const queryResult = request => window.UcpLogDisplay.queryLogItems(request);
              const detailResult = request => {
                const detailJson = JSON.stringify(request.item.detail, null, 2);
                return {
                  sequence: request.sequence,
                  itemId: request.itemId,
                  item: request.item,
                  detailJson,
                  detailDisplayText: detailJson,
                  fullJson: JSON.stringify({ detail: request.item.detail }, null, 2),
                  stack: "",
                  filename: "worker-log.json"
                };
              };

              window.Worker = ControlledWorker;
              window.UcpLogCenter.dispose();
              try {
                window.UcpLogCenter.configure({
                  getState: () => state,
                  getLanguage: () => "zh-CN",
                  t: value => String(value),
                  esc,
                  escAttr,
                  byId,
                  writeClipboard: () => Promise.resolve(true),
                  runOperation: () => {},
                  onFiltersChange: () => {}
                });
                byId("logTimeFilter").value = "all";
                window.UcpLogCenter.syncFiltersFromDom();
                switchPage("logs");

                const queryWorker = workerFor("log_query_worker");
                const firstQuery = queryWorker.requests.at(-1);
                state.log_items[0].message_summary = "query current";
                state.log_items[0].message = "query current";
                window.UcpLogCenter.render();
                const secondQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "error", sequence: firstQuery.sequence, message: "stale query error" });
                const staleQueryIgnored = queryWorker.terminateCalls === 0;
                if (!staleQueryIgnored) {
                  return {
                    staleQueryIgnored,
                    detailMutationRequested: false,
                    staleDetailIgnored: false,
                    stableOrderCacheHit: false,
                    genericErrorRetried: false,
                    renderedJson: ""
                  };
                }
                queryWorker.emit({ type: "result", result: queryResult(secondQuery) });

                const detailWorker = detailWorkers()[0];
                const firstDetail = detailWorker.requests[0];
                state.log_items[0].message_summary = "detail current";
                state.log_items[0].message = "detail current";
                state.log_items[0].detail = { description: "same", nested: { alpha: 1, beta: 2 } };
                window.UcpLogCenter.render();
                const thirdQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: queryResult(thirdQuery) });
                const secondDetail = detailWorker.requests[1];
                const detailMutationRequested = Boolean(secondDetail);
                detailWorker.emit({ type: "error", sequence: firstDetail.sequence, message: "stale detail error" });
                const staleDetailIgnored = detailWorker.terminateCalls === 0
                  && document.getElementById("logDetail").textContent.includes("detail current");
                if (secondDetail) detailWorker.emit({ type: "result", result: detailResult(secondDetail) });

                state.log_items[0].detail = { nested: { beta: 2, alpha: 1 }, description: "same" };
                window.UcpLogCenter.render();
                const fourthQuery = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: queryResult(fourthQuery) });
                const stableOrderCacheHit = detailWorker.requests.length === 2;

                detailWorker.fail();
                const retryWorker = detailWorkers()[1];
                const genericErrorRetried = Boolean(retryWorker && retryWorker.requests.length === 1);
                if (retryWorker) retryWorker.emit({ type: "result", result: detailResult(retryWorker.requests[0]) });
                const renderedJson = document.querySelector("#logDetail .log-detail-readable")?.dataset.json || "";
                return {
                  staleQueryIgnored,
                  detailMutationRequested,
                  staleDetailIgnored,
                  stableOrderCacheHit,
                  genericErrorRetried,
                  renderedJson
                };
              } finally {
                window.UcpLogCenter.dispose();
                window.Worker = nativeWorker;
              }
            }
            """
        )

        self.assertTrue(result["staleQueryIgnored"])
        self.assertTrue(result["detailMutationRequested"])
        self.assertTrue(result["staleDetailIgnored"])
        self.assertTrue(result["stableOrderCacheHit"])
        self.assertTrue(result["genericErrorRetried"])
        self.assertIn('"beta": 2', result["renderedJson"])

    def test_13e_log_center_dispose_is_idempotent_and_cancels_pending_fallback(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest();
              const nativeWorker = window.Worker;
              const nativeSetTimeout = window.setTimeout;
              const nativeClearTimeout = window.clearTimeout;
              const workers = [];
              const timers = [];
              const clearedTimers = [];
              const state = {
                log_items: [{
                  id: "dispose-log",
                  time: "2026-07-10 10:00:00",
                  level: "INFO",
                  source: "GUI",
                  trace_id: "dispose-trace",
                  message_summary: "dispose message",
                  message: "dispose message",
                  detail: { description: "dispose message" },
                  stack: ""
                }],
                settings_snapshot: {}
              };

              class ControlledWorker {
                constructor(url) {
                  this.url = String(url);
                  this.requests = [];
                  this.terminateCalls = 0;
                  workers.push(this);
                }
                postMessage(request) { this.requests.push(request); }
                terminate() { this.terminateCalls += 1; }
                emit(payload) { this.onmessage?.({ data: payload }); }
              }

              const configure = () => {
                window.UcpLogCenter.configure({
                  getState: () => state,
                  getLanguage: () => "zh-CN",
                  t: value => String(value),
                  esc,
                  escAttr,
                  byId,
                  writeClipboard: () => Promise.resolve(true),
                  runOperation: () => {},
                  onFiltersChange: () => {}
                });
                byId("logTimeFilter").value = "all";
                window.UcpLogCenter.syncFiltersFromDom();
              };

              window.Worker = ControlledWorker;
              window.UcpLogCenter.dispose();
              try {
                configure();
                switchPage("logs");
                const queryWorker = workers.find(worker => worker.url.includes("log_query_worker"));
                const queryRequest = queryWorker.requests.at(-1);
                queryWorker.emit({ type: "result", result: window.UcpLogDisplay.queryLogItems(queryRequest) });
                const detailWorker = workers.find(worker => worker.url.includes("log_detail_worker"));
                window.UcpLogCenter.dispose();
                window.UcpLogCenter.dispose();

                document.getElementById("logBody").innerHTML = "";
                document.getElementById("logDetail").innerHTML = "";
                state.log_items[0].message_summary = "fallback must not render";
                state.log_items[0].message = "fallback must not render";
                window.Worker = undefined;
                let nextTimerId = 1;
                window.setTimeout = callback => {
                  const timer = { id: nextTimerId++, callback };
                  timers.push(timer);
                  return timer.id;
                };
                window.clearTimeout = timerId => { clearedTimers.push(timerId); };
                configure();
                window.UcpLogCenter.render();
                const pendingTimer = timers.at(-1);
                window.UcpLogCenter.dispose();
                window.UcpLogCenter.dispose();
                pendingTimer.callback();
                return {
                  queryTerminatedOnce: queryWorker.terminateCalls === 1,
                  detailTerminatedOnce: detailWorker.terminateCalls === 1,
                  fallbackCancelled: clearedTimers.includes(pendingTimer.id),
                  fallbackRendered: document.getElementById("page-logs").textContent.includes("fallback must not render")
                };
              } finally {
                window.UcpLogCenter.dispose();
                window.Worker = nativeWorker;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
              }
            }
            """
        )

        self.assertTrue(result["queryTerminatedOnce"])
        self.assertTrue(result["detailTerminatedOnce"])
        self.assertTrue(result["fallbackCancelled"])
        self.assertFalse(result["fallbackRendered"])

    def test_13f_log_detail_worker_constructor_failure_keeps_readable_summary(self):
        self._goto_ready()
        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              const nativeWorker = window.Worker;
              const state = {
                log_items: [{
                  id: 'constructor-failure-log',
                  time: '2026-07-12 20:21:22',
                  level: 'ERROR',
                  source: 'Downloader',
                  trace_id: 'trace-constructor-failure',
                  message_summary: 'Readable selected summary',
                  message: 'Readable selected summary',
                  detail: { description: 'detail should remain worker-owned' },
                  stack: ''
                }],
                settings_snapshot: {}
              };
              class QueryOnlyWorker {
                constructor(url) {
                  this.url = String(url);
                  if (this.url.includes('log_detail_worker')) throw new Error('detail worker unavailable');
                }
                postMessage(request) {
                  queueMicrotask(() => this.onmessage?.({
                    data: { type: 'result', result: window.UcpLogDisplay.queryLogItems(request) }
                  }));
                }
                terminate() {}
              }
              window.Worker = QueryOnlyWorker;
              window.UcpLogCenter.dispose();
              try {
                window.UcpLogCenter.configure({
                  getState: () => state,
                  getLanguage: () => 'en-US',
                  t: value => ({
                    '\u65e5\u5fd7\u8be6\u60c5': 'Log details',
                    '\u8be6\u7ec6\u4fe1\u606f': 'Details',
                    '\u590d\u5236': 'Copy',
                    '\u5bfc\u51fa': 'Export',
                    '\u91cd\u8bd5': 'Retry',
                    '\u65e5\u5fd7\u8be6\u60c5\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u91cd\u8bd5': 'Log details are temporarily unavailable. Retry.'
                  }[String(value)] || String(value)),
                  esc,
                  escAttr,
                  byId,
                  writeClipboard: () => Promise.resolve(true),
                  runOperation: () => {},
                  onFiltersChange: () => {}
                });
                byId('logTimeFilter').value = 'all';
                window.UcpLogCenter.syncFiltersFromDom();
                switchPage('logs');
                await new Promise((resolve, reject) => {
                  const deadline = performance.now() + 3000;
                  const tick = () => {
                    const retry = document.getElementById('logDetailRetry');
                    if (retry) return resolve();
                    if (performance.now() > deadline) return reject(new Error('unavailable log detail fallback was not rendered'));
                    requestAnimationFrame(tick);
                  };
                  tick();
                });
                const root = document.getElementById('logDetail');
                return {
                  text: root.textContent,
                  retryVisible: !document.getElementById('logDetailRetry').hidden,
                  readableJson: Boolean(root.querySelector('.log-detail-readable')),
                  enabledActions: Array.from(root.querySelectorAll('.log-inspector-actions button')).filter(button => !button.disabled).length
                };
              } finally {
                window.UcpLogCenter.dispose();
                window.Worker = nativeWorker;
              }
            }
            """
        )

        self.assertIn("Readable selected summary", result["text"])
        self.assertIn("Log details are temporarily unavailable", result["text"])
        self.assertTrue(result["retryVisible"])
        self.assertFalse(result["readableJson"])
        self.assertEqual(result["enabledActions"], 0)
