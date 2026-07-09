(function () {
  let dependencies = Object.freeze({});
  const LOG_RENDER_ROW_BUDGET = 300;
  const state = {
    filters: { category: "all", level: "all", time: "30m", platform: "all", trace: "", keyword: "" },
    page: 1,
    pageSize: 20,
    selectedId: "",
    querySequence: 0,
    detailSequence: 0,
    queryWorker: null,
    detailWorker: null,
    fallbackTimer: null,
    queryWorkerAvailable: false,
    detailWorkerAvailable: false,
    query: { signature: "", result: null, pending: false },
    detail: { signature: "", result: null, pending: false },
    rowSignatures: Object.create(null),
    generation: 0,
    disposed: true,
  };

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.filters = { category: "all", level: "all", time: "30m", platform: "all", trace: "", keyword: "" };
    state.page = 1;
    state.pageSize = normalizeLogPageSize(localStorage.getItem("webui_log_page_size") || 20);
    state.selectedId = "";
    state.queryWorkerAvailable = typeof Worker !== "undefined";
    state.detailWorkerAvailable = typeof Worker !== "undefined";
    state.query = { signature: "", result: null, pending: false };
    state.detail = { signature: "", result: null, pending: false };
    state.rowSignatures = Object.create(null);
    state.generation += 1;
    state.disposed = false;
    return window.UcpLogCenter;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpLogCenter is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function getLanguage() {
    return requireDependency("getLanguage")();
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function esc(value) {
    return requireDependency("esc")(value);
  }

  function escAttr(value) {
    return requireDependency("escAttr")(value);
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function logI18nService() {
    return window.UcpLogI18n || null;
  }

  function translateUiText(value) {
    return window.UcpI18n && typeof window.UcpI18n.translateUiText === "function"
      ? window.UcpI18n.translateUiText(value)
      : t(value);
  }

  function notifyFiltersChange() {
    if (typeof dependencies.onFiltersChange === "function") dependencies.onFiltersChange({ ...state.filters });
  }

  function normalizeLogPageSize(value) {
    const numeric = Number(value);
    if (numeric === 0) return 0;
    return [20, 50, 100].includes(numeric) ? numeric : 20;
  }

  function isAllLogFilterText(value) {
    const text = String(value || "").trim().toLowerCase();
    return !text || text === "all" || text === "\u5168\u90e8" || text === "\u6240\u6709";
  }

  function normalizeLogFilterValue(key, value) {
    const raw = String(value || "").trim();
    const canonical = window.UcpI18n && typeof window.UcpI18n.canonicalUiText === "function"
      ? window.UcpI18n.canonicalUiText(raw)
      : raw;
    if (key === "level") {
      if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
      return raw.toUpperCase();
    }
    if (key === "time") {
      if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
      const aliases = {
        "30m": "30m",
        "1h": "1h",
        "24h": "24h",
        "\u8fd1 30 \u5206\u949f": "30m",
        "\u8fd1 1 \u5c0f\u65f6": "1h",
        "\u8fd1 24 \u5c0f\u65f6": "24h",
        "Last 30 minutes": "30m",
        "Last 30 min": "30m",
        "Last 1 hour": "1h",
        "Last 24 hours": "24h",
      };
      return aliases[raw] || aliases[canonical] || raw || "30m";
    }
    if (key === "platform") {
      if (isAllLogFilterText(raw) || isAllLogFilterText(canonical)) return "all";
      return canonical || raw;
    }
    return raw;
  }

  function logSettingsSnapshot() {
    const snapshot = currentState().settings_snapshot || {};
    return snapshot["\u65e5\u5fd7\u8bbe\u7f6e"] || {};
  }

  function uiLogDisplayLimit() {
    const raw = Number(logSettingsSnapshot().ui_log_max_display_count || LOG_RENDER_ROW_BUDGET);
    const value = Number.isFinite(raw) ? Math.floor(raw) : LOG_RENDER_ROW_BUDGET;
    return [100, 300, 500].includes(value) ? value : LOG_RENDER_ROW_BUDGET;
  }

  function logItemId(item) {
    return window.UcpLogDisplay ? window.UcpLogDisplay.logItemId(item) : String((item && item.id) || "");
  }

  function logLevelClass(level) {
    const normalized = String(level || "").toUpperCase();
    if (["SUCCESS", "OK"].includes(normalized)) return "success";
    if (["WARN", "WARNING"].includes(normalized)) return "warn";
    if (normalized === "ERROR") return "error";
    if (["CMD", "COMMAND"].includes(normalized)) return "cmd";
    return "info";
  }

  function localizedLogTabLabel(category) {
    return logI18nService()?.localizedLogTabLabel(category) ?? String(category || "all");
  }

  function emptyLogTabCounts() {
    return Object.fromEntries(["all", "crawl", "download", "system", "performance", "error"].map(key => [key, 0]));
  }

  function currentLogTabCounts() {
    return (state.query.result && state.query.result.tabCounts) || emptyLogTabCounts();
  }

  function syncLogTabLabels(countsOverride) {
    const counts = countsOverride || currentLogTabCounts();
    document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => {
      const category = button.dataset.logTab || "all";
      button.textContent = `${localizedLogTabLabel(category)} ${counts[category] || 0}`;
    });
  }

  function syncLogStaticLanguage() {
    syncLogTabLabels();
    const labels = ["\u65e5\u5fd7\u7ea7\u522b", "\u65f6\u95f4\u8303\u56f4", "\u5e73\u53f0", "Trace ID", "\u5173\u952e\u8bcd\u641c\u7d22"];
    document.querySelectorAll("#page-logs .log-filter-label").forEach((label, index) => {
      if (labels[index]) label.textContent = t(labels[index]);
    });
    const trace = byId("logTraceFilter");
    if (trace) trace.placeholder = t("\u8bf7\u8f93\u5165 Trace ID");
    const keyword = byId("logKeywordFilter");
    if (keyword) keyword.placeholder = t("\u8bf7\u8f93\u5165\u5173\u952e\u8bcd...");
    const headers = ["\u65f6\u95f4", "\u7ea7\u522b", "\u6765\u6e90", "Trace ID", "\u6d88\u606f\u6458\u8981"];
    document.querySelectorAll("#page-logs th").forEach((header, index) => {
      if (headers[index]) header.textContent = t(headers[index]);
    });
    const actions = [
      ["runLogOperation('refresh')", "\u5237\u65b0"],
      ["runLogOperation('clear')", "\u6e05\u7a7a"],
      ["runLogOperation('export')", "\u5bfc\u51fa"],
      ["runLogOperation('open_latest')", "debug.log"],
      ["runLogOperation('open_error_summary')", "error.md"],
      ["copySelectedLogTraceId()", "\u590d\u5236TraceID"],
    ];
    for (const [onclick, label] of actions) {
      const button = document.querySelector(`#page-logs .log-actions [onclick="${onclick}"]`);
      if (button) button.textContent = t(label);
    }
    const previous = byId("logPrevPage");
    if (previous) previous.textContent = t("\u4e0a\u4e00\u9875");
    const next = byId("logNextPage");
    if (next) next.textContent = t("\u4e0b\u4e00\u9875");
  }

  function iconFileUrl(file) {
    const manifest = currentState().icon_manifest || {};
    const route = String(manifest.route || "/ui-icon").replace(/\/+$/, "");
    return `${escAttr(route)}/${escAttr(file || manifest.fallback || "view_grid.png")}`;
  }

  function logLevelCellHtml(item) {
    const label = item.level_display || item.level || "INFO";
    return `<span class="log-level-badge log-level-${logLevelClass(label)}">${esc(label)}</span>`;
  }

  function logValueHtml(value) {
    return esc(logI18nService()?.translateRuntimeLogText(value) ?? String(value ?? ""));
  }

  function logEventCodeText(value) {
    return logI18nService()?.localizeLogEventCode(value) ?? String(value || "-");
  }

  function logSourceCellHtml(item) {
    const label = item.source_display || item.source || item.platform || "";
    const iconFile = item.source_display_icon_file || "";
    const translated = logI18nService()?.translateRuntimeLogText(label) ?? String(label ?? "");
    if (!iconFile) return esc(translated);
    return `<span class="platform-cell log-source-cell"><img src="${iconFileUrl(iconFile)}" alt="" />${esc(translated)}</span>`;
  }

  function logDetailRowHtml(label, valueHtml) {
    return `<span>${esc(t(label))}</span><span class="kv-value">${valueHtml}</span>`;
  }

  function logDetailSummaryHtml(item) {
    const platform = item.platform_display || item.platform_label || item.platform || "";
    const i18n = logI18nService();
    const rows = [
      ["\u65f6\u95f4", esc(item.time || "")],
      ["\u7ea7\u522b", logLevelCellHtml(item)],
      ["\u6027\u8d28", logValueHtml(i18n?.logResultNatureText(item) ?? (item.result_type_display || item.type_display || item.nature_display || item.result_type || item.type || item.nature || "\u8fc7\u7a0b"))],
      ["\u8303\u56f4", logValueHtml(i18n?.logScopeDisplayText(item) ?? (item.log_scope_display || item.scope_display || item.log_scope || item.scope || item.category || "-"))],
      ["\u9636\u6bb5", logValueHtml(i18n?.logStageDisplayText(item) ?? (item.event_stage_display || item.stage_display || item.event_stage || item.stage || "-"))],
      ["\u4e8b\u4ef6\u7801", esc(logEventCodeText(item.event_code || item.status_code || "-"))],
      ["\u6765\u6e90", logSourceCellHtml(item)],
      ["\u5e73\u53f0", logValueHtml(platform || "-")],
      ["Trace ID", esc(item.trace_id || "-")],
      ["\u6d88\u606f", logValueHtml(item.message || item.message_summary || "-")],
    ];
    return `<div class="kv log-detail-kv">${rows.map(([label, value]) => logDetailRowHtml(label, value)).join("")}</div>`;
  }

  function emptyLogDetailSummaryHtml() {
    const labels = ["\u65f6\u95f4", "\u7ea7\u522b", "\u6027\u8d28", "\u8303\u56f4", "\u9636\u6bb5", "\u4e8b\u4ef6\u7801", "\u6765\u6e90", "\u5e73\u53f0", "Trace ID", "\u6d88\u606f"];
    return `<div class="kv log-detail-kv">${labels.map(label => logDetailRowHtml(label, esc("-"))).join("")}</div>`;
  }

  function logQueryItems() {
    const items = currentState().log_items;
    return Array.isArray(items) ? items : [];
  }

  function logItemSignature(item) {
    const detail = item && item.detail;
    let detailMarker = "";
    try {
      detailMarker = detail && typeof detail === "object" ? JSON.stringify(detail) : String(detail || "");
    } catch (_error) {
      detailMarker = String(detail || "");
    }
    return [
      logItemId(item),
      item.time || "",
      item.level || item.raw_level || "",
      item.source_display || item.source || "",
      item.platform_display || item.platform || "",
      item.trace_id || "",
      item.message_summary || "",
      item.message || "",
      item.event_code || item.status_code || "",
      detailMarker,
      item.stack || "",
    ].join("\u001f");
  }

  function logQuerySignature(items) {
    const first = items[0] || {};
    const last = items[items.length - 1] || {};
    return JSON.stringify({
      language: getLanguage(),
      count: items.length,
      first: logItemId(first),
      last: logItemId(last),
      firstTime: first.time || "",
      lastTime: last.time || "",
      items: items.map(logItemSignature),
      filters: state.filters,
      page: state.page,
      pageSize: state.pageSize,
      limit: uiLogDisplayLimit(),
    });
  }

  function buildLogQueryRequest(items, sequence) {
    return {
      sequence,
      items,
      filters: { ...state.filters },
      page: state.page,
      pageSize: state.pageSize,
      rowBudget: uiLogDisplayLimit(),
      selectedId: state.selectedId,
      nowMs: Date.now(),
    };
  }

  function queryLogsSyncRequest(request) {
    const items = Array.isArray(request && request.items) ? request.items : [];
    const sequence = request && request.sequence;
    if (!window.UcpLogDisplay || typeof window.UcpLogDisplay.queryLogItems !== "function") {
      return { sequence, pageItems: [], tabCounts: emptyLogTabCounts(), totalCount: items.length, matchedCount: 0, visibleCount: 0, currentPage: 1, totalPages: 1, selectedId: "" };
    }
    return window.UcpLogDisplay.queryLogItems(request);
  }

  function clearLogQueryFallback() {
    if (state.fallbackTimer === null) return;
    clearTimeout(state.fallbackTimer);
    state.fallbackTimer = null;
  }

  function closeLogQueryWorker() {
    const worker = state.queryWorker;
    state.queryWorker = null;
    state.query.pending = false;
    if (!worker) return;
    try { worker.terminate(); } catch (_error) {}
  }

  function closeLogDetailWorker() {
    const worker = state.detailWorker;
    state.detailWorker = null;
    state.detail.pending = false;
    if (!worker) return;
    try { worker.terminate(); } catch (_error) {}
  }

  function ensureLogQueryWorker() {
    if (!state.queryWorkerAvailable || state.disposed) return null;
    if (state.queryWorker) return state.queryWorker;
    const generation = state.generation;
    try {
      state.queryWorker = new Worker("/static/log_query_worker.js?v=20260707-log-worker");
      state.queryWorker.onmessage = event => {
        if (generation !== state.generation || state.disposed) return;
        const payload = event && event.data ? event.data : {};
        if (payload.type === "result") receiveLogQueryResult(payload.result);
        else if (payload.type === "error") {
          state.queryWorkerAvailable = false;
          closeLogQueryWorker();
          state.query.signature = "";
          render();
        }
      };
      state.queryWorker.onerror = () => {
        if (generation !== state.generation || state.disposed) return;
        state.queryWorkerAvailable = false;
        closeLogQueryWorker();
        state.query.signature = "";
        render();
      };
    } catch (_error) {
      state.queryWorkerAvailable = false;
      state.queryWorker = null;
    }
    return state.queryWorker;
  }

  function logsPageIsActive() {
    const page = byId("page-logs");
    return !page || page.classList.contains("active");
  }

  function receiveLogQueryResult(result) {
    if (state.disposed || !result || Number(result.sequence) !== state.querySequence) return;
    state.query = { signature: state.query.signature, result, pending: false };
    if (logsPageIsActive()) renderLogQueryResult(result);
  }

  function scheduleLogQueryFallback(items, sequence) {
    clearLogQueryFallback();
    const generation = state.generation;
    const request = buildLogQueryRequest(Array.isArray(items) ? items.slice() : [], sequence);
    state.fallbackTimer = setTimeout(() => {
      state.fallbackTimer = null;
      if (state.disposed || generation !== state.generation || Number(sequence) !== state.querySequence) return;
      receiveLogQueryResult(queryLogsSyncRequest(request));
    }, 0);
  }

  function submitLogQuery(items, signature) {
    const sequence = ++state.querySequence;
    state.query = { signature, result: state.query.result, pending: true };
    const worker = ensureLogQueryWorker();
    if (!worker) {
      scheduleLogQueryFallback(items, sequence);
      return;
    }
    clearLogQueryFallback();
    worker.postMessage(buildLogQueryRequest(items, sequence));
  }

  function render() {
    if (state.disposed) requireDependency("getState");
    syncLogStaticLanguage();
    syncLogFilterControls();
    const items = logQueryItems();
    const signature = logQuerySignature(items);
    if (state.query.signature === signature && state.query.result && !state.query.pending) {
      renderLogQueryResult(state.query.result);
      return;
    }
    submitLogQuery(items, signature);
    if (state.query.result) renderLogQueryResult(state.query.result);
  }

  function patchLogTableRows(items) {
    const tbody = byId("logBody");
    if (!tbody) return;
    const existing = new Map();
    Array.from(tbody.children).forEach(row => {
      const key = row.dataset.key || row.dataset.id;
      if (key) existing.set(key, row);
    });
    const seen = new Set();
    items.forEach((item, index) => {
      const key = logItemId(item);
      seen.add(key);
      const html = `
        <tr class="${state.selectedId === key ? "selected" : ""}" onclick="selectLog('${escAttr(key)}')">
          <td>${esc(item.time)}</td>
          <td>${logLevelCellHtml(item)}</td>
          <td>${logSourceCellHtml(item)}</td>
          <td>${esc(item.trace_id || "")}</td>
          <td title="${escAttr(logI18nService()?.translateRuntimeLogText(item.message_summary || "") ?? String(item.message_summary || ""))}">${logValueHtml(item.message_summary || "")}</td>
        </tr>
      `.trim();
      let row = existing.get(key);
      if (!row || state.rowSignatures[key] !== html) {
        const template = document.createElement("template");
        template.innerHTML = html;
        const next = template.content.firstElementChild;
        if (!next) return;
        next.dataset.key = key;
        if (row) row.replaceWith(next);
        row = next;
        state.rowSignatures[key] = html;
      }
      const current = tbody.children[index];
      if (current !== row) tbody.insertBefore(row, current || null);
    });
    Array.from(tbody.children).forEach(row => {
      const key = row.dataset.key || row.dataset.id;
      if (key && !seen.has(key)) row.remove();
    });
    for (const key of Object.keys(state.rowSignatures)) {
      if (!seen.has(key)) delete state.rowSignatures[key];
    }
  }

  function renderLogQueryResult(result) {
    syncLogStaticLanguage();
    syncLogFilterControls();
    const items = Array.isArray(result.pageItems) ? result.pageItems : [];
    const totalPages = Number(result.totalPages) || 1;
    state.page = Number(result.currentPage) || 1;
    syncLogTabLabels(result.tabCounts || emptyLogTabCounts());
    const requested = String(state.selectedId || result.selectedId || "");
    state.selectedId = items.some(item => logItemId(item) === requested) ? requested : (items.length ? logItemId(items[0]) : "");
    patchLogTableRows(items);
    syncLogEmptyState(items.length === 0);
    const allItems = currentState().log_items || [];
    const total = byId("logTotal");
    if (total) total.textContent = translateUiText(`\u5171 ${allItems.length} \u6761 / \u5339\u914d ${Number(result.matchedCount) || 0} \u6761 / \u5f53\u524d\u663e\u793a ${items.length} \u6761`);
    const indicator = byId("logPageIndicator");
    if (indicator) indicator.textContent = translateUiText(`\u7b2c ${state.page} / ${totalPages} \u9875`);
    const size = byId("logPageSize");
    if (size) size.value = String(state.pageSize);
    if (window.UcpCustomSelect && typeof window.UcpCustomSelect.syncForSelect === "function") window.UcpCustomSelect.syncForSelect(size);
    const previous = byId("logPrevPage");
    if (previous) previous.disabled = state.page <= 1 || state.pageSize <= 0;
    const next = byId("logNextPage");
    if (next) next.disabled = state.page >= totalPages || state.pageSize <= 0;
    renderLogDetail(items);
  }

  function syncLogEmptyState(empty) {
    const panel = byId("logEmptyState");
    if (!panel) return;
    panel.hidden = !empty;
    if (!empty) return;
    const title = panel.querySelector("strong");
    const subtitle = panel.querySelector(".log-empty-subtitle");
    const primary = panel.querySelector("[data-log-empty-primary]");
    const secondary = panel.querySelector("[data-log-empty-secondary]");
    if (title) title.textContent = t("\u6682\u65e0\u5339\u914d\u65e5\u5fd7");
    if (subtitle) subtitle.setAttribute("aria-label", t("\u8c03\u6574\u7b5b\u9009\u6761\u4ef6 \u6216\u70b9\u51fb\u300c\u5237\u65b0\u7f13\u51b2\u300d\u91cd\u65b0\u52a0\u8f7d\u65e5\u5fd7"));
    if (primary) primary.textContent = t("\u8c03\u6574\u7b5b\u9009\u6761\u4ef6");
    if (secondary) secondary.textContent = t("\u6216\u70b9\u51fb\u300c\u5237\u65b0\u7f13\u51b2\u300d\u91cd\u65b0\u52a0\u8f7d\u65e5\u5fd7");
  }

  function select(id) {
    state.selectedId = String(id || "");
    render();
  }

  function currentLogDetailItem(itemsOverride) {
    const items = Array.isArray(itemsOverride)
      ? itemsOverride
      : ((state.query.result && Array.isArray(state.query.result.pageItems)) ? state.query.result.pageItems : []);
    return items.find(row => logItemId(row) === state.selectedId) || null;
  }

  function logDetailSignature(item) {
    if (!item) return `${getLanguage()}|`;
    const detail = item.detail;
    const marker = detail && typeof detail === "object"
      ? [Object.keys(detail).sort().join(","), detail.description || "", detail.status_code || "", detail.event_code || ""].join("|")
      : String(detail || "");
    return [getLanguage(), logItemId(item), item.time || "", item.level || item.raw_level || "", item.platform_display || item.platform || "", item.source_display || item.source || "", item.trace_id || "", item.message || item.message_summary || "", item.event_code || item.status_code || "", marker, item.stack || ""].join("\u001f");
  }

  function buildLogDetailRequest(item, sequence) {
    return {
      sequence,
      itemId: logItemId(item),
      item,
      language: getLanguage(),
      translations: logI18nService()?.translationHints(item) ?? {},
    };
  }

  function emptyLogDetailResult(sequence = state.detailSequence) {
    return { sequence, itemId: "", language: getLanguage(), item: null, detailJson: "{}", detailDisplayText: "{}", fullJson: "{}", stack: "", filename: "log_detail_current.json" };
  }

  function ensureLogDetailWorker() {
    if (!state.detailWorkerAvailable || state.disposed) return null;
    if (state.detailWorker) return state.detailWorker;
    const generation = state.generation;
    try {
      state.detailWorker = new Worker("/static/log_detail_worker.js?v=20260709-log-detail-worker");
      state.detailWorker.onmessage = event => {
        if (generation !== state.generation || state.disposed) return;
        const payload = event && event.data ? event.data : {};
        if (payload.type === "result") receiveLogDetailResult(payload.result);
        else if (payload.type === "error") {
          state.detailWorkerAvailable = false;
          closeLogDetailWorker();
          renderLogDetailResult(emptyLogDetailResult(Number(payload.sequence) || state.detailSequence));
        }
      };
      state.detailWorker.onerror = () => {
        if (generation !== state.generation || state.disposed) return;
        state.detailWorkerAvailable = false;
        closeLogDetailWorker();
        renderLogDetailResult(emptyLogDetailResult());
      };
    } catch (_error) {
      state.detailWorkerAvailable = false;
      state.detailWorker = null;
    }
    return state.detailWorker;
  }

  function receiveLogDetailResult(result) {
    if (state.disposed || !result || Number(result.sequence) !== state.detailSequence) return;
    state.detail = { signature: state.detail.signature, result, pending: false };
    if (logsPageIsActive() && String(result.itemId || "") === state.selectedId) renderLogDetailResult(result);
  }

  function submitLogDetail(item) {
    const signature = logDetailSignature(item);
    if (state.detail.signature === signature && (state.detail.pending || state.detail.result)) return;
    const sequence = ++state.detailSequence;
    state.detail = { signature, result: null, pending: true };
    const worker = ensureLogDetailWorker();
    if (!worker) {
      state.detail = { signature, result: emptyLogDetailResult(sequence), pending: false };
      return;
    }
    worker.postMessage(buildLogDetailRequest(item, sequence));
  }

  function currentLogDetailResult() {
    const result = state.detail.result;
    if (!result || state.detail.pending || String(result.itemId || "") !== state.selectedId) return null;
    return result;
  }

  function renderEmptyLogDetail() {
    const root = byId("logDetail");
    if (!root) return;
    root.innerHTML = `
      <div class="log-inspector-header"><h2>${esc(t("\u65e5\u5fd7\u8be6\u60c5"))}</h2><div class="log-inspector-actions"><button class="btn" type="button" disabled>${esc(t("\u590d\u5236"))}</button><button class="btn" type="button" disabled>${esc(t("\u5bfc\u51fa"))}</button></div></div>
      <div class="log-detail-card">${emptyLogDetailSummaryHtml()}</div>
      <div class="log-extra-card log-json-card"><div class="log-card-head"><h2>${esc(t("\u8be6\u7ec6\u4fe1\u606f"))}</h2><button class="btn" type="button" disabled>${esc(t("\u590d\u5236"))}</button></div><pre class="log-snippet">{}</pre></div>
    `;
  }

  function renderPendingLogDetail(item) {
    const root = byId("logDetail");
    if (!root) return;
    root.innerHTML = `
      <div class="log-inspector-header"><h2>${esc(t("\u65e5\u5fd7\u8be6\u60c5"))}</h2><div class="log-inspector-actions"><button class="btn" type="button" disabled>${esc(t("\u590d\u5236"))}</button><button class="btn" type="button" disabled>${esc(t("\u5bfc\u51fa"))}</button></div></div>
      <div class="log-detail-card">${logDetailSummaryHtml(item)}</div>
      <div class="log-extra-card log-json-card"><div class="log-card-head"><h2>${esc(t("\u8be6\u7ec6\u4fe1\u606f"))}</h2><button class="btn" type="button" disabled>${esc(t("\u590d\u5236"))}</button></div><pre class="log-snippet">{}</pre></div>
    `;
  }

  function renderLogDetailResult(result) {
    const item = result && result.item ? result.item : null;
    if (!item) {
      renderEmptyLogDetail();
      return;
    }
    const stack = String(result.stack || "").trim();
    const blocks = [`<div class="log-extra-card log-json-card"><div class="log-card-head"><h2>${esc(t("\u8be6\u7ec6\u4fe1\u606f"))}</h2><button class="btn" type="button" onclick="copyCurrentLogJson()">${esc(t("\u590d\u5236"))}</button></div><pre class="log-snippet log-detail-readable" data-json="${escAttr(result.detailJson || "{}")}">${esc(result.detailDisplayText || "{}")}</pre></div>`];
    if (stack && stack !== "\u65e0") blocks.push(`<div class="log-extra-card"><h2>${esc(t("\u5806\u6808\u8ffd\u8e2a"))}</h2><pre class="log-snippet">${esc(stack)}</pre></div>`);
    const root = byId("logDetail");
    if (!root) return;
    root.innerHTML = `
      <div class="log-inspector-header"><h2>${esc(t("\u65e5\u5fd7\u8be6\u60c5"))}</h2><div class="log-inspector-actions"><button class="btn" type="button" onclick="copyCurrentLogDetail()">${esc(t("\u590d\u5236"))}</button><button class="btn" type="button" onclick="exportCurrentLogDetail()">${esc(t("\u5bfc\u51fa"))}</button></div></div>
      <div class="log-detail-card">${logDetailSummaryHtml(item)}</div>${blocks.join("")}
    `;
  }

  function renderLogDetail(itemsOverride) {
    const items = Array.isArray(itemsOverride) ? itemsOverride : ((state.query.result && state.query.result.pageItems) || []);
    const item = currentLogDetailItem(items);
    if (!item) {
      state.detailSequence += 1;
      state.detail = { signature: "", result: null, pending: false };
      renderEmptyLogDetail();
      return;
    }
    const signature = logDetailSignature(item);
    if (state.detail.signature === signature && state.detail.result && !state.detail.pending) {
      renderLogDetailResult(state.detail.result);
      return;
    }
    submitLogDetail(item);
    if (state.detail.result && !state.detail.pending) renderLogDetailResult(state.detail.result);
    else renderPendingLogDetail(item);
  }

  function reportMessage(message, detail = "") {
    if (typeof dependencies.writeClipboard === "function") dependencies.writeClipboard("", message, detail);
  }

  function copyDetail() {
    const item = currentLogDetailItem();
    if (!item) return reportMessage(t("\u6682\u65e0\u65e5\u5fd7"));
    const result = currentLogDetailResult();
    if (!result) {
      submitLogDetail(item);
      return reportMessage(t("\u8be6\u7ec6\u4fe1\u606f\u6b63\u5728\u51c6\u5907"));
    }
    return requireDependency("writeClipboard")(result.fullJson || "{}", t("\u5df2\u590d\u5236\u65e5\u5fd7\u8be6\u60c5"));
  }

  function copyJson() {
    const item = currentLogDetailItem();
    if (!item) return reportMessage(t("\u6682\u65e0\u65e5\u5fd7"));
    const result = currentLogDetailResult();
    if (!result) {
      submitLogDetail(item);
      return reportMessage(t("\u8be6\u7ec6\u4fe1\u606f\u6b63\u5728\u51c6\u5907"));
    }
    return requireDependency("writeClipboard")(result.detailJson || "{}", t("\u5df2\u590d\u5236\u8be6\u7ec6\u4fe1\u606f"));
  }

  function exportDetail() {
    const item = currentLogDetailItem();
    if (!item) return reportMessage(t("\u6682\u65e0\u65e5\u5fd7"));
    const result = currentLogDetailResult();
    if (!result) {
      submitLogDetail(item);
      return reportMessage(t("\u8be6\u7ec6\u4fe1\u606f\u6b63\u5728\u51c6\u5907"));
    }
    const blob = new Blob([result.fullJson || "{}"], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.filename || "log_detail_current.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    reportMessage(t("\u5df2\u5bfc\u51fa\u65e5\u5fd7\u8be6\u60c5"), link.download);
  }

  function setTab(category) {
    state.filters.category = category || "all";
    state.selectedId = "";
    state.page = 1;
    notifyFiltersChange();
    render();
  }

  function syncLogFiltersFromDom() {
    state.filters.level = normalizeLogFilterValue("level", byId("logLevelFilter")?.value || "all");
    state.filters.time = normalizeLogFilterValue("time", byId("logTimeFilter")?.value || "30m");
    state.filters.platform = normalizeLogFilterValue("platform", byId("logPlatformFilter")?.value || "all");
    state.filters.trace = byId("logTraceFilter")?.value.trim() || "";
    state.filters.keyword = byId("logKeywordFilter")?.value.trim() || "";
    state.selectedId = "";
    state.page = 1;
    notifyFiltersChange();
    render();
  }

  function selectValueOrFallback(select, preferredValue, fallbackValue) {
    if (!select || select.tagName !== "SELECT") return String(preferredValue ?? "");
    const options = Array.from(select.options);
    const preferred = String(preferredValue ?? "");
    if (options.some(option => String(option.value) === preferred)) return preferred;
    const fallback = String(fallbackValue ?? "");
    if (options.some(option => String(option.value) === fallback)) return fallback;
    const defaultOption = options.find(option => option.defaultSelected) || options[0];
    return defaultOption ? String(defaultOption.value) : "";
  }

  function syncLogFilterControls() {
    document.querySelectorAll("#logTabs [data-log-tab]").forEach(button => button.classList.toggle("active", button.dataset.logTab === state.filters.category));
    for (const [id, key, fallback] of [["logLevelFilter", "level", "all"], ["logTimeFilter", "time", "30m"], ["logPlatformFilter", "platform", "all"]]) {
      const node = byId(id);
      const value = selectValueOrFallback(node, normalizeLogFilterValue(key, state.filters[key]), fallback);
      if (node && node.value !== value) node.value = value;
      state.filters[key] = normalizeLogFilterValue(key, value);
      if (window.UcpCustomSelect && typeof window.UcpCustomSelect.syncForSelect === "function") window.UcpCustomSelect.syncForSelect(node);
    }
    for (const [id, value] of [["logTraceFilter", state.filters.trace], ["logKeywordFilter", state.filters.keyword]]) {
      const node = byId(id);
      if (node && node.value !== value) node.value = value;
    }
  }

  function setPage(delta) {
    state.page += Number(delta) || 0;
    render();
  }

  function setPageSize(value) {
    state.pageSize = normalizeLogPageSize(value);
    state.page = 1;
    localStorage.setItem("webui_log_page_size", String(state.pageSize));
    render();
    if (window.UcpCustomSelect && typeof window.UcpCustomSelect.syncForSelect === "function") window.UcpCustomSelect.syncForSelect(byId("logPageSize"));
  }

  function currentLogTraceId() {
    const items = (state.query.result && Array.isArray(state.query.result.pageItems)) ? state.query.result.pageItems : [];
    const current = items.find(row => logItemId(row) === state.selectedId);
    const trace = String((current && current.trace_id) || "").trim();
    if (trace) return trace;
    const fallback = items.find(row => String(row.trace_id || "").trim());
    return String((fallback && fallback.trace_id) || "").trim();
  }

  function copyTraceId() {
    const traceId = currentLogTraceId();
    if (!traceId) return reportMessage(t("\u5f53\u524d\u65e5\u5fd7\u6ca1\u6709\u53ef\u590d\u5236\u7684 Trace ID"));
    return requireDependency("writeClipboard")(traceId, t("\u5df2\u590d\u5236 Trace ID"), traceId);
  }

  function runOperation(operation) {
    return requireDependency("runOperation")(operation);
  }

  function dispose() {
    if (state.disposed) return;
    state.disposed = true;
    state.generation += 1;
    state.querySequence += 1;
    state.detailSequence += 1;
    clearLogQueryFallback();
    closeLogQueryWorker();
    closeLogDetailWorker();
    state.query.pending = false;
    state.detail.pending = false;
    dependencies = Object.freeze({});
  }

  window.UcpLogCenter = Object.freeze({
    configure,
    render,
    select,
    setTab,
    setPage,
    setPageSize,
    syncFiltersFromDom: syncLogFiltersFromDom,
    copyTraceId,
    copyDetail,
    copyJson,
    exportDetail,
    runOperation,
    dispose,
  });
})();
