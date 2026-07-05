(function () {
  let escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  let escapeAttr = value => escapeHtml(value).replace(/'/g, "&#39;");
  let translate = value => String(value || "");
  let translateOption = value => String(value || "");
  let platformIconUrl = () => "";
  let formatCountOption = (value, unit) => {
    const text = String(value || "");
    if (!text) return "";
    if (text === "9999") return "max";
    if (unit === "pages") return `${text} \u9875`;
    if (unit === "notes") return `${text} \u7bc7\u7b14\u8bb0`;
    return `${text} \u4e2a\u89c6\u9891`;
  };

  function configure(options = {}) {
    if (typeof options.esc === "function") escapeHtml = options.esc;
    if (typeof options.escAttr === "function") escapeAttr = options.escAttr;
    if (typeof options.t === "function") translate = options.t;
    if (typeof options.optionLabel === "function") translateOption = options.optionLabel;
    if (typeof options.countOptionLabel === "function") formatCountOption = options.countOptionLabel;
    if (typeof options.platformIconUrl === "function") platformIconUrl = options.platformIconUrl;
  }

  function normalizeSettingOption(option) {
    if (option && typeof option === "object") {
      const value = String(option.value ?? option.id ?? option.label ?? "");
      const label = String(option.label ?? value);
      return { value, label };
    }
    return { value: String(option ?? ""), label: String(option ?? "") };
  }

  const SETTING_SHORT_DESCRIPTIONS = {
    "\u4e0b\u8f7d\u76ee\u5f55": "\u4fdd\u5b58\u4e0b\u8f7d\u6587\u4ef6\u7684\u4f4d\u7f6e",
    "\u6587\u4ef6\u547d\u540d\u89c4\u5219": "\u4ece\u9884\u8bbe\u6a21\u677f\u4e2d\u9009\u62e9",
    "\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f": "\u4e0b\u8f7d\u5b8c\u6210\u540e\u7684\u6253\u5f00\u884c\u4e3a",
    "\u4e0b\u8f7d\u540e\u81ea\u52a8\u6253\u5f00": "\u4efb\u52a1\u5b8c\u6210\u540e\u81ea\u52a8\u6253\u5f00",
    "\u5e76\u53d1\u6570": "\u6700\u5927\u540c\u65f6\u4e0b\u8f7d\u6570",
    "\u56fe\u7247\u53d7\u5e76\u53d1\u6570\u9650\u5236": "\u63a7\u5236\u56fe\u7247\u5feb\u8f66\u9053",
    "\u8bf7\u6c42\u8d85\u65f6": "\u7f51\u7edc\u8bf7\u6c42\u7b49\u5f85\u65f6\u95f4",
    "\u91cd\u8bd5\u6b21\u6570": "\u5931\u8d25\u540e\u91cd\u8bd5\u6b21\u6570",
    "\u4e0b\u8f7d\u901f\u5ea6\u9650\u5236\uff08KB/s\uff09": "\u9650\u5236\u6700\u5927\u4e0b\u8f7d\u901f\u5ea6",
    "\u65ad\u70b9\u7eed\u4f20": "\u7ee7\u7eed\u672a\u5b8c\u6210\u4efb\u52a1",
    "\u4ec5\u4e0b\u8f7d\u89c6\u9891": "\u8df3\u8fc7\u56fe\u7247\u8d44\u6e90",
    "\u6253\u5f00\u65b9\u5f0f": "\u9ed8\u8ba4\u64ad\u653e\u65b9\u5f0f",
    "\u8bb0\u4f4f\u64ad\u653e\u8fdb\u5ea6": "\u4e0b\u6b21\u6062\u590d\u64ad\u653e\u4f4d\u7f6e",
    "\u89c6\u9891\u64ad\u653e\u5b8c\u81ea\u52a8\u4e0b\u4e00\u9879": "\u7ed3\u675f\u540e\u64ad\u653e\u4e0b\u4e00\u9879",
    "\u56fe\u7247\u53ea\u624b\u52a8\u5207\u6362": "\u5173\u95ed\u56fe\u7247\u81ea\u52a8\u8f6e\u64ad",
    "\u65e5\u5fd7\u4fdd\u7559\u5929\u6570": "\u521d\u59cb\u5316\u65f6\u81ea\u52a8\u6e05\u7406",
    "UI\u65e5\u5fd7\u6700\u5927\u663e\u793a\u6570\u91cf": "\u9650\u5236\u65e5\u5fd7\u4e2d\u5fc3\u5c55\u793a\u6761\u6570",
    "\u9519\u8bef\u65f6\u81ea\u52a8\u590d\u5236 Trace": "\u5f02\u5e38\u65f6\u590d\u5236\u8ffd\u8e2a\u7f16\u53f7",
    "\u8bed\u8a00": "\u754c\u9762\u8bed\u8a00",
    "\u8ddf\u968f\u7cfb\u7edf": "\u8ddf\u968f\u7cfb\u7edf\u4e3b\u9898",
    "\u4e3b\u9898": "\u4e3b\u9898\u6a21\u5f0f",
    "\u4e3b\u9898\u8272": "\u754c\u9762\u5f3a\u8c03\u8272",
    "\u754c\u9762\u7f29\u653e": "\u754c\u9762\u6bd4\u4f8b",
    "\u5b57\u4f53\u5927\u5c0f": "\u6587\u5b57\u5927\u5c0f",
  };

  function settingLabelHtml(label) {
    const description = SETTING_SHORT_DESCRIPTIONS[label] || "";
    return `
      <span class="setting-label">
        <strong>${escapeHtml(translate(label))}</strong>
        ${description ? `<em>${escapeHtml(translate(description))}</em>` : ""}
      </span>
    `;
  }

  function settingControlCluster(controlHtml, trailingHtml = "") {
    return `<span class="setting-control-cluster${trailingHtml ? " has-trailing-action" : ""}">${controlHtml}${trailingHtml}</span>`;
  }

  function settingRowClassForKey(key) {
    const classes = [];
    if (key === "download_directory") classes.push("setting-download-directory");
    if (["download_directory", "filename_template", "default_open_mode"].includes(key)) {
      classes.push("setting-wide-control");
    }
    return classes.length ? ` ${classes.join(" ")}` : "";
  }

  function settingsControls(group, value) {
    const options = value && value._options ? value._options : {};
    if (value && Object.prototype.hasOwnProperty.call(value, "download_directory")) {
      const associationLabel = translate("\u7ed1\u5b9a\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f");
      const associationText = escapeHtml(associationLabel);
      const associationAttr = escapeAttr(associationLabel);
      const associationButton = `<button class="btn setting-action" type="button" title="${associationAttr}" aria-label="${associationAttr}" onclick="showFileAssociationModal()">${associationText}</button>`;
      return [
        settingInput("\u4e0b\u8f7d\u76ee\u5f55", "download_directory", value && value.download_directory, "basic"),
        settingSelect("\u6587\u4ef6\u547d\u540d\u89c4\u5219", "filename_template", value && value.filename_template, options.filename_template || [], "basic"),
        settingCheckbox("\u4e0b\u8f7d\u540e\u81ea\u52a8\u6253\u5f00", "open_after_download", !!(value && value.open_after_download), "basic"),
        settingSelect("\u9ed8\u8ba4\u6253\u5f00\u65b9\u5f0f", "default_open_mode", value && value.default_open_mode, options.default_open_mode || [], "basic", "", associationButton),
      ].join("");
    }
    if (group === "\u4e0b\u8f7d\u8bbe\u7f6e") {
      return [
        settingSelect("\u5e76\u53d1\u6570", "max_concurrent", value && value.max_concurrent, options.max_concurrent || [], "download"),
        settingCheckbox("\u56fe\u7247\u53d7\u5e76\u53d1\u6570\u9650\u5236", "image_respects_concurrency", !!(value && value.image_respects_concurrency), "download"),
        settingSelect("\u8bf7\u6c42\u8d85\u65f6", "request_timeout", value && value.request_timeout, options.request_timeout || [], "download"),
        settingSelect("\u91cd\u8bd5\u6b21\u6570", "max_retries", value && value.max_retries, options.max_retries || [], "download"),
        settingCheckbox("\u65ad\u70b9\u7eed\u4f20", "resume_enabled", !!(value && value.resume_enabled), "download"),
        settingSelect("\u4e0b\u8f7d\u901f\u5ea6\u9650\u5236\uff08KB/s\uff09", "speed_limit_kb", value && value.speed_limit_kb, options.speed_limit_kb || [{ value: "0", label: "\u65e0\u9650\u5236" }], "download"),
        settingCheckbox("\u4ec5\u4e0b\u8f7d\u89c6\u9891", "video_only", !!(value && value.video_only), "download"),
      ].join("");
    }
    if (group === "\u5e73\u53f0\u8bbe\u7f6e") {
      const rows = Array.isArray(value) ? value : [];
      return `${platformSettingsSummary(rows)}${platformSettingsHeader()}${rows.map(platformSettingRow).join("")}`;
    }
    if (group === "\u64ad\u653e\u8bbe\u7f6e") {
      return [
        settingSelect("\u6253\u5f00\u65b9\u5f0f", "default_player", value && value.default_player, options.default_player || [], "playback"),
        settingCheckbox("\u8bb0\u4f4f\u64ad\u653e\u8fdb\u5ea6", "remember_position", !!(value && value.remember_position), "playback"),
        settingCheckbox("\u89c6\u9891\u64ad\u653e\u5b8c\u81ea\u52a8\u4e0b\u4e00\u9879", "autoplay_next", !!(value && value.autoplay_next), "playback"),
        imageManualSwitchSetting(value || {}, options || {}),
      ].join("");
    }
    if (group === "\u65e5\u5fd7\u8bbe\u7f6e") {
      return [
        settingSelect("\u65e5\u5fd7\u4fdd\u7559\u5929\u6570", "retention_days", value && value.retention_days, options.retention_days || [], "logging"),
        settingSelect("UI\u65e5\u5fd7\u6700\u5927\u663e\u793a\u6570\u91cf", "ui_log_max_display_count", value && value.ui_log_max_display_count, options.ui_log_max_display_count || [], "logging"),
        settingCheckbox("\u9519\u8bef\u65f6\u81ea\u52a8\u590d\u5236 Trace", "auto_copy_trace_on_error", !!(value && value.auto_copy_trace_on_error), "logging"),
      ].join("");
    }
    if (group === "\u5916\u89c2\u8bbe\u7f6e") {
      return [
        settingSelect("语言", "language", value && value.language, options.language || [], "appearance"),
        settingCheckbox("\u8ddf\u968f\u7cfb\u7edf", "follow_system", !!(value && value.follow_system), "appearance"),
        themeSegmentSetting(value && value.theme, options.theme || []),
        settingSelect("\u4e3b\u9898\u8272", "accent", value && value.accent, options.accent || [], "appearance"),
        settingSelect("\u754c\u9762\u7f29\u653e", "scale", value && value.scale, options.scale || [], "appearance"),
        settingSelect("\u5b57\u4f53\u5927\u5c0f", "font_size", value && value.font_size, options.font_size || [], "appearance"),
      ].join("");
    }
    return "";
  }

  function platformSettingsSummary(rows) {
    const total = rows.length;
    const authed = rows.filter(row => row.auth_status === "\u5df2\u8ba4\u8bc1").length;
    const unauthed = Math.max(0, total - authed);
    const proxyReady = rows.filter(row => row.proxy_editable && row.proxy_config_key).length;
    const chips = [
      ["\u5e73\u53f0\u603b\u6570", total],
      ["\u5df2\u8ba4\u8bc1", authed],
      ["\u672a\u8ba4\u8bc1", unauthed],
      ["\u53ef\u914d\u7f6e\u4ee3\u7406", proxyReady],
    ];
    return `
      <div class="platform-summary">
        ${chips.map(([label, value]) => `<span class="platform-chip"><b>${escapeHtml(translate(label))}</b><strong>${escapeHtml(value)}</strong></span>`).join("")}
      </div>
    `;
  }

  function platformSettingsHeader() {
    return `
      <div class="setting-platform setting-platform-header" aria-hidden="true">
        <span class="platform-name">${escapeHtml(translate("\u5e73\u53f0"))}</span>
        <span>${escapeHtml(translate("\u8ba4\u8bc1\u72b6\u6001"))}</span>
        <span>${escapeHtml(translate("\u722c\u53d6\u6570\u91cf"))}</span>
        <span>${escapeHtml(translate("\u8d85\u65f6"))}</span>
        <span>${escapeHtml(translate("\u4ee3\u7406\u5165\u53e3"))}</span>
      </div>
    `;
  }

  function platformSettingRow(row) {
    const countKey = row.count_config_key || "";
    const timeoutKey = row.timeout_config_key || "";
    const proxyKey = row.proxy_config_key || "";
    const countDisabled = row.count_editable && countKey ? "" : " disabled";
    const timeoutDisabled = row.timeout_editable && timeoutKey ? "" : " disabled";
    const proxyDisabled = row.proxy_editable && proxyKey ? "" : " disabled";
    let countOptions = (row.count_options || []).map(normalizeSettingOption).filter(option => option.value);
    const countValue = String(row.default_count || 20);
    if (!countOptions.some(option => option.value === countValue)) {
      const countUnit = ["pages", "notes"].includes(row.count_unit) ? row.count_unit : "videos";
      countOptions.unshift({ value: countValue, label: formatCountOption(countValue, countUnit) });
    }
    let timeoutOptions = (row.timeout_options || []).map(normalizeSettingOption).filter(option => option.value);
    const timeoutValue = String(row.default_timeout || row.timeout || 60);
    if (timeoutKey && !timeoutOptions.some(option => option.value === timeoutValue)) {
      timeoutOptions.unshift({ value: timeoutValue, label: `${timeoutValue} \u79d2` });
    }
    let proxyOptions = (row.proxy_options || ["\u7cfb\u7edf\u4ee3\u7406", "\u76f4\u8fde", "Clash (7890)", "v2rayN (10809)", "\u81ea\u5b9a\u4e49"]).map(normalizeSettingOption).filter(option => option.value);
    let proxyValue = String(row.proxy || "\u7cfb\u7edf\u4ee3\u7406");
    let proxyCustomValue = String(row.proxy_custom_value || "");
    if (proxyValue && !proxyOptions.some(option => option.value === proxyValue)) {
      proxyCustomValue = proxyCustomValue || proxyValue;
      proxyValue = "\u81ea\u5b9a\u4e49";
    }
    const proxyCustom = !!(row.proxy_custom_active || isCustomProxyValue(proxyValue));
    const hasCustomProxy = !!(row.proxy_custom_allowed && row.proxy_editable && proxyKey);
    const customProxy = hasCustomProxy
      ? `<input class="proxy-custom${proxyCustom ? " active" : ""}" data-platform="${escapeAttr(row.id || "")}" data-setting="proxy_url" value="${escapeAttr(proxyCustomDisplayValue(proxyCustomValue))}" placeholder="${escapeAttr(translate("\u7aef\u53e3"))}" ${proxyCustom ? "" : "hidden disabled"} onblur="commitProxyCustom('${escapeAttr(row.id || "")}', 'proxy_url', this)" />`
      : "";
    const proxyEntryClass = hasCustomProxy && proxyCustom ? " has-custom" : "";
    const authAuthed = row.auth_status === "\u5df2\u8ba4\u8bc1";
    const authLabel = authAuthed ? "\u5df2\u8ba4\u8bc1" : "\u672a\u8ba4\u8bc1";
    const platformIcon = platformIconUrl(row.id || row.name || "", row.icon_file || "");
    const platformName = escapeHtml(translate(row.name || row.id || "\u5e73\u53f0"));
    return `
      <div class="setting-row setting-platform${hasCustomProxy && proxyCustom ? " has-proxy-custom" : ""}">
        <span class="platform-name platform-name-cell">${platformIcon ? `<img src="${escapeAttr(platformIcon)}" alt="" />` : ""}<span>${platformName}</span></span>
        <span class="platform-auth platform-auth-badge ${authAuthed ? "is-authed" : "is-unauthed"}" title="${escapeAttr(row.auth_detail || "")}">${escapeHtml(translate(authLabel))}</span>
        <select class="platform-count" data-setting="${escapeAttr(countKey)}"${countDisabled} onchange="updateSetting('${escapeAttr(row.id || "")}', '${escapeAttr(countKey)}', this.value)">${countOptions.map(option => `<option value="${escapeAttr(option.value)}" ${countValue === option.value ? "selected" : ""}>${escapeHtml(translateOption(option.label))}</option>`).join("")}</select>
        <select class="platform-timeout" data-setting="${escapeAttr(timeoutKey)}"${timeoutDisabled} onchange="updateSetting('${escapeAttr(row.id || "")}', '${escapeAttr(timeoutKey)}', this.value)">${timeoutOptions.map(option => `<option value="${escapeAttr(option.value)}" ${timeoutValue === option.value ? "selected" : ""}>${escapeHtml(translateOption(option.label))}</option>`).join("")}</select>
        <span class="platform-proxy-entry${proxyEntryClass}">
          <select class="platform-proxy" data-setting="${escapeAttr(proxyKey)}"${proxyDisabled} onchange="handleProxySelect('${escapeAttr(row.id || "")}', '${escapeAttr(proxyKey)}', this)">${proxyOptions.map(option => `<option value="${escapeAttr(option.value)}" ${proxyValue === option.value ? "selected" : ""}>${escapeHtml(translateOption(proxyOptionDisplayLabel(option)))}</option>`).join("")}</select>
          ${customProxy}
        </span>
      </div>
    `;
  }

  function isCustomProxyValue(value) {
    const text = String(value || "").trim();
    return text === "\u81ea\u5b9a\u4e49" || text.includes("://") || text.includes(":");
  }

  function proxyOptionDisplayLabel(option) {
    const value = String(option && option.value || "").trim();
    const label = String(option && option.label || "").trim();
    if (value === "\u81ea\u5b9a\u4e49" || label.includes("\u81ea\u5b9a\u4e49")) return "\u81ea\u5b9a\u4e49";
    return label || value;
  }

  function proxyCustomDisplayValue(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const withoutScheme = text.includes("://") ? text.split("://", 2)[1] : text;
    const withoutAuth = withoutScheme.includes("@") ? withoutScheme.split("@").pop() : withoutScheme;
    const hostPart = withoutAuth.split("/", 1)[0];
    const port = hostPart.match(/:(\d{1,5})$/);
    return port ? port[1] : text;
  }

  function settingInput(label, key, value, scope = "") {
    const action = scope === "basic"
      ? ` onblur="updateBasicSetting('${escapeAttr(key)}', this.value)"`
      : (scope ? ` onblur="updateSetting('${escapeAttr(scope)}', '${escapeAttr(key)}', this.value)"` : "");
    const rowClass = settingRowClassForKey(key);
    const control = `<input data-setting="${escapeAttr(key)}" value="${escapeAttr(value || "")}" title="${escapeAttr(value || "")}"${action} />`;
    const browseTitle = escapeAttr(translate("\u9009\u62e9\u4fdd\u5b58\u76ee\u5f55"));
    const trailingHtml = key === "download_directory"
      ? `<button class="btn setting-path-browse" type="button" title="${browseTitle}" aria-label="${browseTitle}" onclick="showDirDialog()"><img src="/ui-icon/action_open_directory.png" alt="" /></button>`
      : "";
    return `<div class="setting-row${rowClass}">${settingLabelHtml(label)}${settingControlCluster(control, trailingHtml)}</div>`;
  }

  function settingCheckbox(label, key, checked, scope = "") {
    const action = scope === "basic"
      ? ` onchange="updateBasicSetting('${escapeAttr(key)}', this.checked)"`
      : (scope ? ` onchange="updateSetting('${escapeAttr(scope)}', '${escapeAttr(key)}', this.checked)"` : "");
    const control = `<input class="setting-switch" data-setting="${escapeAttr(key)}" type="checkbox" ${checked ? "checked" : ""}${action} />`;
    return `<div class="setting-row">${settingLabelHtml(label)}${settingControlCluster(control)}</div>`;
  }

  function imageManualSwitchSetting(value, options) {
    const manual = value.manual_image_switch === true;
    const intervalOptions = options.image_auto_advance_interval_seconds || [
      { value: "1", label: "1 \u79d2" },
      { value: "3", label: "3 \u79d2" },
      { value: "5", label: "5 \u79d2\uff08\u63a8\u8350\uff09" },
      { value: "10", label: "10 \u79d2" },
    ];
    const currentInterval = String(value.image_auto_advance_interval_seconds || 5);
    const normalized = intervalOptions.map(normalizeSettingOption).filter(option => option.value);
    const intervalSelect = `
      <select
        class="image-auto-interval"
        data-setting="image_auto_advance_interval_seconds"
        onchange="updateSetting('playback', 'image_auto_advance_interval_seconds', this.value)"
        ${manual ? "hidden disabled" : ""}
      >
        ${normalized.map(option => `<option value="${escapeAttr(option.value)}" ${currentInterval === option.value ? "selected" : ""}>${escapeHtml(translateOption(option.label))}</option>`).join("")}
      </select>
    `;
    return `
      <div class="setting-row image-manual-row">
        ${settingLabelHtml("\u56fe\u7247\u53ea\u624b\u52a8\u5207\u6362")}
        <span class="image-auto-controls">
          ${intervalSelect}
          <input class="setting-switch" data-setting="manual_image_switch" type="checkbox" ${manual ? "checked" : ""} onchange="updateSetting('playback', 'manual_image_switch', this.checked)" />
        </span>
      </div>
    `;
  }

  function themeSegmentSetting(value, options) {
    let normalized = (options && options.length ? options : [
      { value: "light", label: "\u6d45\u8272" },
      { value: "dark", label: "\u6df1\u8272" },
    ]).map(normalizeSettingOption).filter(option => ["light", "dark"].includes(String(option.value).toLowerCase()));
    if (!normalized.length) {
      normalized = [
        { value: "light", label: "\u6d45\u8272" },
        { value: "dark", label: "\u6df1\u8272" },
      ];
    }
    const current = String(value || "light").toLowerCase() === "dark" ? "dark" : "light";
    const control = `
      <span class="setting-theme-segment" role="radiogroup" aria-label="${escapeAttr(translate("\u6d45\u8272 / \u6df1\u8272"))}">
        ${normalized.map(option => {
          const optionValue = String(option.value).toLowerCase() === "dark" ? "dark" : "light";
          const selected = optionValue === current;
          return `<button class="setting-theme-segment-btn${selected ? " active" : ""}" type="button" role="radio" aria-checked="${selected ? "true" : "false"}" data-setting="theme" data-value="${escapeAttr(optionValue)}" onclick="selectAppearanceTheme('${escapeAttr(optionValue)}')">${escapeHtml(translateOption(option.label))}</button>`;
        }).join("")}
      </span>
    `;
    return `<div class="setting-row setting-theme-row">${settingLabelHtml("\u6d45\u8272 / \u6df1\u8272")}${settingControlCluster(control)}</div>`;
  }

  function settingSelect(label, key, value, options, scope = "", extraAttrs = "", trailingHtml = "") {
    let normalized = (options || []).map(normalizeSettingOption).filter(option => option.value);
    const current = String(value ?? (normalized[0] ? normalized[0].value : ""));
    if (current && !normalized.some(option => option.value === current)) normalized.unshift({ value: current, label: current });
    const action = scope === "basic"
      ? ` onchange="updateBasicSetting('${escapeAttr(key)}', this.value)"`
      : (scope ? ` onchange="updateSetting('${escapeAttr(scope)}', '${escapeAttr(key)}', this.value)"` : "");
    const labelHtml = label ? settingLabelHtml(label) : "";
    const control = `<select data-setting="${escapeAttr(key)}"${action}${extraAttrs}>${normalized.map(option => `<option value="${escapeAttr(option.value)}" ${current === option.value ? "selected" : ""}>${escapeHtml(translateOption(option.label))}</option>`).join("")}</select>`;
    return `<div class="setting-row${settingRowClassForKey(key)}">${labelHtml}${settingControlCluster(control, trailingHtml)}</div>`;
  }

  window.UcpSettingsRender = {
    configure,
    settingsControls,
    platformSettingsSummary,
    platformSettingsHeader,
    platformSettingRow,
    isCustomProxyValue,
    proxyCustomDisplayValue,
    settingInput,
    settingCheckbox,
    settingRowClassForKey,
    imageManualSwitchSetting,
    themeSegmentSetting,
    normalizeSettingOption,
    settingSelect,
  };
})();
