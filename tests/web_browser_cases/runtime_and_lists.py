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
        self._page.wait_for_function(
            "document.getElementById('updateModal').getAttribute('aria-busy') === 'false'",
            timeout=5000,
        )
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

    def test_00aa_update_check_paints_loading_state_before_request_finishes(self):
        self._goto_ready()
        self._page.evaluate(
            """
            () => {
              const nativeFetch = window.fetch.bind(window);
              window.__nativeFetchBeforeUpdateLoadingTest = nativeFetch;
              window.__resolveDeferredUpdateCheck = null;
              window.fetch = (url, options) => {
                if (!String(url).includes('/api/update/check')) return nativeFetch(url, options);
                return new Promise(resolve => {
                  window.__resolveDeferredUpdateCheck = () => resolve({
                    ok: true,
                    status: 200,
                    json: async () => ({
                      status: 'current',
                      local_version: '3.6.17',
                      latest_version: '3.6.17',
                      notes: 'already current'
                    })
                  });
                });
              };
            }
            """
        )
        self.addCleanup(
            lambda: self._page.evaluate(
                """() => {
                  if (window.__nativeFetchBeforeUpdateLoadingTest) {
                    window.fetch = window.__nativeFetchBeforeUpdateLoadingTest;
                  }
                  closeUpdateCheckModal();
                }"""
            )
        )

        self._page.click("#statusVersion")
        self._page.wait_for_selector("#updateModal", state="visible", timeout=5000)
        self._page.wait_for_function("typeof window.__resolveDeferredUpdateCheck === 'function'", timeout=5000)

        loading = self._page.evaluate(
            """
            () => ({
              busy: document.getElementById('updateModal').getAttribute('aria-busy'),
              status: document.getElementById('updateStatus').dataset.status,
              spinnerVisible: !document.getElementById('updateSpinner').hidden,
              versionDisabled: document.getElementById('statusVersion').disabled,
            })
            """
        )
        self.assertEqual(loading["busy"], "true")
        self.assertEqual(loading["status"], "checking")
        self.assertTrue(loading["spinnerVisible"])
        self.assertTrue(loading["versionDisabled"])

        self._page.evaluate("window.__resolveDeferredUpdateCheck()")
        self._page.wait_for_function(
            "document.getElementById('updateModal').getAttribute('aria-busy') === 'false'",
            timeout=5000,
        )
        self.assertTrue(self._page.locator("#updateSpinner").evaluate("element => element.hidden"))

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
              window.__isolateFrontendStateForTest();
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

    def test_13e_task_list_pagers_change_page_and_page_size(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest();
              const waitUntil = async (predicate, label) => {
                const deadline = performance.now() + 5000;
                while (performance.now() < deadline) {
                  if (predicate()) return;
                  await new Promise(resolve => setTimeout(resolve, 20));
                }
                throw new Error(`Timed out waiting for ${label}`);
              };
              const makeItems = (prefix, count, extra) => Array.from(
                { length: count },
                (_, index) => ({
                  id: `${prefix}-${index + 1}`,
                  title: `${prefix} item ${index + 1}`,
                  platform: 'Bilibili',
                  status: prefix === 'failed' ? 'failed' : 'pending',
                  ...extra,
                })
              );

              frontendState.queue_items = makeItems('queue', 45, {});
              frontendState.completed_items = makeItems('completed', 45, {
                completed_at: '2026-07-15 05:00:00',
                duration: '00:01:00',
                format: 'MP4',
                local_path: 'D:/Downloads/item.mp4',
              });
              frontendState.failed_items = makeItems('failed', 45, {
                failed_at: '2026-07-15 05:00:00',
                reason: 'Network timeout',
              });
              selected.queue = '';
              selected.completed = '';
              selected.failed = '';

              const pages = [
                { name: 'queue', body: 'queueBody', size: 'queuePageSize', now: 'queuePageNow', total: 'queueTotalPages', prev: 'queuePrevPage', next: 'queueNextPage' },
                { name: 'completed', body: 'completedBody', size: 'completedPageSize', now: 'completedPageNow', total: 'completedTotalPages', prev: 'completedPrevPage', next: 'completedNextPage' },
                { name: 'failed', body: 'failedBody', size: 'failedPageSize', now: 'failedPageNow', total: 'failedTotalPages', prev: 'failedPrevPage', next: 'failedNextPage' },
              ];
              const results = {};

              for (const page of pages) {
                localStorage.setItem(`webui_${page.name}_page_size`, '20');
                switchPage(page.name);
                await waitUntil(
                  () => document.querySelectorAll(`#${page.body} tr[data-id]`).length === 20
                    && byId(page.now).textContent === '1'
                    && byId(page.total).textContent === '3',
                  `${page.name} initial page`,
                );

                const sizeSelect = byId(page.size);
                sizeSelect.value = '50';
                sizeSelect.dispatchEvent(new Event('change', { bubbles: true }));
                await waitUntil(
                  () => document.querySelectorAll(`#${page.body} tr[data-id]`).length === 45
                    && byId(page.now).textContent === '1'
                    && byId(page.total).textContent === '1',
                  `${page.name} 50-per-page`,
                );

                sizeSelect.value = '20';
                sizeSelect.dispatchEvent(new Event('change', { bubbles: true }));
                await waitUntil(
                  () => document.querySelectorAll(`#${page.body} tr[data-id]`).length === 20
                    && byId(page.now).textContent === '1'
                    && byId(page.total).textContent === '3',
                  `${page.name} reset page size`,
                );
                byId(page.next).click();
                await waitUntil(
                  () => byId(page.now).textContent === '2'
                    && document.querySelectorAll(`#${page.body} tr[data-id]`).length === 20,
                  `${page.name} next page`,
                );

                results[page.name] = {
                  page: byId(page.now).textContent,
                  totalPages: byId(page.total).textContent,
                  pageSize: sizeSelect.value,
                  rowCount: document.querySelectorAll(`#${page.body} tr[data-id]`).length,
                  firstId: document.querySelector(`#${page.body} tr[data-id]`)?.dataset.id || '',
                  prevDisabled: byId(page.prev).disabled,
                  nextDisabled: byId(page.next).disabled,
                };
              }
              return results;
            }
            """
        )

        for page_name, values in result.items():
            self.assertEqual(values["page"], "2", (page_name, values))
            self.assertEqual(values["totalPages"], "3", (page_name, values))
            self.assertEqual(values["pageSize"], "20", (page_name, values))
            self.assertEqual(values["rowCount"], 20, (page_name, values))
            self.assertEqual(values["firstId"], f"{page_name}-21", (page_name, values))
            self.assertFalse(values["prevDisabled"], (page_name, values))
            self.assertFalse(values["nextDisabled"], (page_name, values))

    def test_13ea_active_download_controls_round_trip_through_live_backend(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              const fetchOptions = async () => {
                const response = await fetch(`/api/frontend/state?active_options_audit=${Date.now()}`, {
                  cache: 'no-store',
                });
                if (!response.ok) throw new Error(`frontend state failed: ${response.status}`);
                return (await response.json()).download_options || {};
              };
              const waitForOptions = async (expected, label) => {
                const deadline = performance.now() + 7000;
                let actual = {};
                while (performance.now() < deadline) {
                  actual = await fetchOptions();
                  if (
                    Boolean(actual.auto_retry) === Boolean(expected.auto_retry)
                    && Number(actual.max_retries) === Number(expected.max_retries)
                    && Number(actual.max_concurrent) === Number(expected.max_concurrent)
                  ) return actual;
                  await new Promise(resolve => setTimeout(resolve, 40));
                }
                throw new Error(`${label}: ${JSON.stringify(actual)}`);
              };
              const writeControls = values => {
                byId('activeAutoRetry').checked = Boolean(values.auto_retry);
                byId('activeMaxRetries').value = String(values.max_retries);
                byId('activeMaxConcurrent').value = String(values.max_concurrent);
                byId('activeMaxConcurrent').dispatchEvent(new Event('change', { bubbles: true }));
              };

              switchPage('active');
              const original = await fetchOptions();
              const target = {
                auto_retry: !Boolean(original.auto_retry),
                max_retries: Number(original.max_retries) === 5 ? 4 : 5,
                max_concurrent: Number(original.max_concurrent) === 5 ? 3 : 5,
              };
              let observed;
              let failure = null;
              try {
                writeControls(target);
                observed = await waitForOptions(target, 'active options persist');
              } catch (error) {
                failure = error;
              } finally {
                writeControls(original);
                await waitForOptions(original, 'active options restore');
              }
              if (failure) throw failure;
              return { target, observed };
            }
            """
        )

        self.assertEqual(bool(result["observed"]["auto_retry"]), bool(result["target"]["auto_retry"]))
        self.assertEqual(int(result["observed"]["max_retries"]), int(result["target"]["max_retries"]))
        self.assertEqual(int(result["observed"]["max_concurrent"]), int(result["target"]["max_concurrent"]))

    def test_13eb_toolbox_open_button_dispatches_valid_backend_action(self):
        context = self._browser.new_context(viewport={"width": 1280, "height": 720})
        self.addCleanup(context.close)
        page = context.new_page()
        self.addCleanup(page.close)
        page.add_init_script(
            "Object.defineProperty(window, 'WebSocket', { value: undefined, configurable: true });"
        )
        page.goto(self._server_url, wait_until="domcontentloaded")
        page.wait_for_selector("#app-shell", state="visible", timeout=5000)
        page.wait_for_function("window.__ucrawlFrontendStateSettled === true", timeout=5000)
        page.evaluate("switchPage('toolbox')")
        page.wait_for_selector("#toolDetail .btn-primary", state="visible", timeout=5000)

        with page.expect_response(
            lambda response: response.url.endswith("/api/frontend/action")
            and response.request.method == "POST",
            timeout=5000,
        ) as response_info:
            page.click("#toolDetail .btn-primary")

        response = response_info.value
        request_payload = response.request.post_data_json
        response_payload = response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(request_payload.get("action"), "run_tool")
        self.assertTrue(request_payload.get("payload", {}).get("tool_id"))
        self.assertEqual(response_payload.get("status"), "ok")
        self.assertEqual(
            response_payload.get("data", {}).get("tool_id"),
            request_payload.get("payload", {}).get("tool_id"),
        )

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

    def test_13i_list_pages_terminal_worker_error_closes_worker_and_falls_back(self):
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
              let postsAfterFailure = 0;
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
                  this.dead = false;
                  workers.push(this);
                }
                postMessage(request) {
                  if (this.dead) {
                    postsAfterFailure += 1;
                    return;
                  }
                  this.requests.push(request);
                }
                terminate() {
                  this.terminateCalls += 1;
                  this.dead = true;
                }
                fail() {
                  this.dead = true;
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

                state.completed_items = [{ id: "completed-current", title: "Completed current", format: "MP4" }];
                window.UcpListPages.renderCompleted();
                const staleFallback = fallbacksAfterError[0] || null;
                const currentFallback = timers.find(timer => timer !== staleFallback) || null;
                if (staleFallback) staleFallback.callback();
                const staleFallbackIgnored = selection.completed === ""
                  && document.querySelector("#completedBody tr[data-id]") === null;

                if (currentFallback) currentFallback.callback();
                return {
                  errorPrevented: errorEvent.defaultPrevented,
                  workerTerminatedOnce: worker.terminateCalls === 1,
                  noPostToDeadWorker: postsAfterFailure === 0 && worker.requests.length === 1,
                  noReplacementWorker: workers.length === 1,
                  onlyCurrentFallbackScheduled: fallbacksAfterError.length === 1,
                  staleFallbackCancelled: Boolean(staleFallback && clearedTimers.includes(staleFallback.id)),
                  staleFallbackIgnored,
                  currentFallbackScheduled: Boolean(currentFallback),
                  currentFallbackRendered: selection.completed === "completed-current"
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
        self.assertTrue(result["workerTerminatedOnce"])
        self.assertTrue(result["noPostToDeadWorker"])
        self.assertTrue(result["noReplacementWorker"])
        self.assertTrue(result["onlyCurrentFallbackScheduled"])
        self.assertTrue(result["staleFallbackCancelled"])
        self.assertTrue(result["staleFallbackIgnored"])
        self.assertTrue(result["currentFallbackScheduled"])
        self.assertTrue(result["currentFallbackRendered"])
