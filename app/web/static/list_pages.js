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
    currentRequests: { queue: null, completed: null, failed: null },
    fallbackTimers: { queue: null, completed: null, failed: null },
    rowSignatures: Object.create(null),
    htmlSignatures: Object.create(null),
    diagnosticsOperation: 0,
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
    state.currentRequests = { queue: null, completed: null, failed: null };
    state.fallbackTimers = { queue: null, completed: null, failed: null };
    state.rowSignatures = Object.create(null);
    state.htmlSignatures = Object.create(null);
    state.diagnosticsOperation = 0;
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

  function setSelected(domain, id, options = {}) {
    if (typeof dependencies.setSelection === "function") {
      dependencies.setSelection(domain, String(id || ""), { activate: options.activate === true });
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

  function syncSelectedTableRow(tbodyId, selectedId) {
    const tbody = byId(tbodyId);
    if (!tbody) return false;
    let found = false;
    Array.from(tbody.querySelectorAll("tr[data-id]")).forEach(row => {
      const selected = String(row.dataset.id || "") === String(selectedId || "");
      row.classList.toggle("selected", selected);
      found = found || selected;
    });
    return found;
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
      // 浏览器销毁 Worker 只能尽力而为。
    }
  }

  function scheduleCurrentListPageFallbacks() {
    PAGED_LISTS.forEach(pageKey => {
      const request = state.currentRequests[pageKey];
      if (!request || Number(request.sequence) !== Number(state.sequences[pageKey] || 0)) return;
      scheduleListPageFallback(request);
    });
  }

  function ensureListPageWorker() {
    if (!state.workerAvailable || state.disposed) return null;
    if (state.worker) return state.worker;
    const generation = state.generation;
    try {
      const worker = new Worker("/static/list_page_worker.js?v=20260708-list-page-worker");
      state.worker = worker;
      worker.onmessage = event => applyListPageResult(event.data || {}, worker, generation);
      worker.onerror = event => {
        if (state.disposed || generation !== state.generation || state.worker !== worker) return;
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        state.workerAvailable = false;
        closeListPageWorker(worker);
        scheduleCurrentListPageFallbacks();
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
    state.currentRequests[pageKey] = request;
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
      (worker && state.worker !== worker) ||
      !result ||
      result.type !== "page"
    ) return;
    const pageKey = String(result.pageKey || "");
    if (!PAGED_LISTS.includes(pageKey)) return;
    // Worker 与同步回退可能乱序返回，只接收最新 sequence，避免旧分页覆盖当前选择状态。
    if (Number(result.sequence) !== Number(state.sequences[pageKey] || 0)) return;
    clearListPageFallback(pageKey);
    state.currentRequests[pageKey] = null;
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
      max_retries: Number(settings.max_retries ?? 3),
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

  function renderCompleted(options = {}) {
    const items = Array.isArray(currentState().completed_items) ? currentState().completed_items : [];
    if (options.cleanupPlaybackPositions !== false) cleanupPlaybackPositions(items);
    const selectedId = selected("completed");
    const request = {
      items,
      page: state.completedPage,
      pageSize: state.completedPageSize,
      selectedId,
      selectFirst: true,
      selectedIdMovesPage: Boolean(selectedId),
    };
    if (options.immediate === true) {
      // 删除事务先同步投影可见页，避免 Worker 繁忙时状态已切换但表格高亮仍短暂滞后。
      applyCompletedPageResult(buildListPageResultSync({
        type: "page",
        pageKey: "completed",
        sequence: 0,
        ...request,
      }));
      request.page = state.completedPage;
      request.selectedId = selected("completed");
    }
    submitListPageRequest("completed", request);
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
    setSelected("completed", id, { activate: true });
    renderCompleted();
  }

  // 手动翻页或调整分页大小时清空旧选择，否则 selectedIdMovesPage 会把页码拉回旧条目。
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

  function optimisticallyMutateCompleted(action, payload = {}) {
    if (action !== "delete_item") return null;
    const source = currentState();
    const previousItems = Array.isArray(source.completed_items) ? source.completed_items : [];
    const doomedId = String(payload.id || payload.video_id || "");
    const doomedIndex = previousItems.findIndex(item => String(item.id || "") === doomedId);
    if (doomedIndex < 0) return null;

    const nextItems = previousItems.filter((_item, index) => index !== doomedIndex);
    const nextIndex = Math.min(doomedIndex, nextItems.length - 1);
    const nextSelected = nextIndex >= 0 ? String(nextItems[nextIndex].id || "") : "";
    const previousStatus = source.app_status;
    const previousSelected = selected("completed");
    const previousActiveSelection = selected("queue");
    const previousCount = Number((previousStatus || {}).completed_count);
    source.completed_items = nextItems;
    source.app_status = {
      ...(previousStatus || {}),
      completed_count: Math.max(0, Number.isFinite(previousCount) ? previousCount - 1 : nextItems.length),
    };
    setSelected("completed", nextSelected, { activate: true });
    renderCompleted({ cleanupPlaybackPositions: false, immediate: true });
    if (typeof dependencies.renderStatus === "function") dependencies.renderStatus();
    return () => {
      source.completed_items = previousItems;
      source.app_status = previousStatus;
      setSelected("completed", previousSelected);
      setSelected("queue", previousActiveSelection);
      renderCompleted({ cleanupPlaybackPositions: false, immediate: true });
      if (typeof dependencies.renderStatus === "function") dependencies.renderStatus();
    };
  }

  function renderFailed(options = {}) {
    const items = Array.isArray(currentState().failed_items) ? currentState().failed_items : [];
    const selectedId = reconcileSelectedTask("failed", items);
    syncSelectedTableRow("failedBody", selectedId);
    renderFailedDetail();
    submitListPageRequest("failed", {
      items,
      page: state.failedPage,
      pageSize: state.failedPageSize,
      selectedId,
      selectFirst: true,
      selectedIdMovesPage: options.selectedIdMovesPage !== false && Boolean(selectedId),
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
    byId("failedClearAll").disabled = Number(result.totalCount) <= 0;
    renderFailedDetail();
  }

  function selectFailed(id) {
    setSelected("failed", id);
    const visible = syncSelectedTableRow("failedBody", id);
    renderFailedDetail();
    if (!visible) renderFailed();
  }

  // 手动翻页或调整分页大小时清空旧选择，否则 selectedIdMovesPage 会把页码拉回旧条目。
  function setFailedPage(delta) {
    state.failedPage += Number(delta) || 0;
    setSelected("failed", "");
    renderFailed({ selectedIdMovesPage: false });
  }

  function setFailedPageSize(value) {
    state.failedPageSize = normalizeTablePageSize(value);
    state.failedPage = 1;
    setSelected("failed", "");
    localStorage.setItem("webui_failed_page_size", String(state.failedPageSize));
    renderFailed({ selectedIdMovesPage: false });
  }

  function renderFailedDetail() {
    const item = selectedTaskItem("failed", currentState().failed_items || []);
    setHtmlIfChanged("failedDetail", taskRenderService().failedDetailHtml(item));
    setHtmlIfChanged("failedSolutions", taskRenderService().failedSolutionsHtml(item));
  }

  function optimisticallyMutateFailed(action, payload = {}) {
    const source = currentState();
    const previousItems = Array.isArray(source.failed_items) ? source.failed_items : [];
    const doomedId = String(payload.id || payload.video_id || "");
    const nextItems = action === "clear_failed_records"
      ? []
      : previousItems.filter(item => String(item.id || "") !== doomedId);
    if (nextItems.length === previousItems.length && action !== "clear_failed_records") return null;
    const previousStatus = source.app_status;
    const previousSelected = selected("failed");
    const removedCount = previousItems.length - nextItems.length;
    source.failed_items = nextItems;
    source.app_status = {
      ...(previousStatus || {}),
      failed_count: action === "clear_failed_records"
        ? 0
        : Math.max(0, Number((previousStatus || {}).failed_count) - removedCount),
    };
    if (action === "clear_failed_records" || previousSelected === doomedId) setSelected("failed", "");
    byId("failedClearAll").disabled = nextItems.length === 0;
    renderFailed({ selectedIdMovesPage: false });
    if (typeof dependencies.renderStatus === "function") dependencies.renderStatus();
    return () => {
      source.failed_items = previousItems;
      source.app_status = previousStatus;
      setSelected("failed", previousSelected);
      byId("failedClearAll").disabled = previousItems.length === 0;
      renderFailed({ selectedIdMovesPage: false });
      if (typeof dependencies.renderStatus === "function") dependencies.renderStatus();
    };
  }

  function isCurrentDiagnosticsOperation(generation, operation) {
    return !state.disposed && state.generation === generation && state.diagnosticsOperation === operation;
  }

  async function copyDiagnostics(id) {
    const generation = state.generation;
    const operation = ++state.diagnosticsOperation;
    try {
      const response = await requireDependency("request")("/api/frontend/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "copy_diagnostics", payload: { id } }),
      });
      if (!isCurrentDiagnosticsOperation(generation, operation)) return false;
      if (!response || !response.ok) throw new Error(`HTTP ${response ? response.status : "unknown"}`);
      const result = await response.json();
      if (!isCurrentDiagnosticsOperation(generation, operation)) return false;
      const text = String((result.data && result.data.text) || "");
      if (!text) {
        requireDependency("appendUiLog")("未找到 Trace ID");
        return false;
      }
      const copied = await requireDependency("writeClipboard")(text);
      if (!isCurrentDiagnosticsOperation(generation, operation)) return false;
      if (copied === false) throw new Error("clipboard unavailable");
      requireDependency("appendUiLog")("Trace ID 已复制");
      return true;
    } catch (error) {
      if (isCurrentDiagnosticsOperation(generation, operation)) {
        requireDependency("appendUiLog")("复制诊断信息失败", error && (error.message || String(error)), "❌ ");
      }
      return false;
    }
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
    state.diagnosticsOperation += 1;
    PAGED_LISTS.forEach(pageKey => {
      state.sequences[pageKey] = (Number(state.sequences[pageKey]) || 0) + 1;
      state.currentRequests[pageKey] = null;
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
    optimisticallyMutateCompleted,
    optimisticallyMutateFailed,
    copyDiagnostics,
    navigationOrder,
    dispose,
  });
})();
