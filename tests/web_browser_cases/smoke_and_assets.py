"""WebUI browser cases owned by the smoke and assets responsibility."""

from __future__ import annotations

class SmokeAndAssetsCases:
    def test_01_index_loads(self):
        """主页加载成功。"""
        self._goto_ready()
        title = self._page.title()
        self.assertIn("Universal", title)

    def test_02_platforms_endpoint(self):
        """/api/platforms 返回非空列表。"""
        resp = self._page.request.get(f"{self._server_url}/api/platforms")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertGreater(len(data), 0)
        for p in data:
            self.assertIn("id", p)
            self.assertIn("name", p)

    def test_03_ping_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/ping")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_04_state_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/state")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIn("video_count", data)
        self.assertIn("is_crawling", data)

    def test_05_config_endpoint(self):
        resp = self._page.request.get(f"{self._server_url}/api/config")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)

    def test_06_source_select_visible(self):
        """sourceSelect 应可见。"""
        self._goto_ready()
        # 等待 select 可见
        sel = self._page.locator("#sourceSelect")
        self.assertTrue(sel.is_visible(), "sourceSelect should be visible after init")

    def test_06b_source_select_uses_platform_icons_like_gui(self):
        self._goto_ready()
        self._wait_for_platform_options()

        result = self._page.evaluate(
            """
            () => {
              const wrapper = document.querySelector('.custom-select-source');
              const button = wrapper && wrapper.querySelector('.custom-select-button');
              if (button) button.click();
              const optionIcon = document.querySelector('#sourceSelect option')?.dataset.icon || '';
              const buttonIcon = wrapper?.querySelector('.custom-select-button .custom-select-icon')?.getAttribute('src') || '';
              const menuIconCount = wrapper ? wrapper.querySelectorAll('.custom-select-menu .custom-select-icon').length : 0;
              return { optionIcon, buttonIcon, menuIconCount };
            }
            """
        )

        self.assertIn("/ui-icon/platform_", result["optionIcon"])
        self.assertIn("/ui-icon/platform_", result["buttonIcon"])
        self.assertGreater(result["menuIconCount"], 0)

    def test_07_theme_toggle_changes_data_theme(self):
        """点击主题按钮应切换 data-theme。"""
        self._goto_ready()
        before = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self._page.locator("#themeBtn").click()
        self._page.wait_for_function(
            "expected => document.documentElement.getAttribute('data-theme') === expected",
            arg="light" if before == "dark" else "dark",
            timeout=5000,
        )
        after = self._page.evaluate("document.documentElement.getAttribute('data-theme')")
        self.assertIn(before, {"light", "dark"})
        self.assertEqual(after, "light" if before == "dark" else "dark")

    def test_07a_theme_toggle_is_single_flight_and_latest_intent_wins(self):
        self._goto_ready()
        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const requests = [];
              const pending = [];
              const baseVersion = Number(frontendState.version || 0);
              const settingsForTheme = theme => ({
                ...(frontendState.settings_snapshot || {}),
                '\u5916\u89c2\u8bbe\u7f6e': {
                  ...((frontendState.settings_snapshot || {})['\u5916\u89c2\u8bbe\u7f6e'] || {}),
                  follow_system: false,
                  theme
                }
              });
              window.fetch = (url, options = {}) => {
                if (String(url).includes('/api/frontend/action')) {
                  const body = JSON.parse(options.body || '{}');
                  requests.push(body);
                  return new Promise(resolve => pending.push(theme => resolve(new Response(JSON.stringify({
                    status: 'ok',
                    frontend_delta: {
                      full: true,
                      version: baseVersion + requests.length,
                      changed_sections: ['settings_snapshot'],
                      sections: { settings_snapshot: settingsForTheme(theme) }
                    }
                  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))));
                }
                return originalFetch(url, options);
              };
              try {
                applyTheme(false);
                toggleTheme();
                toggleTheme();
                const afterClicks = {
                  requestCount: requests.length,
                  theme: document.documentElement.dataset.theme,
                  busy: document.getElementById('themeBtn').getAttribute('aria-busy')
                };
                if (!pending.length) return { afterClicks, requests, finalTheme: document.documentElement.dataset.theme };
                pending.shift()('dark');
                await new Promise((resolve, reject) => {
                  const deadline = performance.now() + 3000;
                  const tick = () => {
                    if (pending.length) return resolve();
                    if (performance.now() > deadline) return reject(new Error('latest theme request was not dispatched'));
                    requestAnimationFrame(tick);
                  };
                  tick();
                });
                pending.shift()('light');
                await new Promise((resolve, reject) => {
                  const deadline = performance.now() + 3000;
                  const tick = () => {
                    if (document.getElementById('themeBtn').getAttribute('aria-busy') === 'false') return resolve();
                    if (performance.now() > deadline) return reject(new Error('theme transaction did not settle'));
                    requestAnimationFrame(tick);
                  };
                  tick();
                });
                return {
                  afterClicks,
                  requests,
                  finalTheme: document.documentElement.dataset.theme,
                  finalBusy: document.getElementById('themeBtn').getAttribute('aria-busy')
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertEqual(result["afterClicks"]["requestCount"], 1, result)
        self.assertEqual(result["afterClicks"]["theme"], "light", result)
        self.assertEqual(result["afterClicks"]["busy"], "true", result)
        self.assertEqual(
            [request["payload"]["value"] for request in result["requests"]],
            ["dark", "light"],
        )
        self.assertEqual(result["finalTheme"], "light")
        self.assertEqual(result["finalBusy"], "false")

    def test_07aa_theme_toggle_failure_rolls_back_to_server_state(self):
        self._goto_ready()
        result = self._page.evaluate(
            """
            async () => {
              const originalFetch = window.fetch;
              const serverState = structuredClone(frontendState);
              serverState.settings_snapshot['\u5916\u89c2\u8bbe\u7f6e'] = {
                ...(serverState.settings_snapshot['\u5916\u89c2\u8bbe\u7f6e'] || {}),
                follow_system: false,
                theme: 'light'
              };
              window.fetch = async (url, options = {}) => {
                if (String(url).includes('/api/frontend/action')) {
                  return new Response(JSON.stringify({ status: 'error', message: 'persist failed' }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' }
                  });
                }
                if (String(url).includes('/api/frontend/state')) {
                  return new Response(JSON.stringify(serverState), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' }
                  });
                }
                return originalFetch(url, options);
              };
              try {
                applyTheme(false);
                toggleTheme();
                const optimisticTheme = document.documentElement.dataset.theme;
                await new Promise((resolve, reject) => {
                  const deadline = performance.now() + 3000;
                  const tick = () => {
                    if (document.getElementById('themeBtn').getAttribute('aria-busy') === 'false') return resolve();
                    if (performance.now() > deadline) return reject(new Error('failed theme transaction did not settle'));
                    requestAnimationFrame(tick);
                  };
                  tick();
                });
                return {
                  optimisticTheme,
                  finalTheme: document.documentElement.dataset.theme,
                  cachedTheme: localStorage.getItem('cached_theme'),
                  stateTheme: frontendState.settings_snapshot['\u5916\u89c2\u8bbe\u7f6e'].theme
                };
              } finally {
                window.fetch = originalFetch;
              }
            }
            """
        )

        self.assertEqual(result["optimisticTheme"], "dark")
        self.assertEqual(result["finalTheme"], "light")
        self.assertEqual(result["cachedTheme"], "light")
        self.assertEqual(result["stateTheme"], "light")

    def test_07b_appearance_theme_segment_disables_follow_system(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              const appearance = (frontendState.settings_snapshot['\\u5916\\u89c2\\u8bbe\\u7f6e'] ||= {});
              appearance.follow_system = true;
              appearance.theme = 'light';
              window.UcpSettingsController.switchGroup('\\u5916\\u89c2\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const beforeSwitch = document.querySelector('#page-settings [data-setting="follow_system"]');
              const darkButton = document.querySelector('#page-settings .setting-theme-segment-btn[data-value="dark"]');
              darkButton?.click();
              const afterSwitch = document.querySelector('#page-settings [data-setting="follow_system"]');
              const activeButton = document.querySelector('#page-settings .setting-theme-segment-btn.active');
              return {
                hasSegment: Boolean(darkButton),
                beforeFollowSystem: beforeSwitch ? beforeSwitch.checked : null,
                afterFollowSystem: afterSwitch ? afterSwitch.checked : null,
                activeValue: activeButton?.dataset.value || '',
                theme: frontendState.settings_snapshot['\\u5916\\u89c2\\u8bbe\\u7f6e']?.theme || '',
                dataTheme: document.documentElement.dataset.theme || ''
              };
            }
            """
        )

        self.assertTrue(result["hasSegment"])
        self.assertTrue(result["beforeFollowSystem"])
        self.assertFalse(result["afterFollowSystem"])
        self.assertEqual(result["activeValue"], "dark")
        self.assertEqual(result["theme"], "dark")
        self.assertEqual(result["dataTheme"], "dark")

    def test_07c_follow_system_setting_applies_browser_color_scheme(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              const originalMatchMedia = window.matchMedia;
              window.matchMedia = () => ({
                matches: true,
                addEventListener() {},
                removeEventListener() {}
              });
              frontendState.settings_snapshot = frontendState.settings_snapshot || {};
              const appearance = (frontendState.settings_snapshot['\u5916\u89c2\u8bbe\u7f6e'] ||= {});
              appearance.theme = 'light';
              appearance.follow_system = false;
              updateSetting('appearance', 'follow_system', true);
              const value = {
                followSystem: appearance.follow_system,
                dataTheme: document.documentElement.dataset.theme || ''
              };
              window.matchMedia = originalMatchMedia;
              return value;
            }
            """
        )

        self.assertTrue(result["followSystem"])
        self.assertEqual(result["dataTheme"], "dark")

    def test_08_dir_modal_opens(self):
        """点击更改目录按钮应弹出目录弹窗。"""
        self._goto_ready()
        # 找到更改目录按钮
        # HTML 里 onclick="onChangeDirClicked()"
        self._page.evaluate("onChangeDirClicked()")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('dirModal')?.style.display)",
            timeout=5000,
        )
        # 检查 modal.style.display 变成了 flex
        display = self._page.evaluate("document.getElementById('dirModal').style.display")
        self.assertIn(display, ("flex", "block"))

    def test_09_selection_modal_can_be_called(self):
        """showSelectionModal 函数可以调用。"""
        self._goto_ready()
        # 直接调用 showSelectionModal
        self._page.evaluate("showSelectionModal([{title: 'test'},{title: 'demo'}])")
        self._page.wait_for_function(
            "() => ['flex', 'block'].includes(document.getElementById('selectionModal')?.style.display) && document.getElementById('selectionHeader')?.textContent.includes('2')",
            timeout=5000,
        )
        header = self._page.locator("#selectionHeader").text_content()
        self.assertIn("2", header)

    def test_12_console_no_errors(self):
        """主页加载应无 JS 错误。"""
        errors = []
        self._page.on("pageerror", lambda e: errors.append(str(e)))
        self._page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                      if msg.type == "error" else None)
        self._goto_ready()
        # 过滤已知的非关键错误
        critical_errors = [e for e in errors
                           if "favicon" not in e.lower()
                           and "WebSocket" not in e
                           and "ws" not in e.lower()
                           and "404" not in e]
        self.assertEqual(critical_errors, [], f"JS errors: {critical_errors}")
