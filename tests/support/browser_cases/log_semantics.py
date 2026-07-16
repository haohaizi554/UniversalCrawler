"""WebUI browser cases for shared GUI/Web log query semantics."""

from __future__ import annotations


class LogSemanticsCases:
    def test_09ba_log_query_matches_gui_sort_level_category_and_platform_semantics(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const items = [
                {
                  id: 'crawl-start',
                  time: '2026-07-14 20:14:24',
                  timestamp_ms: Date.parse('2026-07-14T20:14:24'),
                  level: 'INFO',
                  level_display: 'INFO',
                  log_scope: 'crawl',
                  category: 'download',
                  platform_id: 'bilibili',
                  platform: 'Bilibili',
                  source: 'WebController',
                  message: 'Web crawl started',
                  detail: { active_config: { timeout: 60 } }
                },
                {
                  id: 'download-finished',
                  time: '2026-07-14 20:15:15',
                  timestamp_ms: Date.parse('2026-07-14T20:15:15'),
                  level: 'INFO',
                  level_display: 'SUCCESS',
                  log_scope: 'download',
                  category: 'download',
                  platform_id: 'bilibili',
                  platform: 'Bilibili',
                  source: 'BilibiliDownloader',
                  message: 'Download finished'
                },
                {
                  id: 'same-time-a',
                  time: '2026-07-14 20:16:00',
                  level: 'WARN',
                  level_display: 'WARN',
                  log_scope: 'crawl',
                  platform_id: 'bilibili',
                  platform: 'Bilibili',
                  source: 'BilibiliSpider',
                  message: 'first at same second'
                },
                {
                  id: 'same-time-b',
                  time: '2026-07-14 20:16:00',
                  level: 'ERROR',
                  level_display: 'ERROR',
                  log_scope: 'error',
                  platform_id: 'bilibili',
                  platform: 'Bilibili',
                  source: 'BilibiliSpider',
                  message: 'second at same second'
                },
                {
                  id: 'system-mentions-bilibili',
                  time: '2026-07-14 20:13:00',
                  level: 'INFO',
                  level_display: 'INFO',
                  log_scope: 'system',
                  platform_id: 'system',
                  platform: 'System',
                  source: 'GUI',
                  message: 'Started Bilibili crawl task'
                }
              ];
              const base = {
                items,
                filters: { category: 'all', level: 'all', time: 'all', platform: 'all', trace: '', keyword: '' },
                page: 1,
                pageSize: 20,
                rowBudget: 20,
                nowMs: Date.parse('2026-07-14T20:20:00')
              };
              const all = window.UcpLogDisplay.queryLogItems(base);
              const bounded = window.UcpLogDisplay.queryLogItems({ ...base, rowBudget: 3 });
              const success = window.UcpLogDisplay.queryLogItems({
                ...base,
                filters: { ...base.filters, level: 'SUCCESS' }
              });
              const crawl = window.UcpLogDisplay.queryLogItems({
                ...base,
                filters: { ...base.filters, category: 'crawl' }
              });
              const bilibili = window.UcpLogDisplay.queryLogItems({
                ...base,
                filters: { ...base.filters, platform: 'Bilibili' }
              });
              return {
                allOrder: all.pageItems.map(item => item.id),
                boundedOrder: bounded.pageItems.map(item => item.id),
                successIds: success.pageItems.map(item => item.id),
                crawlIds: crawl.pageItems.map(item => item.id),
                bilibiliIds: bilibili.pageItems.map(item => item.id),
                counts: all.tabCounts
              };
            }
            """
        )

        self.assertEqual(
            result["allOrder"],
            ["same-time-b", "same-time-a", "download-finished", "crawl-start", "system-mentions-bilibili"],
        )
        self.assertEqual(result["boundedOrder"], ["same-time-b", "same-time-a", "download-finished"])
        self.assertEqual(result["successIds"], ["download-finished"])
        self.assertEqual(result["crawlIds"], ["same-time-a", "crawl-start"])
        self.assertNotIn("system-mentions-bilibili", result["bilibiliIds"])
        self.assertEqual(
            result["counts"],
            {"all": 5, "crawl": 2, "download": 1, "system": 1, "performance": 0, "error": 1},
        )

    def test_09bb_platform_filter_uses_gui_icon_contract_and_alignment(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              switchPage("logs");
              renderLogs();
              const select = document.getElementById("logPlatformFilter");
              const wrapper = select.closest(".custom-select");
              const button = wrapper.querySelector(".custom-select-button");
              button.click();
              const menu = wrapper.querySelector(".custom-select-menu");
              const rows = Array.from(wrapper.querySelectorAll(".custom-select-option"));
              const labelLefts = rows.map(row => row.querySelector(".custom-select-label").getBoundingClientRect().left);
              const menuRect = menu.getBoundingClientRect();
              const lastRowRect = rows.at(-1).getBoundingClientRect();
              return {
                optionIcons: Array.from(select.options).map(option => option.dataset.icon || ""),
                buttonIcon: button.querySelector(".custom-select-icon")?.getAttribute("src") || "",
                menuIconCount: wrapper.querySelectorAll(".custom-select-menu .custom-select-icon").length,
                rowCount: rows.length,
                labelLeftSpread: labelLefts.length ? Math.max(...labelLefts) - Math.min(...labelLefts) : 0,
                menuClientHeight: menu.clientHeight,
                menuScrollHeight: menu.scrollHeight,
                lastRowBottom: lastRowRect.bottom,
                menuBottom: menuRect.bottom,
              };
            }
            """
        )

        expected_icons = [
            "/ui-icon/platform_web.png",
            "/ui-icon/platform_douyin.png",
            "/ui-icon/platform_bilibili.png",
            "/ui-icon/platform_kuaishou.png",
            "/ui-icon/platform_missav.png",
            "/ui-icon/platform_xiaohongshu.png",
            "/ui-icon/nav_settings.png",
        ]
        self.assertEqual(result["optionIcons"], expected_icons)
        self.assertEqual(result["buttonIcon"], expected_icons[0])
        self.assertEqual(result["menuIconCount"], result["rowCount"])
        self.assertLessEqual(result["labelLeftSpread"], 1.0)
        self.assertLessEqual(result["menuScrollHeight"], result["menuClientHeight"] + 1)
        self.assertLessEqual(result["lastRowBottom"], result["menuBottom"] + 1)

    def test_09bc_log_detail_synthesizes_gui_payload_when_raw_detail_is_empty(self):
        self._goto_ready()

        result = self._page.evaluate(
            r"""
            async () => {
              window.__isolateFrontendStateForTest();
              const id = 'empty-raw-detail';
              frontendState.log_items = [{
                id,
                time: '2026-07-14 20:43:04',
                level: 'INFO',
                source: 'WebController',
                platform: 'System',
                trace_id: 'web-scan-1',
                status_code: 'WEB_SCAN_START',
                event_code: 'WEB_SCAN_START',
                message_summary: 'Scanning directory: D:\\downloads',
                message: 'Scanning directory: D:\\downloads',
                detail: ''
              }];
              window.__setLogFiltersForTest({
                category: 'all', level: 'all', time: 'all', platform: 'all', trace: '', keyword: ''
              });
              switchPage('logs');
              renderLogs();
              await window.__waitForLogRender({
                rows: 1, total: 1, matched: 1, visible: 1, selectedId: id, text: 'Scanning directory'
              });
              let readable = null;
              for (let attempt = 0; attempt < 100; attempt += 1) {
                readable = document.querySelector('#logDetail .log-detail-readable');
                if (readable && readable.dataset.json && readable.dataset.json !== '{}') break;
                await new Promise(resolve => setTimeout(resolve, 10));
              }
              return {
                text: readable?.textContent || '',
                payload: JSON.parse(readable?.dataset.json || '{}')
              };
            }
            """
        )

        self.assertIn("Scanning directory", result["text"])
        self.assertEqual(result["payload"]["description"], "Scanning directory")
        self.assertEqual(result["payload"]["path"], r"D:\downloads")
        self.assertEqual(result["payload"]["status_code"], "WEB_SCAN_START")
        self.assertTrue(result["payload"]["source"].startswith("Web"))
        self.assertEqual(result["payload"]["trace_id"], "web-scan-1")

    def test_09bd_duplicate_log_row_ids_survive_ring_eviction_and_worker_clone(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest({ captureLogWorkers: true });
              let observed = null;
              try {
                window.__setLogFiltersForTest({
                  category: 'all', level: 'all', time: 'all', platform: 'all', trace: '', keyword: ''
                });
                const makeRow = () => ({
                  time: '2026-07-15 06:00:00',
                  level: 'INFO',
                  source: 'Web',
                  trace_id: '',
                  message_summary: 'identical ring event',
                  message: 'identical ring event',
                  detail: '',
                  stack: ''
                });
                const oldest = makeRow();
                const survivor = makeRow();
                frontendState.log_items = [oldest, survivor];
                switchPage('logs');
                renderLogs();
                await window.__waitForLogRender({ rows: 2, total: 2, matched: 2, visible: 2 });

                const firstOwnedIds = frontendState.log_items.map(window.UcpLogDisplay.logItemId);
                const firstDomIds = Array.from(
                  document.querySelectorAll('#logBody tr'),
                  row => row.dataset.key
                );
                const survivorId = firstDomIds[0];
                document.querySelector(`#logBody tr[data-key="${CSS.escape(survivorId)}"]`)?.click();

                const newcomer = makeRow();
                frontendState.log_items = [survivor, newcomer];
                renderLogs();

                const deadline = performance.now() + 3000;
                let afterOwnedIds = [];
                let afterDomIds = [];
                let selectedId = '';
                while (performance.now() < deadline) {
                  afterOwnedIds = frontendState.log_items.map(window.UcpLogDisplay.logItemId);
                  afterDomIds = Array.from(
                    document.querySelectorAll('#logBody tr'),
                    row => row.dataset.key
                  );
                  selectedId = document.querySelector('#logBody tr.selected')?.dataset.key || '';
                  if (
                    afterOwnedIds[0] === survivorId
                    && afterOwnedIds[1]
                    && afterOwnedIds[1] !== survivorId
                    && afterDomIds.length === 2
                    && afterDomIds.every(id => afterOwnedIds.includes(id))
                    && selectedId === survivorId
                  ) break;
                  await new Promise(resolve => setTimeout(resolve, 20));
                }

                observed = {
                  firstOwnedIds,
                  firstDomIds,
                  survivorId,
                  afterOwnedIds,
                  afterDomIds,
                  selectedId,
                  queryWorkerCreated: window.__logWorkerUrls.some(url => url.includes('log_query_worker.js'))
                };
              } finally {
                window.__restoreLogWorkerForTest();
              }
              return observed;
            }
            """
        )

        self.assertEqual(len(set(result["firstOwnedIds"])), 2, result)
        self.assertCountEqual(result["firstDomIds"], result["firstOwnedIds"])
        self.assertEqual(result["afterOwnedIds"][0], result["survivorId"], result)
        self.assertNotIn(result["afterOwnedIds"][1], result["firstOwnedIds"], result)
        self.assertCountEqual(result["afterDomIds"], result["afterOwnedIds"])
        self.assertEqual(result["selectedId"], result["survivorId"], result)
        self.assertTrue(result["queryWorkerCreated"], result)

    def test_09be_backend_log_ids_survive_fresh_snapshot_objects(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.__isolateFrontendStateForTest({ captureLogWorkers: true });
              let observed = null;
              try {
                window.__setLogFiltersForTest({
                  category: 'all', level: 'all', time: 'all', platform: 'all', trace: '', keyword: ''
                });
                const rows = [
                  { id: 'runtime-log:41', time: '2026-07-15 06:00:00', level: 'INFO', source: 'Web', message: 'same' },
                  { id: 'runtime-log:42', time: '2026-07-15 06:00:00', level: 'INFO', source: 'Web', message: 'same' }
                ];
                frontendState.log_items = rows.map(row => ({ ...row }));
                switchPage('logs');
                renderLogs();
                const deadline = performance.now() + 3000;
                let selected = null;
                while (performance.now() < deadline) {
                  selected = document.querySelector(
                    `#logBody tr[data-key="${CSS.escape('runtime-log:41')}"]`
                  );
                  if (selected) break;
                  await new Promise(resolve => setTimeout(resolve, 20));
                }
                selected?.click();

                frontendState.log_items = rows.map(row => ({ ...row }));
                renderLogs();
                while (performance.now() < deadline) {
                  const selectedId = document.querySelector('#logBody tr.selected')?.dataset.key || '';
                  if (selectedId === 'runtime-log:41') break;
                  await new Promise(resolve => setTimeout(resolve, 20));
                }
                observed = {
                  ids: frontendState.log_items.map(window.UcpLogDisplay.logItemId),
                  domIds: Array.from(document.querySelectorAll('#logBody tr'), row => row.dataset.key),
                  selectedId: document.querySelector('#logBody tr.selected')?.dataset.key || ''
                };
              } finally {
                window.__restoreLogWorkerForTest();
              }
              return observed;
            }
            """
        )

        self.assertEqual(result["ids"], ["runtime-log:41", "runtime-log:42"])
        self.assertEqual(result["selectedId"], "runtime-log:41", result)

    def test_09bf_generated_log_id_history_is_bounded(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.__isolateFrontendStateForTest({ captureLogWorkers: true });
              try {
                window.__setLogFiltersForTest({
                  category: 'all', level: 'all', time: 'all', platform: 'all', trace: '', keyword: ''
                });
                const makeRow = () => ({
                  time: '2026-07-15 06:00:00',
                  level: 'INFO',
                  source: 'Web',
                  trace_id: '',
                  message_summary: 'bounded identical event',
                  message: 'bounded identical event',
                  detail: '',
                  stack: ''
                });
                let firstId = '';
                let recycledAt = -1;
                for (let index = 0; index < 2200; index += 1) {
                  frontendState.log_items = [makeRow()];
                  renderLogs();
                  const id = window.UcpLogDisplay.logItemId(frontendState.log_items[0]);
                  if (index === 0) firstId = id;
                  else if (id === firstId) {
                    recycledAt = index;
                    break;
                  }
                }
                return { firstId, recycledAt };
              } finally {
                window.__restoreLogWorkerForTest();
              }
            }
            """
        )

        self.assertTrue(result["firstId"], result)
        self.assertGreater(result["recycledAt"], 0, result)
        self.assertLess(result["recycledAt"], 2200, result)
