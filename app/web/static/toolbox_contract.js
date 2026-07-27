(function () {
  "use strict";

  const ACTIONS = Object.freeze({
    validate: "tool_validate", start: "tool_start", cancel: "tool_cancel",
    openResult: "tool_open_result", clearHistory: "tool_clear_history",
  });
  const ALIASES = Object.freeze({
    validate: ["validate", "tool_validate"], start: ["start", "run", "tool_start"],
    cancel: ["cancel", "tool_cancel"], openResult: ["openResult", "open_result", "tool_open_result"],
    clearHistory: ["clearHistory", "clear_history", "tool_clear_history"],
  });
  const PROJECTION_KEYS = Object.freeze(["toolbox_display_projection", "toolbox_projection", "toolbox_display"]);
  const BATCH_KEYS = Object.freeze(["toolbox_display_batch", "toolbox_projection_batch", "toolbox_batch"]);
  const STATUS = Object.freeze({
    pending: "queued", queued: "queued", validating: "validating", validated: "ready", valid: "ready", ready: "ready",
    starting: "starting", started: "running", running: "running", processing: "running", cancelling: "cancelling",
    canceled: "cancelled", cancelled: "cancelled", success: "completed", succeeded: "completed", complete: "completed",
    completed: "completed", error: "failed", failed: "failed",
  });

  function record(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
  function first(...values) { return values.find(value => value !== undefined && value !== null); }
  function merge(base, incoming) {
    const out = { ...record(base), ...record(incoming) };
    ["form", "validation", "actions", "action_payloads"].forEach(key => {
      if (record(base)[key] && record(incoming)[key]) out[key] = { ...record(base)[key], ...record(incoming)[key] };
    });
    return out;
  }
  function options(raw) {
    if (Array.isArray(raw)) return raw.map(option => {
      if (option && typeof option === "object") {
        const value = first(option.value, option.id, option.key, option.name, "");
        return { value, label: String(first(option.label, option.title, option.name, value, "")), disabled: !!option.disabled };
      }
      return { value: option, label: String(option ?? ""), disabled: false };
    });
    if (raw && typeof raw === "object") return Object.entries(raw).map(([value, label]) => ({ value, label: String(label), disabled: false }));
    return [];
  }
  function parameterRows(raw) {
    for (const candidate of [raw.parameters, raw.params, raw.fields]) {
      if (Array.isArray(candidate)) return candidate;
      if (candidate && typeof candidate === "object") return Object.entries(candidate).map(([name, value]) => ({ ...record(value), name }));
    }
    const schema = record(raw.parameter_schema || raw.input_schema || raw.schema);
    const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : []);
    return Object.entries(record(schema.properties)).map(([name, value]) => ({ ...record(value), name, required: required.has(name) || !!record(value).required }));
  }
  function normalizeParameter(rawParameter, index) {
    const raw = record(rawParameter);
    const name = String(first(raw.name, raw.key, raw.id, `parameter_${index + 1}`));
    const choices = options(first(raw.options, raw.choices, raw.enum));
    const requested = String(first(raw.control, raw.widget, raw.type, "text")).toLowerCase();
    let type = requested;
    if (choices.length || ["choice", "select", "enum"].includes(type)) type = "select";
    else if (["bool", "boolean", "checkbox", "switch"].includes(type)) type = "boolean";
    else if (["int", "integer", "spin"].includes(type)) type = "integer";
    else if (["float", "double", "decimal", "number"].includes(type)) type = "number";
    else if (["textarea", "multiline", "text_area", "code"].includes(type)) type = "textarea";
    else type = "text";
    return {
      name, label: String(first(raw.label, raw.title, raw.display_name, name)),
      description: String(first(raw.description, raw.help_text, raw.help, raw.hint, "")), placeholder: String(first(raw.placeholder, "")),
      type, required: !!raw.required, readOnly: raw.enabled === false || !!first(raw.read_only, raw.readonly, raw.disabled, false),
      secret: !!raw.secret || ["password", "secret"].includes(requested), defaultValue: first(raw.default, raw.default_value, raw.value, type === "boolean" ? false : ""),
      min: first(raw.min, raw.minimum), max: first(raw.max, raw.maximum), step: first(raw.step, type === "integer" ? 1 : undefined),
      pattern: String(first(raw.pattern, "")), rows: Math.max(2, Math.min(8, Number(raw.rows) || 3)), options: choices,
    };
  }
  function normalizeToolDefinition(rawTool) {
    const raw = record(rawTool);
    return {
      ...raw, id: String(first(raw.id, raw.tool_id, raw.key, "")), title: String(first(raw.title, raw.label, raw.name, "")),
      summary: String(first(raw.summary, raw.description, "")), inputExample: String(first(raw.input_example, raw.inputExample, "")),
      outputExample: String(first(raw.output_example, raw.outputExample, "")), iconFile: String(first(raw.icon_file, raw.iconFile, "nav_toolbox.png")),
      parameters: parameterRows(raw).map(normalizeParameter), actions: record(raw.actions), raw,
    };
  }
  function batchRows(batch) {
    const source = record(batch); const rows = [];
    [source.projections, source.updates].forEach(candidate => { if (Array.isArray(candidate)) rows.push(...candidate.filter(value => value && typeof value === "object")); });
    if (source.projection && typeof source.projection === "object") rows.push(source.projection);
    if (!rows.length && (source.tool_id || source.id)) rows.push(source);
    return rows;
  }
  function reduceProjectionCache(previous, snapshot) {
    const source = record(snapshot); const cache = Object.fromEntries(Object.entries(record(previous)).map(([id, value]) => [id, merge({}, value)]));
    const apply = candidate => {
      const projection = record(candidate); const id = String(first(projection.tool_id, projection.id, projection.selected_tool_id, source.toolbox_selected_tool_id, ""));
      if (!id) return ""; cache[id] = merge(cache[id], projection); cache[id].tool_id = id; return id;
    };
    PROJECTION_KEYS.forEach(key => { if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) apply(source[key]); });
    BATCH_KEYS.forEach(key => {
      const batch = source[key]; const sourceBatch = record(batch); const touched = (Array.isArray(batch) ? batch : batchRows(sourceBatch)).map(apply).filter(Boolean);
      const target = String(first(sourceBatch.selected_tool_id, touched[0], source.toolbox_selected_tool_id, Object.keys(cache).length === 1 ? Object.keys(cache)[0] : ""));
      if (target && Array.isArray(sourceBatch.history)) cache[target] = merge(cache[target], { tool_id: target, history: sourceBatch.history });
    });
    return cache;
  }
  function projectionFor(snapshot, toolId) { const cache = reduceProjectionCache({}, snapshot); return cache[String(toolId)] || (Object.keys(cache).length === 1 ? cache[Object.keys(cache)[0]] : {}); }
  function projectionFields(projection) {
    const source = record(projection); const form = record(source.form);
    for (const value of [form.fields, source.parameter_fields, source.parameters]) {
      if (Array.isArray(value)) return value;
      if (value && typeof value === "object") return Object.entries(value).map(([name, row]) => ({ ...record(row), name }));
    }
    return [];
  }
  function projectionValues(projection) { const source = record(projection); return { ...record(source.parameter_values), ...record(source.values), ...record(record(source.form).values) }; }
  function toolForSnapshot(snapshot, toolId, rawOverride = null) {
    const source = record(snapshot); const rows = Array.isArray(source.toolbox_items) ? source.toolbox_items : record(source.toolbox).items;
    const raw = rawOverride || (Array.isArray(rows) && rows.find(row => String(first(record(row).id, record(row).tool_id, "")) === String(toolId || ""))) || { id: toolId };
    const tool = normalizeToolDefinition(raw); const projection = projectionFor(source, tool.id || toolId); const fields = projectionFields(projection);
    if (fields.length) tool.parameters = fields.map(normalizeParameter);
    tool.initialValues = { ...Object.fromEntries(tool.parameters.map(parameter => [parameter.name, parameter.defaultValue])), ...projectionValues(projection) };
    return tool;
  }
  function blank(value) { return value === undefined || value === null || (typeof value === "string" && !value.trim()); }
  function normalizedValue(parameter, value) {
    if (parameter.type === "boolean") return !!value;
    if (parameter.type === "integer") { const parsed = Number.parseInt(value, 10); return Number.isFinite(parsed) ? parsed : value; }
    if (parameter.type === "number") { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : value; }
    return typeof value === "string" ? value.trim() : value;
  }
  function validateParameters(tool, rawValues) {
    const errors = {}; const values = {};
    tool.parameters.forEach(parameter => {
      const value = normalizedValue(parameter, record(rawValues)[parameter.name]); values[parameter.name] = value;
      if (parameter.required && blank(value)) errors[parameter.name] = "required";
      else if (parameter.type === "integer" || parameter.type === "number") {
        if (!Number.isFinite(value)) errors[parameter.name] = "invalid number";
        else if (parameter.min !== undefined && value < Number(parameter.min)) errors[parameter.name] = "below minimum";
        else if (parameter.max !== undefined && value > Number(parameter.max)) errors[parameter.name] = "above maximum";
      } else if (parameter.type === "select" && !blank(value) && !parameter.options.some(option => String(option.value) === String(value))) errors[parameter.name] = "invalid option";
      else if (parameter.pattern && typeof value === "string" && !(new RegExp(parameter.pattern).test(value))) errors[parameter.name] = "invalid format";
    });
    return { valid: !Object.keys(errors).length, errors, values };
  }
  function hasModernContract(tool, snapshot) {
    const source = record(snapshot); const contract = record(source.toolbox_contract); return tool.parameters.length > 0 || Object.keys(record(tool.actions)).length > 0 || Object.keys(record(contract.actions)).length > 0 || !!projectionFor(source, tool.id).form;
  }
  function resolveActionName(kind, tool, snapshot) {
    const names = ALIASES[kind] || []; const configured = record(record(record(snapshot).toolbox_contract).actions);
    for (const map of [record(tool.actions), configured]) for (const name of names) if (typeof map[name] === "string") return map[name];
    return hasModernContract(tool, snapshot) ? ACTIONS[kind] : (kind === "start" ? "run_tool" : ACTIONS[kind]);
  }
  function buildActionPayload(kind, tool, values, context = {}) {
    const payload = { tool_id: tool.id }; const source = record(context);
    if (["validate", "start"].includes(kind)) payload.parameters = { ...record(values) };
    if (kind === "cancel" && first(source.runId, source.run_id, source.execution_id)) payload.run_id = String(first(source.runId, source.run_id, source.execution_id));
    if (kind === "openResult" && first(source.resultId, source.result_id, record(source.result).id, record(source.result).result_id)) payload.result_id = String(first(source.resultId, source.result_id, record(source.result).id, record(source.result).result_id));
    return payload;
  }
  function actionEnabled(projection, action, fallback = false) {
    const source = record(projection); const actions = source.actions;
    if (actions && typeof actions === "object" && !Array.isArray(actions) && Object.prototype.hasOwnProperty.call(actions, action)) return typeof actions[action] === "object" ? actions[action].enabled !== false : !!actions[action];
    if (Array.isArray(actions)) return actions.includes(action); const short = action.replace(/^tool_/, ""); return Object.prototype.hasOwnProperty.call(source, `can_${short}`) ? !!source[`can_${short}`] : (Object.prototype.hasOwnProperty.call(source, `${short}_enabled`) ? !!source[`${short}_enabled`] : fallback);
  }
  function display(value) { if (value === undefined || value === null) return ""; if (["string", "number", "boolean"].includes(typeof value)) return String(value); return display(record(value).display_text || record(value).text); }
  function resultDisplayLines(result) { const source = record(result); const lines = []; const add = value => { if (value && !lines.includes(value)) lines.push(value); }; add(display(source.display_text)); add(display(source.summary)); (source.rows || source.detail_rows || []).forEach(row => { const item = record(row); const label = display(item.label || item.title); const value = display(item.value || item.display_value); add(label && value ? `${label}: ${value}` : display(row)); }); return lines; }
  function normalizeStatus(value) { const key = String(value || "idle").toLowerCase(); return STATUS[key] || key; }
  function normalizeProgress(source) { const value = record(source); const raw = first(value.progress, value.percent, 0); const nested = record(raw); const amount = Number(first(nested.value, nested.percent, raw, 0)); return { progress: Number.isFinite(amount) ? Math.max(0, Math.min(100, amount)) : 0, progressText: String(first(nested.text, nested.label, value.progress_text, value.progressText, "")), progressIndeterminate: !!first(nested.indeterminate, value.progress_indeterminate, value.progressIndeterminate, false) }; }
  function executionFor(snapshot, toolId) {
    const projection = projectionFor(snapshot, toolId); const direct = record(record(snapshot).toolbox_execution); const source = String(first(direct.tool_id, direct.id, toolId, "")) === String(toolId || "") ? merge(projection, direct) : projection; const progress = normalizeProgress(source); const validation = record(source.validation); const result = record(source.result);
    return { status: normalizeStatus(first(source.state, source.status, source.phase, "idle")), statusText: String(first(source.status_text, source.statusText, "")), runId: String(first(source.run_id, source.runId, source.execution_id, "")), result, resultPath: String(first(source.result_path, source.resultPath, result.path, result.file_path, "")), message: String(first(source.message, "")), error: String(first(source.error, source.error_message, "")), validationMessage: String(first(validation.message, source.validation_message, "")), validationErrors: record(first(validation.errors, source.validation_errors, source.errors, {})), canCancel: actionEnabled(source, "tool_cancel", false), canOpenResult: actionEnabled(source, "tool_open_result", !!Object.keys(result).length), ...progress };
  }
  function historyFor(snapshot, toolId) { const projection = projectionFor(snapshot, toolId); const rows = Array.isArray(projection.history) ? projection.history : (Array.isArray(record(snapshot).toolbox_recent_items) ? record(snapshot).toolbox_recent_items : []); return rows.map(row => { const source = record(row); return { ...source, historyId: String(first(source.id, source.history_id, source.result_id, "")), title: String(first(source.title, source.tool_title, "")), timestamp: String(first(source.finished_at, source.last_used, source.time_display, "")), status: normalizeStatus(first(source.state, source.status, "idle")), statusText: String(first(source.status_text, "")), canOpenResult: actionEnabled(source, "tool_open_result", !!first(source.result_id, source.path, false)) }; }); }
  function shouldRender(sections) { const values = sections instanceof Set ? sections : new Set(sections || []); return ["toolbox_items", "toolbox_display_projection", "toolbox_display_batch", "toolbox_execution", "toolbox_recent_items", "toolbox_selected_tool_id"].some(key => values.has(key)); }

  window.UcpToolboxContract = Object.freeze({ normalizeToolDefinition, reduceProjectionCache, projectionFor, toolForSnapshot, validateParameters, resolveActionName, buildActionPayload, actionEnabled, executionFor, historyFor, resultDisplayLines, shouldRender, hasModernContract });
})();
