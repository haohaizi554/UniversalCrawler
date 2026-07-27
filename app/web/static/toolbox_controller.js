(function () {
  "use strict";

  const contract = window.UcpToolboxContract;
  const view = window.UcpToolboxView;
  if (!contract || !view) throw new Error("Toolbox contract and view must load before the controller");

  let dependencies = Object.freeze({});
  const state = {
    configured: false, disposed: true, generation: 0, actionSequence: 0, snapshot: {}, projectionCache: {},
    selectedToolId: "", valuesByTool: Object.create(null), errorsByTool: Object.create(null), touched: new Set(), dirty: new Set(),
    pending: null, actionMessage: "", suspended: false, pagehideHandler: null, pageshowHandler: null,
  };

  function record(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
  function first(...values) { return values.find(value => value !== undefined && value !== null); }
  function currentState() { return typeof dependencies.getState === "function" ? record(dependencies.getState()) : record(state.snapshot); }
  function selectedId() { return typeof dependencies.getSelectedToolId === "function" ? String(dependencies.getSelectedToolId() || "") : state.selectedToolId; }
  function setSelectedId(value) { state.selectedToolId = String(value || ""); if (typeof dependencies.setSelectedToolId === "function") dependencies.setSelectedToolId(state.selectedToolId); }
  function translate(value) {
    const translator = dependencies.translate || dependencies.translateText || dependencies.t;
    return typeof translator === "function" ? translator(value) : String(value ?? "");
  }
  function requestAction(action, payload) { return dependencies.requestAction(action, payload); }
  function toolItems(snapshot = currentState()) {
    const rows = Array.isArray(snapshot.toolbox_items) ? snapshot.toolbox_items : record(snapshot.toolbox).items;
    return Array.isArray(rows) ? rows.map(contract.normalizeToolDefinition) : [];
  }
  function projection(toolId, snapshot = currentState()) { return state.projectionCache[String(toolId)] || contract.projectionFor(snapshot, toolId); }
  function selectedTool(snapshot = currentState()) {
    const id = selectedId(); const item = toolItems(snapshot).find(tool => tool.id === id) || toolItems(snapshot)[0];
    return item ? contract.toolForSnapshot({ ...snapshot, toolbox_display_projection: projection(item.id, snapshot) }, item.id, item.raw) : null;
  }
  function ingest(snapshot = null) {
    if (snapshot) state.snapshot = record(snapshot);
    const source = currentState(); state.projectionCache = contract.reduceProjectionCache(state.projectionCache, source);
    return state.projectionCache;
  }
  function resetSessionState() {
    state.snapshot = {}; state.projectionCache = {}; state.selectedToolId = "";
    state.valuesByTool = Object.create(null); state.errorsByTool = Object.create(null);
    state.touched = new Set(); state.dirty = new Set(); state.pending = null; state.actionMessage = "";
  }
  function detachLifecycleHandlers() {
    if (typeof window.removeEventListener !== "function") return;
    if (state.pagehideHandler) window.removeEventListener("pagehide", state.pagehideHandler);
    if (state.pageshowHandler) window.removeEventListener("pageshow", state.pageshowHandler);
    state.pagehideHandler = null; state.pageshowHandler = null;
  }
  function suspend() {
    if (state.disposed || !state.configured) return false;
    state.disposed = true; state.suspended = true; state.generation += 1; state.actionSequence += 1; state.pending = null;
    return true;
  }
  function resume() {
    if (!state.suspended || !state.configured) return false;
    state.disposed = false; state.suspended = false; state.generation += 1; render();
    return true;
  }
  function configure(options = {}) {
    dispose(); dependencies = Object.freeze({ ...record(options) }); state.configured = true; state.disposed = false; state.suspended = false; state.generation += 1;
    if (typeof window.addEventListener === "function") {
      state.pagehideHandler = event => { if (event && event.persisted) suspend(); else dispose(); };
      state.pageshowHandler = event => { if (event && event.persisted) resume(); };
      window.addEventListener("pagehide", state.pagehideHandler);
      window.addEventListener("pageshow", state.pageshowHandler);
    }
    return window.UcpToolboxController;
  }
  function viewContext() { return Object.freeze({ translate, language: dependencies.language || "", enhanceSelects: dependencies.enhanceSelects, select, updateParameter, validate, start, cancel, openResult, clearHistory }); }
  function parameterValues(tool, execution) {
    const current = state.valuesByTool[tool.id];
    if (current) return current;
    const values = { ...tool.initialValues };
    state.valuesByTool[tool.id] = values;
    return values;
  }
  function effectiveExecution(execution, toolId) {
    if (!state.pending || state.pending.toolId !== toolId) return execution;
    const status = { validate: "validating", start: "starting", cancel: "cancelling" }[state.pending.kind] || execution.status;
    return { ...execution, status };
  }
  function renderModel(tool, snapshot) {
    const rawExecution = contract.executionFor({ ...snapshot, toolbox_display_projection: projection(tool.id, snapshot) }, tool.id);
    const execution = effectiveExecution(rawExecution, tool.id); const currentProjection = projection(tool.id, snapshot); const values = parameterValues(tool, execution);
    const validation = contract.validateParameters(tool, values); const busy = !!state.pending || ["validating", "starting", "queued", "running", "cancelling"].includes(execution.status);
    const history = contract.historyFor({ ...snapshot, toolbox_display_projection: currentProjection }, tool.id);
    const lines = contract.resultDisplayLines(execution.result); const errors = state.errorsByTool[tool.id] || execution.validationErrors || {};
    const validationText = Object.keys(errors).length ? "请修正标记的参数" : (state.dirty.has(tool.id) ? "参数已更改，请重新验证" : execution.validationMessage);
    return {
      execution, history, errors, actionMessage: state.actionMessage, validationText, resultText: lines.length ? lines.map(translate).join("\n") : (execution.resultPath || "暂无执行结果"), pending: state.pending,
      validateEnabled: !busy && contract.actionEnabled(currentProjection, "tool_validate", true),
      startEnabled: !busy && validation.valid && contract.actionEnabled(currentProjection, "tool_start", true),
      cancelEnabled: !state.pending && contract.actionEnabled(currentProjection, "tool_cancel", execution.canCancel),
      openEnabled: !state.pending && contract.actionEnabled(currentProjection, "tool_open_result", execution.canOpenResult),
      clearEnabled: !state.pending && history.length > 0 && contract.actionEnabled(currentProjection, "tool_clear_history", true),
    };
  }
  function renderDetail() {
    if (state.disposed) return false; const snapshot = currentState(); ingest(snapshot); const tool = selectedTool(snapshot);
    if (!tool) return view.renderEmpty(viewContext());
    const modern = contract.hasModernContract(tool, snapshot); view.renderDetail(tool, parameterValues(tool, contract.executionFor(snapshot, tool.id)), modern, viewContext()); view.patchDetail(renderModel(tool, snapshot), viewContext()); return true;
  }
  function render() {
    if (state.disposed) return false; const snapshot = currentState(); ingest(snapshot); const items = toolItems(snapshot); let id = selectedId();
    if (!items.some(tool => tool.id === id)) { id = items.length ? items[0].id : ""; setSelectedId(id); }
    view.renderCards(items, id, viewContext()); return renderDetail();
  }
  function select(toolId) {
    if (state.disposed || !toolItems().some(tool => tool.id === String(toolId))) return false;
    setSelectedId(toolId); state.actionMessage = ""; render(); return true;
  }
  function updateParameter(name, value) {
    const tool = selectedTool(); if (!tool) return false; const parameter = tool.parameters.find(row => row.name === String(name || ""));
    if (!parameter || parameter.readOnly) return false; const values = parameterValues(tool); values[parameter.name] = parameter.type === "boolean" ? !!value : value;
    const errors = { ...(state.errorsByTool[tool.id] || {}) }; delete errors[parameter.name]; state.errorsByTool[tool.id] = errors; state.dirty.add(tool.id); state.actionMessage = ""; renderDetail(); return true;
  }
  function actionErrors(result) { const source = record(result); return record(first(source.validation_errors, source.errors, record(source.data).validation_errors, record(source.data).errors, {})); }
  async function dispatch(kind, tool, values, context = {}) {
    const snapshot = currentState(); const action = contract.resolveActionName(kind, tool, snapshot); if (!action) return { status: "error", message: "操作提交失败" };
    const payload = contract.buildActionPayload(kind, tool, values, context); const generation = state.generation; const sequence = ++state.actionSequence;
    state.pending = { kind, toolId: tool.id, generation, sequence }; state.actionMessage = ""; renderDetail();
    try {
      const result = await requestAction(action, payload);
      if (state.disposed || state.generation !== generation || state.actionSequence !== sequence) return result;
      const errors = actionErrors(result); if (Object.keys(errors).length) state.errorsByTool[tool.id] = errors;
      if (!result || result === false || (result.status && result.status !== "ok")) state.actionMessage = String(first(record(result).message, "操作提交失败"));
      return result;
    } catch (error) {
      if (!state.disposed && state.generation === generation && state.actionSequence === sequence) state.actionMessage = String(first(error && error.message, error, "操作提交失败"));
      return { status: "error", message: state.actionMessage };
    } finally {
      if (!state.disposed && state.generation === generation && state.actionSequence === sequence) { state.pending = null; renderDetail(); }
    }
  }
  function perform(kind) {
    const tool = selectedTool(); if (!tool || state.pending) return Promise.resolve({ status: "error" }); const values = parameterValues(tool); const validation = contract.validateParameters(tool, values);
    state.errorsByTool[tool.id] = validation.errors; state.touched.add(tool.id); state.dirty.delete(tool.id); renderDetail(); if (!validation.valid && ["validate", "start"].includes(kind)) return Promise.resolve({ status: "invalid", errors: validation.errors });
    const execution = contract.executionFor(currentState(), tool.id); const context = kind === "cancel" ? execution : (kind === "openResult" ? execution : projection(tool.id)); return dispatch(kind, tool, validation.values, context);
  }
  function validate() { return perform("validate"); }
  function start() { return perform("start"); }
  function cancel() { return perform("cancel"); }
  function openResult(historyId = "") { if (!historyId) return perform("openResult"); const tool = selectedTool(); const row = tool && contract.historyFor(currentState(), tool.id).find(item => item.historyId === String(historyId)); return tool && row ? dispatch("openResult", tool, {}, row) : Promise.resolve({ status: "error" }); }
  function clearHistory() { return perform("clearHistory"); }
  function shouldRender(sections) { return contract.shouldRender(sections); }
  function dispose() {
    detachLifecycleHandlers(); state.disposed = true; state.configured = false; state.suspended = false;
    state.generation += 1; state.actionSequence += 1; resetSessionState(); dependencies = Object.freeze({});
  }

  window.UcpToolboxController = Object.freeze({ configure, ingest, render, renderDetail, select, updateParameter, validate, start, cancel, openResult, clearHistory, shouldRender, dispose, contract });
})();
