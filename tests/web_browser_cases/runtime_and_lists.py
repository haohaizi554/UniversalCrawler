"""WebUI browser cases owned by the runtime and lists responsibility."""

from __future__ import annotations

class RuntimeAndListCases:
    def test_platform_api_failure_restores_full_snapshot_platforms_and_retry(self):
        context = self._browser.new_context(viewport={"width": 1280, "height": 720})
        self.addCleanup(context.close)
        page = context.new_page()
        self.addCleanup(page.close)
        page.add_init_script(
            "Object.defineProperty(window, 'WebSocket', { value: undefined, configurable: true });"
        )
        page.route("**/api/platforms", lambda route: route.abort("failed"))
        page.goto(self._server_url, wait_until="domcontentloaded")
        page.wait_for_selector("#app-shell", state="visible", timeout=5000)
        page.wait_for_function("window.__ucrawlFrontendStateLoaded === true", timeout=5000)
        page.wait_for_function(
            "(document.querySelector('#sourceSelect')?.options.length || 0) >= 5",
            timeout=5000,
        )

        result = page.evaluate(
            """
            () => ({
              ids: Array.from(document.querySelectorAll('#sourceSelect option')).map(option => option.value),
              retryVisible: !document.getElementById('platformRetry')?.hidden,
              loadState: document.getElementById('sourceSelect')?.dataset.loadState || ''
            })
            """
        )
        self.assertEqual(
            result["ids"],
            ["douyin", "xiaohongshu", "kuaishou", "missav", "bilibili"],
        )
        self.assertTrue(result["retryVisible"])
        self.assertEqual(result["loadState"], "degraded")

    def test_failed_detail_consumes_shared_display_projection(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest();
              frontendState.failed_items = [{
                id: 'failed-old',
                title: 'Old failure',
                reason_detail_display: 'Old reason detail',
                status: 'failed'
              }];
              selected.failed = 'failed-old';
              switchPage('failed');
              renderFailed();
            }
            """
        )
        self._page.wait_for_selector(
            "#failedBody tr[data-id='failed-old'].selected",
            state="visible",
            timeout=5000,
        )
        self._page.evaluate(
            """
            () => {
              window.Worker = class DeferredListWorker {
                postMessage() {}
                terminate() {}
              };
              configureListPagesHelpers();
              frontendState.failed_items = [{
                id: 'failed-projected',
                title: 'Projected failure',
                failed_at: '2026-07-12 18:34:48',
                failed_at_table: '07-12 18:34',
                reason: '原始原因',
                reason_detail: '原始原因详情',
                reason_detail_display: 'Projected reason detail',
                platform: 'Bilibili',
                platform_id: 'bilibili',
                trace_id: 'trace-projected',
                status_label: '失败',
                log_excerpt_items: [{ level: 'ERROR', time: 'raw-time', message: '原始日志' }],
                log_excerpt_display_items: [{
                  level: 'ERROR',
                  time_display: '18:34:48',
                  message_display: 'Projected log message'
                }],
                solutions: [{ title: '原始建议', description: '原始说明' }],
                solutions_display: [{
                  title_display: 'Projected solution',
                  description_display: 'Projected solution description',
                  icon_file: 'action_help.png'
                }]
              }];
              const appearance = frontendState.settings_snapshot['外观设置'] || {};
              appearance.language = 'en-US';
              applyAppearance(appearance);
              renderFailed();
            }
            """
        )

        detail = self._page.text_content("#failedDetail")
        solutions = self._page.text_content("#failedSolutions")
        self.assertEqual(self._page.evaluate("selected.failed"), "failed-projected")
        self.assertIn("Projected reason detail", detail)
        self.assertIn("Projected log message", detail)
        self.assertIn("18:34:48", detail)
        self.assertNotIn("原始原因详情", detail)
        self.assertNotIn("原始日志", detail)
        self.assertIn("Projected solution", solutions)
        self.assertIn("Projected solution description", solutions)
        self.assertNotIn("原始建议", solutions)

    def test_00a_status_version_opens_update_check_dialog(self):
        self._goto_ready()
        self._page.evaluate(
            """() => {
              const appearance = frontendState.settings_snapshot['外观设置'] || {};
              appearance.language = 'en-US';
              applyAppearance(appearance);
              renderCurrentPage();
            }"""
        )
        self._page.route(
            "**/api/update/check",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"status":"available","local_version":"3.6.17",'
                    '"latest_version":"3.6.18","notes":"verified release",'
                    '"html_url":"https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18",'
                    '"candidates":[{"version":"3.6.18"}],"can_prepare":true}'
                ),
            ),
        )
        self._page.route(
            "**/api/update/prepare",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"ready","version":"3.6.18","installer_name":"ucrawl-update.exe"}',
            ),
        )
        self._page.route(
            "**/api/update/install",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"installing","version":"3.6.18"}',
            ),
        )

        self._page.click("#statusVersion")
        self._page.wait_for_selector("#updateModal", state="visible", timeout=5000)
        dialog = self._page.evaluate(
            """
            () => ({
              busy: document.getElementById('updateModal').getAttribute('aria-busy'),
              local: document.getElementById('updateLocalVersion').textContent,
              latest: document.getElementById('updateLatestVersion').textContent,
              localLabel: document.getElementById('updateLocalLabel').textContent,
              latestLabel: document.getElementById('updateLatestLabel').textContent,
              notes: document.getElementById('updateNotes').textContent,
              status: document.getElementById('updateStatus').dataset.status,
            })
            """
        )
        self.assertEqual(dialog["busy"], "false")
        self.assertIn("3.6.17", dialog["local"])
        self.assertIn("3.6.18", dialog["latest"])
        self.assertEqual(dialog["localLabel"], "Current version")
        self.assertEqual(dialog["latestLabel"], "Release version")
        self.assertEqual(dialog["notes"], "verified release")
        self.assertEqual(dialog["status"], "available")

        self.assertTrue(self._page.is_visible("#updatePrepareBtn"))
        self.assertFalse(self._page.is_visible("#updateInstallBtn"))
        self._page.click("#updatePrepareBtn")
        self._page.wait_for_function(
            "document.getElementById('updateStatus').dataset.status === 'ready'",
            timeout=5000,
        )
        self.assertIn("ucrawl-update.exe", self._page.text_content("#updateNotes"))
        self.assertTrue(self._page.is_visible("#updateInstallBtn"))
        self._page.click("#updateInstallBtn")
        self._page.wait_for_function(
            "document.getElementById('updateStatus').dataset.status === 'installing' && document.getElementById('updateInstallBtn').hidden",
            timeout=5000,
        )

        self._page.evaluate("document.getElementById('updateCloseBtn').disabled = false; document.getElementById('updateCloseIcon').disabled = false")
        self._page.press("body", "Escape")
        self._page.wait_for_selector("#updateModal", state="hidden", timeout=5000)
        self.assertEqual(self._page.evaluate("document.activeElement?.id"), "statusVersion")

    def test_00_initial_state_never_exposes_mock_tasks_while_loading_or_after_failure(self):
        page = self._context.new_page()
        self.addCleanup(page.close)
        page.add_init_script(
            """
            (() => {
              const nativeFetch = window.fetch.bind(window);
              window.WebSocket = class PendingWebSocket {
                static CONNECTING = 0;
                static OPEN = 1;
                constructor() { this.readyState = 0; }
                close() {}
                send() {}
              };
              window.fetch = (url, options) => String(url).includes('/api/frontend/state')
                ? new Promise(() => {})
                : nativeFetch(url, options);
            })();
            """
        )
        page.goto(self._server_url, wait_until="domcontentloaded")
        page.wait_for_selector("#app-shell", state="visible", timeout=5000)
        page.wait_for_selector("#frontendStateBanner[data-state='loading']", state="visible", timeout=5000)

        loading_state = page.evaluate(
            """
            () => ({
              queueRows: document.querySelectorAll('#queueBody tr[data-id]').length,
              completedRows: document.querySelectorAll('#completedBody tr[data-id]').length,
              failedRows: document.querySelectorAll('#failedBody tr[data-id]').length,
              startDisabled: document.getElementById('startBtn').disabled,
              pageBlocked: document.getElementById('rightPanel').getAttribute('aria-busy'),
            })
            """
        )
        self.assertEqual(loading_state["queueRows"], 0)
        self.assertEqual(loading_state["completedRows"], 0)
        self.assertEqual(loading_state["failedRows"], 0)
        self.assertTrue(loading_state["startDisabled"])
        self.assertEqual(loading_state["pageBlocked"], "true")

        failed_page = self._context.new_page()
        self.addCleanup(failed_page.close)
        failed_page.add_init_script(
            """
            window.WebSocket = class PendingWebSocket {
              static CONNECTING = 0;
              static OPEN = 1;
              constructor() { this.readyState = 0; }
              close() {}
              send() {}
            };
            """
        )
        failed_page.route(
            "**/api/frontend/state",
            lambda route: route.fulfill(status=503, content_type="application/json", body='{"status":"error"}'),
        )
        failed_page.goto(self._server_url, wait_until="domcontentloaded")
        failed_page.wait_for_selector("#frontendStateBanner[data-state='error']", state="visible", timeout=5000)
        failure_state = failed_page.evaluate(
            """
            () => ({
              taskRows: document.querySelectorAll('#queueBody tr[data-id], #completedBody tr[data-id], #failedBody tr[data-id]').length,
              retryVisible: !document.getElementById('frontendStateRetry').hidden,
              startDisabled: document.getElementById('startBtn').disabled,
            })
            """
        )
        self.assertEqual(failure_state["taskRows"], 0)
        self.assertTrue(failure_state["retryVisible"])
        self.assertTrue(failure_state["startDisabled"])

    def test_11ea_controllers_request_optimistic_patches_without_mutating_snapshots(self):
        self._goto_ready()

        result = self._page.evaluate(
            r"""
            async () => {
              const settingsState = {
                settings_snapshot: {
                  '\u57fa\u7840\u8bbe\u7f6e': { download_directory: 'D:/before' },
                  '\u4e0b\u8f7d\u8bbe\u7f6e': { max_retries: 3 },
                  '\u5916\u89c2\u8bbe\u7f6e': { follow_system: true, theme: 'light', scale: '100%' },
                  '\u64ad\u653e\u8bbe\u7f6e': { image_auto_advance_interval_seconds: 5 },
                  '\u5e73\u53f0\u8bbe\u7f6e': [{
                    id: 'demo',
                    proxy: '\u7cfb\u7edf\u4ee3\u7406',
                    proxy_config_key: 'proxy_url',
                    proxy_options: ['\u7cfb\u7edf\u4ee3\u7406', '\u81ea\u5b9a\u4e49']
                  }]
                }
              };
              const settingsBefore = JSON.stringify(settingsState);
              const settingPatches = [];
              const platformPatches = [];
              window.UcpSettingsController.configure({
                getState: () => settingsState,
                t: value => String(value || ''),
                optionLabel: value => String(value || ''),
                byId: id => document.getElementById(id),
                sendWS: () => {},
                patchSetting: (group, key, value) => settingPatches.push({ group, key, value }),
                patchPlatformSetting: (platformId, key, value) => platformPatches.push({ platformId, key, value }),
                syncAppearance: () => {},
                enhanceSelects: () => {}
              });
              window.UcpSettingsController.updateBasic('download_directory', 'D:/basic');
              window.UcpSettingsController.update('download', 'max_retries', 5);
              window.UcpSettingsController.update('common', 'theme', 'dark');
              window.UcpSettingsController.update('appearance', 'scale', '110%');
              window.UcpSettingsController.update('playback', 'image_auto_advance_interval_seconds', '3');
              window.UcpSettingsController.update('demo', 'proxy_url', 'http://127.0.0.1:7890');

              const dialogState = {
                settings_snapshot: { '\u57fa\u7840\u8bbe\u7f6e': { download_directory: 'D:/before' } }
              };
              const dialogBefore = JSON.stringify(dialogState);
              const dialogPatches = [];
              const originalFetch = window.fetch;
              window.fetch = () => Promise.resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ directory: 'D:/confirmed', message: 'changed' })
              });
              window.UcpDialogController.configure({
                getState: () => dialogState,
                t: value => String(value || ''),
                esc,
                escAttr,
                byId: id => document.getElementById(id),
                frontendAction: () => {},
                sendWS: () => {},
                appendUiLog: () => {},
                patchSetting: (group, key, value) => dialogPatches.push({ group, key, value }),
                closePreview: () => {},
                fetchState: () => Promise.resolve()
              });
              document.getElementById('dirInput').value = 'D:/confirmed';
              await window.UcpDialogController.confirmDirectory();
              window.fetch = originalFetch;

              return {
                settingsUnchanged: JSON.stringify(settingsState) === settingsBefore,
                dialogUnchanged: JSON.stringify(dialogState) === dialogBefore,
                settingPatches,
                platformPatches,
                dialogPatches
              };
            }
            """
        )

        self.assertTrue(result["settingsUnchanged"])
        self.assertTrue(result["dialogUnchanged"])
        self.assertEqual(
            result["settingPatches"],
            [
                {"group": "\u57fa\u7840\u8bbe\u7f6e", "key": "download_directory", "value": "D:/basic"},
                {"group": "\u4e0b\u8f7d\u8bbe\u7f6e", "key": "max_retries", "value": 5},
                {"group": "\u5916\u89c2\u8bbe\u7f6e", "key": "follow_system", "value": False},
                {"group": "\u5916\u89c2\u8bbe\u7f6e", "key": "theme", "value": "dark"},
                {"group": "\u5916\u89c2\u8bbe\u7f6e", "key": "scale", "value": "110%"},
                {"group": "\u64ad\u653e\u8bbe\u7f6e", "key": "image_auto_advance_interval_seconds", "value": 3},
            ],
        )
        self.assertEqual(
            result["platformPatches"],
            [
                {"platformId": "demo", "key": "proxy", "value": "http://127.0.0.1:7890"},
                {"platformId": "demo", "key": "proxy_custom_active", "value": True},
                {"platformId": "demo", "key": "proxy_custom_value", "value": "http://127.0.0.1:7890"},
            ],
        )
        self.assertEqual(
            result["dialogPatches"],
            [{"group": "\u57fa\u7840\u8bbe\u7f6e", "key": "download_directory", "value": "D:/confirmed"}],
        )

    def test_11f_stale_selection_reconciles_to_visible_first_row(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              frontendState.active_downloads = [
                { id: 'active-a', title: 'Active A', platform: 'Bilibili', platform_id: 'bilibili', progress: 12, speed: '1 MB/s' }
              ];
              selected.active = 'missing-active';
              renderActive();

              frontendState.completed_items = Array.from({ length: 21 }, (_, index) => {
                const number = index + 1;
                return {
                  id: `completed-${number}`,
                  title: `Completed ${number}`,
                  filename: `completed-${number}.mp4`,
                  completed_at: `2026-07-04 06:${String(number).padStart(2, '0')}:00`,
                  completed_at_table: `07-04 06:${String(number).padStart(2, '0')}`,
                  format: 'MP4'
                };
              });
              window.UcpListPages.setCompletedPageSize(20);
              window.UcpListPages.setCompletedPage(1);
              selected.completed = 'missing-completed';
              window.UcpListPages.renderCompleted();
              const waitForSelectedRow = (selector, expectedId, selectedGetter, label) => new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const selectedRow = document.querySelector(`${selector} tr.selected`);
                  if (selectedGetter() === expectedId && selectedRow && selectedRow.dataset.id === expectedId) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error(`${label} page worker did not render the selected row`));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });
              await waitForSelectedRow('#completedBody', 'completed-21', () => selected.completed, 'completed');

              frontendState.failed_items = [
                { id: 'failed-a', title: 'Failed A', failed_at: '2026-07-04 06:03:00', failed_at_table: '07-04 06:03', reason: '403', reason_label: '链接失败', platform: 'Bilibili', platform_id: 'bilibili', status_label: '失败' }
              ];
              selected.failed = 'missing-failed';
              renderFailed();
              await waitForSelectedRow('#failedBody', 'failed-a', () => selected.failed, 'failed');

              frontendState.toolbox_items = [
                { id: 'tool-a', title: 'Tool A', summary: 'Tool summary', input_example: 'Input A', output_example: 'Output A', icon_file: 'nav_toolbox.png' }
              ];
              selected.tool = 'missing-tool';
              renderToolbox();

              const selectedRows = selector => Array.from(document.querySelectorAll(selector)).map(row => row.dataset.id);
              return {
                activeSelected: selected.active,
                activeRows: selectedRows('#activeBody tr.selected'),
                activeDetail: document.getElementById('activeDetail').textContent,
                completedSelected: selected.completed,
                completedRows: selectedRows('#completedBody tr.selected'),
                completedDetail: document.getElementById('completedDetail').textContent,
                failedSelected: selected.failed,
                failedRows: selectedRows('#failedBody tr.selected'),
                failedDetail: document.getElementById('failedDetail').textContent,
                toolSelected: selected.tool,
                toolCards: Array.from(document.querySelectorAll('#toolGrid .tool-card.active')).map(button => button.textContent),
                toolDetail: document.getElementById('toolDetail').textContent
              };
            }
            """
        )

        self.assertEqual(result["activeSelected"], "active-a")
        self.assertEqual(result["activeRows"], ["active-a"])
        self.assertIn("Active A", result["activeDetail"])
        self.assertEqual(result["completedSelected"], "completed-21")
        self.assertEqual(result["completedRows"], ["completed-21"])
        self.assertIn("completed-21.mp4", result["completedDetail"])
        self.assertEqual(result["failedSelected"], "failed-a")
        self.assertEqual(result["failedRows"], ["failed-a"])
        self.assertIn("Failed A", result["failedDetail"])
        self.assertEqual(result["toolSelected"], "tool-a")
        self.assertEqual(len(result["toolCards"]), 1)
        self.assertIn("Tool A", result["toolCards"][0])
        self.assertIn("Tool A", result["toolDetail"])

    def test_split_frontend_modules_load_and_survive_navigation(self):
        errors: list[str] = []
        self._page.on("pageerror", lambda error: errors.append(str(error)))

        self._goto_ready()
        module_contracts = self._page.evaluate(
            """
            () => [
              'UcpFrontendRuntime',
              'UcpListPages',
              'UcpLogI18n',
              'UcpLogCenter',
              'UcpSettingsController',
              'UcpDialogController',
              'UcpPlaybackController'
            ].map(name => ({
              name,
              namespace: typeof window[name],
              configure: typeof window[name]?.configure,
              dispose: typeof window[name]?.dispose
            }))
            """
        )
        self.assertTrue(
            all(
                contract["namespace"] == "object"
                and contract["configure"] == "function"
                and contract["dispose"] == "function"
                for contract in module_contracts
            ),
            module_contracts,
        )

        for page_id in ("queue", "active", "completed", "failed", "logs", "settings", "toolbox"):
            self._page.evaluate("pageId => switchPage(pageId)", page_id)
            self._page.wait_for_selector(
                f"#page-{page_id}.active",
                state="visible",
                timeout=5000,
            )

        self._page.evaluate(
            """
            () => {
              for (const name of [
                'UcpFrontendRuntime',
                'UcpListPages',
                'UcpLogI18n',
                'UcpLogCenter',
                'UcpSettingsController',
                'UcpDialogController',
                'UcpPlaybackController'
              ]) {
                window[name].dispose();
                window[name].dispose();
              }
            }
            """
        )
        self.assertEqual(errors, [])

    def test_13f_list_pages_reject_stale_workers_and_preserve_shared_selection(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const nativeWorker = window.Worker;
              const workers = [];
              const selection = { active: "", completed: "", failed: "", queue: "" };
              const state = {
                settings_snapshot: {},
                queue_items: [],
                active_downloads: [],
                completed_items: [{ id: "old-completed", title: "Old completed", format: "MP4" }],
                failed_items: []
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
                emit(result) { this.onmessage?.({ data: result }); }
              }

              const configure = () => window.UcpListPages.configure({
                getState: () => state,
                getSelection: domain => selection[domain] || "",
                setSelection: (domain, id) => { selection[domain] = String(id || ""); },
                t: value => String(value),
                esc,
                escAttr,
                byId,
                frontendAction: () => {},
                playCompleted: () => {},
                renderStatus: () => {}
              });
              const resultFor = (request, item) => ({
                type: "page",
                pageKey: request.pageKey,
                sequence: request.sequence,
                totalCount: 1,
                totalPages: 1,
                currentPage: 1,
                pageSize: request.pageSize,
                pageItems: [item],
                selectedId: item.id
              });

              window.Worker = ControlledWorker;
              window.UcpListPages.dispose();
              try {
                configure();
                window.UcpListPages.renderCompleted();
                const obsoleteWorker = workers[0];
                const obsoleteRequest = obsoleteWorker.requests[0];

                state.completed_items = [{ id: "current-a", title: "Current A", format: "MP4" }];
                configure();
                window.UcpListPages.renderCompleted();
                const currentWorker = workers[1];
                const firstCurrentRequest = currentWorker.requests[0];
                obsoleteWorker.emit(resultFor(obsoleteRequest, { id: "old-completed", title: "Old completed", format: "MP4" }));
                const generationIgnored = selection.completed === "";

                state.completed_items = [{ id: "current-b", title: "Current B", format: "MP4" }];
                window.UcpListPages.renderCompleted();
                const secondCurrentRequest = currentWorker.requests[1];
                currentWorker.emit(resultFor(firstCurrentRequest, { id: "current-a", title: "Current A", format: "MP4" }));
                const sequenceIgnored = selection.completed === "";
                currentWorker.emit(resultFor(secondCurrentRequest, state.completed_items[0]));

                return {
                  generationIgnored,
                  sequenceIgnored,
                  sharedSelection: selection.completed,
                  selectedRows: Array.from(document.querySelectorAll("#completedBody tr.selected")).map(row => row.dataset.id),
                  obsoleteTerminatedOnce: obsoleteWorker.terminateCalls === 1
                };
              } finally {
                window.UcpListPages.dispose();
                window.Worker = nativeWorker;
                if (typeof configureListPagesHelpers === "function") configureListPagesHelpers();
              }
            }
            """
        )

        self.assertTrue(result["generationIgnored"])
        self.assertTrue(result["sequenceIgnored"])
        self.assertEqual(result["sharedSelection"], "current-b")
        self.assertEqual(result["selectedRows"], ["current-b"])
        self.assertTrue(result["obsoleteTerminatedOnce"])

    def test_13g_list_pages_schedule_fallback_and_dispose_idempotently(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const nativeWorker = window.Worker;
              const nativeSetTimeout = window.setTimeout;
              const nativeClearTimeout = window.clearTimeout;
              const timers = [];
              const clearedTimers = [];
              const selection = { active: "", completed: "", failed: "", queue: "" };
              const state = {
                settings_snapshot: {},
                queue_items: [{ id: "queue-fallback", title: "Queue fallback" }],
                active_downloads: [],
                completed_items: [{ id: "completed-fallback", title: "Completed fallback", format: "MP4" }],
                failed_items: [{ id: "failed-fallback", title: "Failed fallback", reason: "403" }]
              };
              let workerTerminateCalls = 0;

              class ControlledWorker {
                postMessage() {}
                terminate() { workerTerminateCalls += 1; }
              }

              const configure = () => window.UcpListPages.configure({
                getState: () => state,
                getSelection: domain => selection[domain] || "",
                setSelection: (domain, id) => { selection[domain] = String(id || ""); },
                t: value => String(value),
                esc,
                escAttr,
                byId,
                frontendAction: () => {},
                playCompleted: () => {},
                renderStatus: () => {}
              });

              window.UcpListPages.dispose();
              try {
                window.Worker = ControlledWorker;
                configure();
                window.UcpListPages.renderQueue();
                window.UcpListPages.dispose();
                window.UcpListPages.dispose();

                window.Worker = undefined;
                let nextTimerId = 1;
                window.setTimeout = callback => {
                  const timer = { id: nextTimerId++, callback };
                  timers.push(timer);
                  return timer.id;
                };
                window.clearTimeout = timerId => { clearedTimers.push(timerId); };

                configure();
                document.getElementById("queueBody").innerHTML = "";
                window.UcpListPages.renderQueue();
                const firstTimer = timers[0];
                const fallbackWasScheduled = document.querySelector("#queueBody tr[data-id]") === null;
                firstTimer.callback();
                const fallbackRendered = document.querySelector("#queueBody tr[data-id]")?.dataset.id === "queue-fallback";

                configure();
                for (const id of ["queueBody", "completedBody", "failedBody"]) document.getElementById(id).innerHTML = "";
                window.UcpListPages.renderQueue();
                window.UcpListPages.renderCompleted();
                window.UcpListPages.renderFailed();
                const pendingTimers = timers.slice(1);
                window.UcpListPages.dispose();
                window.UcpListPages.dispose();
                pendingTimers.forEach(timer => timer.callback());

                return {
                  workerTerminatedOnce: workerTerminateCalls === 1,
                  fallbackWasScheduled,
                  fallbackRendered,
                  allFallbacksCancelled: pendingTimers.length === 3 && pendingTimers.every(timer => clearedTimers.includes(timer.id)),
                  staleFallbackRows: ["queueBody", "completedBody", "failedBody"].some(id => document.querySelector(`#${id} tr[data-id]`))
                };
              } finally {
                window.UcpListPages.dispose();
                window.Worker = nativeWorker;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
                if (typeof configureListPagesHelpers === "function") configureListPagesHelpers();
              }
            }
            """
        )

        self.assertTrue(result["workerTerminatedOnce"])
        self.assertTrue(result["fallbackWasScheduled"])
        self.assertTrue(result["fallbackRendered"])
        self.assertTrue(result["allFallbacksCancelled"])
        self.assertFalse(result["staleFallbackRows"])

    def test_13ga_list_pages_copy_diagnostics_handles_success_failures_and_stale_responses(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const baseDependencies = {
                getState: () => ({ failed_items: [] }),
                getSelection: () => '',
                setSelection: () => {},
                t: value => String(value || ''),
                esc,
                escAttr,
                byId,
                frontendAction: () => {},
                playCompleted: () => {},
                renderStatus: () => {}
              };
              const configure = overrides => window.UcpListPages.configure({ ...baseDependencies, ...overrides });
              const response = (status, data) => ({
                ok: status >= 200 && status < 300,
                status,
                json: () => Promise.resolve(data)
              });

              const success = { requests: [], clipboard: [], logs: [] };
              configure({
                request: (url, options) => {
                  success.requests.push({ url, options });
                  return Promise.resolve(response(200, { data: { text: 'trace-success' } }));
                },
                writeClipboard: text => { success.clipboard.push(text); return Promise.resolve(true); },
                appendUiLog: (label, detail, prefix) => { success.logs.push({ label, detail, prefix }); }
              });
              success.returned = await window.UcpListPages.copyDiagnostics('failed-success');

              const http = { clipboard: [], logs: [] };
              configure({
                request: () => Promise.resolve(response(503, { error: 'service unavailable' })),
                writeClipboard: text => { http.clipboard.push(text); return Promise.resolve(true); },
                appendUiLog: (label, detail, prefix) => { http.logs.push({ label, detail, prefix }); }
              });
              http.returned = await window.UcpListPages.copyDiagnostics('failed-http');

              const network = { clipboard: [], logs: [] };
              configure({
                request: () => Promise.reject(new Error('offline network')),
                writeClipboard: text => { network.clipboard.push(text); return Promise.resolve(true); },
                appendUiLog: (label, detail, prefix) => { network.logs.push({ label, detail, prefix }); }
              });
              network.returned = await window.UcpListPages.copyDiagnostics('failed-network');

              let resolveOldRequest;
              const stale = { clipboard: [], logs: [] };
              configure({
                request: () => new Promise(resolve => { resolveOldRequest = resolve; }),
                writeClipboard: text => { stale.clipboard.push(text); return Promise.resolve(true); },
                appendUiLog: (label, detail, prefix) => { stale.logs.push({ label, detail, prefix }); }
              });
              const oldOperation = window.UcpListPages.copyDiagnostics('failed-stale');

              const current = { clipboard: [], logs: [] };
              configure({
                request: () => Promise.resolve(response(200, { data: { text: 'trace-current' } })),
                writeClipboard: text => { current.clipboard.push(text); return Promise.resolve(true); },
                appendUiLog: (label, detail, prefix) => { current.logs.push({ label, detail, prefix }); }
              });
              resolveOldRequest(response(200, { data: { text: 'trace-stale' } }));
              stale.returned = await oldOperation;
              current.returned = await window.UcpListPages.copyDiagnostics('failed-current');
              window.UcpListPages.dispose();
              window.UcpListPages.dispose();

              return {
                success: {
                  returned: success.returned,
                  url: success.requests[0]?.url,
                  method: success.requests[0]?.options?.method,
                  body: JSON.parse(success.requests[0]?.options?.body || '{}'),
                  clipboard: success.clipboard,
                  logs: success.logs
                },
                http,
                network,
                stale,
                current
              };
            }
            """
        )

        self.assertTrue(result["success"]["returned"])
        self.assertEqual(result["success"]["url"], "/api/frontend/action")
        self.assertEqual(result["success"]["method"], "POST")
        self.assertEqual(
            result["success"]["body"],
            {"action": "copy_diagnostics", "payload": {"id": "failed-success"}},
        )
        self.assertEqual(result["success"]["clipboard"], ["trace-success"])
        self.assertEqual(len(result["success"]["logs"]), 1)
        self.assertFalse(result["http"]["returned"])
        self.assertEqual(result["http"]["clipboard"], [])
        self.assertTrue(any("HTTP 503" in str(entry.get("detail", "")) for entry in result["http"]["logs"]))
        self.assertFalse(result["network"]["returned"])
        self.assertEqual(result["network"]["clipboard"], [])
        self.assertTrue(any("offline network" in str(entry.get("detail", "")) for entry in result["network"]["logs"]))
        self.assertFalse(result["stale"]["returned"])
        self.assertEqual(result["stale"]["clipboard"], [])
        self.assertEqual(result["stale"]["logs"], [])
        self.assertTrue(result["current"]["returned"])
        self.assertEqual(result["current"]["clipboard"], ["trace-current"])

    def test_13h_completed_reconciliation_preserves_global_selection_until_explicit_select(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              frontendState.queue_items = [{ id: "queue-global", title: "Queue global" }];
              frontendState.completed_items = [
                { id: "completed-auto", title: "Completed auto", format: "MP4" },
                { id: "completed-explicit", title: "Completed explicit", format: "MP4" }
              ];
              selectedVideoId = "queue-global";
              selected.completed = "";
              window.UcpListPages.renderQueue();
              window.UcpListPages.renderCompleted();

              const waitForCompleted = expectedId => new Promise((resolve, reject) => {
                const deadline = performance.now() + 3000;
                const tick = () => {
                  const row = document.querySelector("#completedBody tr.selected");
                  if (selected.completed === expectedId && row?.dataset.id === expectedId) {
                    resolve();
                    return;
                  }
                  if (performance.now() > deadline) {
                    reject(new Error(`completed selection did not become ${expectedId}`));
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                tick();
              });

              await waitForCompleted("completed-auto");
              const afterAutomatic = {
                completed: selected.completed,
                global: selectedVideoId
              };

              window.UcpListPages.selectCompleted("completed-explicit");
              await waitForCompleted("completed-explicit");
              return {
                afterAutomatic,
                afterExplicit: {
                  completed: selected.completed,
                  global: selectedVideoId
                }
              };
            }
            """
        )

        self.assertEqual(result["afterAutomatic"], {
            "completed": "completed-auto",
            "global": "queue-global",
        })
        self.assertEqual(result["afterExplicit"], {
            "completed": "completed-explicit",
            "global": "completed-explicit",
        })

    def test_13i_list_pages_worker_onerror_keeps_worker_and_guards_fallback(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const nativeWorker = window.Worker;
              const nativeSetTimeout = window.setTimeout;
              const nativeClearTimeout = window.clearTimeout;
              const workers = [];
              const timers = [];
              const clearedTimers = [];
              const selection = { active: "", completed: "", failed: "", queue: "" };
              const state = {
                settings_snapshot: {},
                queue_items: [],
                active_downloads: [],
                completed_items: [{ id: "completed-old", title: "Completed old", format: "MP4" }],
                failed_items: []
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
                fail() {
                  const event = {
                    defaultPrevented: false,
                    preventDefault() { this.defaultPrevented = true; }
                  };
                  this.onerror?.(event);
                  return event;
                }
              }

              const configure = () => window.UcpListPages.configure({
                getState: () => state,
                getSelection: domain => selection[domain] || "",
                setSelection: (domain, id) => { selection[domain] = String(id || ""); },
                t: value => String(value),
                esc,
                escAttr,
                byId,
                frontendAction: () => {},
                playCompleted: () => {},
                renderStatus: () => {}
              });
              const resultFor = (request, item) => ({
                type: "page",
                pageKey: request.pageKey,
                sequence: request.sequence,
                totalCount: 1,
                totalPages: 1,
                currentPage: 1,
                pageSize: request.pageSize,
                pageItems: [item],
                selectedId: item.id
              });

              window.Worker = ControlledWorker;
              window.setTimeout = callback => {
                const timer = { id: timers.length + 1, callback };
                timers.push(timer);
                return timer.id;
              };
              window.clearTimeout = timerId => { clearedTimers.push(timerId); };
              window.UcpListPages.dispose();
              try {
                configure();
                document.getElementById("completedBody").innerHTML = "";
                window.UcpListPages.renderCompleted();
                const worker = workers[0];
                const errorEvent = worker.fail();
                const fallbacksAfterError = timers.slice();
                const workerStayedUsable = worker.terminateCalls === 0;

                state.completed_items = [{ id: "completed-current", title: "Completed current", format: "MP4" }];
                window.UcpListPages.renderCompleted();
                const newerRequest = worker.requests[1] || null;
                const staleFallback = fallbacksAfterError[0] || null;
                if (staleFallback) staleFallback.callback();
                const staleFallbackIgnored = selection.completed === ""
                  && document.querySelector("#completedBody tr[data-id]") === null;

                if (newerRequest) worker.emit(resultFor(newerRequest, state.completed_items[0]));
                return {
                  errorPrevented: errorEvent.defaultPrevented,
                  workerStayedUsable,
                  onlyCurrentFallbackScheduled: fallbacksAfterError.length === 1,
                  staleFallbackCancelled: Boolean(staleFallback && clearedTimers.includes(staleFallback.id)),
                  staleFallbackIgnored,
                  newerRequestPosted: Boolean(newerRequest),
                  newerResultRendered: selection.completed === "completed-current"
                    && document.querySelector("#completedBody tr.selected")?.dataset.id === "completed-current"
                };
              } finally {
                window.UcpListPages.dispose();
                window.Worker = nativeWorker;
                window.setTimeout = nativeSetTimeout;
                window.clearTimeout = nativeClearTimeout;
                if (typeof configureListPagesHelpers === "function") configureListPagesHelpers();
              }
            }
            """
        )

        self.assertTrue(result["errorPrevented"])
        self.assertTrue(result["workerStayedUsable"])
        self.assertTrue(result["onlyCurrentFallbackScheduled"])
        self.assertTrue(result["staleFallbackCancelled"])
        self.assertTrue(result["staleFallbackIgnored"])
        self.assertTrue(result["newerRequestPosted"])
        self.assertTrue(result["newerResultRendered"])

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
