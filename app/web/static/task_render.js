(function () {
  let escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  let escapeAttr = value => escapeHtml(value).replace(/'/g, "&#39;");
  let translate = value => String(value || "");
  let getIconManifest = () => ({ route: "/ui-icon", fallback: "view_grid.png", actions: {}, platforms: {} });
  let activeTrendRenderer = () => "";
  let activeEventTimelineRenderer = () => "";
  const pendingMetadataTexts = ["\u68c0\u6d4b\u4e2d", "Checking", "\u6aa2\u6e2c\u4e2d"];

  function activeLanguage() {
    let root = document.documentElement;
    try {
      if (globalThis.parent && globalThis.parent !== globalThis && globalThis.parent.document) {
        root = globalThis.parent.document.documentElement;
      }
    } catch (_error) {
      root = document.documentElement;
    }
    const language = String(root?.dataset?.language || "").trim();
    return ["zh-CN", "en-US", "zh-TW"].includes(language) ? language : "zh-CN";
  }

  function pendingMetadataLabel() {
    const language = activeLanguage();
    if (language === "en-US") return "Checking";
    if (language === "zh-TW") return "\u6aa2\u6e2c\u4e2d";
    return "\u68c0\u6d4b\u4e2d";
  }

  let metadataValueRenderer = (value, pending = false) => {
    const text = String(value || "").trim();
    if (pending && (!text || text === "--" || pendingMetadataTexts.includes(text))) {
      return pendingMetadataLabel();
    }
    if (text && text !== "--") return translate(text);
    return pending ? pendingMetadataLabel() : "--";
  };
  let basenameResolver = () => "";
  let dirnameResolver = () => "";

  const PLATFORM_ICONS = {
    douyin: "platform_douyin.png",
    bilibili: "platform_bilibili.png",
    kuaishou: "platform_kuaishou.png",
    missav: "platform_missav.png",
    xiaohongshu: "platform_xiaohongshu.png",
  };

  function configure(options = {}) {
    if (typeof options.esc === "function") escapeHtml = options.esc;
    if (typeof options.escAttr === "function") escapeAttr = options.escAttr;
    if (typeof options.t === "function") translate = options.t;
    if (typeof options.getIconManifest === "function") getIconManifest = options.getIconManifest;
    if (typeof options.activeTrendHtml === "function") activeTrendRenderer = options.activeTrendHtml;
    if (typeof options.activeEventTimelineHtml === "function") activeEventTimelineRenderer = options.activeEventTimelineHtml;
    if (typeof options.displayMetadataValue === "function") metadataValueRenderer = options.displayMetadataValue;
    if (typeof options.basenameFromPath === "function") basenameResolver = options.basenameFromPath;
    if (typeof options.dirnameFromPath === "function") dirnameResolver = options.dirnameFromPath;
  }

  function manifest() {
    const value = getIconManifest();
    return value && typeof value === "object" ? value : {};
  }

  function iconFileUrl(file) {
    const current = manifest();
    return `${escapeAttr(current.route || "/ui-icon")}/${escapeAttr(file || current.fallback || "view_grid.png")}`;
  }

  function platformIcon(platformId) {
    const current = manifest();
    const key = String(platformId || "").toLowerCase();
    const file = (current.platforms || {})[key] || PLATFORM_ICONS[key];
    return file ? `${escapeAttr(current.route || "/ui-icon")}/${escapeAttr(file)}` : "";
  }

  function platformHtml(platform, platformId) {
    const icon = platformId ? platformIcon(platformId) : "";
    return `<span class="platform-cell">${icon ? `<img src="${escapeAttr(icon)}" alt="" />` : ""}${escapeHtml(translate(platform || "\u672c\u5730"))}</span>`;
  }

  function progressHtml(value) {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    return `<span class="progress"><i style="width:${pct}%"></i></span>${pct}%`;
  }

  function actionButton(actionId, label, onclick, danger = false) {
    const current = manifest();
    const icon = (current.actions || {})[actionId] || current.fallback || "view_grid.png";
    const dangerClass = danger ? " danger" : "";
    const clickAttr = onclick ? ` onclick="${escapeAttr(onclick)}"` : "";
    const translated = translate(label);
    return `<button class="op icon${dangerClass}" type="button" title="${escapeAttr(translated)}" aria-label="${escapeAttr(translated)}"${clickAttr}><img src="${escapeAttr(current.route || "/ui-icon")}/${escapeAttr(icon)}" alt="" /></button>`;
  }

  function smartWrapText(value) {
    return escapeHtml(String(value ?? "")).replace(/([\\/])/g, "$1<wbr>");
  }

  const LONG_TEXT_KEYS = new Set(["\u6807\u9898", "\u6587\u4ef6\u540d", "\u8f93\u51fa\u6587\u4ef6\u540d"]);

  function kvHtml(pairs, wrapKeys = new Set()) {
    const implicitWrapKeys = new Set(["\u6807\u9898", "\u6587\u4ef6\u540d", "\u4fdd\u5b58\u8def\u5f84", "\u4fdd\u5b58\u76ee\u5f55", "\u8f93\u51fa\u6587\u4ef6\u540d", "\u6765\u6e90\u94fe\u63a5"]);
    return `<div class="kv">${pairs.map(([key, value]) => {
      const keyText = String(key);
      const shouldWrap = wrapKeys.has(keyText) || implicitWrapKeys.has(keyText);
      const valueText = String(value ?? "");
      const valueClass = shouldWrap
        ? `kv-value smart-wrap${LONG_TEXT_KEYS.has(keyText) ? " long-text" : ""}`
        : `kv-value${LONG_TEXT_KEYS.has(keyText) ? " long-text" : ""}`;
      const valueHtml = shouldWrap ? smartWrapText(valueText) : escapeHtml(valueText);
      return `<span>${escapeHtml(translate(keyText))}</span><span class="${valueClass}" title="${escapeAttr(valueText)}">${valueHtml}</span>`;
    }).join("")}</div>`;
  }

  function queueTitleHtml(item) {
    const subtitle = item.created_at || item.discovered_at || item.added_at || "";
    return `<span class="title-main">${escapeHtml(item.title)}</span>${subtitle ? `<span class="title-sub">${escapeHtml(subtitle)}</span>` : ""}`;
  }

  function queueStatusHtml(status) {
    const label = status || "\u5f85\u4e0b\u8f7d";
    const current = manifest();
    const queueStatus = current.queue_status || {};
    const statusIcons = current.status || {};
    let iconFile = queueStatus[label] || "";
    if (!iconFile && (label.includes("\u5931\u8d25") || label.includes("\u9519\u8bef"))) iconFile = statusIcons.failed || "status_failed.png";
    if (!iconFile && (label.includes("\u5b8c\u6210") || label.includes("\u5df2\u89e3\u6790") || label.includes("\u5b58\u5728"))) iconFile = statusIcons.success || "status_success.png";
    if (!iconFile && (label.includes("\u4e0b\u8f7d") || label.includes("\u8fd0\u884c") || label.includes("\u89e3\u6790\u4e2d"))) iconFile = statusIcons.running || "status_running.png";
    iconFile = iconFile || statusIcons.pending || "status_pending.png";
    return `<span class="icon-text queue-status-cell"><img src="${iconFileUrl(iconFile)}" alt="" />${escapeHtml(translate(label))}</span>`;
  }

  function queueRow(item) {
    const id = escapeAttr(item.id);
    return `
      <tr data-id="${id}">
        <td title="${escapeAttr(item.title)}">${queueTitleHtml(item)}</td>
        <td>${platformHtml(item.platform, item.platform_id)}</td>
        <td>${queueStatusHtml(item.status)}</td>
        <td>${actionButton("delete", "\u5220\u9664", `event.stopPropagation();frontendAction('delete_item',{id:'${id}'})`, true)}</td>
      </tr>
    `;
  }

  function queueEventsHtml(items) {
    const recent = (items || []).slice(-3).reverse();
    return `
      <strong>${escapeHtml(translate("\u4efb\u52a1\u52a8\u6001\uff08\u6700\u8fd1 3 \u6761\uff09"))}</strong>
      ${recent.length
        ? recent.map(item => `<span title="${escapeAttr(item.title)}">${escapeHtml(translate(item.status || "\u5f85\u4e0b\u8f7d"))}\uff1a${escapeHtml(item.title || "")}</span>`).join("")
        : `<span>${escapeHtml(translate("\u6682\u65e0\u961f\u5217\u4efb\u52a1"))}</span>`}
    `;
  }

  function activeRow(item, selectedId) {
    const id = escapeAttr(item.id);
    return `
      <tr data-id="${id}" class="${selectedId === item.id ? "selected" : ""}" onclick="selectActive('${id}')">
        <td title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</td>
        <td>${platformHtml(item.platform, item.platform_id)}</td>
        <td>${progressHtml(item.progress)}</td>
        <td>${escapeHtml(item.speed || "0 B/s")}</td>
        <td>${escapeHtml(item.remaining_time || item.eta || "--")}</td>
        <td>${actionButton("delete", "\u5220\u9664", `event.stopPropagation();frontendAction('delete_item',{id:'${id}'})`, true)}</td>
      </tr>
    `;
  }

  function activeDetailHtml(item) {
    if (!item) {
      return `
        <div class="active-detail-card"><h2>${escapeHtml(translate("\u5f53\u524d\u4e0b\u8f7d"))}</h2><div class="active-detail-fields"><p>${escapeHtml(translate("\u6682\u65e0\u6b63\u5728\u4e0b\u8f7d\u7684\u4efb\u52a1"))}</p></div></div>
        <div class="active-events-card">
          <h2>${escapeHtml(translate("\u5f53\u524d\u4efb\u52a1\u4e8b\u4ef6"))}</h2>
          ${activeEventTimelineRenderer([])}
        </div>
      `;
    }
    const detailFields = Array.isArray(item.detail_fields) && item.detail_fields.length
      ? item.detail_fields.map(field => [field.label || "", field.value || ""])
      : [
          ["\u6807\u9898", item.title], ["\u5e73\u53f0", item.platform], ["\u4fdd\u5b58\u76ee\u5f55", item.save_dir || ""], ["\u8f93\u51fa\u6587\u4ef6\u540d", item.output_filename || ""],
          ["\u6765\u6e90\u94fe\u63a5", item.source_url], ["Trace ID", item.trace_id],
        ];
    const wrapLabels = new Set(
      (Array.isArray(item.detail_fields) && item.detail_fields.length
        ? item.detail_fields.filter(field => field && field.wrap).map(field => field.label || "")
        : ["\u4fdd\u5b58\u76ee\u5f55", "\u8f93\u51fa\u6587\u4ef6\u540d", "\u6765\u6e90\u94fe\u63a5"])
    );
    const chunk = item.chunk_progress || {};
    const chunkPercent = Number(chunk.percent ?? item.progress ?? 0);
    const chunkText = item.chunk_progress_label || `${chunkPercent}% (${chunk.completed || 0}/${chunk.total || 0})`;
    return `
      <div class="active-detail-card">
        <h2>${escapeHtml(translate("\u5f53\u524d\u4e0b\u8f7d"))}</h2>
        <div class="active-detail-fields">
          ${kvHtml(detailFields, wrapLabels)}
        </div>
        <div class="active-detail-metrics">
          <div class="active-chunk">
            <div><strong>${escapeHtml(translate("\u5206\u7247\u8fdb\u5ea6"))}</strong><span>${escapeHtml(chunkText)}</span></div>
            ${progressHtml(chunkPercent)}
          </div>
          <h2>${escapeHtml(translate("\u901f\u5ea6\u8d8b\u52bf\uff08\u8fd160\u79d2\uff09"))}</h2>
          ${activeTrendRenderer(item.speed_trend || [], item.speed_trend_label || item.speed || "0 B/s")}
        </div>
      </div>
      <div class="active-events-card">
        <h2>${escapeHtml(translate("\u5f53\u524d\u4efb\u52a1\u4e8b\u4ef6"))}</h2>
        ${activeEventTimelineRenderer(item.events || [])}
      </div>
    `;
  }

  function completedRow(item, selectedId) {
    const id = escapeAttr(item.id);
    return `
      <tr data-id="${id}" class="${selectedId === item.id ? "selected" : ""}" onclick="selectCompleted('${id}')">
        <td title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.completed_at_table || item.completed_at || "")}</td>
        <td>${escapeHtml(metadataValueRenderer(item.duration, item.metadata_pending))}</td>
        <td>${escapeHtml(item.format)}</td>
        <td>${actionButton("play", "\u64ad\u653e", `event.stopPropagation();playCompleted('${id}')`)}${actionButton("open_directory", "\u6253\u5f00\u76ee\u5f55", `event.stopPropagation();openDirectory('${id}')`)}${actionButton("delete", "\u5220\u9664", `event.stopPropagation();frontendAction('delete_item',{id:'${id}'})`, true)}</td>
      </tr>
    `;
  }

  function completedDetailHtml(item) {
    if (!item) return `<h2>${escapeHtml(translate("\u6587\u4ef6\u4fe1\u606f"))}</h2><p>${escapeHtml(translate("\u6682\u65e0\u5df2\u5b8c\u6210\u6587\u4ef6"))}</p>`;
    const filename = item.filename || basenameResolver(item.local_path) || item.title || "";
    const saveDir = item.save_dir || dirnameResolver(item.local_path) || "";
    return `
      <h2>${escapeHtml(translate("\u6587\u4ef6\u4fe1\u606f"))}</h2>
      ${kvHtml([["\u6587\u4ef6\u540d", filename], ["\u4fdd\u5b58\u8def\u5f84", saveDir], ["\u5b8c\u6210\u65f6\u95f4", item.completed_at], ["\u65f6\u957f", metadataValueRenderer(item.duration, item.metadata_pending)], ["\u5206\u8fa8\u7387", metadataValueRenderer(item.resolution, item.metadata_pending)], ["\u5927\u5c0f", item.size], ["\u683c\u5f0f", item.format]])}
    `;
  }

  function failedStatusHtml(text) {
    return `<span class="failed-status-chip"><i aria-hidden="true">\u00d7</i>${escapeHtml(translate(text || "\u5931\u8d25"))}</span>`;
  }

  function iconTextHtml(text, iconFile) {
    return `<span class="icon-text"><img src="${iconFileUrl(iconFile)}" alt="" />${escapeHtml(translate(text || ""))}</span>`;
  }

  function detailRowHtml(label, value, iconFile = "") {
    const icon = iconFile ? `<img src="${iconFileUrl(iconFile)}" alt="" />` : "";
    return `<div class="failed-detail-row"><span>${escapeHtml(translate(label))}</span><strong>${icon}${escapeHtml(translate(value || ""))}</strong></div>`;
  }

  function failedLogLevel(entry) {
    const raw = String(entry.level || entry.raw_level || "").trim().toUpperCase();
    let level = raw;
    if (!level) {
      const icon = String(entry.icon_file || "").toLowerCase();
      if (icon.includes("error")) level = "ERROR";
      else if (icon.includes("warn")) level = "WARN";
      else if (icon.includes("success") || icon.includes("ok")) level = "SUCCESS";
      else if (icon.includes("cmd") || icon.includes("command")) level = "CMD";
      else level = "INFO";
    }
    if (level === "WARNING") return "WARN";
    if (level === "OK") return "SUCCESS";
    if (level === "COMMAND") return "CMD";
    if (["INFO", "SUCCESS", "WARN", "ERROR", "CMD"].includes(level)) return level;
    return level.slice(0, 8) || "INFO";
  }

  function failedLogLevelClass(level) {
    const normalized = String(level || "INFO").toLowerCase();
    return ["info", "success", "warn", "error", "cmd"].includes(normalized) ? normalized : "info";
  }

  function failedLogTime(value) {
    const text = String(value || "").trim();
    if (!text) return "--:--:--";
    let candidate = text.split(/\s+/).pop() || text;
    candidate = candidate.split(".")[0];
    if (/^\d{1,2}:\d{2}:\d{2}$/.test(candidate)) return candidate.padStart(8, "0");
    const match = text.match(/(\d{1,2}:\d{2}:\d{2})(?:\.\d+)?/);
    if (match) return match[1].padStart(8, "0");
    return text.slice(-8).padStart(8, "-");
  }

  function failedLogRowHtml(entry) {
    const level = failedLogLevel(entry);
    return `
      <div class="failed-log-row">
        <span class="log-time">${escapeHtml(failedLogTime(entry.time))}</span>
        <span class="log-level log-level-${failedLogLevelClass(level)}">${escapeHtml(level)}</span>
        <span class="log-message">${escapeHtml(translate(entry.message || ""))}</span>
      </div>
    `;
  }

  function solutionRowHtml(solution) {
    return `
      <div class="failed-solution-row">
        <img src="${iconFileUrl(solution.icon_file || "action_help.png")}" alt="" />
        <span><strong>${escapeHtml(translate(solution.title || "\u5efa\u8bae"))}</strong><small>${escapeHtml(translate(solution.description || ""))}</small></span>
      </div>
    `;
  }

  function failedRow(item, selectedId) {
    const id = escapeAttr(item.id);
    return `
      <tr data-id="${id}" class="${selectedId === item.id ? "selected" : ""}" onclick="selectFailed('${id}')">
        <td title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.failed_at_table || item.failed_at)}</td>
        <td>${iconTextHtml(item.reason_label || item.reason || "", item.reason_icon_file || "status_error_warning.png")}</td>
        <td>${failedStatusHtml(item.status_label || item.status || "\u5931\u8d25")}</td>
        <td>${actionButton("copy_diagnostics", "\u590d\u5236 Trace ID", `event.stopPropagation();copyDiagnostics('${id}')`)}${actionButton("delete", "\u5220\u9664", `event.stopPropagation();frontendAction('delete_item',{id:'${id}'})`, true)}</td>
      </tr>
    `;
  }

  function failedDetailHtml(item) {
    if (!item) return `<h2>${escapeHtml(translate("\u9519\u8bef\u8be6\u60c5"))}</h2><p>${escapeHtml(translate("\u6682\u65e0\u5931\u8d25\u4efb\u52a1"))}</p>`;
    const current = manifest();
    const platformIconFile = (current.platforms || {})[String(item.platform_id || "").toLowerCase()] || "platform_web.png";
    const logItems = item.log_excerpt_items || (item.log_excerpt || []).map(message => ({ level: "INFO", time: "", message, icon_file: "log_level_info.png" }));
    return `
      <h2>${escapeHtml(translate("\u9519\u8bef\u8be6\u60c5"))}</h2>
      <div class="failed-summary">
        ${detailRowHtml("\u6807\u9898", item.title)}
        ${detailRowHtml("\u5931\u8d25\u65f6\u95f4", item.failed_at)}
        ${detailRowHtml("\u5931\u8d25\u539f\u56e0", item.reason_detail || item.reason, item.reason_icon_file || "status_error_warning.png")}
        ${detailRowHtml("\u5e73\u53f0", item.platform, platformIconFile)}
        ${detailRowHtml("Trace ID", item.trace_id)}
      </div>
      <h2>Trace / ${escapeHtml(translate("\u65e5\u5fd7\u7247\u6bb5"))}</h2>
      <div class="failed-log-list">${logItems.length ? logItems.map(failedLogRowHtml).join("") : `<div class="empty-note">${escapeHtml(translate("\u6682\u65e0\u65e5\u5fd7\u7247\u6bb5"))}</div>`}</div>
    `;
  }

  function failedSolutionsHtml(item) {
    const solutions = item && item.solutions ? item.solutions : [];
    return `
      <h2>${escapeHtml(translate("\u53ef\u80fd\u7684\u89e3\u51b3\u65b9\u6848"))}</h2>
      <div class="failed-solution-list">${solutions.length ? solutions.map(solutionRowHtml).join("") : `<div class="empty-note">${escapeHtml(translate("\u6682\u65e0\u5efa\u8bae"))}</div>`}</div>
    `;
  }

  window.UcpTaskRender = {
    configure,
    iconFileUrl,
    platformIcon,
    platformHtml,
    progressHtml,
    actionButton,
    smartWrapText,
    kvHtml,
    queueTitleHtml,
    queueStatusHtml,
    queueRow,
    queueEventsHtml,
    activeRow,
    activeDetailHtml,
    completedRow,
    completedDetailHtml,
    failedStatusHtml,
    iconTextHtml,
    detailRowHtml,
    failedLogLevel,
    failedLogLevelClass,
    failedLogTime,
    failedLogRowHtml,
    solutionRowHtml,
    failedRow,
    failedDetailHtml,
    failedSolutionsHtml,
  };
})();
