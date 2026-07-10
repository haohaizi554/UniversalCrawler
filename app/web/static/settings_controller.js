(function () {
  let dependencies = Object.freeze({});
  const SETTINGS_GROUP_ORDER_FALLBACK = ["基础设置", "下载设置", "平台设置", "播放设置", "日志设置", "外观设置"];
  const SETTINGS_GROUP_DESCRIPTIONS_FALLBACK = {
    "基础设置": "下载目录、命名规则和打开行为",
    "下载设置": "并发、超时、重试和下载策略",
    "平台设置": "认证状态、爬取数量和代理入口",
    "播放设置": "播放器、进度记忆和预览行为",
    "日志设置": "保留策略、展示数量和错误追踪",
    "外观设置": "语言、主题色、缩放和字体",
  };
  const SETTINGS_GROUP_HINTS_FALLBACK = {
    "基础设置": "路径支持粘贴和选择，命名规则使用预设模板，避免非法文件名。",
    "下载设置": "并发越高不一定越快，建议根据网络和磁盘性能调整。",
    "平台设置": "认证状态自动检测；代理仅对需要的平台开放。",
    "播放设置": "播放设置只影响本地预览，不影响下载文件。",
    "日志设置": "UI 显示数量只影响日志中心显示，不影响日志文件本身。",
    "外观设置": "外观设置会即时生效，并保存到本地配置。",
  };
  const SETTINGS_GROUP_ICONS = {
    "基础设置": "action_open_directory.png",
    "下载设置": "action_download.png",
    "平台设置": "platform_web.png",
    "播放设置": "action_play.png",
    "日志设置": "nav_log_center.png",
    "外观设置": "action_theme_palette.png",
  };
  const SETTING_SECTION_GROUPS = Object.freeze({
    basic: "基础设置",
    download: "下载设置",
    playback: "播放设置",
    logs: "日志设置",
    appearance: "外观设置",
    common: "外观设置",
  });
  const state = {
    currentGroup: "基础设置",
    htmlSignature: "",
    disposed: true,
  };

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.currentGroup = localStorage.getItem("webui_settings_group") || "基础设置";
    state.htmlSignature = "";
    state.disposed = false;
    configureSettingsRender();
    return window.UcpSettingsController;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpSettingsController is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function optionLabel(value) {
    return requireDependency("optionLabel")(value);
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escAttr(value) {
    return esc(value).replace(/'/g, "&#39;");
  }

  function normalizeSettingsGroupName(group) {
    const service = window.UcpI18n || null;
    const canonical = service && typeof service.canonicalUiText === "function"
      ? service.canonicalUiText(group)
      : String(group || "");
    return SETTINGS_GROUP_ORDER_FALLBACK.includes(canonical) ? canonical : String(group || "");
  }

  function settingsContract() {
    const contract = currentState().settings_contract || {};
    const order = Array.isArray(contract.group_order) ? contract.group_order.filter(Boolean) : [];
    return {
      order,
      descriptions: contract.group_descriptions || {},
      hints: contract.group_hints || {},
    };
  }

  function countOptionLabel(value, unit) {
    const service = window.UcpPlatformLimits || null;
    return service && typeof service.countOptionLabel === "function"
      ? service.countOptionLabel(value, unit)
      : String(value || "");
  }

  function platformIconUrl(platformId, iconFile) {
    const id = String(platformId || "").toLowerCase();
    const manifest = currentState().icon_manifest || {};
    const route = String(manifest.route || "/ui-icon").replace(/\/$/, "");
    const file = iconFile || (manifest.platforms || {})[id] || "platform_web.png";
    return `${route}/${file}`;
  }

  function configureSettingsRender() {
    const service = window.UcpSettingsRender || null;
    if (!service || typeof service.configure !== "function") return null;
    service.configure({ esc, escAttr, t, optionLabel, countOptionLabel, platformIconUrl });
    return service;
  }

  function settingsRenderService() {
    const service = configureSettingsRender();
    if (!service) throw new Error("UcpSettingsRender is unavailable");
    return service;
  }

  function settingsControls(group, value) {
    return settingsRenderService().settingsControls(group, value);
  }

  function platformSettingsSummary(rows) {
    return settingsRenderService().platformSettingsSummary(rows);
  }

  function platformSettingsHeader() {
    return settingsRenderService().platformSettingsHeader();
  }

  function platformSettingRow(row) {
    return settingsRenderService().platformSettingRow(row);
  }

  function isCustomProxyValue(value) {
    return settingsRenderService().isCustomProxyValue(value);
  }

  function proxyCustomDisplayValue(value) {
    return settingsRenderService().proxyCustomDisplayValue(value);
  }

  function settingInput(label, key, value, scope = "") {
    return settingsRenderService().settingInput(label, key, value, scope);
  }

  function settingCheckbox(label, key, checked, scope = "") {
    return settingsRenderService().settingCheckbox(label, key, checked, scope);
  }

  function imageManualSwitchSetting(value, options) {
    return settingsRenderService().imageManualSwitchSetting(value, options);
  }

  function normalizeSettingOption(option) {
    return settingsRenderService().normalizeSettingOption(option);
  }

  function settingSelect(label, key, value, options, scope = "", extraAttrs = "") {
    return settingsRenderService().settingSelect(label, key, value, options, scope, extraAttrs);
  }

  function settingGroupIconFile(group) {
    return SETTINGS_GROUP_ICONS[group] || "nav_settings.png";
  }

  function hasFocusedDescendant(element) {
    return !!element && !!document.activeElement && element.contains(document.activeElement);
  }

  function renderSettings(force = false) {
    const settings = currentState().settings_snapshot || {};
    const contract = settingsContract();
    const fallbackOrder = contract.order.length ? contract.order : SETTINGS_GROUP_ORDER_FALLBACK;
    const orderedGroups = fallbackOrder.filter(group => Object.prototype.hasOwnProperty.call(settings, group));
    for (const group of Object.keys(settings)) {
      if (!orderedGroups.includes(group)) orderedGroups.push(group);
    }
    state.currentGroup = normalizeSettingsGroupName(state.currentGroup);
    if (!orderedGroups.includes(state.currentGroup)) state.currentGroup = orderedGroups[0] || "基础设置";
    const currentValue = settings[state.currentGroup] || {};
    const description = contract.descriptions[state.currentGroup]
      || SETTINGS_GROUP_DESCRIPTIONS_FALLBACK[state.currentGroup]
      || "";
    const hint = contract.hints[state.currentGroup]
      || SETTINGS_GROUP_HINTS_FALLBACK[state.currentGroup]
      || "";
    const title = document.querySelector("#page-settings .page-head h1");
    if (title) title.textContent = t("配置中心");
    const subtitle = document.querySelector("#page-settings .page-head p");
    if (subtitle) subtitle.textContent = t("集中管理下载行为、平台状态、播放体验、日志策略与界面外观");
    const navHtml = orderedGroups.map(group => `
      <button class="settings-nav-btn ${group === state.currentGroup ? "active" : ""}" type="button" data-group="${escAttr(group)}" onclick="switchSettingsGroup('${escAttr(group)}')">
        <img src="${escAttr(platformIconUrl("", settingGroupIconFile(group)))}" alt="" />
        <span>${esc(t(group))}</span>
      </button>
    `).join("");
    const html = `
      <div class="settings-shell">
        <aside class="settings-side-nav">
          <div class="settings-nav-title">${esc(t("设置分类"))}</div>
          ${navHtml}
        </aside>
        <section class="settings-detail-panel">
          <header class="settings-detail-head">
            <span class="settings-detail-icon" aria-hidden="true">
              <img src="${escAttr(platformIconUrl("", settingGroupIconFile(state.currentGroup)))}" alt="" />
            </span>
            <h2>${esc(t(state.currentGroup))}</h2>
            <p>${esc(t(description))}</p>
          </header>
          <div class="settings-detail-body ${state.currentGroup === "平台设置" ? "settings-platform-body" : ""}">
            ${settingsControls(state.currentGroup, currentValue)}
          </div>
          ${hint ? `<div class="settings-hint-card"><span class="settings-hint-icon">i</span><span>${esc(t(hint))}</span></div>` : ""}
        </section>
      </div>
    `;
    const grid = byId("settingsGrid");
    if (!grid) return false;
    if (!force && state.htmlSignature && state.htmlSignature !== html && hasFocusedDescendant(grid)) return false;
    if (!force && state.htmlSignature === html) return false;
    grid.innerHTML = html;
    state.htmlSignature = html;
    queueMicrotask(() => {
      if (!state.disposed && typeof dependencies.enhanceSelects === "function") dependencies.enhanceSelects(grid);
    });
    return true;
  }

  function isPlatformSettingsVisible() {
    const page = byId("page-settings");
    return !!page && page.classList.contains("active") && normalizeSettingsGroupName(state.currentGroup) === "平台设置";
  }

  function maybeRefreshPlatformAuthStatus(force = false) {
    if (!isPlatformSettingsVisible()) return false;
    requireDependency("sendWS")("refresh_platform_auth_status", { force: Boolean(force) });
    return true;
  }

  function switchSettingsGroup(group) {
    if (!group) return false;
    const nextGroup = normalizeSettingsGroupName(group);
    const sameGroup = nextGroup === normalizeSettingsGroupName(state.currentGroup);
    if (!sameGroup) {
      state.currentGroup = nextGroup;
      localStorage.setItem("webui_settings_group", nextGroup);
      renderSettings(true);
    }
    maybeRefreshPlatformAuthStatus(false);
    return !sameGroup;
  }

  function patchSetting(group, key, value) {
    return requireDependency("patchSetting")(group, key, value);
  }

  function patchPlatformSetting(platformId, key, value) {
    return requireDependency("patchPlatformSetting")(platformId, key, value);
  }

  function requestPlatformSettingPatches(platformId, key, value) {
    const rows = (currentState().settings_snapshot || {})["平台设置"];
    if (!Array.isArray(rows)) return false;
    const row = rows.find(item => String(item.id || "") === String(platformId || ""));
    if (!row) return false;
    const text = String(value ?? "").trim();
    if (key === row.proxy_config_key || key === "proxy" || key === "proxy_url") {
      const proxyOptions = row.proxy_options || ["系统代理", "直连", "Clash (7890)", "v2rayN (10809)", "自定义"];
      const options = proxyOptions.map(normalizeSettingOption).filter(option => option.value);
      const optionKnown = options.some(option => String(option.value) === text);
      patchPlatformSetting(platformId, "proxy", text || "系统代理");
      patchPlatformSetting(platformId, "proxy_custom_active", text === "自定义" || (!!text && !optionKnown));
      if (text && text !== "自定义" && !optionKnown) patchPlatformSetting(platformId, "proxy_custom_value", text);
      return true;
    }
    if (key === row.count_config_key || key === "default_count" || key === "max_items") {
      patchPlatformSetting(platformId, "default_count", Number.isFinite(Number(text)) ? Number(text) : text);
      return true;
    }
    if (key === row.timeout_config_key || key === "timeout" || key === "default_timeout") {
      patchPlatformSetting(platformId, "default_timeout", Number.isFinite(Number(text)) ? Number(text) : text);
      return true;
    }
    patchPlatformSetting(platformId, key, value);
    return true;
  }

  function handleProxySelect(platformId, key, select) {
    const value = String((select && select.value) || "").trim();
    const row = select && select.closest ? select.closest(".setting-platform") : null;
    const input = row ? row.querySelector(".proxy-custom") : null;
    const proxyEntry = row ? row.querySelector(".platform-proxy-entry") : null;
    if (input) {
      const custom = isCustomProxyValue(value);
      row.classList.toggle("has-proxy-custom", custom);
      if (proxyEntry) proxyEntry.classList.toggle("has-custom", custom);
      input.hidden = !custom;
      input.disabled = !custom;
      input.classList.toggle("active", custom);
      if (custom) {
        if (value !== "自定义") input.value = proxyCustomDisplayValue(value);
        updateSetting(platformId, key, "自定义");
        input.focus();
        return true;
      }
    }
    updateSetting(platformId, key, value);
    return false;
  }

  function commitProxyCustom(platformId, key, input) {
    const value = String((input && input.value) || "").trim();
    if (!value) return false;
    updateSetting(platformId, key, value);
    return true;
  }

  function selectAppearanceTheme(value) {
    const theme = String(value || "").toLowerCase() === "dark" ? "dark" : "light";
    updateSetting("common", "theme", theme);
  }

  function updateBasicSetting(key, value) {
    if (!key) return false;
    patchSetting("基础设置", key, value);
    requireDependency("sendWS")("update_basic_setting", { key, value });
    return true;
  }

  function notifySideEffects(change) {
    if (typeof dependencies.syncAppearance === "function") dependencies.syncAppearance(change);
  }

  function updateSetting(section, key, value) {
    if (!section || !key) return false;
    if (section === "basic") {
      updateBasicSetting(key, value);
      return true;
    }
    if (section === "common" && key === "theme") {
      const dark = String(value).toLowerCase() === "dark";
      patchSetting("外观设置", "follow_system", false);
      patchSetting("外观设置", "theme", dark ? "dark" : "light");
      localStorage.setItem("cached_dark_theme", String(dark));
      notifySideEffects({ section, key, value, applyAppearance: true });
      if (normalizeSettingsGroupName(state.currentGroup) === "外观设置") renderSettings(true);
    } else if (section === "appearance" && ["scale", "font_size", "accent", "language", "follow_system"].includes(key)) {
      patchSetting("外观设置", key, value);
      notifySideEffects({
        section,
        key,
        value,
        applyAppearance: true,
        refreshLanguage: key === "language",
        renderCurrentPage: key === "font_size" || key === "scale",
      });
    } else if (section === "playback") {
      const normalizedValue = key === "image_auto_advance_interval_seconds" ? Number(value || 5) : value;
      patchSetting("播放设置", key, normalizedValue);
      if (normalizeSettingsGroupName(state.currentGroup) === "播放设置") renderSettings(true);
      notifySideEffects({ section, key, value: normalizedValue, reschedulePlayback: true });
    } else if (SETTING_SECTION_GROUPS[section]) {
      patchSetting(SETTING_SECTION_GROUPS[section], key, value);
    } else {
      requestPlatformSettingPatches(section, key, value);
    }
    requireDependency("sendWS")("update_setting", { section, key, value });
    return true;
  }

  function dispose() {
    if (state.disposed) return;
    state.disposed = true;
    state.htmlSignature = "";
    dependencies = Object.freeze({});
  }

  window.UcpSettingsController = Object.freeze({
    configure,
    render: renderSettings,
    switchGroup: switchSettingsGroup,
    updateBasic: updateBasicSetting,
    update: updateSetting,
    handleProxySelect,
    commitProxyCustom,
    selectAppearanceTheme,
    refreshPlatformAuthStatus: maybeRefreshPlatformAuthStatus,
    dispose,
  });
})();
