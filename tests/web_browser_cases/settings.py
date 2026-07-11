"""WebUI browser cases owned by the settings responsibility."""

from __future__ import annotations

from tests.web_browser_support import _stable_platform_settings_snapshot_js


class SettingsCases:
    def test_11d_settings_controller_commits_custom_proxy_through_public_api(self):
        self._goto_ready()

        result = self._page.evaluate(
            r"""
            () => {
              const actions = [];
              const state = {
                settings_snapshot: {
                  '\u5e73\u53f0\u8bbe\u7f6e': [{
                    id: 'demo',
                    name: 'Demo',
                    proxy: '\u7cfb\u7edf\u4ee3\u7406',
                    proxy_config_key: 'proxy_url',
                    proxy_editable: true,
                    proxy_custom_allowed: true,
                    proxy_options: ['\u7cfb\u7edf\u4ee3\u7406', '\u76f4\u8fde', '\u81ea\u5b9a\u4e49']
                  }]
                },
                settings_contract: { group_order: ['\u5e73\u53f0\u8bbe\u7f6e'] }
              };
              window.UcpSettingsController.configure({
                getState: () => state,
                t: value => String(value || ''),
                optionLabel: value => String(value || ''),
                byId: id => document.getElementById(id),
                sendWS: (action, payload) => actions.push({ action, payload }),
                patchSetting: () => {},
                patchPlatformSetting: () => {},
                syncAppearance: () => {},
                enhanceSelects: () => {}
              });
              window.UcpSettingsController.render(true);
              const select = document.querySelector('#settingsGrid .platform-proxy');
              select.value = '\u81ea\u5b9a\u4e49';
              window.UcpSettingsController.handleProxySelect('demo', 'proxy_url', select);
              const input = document.querySelector('#settingsGrid .proxy-custom');
              input.value = 'http://127.0.0.1:7890';
              window.UcpSettingsController.commitProxyCustom('demo', 'proxy_url', input);
              return {
                actions,
                inputHidden: input.hidden,
                inputDisabled: input.disabled,
                rowCustom: select.closest('.setting-platform').classList.contains('has-proxy-custom')
              };
            }
            """
        )

        self.assertEqual(
            result["actions"],
            [
                {"action": "update_setting", "payload": {"section": "demo", "key": "proxy_url", "value": "\u81ea\u5b9a\u4e49"}},
                {"action": "update_setting", "payload": {"section": "demo", "key": "proxy_url", "value": "http://127.0.0.1:7890"}},
            ],
        )
        self.assertFalse(result["inputHidden"])
        self.assertFalse(result["inputDisabled"])
        self.assertTrue(result["rowCustom"])

    def test_11g_settings_nav_icons_load_from_backend_route(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.UcpSettingsController.switchGroup('基础设置');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const images = Array.from(document.querySelectorAll('#page-settings .settings-nav-btn img, #page-settings .settings-detail-icon img'));
              await Promise.all(images.map(img => {
                if (img.complete && img.naturalWidth > 0) return Promise.resolve();
                return new Promise((resolve, reject) => {
                  img.addEventListener('load', resolve, { once: true });
                  img.addEventListener('error', () => reject(new Error(img.src)), { once: true });
                });
              }));
              return {
                nav: Array.from(document.querySelectorAll('#page-settings .settings-nav-btn')).map(button => ({
                  label: button.querySelector('span')?.textContent.trim(),
                  src: button.querySelector('img')?.getAttribute('src'),
                  loaded: (button.querySelector('img')?.naturalWidth || 0) > 0
                })),
                detail: {
                  src: document.querySelector('#page-settings .settings-detail-icon img')?.getAttribute('src'),
                  loaded: (document.querySelector('#page-settings .settings-detail-icon img')?.naturalWidth || 0) > 0
                }
              };
            }
            """
        )

        self.assertEqual([row["label"] for row in result["nav"]], ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"])
        self.assertTrue(all(row["src"].startswith("/ui-icon/") for row in result["nav"]))
        self.assertTrue(all(row["loaded"] for row in result["nav"]))
        self.assertTrue(result["detail"]["src"].startswith("/ui-icon/"))
        self.assertTrue(result["detail"]["loaded"])

    def test_11h_platform_custom_proxy_stays_inside_settings_panel(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              __STABLE_PLATFORM_SETTINGS__
              window.UcpSettingsController.switchGroup('\\u5e73\\u53f0\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const proxySelect = Array.from(document.querySelectorAll('#page-settings select.platform-proxy'))
                .find(select => !select.disabled && Array.from(select.options).some(option => option.value === '\\u81ea\\u5b9a\\u4e49'));
              if (proxySelect) {
                const customOption = Array.from(proxySelect.options).find(option => option.value === '\\u81ea\\u5b9a\\u4e49');
                proxySelect.value = customOption.value;
                proxySelect.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const panel = document.querySelector('#page-settings .settings-detail-panel');
              const row = document.querySelector('#page-settings .setting-platform.has-proxy-custom');
              const input = row?.querySelector('.proxy-custom.active');
              const proxyControl = row?.querySelector('.custom-select.platform-proxy') || row?.querySelector('select.platform-proxy');
              const panelRect = panel?.getBoundingClientRect();
              const rowRect = row?.getBoundingClientRect();
              const inputRect = input?.getBoundingClientRect();
              const proxyRect = proxyControl?.getBoundingClientRect();
              const gap = inputRect && proxyRect ? Math.round(inputRect.left - proxyRect.right) : null;
              const inputWidthRatio = inputRect && proxyRect
                ? inputRect.width / Math.max(1, inputRect.width + proxyRect.width)
                : 0;
              const inputTopInset = inputRect && rowRect ? inputRect.top - rowRect.top : null;
              const inputBottomInset = inputRect && rowRect ? rowRect.bottom - inputRect.bottom : null;
              return {
                hasInput: Boolean(input),
                documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                rowOverflow: rowRect && panelRect ? rowRect.right - panelRect.right : null,
                inputOverflow: inputRect && panelRect ? inputRect.right - panelRect.right : null,
                inputWidth: inputRect ? inputRect.width : 0,
                proxyWidth: proxyRect ? proxyRect.width : 0,
                gap,
                inputWidthRatio,
                inputTopInset,
                inputBottomInset,
                inputHeightDelta: inputRect && proxyRect ? Math.abs(inputRect.height - proxyRect.height) : null,
                inputSameRow: inputRect && proxyRect
                  ? Math.abs((inputRect.top + inputRect.height / 2) - (proxyRect.top + proxyRect.height / 2)) <= 4
                  : false
              };
            }
            """.replace("__STABLE_PLATFORM_SETTINGS__", _stable_platform_settings_snapshot_js())
        )

        self.assertTrue(result["hasInput"])
        self.assertLessEqual(result["documentOverflow"], 1)
        self.assertLessEqual(result["rowOverflow"], 1)
        self.assertLessEqual(result["inputOverflow"], 1)
        self.assertGreaterEqual(result["proxyWidth"], 72)
        self.assertGreaterEqual(result["inputWidth"], 86)
        self.assertGreaterEqual(result["inputWidthRatio"], 0.45)
        self.assertLessEqual(result["inputWidthRatio"], 0.62)
        self.assertGreaterEqual(result["gap"], 7)
        self.assertGreaterEqual(result["inputTopInset"], 1)
        self.assertGreaterEqual(result["inputBottomInset"], 1)
        self.assertLessEqual(result["inputHeightDelta"], 1)
        self.assertTrue(result["inputSameRow"])

    def test_11ha_settings_card_slicing_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u57fa\\u7840\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const body = document.querySelector('#page-settings .settings-detail-body');
              const hint = document.querySelector('#page-settings .settings-hint-card');
              const row = document.querySelector('#page-settings .setting-row');
              const platformBefore = body?.getBoundingClientRect().width || 0;
              const styles = body ? getComputedStyle(body) : null;
              const rowStyles = row ? getComputedStyle(row) : null;
              const hintStyles = hint ? getComputedStyle(hint) : null;
              const basicMetrics = {
                bodyGap: styles?.gap || '',
                bodyPaddingLeft: styles?.paddingLeft || '',
                bodyRadius: styles?.borderRadius || '',
                rowMinHeight: rowStyles?.minHeight || '',
                rowPaddingTop: rowStyles?.paddingTop || '',
                rowRadius: rowStyles?.borderRadius || '',
                hintHeight: hint?.getBoundingClientRect().height || 0,
                hintRadius: hintStyles?.borderRadius || '',
                bodyHintSameWidth: body && hint
                  ? Math.abs(body.getBoundingClientRect().width - hint.getBoundingClientRect().width)
                  : 999,
                wideSettings: Array.from(document.querySelectorAll('#page-settings .setting-wide-control [data-setting]'))
                  .map(node => node.dataset.setting),
                platformBefore
              };
              window.UcpSettingsController.switchGroup('\\u5e73\\u53f0\\u8bbe\\u7f6e');
              window.UcpSettingsController.render(true);
              const platformBody = document.querySelector('#page-settings .settings-platform-body');
              const panel = document.querySelector('#page-settings .settings-detail-panel');
              return {
                ...basicMetrics,
                platformBodyWidth: platformBody?.getBoundingClientRect().width || 0,
                panelInnerWidth: panel
                  ? panel.getBoundingClientRect().width
                    - parseFloat(getComputedStyle(panel).paddingLeft)
                    - parseFloat(getComputedStyle(panel).paddingRight)
                  : 0
              };
            }
            """
        )

        self.assertEqual(result["bodyGap"], "7px")
        self.assertEqual(result["bodyPaddingLeft"], "10px")
        self.assertEqual(result["bodyRadius"], "12px")
        self.assertEqual(result["rowMinHeight"], "60px")
        self.assertEqual(result["rowPaddingTop"], "8px")
        self.assertEqual(result["rowRadius"], "9px")
        self.assertAlmostEqual(result["hintHeight"], 40, delta=1)
        self.assertEqual(result["hintRadius"], "9px")
        self.assertLessEqual(result["bodyHintSameWidth"], 1)
        self.assertIn("download_directory", result["wideSettings"])
        self.assertIn("filename_template", result["wideSettings"])
        self.assertIn("default_open_mode", result["wideSettings"])
        self.assertGreater(result["platformBodyWidth"], result["platformBefore"])
        self.assertLessEqual(abs(result["platformBodyWidth"] - result["panelInnerWidth"]), 2)

    def test_11hb_settings_controls_expose_backend_setting_keys(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              __STABLE_PLATFORM_SETTINGS__
              const groups = {
                basic: '\\u57fa\\u7840\\u8bbe\\u7f6e',
                download: '\\u4e0b\\u8f7d\\u8bbe\\u7f6e',
                platform: '\\u5e73\\u53f0\\u8bbe\\u7f6e',
                playback: '\\u64ad\\u653e\\u8bbe\\u7f6e',
                logging: '\\u65e5\\u5fd7\\u8bbe\\u7f6e',
                appearance: '\\u5916\\u89c2\\u8bbe\\u7f6e'
              };
              const collected = {};
              switchPage('settings');
              for (const [name, group] of Object.entries(groups)) {
                window.UcpSettingsController.switchGroup(group);
                window.UcpSettingsController.render(true);
                collected[name] = Array.from(new Set(
                  Array.from(document.querySelectorAll('#page-settings [data-setting]'))
                    .map(node => node.dataset.setting)
                    .filter(Boolean)
                )).sort();
              }
              return collected;
            }
            """.replace("__STABLE_PLATFORM_SETTINGS__", _stable_platform_settings_snapshot_js())
        )

        expected = {
            "basic": {
                "download_directory",
                "filename_template",
                "open_after_download",
                "show_browser_window",
                "default_open_mode",
            },
            "download": {
                "max_concurrent",
                "image_respects_concurrency",
                "request_timeout",
                "max_retries",
                "resume_enabled",
                "speed_limit_kb",
                "video_only",
            },
            "platform": {"max_items", "max_pages", "timeout", "proxy_app", "proxy_url"},
            "playback": {
                "default_player",
                "remember_position",
                "autoplay_next",
                "image_auto_advance_interval_seconds",
                "manual_image_switch",
            },
            "logging": {
                "retention_days",
                "failed_record_retention_days",
                "ui_log_max_display_count",
                "auto_copy_trace_on_error",
            },
            "appearance": {"language", "follow_system", "theme", "accent", "scale", "font_size"},
        }
        for group, keys in expected.items():
            self.assertTrue(keys.issubset(set(result[group])), (group, result[group]))

    def test_11i_default_open_mode_row_keeps_select_readable(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u57fa\\u7840\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const defaultOpen = document.querySelector('#page-settings [data-setting="default_open_mode"]');
              const cluster = defaultOpen?.closest('.setting-control-cluster');
              const selectBox = defaultOpen?.closest('.custom-select') || defaultOpen;
              const action = cluster?.querySelector('.setting-action');
              const selectRect = selectBox?.getBoundingClientRect();
              const actionRect = action?.getBoundingClientRect();
                return {
                hasCluster: Boolean(cluster),
                selectWidth: selectRect ? selectRect.width : 0,
                actionWidth: actionRect ? actionRect.width : 0,
                actionText: action?.textContent?.trim() || '',
                actionTitle: action?.getAttribute('title') || '',
                actionAria: action?.getAttribute('aria-label') || ''
              };
            }
            """
        )

        self.assertTrue(result["hasCluster"])
        self.assertGreaterEqual(result["selectWidth"], 140)
        self.assertLessEqual(result["actionWidth"], 104)
        self.assertIn("绑定默认打开方式", result["actionText"])
        self.assertIn("默认打开方式", result["actionTitle"])
        self.assertEqual(result["actionTitle"], result["actionAria"])

    def test_11ia_settings_custom_select_selected_option_keeps_theme_contrast(self):
        self._goto_ready()

        samples = self._page.evaluate(
            """
            async () => {
              const accents = ["blue", "green", "purple", "orange", "red"];
              const themes = ["light", "dark"];
              const waitFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve()));
              const rgb = value => {
                const raw = String(value || "");
                const nums = raw.match(/[\\d.]+/g);
                if (!nums || nums.length < 3) return null;
                if (raw.startsWith("color(")) {
                  return nums.slice(0, 3).map(Number).map(component => component <= 1 ? component * 255 : component);
                }
                return nums.slice(0, 3).map(Number);
              };
              const luminance = color => {
                if (!color) return 0;
                const channels = color.map(component => {
                  const normalized = component / 255;
                  return normalized <= 0.03928
                    ? normalized / 12.92
                    : Math.pow((normalized + 0.055) / 1.055, 2.4);
                });
                return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
              };
              const contrast = (front, back) => {
                const a = luminance(front);
                const b = luminance(back);
                const light = Math.max(a, b);
                const dark = Math.min(a, b);
                return (light + 0.05) / (dark + 0.05);
              };
              const sample = async (theme, accent) => {
                applyAppearance({ theme, accent, scale: "100%", font_size: "medium", language: "zh-CN" });
                window.UcpSettingsController.switchGroup("\\u57fa\\u7840\\u8bbe\\u7f6e");
                switchPage("settings");
                window.UcpSettingsController.render(true);
                await waitFrame();
                const select = document.querySelector('#page-settings select[data-setting="filename_template"]');
                const wrapper = select?.closest(".custom-select");
                const button = wrapper?.querySelector(".custom-select-button");
                button?.click();
                const deadline = Date.now() + 1200;
                let sampleResult = null;
                while (Date.now() < deadline) {
                  await waitFrame();
                  const menu = wrapper?.querySelector(".custom-select-menu");
                  const option = wrapper?.querySelector(".custom-select-option.selected");
                  const label = option?.querySelector(".custom-select-label");
                  const optionStyle = option ? getComputedStyle(option) : null;
                  const labelStyle = label ? getComputedStyle(label) : null;
                  const optionColor = optionStyle?.color || "";
                  const labelColor = labelStyle?.color || "";
                  const backgroundColor = optionStyle?.backgroundColor || "";
                  sampleResult = {
                    theme,
                    accent,
                    hasOption: Boolean(option && label && menu && !menu.hidden),
                    optionColor,
                    labelColor,
                    backgroundColor,
                    contrast: contrast(rgb(labelColor), rgb(backgroundColor)),
                  };
                  if (sampleResult.hasOption && optionColor && labelColor && backgroundColor) break;
                }
                closeCustomSelect(wrapper);
                return {
                  theme,
                  accent,
                  ...(sampleResult || {
                    hasOption: false,
                    optionColor: "",
                    labelColor: "",
                    backgroundColor: "",
                    contrast: 1,
                  }),
                };
              };
              const results = [];
              for (const theme of themes) {
                for (const accent of accents) {
                  results.push(await sample(theme, accent));
                }
              }
              return results;
            }
            """
        )

        for sample in samples:
            self.assertTrue(sample["hasOption"], sample)
            self.assertEqual(sample["labelColor"], sample["optionColor"], sample)
            self.assertGreaterEqual(sample["contrast"], 4.5, sample)

    def test_11j_settings_select_opens_up_near_panel_bottom(self):
        original_viewport = self._page.viewport_size
        self._page.set_viewport_size({"width": 1280, "height": 520})
        try:
            self._goto_ready()
            result = self._page.evaluate(
                """
                async () => {
                  const waitFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
                  const waitUntil = async (predicate, timeoutMs = 1200) => {
                    const deadline = Date.now() + timeoutMs;
                    let value = null;
                    while (Date.now() < deadline) {
                      value = predicate();
                      if (value && value.ready) return value;
                      await waitFrame();
                    }
                    return value || { ready: false };
                  };
                  const geometry = (wrapper, menu) => {
                    const wrapperRect = wrapper?.getBoundingClientRect();
                    const menuRect = menu?.getBoundingClientRect();
                    const opened = Boolean(menu && !menu.hidden);
                    const opensUp = Boolean(wrapper?.classList.contains('open-up'));
                    const menuAboveControl = Boolean(menuRect && wrapperRect && menuRect.bottom <= wrapperRect.top + 1);
                    const menuInsideViewport = Boolean(menuRect && menuRect.top >= 3 && menuRect.bottom <= window.innerHeight - 3);
                    return {
                      ready: opened && opensUp && menuAboveControl && menuInsideViewport,
                      opened,
                      opensUp,
                      menuAboveControl,
                      menuInsideViewport,
                      wrapperTop: wrapperRect ? Math.round(wrapperRect.top) : null,
                      wrapperBottom: wrapperRect ? Math.round(wrapperRect.bottom) : null,
                      menuTop: menuRect ? Math.round(menuRect.top) : null,
                      menuBottom: menuRect ? Math.round(menuRect.bottom) : null,
                      viewportHeight: window.innerHeight,
                    };
                  };
                  window.UcpSettingsController.switchGroup('\\u4e0b\\u8f7d\\u8bbe\\u7f6e');
                  switchPage('settings');
                  window.UcpSettingsController.render(true);
                  await waitFrame();
                  const select = document.querySelector('#page-settings select[data-setting="speed_limit_kb"]');
                  const wrapper = select?.closest('.custom-select');
                  const button = wrapper?.querySelector('.custom-select-button');
                  wrapper?.scrollIntoView({ block: 'end', inline: 'nearest' });
                  await waitUntil(() => {
                    const rect = wrapper?.getBoundingClientRect();
                    return { ready: Boolean(rect && window.innerHeight - rect.bottom <= 96) };
                  });
                  button?.click();
                  const menu = wrapper?.querySelector('.custom-select-menu');
                  return await waitUntil(() => geometry(wrapper, menu));
                }
                """
            )
        finally:
            if original_viewport:
                self._page.set_viewport_size(original_viewport)

        self.assertTrue(result["opened"], result)
        self.assertTrue(result["opensUp"], result)
        self.assertTrue(result["menuAboveControl"], result)
        self.assertTrue(result["menuInsideViewport"], result)

    def test_11k_download_settings_order_matches_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u4e0b\\u8f7d\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              return Array.from(document.querySelectorAll('#page-settings .setting-row'))
                .map(row => row.querySelector('[data-setting]')?.dataset.setting || '')
                .filter(Boolean);
            }
            """
        )

        self.assertEqual(
            result,
            [
                "max_concurrent",
                "image_respects_concurrency",
                "request_timeout",
                "max_retries",
                "resume_enabled",
                "speed_limit_kb",
                "video_only",
            ],
        )

    def test_11ka_download_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u4e0b\\u8f7d\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const keys = ['max_retries', 'speed_limit_kb'];
              return Object.fromEntries(keys.map(key => {
                const control = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = control?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["max_retries"]["label"], "重试次数")
        self.assertIn("失败后重试次数", result["max_retries"]["description"])
        self.assertEqual(result["speed_limit_kb"]["label"], "下载速度限制（KB/s）")
        self.assertIn("限制最大下载速度", result["speed_limit_kb"]["description"])

    def test_11kb_log_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u65e5\\u5fd7\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const keys = ['retention_days', 'failed_record_retention_days', 'ui_log_max_display_count'];
              return Object.fromEntries(keys.map(key => {
                const control = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = control?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["retention_days"]["label"], "日志保留天数")
        self.assertIn("初始化时自动清理", result["retention_days"]["description"])
        self.assertEqual(result["failed_record_retention_days"]["label"], "失败记录保留天数")
        self.assertIn("自动清理过期失败记录", result["failed_record_retention_days"]["description"])
        self.assertEqual(result["ui_log_max_display_count"]["label"], "UI日志最大显示数量")
        self.assertIn("限制日志中心展示条数", result["ui_log_max_display_count"]["description"])

    def test_11l_download_directory_browse_button_opens_dir_dialog(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            async () => {
              window.UcpSettingsController.switchGroup('\\u57fa\\u7840\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const row = document.querySelector('#page-settings .setting-download-directory');
              const button = row?.querySelector('.setting-path-browse');
              const icon = button?.querySelector('img');
              button?.click();
              await new Promise(resolve => setTimeout(resolve, 120));
              const modal = document.getElementById('dirModal');
              const result = {
                hasButton: Boolean(button),
                title: button?.getAttribute('title') || '',
                aria: button?.getAttribute('aria-label') || '',
                iconSrc: icon?.getAttribute('src') || '',
                display: modal?.style.display || ''
              };
              if (modal) modal.style.display = 'none';
              return result;
            }
            """
        )

        self.assertTrue(result["hasButton"])
        self.assertIn("选择保存目录", result["title"])
        self.assertEqual(result["title"], result["aria"])
        self.assertIn("action_open_directory.png", result["iconSrc"])
        self.assertEqual(result["display"], "flex")

    def test_11m_playback_setting_labels_match_gui(self):
        self._goto_ready()

        result = self._page.evaluate(
            """
            () => {
              window.UcpSettingsController.switchGroup('\\u64ad\\u653e\\u8bbe\\u7f6e');
              switchPage('settings');
              window.UcpSettingsController.render(true);
              const keys = ['remember_position', 'autoplay_next', 'manual_image_switch'];
              return Object.fromEntries(keys.map(key => {
                const input = document.querySelector(`#page-settings [data-setting="${key}"]`);
                const row = input?.closest('.setting-row');
                return [key, {
                  label: row?.querySelector('.setting-label strong')?.textContent?.trim() || '',
                  description: row?.querySelector('.setting-label em')?.textContent?.trim() || ''
                }];
              }));
            }
            """
        )

        self.assertEqual(result["remember_position"]["label"], "记住播放进度")
        self.assertIn("下次恢复播放位置", result["remember_position"]["description"])
        self.assertEqual(result["autoplay_next"]["label"], "视频播放完自动下一项")
        self.assertIn("结束后播放下一项", result["autoplay_next"]["description"])
        self.assertEqual(result["manual_image_switch"]["label"], "图片只手动切换")
        self.assertIn("关闭图片自动轮播", result["manual_image_switch"]["description"])
