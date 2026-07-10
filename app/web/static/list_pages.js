(function () {
  let dependencies = Object.freeze({});
  const PAGED_LISTS = ["queue", "completed", "failed"];
  const state = {
    queuePage: 1,
    queuePageSize: 20,
    completedPage: 1,
    completedPageSize: 20,
    failedPage: 1,
    failedPageSize: 20,
    worker: null,
    workerAvailable: false,
    sequences: { queue: 0, completed: 0, failed: 0 },
    fallbackTimers: { queue: null, completed: null, failed: null },
    rowSignatures: Object.create(null),
    htmlSignatures: Object.create(null),
    generation: 0,
    disposed: true,
  };

  function configure(options = {}) {
    dispose();
    dependencies = Object.freeze({ ...options });
    state.queuePage = 1;
    state.queuePageSize = normalizeTablePageSize(localStorage.getItem("webui_queue_page_size") || 20);
    state.completedPage = 1;
    state.completedPageSize = normalizeTablePageSize(localStorage.getItem("webui_completed_page_size") || 20);
    state.failedPage = 1;
    state.failedPageSize = normalizeTablePageSize(localStorage.getItem("webui_failed_page_size") || 20);
    state.workerAvailable = typeof Worker !== "undefined";
    state.sequences = { queue: 0, completed: 0, failed: 0 };
    state.fallbackTimers = { queue: null, completed: null, failed: null };
    state.rowSignatures = Object.create(null);
    state.htmlSignatures = Object.create(null);
    state.generation += 1;
    state.disposed = false;
    return window.UcpListPages;
  }

  function requireDependency(name) {
    const value = dependencies[name];
    if (typeof value !== "function") throw new Error(`UcpListPages is not configured: ${name}`);
    return value;
  }

  function currentState() {
    return requireDependency("getState")() || {};
  }

  function selected(domain) {
    return typeof dependencies.getSelection === "function"
      ? String(dependencies.getSelection(domain) || "")
      : "";
  }

  function setSelected(domain, id) {
    if (typeof dependencies.setSelection === "function") {
      dependencies.setSelection(domain, String(id || ""));
    }
  }

  function t(value) {
    return requireDependency("t")(value);
  }

  function byId(id) {
    return requireDependency("byId")(id);
  }

  function translateUiText(value) {
    return window.UcpI18n && typeof window.UcpI18n.translateUiText === "function"
      ? window.UcpI18n.translateUiText(value)
      : t(value);
  }

  function taskRenderService() {
    if (!window.UcpTaskRender) throw new Error("UcpTaskRender is unavailable");
    return window.UcpTaskRender;
  }

  function normalizeTablePageSize(value) {
    const numeric = Number(value);
    return [20, 50, 100].includes(numeric) ? numeric : 20;
  }

  function syncCustomSelectForSelect(select) {
    if (window.UcpCustomSelect && typeof window.UcpCustomSelect.syncForSelect === "function") {
      window.UcpCustomSelect.syncForSelect(select);
    }
  }

  function setHtmlIfChanged(id, html) {
    const next = String(html || "");
    if (state.htmlSignatures[id] === next) return false;
    const node = byId(id);
    if (!node) return false;
    node.innerHTML = next;
    state.htmlSignatures[id] = next;
    return true;
  }

  function patchTableRows(tbodyId, rows, keyFn, rowHtmlFn) {
    const tbody = byId(tbodyId);
    if (!tbody) return;
    const existing = new Map();
    Array.from(tbody.children).forEach(row => {
      const key = row.dataset.key || row.dataset.id;
      if (key) existing.set(key, row);
    });
    const seen = new Set();
    rows.forEach((item, index) => {
      const key = String(keyFn(item, index));
      seen.add(key);
      const html = String(rowHtmlFn(item, index) || "").trim();
      const signatureKey = `${tbodyId}:${key}`;
      let row = existing.get(key);
      if (!row || state.rowSignatures[signatureKey] !== html) {
        const template = document.createElement("template");
        template.innerHTML = html;
        const next = template.content.firstElementChild;
        if (!next) return;
        next.dataset.key = key;
        if (row) row.replaceWith(next);
        row = next;
        state.rowSignatures[signatureKey] = html;
      }
      const current = tbody.children[index];
      if (current !== row) tbody.insertBefore(row, current || null);
    });
    Array.from(tbody.children).forEach(row => {
      const key = row.dataset.key || row.dataset.id;
      if (key && !seen.has(key)) {
        delete state.rowSignatures[`${tbodyId}:${key}`];
        row.remove();
      }
    });
  }

  function reconcileSelectedTask(domain, items) {
    const rows = Array.isArray(items) ? items : [];
    const current = selected(domain);
    if (current && rows.some(item => String((item || {}).id || "") === current)) return current;
    const next = rows.length ? String((rows[0] || {}).id || "") : "";
    setSelected(domain, next);
    return next;
  }

  function selectedTaskItem(domain, items) {
    const id = selected(domain);
    return (Array.isArray(items) ? items : []).find(item => String((item || {}).id || "") === id) || null;
  }

  function clearListPageFallback(pageKey) {
    const timer = state.fallbackTimers[pageKey];
    if (timer === null || timer === undefined) return;
    clearTimeout(timer);
    state.fallbackTimers[pageKey] = null;
  }

  function clearListPageFallbacks() {
    PAGED_LISTS.forEach(clearListPageFallback);
  }

  function closeListPageWorker(expectedWorker = null) {
    const worker = state.worker;
    if (expectedWorker && worker !== expectedWorker) return;
    state.worker = null;
    if (!worker) return;
    try {
      worker.terminate();
    } catch (_error) {
      // Browser teardown is best-effort.
    }
  }

  function ensureListPageWorker() {
    if (!state.workerAvailable || state.disposed) return null;
    if (state.worker) return state.worker;
    const generation = state.generation;
    try {
      const worker = new Worker("/static/list_page_worker.js?v=20260708-list-page-worker");
      state.worker = worker;
      worker.onmessage = event => applyListPageResult(event.data || {}, worker, generation);
      worker.onerror = () => {
        if (state.disposed || generation !== state.generation || state.worker !== worker) return;
        state.workerAvailable = false;
        closeListPageWorker(worker);
        renderQueue();
        renderCompleted();
        renderFailed();
      };
    } catch (_error) {
      state.workerAvailable = false;
      state.worker = null;
    }
    return state.worker;
  }

  function scheduleListPageFallback(request) {
    const pageKey = String(request.pageKey || "");
    clearListPageFallback(pageKey);
    const generation = state.generation;
    const snapshot = { ...request, items: Array.isArray(request.items) ? request.items.slice() : [] };
    const timer = setTimeout(() => {
      if (
        state.disposed ||
        generation !== state.generation ||
        state.fallbackTimers[pageKey] !== timer ||
        Number(snapshot.sequence) !== Number(state.sequences[pageKey] || 0)
      ) return;
      state.fallbackTimers[pageKey] = null;
      applyListPageResult(buildListPageResultSync(snapshot), null, generation);
    }, 0);
    state.fallbackTimers[pageKey] = timer;
  }

  function submitListPageRequest(pageKey, requestData) {
    if (!PAGED_LISTS.includes(pageKey) || state.disposed) return;
    clearListPageFallback(pageKey);
    state.sequences[pageKey] = (Number(state.sequences[pageKey]) || 0) + 1;
    const request = {
      type: "page",
      pageKey,
      sequence: state.sequences[pageKey],
      ...requestData,
    };
    const worker = ensureListPageWorker();
    if (worker) {
      worker.postMessage(request);
      return;
    }
    scheduleListPageFallback(request);
  }

  function applyListPageResult(result, worker = state.worker, generation = state.generation) {
    if (
      state.disposed ||
      generation !== state.generation ||
      state.worker !== worker ||
      !result ||
      result.type !== "page"
    ) return;
    const pageKey = String(result.pageKey || "");
    if (!PAGED_LISTS.includes(pageKey)) return;
    if (Number(result.sequence) !== Number(state.sequences[pageKey] || 0)) return;
    if (pageKey === "queue") {
      applyQueuePageResult(result);
      return;
    }
    if (pageKey === "completed") {
      applyCompletedPageResult(result);
      return;
    }
    applyFailedPageResult(result);
  }

  function buildListPageResultSync(request) {
    const items = Array.isArray(request.items) ? request.items : [];
    const pageSize = normalizeTablePageSize(request.pageSize);
    const totalCount = items.length;
    const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
    let currentPage = Math.max(1, Math.min(Number(request.page) || 1, totalPages));
    let selectedId = String(request.selectedId || "");
    if (selectedId && request.selectedIdMovesPage) {
      const selectedIndex = items.findIndex(item => String((item || {}).id || "") === selectedId);
      if (selectedIndex >= 0) currentPage = Math.floor(selectedIndex / pageSize) + 1;
    }
    const start = (currentPage - 1) * pageSize;
    const pageItems = items.slice(start, start + pageSize);
    const visibleIds = pageItems.map(item => String((item || {}).id || "")).filter(Boolean);
    if ((!selectedId || !visibleIds.includes(selectedId)) && request.selectFirst && visibleIds.length) {
      selectedId = visibleIds[0];
    }
    if (selectedId && !items.some(item => String((item || {}).id || "") === selectedId)) selectedId = "";
    return {
      type: "page",
      pageKey: String(request.pageKey || ""),
      sequence: Number(request.sequence) || 0,
      totalCount,
      totalPages,
      currentPage,
      pageSize,
      pageItems,
      selectedId,
    };
  }

  function renderQueue() {
    const snapshot = currentState();
    const settings = snapshot.settings_snapshot || {};
    const basic = settings["\u57fa\u7840\u8bbe\u7f6e"] || {};
    const path = byId("queuePath");
    if (path) path.textContent = basic.download_directory || "";
    const items = Array.isArray(snapshot.queue_items) ? snapshot.queue_items : [];
    submitListPageRequest("queue", {
      items,
      page: state.queuePage,
      pageSize: state.queuePageSize,
      selectedId: selected("queue"),
      selectFirst: false,
      selectedIdMovesPage: false,
    });
    setHtmlIfChanged("queueEvents", taskRenderService().queueEventsHtml(items));
  }

  function applyQueuePageResult(result) {
    const items = Array.isArray(result.pageItems) ? result.pageItems : [];
    const totalPages = Number(result.totalPages) || 1;
    state.queuePage = Number(result.currentPage) || 1;
    state.queuePageSize = normalizeTablePageSize(result.pageSize);
    patchTableRows("queueBody", items, item => item.id, item => taskRenderService().queueRow(item));
    const selectedId = selected("queue");
    const queueBody = byId("queueBody");
    if (queueBody) {
      Array.from(queueBody.querySelectorAll("tr[data-id]")).forEach(row => {
        row.classList.toggle("selected", String(row.dataset.id || "") === selectedId);
      });
    }
    byId("queueTotal").textContent = translateUiText(`\u5171 ${Number(result.totalCount) || 0} \u9879`);
    byId("queuePageNow").textContent = String(state.queuePage);
    byId("queueTotalPages").textContent = String(totalPages);
    byId("queuePageSize").value = String(state.queuePageSize);
    syncCustomSelectForSelect(byId("queuePageSize"));
    byId("queuePrevPage").disabled = state.queuePage <= 1;
    byId("queueNextPage").disabled = state.queuePage >= totalPages;
  }

  function restoreQueueControls() {
    document.body.classList.remove("queue-compact");
  }

  function setQueuePage(delta) {
    state.queuePage += Number(delta) || 0;
    renderQueue();
  }

  function setQueuePageSize(value) {
    state.queuePageSize = normalizeTablePageSize(value);
    state.queuePage = 1;
    localStorage.setItem("webui_queue_page_size", String(state.queuePageSize));
    renderQueue();
  }

  function setQueueDensity(_mode) {
    localStorage.removeItem("webui_queue_density");
    restoreQueueControls();
    renderQueue();
  }

  function renderActive() {
    syncActiveDownloadOptions();
    const items = Array.isArray(currentState().active_downloads) ? currentState().active_downloads : [];
    const selectedId = reconcileSelectedTask("active", items);
    patchTableRows("activeBody", items, item => item.id, item => taskRenderService().activeRow(item, selectedId));
    byId("activeSummary").textContent = translateUiText(`\u5f53\u524d\u8fd0\u884c\uff1a${items.length} \u4e2a\u4efb\u52a1`);
    renderActiveDetail();
  }

  function currentDownloadOptions() {
    const snapshot = currentState();
    const settings = (snapshot.settings_snapshot || {})["\u4e0b\u8f7d\u8bbe\u7f6e"] || {};
    const options = {
      auto_retry: true,
      max_retries: Number(settings.max_retries || 3),
      max_concurrent: normalizeDownloadConcurrency(settings.max_concurrent || 3),
      ...(snapshot.download_options || {}),
    };
    options.max_concurrent = normalizeDownloadConcurrency(options.max_concurrent);
    return options;
  }

  function normalizeDownloadConcurrency(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 1) return 1;
    if (numeric <= 3) return 3;
    return 5;
  }

  function ensureSelectOption(select, value, label = String(value)) {
    if (!select) return;
    const target = String(value);
    if (!Array.from(select.options).some(option => option.value === target)) {
      const option = document.createElement("option");
      option.value = target;
      option.textContent = label;
      select.appendChild(option);
      Array.from(select.options)
        .sort((a, b) => Number(a.value) - Number(b.value))
        .forEach(optionNode => select.appendChild(optionNode));
    }
  }

  function syncActiveDownloadOptions() {
    const options = currentDownloadOptions();
    const autoRetry = byId("activeAutoRetry");
    const retries = byId("activeMaxRetries");
    const concurrent = byId("activeMaxConcurrent");
    if (autoRetry) autoRetry.checked = Boolean(options.auto_retry);
    if (retries) {
      ensureSelectOption(retries, options.max_retries, `${options.max_retries}\u6b21`);
      retries.value = String(options.max_retries);
      syncCustomSelectForSelect(retries);
    }
    if (concurrent) {
      concurrent.value = String(normalizeDownloadConcurrency(options.max_concurrent));
      syncCustomSelectForSelect(concurrent);
    }
  }

  function updateDownloadOptions() {
    const autoRetry = Boolean(byId("activeAutoRetry") && byId("activeAutoRetry").checked);
    const maxRetries = Number(byId("activeMaxRetries") && byId("activeMaxRetries").value) || 3;
    const maxConcurrent = normalizeDownloadConcurrency(byId("activeMaxConcurrent") && byId("activeMaxConcurrent").value);
    requireDependency("frontendAction")("update_download_options", {
      auto_retry: autoRetry,
      max_retries: maxRetries,
      max_concurrent: maxConcurrent,
    });
  }

  function selectActive(id) {
    setSelected("active", id);
    renderActive();
  }

  function renderActiveDetail() {
    const item = selectedTaskItem("active", currentState().active_downloads || []);
    setHtmlIfChanged("activeDetail", taskRenderService().activeDetailHtml(item));
  }

  function cleanupPlaybackPositions(items) {
    if (window.UcpPlaybackState && typeof window.UcpPlaybackState.cleanupPlaybackPositions === "function") {
      window.UcpPlaybackState.cleanupPlaybackPositions(localStorage, currentState(), items);
    }
  }

  function renderCompleted() {
    const items = Array.isArray(currentState().completed_items) ? currentState().completed_items : [];
    cleanupPlaybackPositions(items);
    const selectedId = selected("completed");
    submitListPageRequest("completed", {
      items,
      page: state.completedPage,
      pageSize: state.completedPageSize,
      selectedId,
      selectFirst: true,
      selectedIdMovesPage: Boolean(selectedId),
    });
  }

  function applyCompletedPageResult(result) {
    const items = Array.isArray(result.pageItems) ? result.pageItems : [];
    const totalPages = Number(result.totalPages) || 1;
    state.completedPage = Number(result.currentPage) || 1;
    state.completedPageSize = normalizeTablePageSize(result.pageSize);
    setSelected("completed", result.selectedId);
    const selectedId = reconcileSelectedTask("completed", items);
    patchTableRows("completedBody", items, item => item.id, item => taskRenderService().completedRow(item, selectedId));
    byId("completedTotal").textContent = translateUiText(`\u5171 ${Number(result.totalCount) || 0} \u9879`);
    byId("completedPageNow").textContent = String(state.completedPage);
    byId("completedTotalPages").textContent = String(totalPages);
    byId("completedPageSize").value = String(state.completedPageSize);
    syncCustomSelectForSelect(byId("completedPageSize"));
    byId("completedPrevPage").disabled = state.completedPage <= 1;
    byId("completedNextPage").disabled = state.completedPage >= totalPages;
    renderCompletedDetail();
    if (typeof dependencies.renderStatus === "function") dependencies.renderStatus();
  }

  function selectCompleted(id) {
    setSelected("completed", id);
    renderCompleted();
  }

  function setCompletedPage(delta) {
    state.completedPage += Number(delta) || 0;
    setSelected("completed", "");
    renderCompleted();
  }

  function setCompletedPageSize(value) {
    state.completedPageSize = normalizeTablePageSize(value);
    state.completedPage = 1;
    setSelected("completed", "");
    localStorage.setItem("webui_completed_page_size", String(state.completedPageSize));
    renderCompleted();
  }

  function renderCompletedDetail() {
    const item = selectedTaskItem("completed", currentState().completed_items || []);
    setHtmlIfChanged("completedDetail", taskRenderService().completedDetailHtml(item));
  }

  function renderFailed() {
    const items = Array.isArray(currentState().failed_items) ? currentState().failed_items : [];
    const selectedId = selected("failed");
    submitListPageRequest("failed", {
      items,
      page: state.failedPage,
      pageSize: state.failedPageSize,
      selectedId,
      selectFirst: true,
      selectedIdMovesPage: Boolean(selectedId),
    });
  }

  function applyFailedPageResult(result) {
    const items = Array.isArray(result.pageItems) ? result.pageItems : [];
    const totalPages = Number(result.totalPages) || 1;
    state.failedPage = Number(result.currentPage) || 1;
    state.failedPageSize = normalizeTablePageSize(result.pageSize);
    setSelected("failed", result.selectedId);
    const selectedId = reconcileSelectedTask("failed", items);
    patchTableRows("failedBody", items, item => item.id, item => taskRenderService().failedRow(item, selectedId));
    byId("failedTotal").textContent = translateUiText(`\u5171 ${Number(result.totalCount) || 0} \u9879`);
    byId("failedPageNow").textContent = String(state.failedPage);
    byId("failedTotalPages").textContent = String(totalPages);
    byId("failedPageSize").value = String(state.failedPageSize);
    syncCustomSelectForSelect(byId("failedPageSize"));
    byId("failedPrevPage").disabled = state.failedPage <= 1;
    byId("failedNextPage").disabled = state.failedPage >= totalPages;
    renderFailedDetail();
  }

  function selectFailed(id) {
    setSelected("failed", id);
    renderFailed();
  }

  function setFailedPage(delta) {
    state.failedPage += Number(delta) || 0;
    setSelected("failed", "");
    renderFailed();
  }

  function setFailedPageSize(value) {
    state.failedPageSize = normalizeTablePageSize(value);
    state.failedPage = 1;
    setSelected("failed", "");
    localStorage.setItem("webui_failed_page_size", String(state.failedPageSize));
    renderFailed();
  }

  function renderFailedDetail() {
    const item = selectedTaskItem("failed", currentState().failed_items || []);
    setHtmlIfChanged("failedDetail", taskRenderService().failedDetailHtml(item));
    setHtmlIfChanged("failedSolutions", taskRenderService().failedSolutionsHtml(item));
  }

  function navigationOrder() {
    return Array.from(document.querySelectorAll("#queueBody tr[data-id]"))
      .map(row => String((row.dataset && row.dataset.id) || ""))
      .filter(Boolean);
  }

  function dispose() {
    if (state.disposed) return;
    state.disposed = true;
    state.generation += 1;
    PAGED_LISTS.forEach(pageKey => {
      state.sequences[pageKey] = (Number(state.sequences[pageKey]) || 0) + 1;
    });
    clearListPageFallbacks();
    closeListPageWorker();
    state.rowSignatures = Object.create(null);
    state.htmlSignatures = Object.create(null);
    dependencies = Object.freeze({});
  }

  window.UcpListPages = Object.freeze({
    configure,
    renderQueue,
    renderActive,
    renderCompleted,
    renderFailed,
    selectActive,
    selectCompleted,
    selectFailed,
    setQueuePage,
    setQueuePageSize,
    setQueueDensity,
    restoreQueueControls,
    setCompletedPage,
    setCompletedPageSize,
    setFailedPage,
    setFailedPageSize,
    updateDownloadOptions,
    renderActiveDetail,
    renderCompletedDetail,
    renderFailedDetail,
    navigationOrder,
    dispose,
  });
})();
